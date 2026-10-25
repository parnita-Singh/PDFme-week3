"""Tests for splitting by page range (for example '1-5,6-10,12')."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pikepdf
import pytest

from test_merge_split import make_pdf
from pdftoolkit.merge_split import main as split_main, parse_ranges, split_by_pages


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pages_in(path) -> int:
    with pikepdf.open(path) as pdf:
        return len(pdf.pages)


@pytest.mark.parametrize("text, expected", [
    ("1-5, 6-10, 12", [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9], [11]]),
    ("3", [[2]]),
    ("2-2", [[1]]),
    ("1-3,2", [[0, 1, 2], [1]]),
])
def test_parse_ranges_reads_the_text(text, expected):
    assert parse_ranges(text, 12) == expected


@pytest.mark.parametrize("text", [
    None, "", "   ", "abc", "1-", "0-2", "3-2", "5-20", "1-3,x", ",",
])
def test_parse_ranges_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parse_ranges(text, 10)


def test_split_by_pages_writes_one_file_per_range(tmp_path):
    src = make_pdf(tmp_path / "twelve.pdf", [300 + i for i in range(12)])
    before = sha256(src)

    report = split_by_pages(src, tmp_path / "out", "1-5, 6-10, 12")

    assert report["ok"] is True
    files = [Path(p["file"]) for p in report["parts"]]
    assert [pages_in(f) for f in files] == [5, 5, 1]
    assert sum(pages_in(f) for f in files) == 11
    assert all(f.exists() for f in files)
    assert sha256(src) == before


def test_split_by_pages_names_the_pages_in_each_file(tmp_path):
    src = make_pdf(tmp_path / "twelve.pdf", [300 + i for i in range(12)])

    report = split_by_pages(src, tmp_path / "out", "2-4,9")

    names = [Path(p["file"]).name for p in report["parts"]]
    assert names == ["twelve_part01_p2-4.pdf", "twelve_part02_p9.pdf"]


def test_split_by_pages_keeps_the_page_sizes(tmp_path):
    src = make_pdf(tmp_path / "sizes.pdf", [300, 400, 500])

    report = split_by_pages(src, tmp_path / "out", "2")

    with pikepdf.open(report["parts"][0]["file"]) as pdf:
        assert float(pdf.pages[0].MediaBox[2]) == 400


def test_bad_range_writes_nothing(tmp_path):
    src = make_pdf(tmp_path / "three.pdf", [300, 310, 320])

    report = split_by_pages(src, tmp_path / "out", "2-9")

    assert report["ok"] is False
    assert "outside the document" in report["message"]
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").glob("*.pdf"))


def test_command_line_split_with_pages(tmp_path, capsys):
    src = make_pdf(tmp_path / "six.pdf", [300 + i for i in range(6)])

    code = split_main(["split", str(src), "--pages", "1-2,3-6", "-o", str(tmp_path / "out")])

    assert code == 0
    assert "2 part(s) by page range" in capsys.readouterr().out
    assert len(list((tmp_path / "out").glob("*.pdf"))) == 2


def test_ui_split_with_page_ranges(tmp_path):
    from pdftoolkit.ui_actions import split_file

    src = make_pdf(tmp_path / "six.pdf", [300 + i for i in range(6)])

    files, message = split_file(str(src), 2000, tmp_path / "outputs", "1-3, 4-6")

    assert len(files) == 2
    assert all(Path(f).exists() for f in files)
    assert "by page range" in message