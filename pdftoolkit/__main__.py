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

    p_fit = sub.add_parser("fit", help="Compress until the output fits a size limit")
    p_fit.add_argument("input_pdf")
    p_fit.add_argument("output_pdf")
    p_fit.add_argument("--max-mb", type=float, default=2000, help="size limit in MB (default 2000)")
    p_fit.add_argument("--min-dpi", type=int, default=100, help="lowest DPI to try (default 100)")
    p_fit.add_argument("--report", default=None)

    p_merge = sub.add_parser("merge", help="Concatenate PDFs in the order given")
    p_merge.add_argument("inputs", nargs="+")
    p_merge.add_argument("-o", "--output", required=True)
    p_merge.add_argument("--report", default=None)

    p_split = sub.add_parser("split", help="Split a PDF into parts under a size limit")
    p_split.add_argument("input_pdf")
    p_split.add_argument("--max-mb", type=float, default=2000)
    p_split.add_argument("-o", "--output-dir", required=True)
    p_split.add_argument("--report", default=None)

    p_bg = sub.add_parser("removebg", help="Remove image backgrounds with rembg")
    p_bg.add_argument("input_pdf")
    p_bg.add_argument("output_pdf")
    p_bg.add_argument("--fill", default="none", help="'none' for transparency, or a colour like #FFFFFF")
    p_bg.add_argument("--pages", default=None, help="page numbers to process, e.g. 1 or 1,3")
    p_bg.add_argument("--model", default="isnet-general-use")
    p_bg.add_argument("--model-file", default=None, help="a local .onnx model file (for offline computers)")
    p_bg.add_argument("--report", default=None)
    p_bg.add_argument("--classify", action="store_true", help="let Gemma (via Ollama) choose the pages")
    p_bg.add_argument("--gemma-model", default="gemma3:4b")

    p_cls = sub.add_parser("classify", help="Label each page with Gemma (via Ollama). Changes nothing.")
    p_cls.add_argument("input_pdf")
    p_cls.add_argument("--gemma-model", default="gemma3:4b")
    p_cls.add_argument("--report", default=None)

    p_pipe = sub.add_parser("pipeline", help="Remove backgrounds, then fit to a size limit")
    p_pipe.add_argument("input_pdf")
    p_pipe.add_argument("output_pdf")
    p_pipe.add_argument("--remove-bg", action="store_true", help="remove backgrounds first")
    p_pipe.add_argument("--fill", default="none", help="'none' for transparency, or a colour like #FFFFFF")
    p_pipe.add_argument("--max-mb", type=float, default=2000)
    p_pipe.add_argument("--min-dpi", type=int, default=100)
    p_pipe.add_argument("--model", default="isnet-general-use")
    p_pipe.add_argument("--model-file", default=None)
    p_pipe.add_argument("--report", default=None)

    args = parser.parse_args(argv)
    if args.command == "removebg":
        return _cmd_removebg(args)
    if args.command == "pipeline":
        return _cmd_pipeline(args)
    if args.command == "classify":
        return _cmd_classify(args)
    if args.command == "merge":
        return _cmd_merge(args)
    if args.command == "split":
        return _cmd_split(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "compress":
        return _cmd_compress(args)
    if args.command == "fit":
        return _cmd_fit(args)
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


def _cmd_fit(args: argparse.Namespace) -> int:
    from pdftoolkit.fit import MB, compress_to_target

    report = compress_to_target(
        args.input_pdf,
        args.output_pdf,
        max_bytes=int(args.max_mb * MB),
        min_dpi=args.min_dpi,
        report_path=args.report,
    )
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"trials run: {len(report['trials'])}; report: {report['report_path']}\n")
    return 0 if report["ok"] else 1


def _cmd_merge(args: argparse.Namespace) -> int:
    from pdftoolkit.merge_split import merge

    report = merge(args.inputs, args.output, args.report)
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0


def _cmd_split(args: argparse.Namespace) -> int:
    from pdftoolkit.merge_split import MB, split_by_size

    report = split_by_size(args.input_pdf, args.output_dir, int(args.max_mb * MB), args.report)
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0 if report["ok"] else 1


def _cmd_classify(args: argparse.Namespace) -> int:
    from pdftoolkit.classify import classify_to_report

    report_path = args.report or Path(args.input_pdf).with_name(Path(args.input_pdf).stem + ".labels.json")
    report = classify_to_report(args.input_pdf, report_path, model=args.gemma_model)
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0 if report["ok"] else 1


def _cmd_removebg(args: argparse.Namespace) -> int:
    from pdftoolkit.background import main as background_main

    if args.classify:
        from pdftoolkit.classify import classify_and_remove

        report = classify_and_remove(
            args.input_pdf,
            args.output_pdf,
            fill=None if args.fill.lower() == "none" else args.fill,
            model=args.gemma_model,
            report_path=args.report,
        )
        sys.stdout.write(report["message"] + "\n")
        sys.stdout.write(f"report: {report['report_path']}\n")
        return 0 if report["ok"] else 1

    argv = [args.input_pdf, args.output_pdf, "--fill", args.fill, "--model", args.model]
    if args.pages:
        argv += ["--pages", args.pages]
    if args.model_file:
        argv += ["--model-file", args.model_file]
    if args.report:
        argv += ["--report", args.report]
    return background_main(argv)


def _cmd_pipeline(args: argparse.Namespace) -> int:
    from pdftoolkit.merge_split import MB
    from pdftoolkit.pipeline import run_pipeline

    report = run_pipeline(
        args.input_pdf,
        args.output_pdf,
        max_bytes=int(args.max_mb * MB),
        remove_bg=args.remove_bg,
        fill=None if args.fill.lower() == "none" else args.fill,
        model=args.model,
        model_file=args.model_file,
        min_dpi=args.min_dpi,
        report_path=args.report,
    )
    sys.stdout.write(report["message"] + "\n")
    sys.stdout.write(f"report: {report['report_path']}\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())