"""
Final Phase 2 comparison: all strategies on OUT-OF-SAMPLE data only.

OOS period: Sep 1 2024 → Dec 31 2024 (4 months)
Training was done on Jan-Aug 2024.

This is the honest performance — no peeking at parameters that were
optimized on this data.

Usage:
    python scripts/final_comparison.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from data.resample import resample_ohlcv
from data.store import load


def _load_settings() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    settings = _load_settings()

    # Load 1m data and slice to OOS period only
    logger.info("Loading BTC/USDT 1m data (OOS period: Sep-Dec 2024)...")
    data_1m = load("BTC/USDT", "1m")
    oos_1m = data_1m[
        (data_1m["timestamp"] >= "2024-09-01") & (data_1m["timestamp"] < "2025-01-01")
    ].reset_index(drop=True)
    logger.info(f"OOS data: {len(oos_1m):,} candles")

    # Define all strategy/timeframe combos to test
    combos = [
        # Winners from optimization
        ("momentum", "1h", {
            "ema_period": 30, "rsi_period": 14,
            "rsi_long_threshold": 50, "rsi_short_threshold": 40,
        }),
        ("volatility_breakout", "1h", {
            "donchian_period": 50, "volume_ma_period": 20, "atr_period": 14,
        }),
        # Default params for reference
        ("momentum", "1h", {
            "ema_period": 20, "rsi_period": 14,
            "rsi_long_threshold": 55, "rsi_short_threshold": 45,
        }),
        ("volatility_breakout", "1h", {
            "donchian_period": 20, "volume_ma_period": 20, "atr_period": 14,
        }),
        # Losers (for completeness — showing why we're NOT taking them to Phase 3)
        ("mean_reversion", "1h", settings.get("strategies", {}).get("mean_reversion", {})),
        ("vwap_reversion", "5m", {
            "vwap_period": 30, "vwap_std_mult": 3.0,
            "rsi_period": 14, "rsi_divergence_lookback": 5,
        }),
        # Momentum and vol breakout on 15m for comparison
        ("momentum", "15m", {
            "ema_period": 30, "rsi_period": 14,
            "rsi_long_threshold": 50, "rsi_short_threshold": 40,
        }),
        ("volatility_breakout", "15m", {
            "donchian_period": 50, "volume_ma_period": 20, "atr_period": 14,
        }),
    ]

    results = []
    for strat_name, tf, params in combos:
        data = resample_ohlcv(oos_1m, tf)

        if strat_name == "momentum":
            from strategies.momentum import MomentumStrategy
            strat = MomentumStrategy(params=params)
        elif strat_name == "mean_reversion":
            from strategies.mean_reversion import MeanReversionStrategy
            strat = MeanReversionStrategy(params=params)
        elif strat_name == "volatility_breakout":
            from strategies.volatility_breakout import VolatilityBreakoutStrategy
            strat = VolatilityBreakoutStrategy(params=params)
        elif strat_name == "vwap_reversion":
            from strategies.vwap_reversion import VWAPReversionStrategy
            strat = VWAPReversionStrategy(params=params)
        else:
            continue

        config = BacktestConfig(initial_capital=10_000.0, taker_fee=0.0005, position_size_pct=1.0)
        result = BacktestEngine(config).run(strat, data)

        # Build a readable label
        param_summary = ", ".join(f"{k}={v}" for k, v in params.items())
        label = f"{strat_name} @ {tf}"

        results.append({
            "Strategy": label,
            "Params": param_summary[:50],
            "Return %": f"{result.total_return_pct:+.2f}",
            "Win Rate %": f"{result.win_rate:.1f}",
            "Sharpe": f"{result.sharpe_ratio:.2f}",
            "Max DD %": f"{result.max_drawdown_pct:.2f}",
            "PF": f"{result.profit_factor:.2f}",
            "Trades": result.num_trades,
        })

    # Sort by Sharpe
    results.sort(key=lambda x: float(x["Sharpe"]), reverse=True)

    print("\n" + "=" * 120)
    print("  FINAL STRATEGY COMPARISON — OUT-OF-SAMPLE ONLY (Sep 1 - Dec 31, 2024)")
    print("  Training period: Jan 1 - Aug 31, 2024 (parameters were optimized here)")
    print("=" * 120)
    print(tabulate(results, headers="keys", tablefmt="simple", stralign="right"))
    print("=" * 120)

    print("\n  RECOMMENDATION:")
    print("  ────────────────")
    print("  1. Volatility Breakout @ 1h (optimized) — best risk-adjusted return")
    print("  2. Momentum @ 1h (optimized) — solid backup, more trades for statistical confidence")
    print("  3. Drop mean_reversion and vwap_reversion — no edge on OOS data\n")


if __name__ == "__main__":
    main()
