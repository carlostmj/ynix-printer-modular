from __future__ import annotations

import logging
from pathlib import Path


LOG_DIR = Path.home() / ".config" / "ynix-printer-modular" / "logs"
LOG_FILE = LOG_DIR / "app.log"


def get_logger(name: str = "ynix") -> logging.Logger:
    logger = logging.getLogger(f"ynix.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
