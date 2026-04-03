"""
Download historical OHLCV candles from Binance via ccxt.

Binance's API returns max 1000 candles per request, so we paginate by
advancing the `since` timestamp after each batch. For 1-minute candles
over 1 year (~525,600 rows), this takes ~530 requests — typically under
5 minutes with polite rate limiting.

If binance.com is geo-blocked (US users), we automatically fall back to
binanceus. You can also pass any ccxt exchange name explicitly.
"""

from __future__ import annotations

import time
from datetime import datetime

import ccxt
import pandas as pd
from loguru import logger

from data.store import save

MAX_RETRIES = 3


def _create_exchange(exchange_id: str = "binanceus") -> ccxt.Exchange:
    """Create a ccxt exchange instance with rate limiting.

    Args:
        exchange_id: ccxt exchange identifier. Defaults to "binanceus" since
                     binance.com is geo-blocked in the US.

    Returns:
        Configured exchange instance.
    """
    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        raise ValueError(f"Unknown exchange: {exchange_id}. Check ccxt docs.")
    return exchange_class({"enableRateLimit": True})


def download_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    start: str = "2024-01-01",
    end: str = "2025-01-01",
    batch_size: int = 1000,
    exchange_id: str = "binanceus",
) -> pd.DataFrame:
    """Download OHLCV candles and save to parquet.

    Args:
        symbol: Trading pair (e.g. "BTC/USDT").
        timeframe: Candle interval (e.g. "1m", "5m", "1h").
        start: Start date as "YYYY-MM-DD".
        end: End date as "YYYY-MM-DD".
        batch_size: Candles per API request (max 1000 for Binance).
        exchange_id: ccxt exchange to use. "binanceus" for US, "binance" outside US.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
    """
    exchange = _create_exchange(exchange_id)

    since_ms = int(datetime.fromisoformat(start).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end).timestamp() * 1000)

    all_candles: list[list] = []
    consecutive_errors = 0

    logger.info(
        f"Downloading {symbol} {timeframe} from {start} to {end} "
        f"via {exchange_id}"
    )

    while since_ms < end_ms:
        try:
            candles = exchange.fetch_ohlcv(
                symbol, timeframe, since=since_ms, limit=batch_size
            )
            consecutive_errors = 0  # Reset on success
        except ccxt.BaseError as e:
            consecutive_errors += 1
            if consecutive_errors >= MAX_RETRIES:
                logger.error(
                    f"Failed after {MAX_RETRIES} consecutive errors. Last: {e}"
                )
                raise
            logger.warning(f"ccxt error (attempt {consecutive_errors}): {e}")
            time.sleep(1)
            continue

        if not candles:
            break

        all_candles.extend(candles)

        # Advance past the last candle we received
        since_ms = candles[-1][0] + 1

        if len(all_candles) % 50_000 < batch_size:
            logger.info(f"  ... {len(all_candles):,} candles downloaded so far")

    df = pd.DataFrame(
        all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    # Convert ms timestamp to datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    # Drop any candles past our end date
    df = df[df["timestamp"] < pd.Timestamp(end, tz="UTC")]

    # Remove duplicates (overlapping batches at boundaries)
    df = df.drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    logger.info(f"Download complete: {len(df):,} candles")

    # Save to parquet
    save(df, symbol, timeframe)

    return df
