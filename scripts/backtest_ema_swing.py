"""
Backtest EMA Swing strategy on BTC/USDT 1H data.

Tests multi-timeframe 200 EMA strategy:
  - LONG when both 4H and 1H close above 200 EMA
  - EXIT when either closes below

Usage:
    python scripts/backtest_ema_swing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import print_report
from data.resample import resample_ohlcv
from data.store import load
from strategies.ema_swing import EMASwingStrategy


def main() -> None:
    logger.info("Loading BTC/USDT 1m data...")
    btc_1m = load("BTC/USDT", "1m")

    # Full year (in-sample) and OOS split
    btc_full = btc_1m[
        (btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)
    btc_oos = btc_1m[
        (btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)

    # Resample to 1H (strategy expects 1H candles, internally resamples to 4H)
    btc_full_1h = resample_ohlcv(btc_full, "1h")
    btc_oos_1h = resample_ohlcv(btc_oos, "1h")

    logger.info(f"Full year 1H candles: {len(btc_full_1h):,}")
    logger.info(f"OOS (Sep-Dec) 1H candles: {len(btc_oos_1h):,}")

    config = BacktestConfig(
        initial_capital=10_000.0,
        taker_fee=0.0005,
        position_size_pct=1.0,
        long_only=True,
    )

    # --- Full Year Backtest ---
    logger.info("\n{'='*60}")
    logger.info("FULL YEAR BACKTEST (2024-01-01 to 2025-01-01)")
    logger.info("{'='*60}")

    strat_full = EMASwingStrategy(params={"ema_period": 200})
    engine_full = BacktestEngine(config)
    result_full = engine_full.run(strat_full, btc_full_1h)
    print_report(result_full, show_trades=20)

    # --- OOS Backtest ---
    logger.info("\n{'='*60}")
    logger.info("OUT-OF-SAMPLE BACKTEST (2024-09-01 to 2025-01-01)")
    logger.info("{'='*60}")

    strat_oos = EMASwingStrategy(params={"ema_period": 200})
    engine_oos = BacktestEngine(config)
    result_oos = engine_oos.run(strat_oos, btc_oos_1h)
    print_report(result_oos, show_trades=20)

    # --- Parameter sweep: EMA periods ---
    logger.info("\n{'='*60}")
    logger.info("PARAMETER SWEEP: EMA PERIOD")
    logger.info("{'='*60}")

    results = []
    for period in [50, 100, 150, 200, 250]:
        strat = EMASwingStrategy(params={"ema_period": period})
        engine = BacktestEngine(config)
        res = engine.run(strat, btc_full_1h)
        results.append({
            "ema_period": period,
            "return_pct": res.total_return_pct,
            "sharpe": res.sharpe_ratio,
            "trades": res.num_trades,
            "win_rate": res.win_rate,
            "max_dd": res.max_drawdown_pct,
        })
        logger.info(
            f"EMA {period}: Return={res.total_return_pct:+.2f}% | "
            f"Sharpe={res.sharpe_ratio:.2f} | Trades={res.num_trades} | "
            f"WR={res.win_rate:.1f}% | MaxDD={res.max_drawdown_pct:.1f}%"
        )

    print("\n=== Parameter Sweep Summary ===")
    print(f"{'Period':>8} {'Return%':>10} {'Sharpe':>8} {'Trades':>8} {'WinRate':>8} {'MaxDD%':>8}")
    print("-" * 54)
    for r in results:
        print(
            f"{r['ema_period']:>8} {r['return_pct']:>+10.2f} {r['sharpe']:>8.2f} "
            f"{r['trades']:>8} {r['win_rate']:>7.1f}% {r['max_dd']:>7.1f}%"
        )


if __name__ == "__main__":
    main()
