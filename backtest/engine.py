"""
Event-driven backtesting engine.

Processes candles one at a time, passing each to the strategy and managing
positions based on the returned signal. This is intentionally NOT vectorized —
event-driven backtesting is slower but much more realistic because:

1. The strategy only sees data up to the current candle (no lookahead bias)
2. Position management logic mirrors what happens in live trading
3. Fees and slippage are applied per-trade, not as a post-hoc adjustment

The engine tracks: portfolio value, open positions, completed trades, and
builds an equity curve for metric calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

from backtest.metrics import BacktestResult, calculate_metrics
from strategies.base import Signal, Strategy


@dataclass
class Position:
    """Represents an open position."""

    side: str            # "long" or "short"
    entry_price: float
    entry_time: pd.Timestamp
    size: float          # in quote currency (USD value)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    initial_capital: float = 10_000.0
    taker_fee: float = 0.0005       # 0.05%
    position_size_pct: float = 1.0  # fraction of capital to use per trade
    long_only: bool = False         # if True, SELL only closes longs (no shorts)


class BacktestEngine:
    """Core backtesting loop.

    Usage:
        engine = BacktestEngine(config)
        result = engine.run(strategy, data)
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self._reset()

    def _reset(self) -> None:
        """Reset engine state for a fresh run."""
        self.capital = self.config.initial_capital
        self.position: Position | None = None
        self.trades: list[dict] = []
        self.equity_curve: list[float] = []

    def run(self, strategy: Strategy, data: pd.DataFrame) -> BacktestResult:
        """Run a backtest over historical data.

        Args:
            strategy: Strategy instance (will be reset before run).
            data: DataFrame with columns [timestamp, open, high, low, close, volume].

        Returns:
            BacktestResult with all performance metrics.
        """
        self._reset()
        strategy.reset()

        logger.info(
            f"Starting backtest: {strategy.name} | "
            f"Capital: ${self.config.initial_capital:,.0f} | "
            f"Fee: {self.config.taker_fee*100:.3f}% | "
            f"Candles: {len(data):,}"
        )

        # Pre-compute indicators for performance (vectorized, single pass)
        strategy.prepare(data)

        columns = data.columns.tolist()
        for row in data.itertuples(index=False):
            candle = dict(zip(columns, row))
            signal = strategy.on_candle(candle)
            self._process_signal(signal, candle)
            self._update_equity(candle)

        # Close any open position at the end
        if self.position is not None:
            last_candle = data.iloc[-1].to_dict()
            self._close_position(last_candle)

        result = calculate_metrics(
            self.trades, self.equity_curve, self.config.initial_capital
        )

        logger.info(
            f"Backtest complete: {result.num_trades} trades | "
            f"Return: {result.total_return_pct:+.2f}% | "
            f"Sharpe: {result.sharpe_ratio:.2f}"
        )

        return result

    def _process_signal(self, signal: Signal, candle: dict) -> None:
        """Act on a strategy signal.

        Rules:
        - BUY: if no position, open long. If short, close short then open long.
        - SELL: if no position, open short. If long, close long then open short.
        - HOLD: do nothing.
        """
        if signal == Signal.HOLD:
            return

        if signal == Signal.BUY:
            if self.position is not None and self.position.side == "long":
                return  # Already long, nothing to do
            if self.position is not None and self.position.side == "short":
                self._close_position(candle)
            self._open_position("long", candle)

        elif signal == Signal.SELL:
            if self.position is not None and self.position.side == "short":
                return  # Already short, nothing to do
            if self.position is not None and self.position.side == "long":
                self._close_position(candle)
            if not self.config.long_only:
                self._open_position("short", candle)

    def _open_position(self, side: str, candle: dict) -> None:
        """Open a new position.

        Deducts the position notional from available capital (margin is locked).
        On close, capital is restored via size + pnl.
        """
        size = self.capital * self.config.position_size_pct
        fee = size * self.config.taker_fee
        self.capital -= size + fee

        self.position = Position(
            side=side,
            entry_price=candle["close"],
            entry_time=candle["timestamp"],
            size=size,
        )

    def _close_position(self, candle: dict) -> None:
        """Close the current position and record the trade."""
        if self.position is None:
            return

        exit_price = candle["close"]
        entry_price = self.position.entry_price

        # Calculate P&L
        if self.position.side == "long":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:  # short
            pnl_pct = (entry_price - exit_price) / entry_price

        pnl = self.position.size * pnl_pct

        # Subtract exit fee
        fee = self.position.size * self.config.taker_fee
        pnl -= fee

        self.capital += self.position.size + pnl

        self.trades.append(
            {
                "side": self.position.side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_time": self.position.entry_time,
                "exit_time": candle["timestamp"],
                "size": self.position.size,
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct * 100, 4),
                "fee": round(fee * 2, 4),  # entry + exit fees
            }
        )

        self.position = None

    def _update_equity(self, candle: dict) -> None:
        """Record current portfolio value (cash + unrealized P&L)."""
        equity = self.capital
        if self.position is not None:
            price = candle["close"]
            if self.position.side == "long":
                unrealized = self.position.size * (
                    (price - self.position.entry_price) / self.position.entry_price
                )
            else:
                unrealized = self.position.size * (
                    (self.position.entry_price - price) / self.position.entry_price
                )
            equity += self.position.size + unrealized
        self.equity_curve.append(round(equity, 2))
