"""
Data store: save and load OHLCV data as parquet files.

Parquet is used because it's fast, compact, and preserves dtypes (especially
datetime indexes) without any manual parsing. A 1-year, 1-minute dataset is
~500k rows — parquet handles that in <1 second.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger


DEFAULT_PARQUET_DIR = Path(__file__).resolve().parent / "parquet"


def _parquet_path(symbol: str, timeframe: str, directory: Path | None = None) -> Path:
    """Build a deterministic file path from symbol + timeframe."""
    directory = directory or DEFAULT_PARQUET_DIR
    safe_symbol = symbol.replace("/", "_")
    return directory / f"{safe_symbol}_{timeframe}.parquet"


def save(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    directory: Path | None = None,
) -> Path:
    """Save OHLCV DataFrame to parquet.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume].
        symbol: Trading pair, e.g. "BTC/USDT".
        timeframe: Candle interval, e.g. "1m".
        directory: Override the default storage directory.

    Returns:
        Path to the written file.
    """
    path = _parquet_path(symbol, timeframe, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info(f"Saved {len(df):,} rows → {path}")
    return path


def load(
    symbol: str,
    timeframe: str,
    directory: Path | None = None,
) -> pd.DataFrame:
    """Load OHLCV data from parquet.

    Args:
        symbol: Trading pair, e.g. "BTC/USDT".
        timeframe: Candle interval, e.g. "1m".
        directory: Override the default storage directory.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].

    Raises:
        FileNotFoundError: If no parquet file exists for this symbol/timeframe.
    """
    path = _parquet_path(symbol, timeframe, directory)
    if not path.exists():
        raise FileNotFoundError(f"No data file at {path}. Run the downloader first.")
    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df):,} rows ← {path}")
    return df
