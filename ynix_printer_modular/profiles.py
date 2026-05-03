from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabelProfile:
    name: str
    width_mm: float
    height_mm: float
    dpi: int
    margin_mm: float = 2.0


CONFIG_DIR = Path.home() / ".config" / "ynix-printer-modular"
CUSTOM_PROFILES_FILE = CONFIG_DIR / "profiles.json"


PROFILES: tuple[LabelProfile, ...] = (
    LabelProfile("10x15", 100.0, 150.0, 203, 2.0),
    LabelProfile("A1", 594.0, 841.0, 300, 5.0),
    LabelProfile("A2", 420.0, 594.0, 300, 5.0),
    LabelProfile("A3", 297.0, 420.0, 300, 4.0),
    LabelProfile("A4", 210.0, 297.0, 300, 4.0),
    LabelProfile("A5", 148.0, 210.0, 300, 3.0),
)


def _profile_from_dict(data: dict) -> LabelProfile | None:
    try:
        name = str(data["name"]).strip()
        width_mm = float(data["width_mm"])
        height_mm = float(data["height_mm"])
        dpi = int(data["dpi"])
        margin_mm = float(data.get("margin_mm", 2.0))
    except (KeyError, TypeError, ValueError):
        return None
    if not name or width_mm <= 0 or height_mm <= 0 or dpi <= 0 or margin_mm < 0:
        return None
    return LabelProfile(name, width_mm, height_mm, dpi, margin_mm)


def load_custom_profiles() -> list[LabelProfile]:
    if not CUSTOM_PROFILES_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    profiles = []
    builtin_names = {profile.name for profile in PROFILES}
    for item in data:
        if not isinstance(item, dict):
            continue
        profile = _profile_from_dict(item)
        if profile and profile.name not in builtin_names:
            profiles.append(profile)
    return profiles


def save_custom_profile(profile: LabelProfile) -> None:
    if is_builtin_profile(profile.name):
        raise ValueError("Perfis padrao nao podem ser sobrescritos")
    profiles = [item for item in load_custom_profiles() if item.name != profile.name]
    profiles.append(profile)
    profiles.sort(key=lambda item: item.name.lower())
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": item.name,
            "width_mm": item.width_mm,
            "height_mm": item.height_mm,
            "dpi": item.dpi,
            "margin_mm": item.margin_mm,
        }
        for item in profiles
    ]
    CUSTOM_PROFILES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def delete_custom_profile(name: str) -> bool:
    profiles = load_custom_profiles()
    kept = [profile for profile in profiles if profile.name != name]
    if len(kept) == len(profiles):
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "name": item.name,
            "width_mm": item.width_mm,
            "height_mm": item.height_mm,
            "dpi": item.dpi,
            "margin_mm": item.margin_mm,
        }
        for item in kept
    ]
    CUSTOM_PROFILES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def is_builtin_profile(name: str) -> bool:
    return any(profile.name == name for profile in PROFILES)


def all_profiles() -> list[LabelProfile]:
    return [*PROFILES, *load_custom_profiles()]


def profile_names() -> list[str]:
    return [profile.name for profile in all_profiles()]


def get_profile(name: str) -> LabelProfile:
    for profile in all_profiles():
        if profile.name == name:
            return profile
    raise KeyError(name)
