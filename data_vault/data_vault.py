"""DataVault — Cached OHLCV data fetching with triple fallback.

Fetches historical daily OHLCV data from Interactive Brokers (primary),
Alpha Vantage (secondary), and yfinance (tertiary).  Data is cached as
Parquet files with a JSON manifest for TTL-based invalidation.

Output DataFrames are normalized to exactly
``['Open', 'High', 'Low', 'Close', 'Volume']`` with a ``DatetimeIndex``,
directly passable to ``Backtest(data, strategy)``.
"""

import datetime
import json
import logging
import os
import sys

try:
    import pandas as pd
    import pyarrow  # noqa: F401 — needed for Parquet I/O
    import yfinance as yf
    from dotenv import load_dotenv
    from ib_async import IB, Contract, util as ib_util
except ImportError as _exc:
    logging.getLogger("data_vault").error(
        "ERROR|VAULT|Missing dependencies. Please run: pip install -r requirements-backtest.txt"
    )
    sys.exit(1)

from data_vault.rate_limiter import YFRateLimiter

logger = logging.getLogger("data_vault")

# ── constants ─────────────────────────────────────────────────────────────────

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

_ENV_DEFAULTS: dict[str, str | None] = {
    "VAULT_DIR": "data_vault/",
    "VAULT_TTL_DAYS": "7",
    "VAULT_FETCH_YEARS": "5",
    "IB_HOST": "127.0.0.1",
    "IB_PORT": "7497",
    "IB_HISTORY_WAIT_SECONDS": "15",
    "ALPHA_VANTAGE_API_KEY": None,  # required, no default
    "VAULT_INTERACTIVE": "true",
    "YF_LIMIT_PER_MIN": "100",
    "YF_LIMIT_PER_HOUR": "2000",
    "YF_LIMIT_PER_DAY": "48000",
}

_AV_DAILY_LIMIT = 25

# Ticker symbols must be alphanumeric (with dots/dashes for classes like BRK.B, BF-B).
import re
_VALID_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


# ── main class ────────────────────────────────────────────────────────────────


class DataVault:
    """Cached OHLCV data fetcher with IB -> Alpha Vantage -> yfinance fallback.

    Args:
        interactive: If ``True`` (default), prompt the user when IB connection
            fails. If ``False``, silently fall through to Alpha Vantage.
            Overridden by the ``VAULT_INTERACTIVE`` env var when set to ``false``.
    """

    def __init__(self, interactive: bool | None = None) -> None:
        # Load .env file — hard stop if missing.
        if not load_dotenv():
            if not os.path.exists(".env"):
                logger.error(
                    "ERROR|VAULT|.env file not found. "
                    "Copy .env.example to .env and fill in values."
                )
                sys.exit(1)

        # Validate required env vars.
        missing = [
            key for key, default in _ENV_DEFAULTS.items()
            if default is None and not os.environ.get(key)
        ]
        if missing:
            logger.error(
                "ERROR|VAULT|Missing required env vars: %s. See .env.example.",
                ", ".join(missing),
            )
            sys.exit(1)

        # Read configuration.
        self._vault_dir: str = os.environ.get("VAULT_DIR", "data_vault/")
        self._ttl_days: int = int(os.environ.get("VAULT_TTL_DAYS", "7"))
        self._fetch_years: int = int(os.environ.get("VAULT_FETCH_YEARS", "5"))
        self._ib_host: str = os.environ.get("IB_HOST", "127.0.0.1")
        self._ib_port: int = int(os.environ.get("IB_PORT", "7497"))
        self._ib_wait: int = int(os.environ.get("IB_HISTORY_WAIT_SECONDS", "15"))
        self._av_key: str = os.environ.get("ALPHA_VANTAGE_API_KEY", "")

        # Interactive mode: constructor arg > env var > default True.
        if interactive is not None:
            self._interactive = interactive
        else:
            self._interactive = os.environ.get(
                "VAULT_INTERACTIVE", "true"
            ).lower() != "false"

        # Auto-create vault directory.
        if not os.path.exists(self._vault_dir):
            os.makedirs(self._vault_dir, exist_ok=True)
            logger.info("INFO|VAULT|Created vault directory: %s", self._vault_dir)

        # Load manifest.
        self._manifest_path: str = os.path.join(self._vault_dir, "manifest.json")
        self._manifest: dict = self._load_manifest()

        # Alpha Vantage daily call counter (reset daily via manifest key).
        self._av_calls_today: int = self._get_av_calls_today()

        # Rate limiter for yfinance.
        self._yf_limiter = YFRateLimiter(
            counter_file=os.path.join(self._vault_dir, "yf_rate_counters.json")
        )

        logger.info(
            "INFO|VAULT|DataVault initialised (vault_dir=%s, ttl=%dd, fetch=%dy)",
            self._vault_dir, self._ttl_days, self._fetch_years,
        )

    # ── public API ────────────────────────────────────────────────────────────

    def get_data(self, ticker: str, years: int | None = None) -> pd.DataFrame | None:
        """Fetch OHLCV data for a single ticker.

        Returns a normalized DataFrame ready for ``Backtest()``, or ``None``
        if all sources fail.

        Args:
            ticker: Stock/ETF ticker symbol (e.g. ``"AAPL"``).
            years: Number of years of history to return. Defaults to
                ``VAULT_FETCH_YEARS``.
        """
        ticker = ticker.upper().strip()
        if not _VALID_TICKER_RE.match(ticker):
            logger.warning("WARN|VAULT|%s: invalid ticker symbol, skipping", ticker)
            return None
        if years is None:
            years = self._fetch_years

        # Negative cache check (F1b).
        entry = self._manifest.get(ticker, {})
        if entry.get("status") == "failed":
            last_attempt = entry.get("last_failed_attempt", "")
            if last_attempt and not self._is_stale(last_attempt):
                logger.info(
                    "INFO|VAULT|%s: skipping (negative cache hit, last attempt %s)",
                    ticker, last_attempt,
                )
                return None

        # Cache check (R5.1).
        cached = self._check_cache(ticker, years)
        if cached is not None:
            return cached

        # Fetch from providers with fallback chain.
        df = self._fetch_from_providers(ticker)
        if df is None:
            # All sources failed — record negative hit (F1).
            logger.warning("WARN|VAULT|%s: all sources failed, caching negative hit", ticker)
            self._manifest[ticker] = {
                "status": "failed",
                "last_failed_attempt": datetime.date.today().isoformat(),
                "failure_reason": "all sources returned empty/error",
            }
            self._save_manifest()
            return None

        # Normalize (R4).
        df = self._normalize(df)
        if df is None or df.empty:
            return None

        # Validate no NaN in OHLC (F6).
        if df[["Open", "High", "Low", "Close"]].isna().any().any():
            logger.warning(
                "WARN|VAULT|%s: fetched data has NaN/missing columns, skipping", ticker,
            )
            return None

        # Save to cache (R5.5).
        self._save_to_cache(ticker, df)

        # Slice to requested years.
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        return df.loc[df.index >= cutoff]

    def get_batch(
        self, tickers: list[str], years: int | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data for multiple tickers sequentially.

        Args:
            tickers: List of ticker symbols.
            years: Number of years of history per ticker.

        Returns:
            Dict mapping ticker -> DataFrame. Tickers that fail all sources
            are omitted.
        """
        results: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            df = self.get_data(ticker, years=years)
            if df is not None:
                results[ticker] = df
        return results

    # ── cache logic ───────────────────────────────────────────────────────────

    def _check_cache(self, ticker: str, years: int) -> pd.DataFrame | None:
        """Return cached data if fresh and sufficient, else ``None``."""
        entry = self._manifest.get(ticker, {})
        fetch_date = entry.get("fetch_date")

        if not fetch_date or entry.get("status") == "failed":
            return None

        if self._is_stale(fetch_date):
            return None

        parquet_path = os.path.join(self._vault_dir, f"{ticker}_history.parquet")
        if not os.path.exists(parquet_path):
            return None

        # Read Parquet — handle corruption (F5).
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            logger.warning(
                "WARN|VAULT|%s: corrupt cache, deleting and re-fetching", ticker,
            )
            os.remove(parquet_path)
            return None

        # Check if cached range covers the requested years.
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        data_start = entry.get("data_start_date", "")
        if data_start:
            cached_start = pd.Timestamp(data_start)
            if cached_start > cutoff:
                # Cache is valid but insufficient — need to re-fetch.
                # Unless this is a short-history ticker (F10/R5.6).
                actual_years = (pd.Timestamp.now() - cached_start).days / 365.25
                if actual_years < years - 0.5:
                    # Short-history: accept what we have if cache is fresh.
                    logger.info(
                        "INFO|VAULT|%s: received %.1f years (requested %d), "
                        "treating as complete", ticker, actual_years, years,
                    )

        logger.info("INFO|VAULT|%s: cache hit", ticker)
        sliced = df.loc[df.index >= cutoff]
        return sliced if not sliced.empty else df

    def _save_to_cache(self, ticker: str, df: pd.DataFrame) -> None:
        """Save DataFrame to Parquet and update manifest (R5.5)."""
        parquet_path = os.path.join(self._vault_dir, f"{ticker}_history.parquet")
        df.to_parquet(parquet_path)

        self._manifest[ticker] = {
            "fetch_date": datetime.date.today().isoformat(),
            "data_start_date": str(df.index.min().date()),
            "data_end_date": str(df.index.max().date()),
            "source": self._manifest.get(ticker, {}).get("source", "unknown"),
            "rows": len(df),
        }
        self._save_manifest()
        logger.info("INFO|VAULT|%s: cached %d rows", ticker, len(df))

    def _is_stale(self, date_str: str) -> bool:
        """Return True if ``date_str`` is older than ``VAULT_TTL_DAYS``."""
        try:
            fetch_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            return True
        return (datetime.date.today() - fetch_date).days > self._ttl_days

    # ── manifest ──────────────────────────────────────────────────────────────

    def _load_manifest(self) -> dict:
        """Load manifest from JSON. Returns empty dict on corruption (F14)."""
        if not os.path.exists(self._manifest_path):
            return {}
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning("WARN|VAULT|manifest.json corrupt, rebuilding from cached files")
            return self._rebuild_manifest()

    def _save_manifest(self) -> None:
        """Persist manifest atomically (write .tmp then replace)."""
        tmp_path = self._manifest_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self._manifest, fh, indent=2)
        os.replace(tmp_path, self._manifest_path)

    def _rebuild_manifest(self) -> dict:
        """Rebuild manifest from existing Parquet files (F14)."""
        manifest: dict = {}
        for fname in os.listdir(self._vault_dir):
            if fname.endswith("_history.parquet"):
                ticker = fname.replace("_history.parquet", "")
                parquet_path = os.path.join(self._vault_dir, fname)
                try:
                    df = pd.read_parquet(parquet_path)
                    manifest[ticker] = {
                        "fetch_date": datetime.date.today().isoformat(),
                        "data_start_date": str(df.index.min().date()),
                        "data_end_date": str(df.index.max().date()),
                        "source": "rebuilt",
                        "rows": len(df),
                    }
                except Exception:
                    logger.warning(
                        "WARN|VAULT|%s: corrupt cache during rebuild, deleting", ticker,
                    )
                    os.remove(parquet_path)
        return manifest

    # ── Alpha Vantage daily counter ───────────────────────────────────────────

    def _get_av_calls_today(self) -> int:
        """Read today's Alpha Vantage call count from manifest metadata."""
        meta = self._manifest.get("_av_meta", {})
        if meta.get("date") == datetime.date.today().isoformat():
            return int(meta.get("calls", 0))
        return 0

    def _increment_av_counter(self) -> None:
        """Increment and persist the daily Alpha Vantage call counter."""
        self._av_calls_today += 1
        self._manifest["_av_meta"] = {
            "date": datetime.date.today().isoformat(),
            "calls": self._av_calls_today,
        }
        self._save_manifest()

    # ── data providers ────────────────────────────────────────────────────────

    def _fetch_from_providers(self, ticker: str) -> pd.DataFrame | None:
        """Try IB -> Alpha Vantage -> yfinance. Return DataFrame or None."""
        source = "unknown"

        # 1. IB (primary).
        df = self._fetch_ib(ticker)
        if df is not None and not df.empty:
            source = "ib"
            self._manifest.setdefault(ticker, {})["source"] = source
            return df

        # 2. Alpha Vantage (secondary).
        df = self._fetch_alpha_vantage(ticker)
        if df is not None and not df.empty:
            source = "alpha_vantage"
            self._manifest.setdefault(ticker, {})["source"] = source
            return df

        # 3. yfinance (tertiary).
        df = self._fetch_yfinance(ticker)
        if df is not None and not df.empty:
            source = "yfinance"
            self._manifest.setdefault(ticker, {})["source"] = source
            return df

        return None

    def _fetch_ib(self, ticker: str) -> pd.DataFrame | None:
        """Fetch daily bars from Interactive Brokers (R5.2)."""
        import time

        ib = IB()
        try:
            ib.connect(self._ib_host, self._ib_port, clientId=0, timeout=10)
        except Exception:
            if self._interactive:
                logger.warning(
                    "IB connection failed at %s:%s. "
                    "Continue with fallback providers? (y/n)",
                    self._ib_host, self._ib_port,
                )
                try:
                    answer = input(
                        f"IB connection failed at {self._ib_host}:{self._ib_port}. "
                        f"Continue with fallback providers? (y/n): "
                    ).strip().lower()
                except EOFError:
                    answer = "y"
                if answer != "y":
                    sys.exit(1)
            else:
                logger.warning(
                    "WARN|VAULT|IB unavailable, falling back to Alpha Vantage"
                )
            return None

        try:
            contract = Contract(
                symbol=ticker, secType="STK", exchange="SMART", currency="USD",
            )
            duration = f"{self._fetch_years} Y"
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="ADJUSTED_LAST",
                useRTH=True,
                formatDate=1,
            )
            if not bars:
                return None

            df = ib_util.df(bars)
            time.sleep(self._ib_wait)
            logger.info("INFO|VAULT|%s: fetched %d bars from IB", ticker, len(df))
            return df

        except Exception as exc:
            logger.warning("WARN|VAULT|%s: IB fetch error: %s", ticker, exc)
            return None
        finally:
            ib.disconnect()

    def _fetch_alpha_vantage(self, ticker: str) -> pd.DataFrame | None:
        """Fetch daily adjusted data from Alpha Vantage (R5.3)."""
        import urllib.parse
        import urllib.request
        import urllib.error

        if self._av_calls_today >= _AV_DAILY_LIMIT:
            logger.warning(
                "WARN|VAULT|Alpha Vantage daily limit reached, falling back to yfinance"
            )
            return None

        safe_ticker = urllib.parse.quote(ticker, safe="")
        url = (
            f"https://www.alphavantage.co/query?"
            f"function=TIME_SERIES_DAILY_ADJUSTED&symbol={safe_ticker}"
            f"&outputsize=full&apikey={self._av_key}"
        )

        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            logger.warning("WARN|VAULT|%s: Alpha Vantage error: %s", ticker, exc)
            return None

        ts = data.get("Time Series (Daily)")
        if not ts:
            error_msg = data.get("Note") or data.get("Error Message") or "empty response"
            logger.warning("WARN|VAULT|%s: Alpha Vantage returned: %s", ticker, error_msg)
            return None

        self._increment_av_counter()

        # Parse into DataFrame.
        records = []
        for date_str, values in ts.items():
            raw_close = float(values["4. close"])
            adj_close = float(values["5. adjusted close"])
            # Adjustment ratio to make OHLC consistent with adjusted close (R4.4).
            adj_ratio = adj_close / raw_close if raw_close != 0 else 1.0
            records.append({
                "Date": date_str,
                "Open": float(values["1. open"]) * adj_ratio,
                "High": float(values["2. high"]) * adj_ratio,
                "Low": float(values["3. low"]) * adj_ratio,
                "Close": adj_close,
                "Volume": int(values["6. volume"]),
            })

        df = pd.DataFrame(records)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        logger.info(
            "INFO|VAULT|%s: fetched %d rows from Alpha Vantage", ticker, len(df),
        )
        return df

    def _fetch_yfinance(self, ticker: str) -> pd.DataFrame | None:
        """Fetch daily adjusted data from yfinance (R5.4)."""
        self._yf_limiter.check_and_increment()

        period_map = {1: "1y", 2: "2y", 5: "5y", 10: "10y"}
        period = period_map.get(self._fetch_years, "max")

        try:
            tk = yf.Ticker(ticker)
            df = tk.history(period=period, auto_adjust=True)
        except Exception as exc:
            logger.warning("WARN|VAULT|%s: yfinance error: %s", ticker, exc)
            return None

        if df is None or df.empty:
            logger.warning("WARN|VAULT|%s: yfinance returned empty data", ticker)
            return None

        logger.info("INFO|VAULT|%s: fetched %d rows from yfinance", ticker, len(df))
        return df

    # ── normalization ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame | None:
        """Normalize DataFrame to backtesting.py format (R4).

        Forces columns to ``['Open', 'High', 'Low', 'Close', 'Volume']``,
        converts index to ``DatetimeIndex``, sorts ascending.
        """
        if df is None or df.empty:
            return None

        # Title-case columns for matching.
        df.columns = [c.title() if isinstance(c, str) else c for c in df.columns]

        # Keep only OHLCV columns.
        available = [c for c in _OHLCV_COLUMNS if c in df.columns]
        if len(available) < 4:
            # Must have at least OHLC.
            return None
        df = df[available].copy()

        # Add Volume if missing.
        if "Volume" not in df.columns:
            df["Volume"] = float("nan")

        # Ensure DatetimeIndex.
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = None

        # Sort ascending.
        df = df.sort_index()

        return df
