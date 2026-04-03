"""
Analyze what features predict next-candle color (green/red) on 5m and 15m BTC data.

For prediction markets, even a 53-55% edge is hugely profitable.
Test: momentum streaks, volume, time-of-day, RSI, candle patterns, volatility regime.
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
    """Add all candidate features for candle color prediction."""
    d = df.copy()
    c, o, h, l, v = d["close"], d["open"], d["high"], d["low"], d["volume"]

    # Target: next candle is green (1) or red (0)
    d["is_green"] = (c > o).astype(int)
    d["next_green"] = d["is_green"].shift(-1)

    # Current candle properties
    d["body_pct"] = (c - o) / o * 100
    d["range_pct"] = (h - l) / o * 100
    d["upper_wick_pct"] = np.where(c >= o, (h - c) / o * 100, (h - o) / o * 100)
    d["lower_wick_pct"] = np.where(c >= o, (o - l) / o * 100, (c - l) / o * 100)

    # Streaks: consecutive green/red candles
    streak = np.zeros(len(d))
    for i in range(1, len(d)):
        if d["is_green"].iloc[i] == d["is_green"].iloc[i - 1]:
            streak[i] = streak[i - 1] + (1 if d["is_green"].iloc[i] == 1 else -1)
        else:
            streak[i] = 1 if d["is_green"].iloc[i] == 1 else -1
    d["streak"] = streak

    # Recent momentum: sum of last N candle bodies
    for n in [3, 5, 10]:
        d[f"momentum_{n}"] = d["body_pct"].rolling(n).sum()

    # Volume features
    d["vol_ma_20"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d["vol_ma_20"]
    d["vol_change"] = v.pct_change()

    # RSI (14-period)
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    d["rsi"] = 100 - (100 / (1 + rs))

    # Bollinger position (where is price in the bands)
    d["bb_mid"] = c.rolling(20).mean()
    d["bb_std"] = c.rolling(20).std()
    d["bb_position"] = (c - d["bb_mid"]) / (d["bb_std"] + 1e-10)

    # EMA slopes
    ema9 = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    d["ema9_slope"] = (ema9 - ema9.shift(1)) / ema9.shift(1) * 100
    d["ema_cross"] = (ema9 > ema21).astype(int)

    # Hour of day (UTC)
    if hasattr(d["timestamp"].iloc[0], "hour"):
        d["hour"] = d["timestamp"].apply(lambda x: x.hour if hasattr(x, "hour") else x.to_pydatetime().hour)
    else:
        d["hour"] = pd.to_datetime(d["timestamp"]).dt.hour

    # Day of week
    if hasattr(d["timestamp"].iloc[0], "weekday"):
        d["dow"] = d["timestamp"].apply(lambda x: x.weekday() if hasattr(x, "weekday") else x.to_pydatetime().weekday())
    else:
        d["dow"] = pd.to_datetime(d["timestamp"]).dt.weekday

    # ATR ratio (current range vs avg range)
    d["atr_14"] = d["range_pct"].rolling(14).mean()
    d["range_ratio"] = d["range_pct"] / (d["atr_14"] + 1e-10)

    # Previous candle features
    d["prev_green"] = d["is_green"].shift(1)
    d["prev_body_pct"] = d["body_pct"].shift(1)
    d["prev_vol_ratio"] = d["vol_ratio"].shift(1)

    return d.dropna(subset=["next_green"])


def analyze_feature(df: pd.DataFrame, feature: str, bins: list | None = None,
                    labels: list | None = None) -> list[dict]:
    """Analyze P(next_green) conditioned on feature buckets."""
    d = df.dropna(subset=[feature, "next_green"]).copy()

    if bins is not None:
        d["bucket"] = pd.cut(d[feature], bins=bins, labels=labels, include_lowest=True)
    elif d[feature].nunique() <= 10:
        d["bucket"] = d[feature]
    else:
        d["bucket"] = pd.qcut(d[feature], q=5, duplicates="drop")

    rows = []
    for bucket, group in d.groupby("bucket", observed=True):
        n = len(group)
        if n < 30:
            continue
        green_pct = group["next_green"].mean() * 100
        rows.append({
            "Bucket": str(bucket),
            "N": n,
            "P(green)": f"{green_pct:.1f}%",
            "Edge": f"{green_pct - 50:+.1f}%",
            "_edge": green_pct - 50,
        })
    return rows


def main() -> None:
    logger.info("Loading BTC data...")
    btc_1m = load("BTC/USDT", "1m")

    # Full year for training analysis, OOS for validation
    full = btc_1m[(btc_1m["timestamp"] >= "2024-01-01") & (btc_1m["timestamp"] < "2024-09-01")].reset_index(drop=True)
    oos = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)

    for tf in ["5m", "15m"]:
        full_tf = resample_ohlcv(full, tf) if tf != "1m" else full
        oos_tf = resample_ohlcv(oos, tf) if tf != "1m" else oos

        full_feat = add_features(full_tf)
        oos_feat = add_features(oos_tf)

        baseline_full = full_feat["next_green"].mean() * 100
        baseline_oos = oos_feat["next_green"].mean() * 100

        print(f"\n{'#'*100}")
        print(f"  BTC/USDT {tf} — CANDLE COLOR PREDICTION ANALYSIS")
        print(f"  Train: Jan-Aug 2024 ({len(full_feat):,} candles) | OOS: Sep-Dec 2024 ({len(oos_feat):,} candles)")
        print(f"  Baseline P(green): Train={baseline_full:.1f}% | OOS={baseline_oos:.1f}%")
        print(f"{'#'*100}")

        # 1. Streak analysis
        print(f"\n  1. STREAK (consecutive same-color candles)")
        streak_bins = [-20, -5, -3, -2, -1, 0, 1, 2, 3, 5, 20]
        streak_labels = ["≤-5", "-4to-3", "-3to-2", "-2to-1", "-1to0", "0to1", "1to2", "2to3", "3to5", "≥5"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "streak", streak_bins, streak_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 2. Current candle color → next candle
        print(f"\n  2. CURRENT CANDLE COLOR → NEXT")
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "prev_green")
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 3. Body size
        print(f"\n  3. BODY SIZE (% move)")
        body_bins = [-10, -1.0, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.0, 10]
        body_labels = ["<-1%", "-1to-0.5", "-0.5to-0.2", "-0.2to-0.05", "flat", "0.05to0.2", "0.2to0.5", "0.5to1%", ">1%"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "body_pct", body_bins, body_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 4. Volume ratio
        print(f"\n  4. VOLUME RATIO (current vol / 20-period avg)")
        vol_bins = [0, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 100]
        vol_labels = ["<0.5x", "0.5-0.8x", "0.8-1.0x", "1.0-1.5x", "1.5-2.0x", "2.0-3.0x", ">3.0x"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "vol_ratio", vol_bins, vol_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 5. RSI zones
        print(f"\n  5. RSI ZONES")
        rsi_bins = [0, 20, 30, 40, 50, 60, 70, 80, 100]
        rsi_labels = ["<20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80", ">80"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "rsi", rsi_bins, rsi_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 6. Bollinger position
        print(f"\n  6. BOLLINGER BAND POSITION (std devs from mean)")
        bb_bins = [-5, -2, -1, -0.5, 0, 0.5, 1, 2, 5]
        bb_labels = ["<-2σ", "-2to-1σ", "-1to-0.5σ", "-0.5to0", "0to0.5σ", "0.5to1σ", "1to2σ", ">2σ"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "bb_position", bb_bins, bb_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 7. Hour of day
        print(f"\n  7. HOUR OF DAY (UTC)")
        hour_bins = [-0.5 + i for i in range(25)]  # -0.5, 0.5, 1.5, ..., 23.5
        hour_labels = [str(h) for h in range(24)]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "hour", hour_bins, hour_labels)
            if rows:
                # Only show hours with notable edge
                notable = [r for r in rows if abs(r["_edge"]) >= 1.0]
                if notable:
                    print(f"\n    {label} (hours with ≥1% edge):")
                    print(tabulate(notable, headers="keys", tablefmt="simple", stralign="right"))

        # 8. Momentum (sum of last N bodies)
        print(f"\n  8. MOMENTUM (sum of last 5 candle bodies %)")
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "momentum_5")
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 9. Range ratio (current range vs ATR)
        print(f"\n  9. RANGE RATIO (current range / ATR14)")
        range_bins = [0, 0.3, 0.6, 1.0, 1.5, 2.0, 3.0, 100]
        range_labels = ["<0.3x", "0.3-0.6x", "0.6-1.0x", "1.0-1.5x", "1.5-2.0x", "2.0-3.0x", ">3.0x"]
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "range_ratio", range_bins, range_labels)
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # 10. EMA cross state
        print(f"\n  10. EMA9 vs EMA21 (trend state)")
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            rows = analyze_feature(data, "ema_cross")
            if rows:
                print(f"\n    {label}:")
                print(tabulate(rows, headers="keys", tablefmt="simple", stralign="right"))

        # === COMBINED SIGNALS ===
        print(f"\n  {'='*80}")
        print(f"  COMBINED SIGNAL ANALYSIS")
        print(f"  {'='*80}")

        # Combine features that showed edge
        for label, data in [("TRAIN", full_feat), ("OOS", oos_feat)]:
            combos = []

            # Momentum continuation: strong green body + uptrend + volume
            mask = (data["body_pct"] > 0.2) & (data["ema_cross"] == 1) & (data["vol_ratio"] > 1.0)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "Strong green + uptrend + vol", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Momentum continuation: strong red body + downtrend + volume
            mask = (data["body_pct"] < -0.2) & (data["ema_cross"] == 0) & (data["vol_ratio"] > 1.0)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "Strong red + downtrend + vol", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Mean reversion: oversold RSI + big red candle
            mask = (data["rsi"] < 30) & (data["body_pct"] < -0.2)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "RSI<30 + big red", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Mean reversion: overbought RSI + big green candle
            mask = (data["rsi"] > 70) & (data["body_pct"] > 0.2)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "RSI>70 + big green", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Streak exhaustion: 3+ greens in a row
            mask = data["streak"] >= 3
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "3+ green streak", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Streak exhaustion: 3+ reds in a row
            mask = data["streak"] <= -3
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "3+ red streak", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Big body + high volume (continuation)
            mask = (data["body_pct"].abs() > 0.5) & (data["vol_ratio"] > 2.0)
            grp = data[mask]
            if len(grp) >= 30:
                g_green = grp[grp["body_pct"] > 0]["next_green"].mean() * 100 if len(grp[grp["body_pct"] > 0]) >= 10 else np.nan
                g_red = grp[grp["body_pct"] < 0]["next_green"].mean() * 100 if len(grp[grp["body_pct"] < 0]) >= 10 else np.nan
                if not np.isnan(g_green):
                    combos.append({"Signal": "Big green + 2x vol", "N": len(grp[grp["body_pct"] > 0]), "P(green)": f"{g_green:.1f}%", "Edge": f"{g_green-50:+.1f}%"})
                if not np.isnan(g_red):
                    combos.append({"Signal": "Big red + 2x vol", "N": len(grp[grp["body_pct"] < 0]), "P(green)": f"{g_red:.1f}%", "Edge": f"{g_red-50:+.1f}%"})

            # Bollinger squeeze + breakout
            mask = (data["bb_position"] > 2) & (data["body_pct"] > 0.1)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "Above +2σ BB + green", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            mask = (data["bb_position"] < -2) & (data["body_pct"] < -0.1)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "Below -2σ BB + red", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            # Low vol flat candle → breakout pending (no directional edge expected)
            mask = (data["vol_ratio"] < 0.5) & (data["body_pct"].abs() < 0.05)
            grp = data[mask]
            if len(grp) >= 30:
                g = grp["next_green"].mean() * 100
                combos.append({"Signal": "Low vol + flat candle", "N": len(grp), "P(green)": f"{g:.1f}%", "Edge": f"{g-50:+.1f}%"})

            if combos:
                combos.sort(key=lambda x: abs(float(x["Edge"].rstrip("%"))), reverse=True)
                print(f"\n    {label}:")
                print(tabulate(combos, headers="keys", tablefmt="simple", stralign="right"))

    print(f"\n{'#'*100}")
    print(f"  SUMMARY: Features marked as promising if edge is consistent (same direction)")
    print(f"  between TRAIN and OOS with |edge| >= 1.5% and N >= 50 in both periods.")
    print(f"{'#'*100}")


if __name__ == "__main__":
    main()
