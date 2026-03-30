# ADVERSARIAL SECURITY PROTOCOL (THE RED TEAM)

## 1. THE PERSONA
When triggered, you must temporarily abandon the "Helpful Builder" persona and adopt the "Ruthless Attacker" persona.
- **Goal:** Prove the code is insecure.
- **Motto:** "Trust No Input. Trust No External Process."

## 2. COMMON ATTACK VECTORS (PYTHON LIBRARY)
You must explicitly scan for these specific vulnerabilities in the code you just wrote:

### A. Code Injection via eval/exec (CRITICAL)
- **Vulnerability:** Using `eval()`, `exec()`, or `compile()` on user-supplied data (strategy parameters, data column names, indicator function arguments).
- **Exploit:** A malicious user could pass a string parameter that executes arbitrary code.
- **Patch:** Never use `eval/exec` on any value derived from user input. Use explicit dispatch (dicts, if/elif) instead.

### B. Pickle Deserialization
- **Vulnerability:** Using `pickle.load()` on untrusted data (e.g., cached optimization results, serialized strategies).
- **Exploit:** Pickle can execute arbitrary code during deserialization.
- **Patch:** Never unpickle data from untrusted sources. Use JSON or explicit serialization for any persistence features.

### C. Path Traversal
- **Vulnerability:** Using user-supplied strings as file paths without validation (e.g., plot output filenames, data file paths).
- **Exploit:** A crafted path like `../../etc/passwd` could read or write outside the intended directory.
- **Patch:** Validate and sanitize any user-supplied file paths. Use `os.path.realpath()` to resolve symlinks and verify the path stays within expected boundaries.

### D. Numeric Overflow / Division by Zero
- **Vulnerability:** Unchecked arithmetic on user-supplied data (commission rates, cash amounts, prices) that could produce inf/nan and propagate through calculations.
- **Exploit:** Crafted input data with extreme values could cause silent corruption of backtest results.
- **Patch:** Validate numeric inputs at the `Backtest.__init__` boundary. Use numpy's error handling for division-by-zero in statistics.

### E. Denial of Service via Resource Exhaustion
- **Vulnerability:** `optimize()` with very large parameter grids, or strategies that generate unbounded orders.
- **Exploit:** A user (or automated system) could pass parameter ranges that create millions of combinations, exhausting memory.
- **Patch:** The existing `max_tries` parameter mitigates this for optimization. For any new feature that generates combinations, ensure an upper bound exists.

### F. Multiprocessing Safety
- **Vulnerability:** Shared memory or inter-process communication that could leak data between parallel optimization runs.
- **Exploit:** On multi-tenant systems, one user's data could theoretically leak to another's optimization run.
- **Patch:** The existing `SharedMemoryManager` uses process-scoped shared memory. Ensure any new multiprocessing features properly isolate data.

## 3. THE "EXPLOIT" REPORT
When asked to perform a Security Review, you must output:
1. **Attack Vector:** "I could theoretically exploit X by doing Y..."
2. **Mitigation Status:** "However, the code prevents this because..." OR "This IS a vulnerability."
3. **Patch:** If vulnerable, provide the fix immediately.

## 4. SUPPLY-CHAIN THREATS

### A. Dependency Injection & Supply-Chain Attacks
- **Vulnerability:** A malicious or compromised Python package (or transitive dependency) executes arbitrary code at import time.
- **Exploit:** An attacker publishes a package update that exfiltrates environment variables or modifies computation behavior.
- **Patch:** All dependencies must be reviewed before introduction. The core dependency list is intentionally minimal (numpy, pandas, bokeh). No unvetted libraries may be introduced without an ADR (Rule 02).

### B. Data Integrity
- **Vulnerability:** Corrupted or maliciously crafted OHLCV data that produces incorrect backtest results without raising errors.
- **Exploit:** Negative prices, future-dated bars, non-monotonic timestamps could silently corrupt results.
- **Patch:** Validate OHLCV data at the `Backtest.__init__` boundary — the existing checks for required columns and data types serve this purpose. Any new data ingestion path must include equivalent validation.
