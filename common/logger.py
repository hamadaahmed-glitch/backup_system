"""
Unified Logging Service.
Configures synchronized console and file-based logging
with timestamping and formatting.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str,
    log_dir: Optional[Path] = None,
    log_file: Optional[str] = None,
    level: int = logging.INFO,
    console_output: bool = True,
) -> logging.Logger:
    """
    Creates and configures a Python standard logger.

    Args:
        name: Name of the logger instance.
        log_dir: Directory where log files are written.
        log_file: Specific log filename.
        level: Logging verbosity level (default: INFO).
        console_output: Whether to duplicate messages to stdout/stderr.

    Returns:
        Configured logging.Logger object.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is called repeatedly
    if logger.handlers:
        return logger

    log_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File Logging
    if log_dir and log_file:
        resolved_log_dir = Path(log_dir).resolve()
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        file_path = resolved_log_dir / log_file

        file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)

    # Console Logging
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        # Simplified console format
        console_format = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    return logger