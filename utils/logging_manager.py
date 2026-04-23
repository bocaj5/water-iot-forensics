"""
Logging management utilities for both nodes.
Provides consistent logging across the system.
"""

import logging
import sys
from typing import Optional


def get_logger(name: str, level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually module name)
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file to write logs to

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Set level
    level_num = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level_num)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level_num)

    # Formatter with timestamp
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    # Add console handler
    if not logger.handlers:
        logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level_num)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def configure_root_logger(level: str = "INFO", log_file: Optional[str] = None):
    """
    Configure root logger for entire application.

    Args:
        level: Logging level
        log_file: Optional file to write logs to
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
