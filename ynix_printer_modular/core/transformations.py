from __future__ import annotations

from dataclasses import replace

from ynix_printer_modular.domain.models import Transform


def move(transform: Transform, dx: float, dy: float, *, snap: int = 0) -> Transform:
    x = transform.x + dx
    y = transform.y + dy
    if snap > 1:
        x = round(x / snap) * snap
        y = round(y / snap) * snap
    return replace(transform, x=x, y=y)


def resize(transform: Transform, dw: float, dh: float, *, min_size: float = 4.0, snap: int = 0) -> Transform:
    width = max(min_size, transform.width + dw)
    height = max(min_size, transform.height + dh)
    if snap > 1:
        width = max(min_size, round(width / snap) * snap)
        height = max(min_size, round(height / snap) * snap)
    return replace(transform, width=width, height=height)


def rotate(transform: Transform, degrees: float, *, snap_degrees: float = 0.0) -> Transform:
    value = transform.rotation + degrees
    if snap_degrees > 0:
        value = round(value / snap_degrees) * snap_degrees
    return replace(transform, rotation=value % 360)


def scale(transform: Transform, sx: float, sy: float | None = None) -> Transform:
    return replace(transform, scale_x=max(0.01, sx), scale_y=max(0.01, sx if sy is None else sy))
