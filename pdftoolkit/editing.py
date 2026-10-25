"""Make a print copy of a PDF without Adobe editing data.

Photoshop and Illustrator store the layered design inside each page's
/PieceInfo entry. Printing never reads that entry, so removing it does not
change the printed page. The page content and the images are left untouched.

The input file is never changed. The output is always a new file.

Usage:
    python -m pdftoolkit.editing input.pdf print.pdf
    python -m pdftoolkit.editing input.pdf print.pdf --report print_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pikepdf


def drop_editing_data(
    input_path: str | Path,
    output_path: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a copy of input_path with /PieceInfo removed, and return a report."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    removed: list[str] = []

    with pikepdf.open(input_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            if "/PieceInfo" in page.obj:
                del page.obj["/PieceInfo"]
                removed.append(f"page {number} /PieceInfo")
        if "/PieceInfo" in pdf.Root:
            del pdf.Root["/PieceInfo"]
            removed.append("catalog /PieceInfo")

        # Only objects still reachable from the document are written, so the
        # editing data is dropped from the file along with its references.
        pdf.save(
            output_path,
            compress_streams=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            recompress_flate=True,
        )

    with pikepdf.open(output_path) as out:
        output_pages = len(out.pages)

    report: dict[str, Any] = {
        "operation": "print_copy",
        "ok": True,
        "input": str(input_path),
        "output": str(output_path),
        "input_bytes": input_path.stat().st_size,
        "output_bytes": output_path.stat().st_size,
        "removed": removed,
        "page_count": output_pages,
    }
    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Make a print copy without Adobe editing data. The input is not changed.",
    )
    parser.add_argument("input", help="PDF to read (not changed)")
    parser.add_argument("output", help="new PDF to write")
    parser.add_argument("--report", help="optional JSON report path")
    args = parser.parse_args(argv)

    report = drop_editing_data(args.input, args.output, args.report)
    removed = ", ".join(report["removed"]) or "nothing to remove"
    print(
        f"print copy: {report['input_bytes'] / 1e6:.1f} MB -> "
        f"{report['output_bytes'] / 1e6:.1f} MB; removed: {removed}"
    )


if __name__ == "__main__":
    main()