"""
Multi-timeframe EMA Swing Trading strategy.

Logic:
  - LONG when BOTH 4H close > 200 EMA(4H) AND 1H close > 200 EMA(1H)
  - EXIT when EITHER 4H close < 200 EMA(4H) OR 1H close < 200 EMA(1H)

This is a trend-following strategy that uses the 200 EMA as a regime filter
on two timeframes. The 4H provides the macro trend direction, the 1H provides
the entry timing. Long-only — only trades when both timeframes confirm uptrend.

Why this works:
  The 200 EMA is widely watched by institutional traders as a bull/bear
  dividing line. When price is above it on both 4H and 1H, the trend is
  strongly bullish across timeframes. Exiting when either breaks down
  catches trend reversals early while staying in during pullbacks that
  don't violate the longer-term structure.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class EMASwingStrategy(Strategy):
    """Multi-timeframe 200 EMA swing trading (long only)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        self.ema_period: int = self.params.get("ema_period", 200)

        # Pre-computed arrays (1H timeframe with 4H EMA mapped)
        self._ema_1h: np.ndarray | None = None
        self._ema_4h_mapped: np.ndarray | None = None
        self._close_4h_mapped: np.ndarray | None = None

        # Trade state
        self._in_trade: bool = False

    @property
    def name(self) -> str:
        return "ema_swing"

    @property
    def warmup_period(self) -> int:
        # 200 EMA on 4H needs 200*4 = 800 hourly bars minimum
        return self.ema_period * 4 + 10

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute 1H EMA and 4H EMA mapped to 1H bars.

        Expects 1H OHLCV data. Internally resamples to 4H for the
        higher-timeframe EMA.
        """
        close_1h = data["close"]

        # 1H 200 EMA
        self._ema_1h = ta.trend.ema_indicator(
            close_1h, window=self.ema_period
        ).to_numpy()

        # Resample to 4H
        data_4h = data.copy()
        data_4h["timestamp"] = pd.to_datetime(data_4h["timestamp"])
        data_4h = data_4h.set_index("timestamp")
        resampled = data_4h.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        # 4H 200 EMA
        ema_4h = ta.trend.ema_indicator(
            resampled["close"], window=self.ema_period
        )

        # Map 4H EMA and close back to 1H bars (forward-fill)
        ema_4h_series = ema_4h.reindex(data_4h.index, method="ffill")
        close_4h_series = resampled["close"].reindex(data_4h.index, method="ffill")

        self._ema_4h_mapped = ema_4h_series.to_numpy()
        self._close_4h_mapped = close_4h_series.to_numpy()

        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Process a 1H candle.

        BUY when both 1H and 4H close > 200 EMA.
        SELL when either closes below.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        if not self._prepared:
            return Signal.HOLD

        close_1h = candle["close"]
        ema_1h = self._ema_1h[idx]
        ema_4h = self._ema_4h_mapped[idx]
        close_4h = self._close_4h_mapped[idx]

        if np.isnan(ema_1h) or np.isnan(ema_4h) or np.isnan(close_4h):
            return Signal.HOLD

        above_1h = close_1h > ema_1h
        above_4h = close_4h > ema_4h

        if self._in_trade:
            # Exit if either timeframe closes below its 200 EMA
            if not above_1h or not above_4h:
                self._in_trade = False
                return Signal.SELL
            return Signal.HOLD
        else:
            # Enter long when both are above
            if above_1h and above_4h:
                self._in_trade = True
                return Signal.BUY
            return Signal.HOLD

    def reset(self) -> None:
        super().reset()
        self._in_trade = False
        self._ema_1h = None
        self._ema_4h_mapped = None
        self._close_4h_mapped = None
