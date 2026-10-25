"""Remove image backgrounds with rembg (open models), keeping every placement.

By default, the original image pixels are left as they are. The rembg mask is
attached to the image as its SMask (alpha), so the image keeps its place on the
page. If a fill colour is given, the image is composited onto that colour and
no transparency is left.

Default selection: opaque raster images that cover less than 90% of the page
they are drawn on. Images that already have transparency are not processed.
Vector backgrounds (filled shapes that cover most of a page, such as Canva
backgrounds) are never processed; they are listed in the report.

The first run downloads the model (about 180 MB for isnet-general-use). After
that, the app works with no internet connection. A model file can also be
supplied with model_file, for machines without internet access.

Usage:
    python -m pdftoolkit removebg input.pdf output.pdf --fill none --pages 1
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pikepdf
from PIL import Image
from pikepdf import Name

from pdftoolkit.inventory import (
    _mat_mul,
    apply_matrix,
    image_objects_on_page,
    inventory_pdf,
    page_media_boxes,
)
from pdftoolkit.reporting import default_report_path, write_report

DEFAULT_MODEL = "isnet-general-use"
COVER_LIMIT = 0.90
VECTOR_NOTE = "vector background, not processed"
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
FILL_PATH_OPERATORS = {"f", "f*", "F", "B", "B*", "b", "b*"}
END_PATH_OPERATORS = {"n", "S", "s"}


# ---------------------------------------------------------------------------
# Colour parsing
# ---------------------------------------------------------------------------

def parse_fill(fill: str | None) -> tuple[int, int, int] | None:
    """'none' or None means transparency. '#RRGGBB' is an RGB colour to composite onto."""
    if fill is None or fill.strip().lower() in ("", "none"):
        return None
    text = fill.strip().lstrip("#")
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"fill must be 'none' or a colour like #FFFFFF, not {fill!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _model_folder(model: str) -> Path:
    from rembg.sessions.base import BaseSession

    return Path(BaseSession.rembg_home()) / "models" / model


def _open_session(model: str, model_file: str | Path | None):
    """Load the rembg session. If model_file is given, copy it into rembg's model folder first."""
    if model_file is not None:
        source = Path(model_file)
        if not source.is_file():
            raise FileNotFoundError(f"model file not found: {source}")
        folder = _model_folder(model)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{model}.onnx"
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
    try:
        from rembg import new_session
    except ImportError as exc:
        raise RuntimeError(
            "rembg is not installed in this Python. Run: "
            "python -m pip install -r requirements-bg.txt"
        ) from exc
    try:
        return new_session(model)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load the model {model!r}. The first run needs internet access to "
            f"download it. For a computer without internet, copy the model file to the "
            f"folder {_model_folder(model)} as {model}.onnx, or pass --model-file. "
            f"Detail: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Choosing images
# ---------------------------------------------------------------------------

def _coverage(record, page_area: float) -> float | None:
    """The largest share of the page that this image is drawn over, or None if not drawn."""
    best = None
    for placement in record.placements:
        share = (placement.width_pts * placement.height_pts) / page_area if page_area else 0.0
        best = share if best is None else max(best, share)
    return best


def _image_rows(records, boxes, selected, pages) -> list[dict[str, Any]]:
    """One row per image record, with the decision and the reason. Eligible rows are marked."""
    rows: list[dict[str, Any]] = []
    for rec in records:
        box = boxes[rec.page_number - 1]
        page_area = (box[2] - box[0]) * (box[3] - box[1])
        coverage = _coverage(rec, page_area)
        row: dict[str, Any] = {
            "page": rec.page_number,
            "image": rec.image_name,
            "object": rec.object_gen,
            "width_px": rec.width_px,
            "height_px": rec.height_px,
            "color_space": rec.color_space,
            "bytes_before": rec.compressed_bytes,
            "coverage": None if coverage is None else round(coverage, 4),
            "action": None,
            "reason": None,
            "eligible": False,
        }
        if rec.is_inline:
            row.update(action="not_processed", reason="inline image; not processed")
        elif rec.object_gen is None:
            row.update(action="not_processed", reason="image object has no object number")
        elif rec.has_transparency:
            row.update(action="not_processed", reason="already has transparency (SMask); not processed")
        elif selected is not None and (rec.page_number, rec.image_name) not in selected:
            row.update(action="not_processed", reason="not in the selected images")
        elif selected is None and pages is not None and rec.page_number not in pages:
            row.update(action="not_processed", reason="page not selected")
        elif coverage is None:
            row.update(action="not_processed", reason="not drawn on a page")
        elif selected is None and coverage >= COVER_LIMIT:
            row.update(
                action="not_processed",
                reason=f"covers {coverage * 100:.0f}% of the page; the default rule is under 90%",
            )
        else:
            row["eligible"] = True
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Vector backgrounds
# ---------------------------------------------------------------------------

def _vector_backgrounds(pdf: pikepdf.Pdf, boxes) -> list[dict[str, Any]]:
    """Filled rectangles that cover most of a page. They are listed, never processed."""
    found: list[dict[str, Any]] = []
    for number, page in enumerate(pdf.pages, start=1):
        box = boxes[number - 1]
        page_area = (box[2] - box[0]) * (box[3] - box[1])
        ctm = IDENTITY
        stack: list[tuple[float, ...]] = []
        pending: list[tuple[float, float, float, float]] = []
        best = 0.0
        for operands, operator in pikepdf.parse_content_stream(page):
            name = str(operator)
            if name == "q":
                stack.append(ctm)
            elif name == "Q":
                ctm = stack.pop() if stack else IDENTITY
            elif name == "cm" and len(operands) == 6:
                ctm = _mat_mul(ctm, tuple(float(v) for v in operands))
            elif name == "re" and len(operands) == 4:
                x, y, w, h = (float(v) for v in operands)
                corners = [apply_matrix(ctm, cx, cy) for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
                xs = [c[0] for c in corners]
                ys = [c[1] for c in corners]
                pending.append((min(xs), min(ys), max(xs), max(ys)))
            elif name in FILL_PATH_OPERATORS:
                for x0, y0, x1, y1 in pending:
                    if page_area:
                        best = max(best, ((x1 - x0) * (y1 - y0)) / page_area)
                pending = []
            elif name in END_PATH_OPERATORS:
                pending = []
        if best >= COVER_LIMIT:
            found.append({"page": number, "coverage": round(best, 4), "note": VECTOR_NOTE})
    return found


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _placements_by_page(path: Path) -> dict[int, list[tuple[float, ...]]]:
    result: dict[int, list[tuple[float, ...]]] = {}
    for rec in inventory_pdf(path):
        for placement in rec.placements:
            result.setdefault(rec.page_number, []).append(tuple(round(v, 6) for v in placement.ctm))
    return {page: sorted(values) for page, values in result.items()}


def _attach_alpha(pdf: pikepdf.Pdf, obj: pikepdf.Stream, mask: Image.Image) -> int:
    """Set the mask as the image's SMask. Returns the mask's size in bytes."""
    data = mask.tobytes()
    smask = pdf.make_stream(data)
    smask[Name.Type] = Name.XObject
    smask[Name.Subtype] = Name.Image
    smask[Name.Width] = mask.width
    smask[Name.Height] = mask.height
    smask[Name.ColorSpace] = Name.DeviceGray
    smask[Name.BitsPerComponent] = 8
    obj[Name.SMask] = smask
    return len(data)


def _composite_in_place(obj: pikepdf.Stream, rgb: Image.Image, mask: Image.Image, fill: tuple[int, int, int]) -> int:
    background = Image.new("RGB", rgb.size, fill)
    out = Image.composite(rgb, background, mask)
    buffer = io.BytesIO()
    out.save(buffer, format="JPEG", quality=95)
    data = buffer.getvalue()
    obj.write(data, filter=Name.DCTDecode)
    obj[Name.Width] = out.width
    obj[Name.Height] = out.height
    obj[Name.ColorSpace] = Name.DeviceRGB
    obj[Name.BitsPerComponent] = 8
    for key in ("/DecodeParms", "/Decode", "/SMask", "/Length1"):
        if key in obj:
            del obj[key]
    return len(data)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def remove_background(
    input_path: str | Path,
    output_path: str | Path,
    selected_images: Iterable[tuple[int, str]] | None = None,
    model: str = DEFAULT_MODEL,
    fill: str | None = None,
    pages: Iterable[int] | None = None,
    model_file: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove backgrounds from selected images, or from the default selection.

    selected_images: list of (page number, image name). If given, exactly these
    images are processed (the transparency check still applies).
    pages: with the default selection, limit it to these page numbers.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")
    fill_rgb = parse_fill(fill)
    selected = None if selected_images is None else {(int(p), str(n)) for p, n in selected_images}
    page_filter = None if pages is None else {int(p) for p in pages}
    if report_path is None:
        report_path = default_report_path(output_path)

    records = inventory_pdf(input_path)
    boxes = page_media_boxes(input_path)
    rows = _image_rows(records, boxes, selected, page_filter)
    warnings: list[str] = []

    if selected is not None:
        seen = {(r["page"], r["image"]) for r in rows}
        for key in sorted(selected - seen):
            warnings.append(f"selected image not found: page {key[0]} {key[1]}")

    eligible = [r for r in rows if r["eligible"]]
    vector = []

    with pikepdf.open(input_path) as pdf:
        vector = _vector_backgrounds(pdf, boxes)
        objects_by_page = {
            number: image_objects_on_page(page) for number, page in enumerate(pdf.pages, start=1)
        }

        if eligible:
            session = _open_session(model, model_file)
            from rembg import remove as rembg_remove

            owner: dict[int, dict[str, Any]] = {}
            for row in eligible:
                obj_num = row["object"]
                if obj_num in owner:
                    row.update(
                        action="shared",
                        reason=f"same image object as page {owner[obj_num]['page']}; handled there",
                        eligible=False,
                    )
                    continue
                owner[obj_num] = row
                try:
                    obj = objects_by_page[row["page"]].get(obj_num)
                    if obj is None:
                        raise RuntimeError("could not locate the image object")
                    if bool(obj.get("/ImageMask", False)):
                        row.update(action="not_processed", reason="stencil mask; not processed", eligible=False)
                        continue
                    pil = pikepdf.PdfImage(obj).as_pil_image()
                    rgb = pil.convert("RGB")
                    mask = rembg_remove(rgb, session=session, only_mask=True)
                    if mask.size != rgb.size:
                        raise RuntimeError(f"mask size {mask.size} does not match image {rgb.size}")
                    mask = mask.convert("L")
                    if fill_rgb is None:
                        row["bytes_after"] = _attach_alpha(pdf, obj, mask)
                        row["mode"] = "alpha"
                    else:
                        if obj.get(Name.ColorSpace) != Name.DeviceRGB:
                            row.update(
                                action="not_processed",
                                reason="fill needs an RGB image; this image is not RGB",
                                eligible=False,
                            )
                            continue
                        row["bytes_after"] = _composite_in_place(obj, rgb, mask, fill_rgb)
                        row["mode"] = "fill"
                    row.update(action="processed", reason=None)
                except Exception as exc:  # recorded, never hidden
                    row.update(action="error", reason=f"error: {exc}", eligible=False)
                    warnings.append(f"page {row['page']} {row['image']}: {exc}")

            # Images that share an object with a processed image describe the same result.
            for row in rows:
                if row["action"] == "shared":
                    source = owner.get(row["object"])
                    if source is not None:
                        row["bytes_after"] = source.get("bytes_after")
                        row["mode"] = source.get("mode")
                        row["action"] = "shared"

        partial = output_path.with_name(output_path.name + ".partial")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(
            partial,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
        )
    os.replace(partial, output_path)

    before = _placements_by_page(input_path)
    after = _placements_by_page(output_path)
    changed_pages = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    if changed_pages:
        warnings.append(f"placements changed on pages {changed_pages}; check before using this file")

    processed = sum(1 for r in rows if r["action"] == "processed")
    errors = sum(1 for r in rows if r["action"] == "error")
    ok = errors == 0 and not changed_pages
    message = (
        f"Processed {processed} image(s)"
        + (f" with fill {fill}" if fill_rgb is not None else " (transparent background)")
        + f"; {len(rows) - processed - errors} not processed; {len(vector)} vector background(s) "
        "listed and not processed."
    )
    report: dict[str, Any] = {
        "operation": "removebg",
        "ok": ok,
        "input": str(input_path),
        "output": str(output_path),
        "model": model,
        "fill": fill if fill_rgb is not None else None,
        "input_bytes": input_path.stat().st_size,
        "output_bytes": output_path.stat().st_size,
        "rule": "default: opaque raster images covering under 90% of their page"
        if selected is None else "selected images only",
        "images": rows,
        "vector_backgrounds": vector,
        "placements_changed_pages": changed_pages,
        "warnings": warnings,
        "message": message,
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove image backgrounds with rembg.")
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument("--fill", default="none", help="'none' for transparency, or a colour like #FFFFFF")
    parser.add_argument("--pages", default=None, help="page numbers to process, e.g. 1 or 1,3")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-file", default=None, help="a local .onnx model file (for offline computers)")
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    pages = None
    if args.pages:
        pages = [int(p) for p in args.pages.split(",") if p.strip()]
    report = remove_background(
        args.input_pdf,
        args.output_pdf,
        model=args.model,
        fill=args.fill,
        pages=pages,
        model_file=args.model_file,
        report_path=args.report,
    )
    sys.stdout.write(report["message"] + "\n")
    for row in report["images"]:
        if row["action"] != "processed":
            sys.stdout.write(f"  page {row['page']} {row['image']}: {row['action']}: {row['reason']}\n")
    for item in report["vector_backgrounds"]:
        sys.stdout.write(f"  page {item['page']}: {item['note']} ({item['coverage'] * 100:.0f}% of page)\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())