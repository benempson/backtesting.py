---
description: Safely executes structural refactors using type-checker-driven development.
---

# Structural Refactor

1.  **Impact Analysis:**
    -   **Identify Target:** Which function signature, class, or data structure is changing?
    -   **Radius Check:** Briefly search (grep) to see how many files will break.
    -   **Safety Check:** If this is a massive change (>20 references), ask user: *"This will affect [N] locations. Proceed?"*
    -   **ADR Gate (Rule 02):** If refactoring a file >300 lines or changing the module structure, write an Architecture Decision Record and wait for user approval before generating code.
    -   **API Check:** If this changes anything exported from `backtesting` or `backtesting.lib`, confirm backward compatibility approach with user.

2.  **Type-First Implementation (The "Red" State):**
    -   **Action:** Modify the source of truth first (e.g., a function signature, a class interface, a data structure).
    -   **Constraint:** Do NOT fix the usage sites yet. Apply only the structural change.
    -   **For Python structural refactors:** Run `mypy backtesting/` to enumerate all breakages — the mypy errors replace the failing test as the "red" state.
    -   **Acknowledgment:** Explicitly state: *"Types/signatures updated. mypy is now broken. This counts as the 'Failing State'."*

3.  **The Fix Loop (Type-Checker-Driven):**
    -   **Iterate:** Go through the broken files (source AND test files).
    -   **Action:** Update the code to match the new structure.
    -   **Constraint:** Do not change business logic behavior unless forced by the structure. Keep functionality equivalent.
    -   **Internal references:** Update all internal callers within `backtesting/`.
    -   **Test references:** Update test code in `backtesting/test/_test.py` to match new signatures.

4.  **Verification (The "Green" State):**
    -   **Type Check:** Run `mypy backtesting/` — verify no new `type: ignore` annotations were added to bypass errors.
    -   **Lint Check:** Run `flake8 backtesting/` — verify no new lint violations.
    -   **Test Run:** Run `python -m backtesting.test` — the suite should pass with the new structure.

5.  **Documentation:**
    -   **Spec Drift:** If this changed a data shape or interface defined in a spec, ask to update it.
    -   **AGENTS.md:** If this changed the module structure or public API, update `AGENTS.md`.
    -   **Docstrings:** Update pdoc3-compatible docstrings for any changed public API.
