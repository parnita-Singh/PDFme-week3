"""Compress a PDF to a target size, measuring the real output at every step.

The trials run in a temporary folder. The output path is written only when a
trial fits the limit, so a failed run leaves no output file behind. The input
file is never changed.

Usage:
    python -m pdftoolkit.fit input.pdf output.pdf --max-mb 2000
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pdftoolkit.compress import compress_pdf
from pdftoolkit.reporting import default_report_path, write_report

DPI_STEPS = (300, 250, 200, 150, 120, 100)
QUALITY_STEPS = (92, 88, 84, 80)
MB = 1_000_000  # the CLI's MB is decimal, so --max-mb 2000 is 2,000,000,000 bytes


def _dpi_plan(dpi_steps: tuple[int, ...], min_dpi: int) -> list[int]:
    """DPI values to try, highest first. min_dpi is always the last one tried."""
    steps = {d for d in dpi_steps if d > min_dpi}
    steps.add(min_dpi)
    return sorted(steps, reverse=True)


def _publish(source: Path, destination: Path) -> None:
    """Copy source to destination in one step, so a half-written file never shows up."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    shutil.copyfile(source, partial)
    os.replace(partial, destination)


def compress_to_target(
    input_path: str | Path,
    output_path: str | Path,
    max_bytes: int,
    min_dpi: int = 100,
    quality_steps: tuple[int, ...] = QUALITY_STEPS,
    dpi_steps: tuple[int, ...] = DPI_STEPS,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Find the highest-quality setting whose real output is at or under max_bytes.

    DPI is tried from high to low. For each DPI, quality is tried from high to low.
    The first setting that fits is written to output_path. If nothing fits, no
    output file is written, and the report says how close the smallest result came.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero.")
    if min_dpi <= 0:
        raise ValueError("min_dpi must be greater than zero.")
    qualities = sorted(set(quality_steps), reverse=True)
    if not qualities or any(not 1 <= q <= 95 for q in qualities):
        raise ValueError("quality_steps must be between 1 and 95.")
    if report_path is None:
        report_path = default_report_path(output_path)

    trials: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    smallest: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="pdfme_fit_") as tmp_name:
        tmp = Path(tmp_name)
        for dpi in _dpi_plan(dpi_steps, min_dpi):
            for quality in qualities:
                name = f"dpi{dpi}_q{quality}"
                trial_pdf = tmp / f"{name}.pdf"
                result = compress_pdf(
                    input_path,
                    trial_pdf,
                    max_dpi=dpi,
                    jpeg_quality=quality,
                    report_path=tmp / f"{name}.json",
                )
                size = trial_pdf.stat().st_size
                fits = bool(result["ok"]) and size <= max_bytes
                trials.append({
                    "max_dpi": dpi,
                    "jpeg_quality": quality,
                    "output_bytes": size,
                    "ok": result["ok"],
                    "fits": fits,
                    "warnings": result["warnings"],
                })
                if result["ok"] and (smallest is None or size < smallest["output_bytes"]):
                    smallest = {"max_dpi": dpi, "jpeg_quality": quality, "output_bytes": size}
                if fits:
                    chosen = {
                        "max_dpi": dpi,
                        "jpeg_quality": quality,
                        "output_bytes": size,
                        "page_count": result["page_count"],
                        "page_sizes": result["page_sizes"],
                        "images": result["images"],
                    }
                    _publish(trial_pdf, output_path)
                    break
            if chosen is not None:
                break

    ok = chosen is not None
    if ok:
        message = (
            f"Fits: max_dpi {chosen['max_dpi']}, quality {chosen['jpeg_quality']}, "
            f"{chosen['output_bytes'] / MB:.1f} MB (limit {max_bytes / MB:.1f} MB)."
        )
    elif smallest is None:
        message = "No setting could be written: every trial reported errors. See the trials list."
    else:
        needed = smallest["output_bytes"] - max_bytes
        message = (
            f"No setting fits. The smallest result was {smallest['output_bytes'] / MB:.1f} MB "
            f"at {smallest['max_dpi']} dpi, quality {smallest['jpeg_quality']}, "
            f"which is {needed / MB:.1f} MB over the limit of {max_bytes / MB:.1f} MB. "
            "No output file was written. To fit, raise the limit, lower min_dpi, "
            "or split the file (Phase 3)."
        )

    report: dict[str, Any] = {
        "operation": "fit",
        "ok": ok,
        "input": str(input_path),
        "output": str(output_path) if ok else None,
        "max_bytes": max_bytes,
        "min_dpi": min_dpi,
        "input_bytes": input_path.stat().st_size,
        "output_bytes": chosen["output_bytes"] if ok else None,
        "chosen": (
            {"max_dpi": chosen["max_dpi"], "jpeg_quality": chosen["jpeg_quality"]} if ok else None
        ),
        "smallest": smallest,
        "needed_reduction_bytes": (
            None if ok or smallest is None else smallest["output_bytes"] - max_bytes
        ),
        "trials": trials,
        "message": message,
    }
    if ok:
        report["page_count"] = chosen["page_count"]
        report["page_sizes"] = chosen["page_sizes"]
        report["images"] = chosen["images"]
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compress a PDF to fit a size limit. The input is not changed.",
    )
    parser.add_argument("input", help="PDF to read (not changed)")
    parser.add_argument("output", help="new PDF to write, only if a setting fits")
    parser.add_argument("--max-mb", type=float, default=2000, help="size limit in MB (default 2000)")
    parser.add_argument("--min-dpi", type=int, default=100, help="lowest DPI to try (default 100)")
    parser.add_argument("--report", help="optional JSON report path")
    args = parser.parse_args(argv)

    report = compress_to_target(
        args.input,
        args.output,
        max_bytes=int(args.max_mb * MB),
        min_dpi=args.min_dpi,
        report_path=args.report,
    )
    print(report["message"])
    print(f"trials run: {len(report['trials'])}; report: {report['report_path']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())