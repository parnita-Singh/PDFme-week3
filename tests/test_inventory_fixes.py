"""Tests for the inventory fixes: identity-based placements, repeated forms,
inline images, pattern images, cycles and transform order."""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Dictionary, Name, Pdf, Stream

from pdftoolkit.inventory import _mat_mul, apply_matrix, inventory_pdf
from _builders import add_page, form_xobject, gradient_image, image_xobject, jpeg_bytes, save


def _by_object(records):
    return {r.object_gen: r for r in records if not r.is_inline}


def test_page_image_and_form_image_with_same_name_stay_separate(tmp_path: Path) -> None:
    pdf = Pdf.new()
    form_img = image_xobject(pdf, jpeg_bytes(gradient_image(100, 100)), 100, 100)
    page_img = image_xobject(pdf, jpeg_bytes(gradient_image(900, 900)), 900, 900)
    form = form_xobject(pdf, b"q 50 0 0 50 0 0 cm /Im0 Do Q", {"/Im0": form_img})
    add_page(
        pdf,
        b"q 300 0 0 300 0 0 cm /Im0 Do Q q 1 0 0 1 400 0 cm /F Do Q",
        {"/Im0": page_img, "/F": form},
    )
    path = save(pdf, tmp_path / "collide.pdf")

    records = inventory_pdf(path)
    assert len(records) == 2, "page image and form image must both be listed"
    by_px = {r.width_px: r for r in records}
    assert by_px[900].effective_dpi == 900 / (300 / 72)  # 216 dpi
    assert by_px[100].effective_dpi == 100 / (50 / 72)  # 144 dpi


def test_form_drawn_twice_records_both_placements(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(100, 100)), 100, 100)
    form = form_xobject(pdf, b"q 50 0 0 50 0 0 cm /Im0 Do Q", {"/Im0": img})
    add_page(
        pdf,
        b"q 1 0 0 1 0 0 cm /F Do Q q 2 0 0 2 0 0 cm /F Do Q",
        {"/F": form},
    )
    path = save(pdf, tmp_path / "twice.pdf")

    (record,) = inventory_pdf(path)
    widths = sorted(p.width_pts for p in record.placements)
    assert widths == [50.0, 100.0], "both uses of the form must be recorded"
    assert record.placed_width_pts == 100.0  # largest placement is reported
    assert record.effective_dpi == 100 / (100 / 72)  # 72 dpi


def test_self_drawing_form_does_not_recurse_forever(tmp_path: Path) -> None:
    pdf = Pdf.new()
    form = form_xobject(pdf, b"q /F Do Q", {})
    form[Name.Resources] = Dictionary(XObject=Dictionary({"/F": form}))
    add_page(pdf, b"q /F Do Q", {"/F": form})
    path = save(pdf, tmp_path / "cycle.pdf")

    assert inventory_pdf(path) == []  # returns, and finds no images


def test_inline_image_is_reported_not_dropped(tmp_path: Path) -> None:
    pdf = Pdf.new()
    content = (
        b"q 100 0 0 100 0 0 cm BI /W 2 /H 2 /BPC 8 /CS /RGB /F /AHx ID "
        b"00ff00 ff0000 0000ff ffffff> EI Q"
    )
    add_page(pdf, content)
    path = save(pdf, tmp_path / "inline.pdf")

    (record,) = inventory_pdf(path)
    assert record.is_inline is True
    assert record.object_gen is None
    assert record.width_px == 2 and record.height_px == 2
    assert record.effective_dpi == 2 / (100 / 72)
    assert record.note and "inline" in record.note


def test_image_inside_pattern_is_reported_with_note(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(50, 50)), 50, 50)
    pattern = Stream(pdf, b"q 20 0 0 20 0 0 cm /Im0 Do Q")
    pattern[Name.PatternType] = 1
    pattern[Name.PaintType] = 1
    pattern[Name.TilingType] = 1
    pattern[Name.BBox] = pikepdf.Array([0, 0, 20, 20])
    pattern[Name.XStep] = 20
    pattern[Name.YStep] = 20
    pattern[Name.Resources] = Dictionary(XObject=Dictionary({"/Im0": img}))
    add_page(
        pdf,
        b"/Pattern cs /P1 scn 0 0 100 100 re f",
        patterns={"/P1": pattern},
    )
    path = save(pdf, tmp_path / "pattern.pdf")

    records = inventory_pdf(path)
    assert len(records) == 1
    assert records[0].note and "pattern" in records[0].note
    assert records[0].effective_dpi is None


def test_nested_transform_order_is_pdf_order() -> None:
    # Outer translate by (100, 0), then an inner scale by 2.
    # PDF applies the inner scale first, so (1, 0) -> (2, 0) -> (102, 0).
    translate = (1.0, 0.0, 0.0, 1.0, 100.0, 0.0)
    scale = (2.0, 0.0, 0.0, 2.0, 0.0, 0.0)
    combined = _mat_mul(translate, scale)
    assert apply_matrix(combined, 1.0, 0.0) == (102.0, 0.0)


def test_unplaced_page_image_is_listed_with_note(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(40, 40)), 40, 40)
    add_page(pdf, b"0 0 m 10 10 l S", {"/Im0": img})
    path = save(pdf, tmp_path / "unused.pdf")

    (record,) = inventory_pdf(path)
    assert record.effective_dpi is None
    assert record.note and "not drawn" in record.note