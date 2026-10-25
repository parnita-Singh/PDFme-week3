"""Tests for the compression fixes: one rewrite per image object, colour spaces
kept or reported, /Decode removed, errors reported, and output checked."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
from PIL import Image, ImageCms
from pikepdf import Array, Dictionary, Name, Pdf, PdfImage, Stream

from pdftoolkit.compress import compress_pdf
from _builders import add_page, gradient_image, image_xobject, jpeg_bytes, save


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode(path: Path, page_index: int = 0, name: str = "/Im0") -> Image.Image:
    with pikepdf.open(path) as pdf:
        obj = pdf.pages[page_index].Resources.XObject[name]
        return PdfImage(obj).as_pil_image().convert("RGB")


def _mean_difference(a: Image.Image, b: Image.Image) -> float:
    b = b.resize(a.size)
    left, right = a.tobytes(), b.tobytes()
    return sum(abs(x - y) for x, y in zip(left, right)) / len(left)


def _row(report: dict, page: int, name: str) -> dict:
    return next(r for r in report["images"] if r["page"] == page and r["name"] == name)


# ---------------------------------------------------------------------------
# One rewrite per image object
# ---------------------------------------------------------------------------


def test_image_shared_by_two_pages_is_downsampled_once(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(1200, 1200)), 1200, 1200)
    add_page(pdf, b"q 300 0 0 300 0 0 cm /Im0 Do Q", {"/Im0": img})
    add_page(pdf, b"q 300 0 0 300 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "shared.pdf")

    out = tmp_path / "shared_out.pdf"
    report = compress_pdf(src, out, max_dpi=150, jpeg_quality=90)

    # 1200 px at 288 dpi -> 150 dpi is 625 px. A double pass would give ~325 px.
    with pikepdf.open(out) as result:
        width = int(result.pages[0].Resources.XObject["/Im0"].Width)
    assert abs(width - 625) <= 1
    assert _row(report, 1, "/Im0")["action"] == "downsampled"
    assert _row(report, 2, "/Im0")["action"] == "shared"
    assert report["ok"] is True


# ---------------------------------------------------------------------------
# Colour spaces
# ---------------------------------------------------------------------------


def _srgb_profile(pdf: Pdf) -> Array:
    profile_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    profile = Stream(pdf, profile_bytes)
    profile[Name.N] = 3
    return Array([Name.ICCBased, profile])


def test_icc_colour_space_is_kept(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(
        pdf,
        jpeg_bytes(gradient_image(1200, 1200)),
        1200,
        1200,
        colorspace=_srgb_profile(pdf),
        filter=Name.DCTDecode,
    )
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "icc.pdf")

    out = tmp_path / "icc_out.pdf"
    report = compress_pdf(src, out, max_dpi=150)

    assert _row(report, 1, "/Im0")["action"] == "downsampled"
    with pikepdf.open(out) as result:
        cs = result.pages[0].Resources.XObject["/Im0"].ColorSpace
        assert str(cs[0]) == "/ICCBased"
        assert int(cs[1].N) == 3


def test_indexed_image_is_converted_and_reported(tmp_path: Path) -> None:
    pdf = Pdf.new()
    palette = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
    index_data = bytes([0, 1, 2, 3] * 300 * 300)[: 600 * 600]
    cs = Array([Name.Indexed, Name.DeviceRGB, 3, pikepdf.String(palette)])
    img = image_xobject(pdf, index_data, 600, 600, bpc=8, colorspace=cs)
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "indexed.pdf")

    out = tmp_path / "indexed_out.pdf"
    report = compress_pdf(src, out, max_dpi=100)

    row = _row(report, 1, "/Im0")
    assert row["action"] == "downsampled"
    assert "conversion" in row and "indexed" in row["conversion"]
    with pikepdf.open(out) as result:
        assert str(result.pages[0].Resources.XObject["/Im0"].ColorSpace) == "/DeviceRGB"


def test_spot_colour_image_is_left_alone(tmp_path: Path) -> None:
    pdf = Pdf.new()
    sep = Array([Name.Separation, Name("/Gold"), Name.DeviceCMYK, Dictionary(FunctionType=2)])
    img = image_xobject(pdf, bytes([128]) * (800 * 800), 800, 800, bpc=8, colorspace=sep)
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "spot.pdf")

    report = compress_pdf(src, tmp_path / "spot_out.pdf", max_dpi=72)

    row = _row(report, 1, "/Im0")
    assert row["action"] == "not_rewritten"
    assert report["ok"] is True


# ---------------------------------------------------------------------------
# /Decode and colour correctness
# ---------------------------------------------------------------------------


def test_inverted_decode_array_does_not_invert_colours(tmp_path: Path) -> None:
    pdf = Pdf.new()
    source = gradient_image(1000, 1000)
    # Store the inverted pixels, with a /Decode array that inverts them back.
    inverted = Image.eval(source, lambda v: 255 - v)
    img = image_xobject(
        pdf,
        jpeg_bytes(inverted),
        1000,
        1000,
        filter=Name.DCTDecode,
        Decode=Array([1, 0, 1, 0, 1, 0]),
    )
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "decode.pdf")

    out = tmp_path / "decode_out.pdf"
    compress_pdf(src, out, max_dpi=100)

    before = _decode(src)
    after = _decode(out)
    assert _mean_difference(before, after) < 6  # inverted output would be ~255 - x
    with pikepdf.open(out) as result:
        assert "/Decode" not in result.pages[0].Resources.XObject["/Im0"]


# ---------------------------------------------------------------------------
# Errors and limits
# ---------------------------------------------------------------------------


def test_corrupt_image_is_reported_and_ok_is_false(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(
        pdf,
        b"this is not a jpeg at all",
        2000,
        2000,
        filter=Name.DCTDecode,
    )
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "corrupt.pdf")

    report = compress_pdf(src, tmp_path / "corrupt_out.pdf", max_dpi=100)

    assert _row(report, 1, "/Im0")["action"] == "skipped"
    assert report["ok"] is False
    assert report["warnings"]


def test_image_already_below_cap_is_never_upscaled(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(100, 100)), 100, 100)
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img})
    src = save(pdf, tmp_path / "small.pdf")

    report = compress_pdf(src, tmp_path / "small_out.pdf", max_dpi=150)

    row = _row(report, 1, "/Im0")
    assert row["action"] == "unchanged"
    assert row["pixels_after"] == [100, 100]


def test_output_keeps_page_count_sizes_and_input_hash(tmp_path: Path) -> None:
    pdf = Pdf.new()
    img = image_xobject(pdf, jpeg_bytes(gradient_image(1500, 1500)), 1500, 1500)
    add_page(pdf, b"q 200 0 0 200 0 0 cm /Im0 Do Q BT /F1 12 Tf ET", {"/Im0": img}, size=(300, 300))
    add_page(pdf, b"q 100 0 0 100 0 0 cm /Im0 Do Q", {"/Im0": img}, size=(400, 200))
    src = save(pdf, tmp_path / "two_pages.pdf")
    input_hash = _sha256(src)

    out = tmp_path / "two_pages_out.pdf"
    report = compress_pdf(src, out, max_dpi=150)

    assert _sha256(src) == input_hash
    assert report["page_count"] == 2
    assert report["page_sizes"] == [(0.0, 0.0, 300.0, 300.0), (0.0, 0.0, 400.0, 200.0)]
    assert report["max_dpi"] == 150
    assert not any("above max_dpi" in w for w in report["warnings"])