from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass(frozen=True)
class RenderSettings:
    width_px: int
    height_px: int
    margin_px: int
    offset_x_px: int
    offset_y_px: int
    fit_mode: str
    auto_rotate: bool
    scale_x_percent: int = 100
    scale_y_percent: int = 100
    scale_uniform_percent: int = 100
    rotation_degrees: int = 0
    crop_left_percent: int = 0
    crop_right_percent: int = 0
    crop_top_percent: int = 0
    crop_bottom_percent: int = 0


@dataclass(frozen=True)
class FitResult:
    image: Image.Image
    content_box: tuple[int, int, int, int]


def fit_image_with_meta(src: Image.Image, settings: RenderSettings) -> FitResult:
    src = src.convert("1")
    crop_left = max(0, min(95, settings.crop_left_percent))
    crop_right = max(0, min(95, settings.crop_right_percent))
    crop_top = max(0, min(95, settings.crop_top_percent))
    crop_bottom = max(0, min(95, settings.crop_bottom_percent))
    left = round(src.width * crop_left / 100)
    right = round(src.width * (1 - crop_right / 100))
    top = round(src.height * crop_top / 100)
    bottom = round(src.height * (1 - crop_bottom / 100))
    if right > left and bottom > top:
        src = src.crop((left, top, right, bottom))

    target_w = max(1, settings.width_px - 2 * settings.margin_px)
    target_h = max(1, settings.height_px - 2 * settings.margin_px)

    if settings.auto_rotate:
        original_ratio = min(target_w / src.width, target_h / src.height)
        rotated_ratio = min(target_w / src.height, target_h / src.width)
        if rotated_ratio > original_ratio:
            src = src.rotate(90, expand=True)

    angle = settings.rotation_degrees % 360
    if angle:
        src = src.rotate(-angle, expand=True, fillcolor=255)

    if settings.fit_mode == "cover":
        ratio = max(target_w / src.width, target_h / src.height)
    else:
        ratio = min(target_w / src.width, target_h / src.height)

    scale_x = max(1, settings.scale_x_percent) / 100.0
    scale_y = max(1, settings.scale_y_percent) / 100.0
    scale_uniform = max(1, settings.scale_uniform_percent) / 100.0
    new_w = max(1, round(src.width * ratio * scale_x * scale_uniform))
    new_h = max(1, round(src.height * ratio * scale_y * scale_uniform))
    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("1", (settings.width_px, settings.height_px), 255)
    x = (settings.width_px - new_w) // 2 + settings.offset_x_px
    y = (settings.height_px - new_h) // 2 + settings.offset_y_px
    canvas.paste(resized, (x, y))
    return FitResult(canvas, (x, y, x + new_w, y + new_h))


def fit_image(src: Image.Image, settings: RenderSettings) -> Image.Image:
    return fit_image_with_meta(src, settings).image


def open_mono(path: Path) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path))
    if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, rgba)
    return img.convert("L").convert("1")
