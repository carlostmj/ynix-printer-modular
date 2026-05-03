from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class QrRenderResult:
    layer: Image.Image
    mask: Image.Image


def _is_transparent_color(value: object) -> bool:
    return str(value or "").strip().lower() in {"", "none", "transparent"}


def render_qrcode_layer(
    data: str,
    size: tuple[int, int],
    stroke: int = 0,
    fill: int | None = None,
    module_scale: int = 1,
) -> QrRenderResult:
    """Render a standards-compliant QR code into a grayscale layer and mask."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    width, height = max(1, int(size[0])), max(1, int(size[1]))
    text = data if data else "YNIX"
    module_scale = max(1, int(module_scale))

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=module_scale,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    cells = len(matrix)
    cell = max(1, min(width, height) // cells)
    qr_size = cells * cell
    offset_x = max(0, (width - qr_size) // 2)
    offset_y = max(0, (height - qr_size) // 2)

    background = 255 if fill is None else fill
    layer = Image.new("L", (width, height), background)
    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(layer)
    mask_draw = ImageDraw.Draw(mask)

    if fill is not None:
        mask_draw.rectangle((offset_x, offset_y, offset_x + qr_size - 1, offset_y + qr_size - 1), fill=1)

    for row, line in enumerate(matrix):
        top = offset_y + row * cell
        bottom = top + cell - 1
        for col, enabled in enumerate(line):
            if not enabled:
                continue
            left = offset_x + col * cell
            right = left + cell - 1
            rect = (left, top, right, bottom)
            draw.rectangle(rect, fill=stroke)
            mask_draw.rectangle(rect, fill=1)

    return QrRenderResult(layer=layer, mask=mask)


def normalize_qr_fill(fill_color: object, color_to_mono) -> int | None:
    if _is_transparent_color(fill_color):
        return None
    return color_to_mono(str(fill_color), 255)
