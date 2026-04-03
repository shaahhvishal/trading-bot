"""
VWAP Trend Continuation Pullback strategy.

Primary timeframe: 5m entries; 1m fine-tuning; 15m context.

Setup:
  - Session VWAP resets at each session start (8h sessions by default)
  - Trend bias: VWAP slope up AND price holding above VWAP (for longs)
  - Optional 15m structure filter: higher highs / higher lows

Entry (long):
  - Condition A (trend): close > VWAP AND VWAP slope > 0
  - Condition B (pullback): price retraces to within 0.4 * ATR of VWAP
  - Trigger: candle reclaims VWAP (closes back above it)
  - No chase: if price never pulls back to VWAP, don't enter

Exits:
  - Stop: below pullback swing low OR below VWAP - 0.5 * ATR (whichever further)
  - Take profit at 2R, then trail under 9 EMA
  - At +1R: move stop to breakeven

Short side is symmetric.

Why this works (market microstructure):
  VWAP is the institutional execution benchmark — large funds often have VWAP
  execution targets. When price pulls back to VWAP in an uptrend, institutions
  are BUYERS there (they want to fill below VWAP to beat their benchmark).
  This creates a natural demand zone. The pullback filters out chasing entries
  and the slope confirms genuine directional flow, not chop.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class VWAPPullbackStrategy(Strategy):
    """VWAP trend continuation pullback with risk-defined exits."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)

        # Session parameters
        self.session_hours: list[int] = self.params.get("session_hours", [0, 8, 16])

        # Entry parameters
        self.atr_period: int = self.params.get("atr_period", 14)
        self.pullback_atr_mult: float = self.params.get("pullback_atr_mult", 0.4)
        self.vwap_slope_lookback: int = self.params.get("vwap_slope_lookback", 5)
        self.use_structure_filter: bool = self.params.get("use_structure_filter", True)
        self.structure_lookback: int = self.params.get("structure_lookback", 6)

        # Exit parameters
        self.stop_atr_mult: float = self.params.get("stop_atr_mult", 0.5)
        self.tp_r_multiple: float = self.params.get("tp_r_multiple", 2.0)
        self.trail_ema_period: int = self.params.get("trail_ema_period", 9)

        # Internal state
        self._reset_trade_state()
        self._session_tp_vol_sum: float = 0.0
        self._session_vol_sum: float = 0.0
        self._session_vwap: float = 0.0
        self._prev_vwap: float = 0.0
        self._session_candle_count: int = 0
        self._pullback_swing_low: float = np.inf
        self._pullback_swing_high: float = -np.inf
        self._in_pullback: bool = False
        self._trend_was_up: bool = False
        self._trend_was_down: bool = False

        # Pre-computed arrays
        self._atr_arr: np.ndarray | None = None
        self._ema_arr: np.ndarray | None = None
        # Session VWAP must be computed candle-by-candle (resets per session)
        # so we precompute it in prepare()
        self._vwap_precomputed: np.ndarray | None = None
        self._vwap_slope_precomputed: np.ndarray | None = None
        self._structure_up: np.ndarray | None = None
        self._structure_down: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "vwap_pullback"

    @property
    def warmup_period(self) -> int:
        return max(self.atr_period, self.trail_ema_period, self.structure_lookback) * 5 + 20

    def _reset_trade_state(self) -> None:
        """Reset position tracking state."""
        self._in_trade: bool = False
        self._trade_side: str = ""
        self._entry_price: float = 0.0
        self._stop_price: float = 0.0
        self._r_value: float = 0.0
        self._breakeven_activated: bool = False
        self._entry_candle_idx: int = 0

    def _is_session_start(self, ts: datetime) -> bool:
        return ts.minute == 0 and ts.hour in self.session_hours

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute session VWAP, ATR, EMA, and structure filters."""
        close = data["close"].to_numpy()
        high = data["high"].to_numpy()
        low = data["low"].to_numpy()
        volume = data["volume"].to_numpy()
        timestamps = data["timestamp"]

        n = len(data)

        # ATR
        self._atr_arr = ta.volatility.average_true_range(
            high=data["high"], low=data["low"], close=data["close"],
            window=self.atr_period
        ).to_numpy()

        # Trailing EMA
        self._ema_arr = ta.trend.ema_indicator(
            data["close"], window=self.trail_ema_period
        ).to_numpy()

        # Session VWAP (resets at each session boundary)
        vwap = np.full(n, np.nan)
        tp_vol_sum = 0.0
        vol_sum = 0.0

        for i in range(n):
            ts = timestamps.iloc[i]
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()

            # Reset at session start
            if hasattr(ts, 'minute') and ts.minute == 0 and ts.hour in self.session_hours:
                tp_vol_sum = 0.0
                vol_sum = 0.0

            tp = (high[i] + low[i] + close[i]) / 3.0
            tp_vol_sum += tp * volume[i]
            vol_sum += volume[i]

            if vol_sum > 0:
                vwap[i] = tp_vol_sum / vol_sum

        self._vwap_precomputed = vwap

        # VWAP slope (difference over lookback)
        slope = np.full(n, 0.0)
        for i in range(self.vwap_slope_lookback, n):
            if not np.isnan(vwap[i]) and not np.isnan(vwap[i - self.vwap_slope_lookback]):
                slope[i] = vwap[i] - vwap[i - self.vwap_slope_lookback]
        self._vwap_slope_precomputed = slope

        # Structure filter: higher highs / higher lows over lookback
        # Check on a coarser grain (every 3 bars to approximate 15m on 5m data)
        struct_up = np.zeros(n, dtype=bool)
        struct_down = np.zeros(n, dtype=bool)
        grain = 3  # approximate 15m structure on 5m bars
        lb = self.structure_lookback

        for i in range(lb * grain, n):
            # Sample highs and lows at grain intervals
            sampled_highs = [high[i - j * grain] for j in range(lb) if i - j * grain >= 0]
            sampled_lows = [low[i - j * grain] for j in range(lb) if i - j * grain >= 0]

            if len(sampled_highs) >= 3 and len(sampled_lows) >= 3:
                # Higher highs and higher lows
                hh = all(sampled_highs[j] >= sampled_highs[j + 1] for j in range(min(3, len(sampled_highs) - 1)))
                hl = all(sampled_lows[j] >= sampled_lows[j + 1] for j in range(min(3, len(sampled_lows) - 1)))
                struct_up[i] = hh and hl

                # Lower highs and lower lows
                lh = all(sampled_highs[j] <= sampled_highs[j + 1] for j in range(min(3, len(sampled_highs) - 1)))
                ll = all(sampled_lows[j] <= sampled_lows[j + 1] for j in range(min(3, len(sampled_lows) - 1)))
                struct_down[i] = lh and ll

        self._structure_up = struct_up
        self._structure_down = struct_down
        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Process a candle through the VWAP pullback logic."""
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        close = candle["close"]
        high = candle["high"]
        low = candle["low"]

        ts = candle["timestamp"]
        if hasattr(ts, 'to_pydatetime'):
            ts = ts.to_pydatetime()

        # Session reset — close any open trade
        if hasattr(ts, 'minute') and self._is_session_start(ts):
            if self._in_trade:
                self._in_trade = False
                signal = Signal.SELL if self._trade_side == "long" else Signal.BUY
                self._reset_trade_state()
                self._in_pullback = False
                self._trend_was_up = False
                self._trend_was_down = False
                self._pullback_swing_low = np.inf
                self._pullback_swing_high = -np.inf
                return signal
            self._in_pullback = False
            self._trend_was_up = False
            self._trend_was_down = False
            self._pullback_swing_low = np.inf
            self._pullback_swing_high = -np.inf

        # Get indicators
        vwap = self._get_vwap(idx)
        vwap_slope = self._get_vwap_slope(idx)
        atr = self._get_atr(idx)

        if np.isnan(vwap) or np.isnan(atr) or atr <= 0:
            return Signal.HOLD

        # If in trade, manage exits
        if self._in_trade:
            return self._manage_exits(idx, candle)

        # Trend detection
        is_uptrend = close > vwap and vwap_slope > 0
        is_downtrend = close < vwap and vwap_slope < 0

        # Structure filter
        if self.use_structure_filter:
            struct_up = self._get_structure_up(idx)
            struct_down = self._get_structure_down(idx)
            is_uptrend = is_uptrend and struct_up
            is_downtrend = is_downtrend and struct_down

        # Track trend state for pullback detection
        if is_uptrend:
            self._trend_was_up = True
            self._trend_was_down = False
            self._in_pullback = False
        elif is_downtrend:
            self._trend_was_down = True
            self._trend_was_up = False
            self._in_pullback = False

        # Detect pullback to VWAP
        pullback_zone = self.pullback_atr_mult * atr

        # Long setup: was in uptrend, now price pulled back near VWAP
        if self._trend_was_up and close <= vwap + pullback_zone and close >= vwap - pullback_zone:
            self._in_pullback = True
            self._pullback_swing_low = min(self._pullback_swing_low, low)

        # Short setup: was in downtrend, now price pulled back near VWAP
        if self._trend_was_down and close >= vwap - pullback_zone and close <= vwap + pullback_zone:
            self._in_pullback = True
            self._pullback_swing_high = max(self._pullback_swing_high, high)

        # Trigger: reclaim after pullback
        if self._in_pullback and self._trend_was_up:
            # Reclaim: close back above VWAP after pulling back
            if close > vwap and vwap_slope > 0:
                # Calculate stop
                stop_from_swing = self._pullback_swing_low
                stop_from_atr = vwap - self.stop_atr_mult * atr
                stop = min(stop_from_swing, stop_from_atr)

                r_value = close - stop
                if r_value > 0 and r_value < close * 0.05:  # sanity: R < 5% of price
                    self._enter_trade("long", close, stop, r_value, idx)
                    self._in_pullback = False
                    self._trend_was_up = False
                    self._pullback_swing_low = np.inf
                    return Signal.BUY

        if self._in_pullback and self._trend_was_down:
            # Reclaim: close back below VWAP after pulling back
            if close < vwap and vwap_slope < 0:
                stop_from_swing = self._pullback_swing_high
                stop_from_atr = vwap + self.stop_atr_mult * atr
                stop = max(stop_from_swing, stop_from_atr)

                r_value = stop - close
                if r_value > 0 and r_value < close * 0.05:
                    self._enter_trade("short", close, stop, r_value, idx)
                    self._in_pullback = False
                    self._trend_was_down = False
                    self._pullback_swing_high = -np.inf
                    return Signal.SELL

        return Signal.HOLD

    def _enter_trade(self, side: str, price: float, stop: float,
                     r_value: float, idx: int) -> None:
        self._in_trade = True
        self._trade_side = side
        self._entry_price = price
        self._stop_price = stop
        self._r_value = r_value
        self._breakeven_activated = False
        self._entry_candle_idx = idx

    def _manage_exits(self, idx: int, candle: dict) -> Signal:
        """Check stop, TP, trailing EMA, breakeven."""
        close = candle["close"]
        low = candle["low"]
        high = candle["high"]

        if self._r_value <= 0:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        if self._trade_side == "long":
            current_r = (close - self._entry_price) / self._r_value
            hit_stop = low <= self._stop_price
        else:
            current_r = (self._entry_price - close) / self._r_value
            hit_stop = high >= self._stop_price

        # Stop loss
        if hit_stop:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        # Take profit at 2R
        if current_r >= self.tp_r_multiple:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        # At +1R: breakeven stop + activate trailing
        if current_r >= 1.0 and not self._breakeven_activated:
            self._breakeven_activated = True
            self._stop_price = self._entry_price

        # Trailing EMA (after breakeven)
        if self._breakeven_activated:
            ema = self._get_ema(idx)
            if not np.isnan(ema):
                if self._trade_side == "long" and close < ema:
                    self._in_trade = False
                    return Signal.SELL
                elif self._trade_side == "short" and close > ema:
                    self._in_trade = False
                    return Signal.BUY

        return Signal.HOLD

    # --- Indicator accessors ---

    def _get_vwap(self, idx: int) -> float:
        if self._prepared and self._vwap_precomputed is not None:
            return self._vwap_precomputed[idx]
        return np.nan

    def _get_vwap_slope(self, idx: int) -> float:
        if self._prepared and self._vwap_slope_precomputed is not None:
            return self._vwap_slope_precomputed[idx]
        return 0.0

    def _get_atr(self, idx: int) -> float:
        if self._prepared and self._atr_arr is not None:
            val = self._atr_arr[idx]
            return 0.0 if np.isnan(val) else val
        return 0.0

    def _get_ema(self, idx: int) -> float:
        if self._prepared and self._ema_arr is not None:
            return self._ema_arr[idx]
        return np.nan

    def _get_structure_up(self, idx: int) -> bool:
        if self._prepared and self._structure_up is not None:
            return bool(self._structure_up[idx])
        return True  # default: no filter

    def _get_structure_down(self, idx: int) -> bool:
        if self._prepared and self._structure_down is not None:
            return bool(self._structure_down[idx])
        return True

    def reset(self) -> None:
        super().reset()
        self._reset_trade_state()
        self._in_pullback = False
        self._trend_was_up = False
        self._trend_was_down = False
        self._pullback_swing_low = np.inf
        self._pullback_swing_high = -np.inf
        self._atr_arr = None
        self._ema_arr = None
        self._vwap_precomputed = None
        self._vwap_slope_precomputed = None
        self._structure_up = None
        self._structure_down = None
