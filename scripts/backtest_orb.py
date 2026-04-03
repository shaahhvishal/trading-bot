"""
Backtest the ORB strategy across assets, timeframes, and OR window sizes.

Usage:
    python scripts/backtest_orb.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import print_report
from data.resample import resample_ohlcv
from data.store import load
from strategies.orb import ORBStrategy


def main() -> None:
    logger.info("Loading data...")
    btc_1m = load("BTC/USDT", "1m")
    eth_1m = load("ETH/USDT", "1m")

    # Full year and OOS
    btc_full = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_full = eth_1m[(eth_1m["timestamp"] >= "2024-01-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    btc_oos = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_oos = eth_1m[(eth_1m["timestamp"] >= "2024-09-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    combos = []

    # Test different configurations
    for asset_name, full_data, oos_data in [("BTC/USDT", btc_full, btc_oos), ("ETH/USDT", eth_full, eth_oos)]:
        for tf in ["1m", "5m"]:
            for or_window in [5, 15]:
                for use_vwap in [True, False]:
                    combos.append({
                        "asset": asset_name,
                        "timeframe": tf,
                        "or_window": or_window,
                        "use_vwap": use_vwap,
                        "full_data": full_data,
                        "oos_data": oos_data,
                    })

    results = []
    config = BacktestConfig(initial_capital=10_000.0, taker_fee=0.0005, position_size_pct=1.0)

    for combo in combos:
        # Resample if needed
        if combo["timeframe"] == "5m":
            data_full = resample_ohlcv(combo["full_data"], "5m")
            data_oos = resample_ohlcv(combo["oos_data"], "5m")
        else:
            data_full = combo["full_data"]
            data_oos = combo["oos_data"]

        params = {
            "or_window_minutes": combo["or_window"],
            "session_hours": [0, 8, 16],
            "atr_skip_mult": 1.2,
            "volume_mult": 1.2,
            "volume_lookback": 30,
            "use_vwap_bias": combo["use_vwap"],
            "vwap_period": 60,
            "tp_r_multiple": 2.0,
            "trail_sma_period": 10,
            "time_stop_minutes": 15,
            "time_stop_r_threshold": 0.5,
        }

        # Run on full year
        strat = ORBStrategy(params=params)
        engine = BacktestEngine(config)
        result_full = engine.run(strat, data_full)

        # Run on OOS
        strat_oos = ORBStrategy(params=params)
        engine_oos = BacktestEngine(config)
        result_oos = engine_oos.run(strat_oos, data_oos)

        label = f"OR={combo['or_window']}m {'VWAP' if combo['use_vwap'] else 'noVWAP'}"

        results.append({
            "Asset": combo["asset"],
            "TF": combo["timeframe"],
            "Config": label,
            "Full Return %": f"{result_full.total_return_pct:+.2f}",
            "Full Sharpe": f"{result_full.sharpe_ratio:.2f}",
            "Full Trades": result_full.num_trades,
            "OOS Return %": f"{result_oos.total_return_pct:+.2f}",
            "OOS Sharpe": f"{result_oos.sharpe_ratio:.2f}",
            "OOS Max DD %": f"{result_oos.max_drawdown_pct:.2f}",
            "OOS WR %": f"{result_oos.win_rate:.1f}",
            "OOS PF": f"{result_oos.profit_factor:.2f}",
            "OOS Trades": result_oos.num_trades,
        })

    # Sort by OOS Sharpe
    results.sort(key=lambda x: float(x["OOS Sharpe"]), reverse=True)

    print("\n" + "=" * 150)
    print("  ORB STRATEGY BACKTEST — Full Year + Out-of-Sample (Sep-Dec 2024)")
    print("=" * 150)
    print(tabulate(results, headers="keys", tablefmt="simple", stralign="right"))
    print("=" * 150)

    # Print detailed report for the best OOS combo
    best = results[0]
    print(f"\n  BEST CONFIG: {best['Asset']} @ {best['TF']} — {best['Config']}")
    print(f"  OOS Return: {best['OOS Return %']} | Sharpe: {best['OOS Sharpe']} | "
          f"Max DD: {best['OOS Max DD %']} | Win Rate: {best['OOS WR %']} | "
          f"PF: {best['OOS PF']} | Trades: {best['OOS Trades']}\n")


if __name__ == "__main__":
    main()
