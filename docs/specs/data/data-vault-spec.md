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
- No async/concurrent fetching (sequential due to IB pacing and rate limits)
- No database backend (Parquet + JSON manifest only)

---

## Revision [Date:2026-03-31 00:00] — change-id: add-cli-logging

### Requirements

- [x] **R10: Logging Configuration** — Configure `data_vault` logger with both a `RotatingFileHandler` (max size and backup count from env vars `VAULT_LOG_MAX_BYTES` default `1048576`, `VAULT_LOG_BACKUP_COUNT` default `6`) and a `StreamHandler` (console). Log file at `{VAULT_DIR}/data_vault.log`. Format: `"{asctime} {levelname}|VAULT|{message}"`.
- [x] **R11: CLI Interface (`__main__.py`)** — Interactive CLI that:
  1. Presents numbered, alphabetically sorted list of exchanges (NYSE, NASDAQ). Accepts comma/space-separated numbers. Validates and exits on invalid input.
  2. Presents numbered, alphabetically sorted list of GICS sectors. Accepts comma/space-separated numbers. Validates and exits on invalid input.
  3. Uses `yfinance.screener` (`EquityQuery` + `screen()`) to fetch tickers for selected sector/exchange combinations. Paginates (max 250/call).
  4. Fetches OHLCV data for all discovered tickers via `DataVault.get_batch()`. Logs progress: `"Fetching {ticker}: {counter} of {total}"`.
- [x] **R12: Exchange/Sector Data** — JSON datastore at `data_vault/markets.json` containing exchanges (code + display name) and GICS sectors.
- [x] **R13: VS Code Debug Config** — `launch.json` entry to run `data_vault` as a module.

### Unhappy Paths

- **Invalid exchange selection (non-numeric, out of range):** Print error, `sys.exit(1)`.
- **Invalid sector selection:** Same as above.
- **yfinance screener returns 0 tickers:** Log warning, skip that sector/exchange combo, continue.
- **yfinance screener API error:** Log warning, skip combo, continue.
- **Screener results exceed 250 (pagination needed):** Paginate with offset until all tickers collected.

### Technical Plan

- **Files:** `data_vault/__main__.py`, `data_vault/logging_config.py`, `data_vault/markets.json`, `.vscode/launch.json`, `.env.example`
- **Test Strategy:** Category B for launch.json/.env changes. Category A for CLI logic (screener, input parsing) — add tests to `data_vault/tests/test_data_vault.py`.

---

## Revision [Date:2026-03-31 14:00] — change-id: round-robin-fetch

### Requirements

- [x] **R14: Round-Robin Source Rotation** — Replace the fixed IB → AV → yF waterfall in `_fetch_from_providers` with a round-robin strategy. The `DataVault` instance maintains a rotation index and a list of available sources (`["ib", "alpha_vantage", "yfinance"]`). For each call to `_fetch_from_providers`:
  1. Pick the source at the current rotation index as the first-try source.
  2. If the first-try source fails for this ticker, cycle through the remaining available sources.
  3. Advance the rotation index after each call (regardless of success/failure).
- [x] **R15: Dynamic Source Exhaustion** — When a source hits its daily limit, remove it from the available sources list for the remainder of the instance's lifetime:
  - Alpha Vantage: 25 calls/day (existing `_AV_DAILY_LIMIT`). On limit hit, remove `"alpha_vantage"` from available sources and log warning.
  - yfinance: 48,000 calls/day (existing `YF_LIMIT_PER_DAY`). On limit hit, remove `"yfinance"` from available sources and log warning.
  - IB: No daily limit. Only removed if connection fails entirely (existing F2 behavior).
- [x] **R16: Graceful Degradation** — When sources are exhausted:
  - Two sources remaining: continue rotation with two.
  - One source remaining (typically IB): fall back to single-source mode with pacing.
  - Zero sources: existing F3 behavior (warn, skip ticker, return None).

### Unhappy Paths

- **F15 — AV limit reached mid-run:** Remove `"alpha_vantage"` from `_available_sources`, log `"Alpha Vantage daily limit reached (%d/%d), removed from rotation"`, continue with remaining sources.
- **F16 — yF limit reached mid-run:** Remove `"yfinance"` from `_available_sources`, log `"yfinance daily limit reached, removed from rotation"`, continue with remaining sources.
- **F17 — Both AV + yF exhausted:** Log `"Only IB remaining in rotation"`, continue IB-only with existing pacing.
- **F18 — IB unavailable at session start:** Remove `"ib"` from `_available_sources`, rotate between AV + yF.
- **F19 — All sources unavailable/exhausted:** Existing F3 — warn, skip ticker, return None.
- **F20 — Source fails for specific ticker (not exhausted):** Try next available source in rotation for same ticker before giving up.

### Technical Plan

- **Files:** `data_vault/data_vault.py` (modify `__init__`, `_fetch_from_providers`, add `_available_sources` and `_rotation_index` attributes)
- **Validation:** No new env vars needed. Existing `_AV_DAILY_LIMIT` and `YF_LIMIT_PER_DAY` env vars already cover limits.
- **Test Strategy:** Category A — add round-robin tests to `data_vault/tests/test_data_vault.py`. Key scenarios: rotation order, source exhaustion mid-batch, fallback when source fails, all-sources-exhausted.

---

## Revision [Date:2026-03-31 16:30] — change-id: smart-throttle-retry

### Requirements

- [x] **R17: Source Throttle Signalling** — Introduce a `_SourceThrottled` exception (internal to `data_vault.py`) with `source: str` and `wait_seconds: float`. Fetch methods raise this instead of silently failing when they are temporarily rate-limited (not permanently exhausted).
- [x] **R18: IB Pacing Modes** — New env var `IB_PACING_ENABLED` (default `true`):
  - **Enabled:** Track `_last_ib_request_time`. Before each IB fetch, if less than `IB_HISTORY_WAIT_SECONDS` have elapsed, raise `_SourceThrottled("ib", remaining)`. Remove the post-fetch `time.sleep()` — pacing is now handled by the rotation.
  - **Disabled:** No proactive tracking. Detect IB pacing violation errors (keyword `"pacing"` in exception message) and raise `_SourceThrottled("ib", IB_HISTORY_WAIT_SECONDS)`.
- [x] **R19: yFinance Throttle Signal** — Modify `YFRateLimiter.check_and_increment()`: on per-minute limit, raise `RateLimitPaused(wait_seconds)` instead of sleeping. Callers catch this and convert to `_SourceThrottled`. Hour/day limits still raise `SystemExit(1)` (handled by existing `_try_fetch_yfinance` wrapper).
- [x] **R20: Smart Retry in `_fetch_from_providers`** — After cycling through all sources for a ticker:
  1. If any sources raised `_SourceThrottled`, collect `{source: wait_seconds}`.
  2. Pick the source with the shortest wait, sleep that duration, retry that one source.
  3. If the retry also fails or is throttled, give up for this ticker (return None).

### Unhappy Paths

- **F21 — IB pacing violation (reactive mode):** Detect "pacing" in IB error, raise `_SourceThrottled`, try next source. If all throttled, wait shortest and retry.
- **F22 — IB proactive throttle:** Less than `IB_HISTORY_WAIT_SECONDS` since last IB call, raise `_SourceThrottled` with remaining time. Try next source.
- **F23 — yF minute limit:** Rate limiter raises `RateLimitPaused`, converted to `_SourceThrottled`. Try next source.
- **F24 — All sources throttled simultaneously:** Wait for shortest cooldown, retry that source. If still fails, return None for this ticker.
- **F25 — Throttled source also permanently exhausted on retry:** Treat as failure, return None.

### Technical Plan

- **Files:** `data_vault/data_vault.py`, `data_vault/rate_limiter.py`, `data_vault/tests/test_data_vault.py`, `.env.example`
- **Validation:** New env var `IB_PACING_ENABLED` with default `true`.
- **Test Strategy:** Category A — add `TestThrottleRetry` class. Key scenarios: IB proactive throttle, IB reactive throttle, yF minute-limit throttle, all-sources-throttled wait-and-retry, shortest-wait selection.
