---
description: Reads an implemented spec and its source code to generate a high-density operational reference document in docs/refs/.
---

# WORKFLOW: GENERATE OPERATIONAL REFERENCE

## 1. SELECT TARGET

- **Check for Pre-specified Target:** If a spec file path was provided in the user's prompt:
    1. Verify the file exists at the specified path. If not, report the error and **STOP**.
    2. Read the file and proceed directly to Source Discovery below.
- **Interactive Discovery (no path provided):** List all `.md` files within `docs/specs/` sub-directories.
- **Gate:** The selected spec MUST have `**Status:** IMPLEMENTED`. If not, **STOP** — only implemented features have operational references.
- **Context Lock:** Read the selected spec in full.
- **Source Discovery:** Identify all source files referenced in the spec (modules, classes, functions, tests). Read each file to capture the current implementation truth — the spec may have drifted.

## 2. EXTRACT & SYNTHESIZE

From the spec AND the actual source code, extract the following categories. When the spec and source code conflict, **source code wins**.

### a) System Constants
- Module-level constants (name + purpose + default value + which module defines it)
- Default parameter values for `Backtest` and `Strategy` constructors
- Numeric thresholds and precision values

### b) Data Model
- Class hierarchy: Strategy → user subclass, Backtest → _Broker → Order/Position/Trade
- Key data structures: `_Indicator`, `_Data`, indicator arrays
- Data flow: OHLCV DataFrame → _Data wrapper → Strategy.next() → Order → Trade

### c) Module Architecture
- Module paths + one-line purpose for each key file
- Key class/function signatures (name + parameters + return type)
- Inter-module dependencies: which modules import from which

### d) Configuration Reference
- All constructor parameters consumed by `Backtest` (name + type + default + effect)
- All constructor parameters consumed by `optimize()` (name + type + default + effect)

### e) Test Coverage
- Test class names + test method count per class
- Key test scenarios (what is being verified per test method)
- Test data used (GOOG, EURUSD, BTCUSD)

### f) Security Considerations
- Attack vectors + risk level + mitigation (from spec if present, verified against source)

### g) Known Edge Cases & Debugging Notes
- Extracted from spec revision root-cause sections
- Platform-specific quirks (Windows multiprocessing, Bokeh version compatibility, etc.)

## 3. GENERATE REFERENCE DOCUMENT

- **Template:** Use the standardized template at `docs/specs/templates/operational-ref.md` (if it exists).
- **Path:** Save to `docs/refs/[area]/[name]-ref.md`, mirroring the spec's sub-directory structure.
  - Example: `docs/specs/core/order-processing-spec.md` -> `docs/refs/core/order-processing-ref.md`
- **Create directories** if `docs/refs/` or its sub-directories don't exist yet.
- **Constraint:** The reference must be self-contained — a maintainer should be able to understand the feature's operational surface without reading the original spec.

## 4. CROSS-REFERENCE UPDATE

- Add the new ref doc path to `PROJECT_SUMMARY.md` file tree (under a `docs/refs/` section).

## 5. VERIFY

- **Source alignment:** Confirm all function signatures and parameter defaults match the current source files.
- **Spec <-> Ref consistency:** Compare constants and edge cases in the squashed spec against those in the ref. Any item present in one but absent from the other is a gap — resolve before completing.
- **Root-cause transfer:** If the squashed spec has any Change History entries annotated `-> see ref`, confirm each one appears in this ref's Edge Cases section.
- **Output:** "Reference generated: `docs/refs/[area]/[name]-ref.md` — [section count] sections, [line count] lines."
