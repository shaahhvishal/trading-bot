"""
CLI entry point for backtesting.

Usage:
    python scripts/run_backtest.py --strategy momentum --symbol BTC/USDT --start 2024-01-01 --end 2025-01-01
    python scripts/run_backtest.py --strategy momentum --symbol ETH/USDT --start 2024-06-01 --end 2025-01-01

Add --download to fetch fresh data before backtesting.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path so imports work when running as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click
import yaml
from loguru import logger

from backtest.engine import BacktestConfig, BacktestEngine
from backtest.report import print_report
from data.downloader import download_ohlcv
from data.store import load


def _load_settings() -> dict:
    """Load settings.yaml config."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_strategy(name: str, settings: dict):
    """Import and instantiate a strategy by name.

    Args:
        name: Strategy name (e.g. "momentum").
        settings: Full settings dict from settings.yaml.

    Returns:
        Strategy instance.

    Raises:
        ValueError: If strategy name is not recognized.
    """
    strategy_params = settings.get("strategies", {}).get(name, {})

    if name == "momentum":
        from strategies.momentum import MomentumStrategy
        return MomentumStrategy(params=strategy_params)
    elif name == "mean_reversion":
        from strategies.mean_reversion import MeanReversionStrategy
        return MeanReversionStrategy(params=strategy_params)
    elif name == "orb":
        from strategies.orb import ORBStrategy
        return ORBStrategy(params=strategy_params)
    elif name == "volatility_breakout":
        from strategies.volatility_breakout import VolatilityBreakoutStrategy
        return VolatilityBreakoutStrategy(params=strategy_params)
    elif name == "vwap_reversion":
        from strategies.vwap_reversion import VWAPReversionStrategy
        return VWAPReversionStrategy(params=strategy_params)
    elif name == "vwap_pullback":
        from strategies.vwap_pullback import VWAPPullbackStrategy
        return VWAPPullbackStrategy(params=strategy_params)
    elif name == "latency_arb":
        from strategies.latency_arb import LatencyArbStrategy
        return LatencyArbStrategy(params=strategy_params)
    elif name == "ema_swing":
        from strategies.ema_swing import EMASwingStrategy
        return EMASwingStrategy(params=strategy_params)
    elif name == "confluence":
        from strategies.confluence import ConfluenceStrategy
        return ConfluenceStrategy(params=strategy_params)
    else:
        raise ValueError(
            f"Unknown strategy: '{name}'. "
            "Available: momentum, mean_reversion, volatility_breakout, vwap_reversion, "
            "vwap_pullback, latency_arb, ema_swing, confluence"
        )


@click.command()
@click.option("--strategy", "-s", default="momentum", help="Strategy name")
@click.option("--symbol", default="BTC/USDT", help="Trading pair")
@click.option("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
@click.option("--end", default="2025-01-01", help="End date (YYYY-MM-DD)")
@click.option("--capital", default=10000.0, help="Initial capital in USD")
@click.option("--fee", default=0.0005, help="Taker fee rate (0.0005 = 0.05%)")
@click.option("--download", is_flag=True, help="Download fresh data before backtest")
@click.option("--exchange", default="binanceus", help="ccxt exchange id (binanceus for US)")
def main(
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    capital: float,
    fee: float,
    download: bool,
    exchange: str,
) -> None:
    """Run a backtest for a given strategy and symbol."""
    settings = _load_settings()

    logger.info(f"Strategy: {strategy} | Symbol: {symbol} | {start} → {end}")

    # Load or download data
    if download:
        logger.info("Downloading fresh data...")
        data = download_ohlcv(symbol=symbol, timeframe="1m", start=start, end=end, exchange_id=exchange)
    else:
        try:
            data = load(symbol, "1m")
            # Filter to requested date range
            data = data[
                (data["timestamp"] >= start) & (data["timestamp"] < end)
            ].reset_index(drop=True)
        except FileNotFoundError:
            logger.warning("No local data found. Downloading...")
            data = download_ohlcv(symbol=symbol, timeframe="1m", start=start, end=end, exchange_id=exchange)

    logger.info(f"Data: {len(data):,} candles from {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")

    # Set up strategy
    strat = _get_strategy(strategy, settings)

    # Set up engine
    config = BacktestConfig(
        initial_capital=capital,
        taker_fee=fee,
        position_size_pct=settings.get("backtest", {}).get("position_size", 1.0),
    )
    engine = BacktestEngine(config)

    # Run backtest
    result = engine.run(strat, data)

    # Print results
    print_report(result, show_trades=15)


if __name__ == "__main__":
    main()
