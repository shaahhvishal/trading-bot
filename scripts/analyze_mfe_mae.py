"""
Analyze MFE (max favorable) and MAE (max adverse) excursion for Volatility Breakout.

MFE = highest unrealized % profit during trade
MAE = deepest unrealized % loss during trade

This tells us: how far do trades go in our favor AND against us before exit?
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


def analyze(data_1h: pd.DataFrame, params: dict) -> list[dict]:
    """Run strategy and track MFE + MAE for each trade."""
    strat = VolatilityBreakoutStrategy(params=params)
    strat.reset()
    strat.prepare(data_1h)

    trades = []
    in_trade = False
    trade_side = ""
    entry_price = 0.0
    entry_time = None
    max_favorable = 0.0
    max_adverse = 0.0
    candles_in_trade = 0
    candle_at_mfe = 0  # how many candles in when MFE was hit

    columns = data_1h.columns.tolist()
    for row in data_1h.itertuples(index=False):
        candle = dict(zip(columns, row))
        signal = strat.on_candle(candle)

        if in_trade:
            candles_in_trade += 1

            # Track MFE (best case)
            if trade_side == "long":
                best_price = candle["high"]
                worst_price = candle["low"]
                current_mfe = (best_price - entry_price) / entry_price * 100
                current_mae = (entry_price - worst_price) / entry_price * 100
            else:
                best_price = candle["low"]
                worst_price = candle["high"]
                current_mfe = (entry_price - best_price) / entry_price * 100
                current_mae = (worst_price - entry_price) / entry_price * 100

            if current_mfe > max_favorable:
                max_favorable = current_mfe
                candle_at_mfe = candles_in_trade
            max_adverse = max(max_adverse, current_mae)

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
                    "mae_pct": max_adverse,
                    "left_on_table_pct": max_favorable - actual_return,
                    "candles_held": candles_in_trade,
                    "candle_at_mfe": candle_at_mfe,
                })
                in_trade = False

        if not in_trade:
            if signal == Signal.BUY:
                in_trade = True
                trade_side = "long"
                entry_price = candle["close"]
                entry_time = candle["timestamp"]
                max_favorable = 0.0
                max_adverse = 0.0
                candles_in_trade = 0
                candle_at_mfe = 0
            elif signal == Signal.SELL:
                in_trade = True
                trade_side = "short"
                entry_price = candle["close"]
                entry_time = candle["timestamp"]
                max_favorable = 0.0
                max_adverse = 0.0
                candles_in_trade = 0
                candle_at_mfe = 0

    return trades


def print_analysis(asset: str, trades: list[dict]) -> None:
    if not trades:
        print(f"\n{asset}: No trades found")
        return

    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    actuals = [t["actual_return_pct"] for t in trades]
    left = [t["left_on_table_pct"] for t in trades]
    durations = [t["candles_held"] for t in trades]

    winners = [t for t in trades if t["actual_return_pct"] > 0]
    losers = [t for t in trades if t["actual_return_pct"] <= 0]

    print(f"\n{'='*90}")
    print(f"  {asset} — MFE + MAE ANALYSIS (OOS: Sep-Dec 2024)")
    print(f"{'='*90}")
    print(f"  Total trades: {len(trades)} | Winners: {len(winners)} | Losers: {len(losers)}")
    print(f"  Avg hold time: {np.mean(durations):.0f}h | Median: {np.median(durations):.0f}h")

    print(f"\n  {'':30s}  {'MFE':>10s}  {'MAE':>10s}  {'Actual':>10s}  {'Left':>10s}")
    print(f"  {'-'*30}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(f"  {'ALL TRADES':30s}  {np.mean(mfes):>+9.2f}%  {np.mean(maes):>+9.2f}%  {np.mean(actuals):>+9.2f}%  {np.mean(left):>+9.2f}%")
    if winners:
        w = winners
        print(f"  {'WINNERS':30s}  {np.mean([t['mfe_pct'] for t in w]):>+9.2f}%  {np.mean([t['mae_pct'] for t in w]):>+9.2f}%  {np.mean([t['actual_return_pct'] for t in w]):>+9.2f}%  {np.mean([t['left_on_table_pct'] for t in w]):>+9.2f}%")
    if losers:
        l = losers
        print(f"  {'LOSERS':30s}  {np.mean([t['mfe_pct'] for t in l]):>+9.2f}%  {np.mean([t['mae_pct'] for t in l]):>+9.2f}%  {np.mean([t['actual_return_pct'] for t in l]):>+9.2f}%  {np.mean([t['left_on_table_pct'] for t in l]):>+9.2f}%")

    # MAE distribution — helps determine stop loss
    print(f"\n  MAE DISTRIBUTION (max drawdown during trade):")
    mae_buckets = [(0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 5), (5, 8), (8, 15), (15, 50)]
    for lo, hi in mae_buckets:
        count = sum(1 for m in maes if lo <= m < hi)
        w_count = sum(1 for t in winners if lo <= t["mae_pct"] < hi)
        l_count = sum(1 for t in losers if lo <= t["mae_pct"] < hi)
        if count > 0:
            print(f"    {lo:>4.1f}% - {hi:>4.1f}%:  {count:>3} trades  (W:{w_count} L:{l_count})")

    # MFE distribution — helps determine take profit
    print(f"\n  MFE DISTRIBUTION (max unrealized profit during trade):")
    mfe_buckets = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 8), (8, 15), (15, 25), (25, 50)]
    for lo, hi in mfe_buckets:
        count = sum(1 for m in mfes if lo <= m < hi)
        w_count = sum(1 for t in winners if lo <= t["mfe_pct"] < hi)
        l_count = sum(1 for t in losers if lo <= t["mfe_pct"] < hi)
        if count > 0:
            print(f"    {lo:>4.1f}% - {hi:>4.1f}%:  {count:>3} trades  (W:{w_count} L:{l_count})")

    # Simulate different TP/SL combos
    print(f"\n  SIMULATED TP/SL PERFORMANCE:")
    print(f"  {'TP %':>6s}  {'SL %':>6s}  {'Wins':>6s}  {'Losses':>8s}  {'WR':>6s}  {'Avg W':>8s}  {'Avg L':>8s}  {'PF':>8s}  {'Total %':>10s}")
    print(f"  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*10}")

    for tp in [3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
        for sl in [1.5, 2.0, 3.0, 4.0, 5.0]:
            sim_wins = 0
            sim_losses = 0
            sim_total_pnl = 0.0
            win_pnl = []
            loss_pnl = []

            for t in trades:
                # Did MAE hit SL first, or MFE hit TP first?
                # We need to check which happened first chronologically
                # Since we don't have bar-by-bar data here, use heuristic:
                # If MAE >= SL, it's a loss (stopped out)
                # If MFE >= TP and MAE < SL, it's a TP win
                # Otherwise, use actual exit
                if t["mae_pct"] >= sl:
                    # Stopped out
                    sim_losses += 1
                    sim_total_pnl -= sl
                    loss_pnl.append(-sl)
                elif t["mfe_pct"] >= tp:
                    # TP hit (and didn't get stopped first)
                    sim_wins += 1
                    sim_total_pnl += tp
                    win_pnl.append(tp)
                else:
                    # Neither hit, use actual exit
                    pnl = t["actual_return_pct"]
                    if pnl > 0:
                        sim_wins += 1
                        win_pnl.append(pnl)
                    else:
                        sim_losses += 1
                        loss_pnl.append(pnl)
                    sim_total_pnl += pnl

            total = sim_wins + sim_losses
            wr = sim_wins / total * 100 if total > 0 else 0
            avg_w = np.mean(win_pnl) if win_pnl else 0
            avg_l = np.mean(loss_pnl) if loss_pnl else 0
            gross_w = sum(win_pnl) if win_pnl else 0
            gross_l = abs(sum(loss_pnl)) if loss_pnl else 0.001
            pf = gross_w / gross_l if gross_l > 0 else 0

            print(f"  {tp:>5.1f}%  {sl:>5.1f}%  {sim_wins:>6d}  {sim_losses:>8d}  {wr:>5.1f}%  {avg_w:>+7.2f}%  {avg_l:>+7.2f}%  {pf:>7.2f}  {sim_total_pnl:>+9.2f}%")

    # Every trade detail
    print(f"\n  ALL TRADES DETAIL:")
    rows = []
    for t in sorted(trades, key=lambda x: x["entry_time"]):
        rows.append({
            "Side": t["side"],
            "Entry": f"${t['entry_price']:,.0f}",
            "Exit": f"${t['exit_price']:,.0f}",
            "MFE %": f"{t['mfe_pct']:+.2f}",
            "MAE %": f"{t['mae_pct']:+.2f}",
            "Actual %": f"{t['actual_return_pct']:+.2f}",
            "Left %": f"{t['left_on_table_pct']:+.2f}",
            "Hours": t["candles_held"],
            "MFE@h": t["candle_at_mfe"],
        })
    print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))
    print(f"{'='*90}")


def main() -> None:
    logger.info("Loading data...")
    btc_1m = load("BTC/USDT", "1m")
    eth_1m = load("ETH/USDT", "1m")

    # Use full year for more data points, plus OOS
    btc_full = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    eth_full = eth_1m[(eth_1m["timestamp"] >= "2024-01-01") & (eth_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    btc_1h = resample_ohlcv(btc_full, "1h")
    eth_1h = resample_ohlcv(eth_full, "1h")

    params = {"donchian_period": 50, "volume_ma_period": 20, "atr_period": 14}

    for asset_name, data in [("BTC/USDT", btc_1h), ("ETH/USDT", eth_1h)]:
        trades = analyze(data, params)
        print_analysis(asset_name, trades)


if __name__ == "__main__":
    main()
