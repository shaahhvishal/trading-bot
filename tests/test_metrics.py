"""Tests for backtest/metrics.py — performance metric calculations."""

from __future__ import annotations

from backtest.metrics import calculate_metrics


def test_zero_trades_returns_defaults():
    """No trades → all metrics should be zero/default."""
    result = calculate_metrics([], [10_000.0] * 10, 10_000.0)

    assert result.num_trades == 0
    assert result.win_rate == 0.0
    assert result.total_return_pct == 0.0
    assert result.total_pnl == 0.0


def test_all_winning_trades():
    """100% win rate scenario."""
    trades = [
        {"pnl": 100.0, "pnl_pct": 1.0},
        {"pnl": 200.0, "pnl_pct": 2.0},
        {"pnl": 50.0, "pnl_pct": 0.5},
    ]
    equity = [10_000.0, 10_100.0, 10_300.0, 10_350.0]
    result = calculate_metrics(trades, equity, 10_000.0)

    assert result.win_rate == 100.0
    assert result.num_trades == 3
    assert result.total_pnl == 350.0
    assert result.avg_loss == 0.0


def test_mixed_wins_and_losses():
    """Win rate calculation with mixed trades."""
    trades = [
        {"pnl": 100.0, "pnl_pct": 1.0},
        {"pnl": -50.0, "pnl_pct": -0.5},
        {"pnl": 200.0, "pnl_pct": 2.0},
        {"pnl": -30.0, "pnl_pct": -0.3},
    ]
    equity = [10_000.0, 10_100.0, 10_050.0, 10_250.0, 10_220.0]
    result = calculate_metrics(trades, equity, 10_000.0)

    assert result.win_rate == 50.0
    assert result.num_trades == 4
    assert result.profit_factor > 1.0  # Winners > losers


def test_max_drawdown():
    """Drawdown from peak should be calculated correctly."""
    # Equity goes 10000 → 11000 → 9000 → 10000
    trades = [
        {"pnl": 1000.0, "pnl_pct": 10.0},
        {"pnl": -2000.0, "pnl_pct": -18.18},
        {"pnl": 1000.0, "pnl_pct": 11.11},
    ]
    equity = [10_000.0, 11_000.0, 9_000.0, 10_000.0]
    result = calculate_metrics(trades, equity, 10_000.0)

    # Max drawdown is from 11000 to 9000 = -18.18%
    assert result.max_drawdown_pct < -18.0
    assert result.max_drawdown_pct > -19.0


def test_profit_factor():
    """Profit factor = gross_wins / gross_losses."""
    trades = [
        {"pnl": 300.0, "pnl_pct": 3.0},
        {"pnl": -100.0, "pnl_pct": -1.0},
    ]
    equity = [10_000.0, 10_300.0, 10_200.0]
    result = calculate_metrics(trades, equity, 10_000.0)

    assert result.profit_factor == 3.0
