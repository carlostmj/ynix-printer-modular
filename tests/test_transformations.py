from thermal_label_app.core.transformations import move, resize, rotate, scale
from thermal_label_app.domain.models import Transform


def test_move_with_snap() -> None:
    transform = Transform(1, 2, 100, 50)
    moved = move(transform, 14, 15, snap=8)
    assert moved.x == 16
    assert moved.y == 16


def test_resize_respects_minimum_and_snap() -> None:
    transform = Transform(0, 0, 10, 10)
    resized = resize(transform, -100, 13, min_size=4, snap=8)
    assert resized.width == 4
    assert resized.height == 24


def test_rotate_and_scale() -> None:
    transform = Transform(0, 0, 10, 10, rotation=350)
    assert rotate(transform, 20).rotation == 10
    scaled = scale(transform, 2, 0.5)
    assert scaled.scale_x == 2
    assert scaled.scale_y == 0.5
