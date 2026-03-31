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
import time

try:
    import pandas as pd
    import pyarrow  # noqa: F401 — needed for Parquet I/O
    import yfinance as yf
    from dotenv import load_dotenv
    from ib_async import IB, Contract, util as ib_util
except ImportError as _exc:
    logging.getLogger("data_vault").error(
        "Missing dependencies. Please run: pip install -r requirements-backtest.txt"
    )
    sys.exit(1)

from .logging_config import setup_logging
from .rate_limiter import YFRateLimiter

logger = logging.getLogger("data_vault")

# ── constants ─────────────────────────────────────────────────────────────────

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

_ENV_DEFAULTS: dict[str, str | None] = {
    "VAULT_DIR": "data_vault/",
    "VAULT_TTL_DAYS": "7",
    "VAULT_FETCH_YEARS": "5",
    "IB_HOST": "127.0.0.1",
    "IB_PORT": "4002",
    "IB_HISTORY_WAIT_SECONDS": "15",
    "ALPHA_VANTAGE_API_KEY": None,  # required, no default
    "IB_PACING_ENABLED": "true",
    "VAULT_INTERACTIVE": "true",
    "YF_LIMIT_PER_MIN": "100",
    "YF_LIMIT_PER_HOUR": "2000",
    "YF_LIMIT_PER_DAY": "48000",
}

_AV_DAILY_LIMIT = 25

# Ticker symbols must be alphanumeric (with dots/dashes for classes like BRK.B, BF-B).
import re
_VALID_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")

# Preferred share suffixes: -P, -PA through -PZ (e.g. AGM-PD, ALL-PB).
# Single-letter suffixes like -A, -B are common share classes (e.g. BRK-B) and kept.
_PREFERRED_TICKER_RE = re.compile(r"-P[A-Z]?$")


def is_preferred_share(ticker: str) -> bool:
    """Return True if ``ticker`` looks like a preferred share class."""
    return bool(_PREFERRED_TICKER_RE.search(ticker.upper()))


# ── throttle exception ──────────────────────────────────────────────────────


class _SourceThrottled(Exception):
    """Raised when a data source is temporarily rate-limited (not exhausted).

    Carries the source name and the number of seconds until the source
    is expected to be available again, so the caller can choose to wait
    or try another source.
    """

    def __init__(self, source: str, wait_seconds: float) -> None:
        self.source = source
        self.wait_seconds = wait_seconds
        super().__init__(
            f"{source} throttled, available in {wait_seconds:.1f}s"
        )


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
                print(".env file not found. "
                      "Copy .env.example to .env and fill in values.")
                sys.exit(1)

        # Configure logging now that env vars are loaded.
        setup_logging()

        # Validate required env vars.
        missing = [
            key for key, default in _ENV_DEFAULTS.items()
            if default is None and not os.environ.get(key)
        ]
        if missing:
            logger.error(
                "Missing required env vars: %s. See .env.example.",
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
        self._ib_pacing_enabled: bool = os.environ.get(
            "IB_PACING_ENABLED", "true"
        ).lower() != "false"

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
            logger.info("Created vault directory: %s", self._vault_dir)

        # Load manifest.
        self._manifest_path: str = os.path.join(self._vault_dir, "manifest.json")
        self._manifest: dict = self._load_manifest()

        # Alpha Vantage daily call counter (reset daily via manifest key).
        self._av_calls_today: int = self._get_av_calls_today()

        # Rate limiter for yfinance.
        self._yf_limiter = YFRateLimiter(
            counter_file=os.path.join(self._vault_dir, "yf_rate_counters.json")
        )

        # Round-robin rotation state (R14/R15/R16).
        self._available_sources: list[str] = ["ib", "alpha_vantage", "yfinance"]
        self._rotation_index: int = 0
        self._ib_unavailable: bool = False
        self._yf_exhausted: bool = False
        self._last_ib_request_time: float | None = None

        logger.info(
            "DataVault initialised (vault_dir=%s, ttl=%dd, fetch=%dy)",
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
            logger.warning("%s: invalid ticker symbol, skipping", ticker)
            return None
        if years is None:
            years = self._fetch_years

        # Negative cache check (F1b).
        entry = self._manifest.get(ticker, {})
        if entry.get("status") == "failed":
            last_attempt = entry.get("last_failed_attempt", "")
            if last_attempt and not self._is_stale(last_attempt):
                logger.info(
                    "%s: skipping (negative cache hit, last attempt %s)",
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
            logger.warning("%s: all sources failed, caching negative hit", ticker)
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
                "%s: fetched data has NaN/missing columns, skipping", ticker,
            )
            return None

        # Save to cache (R5.5) — preserves source timezone.
        self._save_to_cache(ticker, df)

        # Slice to requested years, then strip tz for backtesting.py compatibility.
        cutoff = self._cutoff_for_index(df.index, years)
        return self._strip_tz(df.loc[df.index >= cutoff])

    def prune_preferred_shares(self) -> list[str]:
        """Remove cached data for preferred share tickers.

        Deletes Parquet files and manifest entries for tickers matching
        the preferred share pattern (e.g. ``AGM-PD``, ``ALL-PB``).

        Returns:
            List of pruned ticker symbols.
        """
        pruned: list[str] = []

        # Scan manifest for preferred tickers.
        preferred_in_manifest = [
            t for t in list(self._manifest)
            if not t.startswith("_") and is_preferred_share(t)
        ]
        for ticker in preferred_in_manifest:
            del self._manifest[ticker]
            pruned.append(ticker)

        # Scan vault directory for orphaned Parquet files.
        for fname in os.listdir(self._vault_dir):
            if fname.endswith("_history.parquet"):
                ticker = fname.replace("_history.parquet", "")
                if is_preferred_share(ticker) and ticker not in pruned:
                    pruned.append(ticker)
                if is_preferred_share(ticker):
                    parquet_path = os.path.join(self._vault_dir, fname)
                    os.remove(parquet_path)

        if pruned:
            self._save_manifest()
            logger.info(
                "Pruned %d preferred share tickers from cache: %s",
                len(pruned), ", ".join(sorted(pruned)),
            )
        else:
            logger.info("No preferred share tickers found in cache")

        return sorted(pruned)

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

    # ── timezone helpers ────────────────────────────────────────────────────

    @staticmethod
    def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
        """Strip timezone from DatetimeIndex for backtesting.py compatibility."""
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        return df

    @staticmethod
    def _cutoff_for_index(index: pd.DatetimeIndex, years: int) -> pd.Timestamp:
        """Build a cutoff timestamp that is tz-compatible with ``index``."""
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years)
        if index.tz is not None:
            cutoff = cutoff.tz_localize(index.tz)
        return cutoff

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
                "%s: corrupt cache, deleting and re-fetching", ticker,
            )
            os.remove(parquet_path)
            return None

        # Build tz-compatible cutoff to match cached data's timezone.
        cutoff = self._cutoff_for_index(df.index, years)
        data_start = entry.get("data_start_date", "")
        if data_start:
            cached_start = pd.Timestamp(data_start)
            # Match tz-awareness of cutoff (manifest dates are tz-naive strings).
            if cutoff.tz is not None and cached_start.tz is None:
                cached_start = cached_start.tz_localize(cutoff.tz)
            if cached_start > cutoff:
                # Cache is valid but insufficient — need to re-fetch.
                # Unless this is a short-history ticker (F10/R5.6).
                now = pd.Timestamp.now(tz=cached_start.tz) if cached_start.tz else pd.Timestamp.now()
                actual_years = (now - cached_start).days / 365.25
                if actual_years < years - 0.5:
                    # Short-history: accept what we have if cache is fresh.
                    logger.info(
                        "%s: received %.1f years (requested %d), "
                        "treating as complete", ticker, actual_years, years,
                    )

        logger.info("%s: cache hit", ticker)
        sliced = df.loc[df.index >= cutoff]
        result = sliced if not sliced.empty else df
        return self._strip_tz(result)

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
        logger.info("%s: cached %d rows", ticker, len(df))

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
            logger.warning("manifest.json corrupt, rebuilding from cached files")
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
                        "%s: corrupt cache during rebuild, deleting", ticker,
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

    def _dispatch_fetch(self, source: str, ticker: str) -> pd.DataFrame | None:
        """Resolve and call the fetch method for a given source name."""
        if source == "ib":
            return self._fetch_ib(ticker)
        if source == "alpha_vantage":
            return self._fetch_alpha_vantage(ticker)
        if source == "yfinance":
            return self._try_fetch_yfinance(ticker)
        return None

    def _fetch_from_providers(self, ticker: str) -> pd.DataFrame | None:
        """Try sources in round-robin order (R14). Return DataFrame or None."""
        if not self._available_sources:
            logger.error("No data sources available (F19)")
            return None

        # Pre-check: remove AV if daily limit already reached (F15).
        if (self._av_calls_today >= _AV_DAILY_LIMIT
                and "alpha_vantage" in self._available_sources):
            self._available_sources.remove("alpha_vantage")
            logger.warning(
                "Alpha Vantage daily limit reached (%d/%d), removed from rotation",
                self._av_calls_today, _AV_DAILY_LIMIT,
            )
            if not self._available_sources:
                logger.error("No data sources available (F19)")
                return None

        # Determine rotation start for this call.
        start_idx = self._rotation_index % len(self._available_sources)
        self._rotation_index += 1

        # Build ordered list: start at rotation index, wrap around.
        n = len(self._available_sources)
        ordered = [self._available_sources[(start_idx + i) % n] for i in range(n)]

        throttled: dict[str, float] = {}

        for source in ordered:
            try:
                df = self._dispatch_fetch(source, ticker)
            except _SourceThrottled as exc:
                throttled[exc.source] = exc.wait_seconds
                logger.info(
                    "%s: %s throttled (%.1fs), trying next source",
                    ticker, exc.source, exc.wait_seconds,
                )
                continue

            if df is not None and not df.empty:
                self._manifest.setdefault(ticker, {})["source"] = source
                return df

            # Post-fetch: check if AV just hit its limit (F15).
            if (source == "alpha_vantage"
                    and self._av_calls_today >= _AV_DAILY_LIMIT
                    and "alpha_vantage" in self._available_sources):
                self._available_sources.remove("alpha_vantage")
                logger.warning(
                    "Alpha Vantage daily limit reached (%d/%d), "
                    "removed from rotation",
                    self._av_calls_today, _AV_DAILY_LIMIT,
                )

        # Smart retry: if any source was throttled, wait for the shortest
        # cooldown and retry that one source (R20/F24).
        if throttled:
            best_source = min(throttled, key=lambda s: throttled[s])
            wait = throttled[best_source]
            logger.info(
                "%s: all sources busy/failed, waiting %.1fs for %s",
                ticker, wait, best_source,
            )
            time.sleep(wait)
            try:
                df = self._dispatch_fetch(best_source, ticker)
            except _SourceThrottled:
                return None
            if df is not None and not df.empty:
                self._manifest.setdefault(ticker, {})["source"] = best_source
                return df

        return None

    def _try_fetch_yfinance(self, ticker: str) -> pd.DataFrame | None:
        """Wrapper around _fetch_yfinance that handles rate-limiter signals.

        - ``RateLimitPaused`` (minute limit): converted to ``_SourceThrottled``
          so the caller can try another source and come back later (F23/R19).
        - ``SystemExit`` (hour/day limit): catches and removes yfinance from
          rotation permanently (F16).
        """
        from .rate_limiter import RateLimitPaused
        try:
            return self._fetch_yfinance(ticker)
        except RateLimitPaused as exc:
            raise _SourceThrottled("yfinance", exc.wait_seconds)
        except SystemExit:
            self._yf_exhausted = True
            if "yfinance" in self._available_sources:
                self._available_sources.remove("yfinance")
            logger.warning("yfinance daily limit reached, removed from rotation")
            return None

    def _fetch_ib(self, ticker: str) -> pd.DataFrame | None:
        """Fetch daily bars from Interactive Brokers (R5.2/R18).

        Raises:
            _SourceThrottled: When proactive pacing is enabled and not enough
                time has elapsed since the last IB request, or when a pacing
                violation error is detected in reactive mode.
        """
        # Proactive pacing check (R18 — enabled mode).
        if self._ib_pacing_enabled and self._last_ib_request_time is not None:
            elapsed = time.monotonic() - self._last_ib_request_time
            remaining = self._ib_wait - elapsed
            if remaining > 0:
                raise _SourceThrottled("ib", remaining)

        ib = IB()
        try:
            ib.connect(self._ib_host, self._ib_port, clientId=0, timeout=10)
        except Exception:
            # Mark IB as unavailable and remove from rotation (F18).
            if not self._ib_unavailable:
                self._ib_unavailable = True
                if "ib" in self._available_sources:
                    self._available_sources.remove("ib")
                if self._interactive:
                    logger.warning(
                        "IB connection failed at %s:%s. "
                        "Removed from rotation, continuing with other sources.",
                        self._ib_host, self._ib_port,
                    )
                    try:
                        answer = input(
                            f"IB connection failed at {self._ib_host}:"
                            f"{self._ib_port}. "
                            f"Continue with fallback providers? (y/n): "
                        ).strip().lower()
                    except EOFError:
                        answer = "y"
                    if answer != "y":
                        sys.exit(1)
                else:
                    logger.warning(
                        "IB unavailable, removed from rotation"
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
            # Record request time for proactive pacing (no inline sleep).
            self._last_ib_request_time = time.monotonic()
            logger.info("%s: fetched %d bars from IB", ticker, len(df))
            return df

        except Exception as exc:
            err_msg = str(exc).lower()
            # Reactive pacing: detect IB pacing violation (F21/R18).
            if "pacing" in err_msg:
                logger.warning(
                    "%s: IB pacing violation, throttled for %ds",
                    ticker, self._ib_wait,
                )
                self._last_ib_request_time = time.monotonic()
                raise _SourceThrottled("ib", float(self._ib_wait))
            logger.warning("%s: IB fetch error: %s", ticker, exc)
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
                "Alpha Vantage daily limit reached, falling back to yfinance"
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
            logger.warning("%s: Alpha Vantage error: %s", ticker, exc)
            return None

        ts = data.get("Time Series (Daily)")
        if not ts:
            error_msg = data.get("Note") or data.get("Error Message") or "empty response"
            logger.warning("%s: Alpha Vantage returned: %s", ticker, error_msg)
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
            "%s: fetched %d rows from Alpha Vantage", ticker, len(df),
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
            logger.warning("%s: yfinance error: %s", ticker, exc)
            return None

        if df is None or df.empty:
            logger.warning("%s: yfinance returned empty data", ticker)
            return None

        logger.info("%s: fetched %d rows from yfinance", ticker, len(df))
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

        # Ensure DatetimeIndex (preserve source timezone for cache fidelity).
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index.name = None

        # Sort ascending.
        df = df.sort_index()

        return df
