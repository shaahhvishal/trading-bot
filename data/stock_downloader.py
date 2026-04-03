"""
Download historical OHLCV data for stocks via yfinance.

Supports any ticker available on Yahoo Finance. Downloads daily data
by default (yfinance intraday data is limited to 60 days for 1m).

Usage:
    from data.stock_downloader import download_stock
    df = download_stock("AAPL", start="2024-01-01", end="2025-01-01")
    df = download_stock("NVDA", interval="1h", start="2025-01-01")
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from loguru import logger

from data.store import save


def download_stock(
    ticker: str,
    interval: str = "1d",
    start: str = "2024-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Download OHLCV stock data and save to parquet.

    Args:
        ticker: Stock ticker (e.g. "AAPL", "NVDA").
        interval: Candle interval. "1d" for daily, "1h" for hourly,
                  "1m" for minute (limited to ~30 days by Yahoo).
        start: Start date as "YYYY-MM-DD".
        end: End date as "YYYY-MM-DD". Defaults to today.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
    """
    logger.info(f"Downloading {ticker} {interval} from {start} to {end or 'now'}")

    data = yf.download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )

    if data.empty:
        raise ValueError(f"No data returned for {ticker}. Check ticker and date range.")

    # yfinance returns MultiIndex columns when single ticker, flatten them
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    df = pd.DataFrame({
        "timestamp": data.index,
        "open": data["Open"].values,
        "high": data["High"].values,
        "low": data["Low"].values,
        "close": data["Close"].values,
        "volume": data["Volume"].values,
    })

    # Ensure timestamp is timezone-aware
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    df = df.dropna().reset_index(drop=True)

    logger.info(f"Downloaded {len(df):,} candles for {ticker}")

    # Save using ticker as symbol, interval as timeframe
    save(df, ticker, interval)

    return df


def download_mag7(
    interval: str = "1d",
    start: str = "2024-01-01",
    end: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Download all Magnificent 7 stocks.

    Args:
        interval: Candle interval ("1d", "1h", etc.)
        start: Start date.
        end: End date (defaults to today).

    Returns:
        Dict of ticker → DataFrame.
    """
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
    results = {}

    for ticker in tickers:
        try:
            df = download_stock(ticker, interval=interval, start=start, end=end)
            results[ticker] = df
            logger.info(
                f"  {ticker}: {len(df):,} candles | "
                f"${df['close'].iloc[-1]:,.2f} latest"
            )
        except Exception as e:
            logger.error(f"  {ticker}: FAILED — {e}")

    logger.info(f"\nDownloaded {len(results)}/7 Mag 7 stocks")
    return results
