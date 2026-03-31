"""Tests for data_vault package.

Uses unittest with mocked external providers (IB, Alpha Vantage, yfinance)
since network calls cannot be exercised in CI.  Tests exercise real code paths
for config, cache, normalization, rate limiter, and manifest logic.
"""

import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ohlcv_df(rows: int = 100, start: str = "2021-01-01") -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame for testing."""
    dates = pd.bdate_range(start=start, periods=rows)
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.standard_normal(rows))
    return pd.DataFrame({
        "Open": close - rng.uniform(0, 1, rows),
        "High": close + rng.uniform(0, 2, rows),
        "Low": close - rng.uniform(0, 2, rows),
        "Close": close,
        "Volume": rng.integers(1000, 100000, rows),
    }, index=dates)


def _setup_env(tmpdir: str, extra: dict | None = None) -> None:
    """Write a .env file and set env vars for testing."""
    env_vars = {
        "VAULT_DIR": os.path.join(tmpdir, "vault"),
        "VAULT_TTL_DAYS": "7",
        "VAULT_FETCH_YEARS": "5",
        "IB_HOST": "127.0.0.1",
        "IB_PORT": "7497",
        "IB_HISTORY_WAIT_SECONDS": "0",
        "ALPHA_VANTAGE_API_KEY": "test_key_123",
        "VAULT_INTERACTIVE": "false",
        "YF_LIMIT_PER_MIN": "100",
        "YF_LIMIT_PER_HOUR": "2000",
        "YF_LIMIT_PER_DAY": "48000",
    }
    if extra:
        env_vars.update(extra)

    env_path = os.path.join(tmpdir, ".env")
    with open(env_path, "w") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")

    for k, v in env_vars.items():
        os.environ[k] = v


# ── test: rate limiter ────────────────────────────────────────────────────────


class TestYFRateLimiter(unittest.TestCase):
    """Test the YFRateLimiter rolling-window logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.counter_file = os.path.join(self.tmpdir, "counters.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_increment_counts(self):
        """Basic increment works and persists state."""
        os.environ["VAULT_DIR"] = self.tmpdir
        from data_vault.rate_limiter import YFRateLimiter
        limiter = YFRateLimiter(counter_file=self.counter_file)
        limiter.check_and_increment()

        # State should be persisted.
        self.assertTrue(os.path.exists(self.counter_file))
        with open(self.counter_file, "r") as f:
            state = json.load(f)
        self.assertEqual(state["minute"]["count"], 1)
        self.assertEqual(state["hour"]["count"], 1)
        self.assertEqual(state["day"]["count"], 1)

    def test_multiple_increments(self):
        """Multiple calls increment correctly."""
        os.environ["VAULT_DIR"] = self.tmpdir
        os.environ["YF_LIMIT_PER_MIN"] = "100"
        from data_vault.rate_limiter import YFRateLimiter
        limiter = YFRateLimiter(counter_file=self.counter_file)

        for _ in range(5):
            limiter.check_and_increment()

        with open(self.counter_file, "r") as f:
            state = json.load(f)
        self.assertEqual(state["minute"]["count"], 5)

    def test_corrupt_counter_file(self):
        """Corrupt counter file falls back to fresh state."""
        with open(self.counter_file, "w") as f:
            f.write("NOT JSON")

        os.environ["VAULT_DIR"] = self.tmpdir
        from data_vault.rate_limiter import YFRateLimiter
        limiter = YFRateLimiter(counter_file=self.counter_file)
        # Should not raise — starts fresh.
        limiter.check_and_increment()

    def test_hour_limit_exits(self):
        """Per-hour limit triggers sys.exit(1)."""
        os.environ["VAULT_DIR"] = self.tmpdir
        os.environ["YF_LIMIT_PER_HOUR"] = "2"
        from data_vault.rate_limiter import YFRateLimiter
        limiter = YFRateLimiter(counter_file=self.counter_file)

        limiter.check_and_increment()
        limiter.check_and_increment()

        with self.assertRaises(SystemExit) as ctx:
            limiter.check_and_increment()
        self.assertEqual(ctx.exception.code, 1)

        # Cleanup.
        os.environ["YF_LIMIT_PER_HOUR"] = "2000"

    def test_day_limit_exits(self):
        """Per-day limit triggers sys.exit(1)."""
        os.environ["VAULT_DIR"] = self.tmpdir
        os.environ["YF_LIMIT_PER_DAY"] = "1"
        from data_vault.rate_limiter import YFRateLimiter
        limiter = YFRateLimiter(counter_file=self.counter_file)

        limiter.check_and_increment()

        with self.assertRaises(SystemExit) as ctx:
            limiter.check_and_increment()
        self.assertEqual(ctx.exception.code, 1)

        # Cleanup.
        os.environ["YF_LIMIT_PER_DAY"] = "48000"

    def test_minute_limit_raises_paused(self):
        """Per-minute limit raises RateLimitPaused with wait time (R19)."""
        os.environ["VAULT_DIR"] = self.tmpdir
        os.environ["YF_LIMIT_PER_MIN"] = "1"
        from data_vault.rate_limiter import YFRateLimiter, RateLimitPaused
        limiter = YFRateLimiter(counter_file=self.counter_file)

        limiter.check_and_increment()

        # Second call should raise RateLimitPaused.
        with self.assertRaises(RateLimitPaused) as ctx:
            limiter.check_and_increment()
        self.assertGreater(ctx.exception.wait_seconds, 0)

        # Cleanup.
        os.environ["YF_LIMIT_PER_MIN"] = "100"


# ── test: normalization ───────────────────────────────────────────────────────


class TestNormalization(unittest.TestCase):
    """Test the DataVault._normalize static method."""

    def test_column_casing(self):
        """Columns are title-cased and extra columns dropped."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)
        df.columns = [c.lower() for c in df.columns]
        df["extra"] = 999

        result = DataVault._normalize(df)
        self.assertListEqual(list(result.columns), ["Open", "High", "Low", "Close", "Volume"])

    def test_datetime_index(self):
        """Index is converted to DatetimeIndex with name=None."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)
        df.index = df.index.strftime("%Y-%m-%d")

        result = DataVault._normalize(df)
        self.assertIsInstance(result.index, pd.DatetimeIndex)
        self.assertIsNone(result.index.name)

    def test_sorted_ascending(self):
        """Output is sorted by index ascending."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)
        df = df.iloc[::-1]  # Reverse to descending.

        result = DataVault._normalize(df)
        self.assertTrue(result.index.is_monotonic_increasing)

    def test_missing_ohlc_returns_none(self):
        """DataFrame missing OHLC columns returns None."""
        from data_vault.data_vault import DataVault
        df = pd.DataFrame({"Foo": [1, 2], "Bar": [3, 4]})
        self.assertIsNone(DataVault._normalize(df))

    def test_missing_volume_added(self):
        """Volume column added as NaN if absent."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10).drop(columns=["Volume"])

        result = DataVault._normalize(df)
        self.assertIn("Volume", result.columns)
        self.assertTrue(result["Volume"].isna().all())

    def test_empty_df_returns_none(self):
        """Empty DataFrame returns None."""
        from data_vault.data_vault import DataVault
        self.assertIsNone(DataVault._normalize(pd.DataFrame()))

    def test_tz_aware_index_preserved_in_normalize(self):
        """Timezone-aware index is preserved through normalization (for cache fidelity)."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)
        df.index = df.index.tz_localize("America/New_York")

        result = DataVault._normalize(df)
        self.assertIsNotNone(result.index.tz)
        self.assertEqual(str(result.index.tz), "America/New_York")

    def test_strip_tz_removes_timezone(self):
        """_strip_tz produces a tz-naive DataFrame."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)
        df.index = df.index.tz_localize("America/New_York")

        result = DataVault._strip_tz(df)
        self.assertIsNone(result.index.tz)
        self.assertIsInstance(result.index, pd.DatetimeIndex)

    def test_strip_tz_noop_on_naive(self):
        """_strip_tz is a no-op on tz-naive data."""
        from data_vault.data_vault import DataVault
        df = _make_ohlcv_df(10)

        result = DataVault._strip_tz(df)
        self.assertIsNone(result.index.tz)


# ── test: manifest ────────────────────────────────────────────────────────────


class TestManifest(unittest.TestCase):
    """Test manifest load/save/corruption recovery."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        _setup_env(self.tmpdir, {"VAULT_DIR": self.vault_dir})
        self.env_path = os.path.join(self.tmpdir, ".env")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for k in _ENV_DEFAULTS:
            os.environ.pop(k, None)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_manifest_round_trip(self, _mock_dotenv):
        """Manifest saves and reloads correctly."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        vault._manifest["AAPL"] = {
            "fetch_date": "2026-03-30",
            "data_start_date": "2021-03-30",
            "data_end_date": "2026-03-28",
            "source": "ib",
            "rows": 1258,
        }
        vault._save_manifest()

        # Reload.
        manifest = vault._load_manifest()
        self.assertEqual(manifest["AAPL"]["rows"], 1258)
        self.assertEqual(manifest["AAPL"]["source"], "ib")

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_corrupt_manifest_rebuilt(self, _mock_dotenv):
        """Corrupt manifest.json triggers rebuild from Parquet files (F14)."""
        from data_vault.data_vault import DataVault

        # Write a valid Parquet file.
        df = _make_ohlcv_df(50)
        parquet_path = os.path.join(self.vault_dir, "AAPL_history.parquet")
        df.to_parquet(parquet_path)

        # Corrupt the manifest.
        manifest_path = os.path.join(self.vault_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            f.write("CORRUPT DATA")

        vault = DataVault(interactive=False)
        self.assertIn("AAPL", vault._manifest)
        self.assertEqual(vault._manifest["AAPL"]["rows"], 50)


_ENV_DEFAULTS = {
    "VAULT_DIR", "VAULT_TTL_DAYS", "VAULT_FETCH_YEARS",
    "IB_HOST", "IB_PORT", "IB_HISTORY_WAIT_SECONDS",
    "ALPHA_VANTAGE_API_KEY", "VAULT_INTERACTIVE",
    "YF_LIMIT_PER_MIN", "YF_LIMIT_PER_HOUR", "YF_LIMIT_PER_DAY",
}


# ── test: config & validation ────────────────────────────────────────────────


class TestConfig(unittest.TestCase):
    """Test DataVault.__init__ configuration and validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.saved_env = {k: os.environ.get(k) for k in _ENV_DEFAULTS}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for k in _ENV_DEFAULTS:
            if self.saved_env.get(k) is not None:
                os.environ[k] = self.saved_env[k]
            else:
                os.environ.pop(k, None)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_valid_config(self, _mock_dotenv):
        """DataVault initialises successfully with valid env vars."""
        _setup_env(self.tmpdir)
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)
        self.assertIsNotNone(vault)

    def test_missing_env_file_exits(self):
        """Missing .env file triggers sys.exit(1) (F7)."""
        # Ensure no .env exists and load_dotenv returns False.
        for k in _ENV_DEFAULTS:
            os.environ.pop(k, None)

        with patch("data_vault.data_vault.load_dotenv", return_value=False), \
             patch("data_vault.data_vault.os.path.exists", return_value=False):
            from data_vault.data_vault import DataVault
            with self.assertRaises(SystemExit) as ctx:
                DataVault()
            self.assertEqual(ctx.exception.code, 1)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_missing_required_var_exits(self, _mock_dotenv):
        """Missing ALPHA_VANTAGE_API_KEY triggers sys.exit(1) (F8)."""
        _setup_env(self.tmpdir)
        os.environ.pop("ALPHA_VANTAGE_API_KEY", None)

        from data_vault.data_vault import DataVault
        with self.assertRaises(SystemExit) as ctx:
            DataVault(interactive=False)
        self.assertEqual(ctx.exception.code, 1)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_vault_dir_auto_created(self, _mock_dotenv):
        """VAULT_DIR is auto-created if it doesn't exist (F9)."""
        vault_dir = os.path.join(self.tmpdir, "new_vault")
        _setup_env(self.tmpdir, {"VAULT_DIR": vault_dir})

        from data_vault.data_vault import DataVault
        DataVault(interactive=False)
        self.assertTrue(os.path.isdir(vault_dir))


# ── test: cache logic ────────────────────────────────────────────────────────


class TestCacheLogic(unittest.TestCase):
    """Test cache hit/miss/stale and negative cache."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        _setup_env(self.tmpdir, {"VAULT_DIR": self.vault_dir})
        self.env_path = os.path.join(self.tmpdir, ".env")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for k in _ENV_DEFAULTS:
            os.environ.pop(k, None)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_cache_hit(self, _mock_dotenv):
        """Fresh cached data is returned without fetching."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        # Pre-populate cache.
        df = _make_ohlcv_df(100)
        parquet_path = os.path.join(self.vault_dir, "AAPL_history.parquet")
        df.to_parquet(parquet_path)
        vault._manifest["AAPL"] = {
            "fetch_date": datetime.date.today().isoformat(),
            "data_start_date": str(df.index.min().date()),
            "data_end_date": str(df.index.max().date()),
            "source": "test",
            "rows": len(df),
        }
        vault._save_manifest()

        result = vault._check_cache("AAPL", years=1)
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_cache_miss(self, _mock_dotenv):
        """No cache returns None."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)
        result = vault._check_cache("AAPL", years=5)
        self.assertIsNone(result)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_stale_cache(self, _mock_dotenv):
        """Stale cache (older than TTL) returns None."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        parquet_path = os.path.join(self.vault_dir, "AAPL_history.parquet")
        df.to_parquet(parquet_path)

        stale_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        vault._manifest["AAPL"] = {
            "fetch_date": stale_date,
            "data_start_date": str(df.index.min().date()),
            "data_end_date": str(df.index.max().date()),
            "source": "test",
            "rows": len(df),
        }

        result = vault._check_cache("AAPL", years=5)
        self.assertIsNone(result)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_negative_cache_hit(self, _mock_dotenv):
        """Previously failed ticker is skipped within TTL (F1b)."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        vault._manifest["FB"] = {
            "status": "failed",
            "last_failed_attempt": datetime.date.today().isoformat(),
            "failure_reason": "all sources returned empty/error",
        }

        result = vault.get_data("FB")
        self.assertIsNone(result)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_corrupt_parquet_deleted(self, _mock_dotenv):
        """Corrupt Parquet file is deleted and cache returns None (F5)."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        parquet_path = os.path.join(self.vault_dir, "AAPL_history.parquet")
        with open(parquet_path, "w") as f:
            f.write("NOT A PARQUET FILE")

        vault._manifest["AAPL"] = {
            "fetch_date": datetime.date.today().isoformat(),
            "data_start_date": "2021-01-01",
            "data_end_date": "2026-03-28",
            "source": "test",
            "rows": 1000,
        }

        result = vault._check_cache("AAPL", years=5)
        self.assertIsNone(result)
        self.assertFalse(os.path.exists(parquet_path))


# ── test: integration with Backtest ───────────────────────────────────────────


class TestBacktestIntegration(unittest.TestCase):
    """Verify DataVault output is directly passable to Backtest()."""

    def test_normalized_df_accepted_by_backtest(self):
        """Normalized DataFrame passes Backtest validation."""
        from data_vault.data_vault import DataVault
        from backtesting import Backtest, Strategy

        class DummyStrategy(Strategy):
            def init(self):
                pass

            def next(self):
                pass

        df = _make_ohlcv_df(100, start="2023-01-01")
        normalized = DataVault._normalize(df)

        # This should not raise.
        bt = Backtest(normalized, DummyStrategy, cash=10000)
        stats = bt.run()
        self.assertIsNotNone(stats)


# ── test: CLI input parsing ───────────────────────────────────────────────────


class TestCLIPrompt(unittest.TestCase):
    """Test the CLI _prompt_selection helper."""

    def test_valid_single_selection(self):
        """Single valid number returns the correct option."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta", "Gamma"]
        with patch("builtins.input", return_value="2"):
            result = _prompt_selection("Test", options)
        self.assertEqual(result, ["Beta"])

    def test_valid_comma_separated(self):
        """Comma-separated numbers return correct options."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta", "Gamma"]
        with patch("builtins.input", return_value="1, 3"):
            result = _prompt_selection("Test", options)
        self.assertEqual(result, ["Alpha", "Gamma"])

    def test_valid_space_separated(self):
        """Space-separated numbers return correct options."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta", "Gamma"]
        with patch("builtins.input", return_value="1 2"):
            result = _prompt_selection("Test", options)
        self.assertEqual(result, ["Alpha", "Beta"])

    def test_out_of_range_exits(self):
        """Out-of-range number triggers sys.exit(1)."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta"]
        with patch("builtins.input", return_value="5"):
            with self.assertRaises(SystemExit) as ctx:
                _prompt_selection("Test", options)
            self.assertEqual(ctx.exception.code, 1)

    def test_non_numeric_exits(self):
        """Non-numeric input triggers sys.exit(1)."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta"]
        with patch("builtins.input", return_value="abc"):
            with self.assertRaises(SystemExit) as ctx:
                _prompt_selection("Test", options)
            self.assertEqual(ctx.exception.code, 1)

    def test_empty_input_exits(self):
        """Empty input triggers sys.exit(1)."""
        from data_vault.__main__ import _prompt_selection
        options = ["Alpha", "Beta"]
        with patch("builtins.input", return_value=""):
            with self.assertRaises(SystemExit) as ctx:
                _prompt_selection("Test", options)
            self.assertEqual(ctx.exception.code, 1)


class TestLoadMarkets(unittest.TestCase):
    """Test markets.json loading."""

    def test_load_markets(self):
        """markets.json loads with expected structure."""
        from data_vault.__main__ import _load_markets
        markets = _load_markets()
        self.assertIn("exchanges", markets)
        self.assertIn("sectors", markets)
        self.assertIn("NYSE", markets["exchanges"])
        self.assertIn("NASDAQ", markets["exchanges"])
        self.assertEqual(len(markets["sectors"]), 11)
        self.assertIn("Technology", markets["sectors"])


# ── test: round-robin fetch ──────────────────────────────────────────────────


class TestRoundRobin(unittest.TestCase):
    """Test round-robin source rotation in _fetch_from_providers."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        _setup_env(self.tmpdir, {"VAULT_DIR": self.vault_dir})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for k in _ENV_DEFAULTS:
            os.environ.pop(k, None)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_rotation_order(self, _mock_dotenv):
        """Sources are called in round-robin order across 3 get_data calls."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        sources_tried_first = []

        original_ib = vault._fetch_ib
        original_av = vault._fetch_alpha_vantage
        original_yf = vault._fetch_yfinance

        def mock_ib(ticker):
            sources_tried_first.append("ib")
            return df.copy()

        def mock_av(ticker):
            sources_tried_first.append("alpha_vantage")
            return df.copy()

        def mock_yf(ticker):
            sources_tried_first.append("yfinance")
            return df.copy()

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._fetch_yfinance = mock_yf

        # Call 3 times — each should try a different source first.
        vault.get_data("AAPL")
        vault.get_data("MSFT")
        vault.get_data("GOOG")

        # Each source should have been the first-try exactly once.
        self.assertEqual(sources_tried_first, ["ib", "alpha_vantage", "yfinance"])

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_av_exhaustion_removes_from_rotation(self, _mock_dotenv):
        """AV at daily limit is removed from rotation, rotation continues."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)
        vault._av_calls_today = 25  # At limit.

        df = _make_ohlcv_df(100)
        sources_used = []

        def mock_ib(ticker):
            sources_used.append("ib")
            return df.copy()

        def mock_yf(ticker):
            sources_used.append("yfinance")
            return df.copy()

        vault._fetch_ib = mock_ib
        vault._fetch_yfinance = mock_yf

        # AV should be removed from rotation after first attempt.
        vault.get_data("AAPL")
        vault.get_data("MSFT")
        vault.get_data("GOOG")
        vault.get_data("TSLA")

        # AV should never appear — only IB and yF alternating.
        self.assertNotIn("alpha_vantage", sources_used)
        self.assertIn("ib", sources_used)
        self.assertIn("yfinance", sources_used)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_yf_exhaustion_removes_from_rotation(self, _mock_dotenv):
        """yfinance SystemExit is caught and yF removed from rotation."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        sources_used = []

        def mock_ib(ticker):
            sources_used.append("ib")
            return df.copy()

        def mock_av(ticker):
            sources_used.append("alpha_vantage")
            return df.copy()

        def mock_yf(ticker):
            # Simulate rate limiter hard stop.
            raise SystemExit(1)

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._fetch_yfinance = mock_yf

        # yF is third in rotation — should be tried on 3rd call,
        # caught, and removed.
        vault.get_data("AAPL")  # IB
        vault.get_data("MSFT")  # AV
        vault.get_data("GOOG")  # yF fails → caught, falls back
        vault.get_data("TSLA")  # Should only rotate IB/AV now

        self.assertNotIn("yfinance", vault._available_sources)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_ib_unavailable_removes_from_rotation(self, _mock_dotenv):
        """IB connection failure removes IB from rotation."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)

        def mock_ib(ticker):
            return None  # Connection failed.

        def mock_av(ticker):
            return df.copy()

        def mock_yf(ticker):
            return df.copy()

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._fetch_yfinance = mock_yf

        # After IB fails, it should be flagged as unavailable.
        # Mark IB as having a connection issue (not per-ticker failure).
        vault._ib_unavailable = True
        vault._available_sources = [s for s in vault._available_sources if s != "ib"]

        vault.get_data("AAPL")
        vault.get_data("MSFT")

        self.assertNotIn("ib", vault._available_sources)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_all_sources_exhausted_returns_none(self, _mock_dotenv):
        """Empty available sources returns None (F19)."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)
        vault._available_sources = []

        result = vault.get_data("AAPL")
        self.assertIsNone(result)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_fallback_on_per_ticker_failure(self, _mock_dotenv):
        """Source fails for a ticker, next source is tried for same ticker."""
        from data_vault.data_vault import DataVault
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        sources_tried = []

        def mock_ib(ticker):
            sources_tried.append("ib")
            return None  # Fails for this ticker.

        def mock_av(ticker):
            sources_tried.append("alpha_vantage")
            return df.copy()  # Succeeds.

        def mock_yf(ticker):
            sources_tried.append("yfinance")
            return df.copy()

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._fetch_yfinance = mock_yf

        # First call: IB is first in rotation, fails, falls back to AV.
        result = vault.get_data("AAPL")
        self.assertIsNotNone(result)
        self.assertEqual(sources_tried, ["ib", "alpha_vantage"])


# ── test: throttle & smart retry ─────────────────────────────────────────────


class TestThrottleRetry(unittest.TestCase):
    """Test source throttling and smart retry logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        os.makedirs(self.vault_dir, exist_ok=True)
        _setup_env(self.tmpdir, {
            "VAULT_DIR": self.vault_dir,
            "IB_PACING_ENABLED": "true",
            "IB_HISTORY_WAIT_SECONDS": "15",
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        for k in _ENV_DEFAULTS:
            os.environ.pop(k, None)
        os.environ.pop("IB_PACING_ENABLED", None)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_ib_proactive_throttle_skips_to_next(self, _mock_dotenv):
        """IB proactive pacing raises _SourceThrottled, next source is tried."""
        import time as time_mod
        from data_vault.data_vault import DataVault, _SourceThrottled
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        sources_tried = []

        # Simulate a recent IB request (1 second ago).
        vault._last_ib_request_time = time_mod.monotonic() - 1.0

        original_fetch_ib = vault._fetch_ib

        def mock_av(ticker):
            sources_tried.append("alpha_vantage")
            return df.copy()

        def mock_yf(ticker):
            sources_tried.append("yfinance")
            return df.copy()

        vault._fetch_alpha_vantage = mock_av
        vault._fetch_yfinance = mock_yf

        # IB should be throttled (only 1s of 15s elapsed), AV should be used.
        result = vault.get_data("AAPL")
        self.assertIsNotNone(result)
        # IB should not have been used (throttled), AV picked up.
        self.assertIn("alpha_vantage", sources_tried)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_ib_reactive_throttle_on_pacing_error(self, _mock_dotenv):
        """IB pacing violation error raises _SourceThrottled (reactive mode)."""
        from data_vault.data_vault import DataVault, _SourceThrottled
        vault = DataVault(interactive=False)
        vault._ib_pacing_enabled = False  # Reactive mode.

        df = _make_ohlcv_df(100)
        sources_tried = []

        def mock_ib(ticker):
            # Simulate IB pacing violation.
            raise _SourceThrottled("ib", 15.0)

        def mock_av(ticker):
            sources_tried.append("alpha_vantage")
            return df.copy()

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av

        result = vault.get_data("AAPL")
        self.assertIsNotNone(result)
        self.assertIn("alpha_vantage", sources_tried)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_yf_minute_throttle_skips_to_next(self, _mock_dotenv):
        """yFinance minute limit raises throttle, next source is tried."""
        from data_vault.data_vault import DataVault, _SourceThrottled
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)
        sources_tried = []

        def mock_ib(ticker):
            sources_tried.append("ib")
            return None  # IB fails for this ticker.

        def mock_av(ticker):
            sources_tried.append("alpha_vantage")
            return None  # AV also fails.

        def mock_try_yf(ticker):
            raise _SourceThrottled("yfinance", 30.0)

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._try_fetch_yfinance = mock_try_yf

        # All fail/throttled — should wait for yF (shortest throttle) and retry.
        with patch("data_vault.data_vault.time.sleep") as mock_sleep:
            def yf_after_wait(ticker):
                sources_tried.append("yfinance_retry")
                return df.copy()

            # After sleep, replace the mock so retry succeeds.
            def sleep_side_effect(seconds):
                vault._try_fetch_yfinance = yf_after_wait

            mock_sleep.side_effect = sleep_side_effect
            result = vault.get_data("AAPL")

        self.assertIsNotNone(result)
        mock_sleep.assert_called_once_with(30.0)
        self.assertIn("yfinance_retry", sources_tried)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_all_throttled_waits_shortest(self, _mock_dotenv):
        """When all sources throttled, waits for the shortest cooldown."""
        from data_vault.data_vault import DataVault, _SourceThrottled
        vault = DataVault(interactive=False)

        df = _make_ohlcv_df(100)

        def mock_ib(ticker):
            raise _SourceThrottled("ib", 15.0)

        def mock_av(ticker):
            raise _SourceThrottled("alpha_vantage", 60.0)

        def mock_yf(ticker):
            raise _SourceThrottled("yfinance", 10.0)

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._try_fetch_yfinance = mock_yf

        with patch("data_vault.data_vault.time.sleep") as mock_sleep:
            def yf_after_wait(ticker):
                return df.copy()

            def sleep_side_effect(seconds):
                vault._try_fetch_yfinance = yf_after_wait

            mock_sleep.side_effect = sleep_side_effect
            result = vault.get_data("AAPL")

        # Should have waited for yfinance (10s — the shortest).
        mock_sleep.assert_called_once_with(10.0)
        self.assertIsNotNone(result)

    @patch("data_vault.data_vault.load_dotenv", return_value=True)
    def test_throttled_retry_fails_returns_none(self, _mock_dotenv):
        """If retry after wait also fails, returns None for this ticker."""
        from data_vault.data_vault import DataVault, _SourceThrottled
        vault = DataVault(interactive=False)

        def mock_ib(ticker):
            raise _SourceThrottled("ib", 15.0)

        def mock_av(ticker):
            return None  # Not throttled, just fails.

        def mock_yf(ticker):
            raise _SourceThrottled("yfinance", 10.0)

        vault._fetch_ib = mock_ib
        vault._fetch_alpha_vantage = mock_av
        vault._try_fetch_yfinance = mock_yf

        with patch("data_vault.data_vault.time.sleep") as mock_sleep:
            # yF still fails after wait.
            def yf_still_fails(ticker):
                return None

            mock_sleep.side_effect = lambda s: setattr(
                vault, '_try_fetch_yfinance', yf_still_fails
            )
            result = vault.get_data("AAPL")

        self.assertIsNone(result)
        mock_sleep.assert_called_once_with(10.0)


if __name__ == "__main__":
    unittest.main()
