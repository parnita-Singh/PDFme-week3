"""Tests for merge and split. Pages have different widths so the order can be checked."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
import pytest

from _builders import add_page, gradient_image, image_xobject, jpeg_bytes, save
from pdftoolkit.__main__ import main as cli
from pdftoolkit.merge_split import merge, split_by_size


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_pdf(path: Path, widths: list[int], image_side: int = 700) -> Path:
    """One page per width. Each page has its own photo-like image, so pages take real space."""
    pdf = pikepdf.Pdf.new()
    for k, width in enumerate(widths):
        img = gradient_image(image_side, image_side)
        xobj = image_xobject(pdf, jpeg_bytes(img, 95), image_side, image_side)
        add_page(
            pdf,
            b"q 600 0 0 600 0 0 cm /Im0 Do Q",
            xobjects={"/Im0": xobj},
            size=(width, 792),
        )
    return save(pdf, path)


def widths_of(path: Path) -> list[int]:
    with pikepdf.open(path) as pdf:
        return [int(float(p.MediaBox[2])) for p in pdf.pages]


@pytest.fixture
def six_pages(tmp_path) -> Path:
    return make_pdf(tmp_path / "six.pdf", [300 + 10 * i for i in range(6)])


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def test_merged_page_count_is_the_sum_of_the_inputs(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300, 310, 320])
    b = make_pdf(tmp_path / "b.pdf", [400, 410])
    out = tmp_path / "out.pdf"

    report = merge([a, b], out)

    assert report["ok"] is True
    assert report["page_count"] == 5
    assert len(widths_of(out)) == 5


def test_merged_pages_keep_their_order_and_sizes(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300, 310])
    b = make_pdf(tmp_path / "b.pdf", [500])
    out = tmp_path / "out.pdf"

    merge([b, a], out)  # the order given: b first, then a

    assert widths_of(out) == [500, 300, 310]


def test_merge_does_not_change_the_inputs(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300, 310])
    b = make_pdf(tmp_path / "b.pdf", [400])
    before = (sha256(a), sha256(b))

    merge([a, b], tmp_path / "out.pdf")

    assert (sha256(a), sha256(b)) == before


def test_merge_refuses_to_overwrite_an_input(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300])
    b = make_pdf(tmp_path / "b.pdf", [400])
    before = sha256(a)

    with pytest.raises(ValueError, match="overwrite"):
        merge([a, b], a)

    assert sha256(a) == before


def test_merge_needs_at_least_one_input(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        merge([], tmp_path / "out.pdf")


def test_merge_report_is_written_as_json(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300, 310])
    report_path = tmp_path / "reports" / "merge.json"

    report = merge([a], tmp_path / "out.pdf", report_path)

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["operation"] == "merge"
    assert saved["page_count"] == 2
    assert report["report_path"] == str(report_path)


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------

def test_every_split_part_is_under_the_limit(six_pages, tmp_path):
    limit = six_pages.stat().st_size // 3
    out_dir = tmp_path / "parts"

    report = split_by_size(six_pages, out_dir, limit)

    assert report["ok"] is True
    assert len(report["parts"]) >= 2
    for part in out_dir.glob("*.pdf"):
        assert part.stat().st_size <= limit, part.name


def test_split_pages_add_up_to_the_original_in_order(six_pages, tmp_path):
    limit = six_pages.stat().st_size // 3
    out_dir = tmp_path / "parts"

    report = split_by_size(six_pages, out_dir, limit)

    joined: list[int] = []
    for part in report["parts"]:
        joined += widths_of(Path(part["file"]))
    assert len(joined) == 6
    assert joined == widths_of(six_pages)


def test_a_page_too_big_for_the_limit_stops_and_writes_nothing(six_pages, tmp_path):
    out_dir = tmp_path / "parts"

    report = split_by_size(six_pages, out_dir, max_bytes=1000)

    assert report["ok"] is False
    assert report["problem_page"] == 1
    assert "alone is" in report["message"]
    assert not out_dir.exists() or not any(out_dir.glob("*.pdf"))


def test_split_does_not_change_the_input(six_pages, tmp_path):
    before = sha256(six_pages)

    split_by_size(six_pages, tmp_path / "parts", six_pages.stat().st_size // 3)
    split_by_size(six_pages, tmp_path / "fail", max_bytes=1000)

    assert sha256(six_pages) == before


def test_split_rejects_a_zero_limit(six_pages, tmp_path):
    with pytest.raises(ValueError, match="max_bytes"):
        split_by_size(six_pages, tmp_path / "parts", 0)


def test_split_report_lists_each_part_and_its_pages(six_pages, tmp_path):
    out_dir = tmp_path / "parts"
    report = split_by_size(six_pages, out_dir, six_pages.stat().st_size // 3)

    saved = json.loads((out_dir / "split_report.json").read_text(encoding="utf-8"))
    assert saved["operation"] == "split"
    assert sum(p["page_count"] for p in saved["parts"]) == 6
    assert report["message"].startswith("Split six.pdf")


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def test_cli_merge(tmp_path, capsys):
    a = make_pdf(tmp_path / "a.pdf", [300])
    b = make_pdf(tmp_path / "b.pdf", [400, 410])
    out = tmp_path / "out.pdf"

    assert cli(["merge", str(a), str(b), "-o", str(out)]) == 0

    assert widths_of(out) == [300, 400, 410]
    assert "Merged 2 files" in capsys.readouterr().out


def test_cli_split(six_pages, tmp_path, capsys):
    out_dir = tmp_path / "parts"
    limit_mb = six_pages.stat().st_size / 3 / 1_000_000

    code = cli(["split", str(six_pages), "--max-mb", str(limit_mb), "-o", str(out_dir)])

    assert code == 0
    assert "Split six.pdf" in capsys.readouterr().out
    assert len(list(out_dir.glob("*.pdf"))) >= 2


def test_cli_split_returns_1_when_a_page_is_too_big(six_pages, tmp_path):
    code = cli(["split", str(six_pages), "--max-mb", "0.001", "-o", str(tmp_path / "parts")])
    assert code == 1