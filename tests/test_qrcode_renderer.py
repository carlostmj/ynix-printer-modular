from ynix_printer_modular.core.qrcode_renderer import render_qrcode_layer


def _count_dark(image) -> int:
    histogram = image.convert("L").histogram()
    return sum(histogram[:32])


def _count_mask(mask) -> int:
    histogram = mask.convert("L").histogram()
    return sum(histogram[1:])


def test_qrcode_renderer_creates_real_masked_modules() -> None:
    rendered = render_qrcode_layer("https://tracker.ynix.com.br", (240, 240), stroke=0, fill=None)

    assert rendered.layer.size == (240, 240)
    assert rendered.mask.size == (240, 240)
    assert _count_dark(rendered.layer) > 0
    assert _count_mask(rendered.mask) == _count_dark(rendered.layer)


def test_qrcode_renderer_can_keep_white_quiet_zone() -> None:
    transparent = render_qrcode_layer("YNIX", (240, 240), stroke=0, fill=None)
    filled = render_qrcode_layer("YNIX", (240, 240), stroke=0, fill=255)

    assert _count_mask(filled.mask) > _count_mask(transparent.mask)
