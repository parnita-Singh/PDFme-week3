"""Remove backgrounds, then compress to a size limit: one command, two measured steps.

If the background step reports an error, the pipeline stops and writes no output.
The input file is never changed.

Usage:
    python -m pdftoolkit pipeline input.pdf output.pdf --remove-bg --max-mb 2000
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pdftoolkit.background import DEFAULT_MODEL, remove_background
from pdftoolkit.fit import MB, compress_to_target
from pdftoolkit.reporting import default_report_path, write_report


def run_pipeline(
    input_path: str | Path,
    output_path: str | Path,
    max_bytes: int,
    remove_bg: bool = True,
    fill: str | None = None,
    model: str = DEFAULT_MODEL,
    model_file: str | Path | None = None,
    min_dpi: int = 100,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("Refusing to overwrite the input file; choose a different output path.")
    if report_path is None:
        report_path = default_report_path(output_path)

    steps: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="pdfme_pipeline_") as tmp_name:
        source = input_path
        if remove_bg:
            staged = Path(tmp_name) / "background_removed.pdf"
            bg = remove_background(
                input_path, staged, fill=fill, model=model, model_file=model_file,
                report_path=Path(tmp_name) / "background.json",
            )
            steps["remove_background"] = bg
            if not bg["ok"]:
                message = (
                    "Background removal reported errors, so the pipeline stopped. "
                    "No output file was written. See the background step in the report."
                )
                report = _finish(input_path, output_path, ok=False, steps=steps, message=message,
                                 report_path=report_path)
                return report
            source = staged

        fit = compress_to_target(
            source, output_path, max_bytes=max_bytes, min_dpi=min_dpi,
            report_path=Path(tmp_name) / "fit.json",
        )
        steps["fit"] = fit

    if fit["ok"]:
        message = f"Pipeline finished. {fit['message']}"
    else:
        message = f"Pipeline stopped at the size step. {fit['message']}"
    return _finish(input_path, output_path, ok=fit["ok"], steps=steps, message=message,
                   report_path=report_path)


def _finish(input_path, output_path, ok, steps, message, report_path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "operation": "pipeline",
        "ok": ok,
        "input": str(input_path),
        "output": str(output_path) if ok else None,
        "steps": {
            name: {k: v for k, v in step.items() if k != "images"}
            for name, step in steps.items()
        },
        "message": message,
    }
    write_report(report, report_path)
    report["report_path"] = str(report_path)
    return report