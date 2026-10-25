"""Inventory raster images in a PDF, including effective DPI from placement.

Contract (used by compress.py and locked by tests/test_inventory_fixes.py):

- inventory_pdf(path) returns one ImageRecord per image object per page.
- Placements are keyed by image object identity (its object number), never by
  name. A page image and a form image that share a name stay separate.
- A form drawn more than once records every placement. Only true cycles
  (a form that draws itself) are skipped.
- Inline images and images used inside patterns are reported with a `note`,
  so they are never silently dropped.
- Images drawn inside nested forms use the transform of the whole chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Name, Object, Pdf, parse_content_stream

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
Matrix = tuple[float, float, float, float, float, float]


@dataclass
class Placement:
    """One drawing of an image on a page (user-space points)."""

    width_pts: float
    height_pts: float
    ctm: Matrix


@dataclass
class ImageRecord:
    """One raster image object as used on one page."""

    page_number: int
    image_name: str
    width_px: int
    height_px: int
    color_space: str
    has_transparency: bool
    compressed_bytes: int
    bits_per_component: int
    filter: str | None
    placed_width_pts: float | None
    placed_height_pts: float | None
    effective_dpi_x: float | None
    effective_dpi_y: float | None
    effective_dpi: float | None
    object_gen: int | None = None
    is_inline: bool = False
    placements: list[Placement] = field(default_factory=list)
    note: str | None = None

    @property
    def pixel_size(self) -> tuple[int, int]:
        return (self.width_px, self.height_px)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def inventory_pdf(path: str | Path) -> list[ImageRecord]:
    """Return image records for every page, in page order."""
    path = Path(path)
    records: list[ImageRecord] = []
    with Pdf.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            records.extend(_page_records(index, _scan_page(page)))
    return records


def image_objects_on_page(page: pikepdf.Page) -> dict[int, Object]:
    """Map object number -> image stream for every image reachable from a page.

    Covers page resources and images inside nested forms. Used by compress.py
    to find the exact object a record refers to.
    """
    scan = _scan_page(page)
    return {num: entry.obj for num, entry in scan.entries.items()}


def page_media_boxes(path: str | Path) -> list[tuple[float, float, float, float]]:
    """Return each page's MediaBox as (llx, lly, urx, ury) in points."""
    path = Path(path)
    boxes: list[tuple[float, float, float, float]] = []
    with Pdf.open(path) as pdf:
        for page in pdf.pages:
            box = page.mediabox
            boxes.append((float(box[0]), float(box[1]), float(box[2]), float(box[3])))
    return boxes


def page_count(path: str | Path) -> int:
    with Pdf.open(path) as pdf:
        return len(pdf.pages)


def records_as_dicts(records: list[ImageRecord]) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        rows.append(
            {
                "page": r.page_number,
                "name": r.image_name,
                "pixel_size": [r.width_px, r.height_px],
                "color_space": r.color_space,
                "has_transparency": r.has_transparency,
                "compressed_bytes": r.compressed_bytes,
                "effective_dpi": r.effective_dpi,
                "effective_dpi_x": r.effective_dpi_x,
                "effective_dpi_y": r.effective_dpi_y,
                "placed_size_pts": [r.placed_width_pts, r.placed_height_pts],
                "filter": r.filter,
                "is_inline": r.is_inline,
                "note": r.note,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass
class _Entry:
    obj: Object
    first_name: str
    placements: list[Placement] = field(default_factory=list)
    note: str | None = None


@dataclass
class _PageScan:
    entries: dict[int, _Entry] = field(default_factory=dict)
    inline: list[tuple[Matrix, Any, bool]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _scan_page(page: pikepdf.Page) -> _PageScan:
    scan = _PageScan()
    resources = page.get("/Resources")
    if resources is None:
        resources = pikepdf.Dictionary()
    _walk(page, resources, IDENTITY, scan, ancestors=(), in_pattern=False)

    # Images listed in the page resources but never drawn are still reported.
    for name, obj in _xobject_dict(resources).items():
        if _is_image(obj):
            num = _objnum(obj)
            if num is not None and num not in scan.entries:
                scan.entries[num] = _Entry(
                    obj=obj,
                    first_name=name,
                    note="in page resources but not drawn on this page",
                )
    return scan


def _walk(
    owner: Any,
    resources: Any,
    ctm: Matrix,
    scan: _PageScan,
    ancestors: tuple[int, ...],
    in_pattern: bool,
) -> None:
    """Walk one content stream, following nested forms and tiling patterns."""
    try:
        ops = list(parse_content_stream(owner))
    except Exception as exc:  # unreadable content stream: report, do not crash
        scan.warnings.append(f"could not parse a content stream: {exc}")
        return

    xobjects = _xobject_dict(resources)
    patterns = _pattern_dict(resources)
    stack: list[Matrix] = []
    current = ctm

    for operands, operator in ops:
        op = str(operator)

        if op == "q":
            stack.append(current)
        elif op == "Q":
            current = stack.pop() if stack else ctm
        elif op == "cm" and len(operands) >= 6:
            current = _mat_mul(current, tuple(float(x) for x in operands[:6]))
        elif op == "INLINE IMAGE" and operands:
            scan.inline.append((current, operands[0], in_pattern))
        elif op in ("scn", "SCN") and operands and isinstance(operands[-1], Name):
            pattern = patterns.get(str(operands[-1]))
            if pattern is not None and not in_pattern and pattern.get("/PatternType") == 1:
                num = _objnum(pattern)
                if num is not None and num not in ancestors:
                    pattern_res = pattern.get("/Resources")
                    if pattern_res is None:
                        pattern_res = resources
                    _walk(pattern, pattern_res, current, scan, ancestors + (num,), True)
        elif op == "Do" and operands:
            name = str(operands[0])
            obj = xobjects.get(name)
            if obj is None:
                continue
            if _is_image(obj):
                _add_placement(scan, name, obj, current, in_pattern)
            elif _is_form(obj):
                num = _objnum(obj)
                if num is not None and num in ancestors:
                    scan.warnings.append(f"form {name} draws itself; skipped the repeat")
                    continue
                form_matrix = _matrix_or_identity(obj.get("/Matrix"))
                form_res = obj.get("/Resources")
                if form_res is None:
                    form_res = resources
                child_ancestors = ancestors + ((num,) if num is not None else ())
                _walk(obj, form_res, _mat_mul(current, form_matrix), scan, child_ancestors, in_pattern)


def _add_placement(
    scan: _PageScan,
    name: str,
    obj: Object,
    ctm: Matrix,
    in_pattern: bool,
) -> None:
    num = _objnum(obj)
    if num is None:
        scan.warnings.append(f"image {name} is a direct object; not inventoried")
        return
    entry = scan.entries.get(num)
    if entry is None:
        entry = _Entry(obj=obj, first_name=name)
        scan.entries[num] = entry
    if in_pattern:
        entry.note = "used inside a pattern; placement not measured"
        return
    entry.placements.append(_placement_from_ctm(ctm))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _page_records(page_number: int, scan: _PageScan) -> list[ImageRecord]:
    records: list[ImageRecord] = []
    for num, entry in scan.entries.items():
        records.append(
            _record_from_image(
                page_number,
                entry.first_name,
                entry.obj,
                entry.placements,
                note=entry.note,
                object_gen=num,
            )
        )
    for index, (ctm, inline, in_pattern) in enumerate(scan.inline, start=1):
        records.append(_record_from_inline(page_number, index, ctm, inline, in_pattern))
    records.sort(key=lambda r: (r.is_inline, r.image_name))
    return records


def _record_from_image(
    page_number: int,
    image_name: str,
    obj: Object,
    placements: list[Placement],
    *,
    note: str | None = None,
    object_gen: int | None = None,
) -> ImageRecord:
    width_px = int(obj.get("/Width", 0) or 0)
    height_px = int(obj.get("/Height", 0) or 0)
    bpc = int(obj.get("/BitsPerComponent", 8) or 8)
    return _build_record(
        page_number=page_number,
        image_name=image_name,
        width_px=width_px,
        height_px=height_px,
        color_space=_color_space_name(obj.get("/ColorSpace")),
        has_transparency="/SMask" in obj or "/Mask" in obj,
        compressed_bytes=_compressed_size(obj),
        bits_per_component=bpc,
        filt=_filter_name(obj.get("/Filter")),
        placements=placements,
        note=note,
        object_gen=object_gen,
        is_inline=False,
    )


def _record_from_inline(
    page_number: int,
    index: int,
    ctm: Matrix,
    inline: Any,
    in_pattern: bool,
) -> ImageRecord:
    d = inline.obj
    placements = [] if in_pattern else [_placement_from_ctm(ctm)]
    note = "inline image; compression does not rewrite it"
    if in_pattern:
        note = "inline image inside a pattern; placement not measured"
    try:
        compressed = len(inline.read_raw_bytes())
    except Exception:
        compressed = 0
    return _build_record(
        page_number=page_number,
        image_name=f"inline#{index}",
        width_px=int(inline.width),
        height_px=int(inline.height),
        color_space=_color_space_name(d.get("/ColorSpace")),
        has_transparency=bool(inline.image_mask),
        compressed_bytes=compressed,
        bits_per_component=int(d.get("/BitsPerComponent", 8) or 8),
        filt=_filter_name(d.get("/Filter")),
        placements=placements,
        note=note,
        object_gen=None,
        is_inline=True,
    )


def _build_record(
    *,
    page_number: int,
    image_name: str,
    width_px: int,
    height_px: int,
    color_space: str,
    has_transparency: bool,
    compressed_bytes: int,
    bits_per_component: int,
    filt: str | None,
    placements: list[Placement],
    note: str | None,
    object_gen: int | None,
    is_inline: bool,
) -> ImageRecord:
    placed_w, placed_h = _largest_placement(placements)
    dpi_x = dpi_y = dpi = None
    if placed_w and placed_w > 0 and width_px:
        dpi_x = width_px / (placed_w / 72.0)
    if placed_h and placed_h > 0 and height_px:
        dpi_y = height_px / (placed_h / 72.0)
    if dpi_x is not None and dpi_y is not None:
        dpi = max(dpi_x, dpi_y)
    else:
        dpi = dpi_x if dpi_x is not None else dpi_y

    return ImageRecord(
        page_number=page_number,
        image_name=image_name,
        width_px=width_px,
        height_px=height_px,
        color_space=color_space,
        has_transparency=has_transparency,
        compressed_bytes=compressed_bytes,
        bits_per_component=bits_per_component,
        filter=filt,
        placed_width_pts=placed_w,
        placed_height_pts=placed_h,
        effective_dpi_x=dpi_x,
        effective_dpi_y=dpi_y,
        effective_dpi=dpi,
        object_gen=object_gen,
        is_inline=is_inline,
        placements=list(placements),
        note=note,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _placement_from_ctm(ctm: Matrix) -> Placement:
    # An image is drawn in a 1x1 unit square, so the CTM's columns give its size.
    return Placement(_hypot(ctm[0], ctm[1]), _hypot(ctm[2], ctm[3]), ctm)


def _largest_placement(placements: list[Placement]) -> tuple[float | None, float | None]:
    if not placements:
        return None, None
    best = max(placements, key=lambda p: p.width_pts * p.height_pts)
    return best.width_pts, best.height_pts


def _objnum(obj: Any) -> int | None:
    """Object number of an indirect object, or None for direct objects."""
    try:
        num, gen = obj.objgen
    except Exception:
        return None
    if num == 0 and gen == 0:
        return None
    return int(num)


def _xobject_dict(resources: Any) -> dict[str, Object]:
    if resources is None:
        return {}
    try:
        xobj = resources.get("/XObject")
    except Exception:
        return {}
    if xobj is None:
        return {}
    return {str(k): v for k, v in xobj.items()}


def _pattern_dict(resources: Any) -> dict[str, Object]:
    if resources is None:
        return {}
    try:
        pat = resources.get("/Pattern")
    except Exception:
        return {}
    if pat is None:
        return {}
    return {str(k): v for k, v in pat.items()}


def _is_image(obj: Object) -> bool:
    try:
        return obj.get("/Subtype") == Name.Image
    except Exception:
        return False


def _is_form(obj: Object) -> bool:
    try:
        return obj.get("/Subtype") == Name.Form
    except Exception:
        return False


def _matrix_or_identity(value: Any) -> Matrix:
    if value is None:
        return IDENTITY
    try:
        vals = tuple(float(x) for x in value)
    except Exception:
        return IDENTITY
    return vals if len(vals) == 6 else IDENTITY


def _color_space_name(cs: Any) -> str:
    if cs is None:
        return "unknown"
    if isinstance(cs, Name):
        return str(cs)
    if isinstance(cs, pikepdf.Array) and len(cs) > 0:
        head = str(cs[0])
        if head == "/ICCBased" and len(cs) > 1:
            try:
                n = int(cs[1].get("/N", 0) or 0)
            except Exception:
                n = 0
            return f"/ICCBased({n})"
        if head == "/Indexed":
            base = _color_space_name(cs[1]) if len(cs) > 1 else "unknown"
            return f"/Indexed({base})"
        return head
    return str(cs)


def _filter_name(filt: Any) -> str | None:
    if filt is None:
        return None
    if isinstance(filt, Name):
        return str(filt)
    if isinstance(filt, pikepdf.Array):
        return "+".join(str(x) for x in filt)
    return str(filt)


def _compressed_size(obj: Object) -> int:
    try:
        return len(obj.read_raw_bytes())
    except Exception:
        try:
            return int(obj.get("/Length", 0) or 0)
        except Exception:
            return 0


def _mat_mul(current: Matrix, cm: Matrix) -> Matrix:
    """Return cm x current: the matrix a `cm` operator produces in PDF.

    PDF applies the new matrix first, then the existing CTM, so the
    combined matrix is cm x current in row-vector notation.
    """
    a1, b1, c1, d1, e1, f1 = current
    a2, b2, c2, d2, e2, f2 = cm
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply_matrix(m: Matrix, x: float, y: float) -> tuple[float, float]:
    """Map a point through a PDF matrix. Used by tests and debugging."""
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _hypot(a: float, b: float) -> float:
    return (a * a + b * b) ** 0.5