"""Tests for data/store.py — parquet save/load round-trip."""

from __future__ import annotations

import pandas as pd
import pytest

from data.store import load, save


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Minimal OHLCV DataFrame for testing."""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="min", tz="UTC"),
            "open": [100.0, 101.0, 102.0, 101.5, 103.0],
            "high": [101.0, 102.0, 103.0, 102.5, 104.0],
            "low": [99.5, 100.5, 101.5, 101.0, 102.5],
            "close": [100.5, 101.5, 102.5, 102.0, 103.5],
            "volume": [1000, 1100, 1200, 900, 1300],
        }
    )


def test_save_and_load_roundtrip(tmp_path, sample_df):
    """Data survives a save → load cycle unchanged."""
    save(sample_df, "BTC/USDT", "1m", directory=tmp_path)
    loaded = load("BTC/USDT", "1m", directory=tmp_path)

    pd.testing.assert_frame_equal(loaded, sample_df)


def test_load_missing_file_raises(tmp_path):
    """Loading a non-existent symbol raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load("DOGE/USDT", "1m", directory=tmp_path)


def test_save_creates_directory(tmp_path, sample_df):
    """Save creates nested directories if they don't exist."""
    nested = tmp_path / "nested" / "deep"
    save(sample_df, "ETH/USDT", "5m", directory=nested)
    loaded = load("ETH/USDT", "5m", directory=nested)
    assert len(loaded) == 5
