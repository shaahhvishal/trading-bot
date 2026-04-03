"""
Candle color prediction strategy for prediction markets.

Predicts whether the NEXT 15m BTC candle will be green or red.
Only bets when multiple oversold signals align (high-confidence GREEN).

Proven edge (OOS Sep-Dec 2024):
  - 55.5% accuracy at confidence >= 4.0 (335 bets over 4 months)
  - Profitable at 1.90x+ payout
  - Core signal: mean reversion after extreme selling

Signals scored:
  1. RSI < 20 (+2), RSI < 30 (+1)       — oversold mean reversion
  2. Momentum_5 < -0.5 (+1.5), < -0.3 (+1) — negative momentum bounce
  3. Volume 1.5-2.5x avg (+1)           — high volume = conviction
  4. BB position < -2σ (+1)              — below lower band
  5. Big red + high range (+1)           — range exhaustion reversal
  6. Red streak 3+ (+0.5)               — streak mean reversion

Only predicts GREEN when score >= min_confidence (default 4.0).
RED predictions showed no edge — skipped entirely.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from strategies.base import Signal, Strategy


class Prediction:
    """Represents a candle color prediction."""

    GREEN = "green"
    RED = "red"
    SKIP = "skip"

    def __init__(self, direction: str, confidence: float, signals: list[str]) -> None:
        self.direction = direction
        self.confidence = confidence
        self.signals = signals

    @property
    def should_bet(self) -> bool:
        return self.direction != self.SKIP

    def __repr__(self) -> str:
        if not self.should_bet:
            return "Prediction(SKIP)"
        return f"Prediction({self.direction.upper()}, conf={self.confidence:.1f}, signals={self.signals})"


class CandlePredictorStrategy:
    """Predicts next 15m candle color for prediction markets.

    Not a trading strategy (doesn't emit BUY/SELL/HOLD).
    Instead, call predict() after each candle to get a Prediction.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}
        self.min_confidence: float = self.params.get("min_confidence", 4.0)
        self.rsi_period: int = self.params.get("rsi_period", 14)
        self.momentum_lookback: int = self.params.get("momentum_lookback", 5)
        self.vol_ma_period: int = self.params.get("vol_ma_period", 20)
        self.bb_period: int = self.params.get("bb_period", 20)

        self._warmup = max(self.rsi_period, self.vol_ma_period, self.bb_period, self.momentum_lookback) + 5
        self._history: deque[dict] = deque(maxlen=300)

        # RSI state (incremental Wilder's smoothing)
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._rsi_initialized: bool = False
        self._rsi: float = 50.0

        # Running volume MA
        self._volumes: deque[float] = deque(maxlen=self.vol_ma_period)

        # BB state
        self._closes_bb: deque[float] = deque(maxlen=self.bb_period)

        # Momentum (last N body percentages)
        self._bodies: deque[float] = deque(maxlen=self.momentum_lookback)

        # Streak tracking
        self._streak: int = 0
        self._prev_green: bool | None = None

    @property
    def name(self) -> str:
        return "candle_predictor"

    @property
    def warmup_period(self) -> int:
        return self._warmup

    def on_candle(self, candle: dict) -> Prediction:
        """Process a 15m candle and predict the NEXT candle's color.

        Call this as each candle closes. The returned Prediction
        is for the candle that hasn't started yet.

        Args:
            candle: dict with open, high, low, close, volume, timestamp.

        Returns:
            Prediction with direction, confidence, and signal list.
        """
        self._history.append(candle)
        o, h, l, c, v = candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]

        # Update body % for momentum
        body_pct = (c - o) / o * 100 if o > 0 else 0.0
        self._bodies.append(body_pct)

        # Update RSI (Wilder's smoothing)
        self._update_rsi(c)

        # Update volume deque
        self._volumes.append(v)

        # Update BB closes
        self._closes_bb.append(c)

        # Update streak
        is_green = c > o
        if self._prev_green is not None:
            if is_green == self._prev_green:
                self._streak += 1 if is_green else -1
            else:
                self._streak = 1 if is_green else -1
        else:
            self._streak = 1 if is_green else -1
        self._prev_green = is_green

        # Need enough history
        if len(self._history) < self._warmup:
            return Prediction(Prediction.SKIP, 0, ["warmup"])

        # Compute features
        rsi = self._rsi
        momentum = sum(self._bodies) if len(self._bodies) == self.momentum_lookback else 0.0
        vol_ma = sum(self._volumes) / len(self._volumes) if self._volumes else 1.0
        vol_ratio = v / vol_ma if vol_ma > 0 else 1.0

        bb_mean = sum(self._closes_bb) / len(self._closes_bb) if self._closes_bb else c
        bb_std = (sum((x - bb_mean) ** 2 for x in self._closes_bb) / len(self._closes_bb)) ** 0.5 if len(self._closes_bb) >= 2 else 1.0
        bb_position = (c - bb_mean) / (bb_std + 1e-10)

        range_pct = (h - l) / o * 100 if o > 0 else 0.0
        closes_list = [candle["close"] for candle in self._history]
        if len(closes_list) >= 14:
            recent_ranges = []
            hist_list = list(self._history)
            for i in range(-14, 0):
                r = (hist_list[i]["high"] - hist_list[i]["low"]) / hist_list[i]["open"] * 100 if hist_list[i]["open"] > 0 else 0
                recent_ranges.append(r)
            atr = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 1.0
        else:
            atr = range_pct
        range_ratio = range_pct / (atr + 1e-10)

        # Score signals — only GREEN (RED showed no edge)
        score = 0.0
        signals = []

        # Signal 1: RSI oversold
        if rsi < 20:
            score += 2
            signals.append(f"RSI={rsi:.0f}<20")
        elif rsi < 30:
            score += 1
            signals.append(f"RSI={rsi:.0f}<30")

        # Signal 2: Negative momentum
        if momentum < -0.5:
            score += 1.5
            signals.append(f"Mom5={momentum:.2f}<-0.5")
        elif momentum < -0.3:
            score += 1
            signals.append(f"Mom5={momentum:.2f}<-0.3")

        # Signal 3: High volume
        if 1.5 <= vol_ratio <= 2.5:
            score += 1
            signals.append(f"Vol={vol_ratio:.1f}x")

        # Signal 4: Below -2σ Bollinger Band
        if bb_position < -2:
            score += 1
            signals.append(f"BB={bb_position:.1f}σ")

        # Signal 5: Big red candle + high range
        if range_ratio > 1.5 and body_pct < -0.2:
            score += 1
            signals.append(f"BigRed={body_pct:.2f}%,Range={range_ratio:.1f}x")

        # Signal 6: Red streak
        if self._streak <= -3:
            score += 0.5
            signals.append(f"Streak={self._streak}")

        # Decision
        if score >= self.min_confidence:
            return Prediction(Prediction.GREEN, score, signals)

        return Prediction(Prediction.SKIP, score, signals)

    def _update_rsi(self, close: float) -> None:
        """Incrementally update RSI using Wilder's smoothing."""
        if len(self._history) < 2:
            return

        prev_close = self._history[-2]["close"]
        delta = close - prev_close

        if not self._rsi_initialized:
            if len(self._history) < self.rsi_period + 1:
                return

            # Initial RSI: simple average of first N periods
            gains = []
            losses = []
            hist = list(self._history)
            for i in range(-self.rsi_period, 0):
                d = hist[i]["close"] - hist[i - 1]["close"]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))

            self._avg_gain = sum(gains) / self.rsi_period
            self._avg_loss = sum(losses) / self.rsi_period
            self._rsi_initialized = True
        else:
            # Wilder's smoothing
            gain = max(delta, 0)
            loss = max(-delta, 0)
            self._avg_gain = (self._avg_gain * (self.rsi_period - 1) + gain) / self.rsi_period
            self._avg_loss = (self._avg_loss * (self.rsi_period - 1) + loss) / self.rsi_period

        if self._avg_loss == 0:
            self._rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self._rsi = 100 - (100 / (1 + rs))

    def reset(self) -> None:
        """Clear all state."""
        self._history.clear()
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._rsi_initialized = False
        self._rsi = 50.0
        self._volumes.clear()
        self._closes_bb.clear()
        self._bodies.clear()
        self._streak = 0
        self._prev_green = None
