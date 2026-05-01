from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelProfile:
    name: str
    width_mm: float
    height_mm: float
    dpi: int
    margin_mm: float = 2.0


PROFILES: tuple[LabelProfile, ...] = (
    LabelProfile("10x15", 100.0, 150.0, 203, 2.0),
    LabelProfile("A1", 594.0, 841.0, 300, 5.0),
    LabelProfile("A2", 420.0, 594.0, 300, 5.0),
    LabelProfile("A3", 297.0, 420.0, 300, 4.0),
    LabelProfile("A4", 210.0, 297.0, 300, 4.0),
    LabelProfile("A5", 148.0, 210.0, 300, 3.0),
)


def profile_names() -> list[str]:
    return [profile.name for profile in PROFILES]


def get_profile(name: str) -> LabelProfile:
    for profile in PROFILES:
        if profile.name == name:
            return profile
    raise KeyError(name)

