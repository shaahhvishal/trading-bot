"""
Backtest Volatility Breakout on BTC with SL-only (no TP), trailing stop, and cooldown.

Focus: protect against big drawdowns while letting winners run.
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

    btc_full = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    btc_oos = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    btc_full_1h = resample_ohlcv(btc_full, "1h")
    btc_oos_1h = resample_ohlcv(btc_oos, "1h")

    combos = []

    # Baseline
    combos.append({"label": "NO TP/SL (baseline)", "use_tp_sl": False, "tp_pct": 99, "sl_pct": 99, "breakeven_pct": 99, "trail_ema_period": 9})

    # SL-only (huge TP so it never triggers), various SL + breakeven + trail EMA combos
    for sl in [3.0, 4.0, 5.0, 6.0, 8.0]:
        for be in [1.5, 2.0, 3.0, 4.0]:
            for trail_ema in [5, 9, 14, 20]:
                if be >= sl:
                    continue  # breakeven must be less than SL
                combos.append({
                    "label": f"SL={sl}% BE={be}% EMA={trail_ema}",
                    "use_tp_sl": True,
                    "tp_pct": 99.0,  # effectively no TP
                    "sl_pct": sl,
                    "breakeven_pct": be,
                    "trail_ema_period": trail_ema,
                })

    config = BacktestConfig(initial_capital=10_000.0, taker_fee=0.0005, position_size_pct=1.0)
    results = []

    logger.info(f"Running {len(combos)} configurations...")
    for i, combo in enumerate(combos):
        if (i + 1) % 50 == 0:
            logger.info(f"  {i + 1}/{len(combos)}...")

        params = {
            "donchian_period": 50,
            "volume_ma_period": 20,
            "atr_period": 14,
            "tp_pct": combo["tp_pct"],
            "sl_pct": combo["sl_pct"],
            "breakeven_pct": combo["breakeven_pct"],
            "trail_ema_period": combo["trail_ema_period"],
            "use_tp_sl": combo["use_tp_sl"],
        }

        strat = VolatilityBreakoutStrategy(params=params)
        engine = BacktestEngine(config)
        r_full = engine.run(strat, btc_full_1h)

        strat2 = VolatilityBreakoutStrategy(params=params)
        engine2 = BacktestEngine(config)
        r_oos = engine2.run(strat2, btc_oos_1h)

        results.append({
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
            "_oos_ret": r_oos.total_return_pct,
        })

    # Sort by OOS Sharpe
    results.sort(key=lambda x: x["_oos_sharpe"], reverse=True)
    display = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]

    print(f"\n{'='*150}")
    print(f"  BTC/USDT — SL-ONLY + TRAILING STOP (No TP) — Full Year + OOS Sep-Dec 2024")
    print(f"{'='*150}")
    print(tabulate(display[:30], headers="keys", tablefmt="simple", stralign="right"))

    baseline = next(r for r in results if "baseline" in r["Config"])
    best = results[0]

    print(f"\n  BASELINE: {baseline['OOS Ret %']}% | Sharpe {baseline['OOS Sharpe']} | DD {baseline['OOS DD %']} | WR {baseline['OOS WR %']} | PF {baseline['OOS PF']} | {baseline['OOS Trades']} trades")
    print(f"  BEST:     {best['OOS Ret %']}% | Sharpe {best['OOS Sharpe']} | DD {best['OOS DD %']} | WR {best['OOS WR %']} | PF {best['OOS PF']} | {best['OOS Trades']} trades — {best['Config']}")

    # Also show best by OOS return (might differ from best Sharpe)
    results_by_ret = sorted(results, key=lambda x: x["_oos_ret"], reverse=True)
    best_ret = results_by_ret[0]
    print(f"  BEST RET: {best_ret['OOS Ret %']}% | Sharpe {best_ret['OOS Sharpe']} | DD {best_ret['OOS DD %']} | WR {best_ret['OOS WR %']} | PF {best_ret['OOS PF']} | {best_ret['OOS Trades']} trades — {best_ret['Config']}")
    print(f"{'='*150}")

    # Detailed report for top config
    if "baseline" not in best["Config"]:
        parts = best["Config"].split()
        sl = float(parts[0].split("=")[1].rstrip("%"))
        be = float(parts[1].split("=")[1].rstrip("%"))
        ema = int(parts[2].split("=")[1])
        best_params = {
            "donchian_period": 50, "volume_ma_period": 20, "atr_period": 14,
            "tp_pct": 99.0, "sl_pct": sl, "breakeven_pct": be,
            "trail_ema_period": ema, "use_tp_sl": True,
        }
        print(f"\n  Detailed report for best config: {best['Config']}")
        strat = VolatilityBreakoutStrategy(params=best_params)
        engine = BacktestEngine(config)
        result = engine.run(strat, btc_oos_1h)
        print_report(result, show_trades=25)


if __name__ == "__main__":
    main()
