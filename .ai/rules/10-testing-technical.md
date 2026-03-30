# TECHNICAL TESTING STANDARDS

## 1. TEST STRUCTURE & NAMING
### THE STABILITY MANDATE
Tests must not break because of incidental changes (default parameter values, warning messages, output formatting). Target stable, behavioral assertions.

### TEST CLASS NAMING
- Use `unittest.TestCase` subclasses with descriptive names:
    - *Good:* `TestBacktest`, `TestLib`, `TestOptimize`, `TestPlotting`
    - *Bad:* `Test1`, `TestMisc`

### TEST METHOD NAMING
- Name test methods descriptively:
    - *Good:* `test_order_with_stop_loss`, `test_optimize_constraint_function`, `test_crossover_with_nan`
    - *Bad:* `test_1`, `test_bug_fix`

## 2. FILE CONVENTION
- **Primary test file:** `backtesting/test/_test.py` — all tests go here unless there is a compelling reason to split.
- **Test data:** `backtesting/test/__init__.py` exports `GOOG`, `EURUSD`, `BTCUSD`, `SMA` for use in tests.
- **Helper strategies:** Define test strategy subclasses at module level in `_test.py` (e.g., `SmaCross`, `_S`).

## 3. TEST DATA PATTERNS
### STANDARD DATASETS
```python
from backtesting.test import GOOG, EURUSD, BTCUSD, SMA

SHORT_DATA = GOOG.iloc[:20]  # Short data for fast tests with no indicator lag
```

- **GOOG:** Daily data 2004-2013 (default for most tests)
- **EURUSD:** Hourly data 2017-2018 (for multi-timeframe tests)
- **BTCUSD:** Monthly data 2012-2024 (for long-horizon tests)

### ASSERTIONS
- Use `self.assertEqual`, `self.assertAlmostEqual`, `self.assertTrue`, `self.assertRaises`.
- For DataFrame comparisons, use `pandas.testing.assert_frame_equal`.
- For numeric comparisons with floating-point tolerance, use `self.assertAlmostEqual` or numpy's `np.testing.assert_allclose`.

## 4. TEST PATTERNS IN THIS PROJECT
### STANDARD BACKTEST TEST
```python
def test_feature_name(self):
    bt = Backtest(GOOG, SmaCross)
    stats = bt.run()
    self.assertEqual(stats['# Trades'], expected_value)
```

### TESTING EXCEPTIONS
```python
def test_invalid_data_raises(self):
    with self.assertRaises(ValueError):
        Backtest(pd.DataFrame(), SmaCross)
```

### TESTING OPTIMIZATION
```python
def test_optimize_constraint(self):
    bt = Backtest(GOOG, SmaCross)
    stats = bt.optimize(fast=range(5, 20), slow=range(20, 40),
                        constraint=lambda p: p.fast < p.slow)
    self.assertGreater(stats['# Trades'], 0)
```

### TESTING WITH TEMPORARY FILES (PLOTTING)
```python
def test_plot_output(self):
    bt = Backtest(GOOG, SmaCross)
    bt.run()
    with _tempfile() as f:
        bt.plot(filename=f, open_browser=False)
        self.assertTrue(os.path.exists(f))
```

## 5. TEST LOCATION HIERARCHY (THE "COLOCATION" MANDATE)
### PRIORITY 1: EXISTING TEST CLASS
- **Rule:** When adding a test case, place it in the existing relevant `TestCase` subclass in `_test.py` first.
- **Reasoning:** Splitting tests fragments the domain knowledge. Keep related tests together.

### PRIORITY 2: NEW TEST CLASS
- **Trigger:** You may ONLY create a new `TestCase` subclass if:
    1. The existing classes don't cover the area being tested.
    2. The test requires fundamentally different setup/teardown.
- **Protocol:** Name it architecturally: `TestMultiBacktest`, `TestFractionalBacktest`, never `TestBugFix`.

### THE "LOGIC PERSISTENCE" RULE
- **Forbidden:** You are strictly forbidden from deleting a valid test case once it passes.
- **Consolidation:** If you created a separate test for debugging, merge it into the main test class before marking the task done.

## 6. ASSERTION PRECISION
When testing numerical results, **never** use bare `self.assertTrue(result)`. These tests are **Category A** and must assert specific values:

```python
# BAD — does not catch regressions
self.assertTrue(stats['# Trades'] > 0)

# GOOD — catches exact regression
self.assertEqual(stats['# Trades'], 93)
```

**Exception:** When the exact value is non-deterministic (e.g., stochastic optimization), use range checks with `self.assertGreater` / `self.assertLess`.

## 7. THE "BORN PERMANENT" PROTOCOL (ALL FILE TYPES)
- **Scope:** Applies to test files, source modules, and utilities.
- **Creation:** Never create a file intended to be deleted later. Name it correctly from the start.
    - *Bad:* `test_bug.py`, `test_temp.py`
    - *Good:* A new `TestCase` subclass within `_test.py`
- **Refactoring Artifacts:** If you create a "reproduction" test, you must be prepared to keep it forever. Name it accordingly.

## 8. PERFORMANCE AWARENESS
The full test suite runs in <0.3 seconds. Keep it that way.
- Do not add tests that call `bt.optimize()` with large parameter grids.
- Use `SHORT_DATA` (20 rows) for tests that don't need full price history.
- If a test must be slow (e.g., testing multiprocessing), mark it clearly with a comment.
