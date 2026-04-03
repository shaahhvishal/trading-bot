"""
CLI entry point for live/paper trading.

Usage:
    python scripts/run_live.py
    python scripts/run_live.py --strategy momentum --symbols BTC/USDT
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import click
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


@click.command()
@click.option("--strategy", "-s", default="volatility_breakout", help="Strategy name")
@click.option("--symbols", default="BTC/USDT,ETH/USDT", help="Comma-separated symbols")
@click.option("--capital", default=10_000.0, help="Initial capital")
def main(strategy: str, symbols: str, capital: float) -> None:
    """Start the paper trading bot."""
    from live.bot import TradingBot
    from live.executor import PaperExecutor
    from live.risk_manager import RiskLimits, RiskManager
    from alerts.telegram import TelegramAlerter

    symbol_list = [s.strip() for s in symbols.split(",")]

    # Load strategy
    strategy_params = _load_strategy_params(strategy)
    strategies = {}
    for sym in symbol_list:
        strategies[sym] = _create_strategy(strategy, strategy_params)

    executor = PaperExecutor(initial_capital=capital)
    risk_manager = RiskManager(
        limits=RiskLimits(max_open_positions=2),
        initial_capital=capital,
    )
    alerter = TelegramAlerter.from_env()

    bot = TradingBot(
        symbols=symbol_list,
        strategies=strategies,
        executor=executor,
        risk_manager=risk_manager,
        alerter=alerter,
    )

    logger.info(f"Starting paper trading: {strategy} on {symbol_list}")
    asyncio.run(bot.start())


def _load_strategy_params(name: str) -> dict:
    import yaml
    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with open(config_path) as f:
        settings = yaml.safe_load(f)
    return settings.get("strategies", {}).get(name, {})


def _create_strategy(name: str, params: dict):
    if name == "volatility_breakout":
        from strategies.volatility_breakout import VolatilityBreakoutStrategy
        return VolatilityBreakoutStrategy(params=params)
    elif name == "momentum":
        from strategies.momentum import MomentumStrategy
        return MomentumStrategy(params=params)
    elif name == "mean_reversion":
        from strategies.mean_reversion import MeanReversionStrategy
        return MeanReversionStrategy(params=params)
    elif name == "ema_swing":
        from strategies.ema_swing import EMASwingStrategy
        return EMASwingStrategy(params=params)
    elif name == "confluence":
        from strategies.confluence import ConfluenceStrategy
        return ConfluenceStrategy(params=params)
    else:
        raise ValueError(f"Unknown strategy: {name}")


if __name__ == "__main__":
    main()
