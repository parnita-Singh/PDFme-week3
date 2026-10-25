from __future__ import annotations

from pathlib import Path

from pdftoolkit.inventory import inventory_pdf


def test_sample_banner_dpi_and_sizes(sample_pdf: Path) -> None:
    records = inventory_pdf(sample_pdf)
    assert len(records) == 2
    by_name = {r.image_name.lstrip("/"): r for r in records}

    bg = by_name["Im0"]
    fg = by_name["Im1"]
    assert bg.pixel_size == (3000, 3900)
    assert fg.pixel_size == (576, 576)
    assert bg.color_space in ("/DeviceRGB", "DeviceRGB")
    assert fg.has_transparency is False
    assert bg.compressed_bytes > 0
    assert fg.compressed_bytes > 0
    assert bg.effective_dpi_x is not None and abs(bg.effective_dpi_x - 352.94) < 1.0
    assert bg.effective_dpi_y is not None and abs(bg.effective_dpi_y - 354.55) < 1.0
    assert bg.effective_dpi is not None and abs(bg.effective_dpi - max(bg.effective_dpi_x, bg.effective_dpi_y)) < 0.01
    assert fg.effective_dpi is not None and abs(fg.effective_dpi - 288.0) < 1.0
