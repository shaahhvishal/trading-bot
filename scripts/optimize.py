"""
Parameter optimization with walk-forward validation.

Walk-forward: train on 8 months, test on 4 months, slide forward.
For 2024 data this gives us:
  - Window 1: Train Jan-Aug 2024, Test Sep-Dec 2024
  - Window 2: Train Mar-Oct 2024, Test Nov 2024-Feb 2025 (if data available)

We do a grid search over key parameters on the training set, then evaluate
the best params on the test set. This prevents overfitting.

Usage:
    python scripts/optimize.py
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import yaml
from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.metrics import BacktestResult
from data.resample import resample_ohlcv
from data.store import load


def _load_settings() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _run_backtest(strategy_name: str, params: dict, data: pd.DataFrame,
                  capital: float = 10_000.0, fee: float = 0.0005) -> BacktestResult:
    """Run a single backtest with given params."""
    if strategy_name == "momentum":
        from strategies.momentum import MomentumStrategy
        strat = MomentumStrategy(params=params)
    elif strategy_name == "volatility_breakout":
        from strategies.volatility_breakout import VolatilityBreakoutStrategy
        strat = VolatilityBreakoutStrategy(params=params)
    elif strategy_name == "vwap_reversion":
        from strategies.vwap_reversion import VWAPReversionStrategy
        strat = VWAPReversionStrategy(params=params)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    config = BacktestConfig(initial_capital=capital, taker_fee=fee, position_size_pct=1.0)
    engine = BacktestEngine(config)
    return engine.run(strat, data)


def grid_search(strategy_name: str, param_grid: dict[str, list],
                data: pd.DataFrame) -> list[dict]:
    """Run backtest for every combination of params.

    Args:
        strategy_name: Strategy to test.
        param_grid: Dict of param_name → list of values to try.
        data: Training data.

    Returns:
        List of {params, result} dicts sorted by Sharpe ratio.
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))

    logger.info(f"Grid search: {strategy_name} — {len(combos)} combinations")

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        try:
            result = _run_backtest(strategy_name, params, data)
            results.append({
                "params": params,
                "sharpe": result.sharpe_ratio,
                "return_pct": result.total_return_pct,
                "max_dd": result.max_drawdown_pct,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
                "num_trades": result.num_trades,
            })
        except Exception as e:
            logger.warning(f"Failed with params {params}: {e}")

    results.sort(key=lambda x: x["sharpe"], reverse=True)
    return results


def walk_forward_validate(strategy_name: str, param_grid: dict[str, list],
                          data: pd.DataFrame, train_months: int = 8,
                          test_months: int = 4, step_months: int = 4) -> list[dict]:
    """Walk-forward validation: train on N months, test on M months, slide.

    Args:
        strategy_name: Strategy to optimize.
        param_grid: Parameter grid.
        data: Full dataset.
        train_months: Training window size.
        test_months: Test window size.
        step_months: How far to slide the window each step.

    Returns:
        List of window results with in-sample and out-of-sample metrics.
    """
    data = data.sort_values("timestamp").reset_index(drop=True)
    start = data["timestamp"].iloc[0]
    end = data["timestamp"].iloc[-1]

    windows = []
    window_start = start

    while True:
        train_end = window_start + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)

        if train_end > end:
            break

        train_data = data[(data["timestamp"] >= window_start) & (data["timestamp"] < train_end)]
        test_data = data[(data["timestamp"] >= train_end) & (data["timestamp"] < test_end)]

        if len(train_data) < 100 or len(test_data) < 50:
            window_start += pd.DateOffset(months=step_months)
            continue

        logger.info(
            f"Window: Train {window_start.strftime('%Y-%m-%d')} → "
            f"{train_end.strftime('%Y-%m-%d')} | "
            f"Test → {min(test_end, end).strftime('%Y-%m-%d')}"
        )

        # Grid search on training data
        train_results = grid_search(strategy_name, param_grid, train_data)

        if not train_results:
            window_start += pd.DateOffset(months=step_months)
            continue

        # Pick best params by Sharpe on training data
        best = train_results[0]
        best_params = best["params"]

        # Evaluate on test data (out-of-sample)
        oos_result = _run_backtest(strategy_name, best_params, test_data)

        windows.append({
            "train_period": f"{window_start.strftime('%Y-%m-%d')} → {train_end.strftime('%Y-%m-%d')}",
            "test_period": f"{train_end.strftime('%Y-%m-%d')} → {min(test_end, end).strftime('%Y-%m-%d')}",
            "best_params": best_params,
            "in_sample_sharpe": best["sharpe"],
            "in_sample_return": best["return_pct"],
            "in_sample_dd": best["max_dd"],
            "oos_sharpe": oos_result.sharpe_ratio,
            "oos_return": oos_result.total_return_pct,
            "oos_dd": oos_result.max_drawdown_pct,
            "oos_win_rate": oos_result.win_rate,
            "oos_profit_factor": oos_result.profit_factor,
            "oos_trades": oos_result.num_trades,
        })

        window_start += pd.DateOffset(months=step_months)

    return windows


def main() -> None:
    """Run walk-forward optimization on promising strategy/timeframe combos."""
    settings = _load_settings()

    # Load and prep data
    logger.info("Loading BTC/USDT 1m data...")
    data_1m = load("BTC/USDT", "1m")
    data_1m = data_1m[
        (data_1m["timestamp"] >= "2024-01-01") & (data_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)

    # =========================================================================
    # Define optimization targets
    # =========================================================================
    targets = [
        {
            "name": "momentum",
            "timeframe": "1h",
            "grid": {
                "ema_period": [10, 15, 20, 30, 50],
                "rsi_period": [7, 10, 14, 21],
                "rsi_long_threshold": [50, 55, 60],
                "rsi_short_threshold": [40, 45, 50],
            },
        },
        {
            "name": "volatility_breakout",
            "timeframe": "1h",
            "grid": {
                "donchian_period": [10, 15, 20, 30, 50],
                "volume_ma_period": [10, 15, 20, 30],
            },
        },
        {
            "name": "vwap_reversion",
            "timeframe": "5m",
            "grid": {
                "vwap_period": [10, 15, 20, 30, 50],
                "vwap_std_mult": [1.5, 2.0, 2.5, 3.0],
                "rsi_period": [7, 10, 14],
                "rsi_divergence_lookback": [3, 5, 8],
            },
        },
    ]

    all_summaries = []

    for target in targets:
        strat_name = target["name"]
        tf = target["timeframe"]
        param_grid = target["grid"]

        print(f"\n{'='*80}")
        print(f"  OPTIMIZING: {strat_name} @ {tf}")
        print(f"{'='*80}")

        # Resample data
        data = resample_ohlcv(data_1m, tf)

        # Run walk-forward validation
        windows = walk_forward_validate(strat_name, param_grid, data)

        if not windows:
            print(f"  No valid windows for {strat_name} @ {tf}")
            continue

        # Print per-window results
        window_rows = []
        for w in windows:
            window_rows.append({
                "Train": w["train_period"],
                "Test": w["test_period"],
                "IS Return": f"{w['in_sample_return']:+.2f}%",
                "IS Sharpe": f"{w['in_sample_sharpe']:.2f}",
                "OOS Return": f"{w['oos_return']:+.2f}%",
                "OOS Sharpe": f"{w['oos_sharpe']:.2f}",
                "OOS DD": f"{w['oos_dd']:.2f}%",
                "OOS WR": f"{w['oos_win_rate']:.1f}%",
                "OOS PF": f"{w['oos_profit_factor']:.2f}",
                "Trades": w["oos_trades"],
            })
            print(f"\n  Best params: {w['best_params']}")

        print()
        print(tabulate(window_rows, headers="keys", tablefmt="simple"))

        # Aggregate OOS results
        avg_oos_return = sum(w["oos_return"] for w in windows) / len(windows)
        avg_oos_sharpe = sum(w["oos_sharpe"] for w in windows) / len(windows)
        avg_oos_dd = sum(w["oos_dd"] for w in windows) / len(windows)

        all_summaries.append({
            "Strategy": f"{strat_name} @ {tf}",
            "Avg OOS Return": f"{avg_oos_return:+.2f}%",
            "Avg OOS Sharpe": f"{avg_oos_sharpe:.2f}",
            "Avg OOS Max DD": f"{avg_oos_dd:.2f}%",
            "Windows": len(windows),
        })

    # Final summary
    print(f"\n{'='*80}")
    print("  WALK-FORWARD SUMMARY (Out-of-Sample Averages)")
    print(f"{'='*80}")
    print(tabulate(all_summaries, headers="keys", tablefmt="simple"))
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
