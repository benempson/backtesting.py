"""Logging configuration for the data_vault package.

Sets up the ``data_vault`` logger with:
- A ``RotatingFileHandler`` (max size and backup count from env vars).
- A ``StreamHandler`` (console output).

Call ``setup_logging()`` once at startup before any other data_vault imports.
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging() -> None:
    """Configure the ``data_vault`` logger with file + console handlers."""
    log_dir = os.environ.get("VAULT_LOG_DIR", "logs/")
    max_bytes = int(os.environ.get("VAULT_LOG_MAX_BYTES", 1_048_576))
    backup_count = int(os.environ.get("VAULT_LOG_BACKUP_COUNT", 6))
    log_file = os.path.join(log_dir, "data_vault.log")

    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("data_vault")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls.
    if logger.handlers:
        return

    formatter = logging.Formatter(
        fmt="{asctime} {levelname}|VAULT|{message}",
        style="{",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler.
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
