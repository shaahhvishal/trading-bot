"""
Backtest performance metrics.

All metrics are calculated from a list of completed trades. Each trade is a
dict with: entry_price, exit_price, side ("long"/"short"), entry_time, exit_time,
pnl, pnl_pct.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    """Container for all backtest metrics."""

    total_return_pct: float
    total_pnl: float
    num_trades: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_win_loss_ratio: float
    initial_capital: float
    final_capital: float
    equity_curve: list[float]
    trades: list[dict]


def calculate_metrics(
    trades: list[dict],
    equity_curve: list[float],
    initial_capital: float,
) -> BacktestResult:
    """Calculate all performance metrics from trade log and equity curve.

    Args:
        trades: List of completed trade dicts.
        equity_curve: Portfolio value at each candle.
        initial_capital: Starting capital.

    Returns:
        BacktestResult with all computed metrics.
    """
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_pnl = final_capital - initial_capital
    total_return_pct = (total_pnl / initial_capital) * 100

    num_trades = len(trades)
    if num_trades == 0:
        return BacktestResult(
            total_return_pct=0.0,
            total_pnl=0.0,
            num_trades=0,
            win_rate=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_win_loss_ratio=0.0,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            equity_curve=equity_curve,
            trades=[],
        )

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / num_trades * 100

    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown from equity curve
    equity = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_drawdown_pct = float(np.min(drawdowns)) * 100

    # Sharpe ratio (annualized, assuming 1-minute bars)
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(equity) / equity[:-1]
    returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)
    if len(returns) > 1 and np.std(returns) > 0:
        minutes_per_year = 525_600
        sharpe_ratio = float(
            np.mean(returns) / np.std(returns) * np.sqrt(minutes_per_year)
        )
    else:
        sharpe_ratio = 0.0

    return BacktestResult(
        total_return_pct=round(total_return_pct, 2),
        total_pnl=round(total_pnl, 2),
        num_trades=num_trades,
        win_rate=round(win_rate, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        sharpe_ratio=round(sharpe_ratio, 2),
        profit_factor=round(profit_factor, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        avg_win_loss_ratio=round(avg_win_loss_ratio, 2),
        initial_capital=initial_capital,
        final_capital=round(final_capital, 2),
        equity_curve=equity_curve,
        trades=trades,
    )
