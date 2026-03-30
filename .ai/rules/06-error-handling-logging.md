# ERROR HANDLING & WARNINGS PROTOCOL

## 1. WARNING STANDARDS
- **FORBIDDEN:** Do not use `print()` for error communication in production code.
- **REQUIRED:** Use Python's `warnings` module for user-facing messages:
    ```python
    import warnings
    warnings.warn("Message to the user", category=RuntimeWarning, stacklevel=2)
    ```
- **Deprecations:** Use `DeprecationWarning` or `FutureWarning` for API changes:
    ```python
    warnings.warn(
        "`old_param` is deprecated; use `new_param` instead.",
        DeprecationWarning, stacklevel=2
    )
    ```
- **Context:** Include actionable information in warnings — what went wrong and what the user should do about it.

## 2. UNHAPPY PATH PRE-PLANNING MANDATE
Before implementing any feature or change that involves data processing, optimization, or external interactions (file I/O, multiprocessing), you MUST enumerate its failure modes. This is a design step, not an afterthought.

For each failure mode, define:
1. **Trigger condition** — what causes this failure? (e.g., "empty DataFrame passed to Backtest", "optimize() called with no parameter ranges", "indicator returns all NaN")
2. **Response** — what does the library do? (e.g., raise ValueError with message, warn and return default, skip silently)
3. **User message** — what error/warning does the user see?

**Forbidden:** Implementing a feature's happy path and leaving error handling as a TODO. Unhappy paths must be scoped before the first line of code is written.

## 3. STRUCTURED ERROR MESSAGES
- **Never swallow errors silently** — every failure must produce either a raised exception or a warning.
- **Mechanisms:**
    - For invalid input data: raise `ValueError` with a message describing what's wrong and what's expected.
    - For missing optional dependencies: raise `ImportError` with the pip install command.
    - For configuration errors: raise at `Backtest.__init__` time, not during `run()`.
    - For numeric edge cases (division by zero, empty series): return `np.nan` or an appropriate default with a comment explaining why.
- **Forbidden:** Empty `except` blocks, bare `except: pass`, or returning `None` silently when the caller will not expect it.

## 4. EXCEPTION HIERARCHY
Follow the existing patterns in the codebase:
- `ValueError` — Invalid parameters or data (most common)
- `AttributeError` — Missing strategy parameters (with close-match suggestions)
- `TypeError` — Wrong argument types
- `ImportError` — Missing optional dependencies (sambo, tqdm, matplotlib)
- `RuntimeWarning` — Non-fatal issues during backtesting (e.g., multiprocessing on Windows)

Do not introduce custom exception classes without an ADR (Rule 02). The stdlib exceptions are sufficient for a library of this scope.

## 5. THE "NO SILENT CATCH" RULE
- **Forbidden:** Empty or swallowed `except` blocks that discard the error.
    - *Bad:* `except Exception: pass`
    - *Bad:* `except Exception as e: print(e)`
- **Required:** Every `except` block must:
    1. Either re-raise, return a structured error to the caller, or provide documented fallback behavior.
    2. If catching for a fallback (like optional dependency imports), use the narrowest exception type possible.
- **Existing pattern to follow:**
    ```python
    # From _util.py — graceful fallback for optional dependency
    try:
        from tqdm.auto import tqdm as _tqdm
        _tqdm = partial(_tqdm, leave=False)
    except ImportError:
        def _tqdm(seq, **_):
            return seq
    ```

## 6. VALIDATION AT BOUNDARIES
- **Input validation** belongs in `Backtest.__init__()` and `Strategy._check_params()` — catch bad data early.
- **Numeric validation** (NaN handling, empty series) belongs in the computation functions (`_stats.py`, `lib.py`).
- **Do not validate** internal data passed between private methods within the same module — trust the internal contract.
