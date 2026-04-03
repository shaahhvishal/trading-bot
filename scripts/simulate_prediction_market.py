"""
Simulate prediction market P&L for 15m BTC candle color prediction.

Combines signals with proven edge from MFE/MAE analysis:
  - Mean reversion: RSI oversold → predict GREEN
  - Negative momentum → predict GREEN (bounce)
  - High volume → predict GREEN
  - Big range candles → continuation
  - Momentum continuation: strong candle + trend + volume

Assumes prediction market mechanics:
  - Pay $1 per bet
  - Win payout varies (e.g., 1.85x, 1.90x, 1.95x) depending on market
  - Need win rate > 1/payout to be profitable

Tests individual signals AND combined scoring system.
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


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add prediction features to 15m data."""
    d = df.copy()
    c, o, h, l, v = d["close"], d["open"], d["high"], d["low"], d["volume"]

    d["is_green"] = (c > o).astype(int)
    d["next_green"] = d["is_green"].shift(-1)

    d["body_pct"] = (c - o) / o * 100
    d["range_pct"] = (h - l) / o * 100

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    d["rsi"] = 100 - (100 / (1 + rs))

    # Volume ratio
    d["vol_ma_20"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d["vol_ma_20"]

    # Momentum: sum of last 5 bodies
    d["momentum_5"] = d["body_pct"].rolling(5).sum()

    # Bollinger position
    d["bb_mid"] = c.rolling(20).mean()
    d["bb_std"] = c.rolling(20).std()
    d["bb_position"] = (c - d["bb_mid"]) / (d["bb_std"] + 1e-10)

    # ATR and range ratio
    d["atr_14"] = d["range_pct"].rolling(14).mean()
    d["range_ratio"] = d["range_pct"] / (d["atr_14"] + 1e-10)

    # EMA trend
    ema9 = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    d["ema_cross"] = (ema9 > ema21).astype(int)
    d["ema9_slope"] = (ema9 - ema9.shift(1)) / ema9.shift(1) * 100

    # Streak
    streak = np.zeros(len(d))
    for i in range(1, len(d)):
        if d["is_green"].iloc[i] == d["is_green"].iloc[i - 1]:
            streak[i] = streak[i - 1] + (1 if d["is_green"].iloc[i] == 1 else -1)
        else:
            streak[i] = 1 if d["is_green"].iloc[i] == 1 else -1
    d["streak"] = streak

    return d.dropna(subset=["next_green", "rsi", "vol_ratio", "momentum_5", "bb_position"])


def score_candle(row) -> tuple[str, float]:
    """Score a candle and return (prediction, confidence).

    Returns:
        ("green", score) or ("red", score) or ("skip", 0)
        Score 1-5 indicates confidence level (number of agreeing signals).
    """
    green_score = 0
    red_score = 0

    # Signal 1: RSI oversold → GREEN (mean reversion)
    # Train: 55-56%, OOS: 53-57%
    if row["rsi"] < 20:
        green_score += 2  # strong signal
    elif row["rsi"] < 30:
        green_score += 1

    # Signal 2: RSI overbought → RED (mean reversion)
    # Train: 48%, OOS: 48% — weaker but symmetric
    if row["rsi"] > 80:
        red_score += 1
    elif row["rsi"] > 70:
        red_score += 0.5

    # Signal 3: Negative momentum → GREEN (bounce)
    # Train: 53.7%, OOS: 52.8% — robust with large N
    if row["momentum_5"] < -0.5:
        green_score += 1.5
    elif row["momentum_5"] < -0.3:
        green_score += 1

    # Signal 4: Positive momentum → RED (mean reversion)
    if row["momentum_5"] > 0.5:
        red_score += 1
    elif row["momentum_5"] > 0.3:
        red_score += 0.5

    # Signal 5: High volume (1.5-2x) → GREEN
    # Train: 53.3%, OOS: 53.0%
    if 1.5 <= row["vol_ratio"] <= 2.5:
        green_score += 1

    # Signal 6: Big range candle (>1.5x ATR) → continuation
    # Train: 55%, OOS: 51.4%
    if row["range_ratio"] > 1.5:
        if row["body_pct"] < -0.2:  # big red → predict GREEN (reversal)
            green_score += 1
        elif row["body_pct"] > 0.2:  # big green → predict GREEN (continuation)
            green_score += 0.5

    # Signal 7: Below -2σ BB → GREEN (mean reversion)
    # Train: 55.8%, OOS: 51.5%
    if row["bb_position"] < -2:
        green_score += 1
    elif row["bb_position"] > 2:
        red_score += 0.5

    # Signal 8: Red streak (3+) → GREEN (mean reversion)
    # Train: 52.7%, OOS: 50.8%
    if row["streak"] <= -3:
        green_score += 0.5

    # Net score
    net = green_score - red_score

    if net >= 1.5:
        return ("green", net)
    elif net <= -1.5:
        return ("red", abs(net))
    else:
        return ("skip", 0)


def simulate(data: pd.DataFrame, min_confidence: float, payout: float,
             bet_size: float = 1.0) -> dict:
    """Simulate prediction market P&L.

    Args:
        data: DataFrame with features and next_green column.
        min_confidence: Minimum score to place a bet.
        payout: Win payout multiplier (e.g., 1.85 means pay $1, win $1.85).
        bet_size: Amount per bet.

    Returns:
        Dict with simulation results.
    """
    bets = 0
    wins = 0
    pnl = 0.0
    pnl_curve = []
    green_bets = 0
    green_wins = 0
    red_bets = 0
    red_wins = 0

    for _, row in data.iterrows():
        prediction, confidence = score_candle(row)

        if prediction == "skip" or confidence < min_confidence:
            continue

        bets += 1
        actual_green = row["next_green"] == 1

        if prediction == "green":
            green_bets += 1
            correct = actual_green
            if correct:
                green_wins += 1
        else:
            red_bets += 1
            correct = not actual_green
            if correct:
                red_wins += 1

        if correct:
            wins += 1
            pnl += bet_size * (payout - 1)  # profit = payout - stake
        else:
            pnl -= bet_size  # lose the stake

        pnl_curve.append(pnl)

    wr = wins / bets * 100 if bets > 0 else 0
    breakeven_wr = 1 / payout * 100

    return {
        "bets": bets,
        "wins": wins,
        "win_rate": wr,
        "breakeven_wr": breakeven_wr,
        "edge": wr - breakeven_wr,
        "pnl": pnl,
        "roi": pnl / (bets * bet_size) * 100 if bets > 0 else 0,
        "green_bets": green_bets,
        "green_wr": green_wins / green_bets * 100 if green_bets > 0 else 0,
        "red_bets": red_bets,
        "red_wr": red_wins / red_bets * 100 if red_bets > 0 else 0,
        "pnl_curve": pnl_curve,
        "max_dd": min(pnl_curve) if pnl_curve else 0,
    }


def main() -> None:
    logger.info("Loading BTC data...")
    btc_1m = load("BTC/USDT", "1m")

    train_1m = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2024-09-01")].reset_index(drop=True)
    oos_1m = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    train_15m = resample_ohlcv(train_1m, "15m")
    oos_15m = resample_ohlcv(oos_1m, "15m")

    train = add_features(train_15m)
    oos = add_features(oos_15m)

    logger.info(f"Train: {len(train):,} candles | OOS: {len(oos):,} candles")

    # Test across different payout rates and confidence thresholds
    payouts = [1.80, 1.85, 1.90, 1.95]
    min_confs = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

    for label, data in [("TRAIN (Jan-Aug 2024)", train), ("OOS (Sep-Dec 2024)", oos)]:
        print(f"\n{'='*130}")
        print(f"  {label} — PREDICTION MARKET SIMULATION (15m BTC candles)")
        print(f"{'='*130}")

        results = []
        for payout in payouts:
            for mc in min_confs:
                sim = simulate(data, min_confidence=mc, payout=payout)
                if sim["bets"] < 20:
                    continue
                results.append({
                    "Payout": f"{payout:.2f}x",
                    "Min Conf": mc,
                    "Bets": sim["bets"],
                    "Wins": sim["wins"],
                    "WR %": f"{sim['win_rate']:.1f}",
                    "BE WR %": f"{sim['breakeven_wr']:.1f}",
                    "Edge %": f"{sim['edge']:+.1f}",
                    "P&L ($)": f"{sim['pnl']:+.1f}",
                    "ROI %": f"{sim['roi']:+.1f}",
                    "Green Bets": sim["green_bets"],
                    "Green WR %": f"{sim['green_wr']:.1f}",
                    "Red Bets": sim["red_bets"],
                    "Red WR %": f"{sim['red_wr']:.1f}",
                    "Max DD ($)": f"{sim['max_dd']:.1f}",
                    "_roi": sim["roi"],
                })

        results.sort(key=lambda x: x["_roi"], reverse=True)
        display = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
        print(tabulate(display, headers="keys", tablefmt="simple", stralign="right"))

    # Detailed breakdown for best OOS config
    print(f"\n{'='*130}")
    print(f"  DETAILED SIGNAL BREAKDOWN (OOS)")
    print(f"{'='*130}")

    # Show per-signal performance
    signals = {
        "RSI < 20": lambda r: r["rsi"] < 20,
        "RSI < 30": lambda r: r["rsi"] < 30,
        "RSI > 70": lambda r: r["rsi"] > 70,
        "RSI > 80": lambda r: r["rsi"] > 80,
        "Momentum < -0.5": lambda r: r["momentum_5"] < -0.5,
        "Momentum < -0.3": lambda r: r["momentum_5"] < -0.3,
        "Momentum > 0.3": lambda r: r["momentum_5"] > 0.3,
        "Momentum > 0.5": lambda r: r["momentum_5"] > 0.5,
        "Vol 1.5-2.5x": lambda r: 1.5 <= r["vol_ratio"] <= 2.5,
        "BB < -2σ": lambda r: r["bb_position"] < -2,
        "BB > +2σ": lambda r: r["bb_position"] > 2,
        "Range > 1.5x ATR": lambda r: r["range_ratio"] > 1.5,
        "Red streak ≥3": lambda r: r["streak"] <= -3,
        "Green streak ≥3": lambda r: r["streak"] >= 3,
        "Big red (< -0.3%)": lambda r: r["body_pct"] < -0.3,
        "Big green (> 0.3%)": lambda r: r["body_pct"] > 0.3,
    }

    sig_results = []
    for sig_name, condition in signals.items():
        mask = oos.apply(condition, axis=1)
        grp = oos[mask]
        if len(grp) < 20:
            continue
        p_green = grp["next_green"].mean() * 100
        sig_results.append({
            "Signal": sig_name,
            "N": len(grp),
            "P(green)": f"{p_green:.1f}%",
            "P(red)": f"{100-p_green:.1f}%",
            "Best Bet": "GREEN" if p_green > 52 else ("RED" if p_green < 48 else "SKIP"),
            "Edge vs 50%": f"{abs(p_green - 50):+.1f}%",
        })

    sig_results.sort(key=lambda x: abs(float(x["Edge vs 50%"].rstrip("%"))), reverse=True)
    print(tabulate(sig_results, headers="keys", tablefmt="simple", stralign="right"))

    # Monthly P&L for best config
    print(f"\n{'='*130}")
    print(f"  MONTHLY P&L BREAKDOWN (OOS, payout=1.90x, min_conf=2.0)")
    print(f"{'='*130}")

    oos_with_month = oos.copy()
    if hasattr(oos_with_month["timestamp"].iloc[0], "month"):
        oos_with_month["month"] = oos_with_month["timestamp"].apply(
            lambda x: f"{x.year}-{x.month:02d}" if hasattr(x, "year") else str(x)[:7]
        )
    else:
        oos_with_month["month"] = pd.to_datetime(oos_with_month["timestamp"]).dt.strftime("%Y-%m")

    monthly_rows = []
    for month, grp in oos_with_month.groupby("month"):
        sim = simulate(grp, min_confidence=2.0, payout=1.90)
        if sim["bets"] == 0:
            continue
        monthly_rows.append({
            "Month": month,
            "Bets": sim["bets"],
            "Wins": sim["wins"],
            "WR %": f"{sim['win_rate']:.1f}",
            "P&L ($)": f"{sim['pnl']:+.1f}",
            "ROI %": f"{sim['roi']:+.1f}",
            "Green Bets": sim["green_bets"],
            "Red Bets": sim["red_bets"],
        })
    print(tabulate(monthly_rows, headers="keys", tablefmt="simple", stralign="right"))

    # P&L curve stats for best config
    sim_best = simulate(oos, min_confidence=2.0, payout=1.90)
    curve = sim_best["pnl_curve"]
    if curve:
        peak = max(curve)
        dd_from_peak = min(c - max(curve[:i+1]) for i, c in enumerate(curve))
        print(f"\n  Best config summary (1.90x payout, conf≥2.0):")
        print(f"    Total bets:  {sim_best['bets']}")
        print(f"    Win rate:    {sim_best['win_rate']:.1f}% (need {sim_best['breakeven_wr']:.1f}% to break even)")
        print(f"    Edge:        {sim_best['edge']:+.1f}%")
        print(f"    Total P&L:   ${sim_best['pnl']:+.1f} on ${sim_best['bets']} wagered")
        print(f"    ROI:         {sim_best['roi']:+.1f}%")
        print(f"    Peak P&L:    ${peak:+.1f}")
        print(f"    Max DD:      ${dd_from_peak:.1f}")
        print(f"    Green bets:  {sim_best['green_bets']} ({sim_best['green_wr']:.1f}% WR)")
        print(f"    Red bets:    {sim_best['red_bets']} ({sim_best['red_wr']:.1f}% WR)")


if __name__ == "__main__":
    main()
