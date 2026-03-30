---
description: Enforces TDD with a Human-in-the-Loop check for skipping tests.
---

# TDD Bug Fix

1.  **Analyze & Classify:**
    -   Analyze the user's request.
    -   **Root Cause Check:** Do you know *exactly* why the bug is happening based on the provided info?
        -   **If NO:** Do not guess. Stop. Ask for logs, tracebacks, or relevant code snippets.
    -   Consult `.ai/rules/09-testing-roi.md`.
    -   Determine if this is **Category A (Logic)** or **Category B (Config/Docs)**.

2.  **Instrumentation (The "Vision" Step):**
    -   **Check:** Is the bug logic obvious?
    -   **If NO:** Do not attempt a fix yet.
        -   **Action:** Read the suspect module carefully. Add temporary debug instrumentation if needed (e.g., assertions, print statements for local debugging only).
        -   **Instruction:** Ask the user to reproduce the issue with a minimal example and share the traceback.
        -   *Wait for user feedback.*
    -   **If YES:** Proceed to Step 3.

3.  **Scope Assessment & Complexity Routing:**
    -   **Complexity Assessment:** Follow the scoring protocol in `.ai/workflows/_complexity-assessment.md` (Section A). Evaluate the four dimensions (File Radius, Module Span, Independence, Research Load) and emit the visible output block (Section B).
    -   **Inline Mode (Score 0-1):**
        -   If 1-2 files: Skip the plan — proceed directly to Step 4. No `IMPLEMENTATION_PLAN` file is needed.
        -   If 3+ files but still Score 0-1: Create the plan file (see below) but execute inline (no sub-agents).
    -   **Orchestrator Mode (Score 2+):**
        -   The current session becomes the orchestrator. All implementation will be delegated to sub-agents per the Orchestrator Protocol (Section C of `_complexity-assessment.md`).
    -   **Plan File (for Score 1+ or Orchestrator Mode):**
        -   **Assign Change ID:** Generate a short descriptive kebab-case slug (2-4 words) derived from the bug description (e.g., `fix-sl-gap-handling`, `fix-nan-stats`).
        -   **Plan File:** Create `IMPLEMENTATION_PLAN-{change-id}.md` in the project root.
        -   **Header (CRITICAL):** The first lines MUST be:
            ```
            > Target: {description of the bug — one line}
            > Change ID: {change-id}
            > Routing: [Inline|Orchestrator] (Score N/4)
            ```
        -   **Checklist:** Break the fix into atomic steps (e.g., "- [ ] Write failing test", "- [ ] Fix NaN handling in compute_stats", "- [ ] Run regression suite").
        -   **Parallel Groups (Orchestrator Mode only):** Add a `## Parallel Groups` section per Section D of `_complexity-assessment.md`, mapping checklist items to file ownership groups.
    -   Proceed to Step 4.

4.  **The Fork:**
    -   **IF CATEGORY A:** Proceed to Step 5.
    -   **IF CATEGORY B:**
        -   Ask: *"This appears to be a Config/Docs change (Category B). I recommend skipping the test to save time. Proceed without testing? (Yes/No)"*
        -   **Wait** for user input.
        -   If "Yes": Go to Step 7 (Implement Fix).
        -   If "No": Proceed to Step 5 (Create Reproduction).

5.  **Create Reproduction (TDD):**
    -   **Mode Fork:**
        -   **Inline Mode:** Execute Steps 5-8 as written below (current behavior).
        -   **Orchestrator Mode:** Skip to Step 5b (Orchestrated Execution).
    -   **File Strategy:**
        1.  Identify the target module.
        2.  Locate the existing `TestCase` subclass in `backtesting/test/_test.py`.
        3.  Add the reproduction test method to that existing class.
        4.  If (and ONLY if) the test requires fundamentally different setup, create a new `TestCase` subclass.
    -   **Naming Constraint (CRITICAL):**
        -   New test methods MUST be named descriptively (e.g., `test_order_sl_with_gap`, `test_stats_empty_trades`).
        -   **STRICTLY FORBIDDEN:** `test_temp`, `test_repro`, `test_fix`.
    -   **Coding:** Write the failing test case.
    -   **Constraint:** The test MUST fail given the current bug.

5b. **Orchestrated Execution (Orchestrator Mode only):**
    -   Follow the Wave Execution Model from `.ai/workflows/_complexity-assessment.md` Section C.2:
        1.  **Research Wave:** Spawn 1-2 Scout agents to trace the bug across affected modules, identify all files needing changes, and locate existing test fixtures.
        2.  **Update Plan:** Using Scout results, finalize the `## Parallel Groups` section in the plan file.
        3.  **Execution Wave(s):** Spawn Implementor agents per the plan's parallel groups. Each Implementor writes the reproduction test FIRST, then the fix code. Follow the TDD Batching Protocol (Section E).
        4.  **Collect results:** Mark completed items `[x]` in the plan file after each wave.
    -   **After all waves complete:** Proceed to Step 8 (Final Verification) — the orchestrator runs the full test suite.
    -   **Skip Steps 6-7** — they are handled within each Implementor agent's execution.

6.  **Failure Analysis (The "False Positive" Check) [Inline Mode only]:**
    -   Run the test: `python -m unittest backtesting.test._test.TestClassName.test_method_name -v`
    -   **Analyze Output:**
        -   Is it a **Setup Error** (import errors, fixture misconfiguration)? -> **Loop Back:** Fix the test harness.
        -   Is it an **AssertionError** matching the bug? -> **Proceed:** Go to Step 7.
    -   **Constraint:** Do NOT implement the application fix until you have a clean `AssertionError` that matches the reported bug (Rule 08 "Clean Red" standard).

7.  **Implement Fix [Inline Mode only]:**
    -   Write the code to fix the bug.
    -   **If using a plan:** Mark the current checklist item `[x]` after each sub-task is verified.

8.  **Final Verification:**
    -   **Inline Mode:** Run the specific test to confirm it passes, then run the full suite: `python -m backtesting.test`.
    -   **Orchestrator Mode:** Run the full test suite: `python -m backtesting.test`. If any tests fail, identify which Implementor's work caused the failure and spawn a targeted fix agent.

9.  **Regression Check:**
    -   **Execute the full test suite** via the terminal (`python -m backtesting.test`) to ensure no regressions.
    -   **Constraint:** Do not mark the task as done until all tests pass.

10.  **Adversarial Security Review (Rule 13):**
    > Follow the protocol in `.ai/workflows/_security-review.md`.

11.  **Consolidation & Cleanup:**
    -   **Check:** Did you create any temporary debug instrumentation in Step 2?
    -   **Action:** Remove all temporary print() statements and debug assertions.
    -   **Constraint:** DO NOT remove production warnings (`warnings.warn`) that were part of the fix.
    -   **Plan removal:** If an `IMPLEMENTATION_PLAN-{change-id}.md` was created, delete it.

12.  **Spec Update:**
    -   **Analyze:** Did this bug fix change a fundamental business rule or data contract?
    -   **Decision:**
        -   **If NO (Implementation Fix):** Stop here unless a spec was mentioned by the user.
        -   **If YES (Requirement Change):** Identify the relevant spec file in `docs/specs/`. Suggest a change-id and spec path: *"This fix changed a business rule. I recommend running `/update-spec` on `docs/specs/[area]/[name]-spec.md` with change-id `fix-{description}` to record the revision. Shall I start that now?"*
