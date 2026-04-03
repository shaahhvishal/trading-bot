"""
Backtest report: print results to terminal and optionally export.

Keeps it simple — a clean table of metrics plus the last N trades.
"""

from __future__ import annotations

from tabulate import tabulate

from backtest.metrics import BacktestResult


def print_report(result: BacktestResult, show_trades: int = 10) -> None:
    """Print a formatted backtest report to the terminal.

    Args:
        result: BacktestResult from the engine.
        show_trades: Number of recent trades to display (0 to hide).
    """
    metrics = [
        ["Initial Capital", f"${result.initial_capital:,.2f}"],
        ["Final Capital", f"${result.final_capital:,.2f}"],
        ["Total P&L", f"${result.total_pnl:+,.2f}"],
        ["Total Return", f"{result.total_return_pct:+.2f}%"],
        ["Number of Trades", f"{result.num_trades}"],
        ["Win Rate", f"{result.win_rate:.1f}%"],
        ["Profit Factor", f"{result.profit_factor:.2f}"],
        ["Sharpe Ratio", f"{result.sharpe_ratio:.2f}"],
        ["Max Drawdown", f"{result.max_drawdown_pct:.2f}%"],
        ["Avg Win", f"${result.avg_win:+,.2f}"],
        ["Avg Loss", f"${result.avg_loss:+,.2f}"],
        ["Avg Win/Loss Ratio", f"{result.avg_win_loss_ratio:.2f}"],
    ]

    print("\n" + "=" * 50)
    print("         BACKTEST RESULTS")
    print("=" * 50)
    print(tabulate(metrics, tablefmt="plain"))
    print("=" * 50)

    if show_trades > 0 and result.trades:
        recent = result.trades[-show_trades:]
        trade_rows = []
        for t in recent:
            trade_rows.append([
                t["side"].upper(),
                f"${t['entry_price']:,.2f}",
                f"${t['exit_price']:,.2f}",
                f"${t['pnl']:+,.2f}",
                f"{t['pnl_pct']:+.2f}%",
            ])

        print(f"\n  Last {len(recent)} Trades:")
        print(
            tabulate(
                trade_rows,
                headers=["Side", "Entry", "Exit", "P&L", "P&L %"],
                tablefmt="simple",
            )
        )
        print()
