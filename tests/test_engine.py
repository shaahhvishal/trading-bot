"""Tests for backtest/engine.py — the core backtesting loop."""

from __future__ import annotations

import pandas as pd

from backtest.engine import BacktestConfig, BacktestEngine
from strategies.base import Signal, Strategy


class AlwaysBuyStrategy(Strategy):
    """Test strategy that buys on candle 1 and holds."""

    @property
    def name(self) -> str:
        return "always_buy"

    def on_candle(self, candle: dict) -> Signal:
        self._add_candle(candle)
        return Signal.BUY if len(self._history) == 1 else Signal.HOLD


class BuySellAlternate(Strategy):
    """Alternates BUY then SELL every candle (to generate many trades)."""

    @property
    def name(self) -> str:
        return "alternate"

    def on_candle(self, candle: dict) -> Signal:
        self._add_candle(candle)
        return Signal.BUY if len(self._history) % 2 == 1 else Signal.SELL


class AlwaysHoldStrategy(Strategy):
    """Never trades."""

    @property
    def name(self) -> str:
        return "hold"

    def on_candle(self, candle: dict) -> Signal:
        self._add_candle(candle)
        return Signal.HOLD


def _make_data(prices: list[float]) -> pd.DataFrame:
    """Create a minimal DataFrame from a list of close prices."""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=len(prices), freq="min", tz="UTC"),
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000] * len(prices),
        }
    )


def test_no_trades_returns_initial_capital():
    """Engine with a hold-only strategy should return initial capital unchanged."""
    engine = BacktestEngine(BacktestConfig(initial_capital=10_000))
    data = _make_data([100.0] * 10)
    result = engine.run(AlwaysHoldStrategy(), data)

    assert result.num_trades == 0
    assert result.final_capital == 10_000.0
    assert result.total_return_pct == 0.0


def test_profitable_long_trade():
    """Buy at 100, price goes to 110 → should profit (minus fees)."""
    config = BacktestConfig(initial_capital=10_000, taker_fee=0.0, position_size_pct=1.0)
    engine = BacktestEngine(config)
    # Price rises 10%
    data = _make_data([100.0, 110.0])
    result = engine.run(AlwaysBuyStrategy(), data)

    assert result.num_trades == 1  # force-closed at end
    assert result.total_pnl > 0
    assert result.total_return_pct == 10.0


def test_fees_reduce_profit():
    """Same trade as above but with fees → profit should be less."""
    no_fee = BacktestConfig(initial_capital=10_000, taker_fee=0.0)
    with_fee = BacktestConfig(initial_capital=10_000, taker_fee=0.001)

    data = _make_data([100.0, 110.0])

    result_no_fee = BacktestEngine(no_fee).run(AlwaysBuyStrategy(), data)
    result_with_fee = BacktestEngine(with_fee).run(AlwaysBuyStrategy(), data)

    assert result_with_fee.total_pnl < result_no_fee.total_pnl


def test_equity_curve_length_matches_data():
    """Equity curve should have one entry per candle."""
    engine = BacktestEngine()
    data = _make_data([100.0] * 50)
    result = engine.run(AlwaysHoldStrategy(), data)

    assert len(result.equity_curve) == 50


def test_alternating_strategy_generates_trades():
    """BuySellAlternate should generate multiple trades."""
    config = BacktestConfig(initial_capital=10_000, taker_fee=0.0)
    engine = BacktestEngine(config)
    data = _make_data([100.0] * 10)
    result = engine.run(BuySellAlternate(), data)

    # Should have several trades from the alternating signals
    assert result.num_trades >= 4


def test_short_trade_profits_on_price_drop():
    """A short opened at 100 with price dropping to 90 should profit."""

    class ShortOnce(Strategy):
        @property
        def name(self) -> str:
            return "short_once"

        def on_candle(self, candle: dict) -> Signal:
            self._add_candle(candle)
            return Signal.SELL if len(self._history) == 1 else Signal.HOLD

    config = BacktestConfig(initial_capital=10_000, taker_fee=0.0)
    data = _make_data([100.0, 90.0])
    result = BacktestEngine(config).run(ShortOnce(), data)

    assert result.total_pnl > 0
    assert result.total_return_pct == 10.0
