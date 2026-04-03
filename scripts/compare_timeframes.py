"""
Compare strategies across multiple timeframes.

Usage:
    python scripts/compare_timeframes.py
    python scripts/compare_timeframes.py --symbol ETH/USDT --start 2024-01-01 --end 2025-01-01
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click
import yaml
from loguru import logger
from tabulate import tabulate

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.metrics import BacktestResult
from data.resample import resample_ohlcv
from data.store import load


def _load_settings() -> dict:
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_strategy(name: str, settings: dict):
    strategy_params = settings.get("strategies", {}).get(name, {})
    if name == "momentum":
        from strategies.momentum import MomentumStrategy
        return MomentumStrategy(params=strategy_params)
    elif name == "mean_reversion":
        from strategies.mean_reversion import MeanReversionStrategy
        return MeanReversionStrategy(params=strategy_params)
    elif name == "volatility_breakout":
        from strategies.volatility_breakout import VolatilityBreakoutStrategy
        return VolatilityBreakoutStrategy(params=strategy_params)
    elif name == "vwap_reversion":
        from strategies.vwap_reversion import VWAPReversionStrategy
        return VWAPReversionStrategy(params=strategy_params)
    else:
        raise ValueError(f"Unknown strategy: {name}")


@click.command()
@click.option("--symbol", default="BTC/USDT", help="Trading pair")
@click.option("--start", default="2024-01-01", help="Start date")
@click.option("--end", default="2025-01-01", help="End date")
@click.option("--capital", default=10_000.0, help="Initial capital")
@click.option("--fee", default=0.0005, help="Taker fee rate")
def main(symbol: str, start: str, end: str, capital: float, fee: float) -> None:
    """Run momentum and mean_reversion across 1m, 5m, 15m, 1h timeframes."""
    settings = _load_settings()

    # Load 1m base data
    logger.info(f"Loading {symbol} 1m data...")
    data_1m = load(symbol, "1m")
    data_1m = data_1m[
        (data_1m["timestamp"] >= start) & (data_1m["timestamp"] < end)
    ].reset_index(drop=True)
    logger.info(f"Base data: {len(data_1m):,} candles")

    strategies = ["momentum", "mean_reversion", "volatility_breakout", "vwap_reversion"]
    timeframes = ["1m", "5m", "15m", "1h"]
    results: list[dict] = []

    for tf in timeframes:
        data = resample_ohlcv(data_1m, tf)

        for strat_name in strategies:
            strat = _get_strategy(strat_name, settings)
            config = BacktestConfig(
                initial_capital=capital,
                taker_fee=fee,
                position_size_pct=settings.get("backtest", {}).get("position_size", 1.0),
            )
            engine = BacktestEngine(config)
            result = engine.run(strat, data)

            results.append({
                "Strategy": strat_name,
                "Timeframe": tf,
                "Candles": f"{len(data):,}",
                "Trades": result.num_trades,
                "Return %": f"{result.total_return_pct:+.2f}",
                "Win Rate %": f"{result.win_rate:.1f}",
                "Sharpe": f"{result.sharpe_ratio:.2f}",
                "Max DD %": f"{result.max_drawdown_pct:.2f}",
                "Profit Factor": f"{result.profit_factor:.2f}",
            })

    # Print comparison table
    print("\n" + "=" * 100)
    print(f"  TIMEFRAME COMPARISON — {symbol} — {start} to {end}")
    print("=" * 100)
    print(tabulate(results, headers="keys", tablefmt="simple", stralign="right"))
    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
