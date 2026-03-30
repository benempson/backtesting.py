# TESTING ROI & DECISION MATRIX

## THE "VALUE FOR MONEY" PROTOCOL
Before writing a test, assess the nature of the change. Testing is mandatory for Logic/State (Category A). For config or comment-only changes (Category B), you may skip testing **ONLY with human confirmation**.

## CATEGORY A: MANDATORY TDD (Risk: High)
**Trigger:** Any change that affects *how the system works*.
- **Core Engine Logic:** Changes to `_Broker` order processing, position accounting, trade settlement, SL/TP handling.
- **Data Integrity:** Indicator computation, statistics calculation, equity curve generation.
- **Control Flow:** Optimization loops, multiprocessing dispatch, strategy execution order.
- **Calculations:** Commission computation, margin handling, PnL calculation, drawdown analysis.
- **Edge Cases:** Empty data handling, single-bar data, NaN propagation, zero-volume bars.

*Action:* You MUST write a failing test (in `backtesting/test/_test.py`) before fixing.

## CATEGORY B: NO TEST CANDIDATE (Risk: Low)
**Trigger:** Any change that affects *metadata, comments, or non-logic config*.
- **Comments / Docstrings:** Updating docstrings, inline comments, type annotations with no logic change.
- **Config Defaults:** Tweaking default parameter values that don't affect logic.
- **Warnings:** Adding `warnings.warn()` calls for deprecations.
- **Rules/Docs:** Updating `.ai/rules/`, `AGENTS.md`, `PROJECT_SUMMARY.md`.

*Exclusion:* If a "config" change alters backtest behavior or output, it is **Category A**.

*Action:* Triggers the **Confirmation Protocol**.

## THE CONFIRMATION PROTOCOL (Human-in-the-Loop)
If you determine a task is **Category B**, you MUST NOT write code immediately. You must output:

> **"CLASSIFICATION: Category B (Config/Docs). I propose skipping tests for this change. Proceed? (Yes/No)"**

- **If User says "Yes":** Implement the fix immediately.
- **If User says "No":** Revert to Category A and write a test.
- **Override:** If the user explicitly prompts with "No test needed" or "Hotfix", you may bypass this confirmation.

## TEST PLACEMENT
- **Primary location:** `backtesting/test/_test.py` — the single comprehensive test module.
- **Add to existing TestCase subclass** when the test fits an existing group (e.g., `TestBacktest`, `TestLib`).
- **Create a new TestCase subclass** only when testing a genuinely distinct area that doesn't fit existing groups.

## REFACTORING & TYPE-CHECKING
- **mypy as Test:** When performing structural refactors (changing function signatures, module interfaces), the **mypy error** replaces the **Failing Test** for structural changes.
- **Protocol:**
    1. Change the type signature (break mypy).
    2. Fix the code (satisfy mypy).
    3. Run the suite (regression check).

## THE EXIT GATE (REGRESSION)
- **Mandate:** No Category A task is complete until **`python -m backtesting.test`** passes in full.
- **Category B:** Running the full suite is optional but recommended.

## TEST EXECUTION — ALWAYS USE BASH TOOL
Run all tests yourself via the Bash tool. **Never ask the user to run tests on your behalf.** This includes:
- Confirming the reproduction test fails
- Confirming the fix makes it pass
- Running the full regression suite

Use: `python -m unittest backtesting.test._test.TestClassName.test_method -v` and `python -m backtesting.test`
