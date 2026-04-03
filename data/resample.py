"""
Resample 1-minute OHLCV data to higher timeframes.

Instead of downloading 5m/15m/1h data separately, we resample from 1m candles.
This guarantees consistency — every timeframe uses the exact same underlying data.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger


# Map human-readable timeframes to pandas offset aliases
TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample 1-minute OHLCV data to a higher timeframe.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume].
            Must be 1-minute data sorted by timestamp.
        timeframe: Target timeframe (e.g. "5m", "15m", "1h").

    Returns:
        Resampled DataFrame with the same columns.
    """
    if timeframe == "1m":
        return df.copy()

    freq = TIMEFRAME_MAP.get(timeframe)
    if freq is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Use: {list(TIMEFRAME_MAP)}")

    # Set timestamp as index for resampling
    resampled = df.set_index("timestamp").resample(freq).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna().reset_index()

    logger.info(f"Resampled {len(df):,} × 1m → {len(resampled):,} × {timeframe}")
    return resampled
