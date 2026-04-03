"""
Mean reversion strategy using Bollinger Bands + RSI.

Logic:
  - LONG when price touches/crosses below the lower Bollinger Band AND RSI < oversold
  - SHORT when price touches/crosses above the upper Bollinger Band AND RSI > overbought
  - Close on price returning to the middle band (SMA)

Why this works (market microstructure perspective):
  Bollinger Bands measure volatility-adjusted deviation from the mean. When price
  pushes far from the moving average (outside the bands), it's statistically likely
  to revert — especially in ranging/consolidating markets. RSI confirms the
  extreme: an oversold RSI means sellers are exhausted, and vice versa.

  The edge comes from mean reversion being the dominant regime in crypto during
  low-volatility periods. The risk is that trending markets will blow through
  the bands repeatedly — which is why we combine with RSI for confirmation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class MeanReversionStrategy(Strategy):
    """Bollinger Bands + RSI mean reversion strategy."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.bb_period: int = self.params.get("bb_period", 20)
        self.bb_std: float = self.params.get("bb_std", 2.0)
        self.rsi_period: int = self.params.get("rsi_period", 14)
        self.rsi_oversold: float = self.params.get("rsi_oversold", 30)
        self.rsi_overbought: float = self.params.get("rsi_overbought", 70)

        # Pre-computed indicator arrays (populated by prepare())
        self._bb_lower: np.ndarray | None = None
        self._bb_upper: np.ndarray | None = None
        self._bb_middle: np.ndarray | None = None
        self._rsi: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "mean_reversion"

    @property
    def warmup_period(self) -> int:
        return max(self.bb_period, self.rsi_period) + 10

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute Bollinger Bands and RSI on the full dataset."""
        closes = data["close"]
        bb = ta.volatility.BollingerBands(
            close=closes, window=self.bb_period, window_dev=self.bb_std
        )
        self._bb_lower = bb.bollinger_lband().to_numpy()
        self._bb_upper = bb.bollinger_hband().to_numpy()
        self._bb_middle = bb.bollinger_mavg().to_numpy()
        self._rsi = ta.momentum.rsi(closes, window=self.rsi_period).to_numpy()
        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Evaluate Bollinger Band + RSI conditions and emit signal.

        Args:
            candle: OHLCV dict with keys: timestamp, open, high, low, close, volume.

        Returns:
            BUY if oversold, SELL if overbought, HOLD otherwise.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        # Use pre-computed values (backtest) or compute incrementally (live)
        if self._prepared and self._bb_lower is not None:
            lower_band = self._bb_lower[idx]
            upper_band = self._bb_upper[idx]
            current_rsi = self._rsi[idx]
        else:
            closes = self._closes()
            bb = ta.volatility.BollingerBands(
                close=closes, window=self.bb_period, window_dev=self.bb_std
            )
            lower_band = bb.bollinger_lband().iloc[-1]
            upper_band = bb.bollinger_hband().iloc[-1]
            current_rsi = ta.momentum.rsi(closes, window=self.rsi_period).iloc[-1]

        current_close = candle["close"]

        if np.isnan(lower_band) or np.isnan(upper_band) or np.isnan(current_rsi):
            return Signal.HOLD

        # Long: price at/below lower band + RSI confirms oversold
        if current_close <= lower_band and current_rsi < self.rsi_oversold:
            return Signal.BUY

        # Short: price at/above upper band + RSI confirms overbought
        if current_close >= upper_band and current_rsi > self.rsi_overbought:
            return Signal.SELL

        return Signal.HOLD
