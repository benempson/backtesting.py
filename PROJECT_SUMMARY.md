# PROJECT SUMMARY — backtesting.py

> Last updated: 2026-03-30

## Project Overview

**backtesting.py** is a Python 3.9+ library for backtesting trading strategies against historical OHLCV candlestick data. It provides strategy definition, parameter optimization (grid search + Bayesian via SAMBO), and interactive Bokeh-based visualization. Designed for simplicity and performance across any financial instrument.

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.9+ |
| Core deps | numpy (>=1.17.0), pandas (>=0.25.0), bokeh (>=3.0.0) |
| Visualization | Bokeh (interactive HTML charts) |
| Optimization | Grid search (built-in), Bayesian (SAMBO, optional) |
| Parallelism | multiprocessing (with SharedMemoryManager) |
| Testing | unittest (stdlib) |
| Linting | flake8, ruff |
| Type checking | mypy |
| Docs | pdoc3, Jupyter notebooks |
| CI | GitHub Actions |

## Architecture

Single flat package. No sub-packages, no services.

```
backtesting.py (core engine)
├── Strategy, Backtest, _Broker, Order, Position, Trade
├── _util.py (internal helpers, _Indicator, _Data, SharedMemoryManager)
├── _stats.py (compute_stats, drawdown analysis, geometric mean)
├── _plotting.py (Bokeh visualization, candlesticks, heatmaps)
└── lib.py (public helpers: crossover, SignalStrategy, MultiBacktest, resample_apply)
```

**Dependency direction:** `lib.py → backtesting.py → _util.py / _stats.py / _plotting.py`. Internal modules do not import from each other or from higher layers.

## Key Classes

| Class | Module | Purpose |
|---|---|---|
| `Strategy` | backtesting.py | Abstract base — users subclass and implement `init()` + `next()` |
| `Backtest` | backtesting.py | Main orchestrator — `run()`, `optimize()`, `plot()` |
| `_Broker` | backtesting.py | Internal accounting — fills orders, tracks positions/trades/cash |
| `Order` | backtesting.py | Represents a pending order (market, limit, stop, SL/TP) |
| `Position` | backtesting.py | Current open position — `size`, `pl`, `pl_pct`, `close()` |
| `Trade` | backtesting.py | Completed or active trade record |
| `SignalStrategy` | lib.py | Composable base — define signals, auto-generate orders |
| `TrailingStrategy` | lib.py | Composable base — trailing stop-loss logic |
| `MultiBacktest` | lib.py | Run multiple strategies/instruments and aggregate results |
| `FractionalBacktest` | lib.py | Backtest variant supporting fractional share sizes |

## Configuration

No config files. All configuration is passed as constructor parameters:

- `Backtest(data, strategy, cash, commission, margin, trade_on_close, hedging, exclusive_orders)`
- `bt.optimize(maximize, method, max_tries, constraint, return_heatmap, return_optimization, random_state)`

## File Tree

```
backtesting.py/
├── backtesting/
│   ├── __init__.py          # Package exports
│   ├── backtesting.py       # Core engine (~1750 lines)
│   ├── _util.py             # Internal utilities (~340 lines)
│   ├── _stats.py            # Statistics computation (~210 lines)
│   ├── _plotting.py         # Bokeh visualization (~785 lines)
│   ├── lib.py               # Public helpers & composable strategies (~650 lines)
│   ├── autoscale_cb.js      # Bokeh custom JS callback
│   └── test/
│       ├── __init__.py      # Test data exports: GOOG, EURUSD, BTCUSD, SMA
│       ├── __main__.py      # Test runner entry point
│       ├── _test.py         # Comprehensive unittest suite
│       ├── GOOG.csv         # Daily data 2004-2013
│       ├── EURUSD.csv       # Hourly data 2017-2018
│       └── BTCUSD.csv       # Monthly data 2012-2024
├── doc/
│   ├── build.sh             # pdoc3 build script
│   ├── examples/            # Jupyter notebook tutorials
│   └── pdoc_template/       # Custom pdoc styling
├── .ai/
│   ├── rules/               # AI behavioral rules
│   └── workflows/           # AI operational workflows
├── .github/workflows/
│   ├── ci.yml               # Lint → coverage → build → docs → win64
│   └── deploy-docs.yml      # Documentation deployment
├── data_vault/
│   ├── __init__.py          # Package exports: DataVault
│   ├── data_vault.py        # Core class: config, cache, fetch, normalize
│   ├── rate_limiter.py      # YFRateLimiter for yfinance rate limiting
│   └── tests/
│       └── test_data_vault.py  # 24 tests: config, cache, normalization, rate limiter
├── docs/
│   ├── specs/data/
│   │   └── data-vault-spec.md  # DataVault specification (IMPLEMENTED)
│   └── refs/data/
│       └── data-vault-ref.md   # DataVault operational reference
├── requirements-backtest.txt # DataVault dependencies
├── .env.example              # DataVault env var template
├── AGENTS.md                # AI Architectural Manifesto
├── PROJECT_SUMMARY.md       # This file
├── README.md                # Quick start & features
├── CONTRIBUTING.md           # Dev guidelines, testing, PR process
├── CHANGELOG.md             # Version history
├── LICENSE.md               # AGPL-3.0
├── setup.py                 # setuptools config
├── pyproject.toml           # ruff linting config
├── requirements.txt         # Test dependencies
├── setup.cfg                # Package metadata
└── MANIFEST.in              # sdist includes
```

## Guardrails Summary

See `.ai/rules/` for full details:

- **Architecture:** Respect module dependency direction; no circular imports
- **Testing:** TDD for logic changes; unittest framework; run `python -m backtesting.test`
- **Code hygiene:** No print() debugging; no commented-out code; no TODO/FIXME in commits
- **Public API:** Changes to exports from `backtesting` or `backtesting.lib` are breaking changes
- **Security:** No `eval()` on user data; validate OHLCV inputs at system boundary
- **Governance:** Keep AGENTS.md and PROJECT_SUMMARY.md in sync with architecture changes
