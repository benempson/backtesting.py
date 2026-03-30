# ARCHITECTURAL CONSTITUTION

You are working on the `backtesting.py` project.
Your primary source of truth is the file `AGENTS.md` located in the project root.

## CRITICAL INSTRUCTION
Before generating any code or answering any architectural question, you MUST:
1. Read `AGENTS.md`.
2. Read `AGENT.local.md` if it exists (private per-session notes).
3. Verify that your proposed solution respects the module dependency direction defined in `AGENTS.md`.
4. If you are modifying `backtesting.py`, `lib.py`, or any internal module (`_util.py`, `_stats.py`, `_plotting.py`), explicitly state which architectural rule applies to your change.

FAILURE TO COMPLY with `AGENTS.md` will result in rejected code.

---

## MANIFESTO ETHOS & OBJECTIVES

`AGENTS.md` is not a passive technical reference — it is the **AI Architectural Manifesto**: the prime directive that governs every decision made in this codebase. `PROJECT_SUMMARY.md` is its companion: the living record of the current architecture and file tree.

**Both files exist to serve the same objective: ensure that every AI session — regardless of context — produces work of the same architectural quality as if a Principal Engineer were reviewing it.**

The following principles are the foundation of that objective. They are not optional:

### 1. The Source of Truth is Always Read First
No task begins without reading `AGENTS.md` → `AGENT.local.md` → `.ai/rules/` → `PROJECT_SUMMARY.md` in that order. This is non-negotiable. An AI that skips this step is operating blind.

### 2. Every Task Has a Defined Workflow
There are no "freestyle" implementations. All code-writing tasks — bugs, features, refactors — are governed by a named workflow in `.ai/workflows/`. The workflow exists to enforce correctness, testing, security, and documentation in the right order. Bypassing it bypasses all of those safeguards simultaneously.

### 3. Simplicity is the Prime Directive
backtesting.py is a lightweight library. The flat module structure, minimal dependencies, and small public API surface are **intentional** design choices. A change that adds complexity (new modules, new dependencies, new abstraction layers) must justify itself against the existing simplicity. When in doubt, do less.

### 4. Tests Are Assets, Not Overhead
A test that is deleted to make a build pass is not a solution — it is a regression waiting to happen with no early warning system. Tests, once passing, are permanent. The TDD mandate exists not for ceremony but because bugs caught in red-first tests have a root cause; bugs caught in production do not.

### 5. The Manifesto Must Stay Current
`AGENTS.md` and `PROJECT_SUMMARY.md` are governance documents. When the architecture changes, they must change in the same commit. A stale manifesto is worse than no manifesto — it actively misleads future AI sessions. Section numbers must remain sequential after any edit.

### 6. Specs and References Are Companions
`docs/specs/` (build plans) and `docs/refs/` (operational references) are created in parallel and never replace each other. The spec is the "why and what"; the ref is the "where and how right now". Both are permanent once created.

---

## MODULE DEPENDENCY DIRECTION (INVIOLABLE)

```
lib.py  →  backtesting.py  →  _util.py
                            →  _stats.py
                            →  _plotting.py
```

- `_util.py`, `_stats.py`, and `_plotting.py` are internal modules. They do not import from `backtesting.py` or `lib.py` (except under `TYPE_CHECKING`).
- `backtesting.py` is the core engine. It imports from the internal modules but never from `lib.py`.
- `lib.py` is the public extension layer. It imports from the core and internal modules.
- `__init__.py` re-exports from all modules.

**Forbidden imports (examples):**
- `_util.py` importing from `backtesting.py` (circular dependency)
- `_stats.py` importing from `_plotting.py` (peer modules, no cross-dependency)
- `backtesting.py` importing from `lib.py` (core must not depend on extensions)

---

## PUBLIC API STABILITY

The public API is exported from two locations:

```python
from backtesting import Backtest, Strategy, Pool, set_bokeh_output
from backtesting.lib import crossover, cross, barssince, quantile, ...
```

Any change to these exports (renaming, removing, changing signatures) is a **breaking change**. Breaking changes require:
1. A CHANGELOG entry
2. A deprecation period (when feasible)
3. User confirmation before proceeding

---

## CONFIGURATION: CONSTRUCTOR PARAMETERS, NOT CONFIG FILES

backtesting.py has **no config files, no environment variables, no global state**. All configuration is passed via constructor parameters:

- `Backtest(data, strategy, cash, commission, margin, trade_on_close, hedging, exclusive_orders)`
- `bt.optimize(maximize, method, max_tries, constraint, ...)`

Do not introduce config files, `.env` loading, or global settings. If a new parameter is needed, add it to the relevant constructor.

---

## MANIFESTO MAINTENANCE PROTOCOL

When any of the following changes, update `AGENTS.md` and `PROJECT_SUMMARY.md` **in the same commit**:
- A new module is added to `backtesting/`
- A new public class or function is added to the API surface
- The dependency direction between modules changes
- A new dependency is added to `setup.py`
- The testing framework or CI pipeline changes
- A security or coding standard changes

After editing any numbered section in `AGENTS.md` or any rules file, verify that all section numbers remain sequential before committing.
