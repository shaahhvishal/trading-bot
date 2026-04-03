"""
Live confluence strategy bot with Telegram alerts.

Connects to Binance WebSocket, aggregates 1m → 1H candles, runs the
confluence scoring system, and sends rich Telegram alerts with full
score breakdowns.

Features:
  - Downloads recent history on startup to warm up indicators
  - Sends score update every hour (configurable)
  - BUY/SELL alerts with full indicator breakdown
  - Periodic status with current score and key levels

Usage:
    python scripts/run_confluence.py
    python scripts/run_confluence.py --symbol BTC/USDT --entry 7 --exit 3
    python scripts/run_confluence.py --score-interval 4  # alert every 4H
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click
import numpy as np
import pandas as pd
import ta
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from alerts.telegram import TelegramAlerter
from data.downloader import download_ohlcv
from data.resample import resample_ohlcv
from live.data_feed import BinanceDataFeed
from strategies.confluence import ConfluenceStrategy


class ConfluenceBot:
    """Live confluence strategy bot with Telegram score reporting."""

    def __init__(
        self,
        symbol: str,
        strategy: ConfluenceStrategy,
        alerter: TelegramAlerter,
        score_interval: int = 1,
    ) -> None:
        self.symbol = symbol
        self.strategy = strategy
        self.alerter = alerter
        self.score_interval = score_interval  # hours between score updates

        self._feed: BinanceDataFeed | None = None
        self._running = False
        self._candle_count = 0
        self._in_trade = False
        self._entry_price: float | None = None
        self._entry_time: str | None = None

        # Historical data for indicator computation
        self._history_1h: pd.DataFrame | None = None

    async def start(self) -> None:
        """Initialize with history, then start live feed."""
        self._running = True

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Step 1: Download recent history for warmup
        await self._warmup()

        # Step 2: Send startup message with current score
        score, breakdown = self._current_score()
        startup_msg = self._format_status(score, breakdown, "BOT STARTED")
        await self.alerter.send(startup_msg)
        logger.info(f"Confluence bot started — Score: {score}/12")

        # Step 3: Start live data feed
        self._feed = BinanceDataFeed(
            symbols=[self.symbol],
            on_candle_1h=self._on_candle_1h,
        )

        try:
            await self._feed.start()
        except asyncio.CancelledError:
            logger.info("Feed cancelled")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._feed:
            await self._feed.stop()
        await self.alerter.send("🛑 Confluence bot stopped")
        logger.info("Confluence bot stopped")

    async def _warmup(self) -> None:
        """Download recent historical data and prepare the strategy."""
        logger.info("Downloading recent history for warmup...")

        # Need ~400 days of 1H data for 200 EMA on Daily to stabilize
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=450)

        data_1m = download_ohlcv(
            symbol=self.symbol,
            timeframe="1m",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            exchange_id="binanceus",
        )

        self._history_1h = resample_ohlcv(data_1m, "1h")
        logger.info(f"Warmup: {len(self._history_1h):,} hourly candles loaded")

        # Prepare strategy with full history
        self.strategy.prepare(self._history_1h)

        # Feed all historical candles through on_candle to build internal state
        for row in self._history_1h.itertuples(index=False):
            candle = dict(zip(self._history_1h.columns, row))
            self.strategy.on_candle(candle)

        # Check if strategy currently thinks we're in a trade
        self._in_trade = self.strategy._in_trade

    def _on_candle_1h(self, symbol: str, candle: dict) -> None:
        """Process each new 1H candle."""
        if symbol != self.symbol:
            return

        self._candle_count += 1

        # Append to history and re-prepare
        new_row = pd.DataFrame([candle])
        self._history_1h = pd.concat(
            [self._history_1h, new_row], ignore_index=True
        )

        # Re-prepare with updated data (needed for EMA/RSI arrays to include new candle)
        self.strategy.reset()
        self.strategy.prepare(self._history_1h)

        # Replay all candles to rebuild state
        for row in self._history_1h.itertuples(index=False):
            c = dict(zip(self._history_1h.columns, row))
            sig = self.strategy.on_candle(c)

        # The signal from the last candle is our current signal
        # But we need to get it properly — re-run just the last candle check
        self.strategy.reset()
        self.strategy.prepare(self._history_1h)
        last_signal = None
        for row in self._history_1h.itertuples(index=False):
            c = dict(zip(self._history_1h.columns, row))
            last_signal = self.strategy.on_candle(c)

        # Get score breakdown
        idx = self.strategy._candle_index - 1
        score, breakdown = self.strategy._compute_score(idx)
        price = candle["close"]
        ts = candle.get("timestamp", datetime.now(timezone.utc))

        logger.info(
            f"[{ts}] {symbol} ${price:,.2f} | "
            f"Score: {score}/12 | Signal: {last_signal.value} | "
            f"In trade: {self.strategy._in_trade}"
        )

        # Handle BUY signal
        if last_signal.value == "BUY" and not self._in_trade:
            self._in_trade = True
            self._entry_price = price
            self._entry_time = str(ts)
            msg = self._format_buy_alert(price, ts, score, breakdown)
            asyncio.get_event_loop().create_task(self.alerter.send(msg))

        # Handle SELL signal
        elif last_signal.value == "SELL" and self._in_trade:
            pnl_pct = ((price - self._entry_price) / self._entry_price * 100) if self._entry_price else 0
            msg = self._format_sell_alert(price, ts, score, breakdown, pnl_pct)
            asyncio.get_event_loop().create_task(self.alerter.send(msg))
            self._in_trade = False
            self._entry_price = None
            self._entry_time = None

        # Periodic score update
        elif self._candle_count % self.score_interval == 0:
            msg = self._format_status(score, breakdown, "HOURLY UPDATE")
            asyncio.get_event_loop().create_task(self.alerter.send(msg))

    def _current_score(self) -> tuple[int, dict[str, int]]:
        """Get the current confluence score."""
        idx = self.strategy._candle_index - 1
        if idx < self.strategy.warmup_period:
            return 0, {}
        return self.strategy._compute_score(idx)

    def _format_score_bar(self, score: int, max_score: int = 12) -> str:
        """Create a visual score bar."""
        filled = "█" * score
        empty = "░" * (max_score - score)
        return f"[{filled}{empty}] {score}/{max_score}"

    def _format_breakdown(self, breakdown: dict[str, int]) -> str:
        """Format indicator breakdown for Telegram."""
        labels = {
            "ema_trend": "EMA Trend",
            "fibonacci": "Fibonacci",
            "trendline": "Trendline",
            "rsi_divergence": "RSI Diverg.",
            "sr_retest": "S/R Retest",
            "htf_confluence": "HTF Conflu.",
        }
        lines = []
        for key, label in labels.items():
            val = breakdown.get(key, 0)
            dots = "●" * val + "○" * (2 - val)
            lines.append(f"  {dots} {label}")
        return "\n".join(lines)

    def _format_buy_alert(
        self, price: float, ts: object, score: int, breakdown: dict
    ) -> str:
        close_1h = self._history_1h["close"]
        ema50 = ta.trend.ema_indicator(close_1h, window=50).iloc[-1]
        ema200 = ta.trend.ema_indicator(close_1h, window=200).iloc[-1]

        return (
            f"🟢 <b>BUY SIGNAL — {self.symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {str(ts)[:19]} UTC\n"
            f"💰 ${price:,.2f}\n\n"
            f"📊 <b>Confluence: {self._format_score_bar(score)}</b>\n\n"
            f"{self._format_breakdown(breakdown)}\n\n"
            f"📈 Key Levels:\n"
            f"  50 EMA:  ${ema50:,.0f}\n"
            f"  200 EMA: ${ema200:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Entry threshold: ≥{self.strategy.entry_threshold} | "
            f"Exit threshold: ≤{self.strategy.exit_threshold}"
        )

    def _format_sell_alert(
        self, price: float, ts: object, score: int, breakdown: dict, pnl_pct: float
    ) -> str:
        emoji = "✅" if pnl_pct >= 0 else "❌"
        return (
            f"{emoji} <b>EXIT SIGNAL — {self.symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {str(ts)[:19]} UTC\n"
            f"💰 ${price:,.2f}\n"
            f"📉 P&L: {pnl_pct:+.2f}%\n"
            f"  Entry: ${self._entry_price:,.2f}\n\n"
            f"📊 <b>Confluence: {self._format_score_bar(score)}</b>\n\n"
            f"{self._format_breakdown(breakdown)}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Score dropped below exit threshold ({self.strategy.exit_threshold})"
        )

    def _format_status(
        self, score: int, breakdown: dict, title: str = "STATUS"
    ) -> str:
        price = self._history_1h["close"].iloc[-1]
        ts = self._history_1h["timestamp"].iloc[-1]

        close_1h = self._history_1h["close"]
        ema50 = ta.trend.ema_indicator(close_1h, window=50).iloc[-1]
        ema200 = ta.trend.ema_indicator(close_1h, window=200).iloc[-1]
        rsi = ta.momentum.rsi(close_1h, window=14).iloc[-1]

        position_str = "🟢 LONG" if self._in_trade else "⚪ FLAT"
        if self._in_trade and self._entry_price:
            unrealized = (price - self._entry_price) / self._entry_price * 100
            position_str += f" ({unrealized:+.2f}%)"

        needed = max(0, self.strategy.entry_threshold - score)
        threshold_str = f"Need {needed} more" if needed > 0 else "✅ ACTIVE"

        return (
            f"📊 <b>{title} — {self.symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {str(ts)[:19]} UTC\n"
            f"💰 ${price:,.2f} | RSI: {rsi:.1f}\n"
            f"📍 {position_str}\n\n"
            f"<b>Confluence: {self._format_score_bar(score)}</b>\n"
            f"  {threshold_str}\n\n"
            f"{self._format_breakdown(breakdown)}\n\n"
            f"📈 Key Levels:\n"
            f"  50 EMA:  ${ema50:,.0f} ({((price/ema50)-1)*100:+.1f}%)\n"
            f"  200 EMA: ${ema200:,.0f} ({((price/ema200)-1)*100:+.1f}%)"
        )


@click.command()
@click.option("--symbol", default="BTC/USDT", help="Trading pair")
@click.option("--entry", default=7, help="Entry score threshold (out of 12)")
@click.option("--exit", "exit_threshold", default=3, help="Exit score threshold")
@click.option("--score-interval", default=1, help="Hours between score updates")
def main(symbol: str, entry: int, exit_threshold: int, score_interval: int) -> None:
    """Start the confluence strategy Telegram bot."""
    strategy = ConfluenceStrategy(params={
        "entry_threshold": entry,
        "exit_threshold": exit_threshold,
    })

    alerter = TelegramAlerter.from_env()

    bot = ConfluenceBot(
        symbol=symbol,
        strategy=strategy,
        alerter=alerter,
        score_interval=score_interval,
    )

    logger.info(
        f"Confluence bot — {symbol} | "
        f"Entry>={entry} Exit<={exit_threshold} | "
        f"Score updates every {score_interval}H"
    )

    asyncio.run(bot.start())


if __name__ == "__main__":
    main()
