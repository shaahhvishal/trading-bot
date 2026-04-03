"""
Analyze Maximum Favorable Excursion (MFE) for Volatility Breakout trades.

For each trade, track the highest unrealized % return before the exit signal fires.
Compare to actual exit return to see how much profit is left on the table.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from loguru import logger
from tabulate import tabulate

from data.resample import resample_ohlcv
from data.store import load
from strategies.volatility_breakout import VolatilityBreakoutStrategy
from strategies.base import Signal


def analyze_mfe(data_1h: pd.DataFrame, params: dict) -> list[dict]:
    """Run strategy and track MFE for each trade."""
    strat = VolatilityBreakoutStrategy(params=params)
    strat.reset()
    strat.prepare(data_1h)

    trades = []
    in_trade = False
    trade_side = ""
    entry_price = 0.0
    entry_time = None
    max_favorable = 0.0  # best unrealized % return during trade

    columns = data_1h.columns.tolist()
    for row in data_1h.itertuples(index=False):
        candle = dict(zip(columns, row))
        signal = strat.on_candle(candle)

        if in_trade:
            # Track MFE using high/low of each candle during the trade
            if trade_side == "long":
                best_price = candle["high"]
                current_mfe = (best_price - entry_price) / entry_price * 100
            else:
                best_price = candle["low"]
                current_mfe = (entry_price - best_price) / entry_price * 100
            max_favorable = max(max_favorable, current_mfe)

            # Check for exit
            should_exit = False
            if trade_side == "long" and signal == Signal.SELL:
                should_exit = True
            elif trade_side == "short" and signal == Signal.BUY:
                should_exit = True

            if should_exit:
                exit_price = candle["close"]
                if trade_side == "long":
                    actual_return = (exit_price - entry_price) / entry_price * 100
                else:
                    actual_return = (entry_price - exit_price) / entry_price * 100

                trades.append({
                    "side": trade_side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "entry_time": entry_time,
                    "exit_time": candle["timestamp"],
                    "actual_return_pct": actual_return,
                    "mfe_pct": max_favorable,
                    "left_on_table_pct": max_favorable - actual_return,
                })
                in_trade = False

        # Check for new entry
        if not in_trade:
            if signal == Signal.BUY:
                in_trade = True
                trade_side = "long"
                entry_price = candle["close"]
                entry_time = candle["timestamp"]
                max_favorable = 0.0
            elif signal == Signal.SELL:
                in_trade = True
                trade_side = "short"
                entry_price = candle["close"]
                entry_time = candle["timestamp"]
                max_favorable = 0.0

    return trades


def main() -> None:
    logger.info("Loading data...")
    btc_1m = load("BTC/USDT", "1m")
    eth_1m = load("ETH/USDT", "1m")

    btc_oos = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_oos = eth_1m[(eth_1m["timestamp"] >= "2024-09-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    btc_1h = resample_ohlcv(btc_oos, "1h")
    eth_1h = resample_ohlcv(eth_oos, "1h")

    params = {"donchian_period": 50, "volume_ma_period": 20, "atr_period": 14}

    for asset_name, data in [("BTC/USDT", btc_1h), ("ETH/USDT", eth_1h)]:
        trades = analyze_mfe(data, params)

        if not trades:
            print(f"\n{asset_name}: No trades found")
            continue

        mfes = [t["mfe_pct"] for t in trades]
        actuals = [t["actual_return_pct"] for t in trades]
        left = [t["left_on_table_pct"] for t in trades]

        winners = [t for t in trades if t["actual_return_pct"] > 0]
        losers = [t for t in trades if t["actual_return_pct"] <= 0]

        print(f"\n{'='*80}")
        print(f"  {asset_name} — VOLATILITY BREAKOUT MFE ANALYSIS (OOS: Sep-Dec 2024)")
        print(f"{'='*80}")
        print(f"  Total trades: {len(trades)}")
        print(f"  Winners: {len(winners)} | Losers: {len(losers)}")
        print(f"\n  ALL TRADES:")
        print(f"    Avg MFE (max unrealized):   {np.mean(mfes):+.2f}%")
        print(f"    Avg actual return:          {np.mean(actuals):+.2f}%")
        print(f"    Avg left on table:          {np.mean(left):+.2f}%")
        print(f"    Median MFE:                 {np.median(mfes):+.2f}%")
        print(f"    Max MFE seen:               {np.max(mfes):+.2f}%")

        if winners:
            w_mfes = [t["mfe_pct"] for t in winners]
            w_actuals = [t["actual_return_pct"] for t in winners]
            w_left = [t["left_on_table_pct"] for t in winners]
            print(f"\n  WINNING TRADES ({len(winners)}):")
            print(f"    Avg MFE:                    {np.mean(w_mfes):+.2f}%")
            print(f"    Avg actual return:          {np.mean(w_actuals):+.2f}%")
            print(f"    Avg left on table:          {np.mean(w_left):+.2f}%")
            print(f"    Capture ratio (actual/MFE): {np.mean(w_actuals)/np.mean(w_mfes)*100:.1f}%")

        if losers:
            l_mfes = [t["mfe_pct"] for t in losers]
            l_actuals = [t["actual_return_pct"] for t in losers]
            l_left = [t["left_on_table_pct"] for t in losers]
            print(f"\n  LOSING TRADES ({len(losers)}):")
            print(f"    Avg MFE (was positive by):  {np.mean(l_mfes):+.2f}%")
            print(f"    Avg actual return:          {np.mean(l_actuals):+.2f}%")
            print(f"    Avg left on table:          {np.mean(l_left):+.2f}%")

        # Distribution of MFE
        print(f"\n  MFE DISTRIBUTION:")
        buckets = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 20), (20, 50), (50, 100)]
        for lo, hi in buckets:
            count = sum(1 for m in mfes if lo <= m < hi)
            if count > 0:
                print(f"    {lo:>3}% - {hi:>3}%:  {count:>3} trades ({count/len(trades)*100:.1f}%)")
        count_100 = sum(1 for m in mfes if m >= 100)
        if count_100 > 0:
            print(f"    100%+:       {count_100:>3} trades ({count_100/len(trades)*100:.1f}%)")

        # Show top 10 trades by MFE
        trades_sorted = sorted(trades, key=lambda t: t["mfe_pct"], reverse=True)
        print(f"\n  TOP 10 TRADES BY MFE:")
        top_rows = []
        for t in trades_sorted[:10]:
            top_rows.append({
                "Side": t["side"],
                "Entry": f"${t['entry_price']:,.0f}",
                "Exit": f"${t['exit_price']:,.0f}",
                "MFE %": f"{t['mfe_pct']:+.2f}",
                "Actual %": f"{t['actual_return_pct']:+.2f}",
                "Left %": f"{t['left_on_table_pct']:+.2f}",
                "Entry Time": str(t["entry_time"])[:16],
            })
        print(tabulate(top_rows, headers="keys", tablefmt="simple", stralign="right"))
        print(f"{'='*80}")


if __name__ == "__main__":
    main()
