"""
Backtest Volatility Breakout with TP/SL vs without, across parameter combos.

Usage:
    python scripts/backtest_vol_tpsl.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import print_report
from data.resample import resample_ohlcv
from data.store import load
from strategies.volatility_breakout import VolatilityBreakoutStrategy


def main() -> None:
    logger.info("Loading data...")
    btc_1m = load("BTC/USDT", "1m")
    eth_1m = load("ETH/USDT", "1m")

    btc_full = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_full = eth_1m[(eth_1m["timestamp"] >= "2024-01-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    btc_oos = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_oos = eth_1m[(eth_1m["timestamp"] >= "2024-09-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    btc_full_1h = resample_ohlcv(btc_full, "1h")
    eth_full_1h = resample_ohlcv(eth_full, "1h")
    btc_oos_1h = resample_ohlcv(btc_oos, "1h")
    eth_oos_1h = resample_ohlcv(eth_oos, "1h")

    combos = []

    # Baseline: no TP/SL (original behavior)
    combos.append({"label": "NO TP/SL (baseline)", "tp_pct": 99.0, "sl_pct": 99.0, "breakeven_pct": 99.0, "use_tp_sl": False})

    # TP/SL combos informed by MFE/MAE analysis
    for tp in [5.0, 6.0, 8.0, 10.0]:
        for sl in [3.0, 4.0, 5.0]:
            for be in [1.5, 2.0, 3.0]:
                combos.append({
                    "label": f"TP={tp}% SL={sl}% BE={be}%",
                    "tp_pct": tp,
                    "sl_pct": sl,
                    "breakeven_pct": be,
                    "use_tp_sl": True,
                })

    config = BacktestConfig(initial_capital=10_000.0, taker_fee=0.0005, position_size_pct=1.0)
    results = []
    total = len(combos) * 2  # BTC + ETH
    count = 0

    for asset_name, full_data, oos_data in [("BTC/USDT", btc_full_1h, btc_oos_1h), ("ETH/USDT", eth_full_1h, eth_oos_1h)]:
        for combo in combos:
            count += 1
            if count % 20 == 0:
                logger.info(f"Running combo {count}/{total}...")

            params = {
                "donchian_period": 50,
                "volume_ma_period": 20,
                "atr_period": 14,
                "tp_pct": combo["tp_pct"],
                "sl_pct": combo["sl_pct"],
                "breakeven_pct": combo["breakeven_pct"],
                "trail_ema_period": 9,
                "use_tp_sl": combo["use_tp_sl"],
            }

            # Full year
            strat = VolatilityBreakoutStrategy(params=params)
            engine = BacktestEngine(config)
            r_full = engine.run(strat, full_data)

            # OOS
            strat2 = VolatilityBreakoutStrategy(params=params)
            engine2 = BacktestEngine(config)
            r_oos = engine2.run(strat2, oos_data)

            results.append({
                "Asset": asset_name,
                "Config": combo["label"],
                "Full Ret %": f"{r_full.total_return_pct:+.1f}",
                "Full Sharpe": f"{r_full.sharpe_ratio:.2f}",
                "Full Trades": r_full.num_trades,
                "Full WR %": f"{r_full.win_rate:.1f}",
                "OOS Ret %": f"{r_oos.total_return_pct:+.1f}",
                "OOS Sharpe": f"{r_oos.sharpe_ratio:.2f}",
                "OOS DD %": f"{r_oos.max_drawdown_pct:.1f}",
                "OOS WR %": f"{r_oos.win_rate:.1f}",
                "OOS PF": f"{r_oos.profit_factor:.2f}",
                "OOS Trades": r_oos.num_trades,
                "_oos_sharpe": r_oos.sharpe_ratio,
                "_asset": asset_name,
            })

    # Print per-asset, sorted by OOS Sharpe
    for asset in ["BTC/USDT", "ETH/USDT"]:
        asset_results = [r for r in results if r["_asset"] == asset]
        asset_results.sort(key=lambda x: x["_oos_sharpe"], reverse=True)

        # Remove internal keys for display
        display = [{k: v for k, v in r.items() if not k.startswith("_")} for r in asset_results]

        print(f"\n{'='*160}")
        print(f"  {asset} — VOLATILITY BREAKOUT TP/SL COMPARISON (Full Year + OOS Sep-Dec 2024)")
        print(f"{'='*160}")
        print(tabulate(display[:25], headers="keys", tablefmt="simple", stralign="right"))

        # Find baseline
        baseline = next(r for r in asset_results if "baseline" in r["Config"])
        best = asset_results[0]
        print(f"\n  BASELINE: {baseline['OOS Ret %']}% return | Sharpe {baseline['OOS Sharpe']} | DD {baseline['OOS DD %']} | WR {baseline['OOS WR %']} | PF {baseline['OOS PF']}")
        print(f"  BEST:     {best['OOS Ret %']}% return | Sharpe {best['OOS Sharpe']} | DD {best['OOS DD %']} | WR {best['OOS WR %']} | PF {best['OOS PF']} — {best['Config']}")
        print(f"{'='*160}")

    # Print detailed report for overall best OOS config on BTC
    btc_results = [r for r in results if r["_asset"] == "BTC/USDT"]
    btc_results.sort(key=lambda x: x["_oos_sharpe"], reverse=True)
    best_btc = btc_results[0]
    print(f"\n  Running detailed report for best BTC config: {best_btc['Config']}")

    # Extract params from label
    if "baseline" not in best_btc["Config"]:
        parts = best_btc["Config"].split()
        tp = float(parts[0].split("=")[1].rstrip("%"))
        sl = float(parts[1].split("=")[1].rstrip("%"))
        be = float(parts[2].split("=")[1].rstrip("%"))
        best_params = {
            "donchian_period": 50, "volume_ma_period": 20, "atr_period": 14,
            "tp_pct": tp, "sl_pct": sl, "breakeven_pct": be,
            "trail_ema_period": 9, "use_tp_sl": True,
        }
    else:
        best_params = {
            "donchian_period": 50, "volume_ma_period": 20, "atr_period": 14,
            "use_tp_sl": False,
        }

    strat = VolatilityBreakoutStrategy(params=best_params)
    engine = BacktestEngine(config)
    result = engine.run(strat, btc_oos_1h)
    print_report(result, show_trades=20)


if __name__ == "__main__":
    main()
