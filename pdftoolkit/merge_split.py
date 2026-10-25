"""Merge PDFs, and split a PDF into parts that each fit a size limit.

Merge and split use pypdf. Inputs are never changed. Every output is written
to a temporary name first and then moved into place, so a failed run never
leaves a half-written file behind.

Usage:
    python -m pdftoolkit.merge_split merge a.pdf b.pdf -o out.pdf
    python -m pdftoolkit.merge_split split in.pdf --max-mb 2000 -o outdir/
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from pypdf import PdfReader, PdfWriter

from pdftoolkit.reporting import default_report_path, write_report

MB = 1_000_000  # decimal, matching the rest of the toolkit


def _check_not_an_input(outputs: Sequence[Path], inputs: Sequence[Path]) -> None:
    input_paths = {p.resolve() for p in inputs}
    for out in outputs:
        if out.resolve() in input_paths:
            raise ValueError(f"Refusing to overwrite an input file: {out}")


def _write_atomic(writer: PdfWriter, destination: Path) -> int:
    """Write the PDF to a partial file, then move it into place. Returns its size."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    with partial.open("wb") as fh:
        writer.write(fh)
    os.replace(partial, destination)
    return destination.stat().st_size


def _pages_writer(reader: PdfReader, indices: Sequence[int]) -> PdfWriter:
    writer = PdfWriter()
    for i in indices:
        writer.add_page(reader.pages[i])
    return writer


def _measure(reader: PdfReader, indices: Sequence[int], scratch: Path) -> int:
    """The real size, in bytes, of a PDF made of these pages."""
    scratch.parent.mkdir(parents=True, exist_ok=True)
    with scratch.open("wb") as fh:
        _pages_writer(reader, indices).write(fh)
    return scratch.stat().st_size


def _plan_parts(
    reader: PdfReader, max_bytes: int, scratch: Path
) -> tuple[list[list[int]] | None, dict[str, Any] | None]:
    """Group pages into parts, adding one page at a time and measuring each real size.

    Returns (parts, None) on success. If one page is over the limit on its own,
    returns (None, problem) and nothing else is done.
    """
    parts: list[list[int]] = []
    current: list[int] = []
    for i in range(len(reader.pages)):
        candidate = current + [i]
        size = _measure(reader, candidate, scratch)
        if size <= max_bytes:
            current = candidate
            continue
        if not current:  # the candidate is just this page, and it is already too big
            return None, {"page": i + 1, "bytes": size}
        parts.append(current)
        current = [i]
        alone = _measure(reader, current, scratch)
        if alone > max_bytes:
            return None, {"page": i + 1, "bytes": alone}
    if current:
        parts.append(current)
    return parts, None


def _page_range(indices: Sequence[int]) -> str:
    first, last = indices[0] + 1, indices[-1] + 1
    return f"{first}" if first == last else f"{first}-{last}"


def merge(
    input_paths: Sequence[str | Path],
    output_path: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Concatenate the pages of the input PDFs in the order given."""
    inputs = [Path(p) for p in input_paths]
    output = Path(output_path)
    if not inputs:
        raise ValueError("merge needs at least one input PDF.")
    _check_not_an_input([output], inputs)
    if report_path is None:
        report_path = default_report_path(output)

    writer = PdfWriter()
    sources: list[dict[str, Any]] = []
    for path in inputs:
        reader = PdfReader(str(path))
        writer.append(reader)
        sources.append({
            "input": str(path),
            "pages": len(reader.pages),
            "input_bytes": path.stat().st_size,
        })

    expected_pages = sum(s["pages"] for s in sources)
    if len(writer.pages) != expected_pages:
        raise RuntimeError(
            f"Merged {len(writer.pages)} pages, expected {expected_pages}. Nothing was written."
        )
    output_bytes = _write_atomic(writer, output)

    check = PdfReader(str(output))
    if len(check.pages) != expected_pages:
        raise RuntimeError(
            f"Saved file has {len(check.pages)} pages, expected {expected_pages}."
        )

    message = (
        f"Merged {len(inputs)} files into {output.name}: {expected_pages} pages "
        f"({output_bytes / MB:.1f} MB)."
    )
    report: dict[str, Any] = {
        "operation": "merge",
        "ok": True,
        "output": str(output),
        "page_count": expected_pages,
        "output_bytes": output_bytes,
        "sources": sources,
        "message": message,
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def split_by_size(
    input_path: str | Path,
    output_dir: str | Path,
    max_bytes: int,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Split a PDF into parts that are each at or under max_bytes.

    If a single page is over max_bytes, no parts are written and the report says which page.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero.")
    if report_path is None:
        report_path = output_dir / "split_report.json"

    reader = PdfReader(str(input_path))
    total_pages = len(reader.pages)
    report: dict[str, Any] = {
        "operation": "split",
        "input": str(input_path),
        "output_dir": str(output_dir),
        "max_bytes": max_bytes,
        "input_bytes": input_path.stat().st_size,
        "page_count": total_pages,
        "parts": [],
    }

    with tempfile.TemporaryDirectory(prefix="pdfme_split_") as tmp_name:
        tmp = Path(tmp_name)
        parts, problem = _plan_parts(reader, max_bytes, tmp / "candidate.pdf")

        if problem is not None:
            report["ok"] = False
            report["problem_page"] = problem["page"]
            report["problem_page_bytes"] = problem["bytes"]
            report["message"] = (
                f"Page {problem['page']} alone is {problem['bytes'] / MB:.1f} MB, over the limit "
                f"of {max_bytes / MB:.1f} MB. No parts were written. Raise the limit, or "
                "compress that page first."
            )
            write_report(report, report_path)
            report["report_path"] = str(report_path)
            return report

        # Write every part to the temporary folder and check it before anything
        # is moved into the output folder.
        staged: list[tuple[Path, str, Sequence[int], int]] = []
        for number, indices in enumerate(parts, start=1):
            name = f"{input_path.stem}_part{number:02d}.pdf"
            staged_path = tmp / "parts" / name
            size = _write_atomic(_pages_writer(reader, indices), staged_path)
            if size > max_bytes:  # cannot happen after planning; checked anyway
                raise RuntimeError(f"{name} is {size} bytes, over the limit. Nothing was written.")
            staged.append((staged_path, name, indices, size))

        written_pages = sum(len(PdfReader(str(p)).pages) for p, _, _, _ in staged)
        if written_pages != total_pages:
            raise RuntimeError(
                f"Parts have {written_pages} pages in total, expected {total_pages}. "
                "Nothing was written."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        for staged_path, name, indices, size in staged:
            destination = output_dir / name
            os.replace(staged_path, destination)
            report["parts"].append({
                "file": str(destination),
                "pages": _page_range(indices),
                "page_count": len(indices),
                "bytes": size,
            })

    report["ok"] = True
    lines = [
        f"Split {input_path.name} ({total_pages} pages) into {len(parts)} parts, "
        f"each at or under {max_bytes / MB:.1f} MB:"
    ]
    lines += [
        f"  {Path(p['file']).name}: pages {p['pages']} ({p['bytes'] / MB:.1f} MB)"
        for p in report["parts"]
    ]
    report["message"] = "\n".join(lines)
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def parse_ranges(text: str | None, total_pages: int) -> list[list[int]]:
    """'1-5, 6-10, 12' -> [[0..4], [5..9], [11]] as zero-based page indices, one list per part.

    Pages are counted from 1. Raises ValueError with a message the page can show.
    """
    if text is None or not text.strip():
        raise ValueError("Enter at least one page range, e.g. 1-5 or 1-5,6-10.")
    groups: list[list[int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        first_text, dash, last_text = part.partition("-")
        try:
            first = int(first_text)
            last = int(last_text) if dash else first
        except ValueError:
            raise ValueError(f"Cannot read '{part}'. Use numbers like 1-5 or 12.") from None
        if dash and not last_text.strip():
            raise ValueError(f"'{part}' is missing the last page. Use something like {first}-{first + 4}.")
        if first < 1 or last > total_pages or first > last:
            raise ValueError(f"'{part}' is outside the document, which has {total_pages} pages.")
        groups.append(list(range(first - 1, last)))
    if not groups:
        raise ValueError("Enter at least one page range, e.g. 1-5 or 1-5,6-10.")
    return groups


def split_by_pages(
    input_path: str | Path,
    output_dir: str | Path,
    ranges_text: str | None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write one PDF per page range, e.g. '1-5, 6-10, 12'. The input is not changed."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if report_path is None:
        report_path = output_dir / "split_report.json"

    reader = PdfReader(str(input_path))
    total_pages = len(reader.pages)
    report: dict[str, Any] = {
        "operation": "split_pages",
        "input": str(input_path),
        "output_dir": str(output_dir),
        "ranges": ranges_text,
        "input_bytes": input_path.stat().st_size,
        "page_count": total_pages,
        "parts": [],
    }
    try:
        groups = parse_ranges(ranges_text, total_pages)
    except ValueError as exc:
        report.update(ok=False, message=str(exc))
        write_report(report, report_path)
        report["report_path"] = str(report_path)
        return report

    # Output names always start with the input's name plus "_partNN", so they can never be the input file.
    names = [f"{input_path.stem}_part{n:02d}_p{_page_range(g)}.pdf" for n, g in enumerate(groups, start=1)]

    with tempfile.TemporaryDirectory(prefix="pdfme_pages_") as tmp_name:
        tmp = Path(tmp_name)
        staged = []
        for name, indices in zip(names, groups):
            size = _write_atomic(_pages_writer(reader, indices), tmp / "parts" / name)
            staged.append((tmp / "parts" / name, name, indices, size))

        output_dir.mkdir(parents=True, exist_ok=True)
        for staged_path, name, indices, size in staged:
            destination = output_dir / name
            os.replace(staged_path, destination)
            report["parts"].append({
                "file": str(destination),
                "pages": _page_range(indices),
                "page_count": len(indices),
                "bytes": size,
            })

    report["ok"] = True
    lines = [f"Split {input_path.name} into {len(groups)} part(s) by page range:"]
    lines += [
        f"  {Path(p['file']).name}: pages {p['pages']} ({p['bytes'] / MB:.1f} MB)"
        for p in report["parts"]
    ]
    report["message"] = "\n".join(lines)
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge PDFs, or split a PDF by size or page range.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_merge = sub.add_parser("merge", help="Concatenate PDFs in the order given")
    p_merge.add_argument("inputs", nargs="+")
    p_merge.add_argument("-o", "--output", required=True)
    p_merge.add_argument("--report", default=None)

    p_split = sub.add_parser("split", help="Split a PDF into parts under a size limit")
    p_split.add_argument("input_pdf")
    p_split.add_argument("--max-mb", type=float, default=2000)
    p_split.add_argument("--pages", default=None, help="page ranges instead of size, e.g. 1-5,6-10,12")
    p_split.add_argument("-o", "--output-dir", required=True)
    p_split.add_argument("--report", default=None)

    args = parser.parse_args(argv)
    if args.command == "merge":
        report = merge(args.inputs, args.output, args.report)
    elif args.pages:
        report = split_by_pages(args.input_pdf, args.output_dir, args.pages, args.report)
    else:
        report = split_by_size(
            args.input_pdf, args.output_dir, int(args.max_mb * MB), args.report
        )
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())