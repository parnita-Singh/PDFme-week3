"""The work behind the web page. No web code here, so it can be tested directly.

Each function takes file paths and options, writes into an output folder, and
returns (output paths, a short text message). Errors are returned as messages,
so the page never crashes on a bad file.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from pdftoolkit.inventory import inventory_pdf, page_count, records_as_dicts

MB = 1_000_000
DEFAULT_OUTPUT_DIR = Path("outputs")


def _unique(folder: Path, name: str) -> Path:
    """A path in folder that does not exist yet: name.pdf, name_2.pdf, and so on."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / name
    counter = 2
    while candidate.exists():
        candidate = folder / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1
    return candidate


def _parse_pages(text: str | None) -> list[int] | None:
    """'' or None means all pages. '1' or '1,3' or '2-4' are page numbers."""
    if text is None or not text.strip():
        return None
    pages: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, last = part.split("-", 1)
            pages.extend(range(int(first), int(last) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def _safe(action, *args, **kwargs):
    """Run an action. Return (result, None) or (None, error message)."""
    try:
        return action(*args, **kwargs), None
    except Exception as exc:  # shown in the page, never crashes it
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

INSPECT_HEADERS = ["page", "image", "width_px", "height_px", "colour", "transparent", "size_MB",
                   "effective_dpi", "placed_inches", "covers_page"]
LABEL_HEADERS = ["page", "label", "reason"]


def image_choices(path: str | None) -> list[tuple[str, str]]:
    """Entries for the image tick list: (what the person sees, the value used for processing).

    The value is 'page:name', for example '1:X4', which remove_background reads directly.
    """
    if not path:
        return []
    rows, _ = inspect_file(path)
    choices = []
    for page, name, _w, _h, _colour, _transparent, _size, _dpi, placed, covers in rows:
        short = name.lstrip("/")
        label = f"Page {page}, image {short}: {placed} in, covers {covers}"
        choices.append((label, f"{page}:{short}"))
    return choices


def inspect_file(path: str) -> tuple[list[list[Any]], str]:
    """Rows for a table (headers in INSPECT_HEADERS): one row per image, plus a summary line.

    placed_inches is the size the image is drawn at (width x height). covers_page is the share
    of the page it covers: a full-page background shows about 100%.
    """
    from pdftoolkit.background import _coverage
    from pdftoolkit.inventory import page_media_boxes

    records, error = _safe(inventory_pdf, path)
    if error:
        return [], f"Could not read the file: {error}"
    boxes, _ = _safe(page_media_boxes, path)
    boxes = boxes or []
    rows = []
    for rec, r in zip(records, records_as_dicts(records)):
        placed, covers = "not drawn", "not drawn"
        if rec.placements:
            biggest = max(rec.placements, key=lambda p: p.width_pts * p.height_pts)
            placed = f"{biggest.width_pts / 72:.1f} x {biggest.height_pts / 72:.1f}"
        if 0 < rec.page_number <= len(boxes):
            box = boxes[rec.page_number - 1]
            share = _coverage(rec, (box[2] - box[0]) * (box[3] - box[1]))
            if share is not None:
                covers = f"{share * 100:.0f}%"
        rows.append([
            r["page"], r["name"], r["pixel_size"][0], r["pixel_size"][1], r["color_space"],
            "yes" if r["has_transparency"] else "no", round(r["compressed_bytes"] / MB, 2),
            None if r["effective_dpi"] is None else round(r["effective_dpi"], 1),
            placed, covers,
        ])
    pages, _ = _safe(page_count, path)
    message = (f"{pages} page(s), {len(rows)} image(s)." if pages is not None
               else "Pages could not be counted.")
    return rows, message


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------

def compress_file(path: str, mode: str, max_dpi: float, quality: int, target_mb: float,
                  output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str | None, str]:
    """mode: 'Fixed resolution' or 'Fit to size'."""
    from pdftoolkit.compress import compress_pdf
    from pdftoolkit.fit import compress_to_target

    stem = Path(path).stem
    if mode == "Fit to size":
        out = _unique(Path(output_dir), f"{stem}_fit.pdf")
        report, error = _safe(compress_to_target, path, out, max_bytes=int(target_mb * MB))
        if error:
            return None, f"Error: {error}"
        return (str(out) if report["ok"] else None), report["message"]

    out = _unique(Path(output_dir), f"{stem}_{int(max_dpi)}dpi.pdf")
    report, error = _safe(compress_pdf, path, out, max_dpi=max_dpi, jpeg_quality=int(quality))
    if error:
        return None, f"Error: {error}"
    message = (f"Compressed to {report['output_bytes'] / MB:.1f} MB "
               f"(from {report['input_bytes'] / MB:.1f} MB) at {max_dpi:g} dpi, quality {int(quality)}.")
    if report["warnings"]:
        message += " Warnings: " + "; ".join(report["warnings"])
    return str(out), message


# ---------------------------------------------------------------------------
# Print copy
# ---------------------------------------------------------------------------

def print_copy_file(path: str, output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str | None, str]:
    from pdftoolkit.editing import drop_editing_data

    out = _unique(Path(output_dir), f"{Path(path).stem}_print.pdf")
    report, error = _safe(drop_editing_data, path, out)
    if error:
        return None, f"Error: {error}"
    removed = ", ".join(report["removed"]) or "nothing to remove"
    return str(out), (f"Print copy: {report['input_bytes'] / MB:.1f} MB -> "
                      f"{report['output_bytes'] / MB:.1f} MB. Removed: {removed}. "
                      "The original file is unchanged.")


# ---------------------------------------------------------------------------
# Merge and split
# ---------------------------------------------------------------------------

def merge_files(paths: list[str], output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str | None, str]:
    from pdftoolkit.merge_split import merge

    if not paths:
        return None, "Choose at least one PDF."
    out = _unique(Path(output_dir), "merged.pdf")
    report, error = _safe(merge, paths, out)
    if error:
        return None, f"Error: {error}"
    return str(out), report["message"]


def split_file(path: str, max_mb: float, output_dir: Path = DEFAULT_OUTPUT_DIR,
               pages_text: str = "") -> tuple[list[str], str]:
    """Split by size, or by page ranges such as '1-5,6-10' when pages_text is given."""
    from pdftoolkit.merge_split import split_by_pages, split_by_size

    if pages_text and pages_text.strip():
        folder = Path(output_dir) / f"{Path(path).stem}_pages"
        if folder.exists():
            shutil.rmtree(folder)
        report, error = _safe(split_by_pages, path, folder, pages_text)
    else:
        folder = Path(output_dir) / f"{Path(path).stem}_parts"
        if folder.exists():
            shutil.rmtree(folder)
        report, error = _safe(split_by_size, path, folder, int(max_mb * MB))
    if error:
        return [], f"Error: {error}"
    files = [p["file"] for p in report.get("parts", [])]
    return files, report["message"]


# ---------------------------------------------------------------------------
# Background removal, labels, pipeline
# ---------------------------------------------------------------------------

def remove_background_file(path: str, fill: str, pages_text: str, use_gemma: bool,
                           model_file: str | None, gemma_model: str,
                           output_dir: Path = DEFAULT_OUTPUT_DIR,
                           cover_limit_pct: float = 90) -> tuple[str | None, str]:
    from pdftoolkit.background import parse_fill, remove_background

    out = _unique(Path(output_dir), f"{Path(path).stem}_nobg.pdf")
    fill_value = (fill or "none").strip()
    try:
        parse_fill(fill_value)
        pages = _parse_pages(pages_text)
    except ValueError as exc:
        return None, f"Error: {exc}"

    if use_gemma:
        from pdftoolkit.classify import classify_and_remove

        report, error = _safe(classify_and_remove, path, out, fill=None if fill_value.lower() == "none" else fill_value,
                              model=gemma_model)
    else:
        report, error = _safe(remove_background, path, out, fill=fill_value, pages=pages,
                              model_file=model_file or None, cover_limit=cover_limit_pct / 100)
    if error:
        return None, f"Error: {error}"
    if not report["ok"]:
        return None, f"Stopped, no output written: {report['message']}"
    return str(out), report["message"]


def labels_file(path: str, gemma_model: str,
                output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[list[list[Any]], str, str | None]:
    """Rows of (page, label, reason) (headers in LABEL_HEADERS), a message, and the label report file."""
    from pdftoolkit.classify import classify_to_report

    report_path = _unique(Path(output_dir), f"{Path(path).stem}_labels.json")
    report, error = _safe(classify_to_report, path, report_path, model=gemma_model)
    if error:
        return [], f"Error: {error}", None
    rows = [[p["page"], p["label"], p["reason"]] for p in report["pages"]]
    return rows, report["message"], str(report_path)


def pipeline_file(path: str, remove_bg: bool, fill: str, max_mb: float, model_file: str | None,
                  output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str | None, str]:
    from pdftoolkit.pipeline import run_pipeline

    out = _unique(Path(output_dir), f"{Path(path).stem}_final.pdf")
    fill_value = (fill or "none").strip()
    report, error = _safe(run_pipeline, path, out, max_bytes=int(max_mb * MB), remove_bg=remove_bg,
                          fill=None if fill_value.lower() == "none" else fill_value,
                          model_file=model_file or None)
    if error:
        return None, f"Error: {error}"
    if not report["ok"]:
        return None, report["message"]
    return str(out), report["message"]


def remove_images_file(path: str, fill: str, images_text: str, model_file: str | None,
                       output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[str | None, str]:
    """Remove the background from named images only, e.g. '1:Im0'. The 90% rule does not apply."""
    from pdftoolkit.background import parse_fill, parse_image_list, remove_background

    out = _unique(Path(output_dir), f"{Path(path).stem}_nobg.pdf")
    fill_value = (fill or "none").strip()
    try:
        parse_fill(fill_value)
        selected = parse_image_list(images_text)
    except ValueError as exc:
        return None, f"Error: {exc}"
    if not selected:
        return None, "Choose at least one image, e.g. 1:Im0. Use Inspect to see the names."
    report, error = _safe(remove_background, path, out, selected_images=selected, fill=fill_value,
                          model_file=model_file or None)
    if error:
        return None, f"Error: {error}"
    if not report["ok"]:
        return None, f"Stopped, no output written: {report['message']}"
    return str(out), report["message"]