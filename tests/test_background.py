"""Tests for background removal (rembg). The first run downloads the model once."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageDraw
from pikepdf import Name

from _builders import add_page, image_xobject, jpeg_bytes, save
from pdftoolkit.background import parse_fill, remove_background
from pdftoolkit.inventory import inventory_pdf


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def subject_image(size: int = 400) -> Image.Image:
    """A red circle on a blue background: the background should be removed, the circle kept."""
    img = Image.new("RGB", (size, size), (30, 80, 200))
    ImageDraw.Draw(img).ellipse([size // 4, size // 4, 3 * size // 4, 3 * size // 4], fill=(230, 40, 40))
    return img


def make_subject_pdf(path: Path) -> Path:
    """One page: a 2-inch subject image in the middle of the page."""
    pdf = pikepdf.Pdf.new()
    img = subject_image()
    xobj = image_xobject(pdf, jpeg_bytes(img, 95), img.width, img.height)
    add_page(pdf, b"q 144 0 0 144 234 324 cm /Im1 Do Q", xobjects={"/Im1": xobj})
    return save(pdf, path)


def make_mixed_pdf(path: Path) -> Path:
    """One page: a full-page photo (/Im0) and a subject image (/Im1)."""
    pdf = pikepdf.Pdf.new()
    full = Image.new("RGB", (800, 1000), (120, 140, 90))
    bg = image_xobject(pdf, jpeg_bytes(full, 95), 800, 1000)
    subject = subject_image()
    fg = image_xobject(pdf, jpeg_bytes(subject, 95), subject.width, subject.height)
    add_page(
        pdf,
        b"q 612 0 0 792 0 0 cm /Im0 Do Q q 144 0 0 144 234 324 cm /Im1 Do Q",
        xobjects={"/Im0": bg, "/Im1": fg},
    )
    return save(pdf, path)


def make_vector_pdf(path: Path) -> Path:
    """One page with a filled full-page rectangle (a vector background) and no images."""
    pdf = pikepdf.Pdf.new()
    add_page(pdf, b"0.2 0.4 0.8 rg 0 0 612 792 re f 1 0 0 rg 100 100 50 50 re f")
    return save(pdf, path)


def make_transparent_pdf(path: Path) -> Path:
    """One page with an image that already has an SMask."""
    pdf = pikepdf.Pdf.new()
    img = subject_image()
    smask = pdf.make_stream(bytes([255]) * (img.width * img.height))
    smask[Name.Type] = Name.XObject
    smask[Name.Subtype] = Name.Image
    smask[Name.Width], smask[Name.Height] = img.width, img.height
    smask[Name.ColorSpace] = Name.DeviceGray
    smask[Name.BitsPerComponent] = 8
    xobj = image_xobject(pdf, jpeg_bytes(img, 95), img.width, img.height, SMask=smask)
    add_page(pdf, b"q 144 0 0 144 234 324 cm /Im1 Do Q", xobjects={"/Im1": xobj})
    return save(pdf, path)


def alpha_of(pdf_path: Path, page_number: int = 1, name: str = "/Im1") -> Image.Image:
    with pikepdf.open(pdf_path) as pdf:
        obj = pdf.pages[page_number - 1].Resources.XObject[name]
        return pikepdf.PdfImage(obj.SMask).as_pil_image().convert("L")


def row_for(report: dict, name: str) -> dict:
    return next(r for r in report["images"] if r["image"] == name)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

def test_background_becomes_transparent_and_subject_stays_opaque(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    out = tmp_path / "out.pdf"

    report = remove_background(src, out)

    assert report["ok"] is True
    assert row_for(report, "/Im1")["action"] == "processed"
    alpha = alpha_of(out)
    w, h = alpha.size
    corners = [alpha.getpixel((x, y)) for x, y in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
    centre = alpha.getpixel((w // 2, h // 2))
    assert max(corners) < 32, corners
    assert centre > 223, centre


def test_processed_images_have_an_smask(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    out = tmp_path / "out.pdf"

    remove_background(src, out)

    with pikepdf.open(out) as pdf:
        assert "/SMask" in pdf.pages[0].Resources.XObject["/Im1"]


def test_placements_and_page_count_are_unchanged(tmp_path):
    src = make_mixed_pdf(tmp_path / "mixed.pdf")
    out = tmp_path / "out.pdf"

    report = remove_background(src, out)

    assert report["placements_changed_pages"] == []
    before = sorted(tuple(p.ctm) for r in inventory_pdf(src) for p in r.placements)
    after = sorted(tuple(p.ctm) for r in inventory_pdf(out) for p in r.placements)
    assert before == after
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


def test_full_page_background_is_not_processed_by_default(tmp_path):
    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    report = remove_background(src, tmp_path / "out.pdf")

    bg = row_for(report, "/Im0")
    assert bg["action"] == "not_processed"
    assert "covers" in bg["reason"]
    assert row_for(report, "/Im1")["action"] == "processed"


def test_selected_images_process_exactly_those(tmp_path):
    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    report = remove_background(src, tmp_path / "out.pdf", selected_images=[(1, "/Im0")])

    assert row_for(report, "/Im0")["action"] == "processed"
    assert row_for(report, "/Im1")["action"] == "not_processed"


def test_pages_option_limits_the_default_selection(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    report = remove_background(src, tmp_path / "out.pdf", pages=[2])

    assert row_for(report, "/Im1")["action"] == "not_processed"
    assert row_for(report, "/Im1")["reason"] == "page not selected"


def test_vector_background_is_listed_and_not_processed(tmp_path):
    src = make_vector_pdf(tmp_path / "vector.pdf")

    report = remove_background(src, tmp_path / "out.pdf")

    assert [v["page"] for v in report["vector_backgrounds"]] == [1]
    assert report["vector_backgrounds"][0]["note"] == "vector background, not processed"
    assert report["images"] == []


def test_image_that_already_has_transparency_is_not_processed(tmp_path):
    src = make_transparent_pdf(tmp_path / "transparent.pdf")

    report = remove_background(src, tmp_path / "out.pdf")

    row = row_for(report, "/Im1")
    assert row["action"] == "not_processed"
    assert "already has transparency" in row["reason"]


def test_fill_colour_composites_onto_the_colour_with_no_smask(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    out = tmp_path / "out.pdf"

    report = remove_background(src, out, fill="#FFFFFF")

    assert report["fill"] == "#FFFFFF"
    with pikepdf.open(out) as pdf:
        obj = pdf.pages[0].Resources.XObject["/Im1"]
        assert "/SMask" not in obj
        corner = pikepdf.PdfImage(obj).as_pil_image().convert("RGB").getpixel((2, 2))
    assert all(v > 240 for v in corner), corner


def test_input_file_is_not_changed(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    before = sha256(src)

    remove_background(src, tmp_path / "out.pdf")

    assert sha256(src) == before


def test_refuses_to_overwrite_the_input(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    before = sha256(src)

    with pytest.raises(ValueError, match="overwrite"):
        remove_background(src, src)

    assert sha256(src) == before


def test_no_model_is_loaded_when_nothing_is_selected(tmp_path):
    # A model name that does not exist would fail if it were loaded. Nothing is selected
    # here (the only image covers the whole page), so the run must still succeed.
    pdf = pikepdf.Pdf.new()
    full = Image.new("RGB", (800, 1000), (120, 140, 90))
    xobj = image_xobject(pdf, jpeg_bytes(full, 95), 800, 1000)
    add_page(pdf, b"q 612 0 0 792 0 0 cm /Im0 Do Q", xobjects={"/Im0": xobj})
    src = save(pdf, tmp_path / "full.pdf")

    report = remove_background(src, tmp_path / "out.pdf", model="no-such-model")

    assert report["ok"] is True
    assert row_for(report, "/Im0")["action"] == "not_processed"


# ---------------------------------------------------------------------------
# parse_fill and the command line
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "none", "NONE", ""])
def test_parse_fill_none_means_transparency(value):
    assert parse_fill(value) is None


def test_parse_fill_reads_a_hex_colour():
    assert parse_fill("#FFFFFF") == (255, 255, 255)
    assert parse_fill("102030") == (16, 32, 48)


@pytest.mark.parametrize("value", ["white", "#FFF", "#GGGGGG"])
def test_parse_fill_rejects_bad_values(value):
    with pytest.raises(ValueError, match="fill"):
        parse_fill(value)


def test_command_line_removebg(tmp_path, capsys):
    from pdftoolkit.__main__ import main as cli

    src = make_subject_pdf(tmp_path / "subject.pdf")
    out = tmp_path / "out.pdf"

    code = cli(["removebg", str(src), str(out), "--fill", "none", "--pages", "1"])

    assert code == 0
    assert out.exists()
    assert "Processed 1 image" in capsys.readouterr().out