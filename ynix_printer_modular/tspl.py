from __future__ import annotations

from PIL import Image


def build_tspl(
    img: Image.Image,
    width_mm: float,
    height_mm: float,
    *,
    gap_mm: float = 2.0,
    invert: bool = True,
    speed: int = 4,
    density: int = 10,
) -> bytes:
    mono = img.convert("1")
    width_px, height_px = mono.size
    bytes_per_row = (width_px + 7) // 8
    pixels = mono.load()
    data = bytearray()

    for y in range(height_px):
        for xb in range(bytes_per_row):
            byte = 0
            for bit in range(8):
                x = xb * 8 + bit
                if x >= width_px:
                    continue
                should_print = (pixels[x, y] != 0) if invert else (pixels[x, y] == 0)
                if should_print:
                    byte |= 1 << (7 - bit)
            data.append(byte)

    header = (
        f"SIZE {width_mm:.2f} mm,{height_mm:.2f} mm\r\n"
        f"GAP {gap_mm:.2f} mm,0\r\n"
        f"SPEED {speed}\r\n"
        f"DENSITY {density}\r\n"
        "DIRECTION 1\r\n"
        "REFERENCE 0,0\r\n"
        "CLS\r\n"
        f"BITMAP 0,0,{bytes_per_row},{height_px},0,"
    ).encode("ascii")
    return header + bytes(data) + b"\r\nPRINT 1,1\r\n"
