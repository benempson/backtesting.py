# Operational Reference: DataVault

> Generated from `docs/specs/data/data-vault-spec.md` and source code on 2026-03-31.

---

## 1. System Constants

### `data_vault/data_vault.py`

| Constant | Value | Purpose |
|---|---|---|
| `_OHLCV_COLUMNS` | `["Open", "High", "Low", "Close", "Volume"]` | Canonical column order for normalized output |
| `_AV_DAILY_LIMIT` | `25` | Alpha Vantage free-tier daily call ceiling |
| `_VALID_TICKER_RE` | `^[A-Z0-9][A-Z0-9.\-]{0,19}$` | Ticker validation regex (security: path traversal prevention) |

### `data_vault/rate_limiter.py`

| Constant | Value | Purpose |
|---|---|---|
| `_DEFAULT_LIMIT_PER_MIN` | `100` | Default yfinance per-minute ceiling |
| `_DEFAULT_LIMIT_PER_HOUR` | `2000` | Default yfinance per-hour ceiling |
| `_DEFAULT_LIMIT_PER_DAY` | `48000` | Default yfinance per-day ceiling |
| `_WINDOW_DURATIONS` | `{minute: 1m, hour: 1h, day: 1d}` | Rolling window durations |

### `data_vault/__main__.py`

| Constant | Value | Purpose |
|---|---|---|
| `_YF_SCREENER_PAGE_SIZE` | `250` | Max results per yfinance screener call (Yahoo limit) |

### Environment Variable Defaults (`_ENV_DEFAULTS`)

| Variable | Default | Required |
|---|---|---|
| `VAULT_DIR` | `data_vault/` | No |
| `VAULT_TTL_DAYS` | `7` | No |
| `VAULT_FETCH_YEARS` | `5` | No |
| `IB_HOST` | `127.0.0.1` | No |
| `IB_PORT` | `7497` | No |
| `IB_HISTORY_WAIT_SECONDS` | `15` | No |
| `ALPHA_VANTAGE_API_KEY` | *(none)* | **Yes** |
| `VAULT_INTERACTIVE` | `true` | No |
| `YF_LIMIT_PER_MIN` | `100` | No |
| `YF_LIMIT_PER_HOUR` | `2000` | No |
| `YF_LIMIT_PER_DAY` | `48000` | No |
| `VAULT_LOG_MAX_BYTES` | `1048576` | No |
| `VAULT_LOG_BACKUP_COUNT` | `6` | No |

---

## 2. Data Model

### Class: `DataVault` (`data_vault/data_vault.py`)

Single entry point for all data fetching. Owns the cache, manifest, and provider fallback chain.

**Instance attributes:**
- `_vault_dir: str` — Parquet/manifest storage directory
- `_ttl_days: int` — Cache staleness threshold
- `_fetch_years: int` — Default history depth
- `_ib_host, _ib_port, _ib_wait` — IB connection parameters
- `_av_key: str` — Alpha Vantage API key
- `_interactive: bool` — Whether to prompt on IB failure
- `_manifest: dict` — In-memory manifest (ticker -> metadata)
- `_av_calls_today: int` — Daily Alpha Vantage call counter
- `_yf_limiter: YFRateLimiter` — yfinance rate limiter instance

### Class: `YFRateLimiter` (`data_vault/rate_limiter.py`)

Rolling-window rate limiter with 3 windows (minute, hour, day). State persisted to JSON.

**Instance attributes:**
- `_counter_file: str` — Path to persisted state JSON
- `_limits: dict[str, int]` — Per-window ceilings
- `_state: dict[str, dict]` — Per-window `{count, window_start}` pairs

### Data Flow

```
User script -> DataVault.get_data("AAPL")
  -> negative cache check
  -> _check_cache (Parquet + manifest TTL)
  -> _fetch_from_providers (IB -> AV -> yfinance)
  -> _normalize (title-case, DatetimeIndex, sort)
  -> NaN validation
  -> _save_to_cache (Parquet + manifest update)
  -> slice to requested years
  -> return DataFrame
```

---

## 3. Module Architecture

| File | Purpose |
|---|---|
| `data_vault/__init__.py` | Package entry — exports `DataVault` |
| `data_vault/__main__.py` | Interactive CLI: exchange/sector selection, screener, batch fetch |
| `data_vault/data_vault.py` | Core class: config loading, cache, 3 provider fetchers, normalization |
| `data_vault/rate_limiter.py` | `YFRateLimiter`: rolling-window rate limiter for yfinance |
| `data_vault/logging_config.py` | `setup_logging()`: rotating file + console handlers |
| `data_vault/markets.json` | Exchange codes (NYSE/NASDAQ) and GICS sector list |
| `data_vault/tests/test_data_vault.py` | 31 unittest tests across 8 TestCase classes |
| `.vscode/launch.json` | VS Code debug config for `python -m data_vault` |

**Dependencies:** `data_vault.py` imports from `rate_limiter.py` and `logging_config.py`. `__main__.py` imports from `data_vault.py` and `logging_config.py`. No reverse dependencies. No imports from `backtesting/`.

---

## 4. Key Signatures

### `DataVault`

| Method | Signature | Returns |
|---|---|---|
| `__init__` | `(interactive: bool \| None = None)` | — |
| `get_data` | `(ticker: str, years: int \| None = None)` | `pd.DataFrame \| None` |
| `get_batch` | `(tickers: list[str], years: int \| None = None)` | `dict[str, pd.DataFrame]` |
| `_normalize` | `@staticmethod (df: pd.DataFrame)` | `pd.DataFrame \| None` |
| `_check_cache` | `(ticker: str, years: int)` | `pd.DataFrame \| None` |
| `_fetch_from_providers` | `(ticker: str)` | `pd.DataFrame \| None` |
| `_fetch_ib` | `(ticker: str)` | `pd.DataFrame \| None` |
| `_fetch_alpha_vantage` | `(ticker: str)` | `pd.DataFrame \| None` |
| `_fetch_yfinance` | `(ticker: str)` | `pd.DataFrame \| None` |

### `YFRateLimiter`

| Method | Signature | Returns |
|---|---|---|
| `__init__` | `(counter_file: str \| None = None)` | — |
| `check_and_increment` | `()` | `None` (may `sys.exit(1)` or sleep) |

---

## 5. Test Coverage

**File:** `data_vault/tests/test_data_vault.py` — 24 tests

| Test Class | Methods | What Is Verified |
|---|---|---|
| `TestYFRateLimiter` | 6 | Increment, persist, corrupt file recovery, minute pause, hour/day hard stop |
| `TestNormalization` | 6 | Column casing, DatetimeIndex, sort, missing OHLC, missing Volume, empty DF |
| `TestManifest` | 2 | Round-trip save/load, corrupt manifest rebuild from Parquet (F14) |
| `TestConfig` | 4 | Valid config, missing .env (F7), missing var (F8), VAULT_DIR auto-create (F9) |
| `TestCacheLogic` | 5 | Cache hit, miss, stale, negative cache (F1b), corrupt Parquet (F5) |
| `TestBacktestIntegration` | 1 | Normalized DF passes `Backtest()` validation |

---

## 6. Security Considerations

| Vector | Risk | Mitigation |
|---|---|---|
| Path traversal via ticker | High | `_VALID_TICKER_RE` regex validates before use in file paths |
| URL injection via ticker | Medium | `urllib.parse.quote(ticker, safe="")` in Alpha Vantage URL |
| Division by zero in AV adjustment | Medium | Guard: `if raw_close != 0 else 1.0` |
| Code injection via eval/exec | N/A | Not used anywhere |
| Pickle deserialization | N/A | Parquet + JSON only |
| Resource exhaustion | Low | Rate limiter + sequential fetching |

---

## 7. Edge Cases

| Case | Behavior |
|---|---|
| Ticker doesn't exist on any source | Negative cache hit recorded; skipped on retry within TTL |
| IB not running (interactive mode) | User prompted; `n` -> `sys.exit(1)`, `y` -> fallback |
| IB not running (non-interactive) | Silent fallback to Alpha Vantage |
| Alpha Vantage 25/day limit hit | Immediate fallback to yfinance, counter tracked in manifest |
| yfinance per-minute limit | Automatic sleep + resume |
| yfinance per-hour/day limit | Hard `sys.exit(1)` |
| Corrupt Parquet file | Deleted, re-fetched from providers |
| Corrupt manifest.json | Rebuilt from existing Parquet file metadata |
| Provider returns <N years (IPO) | Accepted as complete; actual dates in manifest |
| Data has NaN in OHLC | Ticker skipped with warning |
| Corrupt rate counter file | Fresh state (count=0) initialized |
| Ticker with dots/dashes (BRK.B) | Allowed by `_VALID_TICKER_RE` |
| `.env` missing | `sys.exit(1)` with guidance message |
| Disk full | `OSError` raised as-is (no wrapping) |

---

## 8. Manifest Schema

Each ticker entry in `{VAULT_DIR}/manifest.json`:

**Successful fetch:**
```
{ticker}: {fetch_date, data_start_date, data_end_date, source, rows}
```

**Failed fetch (negative cache):**
```
{ticker}: {status: "failed", last_failed_attempt, failure_reason}
```

**Alpha Vantage counter (metadata key):**
```
_av_meta: {date, calls}
```
