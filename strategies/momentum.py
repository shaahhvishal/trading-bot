"""
Momentum / trend-following strategy.

Logic:
  - LONG when price > EMA(20) AND RSI(14) > 55
  - SHORT when price < EMA(20) AND RSI(14) < 45
  - Close position on signal reversal (e.g. long → short flips)

Why this works (market microstructure perspective):
  EMA filters out noise and identifies the prevailing trend direction.
  RSI confirms momentum — we only enter when the trend has genuine buying
  or selling pressure behind it. This avoids whipsaws in ranging markets.
  The combination catches the "meat" of trends while filtering false starts.

This is our baseline strategy for validating the backtesting engine.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class MomentumStrategy(Strategy):
    """EMA + RSI momentum strategy."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.ema_period: int = self.params.get("ema_period", 20)
        self.rsi_period: int = self.params.get("rsi_period", 14)
        self.rsi_long: float = self.params.get("rsi_long_threshold", 55)
        self.rsi_short: float = self.params.get("rsi_short_threshold", 45)

        # Pre-computed indicator arrays (populated by prepare())
        self._ema: np.ndarray | None = None
        self._rsi: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "momentum"

    @property
    def warmup_period(self) -> int:
        return max(self.ema_period, self.rsi_period) + 10

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute EMA and RSI on the full dataset."""
        closes = data["close"]
        self._ema = ta.trend.ema_indicator(closes, window=self.ema_period).to_numpy()
        self._rsi = ta.momentum.rsi(closes, window=self.rsi_period).to_numpy()
        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Evaluate EMA + RSI conditions and emit signal.

        Args:
            candle: OHLCV dict with keys: timestamp, open, high, low, close, volume.

        Returns:
            BUY if bullish, SELL if bearish, HOLD otherwise.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1  # 0-based index into data

        if idx < self.warmup_period:
            return Signal.HOLD

        # Use pre-computed values (backtest) or compute incrementally (live)
        if self._prepared and self._ema is not None:
            current_ema = self._ema[idx]
            current_rsi = self._rsi[idx]
        else:
            closes = self._closes()
            ema = ta.trend.ema_indicator(closes, window=self.ema_period)
            rsi = ta.momentum.rsi(closes, window=self.rsi_period)
            current_ema = ema.iloc[-1]
            current_rsi = rsi.iloc[-1]

        current_close = candle["close"]

        if np.isnan(current_ema) or np.isnan(current_rsi):
            return Signal.HOLD

        # Long: price above EMA and RSI shows bullish momentum
        if current_close > current_ema and current_rsi > self.rsi_long:
            return Signal.BUY

        # Short: price below EMA and RSI shows bearish momentum
        if current_close < current_ema and current_rsi < self.rsi_short:
            return Signal.SELL

        return Signal.HOLD
