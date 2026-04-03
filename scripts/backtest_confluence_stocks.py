"""
Backtest Confluence strategy on Mag 7 stocks (daily candles).

The confluence strategy was built for 1H crypto with 4H/Daily HTF.
For daily stock data, we adapt:
  - Primary timeframe: Daily (instead of 1H)
  - HTF: Weekly + Monthly (instead of 4H + Daily)

Usage:
    python scripts/backtest_confluence_stocks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import ta
from loguru import logger

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import print_report
from data.store import load
from strategies.confluence import ConfluenceStrategy


class StockConfluenceStrategy(ConfluenceStrategy):
    """Confluence strategy adapted for daily stock data.

    Overrides prepare() to use Weekly + Monthly as higher timeframes
    instead of 4H + Daily (which are for 1H crypto data).
    """

    def prepare(self, data: pd.DataFrame) -> None:
        """Pre-compute indicators on Daily data + resample to Weekly/Monthly."""
        close = data["close"]
        high = data["high"]
        low = data["low"]

        self._close_arr = close.to_numpy()
        self._high_arr = high.to_numpy()
        self._low_arr = low.to_numpy()

        # Daily indicators
        self._ema_fast_arr = ta.trend.ema_indicator(close, window=self.ema_fast).to_numpy()
        self._ema_slow_arr = ta.trend.ema_indicator(close, window=self.ema_slow).to_numpy()
        self._rsi_arr = ta.momentum.rsi(close, window=self.rsi_period).to_numpy()

        # Resample to Weekly
        data_ts = data.copy()
        data_ts["timestamp"] = pd.to_datetime(data_ts["timestamp"])
        data_ts = data_ts.set_index("timestamp")

        resampled_w = data_ts.resample("W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        ema_50_w = ta.trend.ema_indicator(resampled_w["close"], window=self.ema_fast)
        self._ema_50_4h = ema_50_w.reindex(data_ts.index, method="ffill").to_numpy()
        self._ema_200_4h = ta.trend.ema_indicator(
            resampled_w["close"], window=self.ema_slow
        ).reindex(data_ts.index, method="ffill").to_numpy()
        self._close_4h = resampled_w["close"].reindex(data_ts.index, method="ffill").to_numpy()

        # Resample to Monthly
        resampled_m = data_ts.resample("ME").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        ema_50_m = ta.trend.ema_indicator(resampled_m["close"], window=min(self.ema_fast, len(resampled_m)))
        self._ema_50_1d = ema_50_m.reindex(data_ts.index, method="ffill").to_numpy()
        self._ema_200_1d = ta.trend.ema_indicator(
            resampled_m["close"], window=min(self.ema_slow, len(resampled_m))
        ).reindex(data_ts.index, method="ffill").to_numpy()
        self._close_1d = resampled_m["close"].reindex(data_ts.index, method="ffill").to_numpy()

        self._prepared = True


def run_stock(ticker: str, config: BacktestConfig, entry: int, exit_t: int) -> dict | None:
    """Run confluence backtest on a single stock."""
    try:
        data = load(ticker, "1d")
    except FileNotFoundError:
        logger.warning(f"{ticker}: no data found, skipping")
        return None

    # Use shorter lookbacks for daily data (200 days is ~10 months)
    strat = StockConfluenceStrategy(params={
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_period": 14,
        "fib_swing_lookback": 60,
        "sr_lookback": 40,
        "tl_swing_lookback": 5,
        "entry_threshold": entry,
        "exit_threshold": exit_t,
    })

    engine = BacktestEngine(config)
    result = engine.run(strat, data)
    return {
        "ticker": ticker,
        "return_pct": result.total_return_pct,
        "sharpe": result.sharpe_ratio,
        "trades": result.num_trades,
        "win_rate": result.win_rate,
        "max_dd": result.max_drawdown_pct,
        "pf": result.profit_factor,
        "result": result,
    }


def main() -> None:
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

    config = BacktestConfig(
        initial_capital=10_000.0,
        taker_fee=0.001,  # typical stock commission ~0.1%
        position_size_pct=1.0,
        long_only=True,
    )

    # --- Run all Mag 7 with default thresholds ---
    print("=" * 70)
    print("CONFLUENCE STRATEGY — MAG 7 STOCKS (Daily, entry>=6, exit<=2)")
    print("=" * 70)

    results = []
    for ticker in tickers:
        r = run_stock(ticker, config, entry=6, exit_t=2)
        if r:
            results.append(r)

    # Summary table
    print(f"\n{'Ticker':<8} {'Return%':>10} {'Sharpe':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'MaxDD%':>8}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x["return_pct"], reverse=True):
        print(
            f"{r['ticker']:<8} {r['return_pct']:>+10.2f} {r['sharpe']:>8.2f} "
            f"{r['trades']:>7} {r['win_rate']:>5.1f}% {r['pf']:>5.2f} {r['max_dd']:>7.1f}%"
        )

    # Portfolio return (equal-weight)
    if results:
        avg_return = sum(r["return_pct"] for r in results) / len(results)
        avg_sharpe = sum(r["sharpe"] for r in results) / len(results)
        print(f"\n{'AVG':<8} {avg_return:>+10.2f} {avg_sharpe:>8.2f}")

    # --- Show best stock in detail ---
    if results:
        best = max(results, key=lambda x: x["return_pct"])
        print(f"\n{'='*70}")
        print(f"BEST: {best['ticker']} DETAILED REPORT")
        print(f"{'='*70}")
        print_report(best["result"], show_trades=15)

    # --- Threshold sweep on best stock ---
    if results:
        best_ticker = best["ticker"]
        print(f"\n{'='*70}")
        print(f"THRESHOLD SWEEP — {best_ticker}")
        print(f"{'='*70}")

        sweep = []
        for entry in [5, 6, 7, 8]:
            for exit_t in [2, 3, 4]:
                if exit_t >= entry:
                    continue
                r = run_stock(best_ticker, config, entry, exit_t)
                if r:
                    sweep.append(r | {"entry": entry, "exit": exit_t})

        print(f"\n{'Entry':>6} {'Exit':>5} {'Return%':>10} {'Sharpe':>8} {'Trades':>7} {'WR%':>6} {'PF':>6} {'MaxDD%':>8}")
        print("-" * 62)
        for r in sorted(sweep, key=lambda x: x["return_pct"], reverse=True):
            print(
                f"{r['entry']:>6} {r['exit']:>5} {r['return_pct']:>+10.2f} "
                f"{r['sharpe']:>8.2f} {r['trades']:>7} {r['win_rate']:>5.1f}% "
                f"{r['pf']:>5.2f} {r['max_dd']:>7.1f}%"
            )


if __name__ == "__main__":
    main()
