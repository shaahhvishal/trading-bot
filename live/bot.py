"""
Main trading bot: ties data feed → strategy → risk manager → executor → alerts.

The bot runs as an asyncio event loop:
  1. Binance WebSocket feeds 1m candles
  2. CandleAggregator builds 1h candles
  3. On each 1h close: run strategy → get signal
  4. Risk manager checks if trade is allowed
  5. Executor places paper order (or real order in Phase 4)
  6. Telegram alerts on every trade and risk event

Handles SIGINT/SIGTERM for clean shutdown (closes WebSocket, saves state).
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from alerts.telegram import TelegramAlerter
from live.data_feed import BinanceDataFeed
from live.executor import PaperExecutor
from live.risk_manager import RiskEvent, RiskLimits, RiskManager
from strategies.base import Signal, Strategy


class TradingBot:
    """Main trading bot that orchestrates all components."""

    def __init__(
        self,
        symbols: list[str],
        strategies: dict[str, Strategy],
        executor: PaperExecutor,
        risk_manager: RiskManager,
        alerter: TelegramAlerter | None = None,
    ) -> None:
        """Initialize the trading bot.

        Args:
            symbols: Trading pairs to trade (e.g. ["BTC/USDT", "ETH/USDT"]).
            strategies: Dict of symbol → Strategy instance.
            executor: Order executor (paper or live).
            risk_manager: Risk manager instance.
            alerter: Optional Telegram alerter.
        """
        self.symbols = symbols
        self.strategies = strategies
        self.executor = executor
        self.risk_manager = risk_manager
        self.alerter = alerter
        self._feed: BinanceDataFeed | None = None
        self._running = False
        self._last_daily_summary: str | None = None
        self._candle_count = 0

    async def start(self) -> None:
        """Start the bot. Blocks until stopped."""
        self._running = True

        # Set up signal handlers for clean shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Wire up risk breach alerts
        self.risk_manager.on_breach = self._on_risk_breach

        # Set up data feed
        self._feed = BinanceDataFeed(
            symbols=self.symbols,
            on_candle_1h=self._on_candle_1h,
        )

        logger.info(
            f"Bot starting — Symbols: {self.symbols} | "
            f"Strategies: {list(self.strategies.keys())} | "
            f"Capital: ${self.executor.initial_capital:,.2f}"
        )

        if self.alerter:
            await self.alerter.send(
                f"🤖 Bot started\n"
                f"Symbols: {', '.join(self.symbols)}\n"
                f"Capital: ${self.executor.initial_capital:,.2f}\n"
                f"Mode: PAPER"
            )

        # Start daily summary task and data feed concurrently
        try:
            await asyncio.gather(
                self._feed.start(),
                self._daily_summary_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Bot tasks cancelled")

    async def stop(self) -> None:
        """Gracefully shut down the bot."""
        if not self._running:
            return

        logger.info("Shutting down bot...")
        self._running = False

        if self._feed:
            await self._feed.stop()

        if self.alerter:
            summary = self.executor.summary()
            await self.alerter.send(
                f"🛑 Bot stopped\n"
                f"Total P&L: ${summary['total_pnl']:+,.2f}\n"
                f"Trades: {summary['total_trades']}\n"
                f"Open positions: {len(summary['open_positions'])}"
            )

        logger.info("Bot shutdown complete")

    def _on_candle_1h(self, symbol: str, candle: dict) -> None:
        """Called when a 1h candle completes. Runs the full trading pipeline.

        This runs synchronously within the WebSocket message handler.
        """
        self._candle_count += 1

        strategy = self.strategies.get(symbol)
        if strategy is None:
            return

        try:
            self._process_candle(symbol, candle, strategy)
        except Exception as e:
            logger.error(f"Error processing {symbol} candle: {e}")
            if self.alerter:
                asyncio.get_event_loop().create_task(
                    self.alerter.send_error(f"Error processing {symbol}: {e}")
                )

    def _process_candle(self, symbol: str, candle: dict, strategy: Strategy) -> None:
        """Process a single candle through the full pipeline."""
        price = candle["close"]

        # 1. Run strategy
        signal = strategy.on_candle(candle)

        # 2. Check risk limits (daily loss + total drawdown)
        current_capital = self.executor.capital
        self.risk_manager.check_total_drawdown(current_capital)
        self.risk_manager.check_daily_loss(self.executor.daily_pnl())

        if self.risk_manager.is_halted:
            return

        # 3. Execute based on signal
        current_position = self.executor.get_position(symbol)

        if signal == Signal.HOLD:
            return

        if signal == Signal.BUY:
            # Close short if exists, then open long
            if current_position and current_position.side == "short":
                trade = self.executor.close_position(symbol, price)
                if trade:
                    self._on_trade(trade)
            if not current_position or current_position.side == "short":
                self._try_open_position(symbol, "long", price)

        elif signal == Signal.SELL:
            # Close long if exists, then open short
            if current_position and current_position.side == "long":
                trade = self.executor.close_position(symbol, price)
                if trade:
                    self._on_trade(trade)
            if not current_position or current_position.side == "long":
                self._try_open_position(symbol, "short", price)

    def _try_open_position(self, symbol: str, side: str, price: float) -> None:
        """Attempt to open a position, subject to risk checks."""
        size = self.risk_manager.calculate_position_size(self.executor.capital)
        if size <= 0:
            return

        allowed, reason = self.risk_manager.check_new_position(
            symbol=symbol,
            proposed_size=size,
            current_capital=self.executor.capital,
            open_position_count=self.executor.open_position_count,
        )

        if not allowed:
            logger.warning(f"Position blocked: {reason}")
            return

        trade = self.executor.open_position(symbol, side, price, size)
        self._on_trade(trade)

    def _on_trade(self, trade: dict) -> None:
        """Called after every trade execution — send alert."""
        if not self.alerter:
            return

        if trade["action"] == "open":
            msg = (
                f"📈 OPEN {trade['side'].upper()} {trade['symbol']}\n"
                f"Price: ${trade['price']:,.2f}\n"
                f"Size: ${trade['size']:,.2f}\n"
                f"Capital: ${trade['capital_after']:,.2f}"
            )
        else:
            emoji = "✅" if trade.get("pnl", 0) >= 0 else "❌"
            msg = (
                f"{emoji} CLOSE {trade['side'].upper()} {trade['symbol']}\n"
                f"Entry: ${trade['entry_price']:,.2f} → Exit: ${trade['exit_price']:,.2f}\n"
                f"P&L: ${trade['pnl']:+,.2f} ({trade['pnl_pct']:+.2f}%)\n"
                f"Capital: ${trade['capital_after']:,.2f}"
            )

        asyncio.get_event_loop().create_task(self.alerter.send(msg))

    def _on_risk_breach(self, event: RiskEvent) -> None:
        """Called by risk manager when a limit is breached."""
        if self.alerter:
            asyncio.get_event_loop().create_task(
                self.alerter.send_risk_breach(event.details)
            )

    async def _daily_summary_loop(self) -> None:
        """Send daily P&L summary at midnight UTC."""
        while self._running:
            await asyncio.sleep(60)  # Check every minute

            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")

            # Send summary at 00:00 UTC (first minute of new day)
            if now.hour == 0 and now.minute == 0 and self._last_daily_summary != today:
                self._last_daily_summary = today
                await self._send_daily_summary()

    async def _send_daily_summary(self) -> None:
        """Send daily P&L summary via Telegram."""
        summary = self.executor.summary()
        msg = (
            f"📊 DAILY SUMMARY\n"
            f"──────────────\n"
            f"Capital: ${summary['capital']:,.2f}\n"
            f"Daily P&L: ${summary['daily_pnl']:+,.2f}\n"
            f"Total P&L: ${summary['total_pnl']:+,.2f}\n"
            f"Total Trades: {summary['total_trades']}\n"
            f"Open Positions: {len(summary['open_positions'])}"
        )
        if self.alerter:
            await self.alerter.send(msg)
        logger.info(f"Daily summary sent: P&L=${summary['daily_pnl']:+,.2f}")


def load_bot_from_config(config_path: str = "config/settings.yaml") -> TradingBot:
    """Create a TradingBot from the config file.

    Args:
        config_path: Path to settings.yaml.

    Returns:
        Configured TradingBot instance.
    """
    with open(config_path) as f:
        settings = yaml.safe_load(f)

    symbols = settings.get("live", {}).get("symbols", ["BTC/USDT", "ETH/USDT"])
    strategy_name = settings.get("live", {}).get("strategy", "volatility_breakout")
    initial_capital = settings.get("backtest", {}).get("initial_capital", 10_000.0)
    taker_fee = settings.get("backtest", {}).get("taker_fee", 0.0005)

    # Load strategy
    strategy_params = settings.get("strategies", {}).get(strategy_name, {})
    if strategy_name == "volatility_breakout":
        from strategies.volatility_breakout import VolatilityBreakoutStrategy
        strategy_class = VolatilityBreakoutStrategy
    elif strategy_name == "momentum":
        from strategies.momentum import MomentumStrategy
        strategy_class = MomentumStrategy
    else:
        raise ValueError(f"Unknown strategy for live: {strategy_name}")

    strategies = {sym: strategy_class(params=strategy_params) for sym in symbols}

    # Create executor
    executor = PaperExecutor(
        initial_capital=initial_capital,
        taker_fee=taker_fee,
    )

    # Create risk manager
    risk_settings = settings.get("risk", {})
    risk_limits = RiskLimits(
        max_position_pct=risk_settings.get("max_position_pct", 0.05),
        daily_loss_limit=risk_settings.get("daily_loss_limit", -0.15),
        total_drawdown_limit=risk_settings.get("total_drawdown_limit", -0.30),
        max_open_positions=risk_settings.get("max_open_positions", 2),
    )
    risk_manager = RiskManager(limits=risk_limits, initial_capital=initial_capital)

    # Create alerter
    alerter = TelegramAlerter.from_env()

    return TradingBot(
        symbols=symbols,
        strategies=strategies,
        executor=executor,
        risk_manager=risk_manager,
        alerter=alerter,
    )
