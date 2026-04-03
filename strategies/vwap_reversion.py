"""
VWAP mean reversion strategy.

Logic:
  - Calculate rolling VWAP (volume-weighted average price) over N periods
  - LONG when price is significantly below VWAP (oversold) AND RSI shows
    bullish divergence (RSI rising while price still falling)
  - SHORT when price is significantly above VWAP (overbought) AND RSI shows
    bearish divergence (RSI falling while price still rising)
  - "Significantly" = more than K standard deviations from VWAP

Why this works (market microstructure perspective):
  VWAP represents the "fair value" where most volume traded — it's the
  benchmark institutional traders use. When price deviates far from VWAP,
  it tends to revert because:

  1. Market makers widen spreads at extremes, reducing momentum
  2. Institutional algos often have VWAP execution targets, creating
     mean-reverting pressure
  3. Retail stop-losses cluster at extremes, and once they're swept,
     there's no more fuel for continuation

  RSI divergence filters false signals: if RSI is RISING while price
  is FALLING near VWAP-2σ, buying pressure is building beneath the surface.
  That's our entry signal.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class VWAPReversionStrategy(Strategy):
    """VWAP mean reversion with RSI divergence confirmation."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.vwap_period: int = self.params.get("vwap_period", 20)
        self.vwap_std_mult: float = self.params.get("vwap_std_mult", 2.0)
        self.rsi_period: int = self.params.get("rsi_period", 14)
        self.rsi_divergence_lookback: int = self.params.get("rsi_divergence_lookback", 5)

        # Pre-computed arrays
        self._vwap: np.ndarray | None = None
        self._vwap_upper: np.ndarray | None = None
        self._vwap_lower: np.ndarray | None = None
        self._rsi: np.ndarray | None = None
        self._closes_arr: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "vwap_reversion"

    @property
    def warmup_period(self) -> int:
        return max(self.vwap_period, self.rsi_period) + self.rsi_divergence_lookback + 5

    def _compute_rolling_vwap(self, close: pd.Series, high: pd.Series,
                               low: pd.Series, volume: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute rolling VWAP and standard deviation bands.

        Uses typical price (H+L+C)/3 weighted by volume over a rolling window.
        """
        typical_price = (high + low + close) / 3.0
        tp_vol = typical_price * volume

        # Rolling VWAP = sum(TP * Vol) / sum(Vol)
        rolling_tp_vol = tp_vol.rolling(window=self.vwap_period).sum()
        rolling_vol = volume.rolling(window=self.vwap_period).sum()
        vwap = (rolling_tp_vol / rolling_vol).to_numpy()

        # Rolling standard deviation of typical price from VWAP
        tp_arr = typical_price.to_numpy()
        vwap_std = pd.Series(tp_arr).rolling(window=self.vwap_period).std().to_numpy()

        upper = vwap + self.vwap_std_mult * vwap_std
        lower = vwap - self.vwap_std_mult * vwap_std

        return vwap, upper, lower

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute VWAP bands and RSI on the full dataset."""
        close = data["close"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"]

        self._vwap, self._vwap_upper, self._vwap_lower = self._compute_rolling_vwap(
            close, high, low, volume
        )
        self._rsi = ta.momentum.rsi(close, window=self.rsi_period).to_numpy()
        self._closes_arr = close.to_numpy()
        self._prepared = True

    def _check_divergence(self, idx: int, direction: str) -> bool:
        """Check for RSI divergence over the lookback window.

        Bullish divergence: price making lower lows, RSI making higher lows
        Bearish divergence: price making higher highs, RSI making lower highs

        Args:
            idx: Current candle index.
            direction: "bullish" or "bearish".

        Returns:
            True if divergence detected.
        """
        lb = self.rsi_divergence_lookback
        if idx < lb:
            return False

        if self._prepared and self._rsi is not None and self._closes_arr is not None:
            rsi_now = self._rsi[idx]
            rsi_prev = self._rsi[idx - lb]
            close_now = self._closes_arr[idx]
            close_prev = self._closes_arr[idx - lb]
        else:
            return False

        if np.isnan(rsi_now) or np.isnan(rsi_prev):
            return False

        if direction == "bullish":
            # Price lower, RSI higher → buying pressure building
            return close_now < close_prev and rsi_now > rsi_prev
        else:
            # Price higher, RSI lower → selling pressure building
            return close_now > close_prev and rsi_now < rsi_prev

    def on_candle(self, candle: dict) -> Signal:
        """Check for VWAP deviation + RSI divergence.

        Args:
            candle: OHLCV dict.

        Returns:
            BUY if oversold with bullish divergence, SELL if overbought with
            bearish divergence, HOLD otherwise.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        if self._prepared and self._vwap_lower is not None:
            vwap_lower = self._vwap_lower[idx]
            vwap_upper = self._vwap_upper[idx]
        else:
            # Live mode: compute from history buffer
            history_df = pd.DataFrame(self._history)
            self._vwap, self._vwap_upper, self._vwap_lower = self._compute_rolling_vwap(
                history_df["close"], history_df["high"],
                history_df["low"], history_df["volume"]
            )
            self._rsi = ta.momentum.rsi(history_df["close"], window=self.rsi_period).to_numpy()
            self._closes_arr = history_df["close"].to_numpy()
            vwap_lower = self._vwap_lower[-1]
            vwap_upper = self._vwap_upper[-1]

        current_close = candle["close"]

        if np.isnan(vwap_lower) or np.isnan(vwap_upper):
            return Signal.HOLD

        # Long: price below lower VWAP band + bullish RSI divergence
        if current_close <= vwap_lower and self._check_divergence(idx, "bullish"):
            return Signal.BUY

        # Short: price above upper VWAP band + bearish RSI divergence
        if current_close >= vwap_upper and self._check_divergence(idx, "bearish"):
            return Signal.SELL

        return Signal.HOLD
