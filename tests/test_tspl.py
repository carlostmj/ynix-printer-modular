from PIL import Image

from ynix_printer_modular.tspl import build_tspl


def test_build_tspl_contains_expected_header_and_payload() -> None:
    image = Image.new("1", (8, 2), 255)
    payload = build_tspl(image, 10, 20, invert=True, speed=3, density=12)

    assert payload.startswith(b"SIZE 10.00 mm,20.00 mm\r\n")
    assert b"SPEED 3\r\n" in payload
    assert b"DENSITY 12\r\n" in payload
    assert b"BITMAP 0,0,1,2,0," in payload
    assert payload.endswith(b"\r\nPRINT 1,1\r\n")
