# Spec: DataVault — Cached OHLCV Data Fetching with Triple Fallback

**Status:** IMPLEMENTED
**Squashed:** 2026-03-30
**Area:** `data_vault/` (standalone package, outside `backtesting/`)
**Author:** AI-assisted
**Date:** 2026-03-30

---

## Context & Goal

DataVault provides a single `DataVault` class that fetches, caches, and normalizes historical daily OHLCV data. It uses a triple-fallback strategy (Interactive Brokers -> Alpha Vantage -> yfinance) with Parquet-based caching and a JSON manifest for TTL-based invalidation. Output DataFrames are directly passable to `Backtest(data, strategy)` without transformation.

**Key constraints:**
- DataVault is a standalone package at repo root (`data_vault/`). It has no import relationship with `backtesting/`.
- Dependencies are isolated to `requirements-backtest.txt`, not added to `setup.py`.

---

## Requirements

### R1: Package Structure
- `data_vault/__init__.py` exports `DataVault`
- `data_vault/data_vault.py` — main module (config, cache, fetch, normalize)
- `data_vault/rate_limiter.py` — yfinance rate limiter (adapted from `TradingAgents/screener/yf_rate_limiter.py`)
- `requirements-backtest.txt` — `python-dotenv`, `pyarrow`, `yfinance`, `ib_async`
- `.env.example` — template with all env vars and defaults

### R2: Configuration (.env Integration)
- On `DataVault.__init__`, loads `.env` via `python-dotenv`. Hard stop if missing.
- Required environment variables validated upfront:

| Variable | Default | Description |
|---|---|---|
| `VAULT_DIR` | `data_vault/` | Directory for Parquet files and manifest |
| `VAULT_TTL_DAYS` | `7` | Days before cached data is considered stale |
| `VAULT_FETCH_YEARS` | `5` | Default number of years to fetch from providers |
| `IB_HOST` | `127.0.0.1` | Interactive Brokers TWS/Gateway host |
| `IB_PORT` | `7497` | Interactive Brokers TWS/Gateway port |
| `IB_HISTORY_WAIT_SECONDS` | `15` | Sleep between IB historical data requests |
| `ALPHA_VANTAGE_API_KEY` | *(required, no default)* | Alpha Vantage API key |
| `VAULT_INTERACTIVE` | `true` | If `false`, skip all interactive prompts |
| `YF_LIMIT_PER_MIN` | `100` | yfinance per-minute request ceiling |
| `YF_LIMIT_PER_HOUR` | `2000` | yfinance per-hour request ceiling |
| `YF_LIMIT_PER_DAY` | `48000` | yfinance per-day request ceiling |

### R3: Cache & Manifest
- Each ticker cached as `{VAULT_DIR}/{TICKER}_history.parquet`
- JSON manifest at `{VAULT_DIR}/manifest.json` tracks: `fetch_date`, `data_start_date`, `data_end_date`, `source`, `rows`
- `VAULT_DIR` auto-created via `os.makedirs(exist_ok=True)`

### R4: Data Normalization
- Columns forced to exactly `['Open', 'High', 'Low', 'Close', 'Volume']` (title-cased). Extra columns dropped.
- Index converted to `pd.DatetimeIndex` with `name=None`. Sorted ascending.
- Adjusted prices: IB uses `ADJUSTED_LAST`, yfinance uses `auto_adjust=True`, Alpha Vantage applies adjustment ratio (`adj_close / close`) to raw OHLC.

### R5: Fetching Logic — `get_data(ticker, years=5)`
- **Cache check:** TTL-based. Fresh + sufficient range -> return slice. Stale -> re-fetch. Missing -> fetch fresh.
- **IB (primary):** Connect, fetch daily bars with `ADJUSTED_LAST`, sleep `IB_HISTORY_WAIT_SECONDS`. On failure: interactive prompt or silent fallback.
- **Alpha Vantage (secondary):** `TIME_SERIES_DAILY_ADJUSTED`, 25 calls/day limit tracked in manifest. On limit -> fallback to yfinance.
- **yfinance (tertiary):** Rate-limited via `YFRateLimiter`. `auto_adjust=True`. On failure -> negative cache hit.
- **Negative cache:** Failed tickers recorded in manifest. Skipped on retry within TTL.
- **Short history:** Partial data accepted as complete. Actual dates recorded.
- **Post-fetch:** Normalize, save Parquet, update manifest.
- **Ticker validation:** Regex `^[A-Z0-9][A-Z0-9.\-]{0,19}$` prevents path traversal.

### R6: Batch Interface
- `get_batch(tickers, years=5) -> dict[str, DataFrame]`: Sequential iteration, failed tickers omitted.

### R7: yfinance Rate Limiter
- Rolling windows: per-minute, per-hour, per-day. Limits from env vars.
- Per-minute: pause and resume. Per-hour/day: hard stop (`sys.exit(1)`).
- State persisted to `{VAULT_DIR}/yf_rate_counters.json` (atomic write pattern).

### R8: Logging
- `logging.getLogger("data_vault")`. Format: `"{LEVEL}|VAULT|{message}"`.

### R9: Imports & Dependencies
- All imports at top of `data_vault.py`. `ImportError` -> error message + `sys.exit(1)`.

---

## Failure Modes

| # | Trigger | Response |
|---|---|---|
| F1 | Ticker not found on any source | Log warning, record negative cache hit, return `None` |
| F1b | Negative cache hit on retry | Skip fetch, return `None` immediately |
| F2 | IB connection refused | Interactive: prompt. Non-interactive: silent fallback |
| F3 | All 3 sources fail | Warn, continue to next ticker |
| F4 | Alpha Vantage daily limit | Immediate fallback to yfinance |
| F5 | Corrupted Parquet | Delete file, re-fetch |
| F6 | NaN in OHLC / missing columns | Warn, skip ticker |
| F7 | `.env` missing | `sys.exit(1)` |
| F8 | Required env var missing | `sys.exit(1)` with list of missing vars |
| F9 | `VAULT_DIR` missing | Auto-create |
| F10 | Fewer years than requested | Accept as complete |
| F11 | Disk full / permission denied | Raise `OSError` as-is |
| F12 | yfinance per-minute limit | Pause, auto-resume |
| F13 | yfinance per-hour/day limit | `sys.exit(1)` |
| F14 | Manifest corrupted | Rebuild from Parquet files |

---

## Security Considerations

- **Path traversal:** Ticker symbols validated via regex before use in file paths or URLs.
- **URL injection:** Alpha Vantage ticker parameter URL-encoded via `urllib.parse.quote`.
- **Division by zero:** Alpha Vantage adjustment ratio guarded (`if raw_close != 0 else 1.0`).
- **No eval/exec:** All data processing uses pandas/numpy operations only.
- **No pickle:** Parquet + JSON only for persistence.

---

## File Map

| File | Purpose |
|---|---|
| `data_vault/__init__.py` | Package exports: `DataVault` |
| `data_vault/data_vault.py` | Main `DataVault` class — config, cache, fetch, normalize |
| `data_vault/rate_limiter.py` | `YFRateLimiter` adapted for vault context |
| `data_vault/tests/test_data_vault.py` | 24 tests: config, cache, normalization, rate limiter, manifest, integration |
| `requirements-backtest.txt` | Pip requirements for DataVault dependencies |
| `.env.example` | Template with all env vars and defaults documented |

---

## Out of Scope
- No changes to `backtesting/` package (core library untouched)
- No CLI interface (DataVault is used programmatically)
- No async/concurrent fetching (sequential due to IB pacing and rate limits)
- No database backend (Parquet + JSON manifest only)
