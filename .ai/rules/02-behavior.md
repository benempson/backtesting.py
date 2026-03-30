# AI BEHAVIORAL PROTOCOLS

## MAJOR CHANGES (ADR REQUIREMENT)
If you suggest a change that involves:
1. Adding a new library/dependency to `setup.py`.
2. Changing the module structure (e.g., splitting a module, adding a new sub-package).
3. Refactoring a file larger than 300 lines.
4. Changing the public API surface (adding, removing, or renaming exports).

**YOU MUST STOP** and write a short "Architecture Decision Record" (ADR) justification first.
- List Pros/Cons.
- Explain why the current pattern in `AGENTS.md` is insufficient.
- Wait for user approval before generating code.

### ADR: [Short title]
**Decision:** [What you propose to do]
**Reason current pattern is insufficient:** [Specific constraint or failure mode]
**Pros:** [Bullet list]
**Cons / risks:** [Bullet list]
**Alternatives considered:** [What else was evaluated]

## REFACTORING
If you see "Spaghetti Code" or a file violating the Single Responsibility Principle:
- Do not just patch the bug.
- Propose a refactor to split the logic (e.g., "This section of backtesting.py is doing too much — can I extract the order-processing logic into a separate internal module?").

## CODE HYGIENE (THE "CLEAN SLATE" RULE)
### 1. NO "JUST IN CASE" COMMENTS
- **Rule:** When refactoring or fixing bugs, **DELETE** the old code. Do not comment it out.
- **Reasoning:** Commented-out code causes context pollution and confuses future AI requests.
- **Safety:** We rely on Git and IDE Undo/Redo for version history, not the file content.

### 2. DESTRUCTIVE REFACTORING
- If you change a strategy (e.g., swapping a computation approach), **overwrite** the previous implementation completely.
- Do not leave "Legacy" or "Old Way" blocks.

### 3. CLEANUP PROTOCOL (PRINT VS WARNINGS)
- **Trash:** `print()` statements used for ad-hoc debugging.
    - **Action:** MUST be deleted before finishing a task. These are for your temporary use only.
- **Treasure:** `warnings.warn()` calls for user-facing deprecation notices and runtime warnings.
    - **Action:** MUST be preserved — they are part of the public API contract.

## DOCUMENTATION & COMMENTING STANDARDS
### 1. THE "WHY," NOT THE "WHAT"
- **Forbidden:** Redundant comments that describe syntax (e.g., `i = 0  # set i to zero`).
- **Required:** Comments that explain **Business Logic**, **Edge Cases**, or **Architectural Decisions**.
    - *Good:* `# SL/TP orders must be reprocessed on the same bar they're created to handle gaps.`
    - *Good:* `# Use itertuples over a column subset for ~3x speedup on large DataFrames.`
- **AI Context:** Write comments assuming that a *future AI session* will read them to understand the *intent* of the code.

### 2. DOCSTRINGS FOR EXPORTS
- All public functions, classes, and modules MUST have a docstring.
- Docstrings must be pdoc3-compatible markdown.
- Briefly explain what the function does, its parameters, and return value.
- *Example:*
    ```python
    def crossover(series1, series2) -> bool:
        """
        Return `True` if `series1` just crossed over (above) `series2`.

            >>> crossover(self.sma1, self.sma2)
        """
    ```

### 3. VISUAL ORGANIZATION
- In files larger than 100 lines, use comment separators to group logic.
    - `# ── helpers ──────────────────────────────────────────────────────────────────`
    - `# ── order processing ────────────────────────────────────────────────────────`

## 4. NO MAGIC STRINGS (CONSTANTS)
### THE PROTOCOL
- **Definition:** A "Magic String" is any string literal used in logic comparisons, state updates, or configuration (e.g., `'Open'`, `'Close'`, `'buy'`).
- **Rule:** Magic strings are **STRONGLY DISCOURAGED** in business logic. Use module-level constants or existing patterns.

### IMPLEMENTATION
1. **Column names:** Follow the existing `OHLCV_AGG` pattern — column names ('Open', 'High', 'Low', 'Close', 'Volume') are well-established and documented. These are acceptable as-is.
2. **Order types/sides:** Follow existing internal patterns (e.g., `copysign` for long/short).
3. **New constants:** If introducing a new string used in comparisons, define it as a module-level constant.

## 5. THE "ANTI-ASSUMPTION" PROTOCOL
- **The Prime Rule:** If a requirement is ambiguous, you are **STRICTLY FORBIDDEN** from guessing.
- **The "Gap Analysis" Check:** Before generating any plan or code, ask yourself: *"Do I have 100% of the information required to execute this?"*
    - *If No:* Stop. List the missing pieces. Ask the user.
- **Specific Triggers (Stop & Ask):**
    - **Logic:** "What should happen if the data has gaps?" "Is this field optional?" "What about zero-volume bars?"
    - **Data:** "What format is the input data in?" "Does this work with non-daily timeframes?"
    - **API:** "Does this change the public API? Is a deprecation period needed?"

### MANDATORY STOP-AND-ASK TRIGGERS
Before writing any implementation code for a new feature or change that affects the public API, you MUST ask these questions. If the answer is unknown, **STOP** and ask the user:

**Trigger 1 — Edge Case Coverage:**
> *"What should happen with edge cases? I need to know the expected behavior for: empty data, single-row data, NaN values in OHLCV, zero-volume bars, and any instrument-specific quirks relevant to this feature."*

You may only proceed once each edge case has a defined behavior.

**Trigger 2 — API Surface Impact:**
If a change adds, removes, or modifies a public function/class/parameter:
> *"Does this change the public API? Is backward compatibility required? Should there be a deprecation period?"*

Do not proceed until the API impact is confirmed and the approach is agreed.

- **Layered Coverage Rule:** When updating a workflow file, proactively review the corresponding `.ai/rules/` files for the same topic. Workflow files govern *process*; rules files govern *always-active behaviour*. A gap in one often signals a gap in the other.
- **The "Assumption" Label:** If you must make a minor technical assumption, you must explicitly state it:
    > "Assumption: The input DataFrame always has a DatetimeIndex. Correct?"

## 6. DESTRUCTIVE ACTION PROTOCOL (FILE DELETION)
- **The Rule:** Before issuing a file deletion, you MUST output a specific text block in the chat:

    > **DELETION REQUEST**
    > **File:** `backtesting/full/path/to/file.py`
    > **Reason:** [e.g., "Logic merged into _util.py"]
    > **Status:** [e.g., "Safe to delete (verified merged)"]

- **Timing:** Output this text *immediately before* invoking the tool.

## 7. PRODUCTION-READY MANDATE
All code produced in any workflow is production-ready by default. There are no "placeholder" commits.
- No `print()` debug statements (use `warnings.warn()` for user-facing messages only).
- No `TODO` / `FIXME` comments left in place.
- No empty `except` blocks — every `except` must handle the error appropriately.
- No hardcoded file paths or platform-specific assumptions without guards.
- No `type: ignore` annotations without a comment explaining why.

## 8. WORKFLOW FIRST
Never write implementation code without first invoking the appropriate workflow from `.ai/workflows/`. Reading a file, analysing architecture, or asking a clarifying question does not require a workflow. Writing code does.

## 9. REPLACE_ALL IDEMPOTENCY CHECK
Before using `replace_all` (or any bulk find-and-replace), verify that `new_string` does NOT contain `old_string` as a substring.
- **The hazard:** If `new_string` embeds `old_string`, a second invocation will produce double-prefixes and corrupt every occurrence in the file.
- **The check:** Before issuing the call, ask: *"If this replacement were applied twice, would the result still be correct?"*

## 10. FILE RENAME PROTOCOL
When renaming a tracked file in the repo, always use `git mv` (via `Bash` tool), not a plain file system move. Plain `mv` causes Git to see an untracked add + a deleted file, which loses history.

```bash
git mv backtesting/old_name.py backtesting/new_name.py
```

After the rename, update all imports and references and commit everything in one pass.

## 11. SPEC VS IMPLEMENTATION TRUST HIERARCHY
When the spec and the actual implementation file disagree, **the implementation file is the ground truth**. Do not write plans or code based on what the spec says happened — verify against the live file first.
- **Before planning any change:** read the actual file, not just the spec.
- **When a divergence is found:** flag it explicitly to the user ("The spec says X but the actual file does Y — I'll base my plan on the file").
