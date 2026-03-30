---
description: Shared 5-category failure mode probe for spec drafting and updates. Referenced by draft-spec and update-spec workflows.
type: include
---

# UNHAPPY PATH PROBE (5-CATEGORY CHECKLIST)

This file is an **include** — it is referenced by other workflows, not invoked directly.

---

## Protocol

For any feature or change involving data processing, computation, optimization, or file I/O, walk through this 5-category checklist. For each category, explicitly ask what the fallback behavior or error response should be:

1. **Invalid input data** — empty DataFrame, missing OHLCV columns, NaN values, non-monotonic index, wrong dtypes.
2. **Numeric edge cases** — division by zero in statistics, negative prices, zero commission, cash exhausted, single-bar data.
3. **Optimization failures** — no valid parameter combinations, constraint excludes all candidates, optimizer convergence failure.
4. **Resource exhaustion** — very large datasets, massive parameter grids, multiprocessing on Windows (spawn vs fork).
5. **Visualization failures** — no trades to plot, empty indicator arrays, Bokeh version incompatibilities, headless environment (no browser).

**Constraint:** Do not proceed until every applicable category above has a defined fallback behavior. Do not accept "handle errors gracefully" as an answer — name the specific case, the trigger condition, the expected system response, and whether it requires a raised exception or a warning.
