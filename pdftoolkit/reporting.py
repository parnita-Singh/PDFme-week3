"""JSON + readable text reports for every PDFme operation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_report_path(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    return output_path.with_name(output_path.name + ".report.json")


def write_report(report: dict[str, Any], json_path: str | Path | None) -> Path | None:
    """Write report JSON and a sibling .txt summary. Returns the JSON path."""
    if json_path is None:
        return None
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    txt_path = json_path.with_name(json_path.stem + ".txt") if json_path.suffix.lower() == ".json" else json_path.with_suffix(".txt")
    if txt_path == json_path:
        txt_path = json_path.with_name(json_path.name + ".txt")
    txt_path.write_text(format_summary(report), encoding="utf-8")
    return json_path


def format_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    op = report.get("operation", "operation")
    ok = report.get("ok", True)
    lines.append(f"PDFme report: {op}")
    lines.append(f"Status: {'ok' if ok else 'FAILED'}")
    for key in ("input", "output", "message", "chosen_dpi", "chosen_quality", "max_dpi", "jpeg_quality"):
        if key in report and report[key] is not None:
            lines.append(f"{key}: {report[key]}")
    if "input_bytes" in report or "output_bytes" in report:
        lines.append(
            f"file bytes: {report.get('input_bytes')} -> {report.get('output_bytes')}"
        )
    images = report.get("images") or report.get("items") or []
    if images:
        lines.append("")
        lines.append("Images:")
        for item in images:
            lines.append(_format_image_row(item))
    extra = report.get("notes") or []
    if extra:
        lines.append("")
        lines.append("Notes:")
        for note in extra:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _format_image_row(item: dict[str, Any]) -> str:
    page = item.get("page")
    name = item.get("name")
    action = item.get("action")
    pb = item.get("pixels_before")
    pa = item.get("pixels_after")
    db = item.get("dpi_before")
    da = item.get("dpi_after")
    bb = item.get("bytes_before")
    ba = item.get("bytes_after")
    dpi_b = f"{db:.1f}" if isinstance(db, (int, float)) else db
    dpi_a = f"{da:.1f}" if isinstance(da, (int, float)) else da
    return (
        f"  page {page} {name}: {action}; "
        f"px {pb} -> {pa}; dpi {dpi_b} -> {dpi_a}; bytes {bb} -> {ba}"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")
