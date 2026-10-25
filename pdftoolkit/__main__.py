"""Command-line interface: python -m pdftoolkit <command> ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdftoolkit.reporting import default_report_path, format_summary, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdftoolkit",
        description="Local, offline PDF toolkit (PDFme).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="List images, sizes, and effective DPI")
    p_inspect.add_argument("input_pdf")
    p_inspect.add_argument("--report", default=None)

    p_compress = sub.add_parser("compress", help="Downsample images above a maximum DPI")
    p_compress.add_argument("input_pdf")
    p_compress.add_argument("output_pdf")
    p_compress.add_argument("--max-dpi", type=float, default=150)
    p_compress.add_argument("--quality", type=int, default=90)
    p_compress.add_argument("--report", default=None)

    args = parser.parse_args(argv)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "compress":
        return _cmd_compress(args)
    parser.error(f"unknown command {args.command}")
    return 2


def _cmd_inspect(args: argparse.Namespace) -> int:
    from pdftoolkit.inventory import inventory_pdf, page_count, records_as_dicts

    records = inventory_pdf(args.input_pdf)
    report = {
        "operation": "inspect",
        "ok": True,
        "input": args.input_pdf,
        "page_count": page_count(args.input_pdf),
        "images": records_as_dicts(records),
    }
    report_path = args.report or Path(args.input_pdf).with_name(Path(args.input_pdf).name + ".inspect.json")
    write_report(report, report_path)
    sys.stdout.write(format_summary(report))
    return 0


def _cmd_compress(args: argparse.Namespace) -> int:
    from pdftoolkit.compress import compress_pdf

    report_path = args.report or default_report_path(args.output_pdf)
    report = compress_pdf(
        args.input_pdf,
        args.output_pdf,
        max_dpi=args.max_dpi,
        jpeg_quality=args.quality,
        report_path=report_path,
    )
    sys.stdout.write(format_summary(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
