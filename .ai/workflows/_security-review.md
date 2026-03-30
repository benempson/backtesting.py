---
description: Shared adversarial security review protocol (Rule 13). Referenced by implement-spec, update-spec, fix-bug, and new-func workflows.
type: include
---

# ADVERSARIAL SECURITY REVIEW (RULE 13)

This file is an **include** — it is referenced by other workflows, not invoked directly.

---

## Protocol

1. **Persona Switch:** Activate Rule 13 ("The Red Team").
2. **Scope:**
   - **Inline Mode:** Review the code written in this session.
   - **Orchestrator Mode:** Review ALL files modified across ALL Implementor agents. Security review is never delegated to sub-agents — they see only their slice; the review needs the full picture.
3. **Challenge:** Attempt to construct a theoretical exploit against the changes made:
   - *Check:* Did we use `eval()`, `exec()`, or `compile()` on any user-supplied value?
   - *Check:* Are user-supplied file paths validated before use (e.g., plot output filenames)?
   - *Check:* Could any new numeric parameter cause overflow, division-by-zero, or inf/nan propagation?
   - *Check:* Are OHLCV data inputs validated at the Backtest boundary?
   - *Check:* Could any new feature exhaust memory or CPU with crafted inputs?
4. **Output:**
   - If Secure: `"Security Review Passed: [Reason]"`
   - If Vulnerable: `"VULNERABILITY FOUND: [Description]. Fixing now..."` → **Loop back to Implementation.**
