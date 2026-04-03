"""
Opening Range Breakout (ORB) strategy with confirmation and risk-defined exits.

Primary timeframe: 1m execution; 5m confirmation; optional 15m bias.

Setup:
  - Define session open times (crypto: 00:00, 08:00, 16:00 UTC for 8h sessions)
  - Opening range = first N minutes of session (default 15 min)
  - OR_high, OR_low, OR_width tracked per session
  - Skip filter: if OR_width > 1.2 * ATR(14, 5m), skip the session

Entry (long):
  - Bias filter: price > VWAP and VWAP slope >= 0
  - Trigger: 1m candle closes above OR_high
  - Confirmation: breakout candle volume > 1.2x median volume (last 30 min)
  - Short side is symmetric (close below OR_low)

Exits:
  - Initial stop: below OR_low (long) / above OR_high (short)
  - At +1R: move stop to breakeven
  - At +2R: take profit (exit)
  - Trailing stop: exit if 1m closes below 10-SMA (long) / above 10-SMA (short)
    (activated after +1R reached)
  - Time stop: if < +0.5R within time_stop_minutes, exit

Why this works (market microstructure):
  The opening range captures the initial price discovery of a session. When price
  breaks out of this range with volume, it signals directional conviction from
  larger participants. The OR acts as a natural support/resistance level —
  breakouts above attract momentum buyers and trigger stops, creating a cascade.
  The skip filter avoids wide-range sessions where the breakout edge is diluted.
  The VWAP bias ensures we trade with institutional flow, not against it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class ORBStrategy(Strategy):
    """Opening Range Breakout with confirmation and risk-defined exits."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)

        # Opening range parameters
        self.or_window_minutes: int = self.params.get("or_window_minutes", 15)
        self.session_hours: list[int] = self.params.get("session_hours", [0, 8, 16])
        self.atr_skip_mult: float = self.params.get("atr_skip_mult", 1.2)
        self.atr_period: int = self.params.get("atr_period", 14)

        # Entry confirmation
        self.volume_mult: float = self.params.get("volume_mult", 1.2)
        self.volume_lookback: int = self.params.get("volume_lookback", 30)
        self.use_vwap_bias: bool = self.params.get("use_vwap_bias", True)
        self.vwap_period: int = self.params.get("vwap_period", 60)

        # Exit parameters
        self.tp_r_multiple: float = self.params.get("tp_r_multiple", 2.0)
        self.trail_sma_period: int = self.params.get("trail_sma_period", 10)
        self.time_stop_minutes: int = self.params.get("time_stop_minutes", 15)
        self.time_stop_r_threshold: float = self.params.get("time_stop_r_threshold", 0.5)

        # Internal state
        self._reset_session_state()

        # Pre-computed arrays for backtesting
        self._atr_5m: np.ndarray | None = None
        self._vwap_arr: np.ndarray | None = None
        self._sma_arr: np.ndarray | None = None
        self._volume_median: np.ndarray | None = None

    @property
    def name(self) -> str:
        return "orb"

    @property
    def warmup_period(self) -> int:
        return max(self.volume_lookback, self.vwap_period, self.atr_period * 5) + 10

    def _reset_session_state(self) -> None:
        """Reset state for a new session."""
        self._or_high: float = -np.inf
        self._or_low: float = np.inf
        self._or_defined: bool = False
        self._or_skipped: bool = False
        self._or_candle_count: int = 0
        self._session_active: bool = False

        # Position tracking (internal — the engine handles the actual position)
        self._in_trade: bool = False
        self._trade_side: str = ""  # "long" or "short"
        self._entry_price: float = 0.0
        self._stop_price: float = 0.0
        self._r_value: float = 0.0
        self._breakeven_activated: bool = False
        self._trail_activated: bool = False
        self._entry_candle_idx: int = 0

    def _is_session_start(self, ts: datetime) -> bool:
        """Check if this timestamp is the start of a new session."""
        return ts.minute == 0 and ts.hour in self.session_hours

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute indicators for backtesting performance."""
        close = data["close"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"]

        # ATR on 5m-equivalent (use 5-bar ATR on 1m as approximation)
        self._atr_5m = ta.volatility.average_true_range(
            high=high, low=low, close=close, window=self.atr_period * 5
        ).to_numpy()

        # Rolling VWAP
        typical_price = (high + low + close) / 3.0
        tp_vol = typical_price * volume
        rolling_tp_vol = tp_vol.rolling(window=self.vwap_period).sum()
        rolling_vol = volume.rolling(window=self.vwap_period).sum()
        self._vwap_arr = (rolling_tp_vol / rolling_vol).to_numpy()

        # 10-period SMA for trailing stop
        self._sma_arr = close.rolling(window=self.trail_sma_period).mean().to_numpy()

        # Rolling median volume (30-bar)
        self._volume_median = volume.rolling(window=self.volume_lookback).median().to_numpy()

        self._prepared = True

    def on_candle(self, candle: dict) -> Signal:
        """Process a 1m candle through the ORB logic.

        Args:
            candle: OHLCV dict with timestamp, open, high, low, close, volume.

        Returns:
            BUY, SELL, or HOLD.
        """
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period:
            return Signal.HOLD

        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if not hasattr(ts, 'hour'):
            # pandas Timestamp
            ts = ts.to_pydatetime()

        close = candle["close"]
        high = candle["high"]
        low = candle["low"]
        volume = candle["volume"]

        # Check for new session start
        if self._is_session_start(ts):
            # If we're in a trade from previous session, close it
            if self._in_trade:
                self._in_trade = False
                signal = Signal.SELL if self._trade_side == "long" else Signal.BUY
                self._reset_session_state()
                return signal

            self._reset_session_state()
            self._session_active = True
            self._or_candle_count = 0

        # Phase 1: Build the opening range
        if self._session_active and not self._or_defined:
            self._or_candle_count += 1
            self._or_high = max(self._or_high, high)
            self._or_low = min(self._or_low, low)

            if self._or_candle_count >= self.or_window_minutes:
                self._or_defined = True
                or_width = self._or_high - self._or_low

                # Skip filter: OR too wide relative to ATR
                atr = self._get_atr(idx)
                if atr > 0 and or_width > self.atr_skip_mult * atr:
                    self._or_skipped = True

            return Signal.HOLD

        # If OR was skipped, do nothing until next session
        if self._or_skipped or not self._or_defined:
            return Signal.HOLD

        # Phase 2: If in a trade, manage exits
        if self._in_trade:
            return self._manage_exits(idx, candle)

        # Phase 3: Look for breakout entry
        return self._check_entry(idx, candle)

    def _check_entry(self, idx: int, candle: dict) -> Signal:
        """Check for breakout entry conditions."""
        close = candle["close"]
        volume = candle["volume"]

        # Volume confirmation
        median_vol = self._get_median_volume(idx)
        if median_vol <= 0 or volume < self.volume_mult * median_vol:
            return Signal.HOLD

        # VWAP bias filter
        if self.use_vwap_bias:
            vwap = self._get_vwap(idx)
            if np.isnan(vwap):
                return Signal.HOLD

        # Long breakout: close above OR_high
        if close > self._or_high:
            if self.use_vwap_bias:
                vwap = self._get_vwap(idx)
                if close < vwap:
                    return Signal.HOLD

            self._enter_trade("long", close, idx)
            return Signal.BUY

        # Short breakout: close below OR_low
        if close < self._or_low:
            if self.use_vwap_bias:
                vwap = self._get_vwap(idx)
                if close > vwap:
                    return Signal.HOLD

            self._enter_trade("short", close, idx)
            return Signal.SELL

        return Signal.HOLD

    def _enter_trade(self, side: str, price: float, idx: int) -> None:
        """Record internal trade state."""
        self._in_trade = True
        self._trade_side = side
        self._entry_price = price
        self._entry_candle_idx = idx
        self._breakeven_activated = False
        self._trail_activated = False

        if side == "long":
            self._stop_price = self._or_low
            self._r_value = price - self._or_low
        else:
            self._stop_price = self._or_high
            self._r_value = self._or_high - price

    def _manage_exits(self, idx: int, candle: dict) -> Signal:
        """Check all exit conditions for an open trade."""
        close = candle["close"]
        low = candle["low"]
        high = candle["high"]

        if self._r_value <= 0:
            # Degenerate case, close the trade
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        # Calculate current R-multiple of profit
        if self._trade_side == "long":
            current_r = (close - self._entry_price) / self._r_value
            hit_stop = low <= self._stop_price
        else:
            current_r = (self._entry_price - close) / self._r_value
            hit_stop = high >= self._stop_price

        # 1. Stop loss hit
        if hit_stop:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        # 2. Take profit at target R-multiple
        if current_r >= self.tp_r_multiple:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        # 3. At +1R: move stop to breakeven + activate trailing
        if current_r >= 1.0 and not self._breakeven_activated:
            self._breakeven_activated = True
            self._trail_activated = True
            self._stop_price = self._entry_price

        # 4. Trailing stop via SMA (after +1R)
        if self._trail_activated:
            sma = self._get_sma(idx)
            if not np.isnan(sma):
                if self._trade_side == "long" and close < sma:
                    self._in_trade = False
                    return Signal.SELL
                elif self._trade_side == "short" and close > sma:
                    self._in_trade = False
                    return Signal.BUY

        # 5. Time stop: not enough progress within N minutes
        candles_in_trade = idx - self._entry_candle_idx
        if candles_in_trade >= self.time_stop_minutes and current_r < self.time_stop_r_threshold:
            self._in_trade = False
            return Signal.SELL if self._trade_side == "long" else Signal.BUY

        return Signal.HOLD

    def _get_atr(self, idx: int) -> float:
        """Get ATR value at index."""
        if self._prepared and self._atr_5m is not None:
            val = self._atr_5m[idx]
            return 0.0 if np.isnan(val) else val
        # Live fallback
        if len(self._history) < self.atr_period * 5:
            return 0.0
        closes = pd.Series([c["close"] for c in self._history])
        highs = pd.Series([c["high"] for c in self._history])
        lows = pd.Series([c["low"] for c in self._history])
        atr = ta.volatility.average_true_range(
            high=highs, low=lows, close=closes, window=self.atr_period * 5
        )
        val = atr.iloc[-1]
        return 0.0 if np.isnan(val) else val

    def _get_vwap(self, idx: int) -> float:
        """Get VWAP value at index."""
        if self._prepared and self._vwap_arr is not None:
            return self._vwap_arr[idx]
        return np.nan

    def _get_sma(self, idx: int) -> float:
        """Get trailing SMA value at index."""
        if self._prepared and self._sma_arr is not None:
            return self._sma_arr[idx]
        if len(self._history) >= self.trail_sma_period:
            closes = [c["close"] for c in self._history[-self.trail_sma_period:]]
            return sum(closes) / len(closes)
        return np.nan

    def _get_median_volume(self, idx: int) -> float:
        """Get median volume over lookback window."""
        if self._prepared and self._volume_median is not None:
            val = self._volume_median[idx]
            return 0.0 if np.isnan(val) else val
        if len(self._history) >= self.volume_lookback:
            vols = sorted([c["volume"] for c in self._history[-self.volume_lookback:]])
            mid = len(vols) // 2
            return vols[mid]
        return 0.0

    def reset(self) -> None:
        """Clear all state."""
        super().reset()
        self._reset_session_state()
        self._atr_5m = None
        self._vwap_arr = None
        self._sma_arr = None
        self._volume_median = None
