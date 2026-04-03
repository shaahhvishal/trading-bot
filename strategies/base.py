"""
Abstract base class for all strategies.

Every strategy receives candles one at a time via on_candle() and returns
a Signal. This same interface is used for both backtesting and live trading,
so the strategy never knows (or cares) which mode it's running in.

For backtesting performance, strategies can override prepare() to pre-compute
indicators on the full dataset. on_candle() then does a cheap lookup instead
of recalculating from scratch on every candle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import pandas as pd


class Signal(Enum):
    """Trading signal emitted by a strategy."""

    BUY = "BUY"      # Open/add to long position
    SELL = "SELL"     # Open/add to short position
    HOLD = "HOLD"     # Do nothing


class Strategy(ABC):
    """Base class all strategies must inherit from."""

    # Max candles to keep in memory for live trading mode.
    MAX_HISTORY: int = 300

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Initialize with optional parameter overrides.

        Args:
            params: Strategy-specific parameters (from settings.yaml).
        """
        self.params = params or {}
        self._history: list[dict] = []
        self._candle_index: int = 0
        self._prepared: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        ...

    @property
    def warmup_period(self) -> int:
        """Number of candles needed before the strategy can emit real signals.

        Override this in subclasses. The backtester skips signals during warmup.
        """
        return 0

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute indicators on the full dataset for fast backtesting.

        Override this in subclasses. Called by the backtest engine before the
        main loop. In live mode this is NOT called — on_candle() falls back
        to incremental computation.

        Args:
            data: Full OHLCV DataFrame.
        """
        self._prepared = False

    def _add_candle(self, candle: dict) -> None:
        """Append candle to internal history buffer (capped at MAX_HISTORY)."""
        self._history.append(candle)
        self._candle_index += 1
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

    def _closes(self) -> pd.Series:
        """Return close prices as a pandas Series (for indicator math)."""
        return pd.Series([c["close"] for c in self._history])

    @abstractmethod
    def on_candle(self, candle: dict) -> Signal:
        """Process a new candle and return a trading signal.

        Args:
            candle: Dict with keys: timestamp, open, high, low, close, volume.

        Returns:
            Signal.BUY, Signal.SELL, or Signal.HOLD.
        """
        ...

    def reset(self) -> None:
        """Clear internal state. Called between backtest runs."""
        self._history.clear()
        self._candle_index = 0
        self._prepared = False
