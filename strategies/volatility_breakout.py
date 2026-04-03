"""
Volatility breakout strategy using Donchian Channels + ATR + Volume.

Logic:
  - LONG when price breaks above the Donchian upper band (N-period high)
    AND volume is above its moving average (confirms real breakout, not noise)
  - SHORT when price breaks below the Donchian lower band (N-period low)
    AND volume confirms

Exits:
  - Signal-based: opposite Donchian breakout reverses the position.
  - MFE/MAE analysis (2024 BTC data) confirmed signal-based exits are optimal:
    winners avg +10% MFE with 58% capture ratio, and adding hard TP/SL
    causes re-entry churn that degrades returns. The Donchian channel itself
    acts as a natural trailing stop — it only exits when momentum truly reverses.

Why this works (market microstructure perspective):
  Donchian breakouts capture the moment price escapes a consolidation range.
  When BTC has been trading between $60k-$62k for hours and then breaks $62k,
  there's typically a cascade of stop-losses and liquidations above that level
  that propel price further. Volume confirmation filters out false breakouts
  that happen on thin liquidity (e.g., Asia session low-volume wicks).

  This is essentially a turtle-trading-inspired approach adapted for crypto.
  The edge comes from the asymmetry: false breakouts lose small (quick revert),
  true breakouts win big (momentum continuation).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class VolatilityBreakoutStrategy(Strategy):
    """Donchian Channel breakout with volume confirmation."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.donchian_period: int = self.params.get("donchian_period", 20)
        self.volume_ma_period: int = self.params.get("volume_ma_period", 20)
        self.atr_period: int = self.params.get("atr_period", 14)

        # Pre-computed arrays
        self._donchian_high: np.ndarray | None = None
        self._donchian_low: np.ndarray | None = None
        self._volume_ma: np.ndarray | None = None
        self._atr: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "volatility_breakout"

    @property
    def warmup_period(self) -> int:
        return max(self.donchian_period, self.volume_ma_period, self.atr_period) + 5

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute Donchian channels, volume MA, and ATR."""
        high = data["high"]
        low = data["low"]
        close = data["close"]
        volume = data["volume"]

        # Donchian channels: highest high and lowest low over N periods
        self._donchian_high = high.rolling(window=self.donchian_period).max().to_numpy()
        self._donchian_low = low.rolling(window=self.donchian_period).min().to_numpy()

        # Volume moving average for confirmation
        self._volume_ma = volume.rolling(window=self.volume_ma_period).mean().to_numpy()

        # ATR for volatility context
        self._atr = ta.volatility.average_true_range(
            high=high, low=low, close=close, window=self.atr_period
        ).to_numpy()

        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Check for Donchian breakout with volume confirmation.

        Args:
            candle: OHLCV dict.

        Returns:
            BUY on upside breakout, SELL on downside breakout, HOLD otherwise.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        if self._prepared and self._donchian_high is not None:
            # Use previous bar's channel (avoid lookahead — current bar's high
            # could BE the new Donchian high, so compare close to prior channel)
            prev_high = self._donchian_high[idx - 1]
            prev_low = self._donchian_low[idx - 1]
            vol_ma = self._volume_ma[idx]
        else:
            # Live mode fallback
            closes = self._closes()
            highs = pd.Series([c["high"] for c in self._history])
            lows = pd.Series([c["low"] for c in self._history])
            volumes = pd.Series([c["volume"] for c in self._history])
            prev_high = highs.iloc[:-1].rolling(self.donchian_period).max().iloc[-1]
            prev_low = lows.iloc[:-1].rolling(self.donchian_period).min().iloc[-1]
            vol_ma = volumes.rolling(self.volume_ma_period).mean().iloc[-1]

        current_close = candle["close"]
        current_volume = candle["volume"]

        if np.isnan(prev_high) or np.isnan(prev_low) or np.isnan(vol_ma):
            return Signal.HOLD

        volume_confirms = current_volume > vol_ma

        # Breakout above Donchian high with volume
        if current_close > prev_high and volume_confirms:
            return Signal.BUY

        # Breakdown below Donchian low with volume
        if current_close < prev_low and volume_confirms:
            return Signal.SELL

        return Signal.HOLD
