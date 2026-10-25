"""Tests for the pipeline: remove backgrounds, then fit to a size limit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
import pytest

from test_background import make_mixed_pdf
from pdftoolkit.__main__ import main as cli
from pdftoolkit.pipeline import run_pipeline


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def src(tmp_path) -> Path:
    return make_mixed_pdf(tmp_path / "mixed.pdf")


def test_pipeline_removes_backgrounds_then_fits_the_limit(src, tmp_path):
    out = tmp_path / "out" / "final.pdf"
    limit = src.stat().st_size * 2  # generous: the point here is the order of the steps

    report = run_pipeline(src, out, max_bytes=limit, remove_bg=True)

    assert report["ok"] is True
    assert out.exists()
    assert out.stat().st_size <= limit
    assert set(report["steps"]) == {"remove_background", "fit"}
    assert report["steps"]["remove_background"]["ok"] is True
    with pikepdf.open(out) as pdf:
        assert "/SMask" in pdf.pages[0].Resources.XObject["/Im1"]


def test_pipeline_without_remove_bg_only_fits(src, tmp_path):
    out = tmp_path / "fit_only.pdf"

    # No model is needed when remove_bg is off, so a missing model name is not a problem.
    report = run_pipeline(src, out, max_bytes=src.stat().st_size * 2, remove_bg=False,
                          model="no-such-model")

    assert report["ok"] is True
    assert set(report["steps"]) == {"fit"}
    with pikepdf.open(out) as pdf:
        assert "/SMask" not in pdf.pages[0].Resources.XObject["/Im1"]


def test_pipeline_stops_when_nothing_fits_and_writes_no_output(src, tmp_path):
    out = tmp_path / "final.pdf"

    report = run_pipeline(src, out, max_bytes=1000, remove_bg=True)

    assert report["ok"] is False
    assert report["output"] is None
    assert not out.exists()
    assert "Pipeline stopped at the size step" in report["message"]


def test_pipeline_writes_no_output_when_the_model_file_is_missing(src, tmp_path):
    out = tmp_path / "final.pdf"

    with pytest.raises(FileNotFoundError, match="model file not found"):
        run_pipeline(src, out, max_bytes=src.stat().st_size * 2, remove_bg=True,
                     model_file=tmp_path / "missing.onnx")

    assert not out.exists()


def test_pipeline_does_not_change_the_input(src, tmp_path):
    before = sha256(src)

    run_pipeline(src, tmp_path / "final.pdf", max_bytes=src.stat().st_size * 2)

    assert sha256(src) == before


def test_pipeline_refuses_to_overwrite_the_input(src):
    with pytest.raises(ValueError, match="overwrite"):
        run_pipeline(src, src, max_bytes=10_000_000)


def test_pipeline_report_is_written_as_json(src, tmp_path):
    report_path = tmp_path / "reports" / "pipeline.json"

    run_pipeline(src, tmp_path / "final.pdf", max_bytes=src.stat().st_size * 2,
                 report_path=report_path)

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["operation"] == "pipeline"
    assert saved["ok"] is True


def test_command_line_pipeline(src, tmp_path, capsys):
    out = tmp_path / "final.pdf"
    limit_mb = src.stat().st_size * 2 / 1_000_000

    code = cli(["pipeline", str(src), str(out), "--remove-bg", "--max-mb", str(limit_mb)])

    assert code == 0
    assert out.exists()
    assert "Pipeline finished" in capsys.readouterr().out