"""Tests for compress_to_target: fit a PDF under a size limit, measured for real."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Name

from _builders import add_page, gradient_image, image_xobject, jpeg_bytes, save
from pdftoolkit.fit import _dpi_plan, compress_to_target, main


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_sample(path: Path) -> Path:
    """A full-page background (about 353 dpi) and a 2-inch foreground (288 dpi)."""
    pdf = pikepdf.Pdf.new()
    bg = image_xobject(pdf, jpeg_bytes(gradient_image(3000, 3900), 95), 3000, 3900)
    fg = image_xobject(pdf, jpeg_bytes(gradient_image(576, 576), 95), 576, 576)
    add_page(
        pdf,
        b"q 612 0 0 792 0 0 cm /Im0 Do Q q 144 0 0 144 234 324 cm /Im1 Do Q",
        xobjects={"/Im0": bg, "/Im1": fg},
    )
    return save(pdf, path)


@pytest.fixture
def sample(tmp_path) -> Path:
    return make_sample(tmp_path / "sample.pdf")


def test_result_is_at_or_under_the_limit(sample, tmp_path):
    limit = sample.stat().st_size // 2
    out = tmp_path / "out" / "fit.pdf"

    report = compress_to_target(sample, out, max_bytes=limit)

    assert report["ok"] is True
    assert out.exists()
    assert out.stat().st_size <= limit
    assert report["output_bytes"] == out.stat().st_size


def test_report_gives_the_chosen_dpi_and_quality(sample, tmp_path):
    limit = sample.stat().st_size // 2
    out = tmp_path / "fit.pdf"

    report = compress_to_target(sample, out, max_bytes=limit)

    assert report["chosen"]["max_dpi"] in (300, 250, 200, 150, 120, 100)
    assert report["chosen"]["jpeg_quality"] in (92, 88, 84, 80)
    saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert saved["chosen"] == report["chosen"]


def test_chosen_setting_is_the_first_one_that_fits(sample, tmp_path):
    """Every trial tried before the chosen one must be too big."""
    limit = sample.stat().st_size // 2

    report = compress_to_target(sample, tmp_path / "fit.pdf", max_bytes=limit)

    fits = [t["fits"] for t in report["trials"]]
    assert fits[-1] is True
    assert not any(fits[:-1])
    assert all(t["output_bytes"] > limit for t in report["trials"][:-1])


def test_no_trial_goes_below_min_dpi(sample, tmp_path):
    limit = 1  # impossible, so every trial runs
    report = compress_to_target(sample, tmp_path / "fit.pdf", max_bytes=limit, min_dpi=200)

    assert report["trials"]
    assert all(t["max_dpi"] >= 200 for t in report["trials"])


def test_impossible_limit_writes_no_output_and_reports_the_best_result(sample, tmp_path):
    out = tmp_path / "fit.pdf"

    report = compress_to_target(sample, out, max_bytes=1000)

    assert report["ok"] is False
    assert report["output"] is None
    assert not out.exists()
    assert report["smallest"] is not None
    assert report["needed_reduction_bytes"] > 0
    assert "No setting fits" in report["message"]
    assert "No output file was written" in report["message"]


def test_impossible_limit_leaves_an_existing_output_untouched(sample, tmp_path):
    out = tmp_path / "fit.pdf"
    out.write_bytes(b"keep me")

    compress_to_target(sample, out, max_bytes=1000)

    assert out.read_bytes() == b"keep me"


def test_trial_files_are_not_left_next_to_the_output(sample, tmp_path):
    out_dir = tmp_path / "out"
    out = out_dir / "fit.pdf"

    compress_to_target(sample, out, max_bytes=sample.stat().st_size // 2)

    # The report's file name depends on the project's reporting.py, so only
    # check what must not be there: other PDFs, trial files, partial files.
    names = [p.name for p in out_dir.iterdir()]
    assert [n for n in names if n.endswith(".pdf")] == ["fit.pdf"]
    assert not any(n.startswith("dpi") or n.endswith(".partial") for n in names)


def test_input_file_is_not_changed(sample, tmp_path):
    before = sha256(sample)

    compress_to_target(sample, tmp_path / "fit.pdf", max_bytes=sample.stat().st_size // 2)
    compress_to_target(sample, tmp_path / "fail.pdf", max_bytes=1000)

    assert sha256(sample) == before


def test_output_has_the_same_pages(sample, tmp_path):
    out = tmp_path / "fit.pdf"

    compress_to_target(sample, out, max_bytes=sample.stat().st_size // 2)

    with pikepdf.open(sample) as before, pikepdf.open(out) as after:
        assert len(after.pages) == len(before.pages) == 1
        assert [float(v) for v in after.pages[0].MediaBox] == [
            float(v) for v in before.pages[0].MediaBox
        ]


def test_refuses_to_overwrite_input(sample):
    with pytest.raises(ValueError, match="overwrite"):
        compress_to_target(sample, sample, max_bytes=10_000_000)


@pytest.mark.parametrize("bad", [0, -5])
def test_rejects_a_zero_or_negative_limit(sample, tmp_path, bad):
    with pytest.raises(ValueError, match="max_bytes"):
        compress_to_target(sample, tmp_path / "fit.pdf", max_bytes=bad)


def test_dpi_plan_is_high_to_low_and_ends_at_min_dpi():
    steps = (300, 250, 200, 150, 120, 100)
    assert _dpi_plan(steps, 100) == [300, 250, 200, 150, 120, 100]
    assert _dpi_plan(steps, 110) == [300, 250, 200, 150, 120, 110]
    assert _dpi_plan(steps, 200) == [300, 250, 200]


def test_command_line_returns_0_on_success_and_1_on_failure(sample, tmp_path, capsys):
    ok_out = tmp_path / "ok.pdf"
    assert main([str(sample), str(ok_out), "--max-mb", str(sample.stat().st_size / 2_000_000)]) == 0
    assert ok_out.exists()
    assert "Fits:" in capsys.readouterr().out

    fail_out = tmp_path / "fail.pdf"
    assert main([str(sample), str(fail_out), "--max-mb", "0.001"]) == 1
    assert not fail_out.exists()
    assert "No setting fits" in capsys.readouterr().out