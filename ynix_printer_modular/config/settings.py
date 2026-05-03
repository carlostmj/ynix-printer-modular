from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CONFIG_DIR = Path.home() / ".config" / "ynix-printer-modular"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class AppSettings:
    last_printer: str = ""
    last_project: str = ""
    last_output_mode: str = "Térmica TSPL"
    preferences: dict[str, Any] = field(default_factory=lambda: {"snap_enabled": False, "grid_size": 8})


def load_settings() -> AppSettings:
    if not SETTINGS_FILE.exists():
        return AppSettings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(data, dict):
        return AppSettings()
    return AppSettings(
        last_printer=str(data.get("last_printer", "")),
        last_project=str(data.get("last_project", "")),
        last_output_mode=str(data.get("last_output_mode", "Térmica TSPL")),
        preferences=dict(data.get("preferences", {})),
    )


def save_settings(settings: AppSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
