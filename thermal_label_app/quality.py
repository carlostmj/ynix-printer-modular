from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintQuality:
    label: str
    speed: int
    density: int


QUALITIES: tuple[PrintQuality, ...] = (
    PrintQuality("Rápida", speed=6, density=8),
    PrintQuality("Normal", speed=4, density=10),
    PrintQuality("Alta", speed=3, density=12),
    PrintQuality("Máxima", speed=2, density=14),
)


def quality_names() -> list[str]:
    return [quality.label for quality in QUALITIES]


def get_quality(label: str) -> PrintQuality:
    for quality in QUALITIES:
        if quality.label == label:
            return quality
    return QUALITIES[1]

