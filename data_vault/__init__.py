"""DataVault — Cached OHLCV data fetching with triple fallback.

Provides a single ``DataVault`` class that fetches, caches, and normalizes
historical OHLCV data from Interactive Brokers, Alpha Vantage, and yfinance.
Output DataFrames are directly passable to ``Backtest(data, strategy)``.

Usage::

    from data_vault import DataVault

    vault = DataVault()
    df = vault.get_data("AAPL", years=5)
"""

from .data_vault import DataVault

__all__ = ["DataVault"]
