"""
Multi-indicator Confluence Strategy.

Scores 6 independent technical signals and only enters when multiple
indicators align (confluence). Long-only — designed for BTC swing trading
on 1H candles with 4H and Daily higher-timeframe confirmation.

Scoring system (0-2 points each, max 12):
  1. EMA Trend      — price vs 50 & 200 EMA
  2. Fibonacci       — bounce off key retracement levels of recent swing
  3. Trendline       — price vs auto-detected swing-low trendline
  4. RSI Divergence  — bullish divergence or oversold recovery
  5. S/R Retest      — breakout above resistance, retest as support
  6. HTF Confluence  — 4H and Daily trend alignment

Entry: total score >= entry_threshold (default 7)
Exit:  total score <= exit_threshold  (default 3)

Why confluence works:
  Any single indicator can give false signals. But when 5+ independent
  indicators agree (EMA trend is up, price is at a fib level, RSI shows
  bullish divergence, S/R confirms, and higher timeframes agree), the
  probability of a successful trade is significantly higher. This is
  how institutional traders combine signals — each indicator is a "vote"
  and you only act when there's strong consensus.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import ta

from strategies.base import Signal, Strategy


class ConfluenceStrategy(Strategy):
    """Multi-indicator confluence scoring strategy (long only)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)

        # EMA params
        self.ema_fast: int = self.params.get("ema_fast", 50)
        self.ema_slow: int = self.params.get("ema_slow", 200)

        # RSI params
        self.rsi_period: int = self.params.get("rsi_period", 14)
        self.rsi_oversold: float = self.params.get("rsi_oversold", 30.0)
        self.rsi_div_lookback: int = self.params.get("rsi_div_lookback", 20)

        # Fibonacci params
        self.fib_swing_lookback: int = self.params.get("fib_swing_lookback", 100)
        self.fib_tolerance: float = self.params.get("fib_tolerance", 0.01)

        # Support/Resistance params
        self.sr_lookback: int = self.params.get("sr_lookback", 50)
        self.sr_tolerance: float = self.params.get("sr_tolerance", 0.005)

        # Trendline params
        self.tl_swing_lookback: int = self.params.get("tl_swing_lookback", 5)
        self.tl_min_swings: int = self.params.get("tl_min_swings", 3)
        self.tl_tolerance: float = self.params.get("tl_tolerance", 0.005)

        # Scoring thresholds
        self.entry_threshold: int = self.params.get("entry_threshold", 7)
        self.exit_threshold: int = self.params.get("exit_threshold", 3)

        # Pre-computed arrays
        self._ema_fast_arr: np.ndarray | None = None
        self._ema_slow_arr: np.ndarray | None = None
        self._rsi_arr: np.ndarray | None = None
        self._close_arr: np.ndarray | None = None
        self._high_arr: np.ndarray | None = None
        self._low_arr: np.ndarray | None = None

        # 4H arrays
        self._ema_50_4h: np.ndarray | None = None
        self._ema_200_4h: np.ndarray | None = None
        self._close_4h: np.ndarray | None = None

        # Daily arrays
        self._ema_50_1d: np.ndarray | None = None
        self._ema_200_1d: np.ndarray | None = None
        self._close_1d: np.ndarray | None = None

        # Trade state
        self._in_trade: bool = False

    @property
    def name(self) -> str:
        return "confluence"

    @property
    def warmup_period(self) -> int:
        # 200 EMA on Daily needs ~200*24 = 4800 hourly bars, but we use
        # a mapped approach. Still need enough 1H bars for 200 EMA + fib lookback.
        return self.ema_slow + self.fib_swing_lookback + 10

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute all indicators on 1H data + resample to 4H and Daily."""
        close = data["close"]
        high = data["high"]
        low = data["low"]

        self._close_arr = close.to_numpy()
        self._high_arr = high.to_numpy()
        self._low_arr = low.to_numpy()

        # --- 1H indicators ---
        self._ema_fast_arr = ta.trend.ema_indicator(close, window=self.ema_fast).to_numpy()
        self._ema_slow_arr = ta.trend.ema_indicator(close, window=self.ema_slow).to_numpy()
        self._rsi_arr = ta.momentum.rsi(close, window=self.rsi_period).to_numpy()

        # --- Resample to 4H ---
        data_ts = data.copy()
        data_ts["timestamp"] = pd.to_datetime(data_ts["timestamp"])
        data_ts = data_ts.set_index("timestamp")

        resampled_4h = data_ts.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        ema_50_4h = ta.trend.ema_indicator(resampled_4h["close"], window=self.ema_fast)
        ema_200_4h = ta.trend.ema_indicator(resampled_4h["close"], window=self.ema_slow)

        self._ema_50_4h = ema_50_4h.reindex(data_ts.index, method="ffill").to_numpy()
        self._ema_200_4h = ema_200_4h.reindex(data_ts.index, method="ffill").to_numpy()
        self._close_4h = resampled_4h["close"].reindex(data_ts.index, method="ffill").to_numpy()

        # --- Resample to Daily ---
        resampled_1d = data_ts.resample("1D").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        ema_50_1d = ta.trend.ema_indicator(resampled_1d["close"], window=self.ema_fast)
        ema_200_1d = ta.trend.ema_indicator(resampled_1d["close"], window=self.ema_slow)

        self._ema_50_1d = ema_50_1d.reindex(data_ts.index, method="ffill").to_numpy()
        self._ema_200_1d = ema_200_1d.reindex(data_ts.index, method="ffill").to_numpy()
        self._close_1d = resampled_1d["close"].reindex(data_ts.index, method="ffill").to_numpy()

        self._prepared = True

    # ------------------------------------------------------------------
    # Scoring modules
    # ------------------------------------------------------------------

    def _score_ema_trend(self, idx: int) -> int:
        """EMA Trend: +1 price > 50 EMA, +1 price > 200 EMA."""
        close = self._close_arr[idx]
        ema_fast = self._ema_fast_arr[idx]
        ema_slow = self._ema_slow_arr[idx]

        if np.isnan(ema_fast) or np.isnan(ema_slow):
            return 0

        score = 0
        if close > ema_fast:
            score += 1
        if close > ema_slow:
            score += 1
        return score

    def _score_fibonacci(self, idx: int) -> int:
        """Fibonacci: score based on proximity to key fib retracement levels.

        Finds the recent swing high/low and checks if current price is
        near the 0.382, 0.5, or 0.618 retracement level (bounce zone).
        """
        if idx < self.fib_swing_lookback:
            return 0

        window_high = self._high_arr[idx - self.fib_swing_lookback: idx]
        window_low = self._low_arr[idx - self.fib_swing_lookback: idx]

        swing_high = np.max(window_high)
        swing_low = np.min(window_low)
        swing_range = swing_high - swing_low

        if swing_range < 1e-8:
            return 0

        close = self._close_arr[idx]

        # Fib retracement levels (measured from swing high downward)
        fib_levels = {
            0.382: swing_high - 0.382 * swing_range,
            0.500: swing_high - 0.500 * swing_range,
            0.618: swing_high - 0.618 * swing_range,
        }

        tol = self.fib_tolerance * close

        # Check proximity to fib levels (bullish = bouncing UP from fib)
        for level, price in fib_levels.items():
            if abs(close - price) < tol:
                # Near a fib level — check if price is bouncing (close > open-ish)
                prev_close = self._close_arr[idx - 1]
                if close >= prev_close:  # Price recovering
                    if level == 0.618:
                        return 2  # Golden ratio — strongest
                    return 1  # 0.382 or 0.5

        # Also: if price is above the 0.382 level, mild bullish signal
        if close > fib_levels[0.382]:
            return 1

        return 0

    def _score_trendline(self, idx: int) -> int:
        """Trendline: auto-detect rising trendline from swing lows.

        Finds recent swing lows using a simple pivot detection, fits a
        line through the lowest points, and scores based on price position.
        """
        lookback = min(idx, self.fib_swing_lookback)
        if lookback < 20:
            return 0

        lows = self._low_arr[idx - lookback: idx + 1]
        swing_dist = self.tl_swing_lookback

        # Find swing lows (local minima)
        swing_low_indices = []
        swing_low_prices = []
        for i in range(swing_dist, len(lows) - 1):
            window = lows[max(0, i - swing_dist): i + swing_dist + 1]
            if lows[i] == np.min(window):
                swing_low_indices.append(i)
                swing_low_prices.append(lows[i])

        if len(swing_low_indices) < 2:
            return 0

        # Use the last few swing lows to define the trendline
        sl_idx = np.array(swing_low_indices[-self.tl_min_swings:])
        sl_prices = np.array(swing_low_prices[-self.tl_min_swings:])

        if len(sl_idx) < 2:
            return 0

        # Linear regression through swing lows
        slope, intercept = np.polyfit(sl_idx, sl_prices, 1)

        # Trendline value at current bar
        current_bar = len(lows) - 1
        tl_value = slope * current_bar + intercept

        close = self._close_arr[idx]
        tol = self.tl_tolerance * close

        if slope <= 0:
            # Downtrend trendline — not bullish
            return 0

        if close > tl_value + tol:
            return 2  # Clearly above rising trendline
        elif close > tl_value - tol:
            return 1  # Near the trendline (potential bounce)

        return 0

    def _score_rsi_divergence(self, idx: int) -> int:
        """RSI Divergence: bullish divergence or oversold recovery.

        +2: Bullish divergence — price made lower low but RSI made higher low
        +1: RSI recovering from oversold (< 30 → now rising)
        """
        if idx < self.rsi_div_lookback:
            return 0

        rsi = self._rsi_arr[idx]
        if np.isnan(rsi):
            return 0

        lookback = self.rsi_div_lookback
        close_window = self._close_arr[idx - lookback: idx + 1]
        rsi_window = self._rsi_arr[idx - lookback: idx + 1]

        # Remove NaNs
        valid = ~np.isnan(rsi_window)
        if np.sum(valid) < lookback // 2:
            return 0

        # Find two recent price lows in the window
        half = lookback // 2
        first_half_low_idx = np.argmin(close_window[:half])
        second_half_low_idx = half + np.argmin(close_window[half:])

        price_low_1 = close_window[first_half_low_idx]
        price_low_2 = close_window[second_half_low_idx]
        rsi_low_1 = rsi_window[first_half_low_idx]
        rsi_low_2 = rsi_window[second_half_low_idx]

        if np.isnan(rsi_low_1) or np.isnan(rsi_low_2):
            return 0

        # Bullish divergence: price lower low, RSI higher low
        if price_low_2 < price_low_1 and rsi_low_2 > rsi_low_1 + 2:
            return 2

        # RSI oversold recovery
        rsi_recent = self._rsi_arr[max(0, idx - 5): idx + 1]
        if np.any(rsi_recent < self.rsi_oversold) and rsi > self.rsi_oversold:
            return 1

        return 0

    def _score_sr_retest(self, idx: int) -> int:
        """Support/Resistance: breakout above resistance, then retest as support.

        Identifies key S/R levels from recent pivot highs/lows, then checks
        if price has broken above a level and is retesting it from above.
        """
        lookback = min(idx, self.sr_lookback)
        if lookback < 20:
            return 0

        highs = self._high_arr[idx - lookback: idx]
        lows = self._low_arr[idx - lookback: idx]
        close = self._close_arr[idx]

        # Find pivot highs (resistance levels)
        pivot_dist = 5
        resistance_levels = []
        for i in range(pivot_dist, len(highs) - pivot_dist):
            window = highs[i - pivot_dist: i + pivot_dist + 1]
            if highs[i] == np.max(window):
                resistance_levels.append(highs[i])

        # Find pivot lows (support levels)
        support_levels = []
        for i in range(pivot_dist, len(lows) - pivot_dist):
            window = lows[i - pivot_dist: i + pivot_dist + 1]
            if lows[i] == np.min(window):
                support_levels.append(lows[i])

        tol = self.sr_tolerance * close

        # Check for breakout + retest: price above a former resistance,
        # now using it as support (close near the level from above)
        for level in resistance_levels:
            if close > level and abs(close - level) < tol * 3:
                # Price is just above former resistance — retest as support
                return 2

        # Check if price is above any key support level (bullish)
        for level in support_levels[-3:]:  # Recent supports
            if abs(close - level) < tol:
                return 1  # Near support — potential bounce

        # Price above most recent resistance levels = breakout
        if resistance_levels and close > max(resistance_levels[-3:]):
            return 1

        return 0

    def _score_htf_confluence(self, idx: int) -> int:
        """Higher Timeframe: +1 if 4H bullish, +1 if Daily bullish.

        Bullish = close > 50 EMA on that timeframe.
        """
        score = 0

        # 4H
        if (self._close_4h is not None and self._ema_50_4h is not None
                and not np.isnan(self._ema_50_4h[idx])
                and not np.isnan(self._close_4h[idx])):
            if self._close_4h[idx] > self._ema_50_4h[idx]:
                score += 1

        # Daily
        if (self._close_1d is not None and self._ema_50_1d is not None
                and not np.isnan(self._ema_50_1d[idx])
                and not np.isnan(self._close_1d[idx])):
            if self._close_1d[idx] > self._ema_50_1d[idx]:
                score += 1

        return score

    # ------------------------------------------------------------------
    # Main signal logic
    # ------------------------------------------------------------------

    def _compute_score(self, idx: int) -> tuple[int, dict[str, int]]:
        """Compute total confluence score and individual breakdowns."""
        scores = {
            "ema_trend": self._score_ema_trend(idx),
            "fibonacci": self._score_fibonacci(idx),
            "trendline": self._score_trendline(idx),
            "rsi_divergence": self._score_rsi_divergence(idx),
            "sr_retest": self._score_sr_retest(idx),
            "htf_confluence": self._score_htf_confluence(idx),
        }
        return sum(scores.values()), scores

    def on_candle(self, candle: dict) -> Signal:
        """Process a 1H candle. BUY on high confluence, SELL when it fades."""
        self._add_candle(candle)
        idx = self._candle_index - 1

        if idx < self.warmup_period or not self._prepared:
            return Signal.HOLD

        total, _breakdown = self._compute_score(idx)

        if self._in_trade:
            if total <= self.exit_threshold:
                self._in_trade = False
                return Signal.SELL
            return Signal.HOLD
        else:
            if total >= self.entry_threshold:
                self._in_trade = True
                return Signal.BUY
            return Signal.HOLD

    def reset(self) -> None:
        super().reset()
        self._in_trade = False
        self._ema_fast_arr = None
        self._ema_slow_arr = None
        self._rsi_arr = None
        self._close_arr = None
        self._high_arr = None
        self._low_arr = None
        self._ema_50_4h = None
        self._ema_200_4h = None
        self._close_4h = None
        self._ema_50_1d = None
        self._ema_200_1d = None
        self._close_1d = None
