"""Validate CandlePredictorStrategy matches simulation results on OOS data."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from data.resample import resample_ohlcv
from data.store import load
from strategies.candle_predictor import CandlePredictorStrategy, Prediction


def main() -> None:
    logger.info("Loading data...")
    btc_1m = load("BTC/USDT", "1m")
    oos_1m = btc_1m[(btc_1m["timestamp"] >= "2024-09-01") & (btc_1m["timestamp"] < "2025-01-01")].reset_index(drop=True)
    oos_15m = resample_ohlcv(oos_1m, "15m")

    for min_conf in [2.0, 3.0, 4.0]:
        strat = CandlePredictorStrategy(params={"min_confidence": min_conf})

        bets = 0
        wins = 0
        green_bets = 0
        green_wins = 0

        columns = oos_15m.columns.tolist()
        rows = list(oos_15m.itertuples(index=False))

        for i, row in enumerate(rows):
            candle = dict(zip(columns, row))
            pred = strat.on_candle(candle)

            if not pred.should_bet or i >= len(rows) - 1:
                continue

            # Check next candle
            next_candle = dict(zip(columns, rows[i + 1]))
            next_green = next_candle["close"] > next_candle["open"]

            bets += 1
            if pred.direction == Prediction.GREEN:
                green_bets += 1
                if next_green:
                    wins += 1
                    green_wins += 1
            elif pred.direction == Prediction.RED:
                if not next_green:
                    wins += 1

        wr = wins / bets * 100 if bets > 0 else 0
        gwr = green_wins / green_bets * 100 if green_bets > 0 else 0

        # P&L at 1.90x payout
        pnl_190 = wins * 0.90 - (bets - wins) * 1.0

        print(f"\n  min_conf={min_conf}: {bets} bets | {wins} wins | WR={wr:.1f}% | "
              f"Green: {green_bets} ({gwr:.1f}% WR) | "
              f"P&L@1.90x: ${pnl_190:+.1f}")

        # Show some example predictions
        if min_conf == 4.0:
            strat2 = CandlePredictorStrategy(params={"min_confidence": 4.0})
            print(f"\n  Sample predictions (conf>=4.0):")
            count = 0
            for i, row in enumerate(rows):
                candle = dict(zip(columns, row))
                pred = strat2.on_candle(candle)
                if pred.should_bet and i < len(rows) - 1:
                    next_candle = dict(zip(columns, rows[i + 1]))
                    next_green = next_candle["close"] > next_candle["open"]
                    result = "✓" if (pred.direction == "green" and next_green) else "✗"
                    ts = str(candle["timestamp"])[:16]
                    print(f"    {ts} | {pred.direction.upper()} conf={pred.confidence:.1f} | "
                          f"Next={'GREEN' if next_green else 'RED'} {result} | {pred.signals}")
                    count += 1
                    if count >= 15:
                        break

    print()


if __name__ == "__main__":
    main()
