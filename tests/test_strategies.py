"""Tests for strategy signal generation."""

from __future__ import annotations

import pandas as pd

from strategies.base import Signal
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy


def _candle(close: float, idx: int = 0) -> dict:
    """Create a minimal candle dict."""
    return {
        "timestamp": pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=idx),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
    }


class TestMomentumStrategy:
    """Tests for the EMA + RSI momentum strategy."""

    def test_hold_during_warmup(self):
        """Strategy should return HOLD during warmup period."""
        strat = MomentumStrategy()
        for i in range(strat.warmup_period - 1):
            signal = strat.on_candle(_candle(100.0, i))
            assert signal == Signal.HOLD

    def test_warmup_period_is_positive(self):
        """Warmup should be at least max(ema_period, rsi_period)."""
        strat = MomentumStrategy()
        assert strat.warmup_period >= 20

    def test_name(self):
        assert MomentumStrategy().name == "momentum"

    def test_params_override(self):
        """Custom params should override defaults."""
        strat = MomentumStrategy(params={"ema_period": 50, "rsi_period": 20})
        assert strat.ema_period == 50
        assert strat.rsi_period == 20

    def test_generates_signals_after_warmup(self):
        """After enough trending candles, strategy should generate non-HOLD signals."""
        strat = MomentumStrategy()
        # Feed a strong uptrend: should eventually trigger BUY
        signals = []
        for i in range(100):
            price = 100.0 + i * 0.5  # steady uptrend
            signal = strat.on_candle(_candle(price, i))
            signals.append(signal)

        # After warmup, at least some signals should be BUY in a clear uptrend
        post_warmup = signals[strat.warmup_period:]
        assert Signal.BUY in post_warmup


class TestMeanReversionStrategy:
    """Tests for the Bollinger Bands + RSI mean reversion strategy."""

    def test_hold_during_warmup(self):
        """Strategy should return HOLD during warmup period."""
        strat = MeanReversionStrategy()
        for i in range(strat.warmup_period - 1):
            signal = strat.on_candle(_candle(100.0, i))
            assert signal == Signal.HOLD

    def test_warmup_period_is_positive(self):
        strat = MeanReversionStrategy()
        assert strat.warmup_period >= 20

    def test_name(self):
        assert MeanReversionStrategy().name == "mean_reversion"

    def test_params_override(self):
        strat = MeanReversionStrategy(params={"bb_period": 30, "rsi_oversold": 25})
        assert strat.bb_period == 30
        assert strat.rsi_oversold == 25

    def test_ranging_prices_mostly_hold(self):
        """Gently oscillating prices should mostly produce HOLD signals."""
        strat = MeanReversionStrategy()
        signals = []
        # Small oscillation around 100 — well within bands
        for i in range(60):
            price = 100.0 + (i % 3 - 1) * 0.5  # 99.5, 100.0, 100.5 repeating
            signal = strat.on_candle(_candle(price, i))
            signals.append(signal)

        post_warmup = signals[strat.warmup_period:]
        hold_count = sum(1 for s in post_warmup if s == Signal.HOLD)
        # Most signals should be HOLD in a tight range
        assert hold_count / len(post_warmup) > 0.8

    def test_reset_clears_history(self):
        """After reset, history should be empty."""
        strat = MeanReversionStrategy()
        for i in range(10):
            strat.on_candle(_candle(100.0, i))
        assert len(strat._history) == 10

        strat.reset()
        assert len(strat._history) == 0
