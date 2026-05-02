from __future__ import annotations

from PIL import Image

from thermal_label_app.printing import send_raw
from thermal_label_app.tspl import build_tspl


class TsplAdapter:
    def send_raw(self, printer_name: str, payload: bytes) -> str:
        return send_raw(printer_name, payload)

    def build_bitmap(self, img: Image.Image, width_mm: float, height_mm: float, **kwargs) -> bytes:
        return build_tspl(img, width_mm, height_mm, **kwargs)
