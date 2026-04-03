"""
Backtest the VWAP Pullback strategy across assets, timeframes, and configurations.

Usage:
    python scripts/backtest_vwap_pullback.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from data.resample import resample_ohlcv
from data.store import load
from strategies.vwap_pullback import VWAPPullbackStrategy


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

    for asset_name, full_data, oos_data in [("BTC/USDT", btc_full, btc_oos), ("ETH/USDT", eth_full, eth_oos)]:
        for tf in ["1m", "5m"]:
            for pullback_mult in [0.3, 0.4, 0.6]:
                for use_struct in [True, False]:
                    for tp_r in [1.5, 2.0, 3.0]:
                        combos.append({
                            "asset": asset_name,
                            "timeframe": tf,
                            "pullback_mult": pullback_mult,
                            "use_struct": use_struct,
                            "tp_r": tp_r,
                            "full_data": full_data,
                            "oos_data": oos_data,
                        })

    results = []
    config = BacktestConfig(initial_capital=10_000.0, taker_fee=0.0005, position_size_pct=1.0)

    total = len(combos)
    for i, combo in enumerate(combos):
        if (i + 1) % 10 == 0:
            logger.info(f"Running combo {i + 1}/{total}...")

        # Resample if needed
        if combo["timeframe"] == "5m":
            data_full = resample_ohlcv(combo["full_data"], "5m")
            data_oos = resample_ohlcv(combo["oos_data"], "5m")
        else:
            data_full = combo["full_data"]
            data_oos = combo["oos_data"]

        params = {
            "session_hours": [0, 8, 16],
            "atr_period": 14,
            "pullback_atr_mult": combo["pullback_mult"],
            "vwap_slope_lookback": 5,
            "use_structure_filter": combo["use_struct"],
            "structure_lookback": 6,
            "stop_atr_mult": 0.5,
            "tp_r_multiple": combo["tp_r"],
            "trail_ema_period": 9,
        }

        # Run on full year
        strat = VWAPPullbackStrategy(params=params)
        engine = BacktestEngine(config)
        result_full = engine.run(strat, data_full)

        # Run on OOS
        strat_oos = VWAPPullbackStrategy(params=params)
        engine_oos = BacktestEngine(config)
        result_oos = engine_oos.run(strat_oos, data_oos)

        label = f"PB={combo['pullback_mult']} {'Struct' if combo['use_struct'] else 'NoStr'} TP={combo['tp_r']}R"

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

    print("\n" + "=" * 160)
    print("  VWAP PULLBACK STRATEGY BACKTEST — Full Year + Out-of-Sample (Sep-Dec 2024)")
    print("=" * 160)
    print(tabulate(results, headers="keys", tablefmt="simple", stralign="right"))
    print("=" * 160)

    # Print top 5
    print("\n  TOP 5 CONFIGS BY OOS SHARPE:")
    for i, r in enumerate(results[:5]):
        print(f"  #{i+1}: {r['Asset']} @ {r['TF']} — {r['Config']} | "
              f"OOS Return: {r['OOS Return %']} | Sharpe: {r['OOS Sharpe']} | "
              f"Max DD: {r['OOS Max DD %']} | WR: {r['OOS WR %']} | Trades: {r['OOS Trades']}")
    print()


if __name__ == "__main__":
    main()
