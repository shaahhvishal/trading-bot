"""
Backtest Confluence strategy on BTC/USDT 1H data.

Tests multi-indicator scoring system with parameter sweep on entry/exit thresholds.

Usage:
    python scripts/backtest_confluence.py
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
from strategies.confluence import ConfluenceStrategy


def main() -> None:
    logger.info("Loading BTC/USDT 1m data...")
    btc_1m = load("BTC/USDT", "1m")

    # Full year and OOS
    btc_full = btc_1m[
        (btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)
    btc_oos = btc_1m[
        (btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)

    btc_full_1h = resample_ohlcv(btc_full, "1h")
    btc_oos_1h = resample_ohlcv(btc_oos, "1h")

    logger.info(f"Full year 1H: {len(btc_full_1h):,} candles")
    logger.info(f"OOS (Sep-Dec) 1H: {len(btc_oos_1h):,} candles")

    config = BacktestConfig(
        initial_capital=10_000.0,
        taker_fee=0.0005,
        position_size_pct=1.0,
        long_only=True,
    )

    # --- Score Diagnostic: show score distribution ---
    logger.info("\n=== SCORE DISTRIBUTION (Full Year) ===")
    diag_strat = ConfluenceStrategy()
    diag_strat.prepare(btc_full_1h)
    scores = []
    for row in btc_full_1h.itertuples(index=False):
        candle = dict(zip(btc_full_1h.columns, row))
        diag_strat._add_candle(candle)
        idx = diag_strat._candle_index - 1
        if idx >= diag_strat.warmup_period:
            total, breakdown = diag_strat._compute_score(idx)
            scores.append((total, breakdown))

    if scores:
        from collections import Counter
        score_counts = Counter(s[0] for s in scores)
        print("\nScore  Count   Pct")
        print("-" * 30)
        total_bars = len(scores)
        for s in sorted(score_counts.keys()):
            pct = score_counts[s] / total_bars * 100
            bar = "█" * int(pct / 2)
            print(f"  {s:>2}   {score_counts[s]:>5}  {pct:5.1f}%  {bar}")

        # Show avg contribution per indicator
        print("\nAvg score per indicator:")
        indicator_names = list(scores[0][1].keys())
        for name in indicator_names:
            avg = sum(s[1][name] for s in scores) / len(scores)
            print(f"  {name:<20s} {avg:.2f} / 2.00")

    # --- Full Year Backtest (default thresholds) ---
    print("\n" + "=" * 60)
    print("FULL YEAR BACKTEST (entry>=7, exit<=3)")
    print("=" * 60)

    strat = ConfluenceStrategy(params={"entry_threshold": 7, "exit_threshold": 3})
    engine = BacktestEngine(config)
    result = engine.run(strat, btc_full_1h)
    print_report(result, show_trades=15)

    # --- OOS ---
    print("\n" + "=" * 60)
    print("OUT-OF-SAMPLE (Sep-Dec 2024)")
    print("=" * 60)

    strat_oos = ConfluenceStrategy(params={"entry_threshold": 7, "exit_threshold": 3})
    engine_oos = BacktestEngine(config)
    result_oos = engine_oos.run(strat_oos, btc_oos_1h)
    print_report(result_oos, show_trades=15)

    # --- Threshold Sweep ---
    print("\n" + "=" * 60)
    print("THRESHOLD SWEEP (Full Year)")
    print("=" * 60)

    results = []
    for entry_t in [5, 6, 7, 8, 9]:
        for exit_t in [2, 3, 4]:
            if exit_t >= entry_t:
                continue
            strat = ConfluenceStrategy(params={
                "entry_threshold": entry_t,
                "exit_threshold": exit_t,
            })
            engine = BacktestEngine(config)
            res = engine.run(strat, btc_full_1h)
            results.append({
                "entry": entry_t,
                "exit": exit_t,
                "return_pct": res.total_return_pct,
                "sharpe": res.sharpe_ratio,
                "trades": res.num_trades,
                "win_rate": res.win_rate,
                "max_dd": res.max_drawdown_pct,
                "pf": res.profit_factor,
            })

    print(f"\n{'Entry':>6} {'Exit':>5} {'Return%':>10} {'Sharpe':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'MaxDD%':>8}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x["return_pct"], reverse=True):
        print(
            f"{r['entry']:>6} {r['exit']:>5} {r['return_pct']:>+10.2f} "
            f"{r['sharpe']:>8.2f} {r['trades']:>7} {r['win_rate']:>5.1f}% "
            f"{r['pf']:>5.2f} {r['max_dd']:>7.1f}%"
        )


if __name__ == "__main__":
    main()
