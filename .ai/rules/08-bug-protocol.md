# BUG FIXING PROTOCOL (STRICT ENFORCEMENT)

## THE TRIGGER
Whenever the user asks you to "fix a bug," "solve an issue," or "repair code," you must enter **TDD MODE**.

## THE ALGORITHM
You are STRICTLY FORBIDDEN from generating the fix immediately. You must follow this sequence:

1. **Phase 1: Analysis**
    - Identify the file causing the bug.
    - Identify the existing test class in `backtesting/test/_test.py` (or propose adding a new `TestCase` subclass if the area is untested).

2. **Phase 2: The Reproduction (STOP HERE)**
    - Write a *failing test case* that reproduces the bug.
    - **STOP.** Run `python -m backtesting.test` to confirm it fails (or run the specific test class).

3. **Phase 3: The Fix**
    - Only AFTER confirming the test failed, generate the code fix.

4. **Phase 4: The Verification**
    - Run the test again to confirm it passes.

## EXCEPTION
If the user explicitly types "HOTFIX" or "SKIP TEST", you may bypass this protocol. Otherwise, it is mandatory.

## THE "VALID FAILURE" STANDARD (CLEAN RED)
In TDD, a failing test allows you to proceed ONLY if it fails for the right reason.

### CRITERIA
- **Valid Failure (Proceed):** An **AssertionError** where the logic ran but produced the wrong output (e.g., `AssertionError: Expected 3 trades, got 2`).
- **Invalid Failure (Stop):** A **Setup/Import Error** (e.g., `ModuleNotFoundError`, `AttributeError`, fixture misconfiguration).

### PROTOCOL
- If the test fails due to setup/import issues, you **MUST NOT** touch the application code.
- **Action:** Fix the test harness first.
- **Gate:** You may only move to the "Fix" phase when you have a clean `AssertionError` that matches the reported bug behavior.

## RUNNING TESTS

### Single Test Class
```bash
python -m unittest backtesting.test._test.TestBacktest.test_method_name -v
```

### Full Suite
```bash
python -m backtesting.test
```

### With Coverage
```bash
coverage run -m backtesting.test && coverage report
```
