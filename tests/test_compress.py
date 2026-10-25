from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
from PIL import Image, ImageDraw
from pikepdf import Dictionary, Name, Pdf, Stream

from pdftoolkit.compress import compress_pdf
from pdftoolkit.inventory import inventory_pdf, page_count, page_media_boxes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_compress_opens_same_pages_and_is_smaller(sample_pdf: Path, tmp_path: Path) -> None:
    original_hash = _sha256(sample_pdf)
    output = tmp_path / "compressed.pdf"
    report = compress_pdf(sample_pdf, output, max_dpi=150, jpeg_quality=90)

    assert output.exists()
    with pikepdf.open(output) as pdf:
        assert len(pdf.pages) == page_count(sample_pdf)
    assert page_media_boxes(output) == page_media_boxes(sample_pdf)
    assert output.stat().st_size < sample_pdf.stat().st_size
    assert _sha256(sample_pdf) == original_hash
    assert report["ok"] is True
    actions = {item["name"].lstrip("/"): item["action"] for item in report["images"]}
    assert actions["Im0"] == "downsampled"
    assert actions["Im1"] == "downsampled"


def test_images_at_or_below_max_dpi_unchanged(sample_pdf: Path, tmp_path: Path) -> None:
    original_hash = _sha256(sample_pdf)
    before = {r.image_name: r for r in inventory_pdf(sample_pdf)}
    output = tmp_path / "partial.pdf"
    report = compress_pdf(sample_pdf, output, max_dpi=320, jpeg_quality=90)

    after = {r.image_name: r for r in inventory_pdf(output)}
    before_by = {k.lstrip("/"): v for k, v in before.items()}
    after_by = {k.lstrip("/"): v for k, v in after.items()}
    fg_before = before_by["Im1"]
    fg_after = after_by["Im1"]
    bg_before = before_by["Im0"]
    bg_after = after_by["Im0"]

    assert fg_after.width_px == fg_before.width_px
    assert fg_after.height_px == fg_before.height_px
    assert fg_after.compressed_bytes == fg_before.compressed_bytes
    assert bg_after.width_px < bg_before.width_px
    assert _sha256(sample_pdf) == original_hash

    by_name = {item["name"].lstrip("/"): item for item in report["images"]}
    assert by_name["Im1"]["action"] == "unchanged"
    assert by_name["Im0"]["action"] == "downsampled"


def test_original_hash_unchanged_when_nothing_to_do(sample_pdf: Path, tmp_path: Path) -> None:
    original_hash = _sha256(sample_pdf)
    output = tmp_path / "noop.pdf"
    report = compress_pdf(sample_pdf, output, max_dpi=400, jpeg_quality=90)
    assert _sha256(sample_pdf) == original_hash
    assert all(item["action"] == "unchanged" for item in report["images"])


def test_smask_is_downsampled_lossless(tmp_path: Path) -> None:
    src = tmp_path / "with_mask.pdf"
    _write_masked_pdf(src)
    original_hash = _sha256(src)
    out = tmp_path / "with_mask_out.pdf"
    report = compress_pdf(src, out, max_dpi=72, jpeg_quality=85)
    assert _sha256(src) == original_hash
    assert out.exists()
    with pikepdf.open(out) as pdf:
        page = pdf.pages[0]
        image = page.Resources.XObject["/Im0"]
        assert "/SMask" in image
        smask = image["/SMask"]
        assert smask["/Width"] == image["/Width"]
        assert smask["/Height"] == image["/Height"]
        filt = smask.get("/Filter")
        assert filt in (Name.FlateDecode, None) or (hasattr(filt, "__iter__") and Name.FlateDecode in filt)
    row = report["images"][0]
    assert row["action"] == "downsampled"


def _write_masked_pdf(path: Path) -> None:
    page_w, page_h = 288.0, 288.0  # 4 inches
    rgb = Image.new("RGB", (800, 800), (10, 80, 200))
    draw = ImageDraw.Draw(rgb)
    draw.ellipse([200, 200, 600, 600], fill=(240, 200, 40))
    mask = Image.new("L", (800, 800), 0)
    ImageDraw.Draw(mask).ellipse([200, 200, 600, 600], fill=255)

    pdf = Pdf.new()
    pdf.add_blank_page(page_size=(page_w, page_h))
    page = pdf.pages[0]
    raw = rgb.tobytes()
    image = Stream(pdf, raw)
    image[Name.Type] = Name.XObject
    image[Name.Subtype] = Name.Image
    image[Name.Width] = 800
    image[Name.Height] = 800
    image[Name.ColorSpace] = Name.DeviceRGB
    image[Name.BitsPerComponent] = 8
    image.write(raw)

    mraw = mask.tobytes()
    smask = Stream(pdf, mraw)
    smask[Name.Type] = Name.XObject
    smask[Name.Subtype] = Name.Image
    smask[Name.Width] = 800
    smask[Name.Height] = 800
    smask[Name.ColorSpace] = Name.DeviceGray
    smask[Name.BitsPerComponent] = 8
    smask.write(mraw)
    image[Name.SMask] = smask

    xobjects = Dictionary()
    xobjects[Name.Im0] = image
    resources = Dictionary()
    resources[Name.XObject] = xobjects
    page[Name.Resources] = resources
    content = f"q {page_w:.4f} 0 0 {page_h:.4f} 0 0 cm /Im0 Do Q\n"
    page[Name.Contents] = Stream(pdf, content.encode("ascii"))
    pdf.save(path)
    pdf.close()
