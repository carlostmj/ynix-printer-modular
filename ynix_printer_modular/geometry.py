from __future__ import annotations


def mm_to_px(mm: float, dpi: int) -> int:
    return max(1, round((mm / 25.4) * dpi))


def px_to_mm(px: int, dpi: int) -> float:
    return (px / dpi) * 25.4


def cm_to_px(cm: float, dpi: int) -> int:
    return mm_to_px(cm * 10.0, dpi)

