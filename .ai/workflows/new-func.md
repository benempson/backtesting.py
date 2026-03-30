---
description: Implements new functionality with strict architectural alignment, mandatory testing, and explicit user approval.
---

# New Feature Implementation

1.  **Analysis & Strategy Formulation:**
    -   **Analyze Request:** Re-state the requirement to ensure understanding.
    -   **Gap Analysis (Rule 02):** Are there any ambiguities regarding which module is affected, edge cases, or error handling?
        -   **Action:** If yes, ask clarifying questions now. Do not propose a plan yet.
    -   **Rule Check:** Consult `AGENTS.md`. Identify which modules need modification.
    -   **Module Impact Check (Rule 02):** Does this change cross module boundaries? Confirm dependency direction is clean (lib.py → backtesting.py → _util/_stats/_plotting).
    -   **API Impact Check:** Does this add to the public API surface? If so, confirm with user.
    -   **ROI Check:** Consult `.ai/rules/09-testing-roi.md`.
        -   Determine: **Category A (Logic/Flow)** or **Category B (Config/Docs)**.
    -   **Test Strategy:** If Category A, define *where* the test will live (which `TestCase` subclass in `backtesting/test/_test.py`) and *what* the key assertions will be.

2.  **The Proposal:**
    -   **Action:** Present a concise plan to the user containing:
        1.  **Requirement:** "I understand you want to..."
        2.  **Classification:** "Category [A/B] (Testing [Required/Optional])"
        3.  **Architecture:** "I will modify `[File A]`, add method to `[Class B]`..."
        4.  **Test Plan:** "I will test `[Scenario]` in `TestClassName` in `backtesting/test/_test.py`."
    -   **Conditional Gate:** If the gap analysis in Step 1 found ambiguities or conflicts, ask: *"Does this plan align with your intent? (Yes/No)"* and **STOP** for confirmation. If no ambiguities were found, emit the plan and proceed — the user can still interject with changes.

3.  **Implementation (Code & Test):**
    -   **Action:** Write the source code following the module conventions in `AGENTS.md`.
    -   **Constraint (Validation):** If this involves external data or user parameters, you MUST validate at the system boundary (Backtest.__init__ or Strategy._check_params).
    -   **Constraint (Warnings):** Use `warnings.warn()` for user-facing messages. Follow existing warning patterns.
    -   **Constraint:** Ensure strict module separation — internal helpers stay in `_util.py`, statistics in `_stats.py`, visualization in `_plotting.py`, public helpers in `lib.py`.
    -   **Action:** Write/Update the corresponding test (if Category A).

4.  **Verification:**
    -   **IF CATEGORY A:** Run `python -m unittest backtesting.test._test.TestClassName -v`. Confirm it passes.
    -   **IF CATEGORY B:** Confirm the config change has the expected effect.

5.  **Adversarial Security Review (Rule 13):**
    > Follow the protocol in `.ai/workflows/_security-review.md`.

6.  **Regression Check:**
    -   **Execute the full test suite** via the terminal (`python -m backtesting.test`) to ensure no regressions.
    -   **Constraint:** Do not mark the task as done until all tests pass.

7.  **Governance & Cleanup:**
    -   **Documentation:** Read `.ai/rules/99-governance.md`.
        -   Ask: *"Since we added a new feature, should I update `PROJECT_SUMMARY.md` to keep the context fresh?"*
    -   **API Surface:** If a new public function/class was added, update `AGENTS.md` to document it.
