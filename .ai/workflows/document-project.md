---
description: Scans the codebase to generate a comprehensive architectural summary and file tree.
usage: /document-project
---

# Generate Project Documentation

1.  **Context Gathering (The Stack):**
    -   Read `setup.py` and `pyproject.toml` to identify:
        -   Python version and package name.
        -   Key dependencies (numpy, pandas, bokeh).
        -   Test framework (unittest).
        -   Linting tools (flake8, ruff, mypy).

2.  **Context Gathering (The Rules):**
    -   Read `AGENTS.md` to capture enforced architectural patterns (module dependency direction, API stability, etc.).
    -   Read `.ai/rules/00-architecture.md` to catch any active meta-rules.

3.  **Structure Mapping:**
    -   Generate a file tree of the `backtesting/` directory, `doc/` directory, and project root.
    -   **Constraint:** Limit depth to 3 levels to keep it readable.
    -   **Constraint:** Ignore `__pycache__`, `.git`, `.ai`, `*.egg-info`.
    -   *Goal:* Visualize the module organization and test structure.

4.  **Deep Dive: The Core Architecture:**
    -   Read `backtesting/backtesting.py` to summarize the core classes (Strategy, Backtest, _Broker, Order, Position, Trade).
    -   Read `backtesting/lib.py` to summarize the public helper functions and composable strategies.
    -   Read `backtesting/_util.py` to summarize internal utilities.
    -   Read `backtesting/_stats.py` to summarize the statistics system.
    -   Read `backtesting/_plotting.py` to summarize the visualization system.

5.  **Synthesis & Output:**
    -   Compile all findings into a Markdown report titled `PROJECT_SUMMARY.md`.
    -   **Required Sections:**
        1.  **Project Overview:** Name, purpose, and core stack.
        2.  **Architecture:** Explanation of the flat module structure and dependency direction.
        3.  **Key Classes:** Strategy, Backtest, Order, Position, Trade and their relationships.
        4.  **Public API:** Exports from `backtesting` and `backtesting.lib`.
        5.  **Configuration:** Constructor parameters (no config files).
        6.  **Guardrails:** Summary of the rules in `AGENTS.md`.
        7.  **File Tree:** The generated directory structure.
    -   **Action:** Save this file to the project root.
    -   **Action:** Print the content of the summary to the chat window.
