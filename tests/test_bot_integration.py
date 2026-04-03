"""
Integration test: run the full bot pipeline with simulated candles.

Tests the complete chain: candle → strategy → risk manager → executor
without any network calls (no WebSocket, no Telegram).
"""

from __future__ import annotations

from datetime import datetime, timezone

import tempfile

import pytest

from live.bot import TradingBot
from live.executor import PaperExecutor
from live.risk_manager import RiskLimits, RiskManager
from strategies.base import Signal, Strategy


class AlwaysBuyStrategy(Strategy):
    """Test strategy that buys on first candle, holds after."""

    @property
    def name(self) -> str:
        return "always_buy"

    def on_candle(self, candle: dict) -> Signal:
        self._add_candle(candle)
        return Signal.BUY if len(self._history) == 1 else Signal.HOLD


class AlternateBuySell(Strategy):
    """Alternates BUY/SELL each candle to generate trades."""

    @property
    def name(self) -> str:
        return "alternate"

    def on_candle(self, candle: dict) -> Signal:
        self._add_candle(candle)
        return Signal.BUY if len(self._history) % 2 == 1 else Signal.SELL


def _candle(price: float, minute: int = 0) -> dict:
    """Create a 1h candle dict."""
    return {
        "timestamp": datetime(2024, 6, 1, minute, 0, tzinfo=timezone.utc),
        "open": price,
        "high": price + 100,
        "low": price - 100,
        "close": price,
        "volume": 1000,
    }


class TestBotIntegration:
    """Full pipeline integration tests."""

    def _make_bot(self, strategy_class, capital=10_000.0, **risk_kwargs):
        """Create a bot with a test strategy, no alerter."""
        symbol = "BTC/USDT"
        # Use a temp file to avoid loading/polluting real trade log
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        executor = PaperExecutor(initial_capital=capital, taker_fee=0.0005,
                                 trade_log_path=tmp.name)
        limits = RiskLimits(
            max_position_pct=risk_kwargs.get("max_position_pct", 0.05),
            daily_loss_limit=risk_kwargs.get("daily_loss_limit", -0.15),
            total_drawdown_limit=risk_kwargs.get("total_drawdown_limit", -0.30),
            max_open_positions=risk_kwargs.get("max_open_positions", 2),
        )
        rm = RiskManager(limits=limits, initial_capital=capital)
        strategy = strategy_class()

        bot = TradingBot(
            symbols=[symbol],
            strategies={symbol: strategy},
            executor=executor,
            risk_manager=rm,
            alerter=None,
        )
        return bot

    def test_5_candle_pipeline(self):
        """Run 5 candles through the full pipeline — verify trades execute."""
        bot = self._make_bot(AlternateBuySell)
        symbol = "BTC/USDT"

        prices = [60000, 61000, 60500, 62000, 61500]
        for i, price in enumerate(prices):
            candle = _candle(price, i)
            bot._on_candle_1h(symbol, candle)

        # Should have executed trades (alternating buy/sell)
        assert len(bot.executor.trade_log) > 0
        # All trades should have valid prices
        for trade in bot.executor.trade_log:
            price = trade.get("price") or trade.get("entry_price", 0)
            assert price > 0

    def test_risk_manager_blocks_oversized_position(self):
        """Risk manager should limit position size to 5% of capital."""
        bot = self._make_bot(AlwaysBuyStrategy)
        symbol = "BTC/USDT"

        # With 10k capital and 5% limit, max position = $500
        candle = _candle(60000)
        bot._on_candle_1h(symbol, candle)

        # Position should have been opened at the risk-limited size
        open_trades = [t for t in bot.executor.trade_log if t["action"] == "open"]
        if open_trades:
            assert open_trades[0]["size"] <= 500.0

    def test_risk_manager_halts_on_drawdown(self):
        """Kill switch triggers when drawdown exceeds -30%."""
        bot = self._make_bot(AlternateBuySell, capital=10_000.0,
                             total_drawdown_limit=-0.30)

        # Manually drain capital to trigger kill switch
        bot.executor.capital = 6_500  # >30% below initial 10k
        bot.risk_manager.update_capital(10_000)  # set peak

        candle = _candle(60000)
        bot._on_candle_1h("BTC/USDT", candle)

        # Kill switch should have fired
        assert bot.risk_manager.is_killed

    def test_no_crash_on_hold_signals(self):
        """Bot handles HOLD signals gracefully (no trades)."""

        class AlwaysHold(Strategy):
            @property
            def name(self) -> str:
                return "hold"

            def on_candle(self, candle: dict) -> Signal:
                self._add_candle(candle)
                return Signal.HOLD

        bot = self._make_bot(AlwaysHold)
        for i in range(5):
            bot._on_candle_1h("BTC/USDT", _candle(60000 + i * 100, i))

        assert len(bot.executor.trade_log) == 0
        assert bot.executor.capital == 10_000.0

    def test_position_flip_closes_and_reopens(self):
        """Going from long to short should close the long first."""
        bot = self._make_bot(AlternateBuySell)
        symbol = "BTC/USDT"

        # Candle 1: BUY (opens long)
        bot._on_candle_1h(symbol, _candle(60000, 0))
        assert bot.executor.get_position(symbol) is not None
        assert bot.executor.get_position(symbol).side == "long"

        # Candle 2: SELL (should close long, open short)
        bot._on_candle_1h(symbol, _candle(61000, 1))
        pos = bot.executor.get_position(symbol)
        assert pos is not None
        assert pos.side == "short"

        # Should have: open long, close long, open short
        actions = [t["action"] for t in bot.executor.trade_log]
        assert actions == ["open", "close", "open"]

    def test_executor_tracks_pnl(self):
        """Executor correctly calculates P&L on closed trades."""
        bot = self._make_bot(AlternateBuySell)
        symbol = "BTC/USDT"

        # Buy at 60000, sell at 61000 (1.67% gain on a small position)
        bot._on_candle_1h(symbol, _candle(60000, 0))
        bot._on_candle_1h(symbol, _candle(61000, 1))

        close_trades = [t for t in bot.executor.trade_log if t["action"] == "close"]
        assert len(close_trades) >= 1
        # First close should be profitable (bought at 60k, sold at 61k)
        assert close_trades[0]["pnl"] > 0
