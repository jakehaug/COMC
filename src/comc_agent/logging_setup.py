"""Structured logging to both console and rotating file."""
from __future__ import annotations

import logging
import logging.handlers

from rich.logging import RichHandler

from .config import settings


def configure(level: int = logging.INFO) -> logging.Logger:
    settings.runtime.ensure_dirs()
    logger = logging.getLogger("comc_agent")
    if logger.handlers:
        return logger
    logger.setLevel(level)

    console = RichHandler(rich_tracebacks=True, show_path=False, markup=False)
    console.setLevel(level)
    logger.addHandler(console)

    fh = logging.handlers.RotatingFileHandler(
        settings.runtime.logs_dir / "agent.log",
        maxBytes=2_000_000,
        backupCount=5,
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    fh.setLevel(level)
    logger.addHandler(fh)
    logger.propagate = False
    return logger


log = configure()
