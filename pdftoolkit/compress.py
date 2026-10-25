"""Downsample raster images in a PDF to a maximum DPI and re-encode them as JPEG.

Contract:

- Never modifies the input file.
- Page count, page sizes and image placements are unchanged.
- Images at or below max_dpi are not rewritten.
- Each image object is rewritten at most once, even if it appears on several pages.
- Colour spaces are kept where possible. Anything that cannot be rewritten
  safely (stencil masks, spot colours, CMYK palettes) is reported as
  "not_rewritten" and left unchanged, never silently converted.
- /Decode arrays are removed when an image is re-encoded, because the
  re-encoded pixels already have the decode applied.
- Errors are recorded in the report, and any image skipped because of an
  error makes "ok" false.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pikepdf
from PIL import Image
from pikepdf import Name, Object, Pdf, Stream

from pdftoolkit.inventory import (
    ImageRecord,
    image_objects_on_page,
    inventory_pdf,
    page_count,
    page_media_boxes,
)
from pdftoolkit.reporting import default_report_path, write_report

LANCZOS = Image.Resampling.LANCZOS
DEVICE_NAMES = {"/DeviceRGB", "/DeviceGray", "/DeviceCMYK"}
MODE_TO_NAME = {"RGB": Name.DeviceRGB, "L": Name.DeviceGray, "CMYK": Name.DeviceCMYK}
MODE_TO_COMPONENTS = {"RGB": 3, "L": 1, "CMYK": 4}


def compress_pdf(
    input_path: str | Path,
    output_path: str | Path,
    max_dpi: float = 150,
    jpeg_quality: int = 90,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Downsample images above max_dpi and re-encode them as JPEG.

    Returns the report dictionary. The report is also written to report_path
    (or the default report path next to output_path).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if report_path is None:
        report_path = default_report_path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")
    if max_dpi <= 0:
        raise ValueError("max_dpi must be greater than zero.")

    before_records = inventory_pdf(input_path)
    input_bytes = input_path.stat().st_size
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [_base_row(rec) for rec in before_records]
    warnings: list[str] = []

    # The most demanding (highest) effective DPI an object is drawn at decides
    # how far it is downsampled, so it fits on every page it appears on.
    best_dpi: dict[int, float] = {}
    for rec in before_records:
        if rec.object_gen is not None and rec.effective_dpi is not None:
            best_dpi[rec.object_gen] = max(best_dpi.get(rec.object_gen, 0.0), rec.effective_dpi)

    owner_row: dict[int, int] = {}  # object number -> index of the row that rewrites it
    shared_of: dict[int, int] = {}  # row index -> owner row index, for shared images

    with Pdf.open(input_path) as pdf:
        # Look up image objects before anything is modified.
        objects_by_page = {
            number: image_objects_on_page(page)
            for number, page in enumerate(pdf.pages, start=1)
        }

        for index, rec in enumerate(before_records):
            row = rows[index]
            if rec.is_inline:
                row["action"] = "not_rewritten"
                row["reason"] = "inline image; compression does not rewrite it"
                continue
            if rec.object_gen is None:
                row["reason"] = "image object has no object number; not rewritten"
                continue
            if rec.effective_dpi is None:
                row["reason"] = rec.note or "no placement; cannot compute effective DPI"
                continue
            if rec.object_gen in owner_row:
                row["action"] = "shared"
                row["reason"] = f"same image object as row {owner_row[rec.object_gen]}; handled there"
                shared_of[index] = owner_row[rec.object_gen]
                continue

            owner_row[rec.object_gen] = index
            dpi = best_dpi[rec.object_gen]
            if dpi <= max_dpi:
                row["reason"] = f"effective DPI {dpi:.2f} <= max_dpi {max_dpi}"
                continue

            obj = objects_by_page[rec.page_number].get(rec.object_gen)
            if obj is None:
                row["action"] = "skipped"
                row["reason"] = "could not locate image object"
                warnings.append(f"page {rec.page_number} {rec.image_name}: could not locate image object")
                continue

            try:
                _rewrite_image(pdf, obj, dpi=dpi, max_dpi=max_dpi, jpeg_quality=jpeg_quality, row=row)
            except Exception as exc:  # recorded, never hidden
                row["action"] = "skipped"
                row["reason"] = f"error: {exc}"
                warnings.append(f"page {rec.page_number} {rec.image_name}: {exc}")

        warnings.extend(_save_pdf(pdf, output_path))

    # Shared rows describe the same object as their owner row.
    for index, owner_index in shared_of.items():
        for key in ("pixels_after", "dpi_after", "bytes_after"):
            rows[index][key] = rows[owner_index][key]

    # Check the saved file itself: no image may be above max_dpi any more.
    # Object numbers can change on save, so this uses a fresh inventory.
    max_output_dpi = 0.0
    for rec in inventory_pdf(output_path):
        if not rec.is_inline and rec.effective_dpi is not None:
            max_output_dpi = max(max_output_dpi, rec.effective_dpi)
    if max_output_dpi > max_dpi * 1.01:
        warnings.append(
            f"output still has an image at {max_output_dpi:.1f} dpi, above max_dpi {max_dpi}"
        )

    output_bytes = output_path.stat().st_size
    ok = not any(row["action"] == "skipped" for row in rows)
    report: dict[str, Any] = {
        "operation": "compress",
        "ok": ok,
        "input": str(input_path),
        "output": str(output_path),
        "max_dpi": max_dpi,
        "jpeg_quality": jpeg_quality,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "page_count": page_count(output_path),
        "page_sizes": page_media_boxes(output_path),
        "images": rows,
        "warnings": warnings,
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


# ---------------------------------------------------------------------------
# Row bookkeeping
# ---------------------------------------------------------------------------


def _base_row(rec: ImageRecord) -> dict[str, Any]:
    return {
        "page": rec.page_number,
        "name": rec.image_name,
        "pixels_before": [rec.width_px, rec.height_px],
        "pixels_after": [rec.width_px, rec.height_px],
        "dpi_before": rec.effective_dpi,
        "dpi_after": rec.effective_dpi,
        "bytes_before": rec.compressed_bytes,
        "bytes_after": rec.compressed_bytes,
        "action": "unchanged",
        "color_space": rec.color_space,
    }


# ---------------------------------------------------------------------------
# Rewriting one image object
# ---------------------------------------------------------------------------


def _rewrite_image(
    pdf: Pdf,
    obj: Stream,
    *,
    dpi: float,
    max_dpi: float,
    jpeg_quality: int,
    row: dict[str, Any],
) -> None:
    plan, reason = _colour_plan(obj)
    if plan == "unsupported":
        row["action"] = "not_rewritten"
        row["reason"] = reason
        return

    cur_w = int(obj.get("/Width"))
    cur_h = int(obj.get("/Height"))
    scale = max_dpi / dpi
    new_w = min(cur_w, max(1, round(cur_w * scale)))
    new_h = min(cur_h, max(1, round(cur_h * scale)))
    if new_w == cur_w and new_h == cur_h:
        row["reason"] = "target size is not smaller (never upscale)"
        return

    pil, mask = _load_image_and_mask(obj)
    if plan == "icc" and MODE_TO_COMPONENTS.get(_mode_for(pil), -1) != _icc_components(obj):
        row["action"] = "not_rewritten"
        row["reason"] = "ICC profile component count does not match the decoded image"
        return

    resampled = pil.resize((new_w, new_h), LANCZOS)
    resampled_mask = mask.resize((new_w, new_h), LANCZOS) if mask is not None else None

    jpeg_bytes, mode = _encode_jpeg(resampled, jpeg_quality)
    colour_value = _output_colour_space(obj, plan, mode, row)

    _write_jpeg_stream(obj, jpeg_bytes, new_w, new_h, colour_value)
    if resampled_mask is not None:
        _write_new_smask(pdf, obj, resampled_mask)

    smask_obj = obj.get("/SMask")
    row["action"] = "downsampled"
    row["pixels_after"] = [new_w, new_h]
    row["dpi_after"] = dpi * new_w / cur_w
    row["bytes_after"] = len(obj.read_raw_bytes()) + (
        len(smask_obj.read_raw_bytes()) if smask_obj is not None else 0
    )
    if str(colour_value) != row["color_space"]:
        row["color_space_after"] = str(colour_value)


def _colour_plan(obj: Stream) -> tuple[str, str | None]:
    """Decide whether this image can be rewritten safely.

    Returns (plan, reason). plan is one of:
      device      DeviceRGB, DeviceGray or DeviceCMYK, kept as-is
      icc         ICCBased, kept with its original profile
      indexed     Indexed with an RGB base, converted to RGB
      unsupported anything else; left unchanged
    """
    if bool(obj.get("/ImageMask", False)):
        return "unsupported", "stencil image mask; not rewritten"
    cs = obj.get("/ColorSpace")
    if cs is None:
        return "device", None
    if isinstance(cs, Name):
        if str(cs) in DEVICE_NAMES:
            return "device", None
        return "unsupported", f"colour space {cs} not rewritten"
    if isinstance(cs, pikepdf.Array) and len(cs) > 0:
        head = str(cs[0])
        if head == "/ICCBased":
            return "icc", None
        if head == "/Indexed" and len(cs) > 1 and str(cs[1]) != "/DeviceCMYK":
            return "indexed", None
        return "unsupported", f"colour space {head} not rewritten"
    return "unsupported", "unknown colour space; not rewritten"


def _icc_components(obj: Stream) -> int:
    cs = obj.get("/ColorSpace")
    return int(cs[1].get("/N", 0) or 0)


def _output_colour_space(obj: Stream, plan: str, mode: str, row: dict[str, Any]) -> Object:
    if plan == "icc":
        return obj.get("/ColorSpace")
    if plan == "indexed":
        row["conversion"] = "indexed palette converted to RGB; colours kept, palette removed"
        return Name.DeviceRGB
    return MODE_TO_NAME[mode]


def _mode_for(pil: Image.Image) -> str:
    if pil.mode == "CMYK":
        return "CMYK"
    if pil.mode in ("L", "1"):
        return "L"
    return "RGB"


# ---------------------------------------------------------------------------
# Decoding and encoding
# ---------------------------------------------------------------------------


def _load_image_and_mask(obj: Stream) -> tuple[Image.Image, Image.Image | None]:
    """Decode an image to PIL, with its soft mask if it has one.

    pikepdf applies /Decode arrays while decoding, so the result is the
    colours a viewer would show.
    """
    mask = None
    smask = obj.get("/SMask")
    if smask is not None:
        mask = _decode(smask).convert("L")

    pil = _decode(obj)
    if pil.mode in ("RGBA", "LA"):
        if mask is None:
            mask = pil.getchannel("A")
        pil = pil.convert("RGB") if pil.mode == "RGBA" else pil.convert("L")
    elif pil.mode == "P":
        if "transparency" in pil.info and mask is None:
            rgba = pil.convert("RGBA")
            mask = rgba.getchannel("A")
            pil = rgba.convert("RGB")
        else:
            pil = pil.convert("RGB")
    return pil, mask


def _decode(obj: Stream) -> Image.Image:
    return pikepdf.PdfImage(obj).as_pil_image()


def _encode_jpeg(pil: Image.Image, quality: int) -> tuple[bytes, str]:
    mode = _mode_for(pil)
    if mode == "RGB":
        img = pil if pil.mode == "RGB" else pil.convert("RGB")
    elif mode == "L":
        img = pil.convert("L")
    else:
        img = pil
    buf = io.BytesIO()
    kwargs: dict[str, Any] = {"format": "JPEG", "quality": max(1, min(95, int(quality)))}
    if mode == "CMYK":
        kwargs["subsampling"] = 0
    img.save(buf, **kwargs)
    return buf.getvalue(), mode


def _write_jpeg_stream(
    obj: Stream,
    jpeg_bytes: bytes,
    width: int,
    height: int,
    colour_space: Object,
) -> None:
    obj.write(jpeg_bytes, filter=Name.DCTDecode)
    obj["/Width"] = width
    obj["/Height"] = height
    obj["/ColorSpace"] = colour_space
    obj["/BitsPerComponent"] = 8
    obj["/Filter"] = Name.DCTDecode
    # The new pixels already have any decode applied, so the old /Decode
    # array must go, or colours would be inverted a second time.
    for stale in ("/DecodeParms", "/DP", "/Decode", "/Length1", "/Name"):
        if stale in obj:
            del obj[stale]


def _write_new_smask(pdf: Pdf, image_obj: Stream, mask: Image.Image) -> None:
    """Attach a new soft mask. A new object is always created, so a mask
    shared with another image is never changed by accident."""
    raw = mask.convert("L").tobytes()
    smask = Stream(pdf, raw)
    smask.write(raw, filter=Name.FlateDecode)
    smask["/Type"] = Name.XObject
    smask["/Subtype"] = Name.Image
    smask["/Width"] = mask.width
    smask["/Height"] = mask.height
    smask["/ColorSpace"] = Name.DeviceGray
    smask["/BitsPerComponent"] = 8
    image_obj["/SMask"] = smask


def _save_pdf(pdf: Pdf, output_path: Path) -> list[str]:
    warnings: list[str] = []
    try:
        pdf.remove_unreferenced_resources()
    except Exception as exc:
        warnings.append(f"could not remove unreferenced resources: {exc}")
    pdf.save(
        output_path,
        compress_streams=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        recompress_flate=True,
    )
    return warnings