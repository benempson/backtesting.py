# BACKTESTING.PY — AI ARCHITECTURAL MANIFESTO

> **Purpose:** This is the prime directive for every AI session working on this codebase. Read this file first, always.

## PROJECT IDENTITY

**backtesting.py** is a lightweight, production-ready Python library for backtesting algorithmic trading strategies. It enables traders and quantitative analysts to define strategies in Python, backtest them against historical OHLCV data, optimize parameters, and visualize results interactively.

- **Repository:** https://github.com/kernc/backtesting.py
- **License:** AGPL-3.0
- **Python:** 3.9+
- **Core Dependencies:** numpy (>=1.17.0), pandas (>=0.25.0), bokeh (>=3.0.0)

---

## ARCHITECTURAL OVERVIEW

The codebase is a single Python package (`backtesting/`) with a flat module structure. There are no sub-packages, no microservices, no agent graphs. Simplicity is the architecture.

### Module Responsibilities

| Module | Purpose | Lines (approx) |
|---|---|---|
| `backtesting/backtesting.py` | Core engine: `Backtest`, `Strategy`, `_Broker`, `Order`, `Position`, `Trade` | ~1750 |
| `backtesting/_util.py` | Internal utilities: `_Indicator`, `_Data`, `SharedMemoryManager`, helpers | ~340 |
| `backtesting/_stats.py` | Performance statistics: `compute_stats`, drawdown analysis, geometric mean | ~210 |
| `backtesting/_plotting.py` | Bokeh-based interactive visualization: candlesticks, equity curve, heatmaps | ~785 |
| `backtesting/lib.py` | Public helpers and composable strategies: `crossover`, `SignalStrategy`, `MultiBacktest`, `resample_apply` | ~650 |
| `backtesting/__init__.py` | Package exports: `Backtest`, `Strategy`, `Pool`, `set_bokeh_output` | ~95 |
| `backtesting/test/` | Test suite (unittest): `_test.py`, test data (GOOG, EURUSD, BTCUSD CSV files) | ~1000+ assertions |

### Key Design Patterns

1. **Declarative Indicator System** — Indicators are declared in `Strategy.init()` via `self.I(func, *args)`. The framework automatically handles plotting, overlays, and NaN warmup detection.

2. **Lazy Data Revelation** — In `init()`, full data is available for precomputation. In `next()`, only data up to the current bar is visible. This prevents look-ahead bias.

3. **Order-Driven Simulation** — Market orders fill on the next bar's open (by default). Limit/stop orders fill when conditions are met. SL/TP orders are automatically created and reprocessed on the same bar.

4. **No External State** — The library is stateless between runs. No databases, no config files, no environment variables required.

5. **Numeric-First** — The core engine operates on numpy arrays, not DataFrames, for performance. DataFrames are used only at the API boundary.

### Dependency Direction

```
backtesting.py  →  _util.py
                →  _stats.py
                →  _plotting.py
lib.py          →  backtesting.py, _stats.py, _plotting.py, _util.py
```

- `_util.py`, `_stats.py`, and `_plotting.py` are internal modules (prefixed with `_`). They do not import from `backtesting.py` or `lib.py` (except via TYPE_CHECKING).
- `lib.py` is the public extension layer — it imports from the core but the core does not import from `lib.py`.
- `__init__.py` re-exports from all modules.

**Forbidden imports:**
- `_util.py` importing from `backtesting.py` or `lib.py` (circular dependency)
- `_stats.py` importing from `_plotting.py` or vice versa (peer modules, no cross-dependency)
- `_plotting.py` importing from `lib.py`

---

## TESTING

- **Framework:** Python's built-in `unittest` module
- **Entry point:** `python -m backtesting.test`
- **Test file:** `backtesting/test/_test.py` (single comprehensive test module)
- **Test data:** GOOG (daily), EURUSD (hourly), BTCUSD (monthly) — CSV files in `backtesting/test/`
- **Coverage:** `coverage run -m backtesting.test && coverage report`
- **Performance:** Full suite runs in <0.3 seconds

### Test Conventions

- Tests use `unittest.TestCase` subclasses
- Test data is imported from `backtesting.test` (`GOOG`, `EURUSD`, `BTCUSD`, `SMA`)
- Strategy subclasses for testing are defined at module level in `_test.py`
- No mocking framework is used — tests exercise real code paths
- Performance tests verify the suite completes within time bounds

---

## CI/CD

The GitHub Actions pipeline (`.github/workflows/ci.yml`) runs on push/PR to `master`:

1. **Lint** (Ubuntu): `flake8 backtesting setup.py` + `mypy backtesting`
2. **Coverage** (Ubuntu, Python 3.10): `coverage run -m backtesting.test`
3. **Build** (Ubuntu, Python 3.12/3.13): `python -m backtesting.test`
4. **Docs** (Ubuntu): `doc/build.sh` (pdoc3)
5. **Win64** (Windows, Python 3.13): `python -m backtesting.test`

---

## CODE STANDARDS

- **Line length:** 100 characters (enforced by ruff/flake8)
- **Linter:** flake8 + ruff (see `pyproject.toml` for rule selection)
- **Type checking:** mypy (run as `mypy backtesting`)
- **Docstrings:** pdoc3-compatible markdown docstrings on all public API
- **No print():** Use `warnings.warn()` for user-facing messages
- **Naming:** Follow existing conventions — private modules prefixed with `_`, private methods prefixed with `_`

---

## PUBLIC API SURFACE

The public API is intentionally small. Users import from two places:

```python
from backtesting import Backtest, Strategy  # Core
from backtesting.lib import crossover, SignalStrategy, ...  # Helpers
```

Any change to these exports is a breaking change and requires a CHANGELOG entry.

---

## GOVERNANCE

- **Rules:** `.ai/rules/` — Always-active behavioral rules for AI sessions.
- **Workflows:** `.ai/workflows/` — Named procedures for code-writing tasks (bugs, features, refactors, specs).
- **This file (AGENTS.md):** The prime directive. Read first, always.
- **PROJECT_SUMMARY.md:** Living record of current architecture and file tree.

When the architecture changes, update both `AGENTS.md` and `PROJECT_SUMMARY.md` in the same commit.
