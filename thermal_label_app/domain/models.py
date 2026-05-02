from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanvasSpec:
    width_mm: float
    height_mm: float
    dpi: int

    @property
    def width_px(self) -> int:
        return max(1, round((self.width_mm / 25.4) * self.dpi))

    @property
    def height_px(self) -> int:
        return max(1, round((self.height_mm / 25.4) * self.dpi))


@dataclass(frozen=True)
class PrintConfig:
    printer_name: str
    output_mode: str
    quality: str
    invert: bool = False


@dataclass(frozen=True)
class Transform:
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
