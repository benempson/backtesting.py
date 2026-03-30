---
description: Review and update architectural guardrails
usage: type /review-rules
---

# Architectural Review

1.  **Read Context:** Read `AGENTS.md` and all files in `.ai/rules/`.
2.  **Scan Codebase:** Briefly scan `backtesting/` (especially `backtesting.py`, `lib.py`, `_util.py`) for recent patterns that deviate from these rules.
3.  **Report:**
    - Are there any rules being consistently ignored?
    - Are there any new patterns (like a new helper function or strategy base class) that aren't documented?
    - Is `AGENTS.md` still accurate regarding the module structure and public API?
4.  **Propose Updates:** List recommended edits to the rule files to bring them in sync with reality.
