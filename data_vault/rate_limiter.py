"""YFRateLimiter — rolling-window rate limiter for yfinance API calls.

Enforces three rolling windows (per-minute, per-hour, per-day) to stay within
safe yfinance request limits.  Window state is persisted to a JSON counter file
so counts survive process restarts within the same window.

Vault-specific behavior (R7.3):
- **Per-minute:** Pause execution, display wait message, sleep until reset, resume.
- **Per-hour / Per-day:** Hard stop with ``sys.exit(1)``.

Adapted from ``TradingAgents/screener/yf_rate_limiter.py``.
"""

import datetime
import json
import logging
import os
import sys
import time

logger = logging.getLogger("data_vault")

# ── defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_LIMIT_PER_MIN: int = 100
_DEFAULT_LIMIT_PER_HOUR: int = 2000
_DEFAULT_LIMIT_PER_DAY: int = 48000

_WINDOW_DURATIONS: dict[str, datetime.timedelta] = {
    "minute": datetime.timedelta(minutes=1),
    "hour": datetime.timedelta(hours=1),
    "day": datetime.timedelta(days=1),
}


# ── main class ────────────────────────────────────────────────────────────────


class YFRateLimiter:
    """Rolling-window rate limiter for yfinance API calls.

    Reads limits from environment variables and persists window state to disk.
    Per-minute limit triggers a pause-and-resume; per-hour and per-day limits
    trigger a hard stop (``sys.exit(1)``).

    Args:
        counter_file: Path to the JSON state file. Falls back to
            ``{VAULT_DIR}/yf_rate_counters.json``.
    """

    def __init__(self, counter_file: str | None = None) -> None:
        vault_dir = os.environ.get("VAULT_DIR", "data_vault/")
        self._counter_file: str = counter_file or os.path.join(
            vault_dir, "yf_rate_counters.json"
        )

        self._limits: dict[str, int] = {
            "minute": int(os.environ.get("YF_LIMIT_PER_MIN", _DEFAULT_LIMIT_PER_MIN)),
            "hour": int(os.environ.get("YF_LIMIT_PER_HOUR", _DEFAULT_LIMIT_PER_HOUR)),
            "day": int(os.environ.get("YF_LIMIT_PER_DAY", _DEFAULT_LIMIT_PER_DAY)),
        }

        logger.info(
            "INFO|VAULT|YFRateLimiter initialised (limits: min=%d, hr=%d, day=%d)",
            self._limits["minute"], self._limits["hour"], self._limits["day"],
        )

        self._state: dict[str, dict] = self._load_state()

    # ── public API ────────────────────────────────────────────────────────────

    def check_and_increment(self) -> None:
        """Check all rolling windows and increment counters.

        - Per-minute limit: pauses execution until the window resets, then resumes.
        - Per-hour / per-day limit: hard stop with ``sys.exit(1)``.

        Call this before every yfinance request.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        self._reset_expired_windows(now)

        # Check all windows before incrementing (atomic check).
        for window in ("minute", "hour", "day"):
            count = self._state[window]["count"]
            limit = self._limits[window]
            if count >= limit:
                reset_at = self._state[window]["window_start"] + _WINDOW_DURATIONS[window]

                if window == "minute":
                    # Per-minute: pause and resume automatically.
                    wait_seconds = max(0, (reset_at - now).total_seconds())
                    logger.warning(
                        "WARN|VAULT|yfinance minute limit reached. "
                        "Waiting until %s...", reset_at.isoformat(),
                    )
                    time.sleep(wait_seconds)
                    # After sleeping, reset the minute window and re-check.
                    self._state["minute"] = {"count": 0, "window_start": reset_at}
                    self._save_state()
                    return self.check_and_increment()

                # Per-hour / per-day: hard stop.
                logger.error(
                    "ERROR|VAULT|yfinance %s limit reached (%d/%d). "
                    "Retry after %s.", window, count, limit, reset_at.isoformat(),
                )
                sys.exit(1)

        # All windows within limits — increment all counters.
        for window in ("minute", "hour", "day"):
            self._state[window]["count"] += 1

        self._save_state()

    # ── internals ─────────────────────────────────────────────────────────────

    def _reset_expired_windows(self, now: datetime.datetime) -> None:
        """Reset any window whose duration has elapsed."""
        for window, duration in _WINDOW_DURATIONS.items():
            window_start = self._state[window]["window_start"]
            if now - window_start >= duration:
                self._state[window] = {"count": 0, "window_start": now}

    def _load_state(self) -> dict[str, dict]:
        """Load window state from the counter file.

        Returns fresh state if the file is missing or corrupt.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        fresh = self._fresh_state(now)

        if not os.path.exists(self._counter_file):
            return fresh

        try:
            with open(self._counter_file, "r", encoding="utf-8") as fh:
                raw: dict = json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning("WARN|VAULT|yf_rate_counters.json corrupt, starting fresh")
            return fresh

        state: dict[str, dict] = {}
        for window in ("minute", "hour", "day"):
            if window not in raw:
                state[window] = {"count": 0, "window_start": now}
                continue
            try:
                count = int(raw[window]["count"])
                window_start = datetime.datetime.fromisoformat(raw[window]["window_start"])
                if window_start.tzinfo is None:
                    window_start = window_start.replace(tzinfo=datetime.timezone.utc)
                state[window] = {"count": count, "window_start": window_start}
            except (KeyError, ValueError, TypeError):
                state[window] = {"count": 0, "window_start": now}

        return state

    def _save_state(self) -> None:
        """Persist current window state atomically (write .tmp then replace)."""
        serialisable = {
            window: {
                "count": data["count"],
                "window_start": data["window_start"].isoformat(),
            }
            for window, data in self._state.items()
        }

        tmp_path = self._counter_file + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._counter_file) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(serialisable, fh, indent=2)
            os.replace(tmp_path, self._counter_file)
        except OSError as exc:
            logger.warning(
                "WARN|VAULT|Failed to persist rate counter state: %s", exc,
            )

    @staticmethod
    def _fresh_state(now: datetime.datetime) -> dict[str, dict]:
        """Return a zero-count state dict for all windows."""
        return {window: {"count": 0, "window_start": now} for window in _WINDOW_DURATIONS}
