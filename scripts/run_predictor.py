"""
Live 15m candle color predictor for BTC/USDT prediction markets.

Connects to Binance WebSocket, aggregates 1m→15m candles,
and outputs GREEN predictions when confidence is high enough.

Usage:
    python scripts/run_predictor.py
    python scripts/run_predictor.py --min-conf 3.5 --telegram
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click
from loguru import logger

from live.prediction_feed import PredictionFeed
from strategies.candle_predictor import CandlePredictorStrategy, Prediction


class PredictionRunner:
    """Orchestrates live prediction feed + strategy + alerts."""

    def __init__(
        self,
        symbol: str,
        min_confidence: float,
        use_telegram: bool,
        payout: float,
    ) -> None:
        self.symbol = symbol
        self.payout = payout
        self.strategy = CandlePredictorStrategy(params={"min_confidence": min_confidence})
        self.feed = PredictionFeed(symbol=symbol, on_prediction=self._on_candle)
        self.use_telegram = use_telegram
        self.alerter = None

        # Stats
        self.total_candles = 0
        self.total_bets = 0
        self.total_wins = 0
        self.total_pnl = 0.0
        self._last_prediction: Prediction | None = None
        self._last_candle: dict | None = None

    async def _init_telegram(self) -> None:
        if not self.use_telegram:
            return
        try:
            from alerts.telegram import TelegramAlerter
            self.alerter = TelegramAlerter.from_env()
            if self.alerter:
                await self.alerter.send("🔮 Candle Predictor started\n"
                                       f"Symbol: {self.symbol}\n"
                                       f"Min confidence: {self.strategy.min_confidence}\n"
                                       f"Payout: {self.payout}x")
        except Exception as e:
            logger.warning(f"Telegram init failed: {e}")

    async def _on_candle(self, candle: dict) -> None:
        """Called when a 15m candle completes."""
        # Check previous prediction result
        if self._last_prediction is not None and self._last_prediction.should_bet and self._last_candle is not None:
            actual_green = candle["open"] < candle["close"]  # This candle is the one we predicted
            # Actually, the prediction was made AFTER last_candle closed, predicting THIS candle
            # But we receive this candle's data only after it closes
            # So we need to check: was our prediction correct?
            self._check_result(candle)

        # Run strategy on the completed candle to predict the NEXT one
        self.total_candles += 1
        pred = self.strategy.on_candle(candle)

        ts = candle["timestamp"]
        if hasattr(ts, "strftime"):
            ts_str = ts.strftime("%Y-%m-%d %H:%M")
        else:
            ts_str = str(ts)[:16]

        price = candle["close"]

        if pred.should_bet:
            self.total_bets += 1
            wr = self.total_wins / self.total_bets * 100 if self.total_bets > 1 else 0

            msg = (
                f"{'='*60}\n"
                f"  🟢 PREDICT GREEN — next 15m candle\n"
                f"  Time: {ts_str} UTC | Price: ${price:,.0f}\n"
                f"  Confidence: {pred.confidence:.1f} | Signals: {', '.join(pred.signals)}\n"
                f"  Stats: {self.total_bets} bets | {self.total_wins} wins | "
                f"WR={wr:.1f}% | P&L=${self.total_pnl:+.1f}\n"
                f"{'='*60}"
            )
            logger.info(msg)

            if self.alerter:
                await self.alerter.send(
                    f"🟢 PREDICT GREEN — next 15m candle\n"
                    f"⏰ {ts_str} UTC | 💰 ${price:,.0f}\n"
                    f"📊 Conf: {pred.confidence:.1f}\n"
                    f"🔍 {', '.join(pred.signals)}\n"
                    f"📈 {self.total_bets} bets | WR={wr:.1f}% | P&L=${self.total_pnl:+.1f}"
                )
        else:
            if self.total_candles % 4 == 0:  # log every hour
                wr = self.total_wins / max(self.total_bets, 1) * 100
                logger.info(
                    f"  {ts_str} | ${price:,.0f} | SKIP (score={pred.confidence:.1f}) | "
                    f"Bets: {self.total_bets} | WR={wr:.1f}% | P&L=${self.total_pnl:+.1f}"
                )

        self._last_prediction = pred
        self._last_candle = candle

    def _check_result(self, current_candle: dict) -> None:
        """Check if the previous prediction was correct."""
        pred = self._last_prediction
        if pred is None or not pred.should_bet:
            return

        actual_green = current_candle["close"] > current_candle["open"]
        correct = (pred.direction == Prediction.GREEN and actual_green) or \
                  (pred.direction == Prediction.RED and not actual_green)

        if correct:
            self.total_wins += 1
            self.total_pnl += self.payout - 1  # profit
            result_str = "✓ WIN"
        else:
            self.total_pnl -= 1.0  # lose stake
            result_str = "✗ LOSS"

        logger.info(f"  Result: {result_str} | Predicted {pred.direction.upper()}, "
                    f"actual={'GREEN' if actual_green else 'RED'}")

    async def run(self) -> None:
        await self._init_telegram()

        logger.info(f"Starting predictor: {self.symbol} 15m | "
                    f"min_conf={self.strategy.min_confidence} | payout={self.payout}x")
        logger.info(f"Breakeven WR: {1/self.payout*100:.1f}% | "
                    f"Target WR: 55%+ | Connecting to Binance...")

        await self.feed.start()

    def stop(self) -> None:
        self.feed.stop()
        wr = self.total_wins / max(self.total_bets, 1) * 100
        logger.info(f"\nFinal stats: {self.total_bets} bets | {self.total_wins} wins | "
                    f"WR={wr:.1f}% | P&L=${self.total_pnl:+.1f}")


@click.command()
@click.option("--symbol", default="BTC/USDT", help="Trading pair")
@click.option("--min-conf", default=4.0, type=float, help="Minimum confidence to bet (default 4.0)")
@click.option("--payout", default=1.90, type=float, help="Prediction market payout multiplier")
@click.option("--telegram", is_flag=True, help="Send alerts to Telegram")
def main(symbol: str, min_conf: float, payout: float, telegram: bool) -> None:
    """Run live 15m candle color predictor."""
    runner = PredictionRunner(
        symbol=symbol,
        min_confidence=min_conf,
        use_telegram=telegram,
        payout=payout,
    )

    loop = asyncio.new_event_loop()

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        runner.stop()
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        runner.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
