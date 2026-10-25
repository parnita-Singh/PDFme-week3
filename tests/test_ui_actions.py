"""Tests for the work behind the web page (no web code involved)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from test_background import make_mixed_pdf, make_subject_pdf
from test_classify import FakeClient
from test_editing import make_layered_pdf
from test_merge_split import make_pdf
from pdftoolkit import classify as classify_module
from pdftoolkit.ui_actions import (
    _parse_pages,
    compress_file,
    inspect_file,
    labels_file,
    merge_files,
    pipeline_file,
    print_copy_file,
    remove_background_file,
    split_file,
)


def pages_in(path) -> int:
    with pikepdf.open(path) as pdf:
        return len(pdf.pages)


# ---------------------------------------------------------------------------
# Page-number text
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("", None), (None, None), ("   ", None),
    ("1", [1]), ("1,3", [1, 3]), ("2-4", [2, 3, 4]), ("3, 1, 1", [1, 3]),
])
def test_parse_pages(text, expected):
    assert _parse_pages(text) == expected


def test_parse_pages_rejects_text():
    with pytest.raises(ValueError):
        _parse_pages("first page")


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def test_inspect_lists_one_row_per_image(tmp_path):
    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    rows, message = inspect_file(str(src))

    assert len(rows) == 2
    assert "1 page(s), 2 image(s)." == message


def test_inspect_reports_an_unreadable_file(tmp_path):
    bad = tmp_path / "not_a_pdf.pdf"
    bad.write_text("this is not a pdf")

    rows, message = inspect_file(str(bad))

    assert rows == []
    assert message.startswith("Could not read the file")


def test_inspect_shows_how_much_of_the_page_each_image_covers(tmp_path):
    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    rows, _ = inspect_file(str(src))

    by_name = {row[1]: row for row in rows}
    assert by_name["/Im0"][9] == "100%"       # full-page background
    assert by_name["/Im1"][9] == "4%"         # 2 x 2 inch subject
    assert by_name["/Im0"][8] == "8.5 x 11.0"  # placed size in inches


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------

def test_compress_fixed_resolution_writes_an_output(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = compress_file(str(src), "Fixed resolution", 150, 90, 0, tmp_path / "outputs")

    assert out is not None and Path(out).exists()
    assert "Compressed to" in message
    assert Path(out).parent == tmp_path / "outputs"


def test_compress_fit_to_size_writes_nothing_when_impossible(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = compress_file(str(src), "Fit to size", 150, 90, 0.001, tmp_path / "outputs")

    assert out is None
    assert "No setting fits" in message
    assert not (tmp_path / "outputs").exists() or not any((tmp_path / "outputs").glob("*.pdf"))


def test_compress_never_overwrites_an_earlier_result(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    folder = tmp_path / "outputs"

    first, _ = compress_file(str(src), "Fixed resolution", 150, 90, 0, folder)
    second, _ = compress_file(str(src), "Fixed resolution", 150, 90, 0, folder)

    assert first != second
    assert Path(first).exists() and Path(second).exists()


# ---------------------------------------------------------------------------
# Print copy
# ---------------------------------------------------------------------------

def test_print_copy_removes_editing_data_and_keeps_the_original(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    before = src.read_bytes()

    out, message = print_copy_file(str(src), tmp_path / "outputs")

    assert out is not None
    with pikepdf.open(out) as pdf:
        assert "/PieceInfo" not in pdf.pages[0].obj
    assert "Print copy:" in message
    assert src.read_bytes() == before


# ---------------------------------------------------------------------------
# Merge and split
# ---------------------------------------------------------------------------

def test_merge_joins_the_files_in_order(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", [300, 310])
    b = make_pdf(tmp_path / "b.pdf", [400])

    out, _ = merge_files([str(a), str(b)], tmp_path / "outputs")

    assert pages_in(out) == 3


def test_merge_with_no_files_asks_for_one(tmp_path):
    out, message = merge_files([], tmp_path / "outputs")
    assert out is None
    assert "at least one" in message


def test_split_returns_the_part_files(tmp_path):
    src = make_pdf(tmp_path / "six.pdf", [300 + 10 * i for i in range(6)])
    limit_mb = src.stat().st_size / 3 / 1_000_000

    files, message = split_file(str(src), limit_mb, tmp_path / "outputs")

    assert len(files) >= 2
    assert all(Path(f).exists() for f in files)
    assert sum(pages_in(f) for f in files) == 6
    assert message.startswith("Split six.pdf")


# ---------------------------------------------------------------------------
# Background, labels and pipeline
# ---------------------------------------------------------------------------

def test_remove_background_writes_an_output(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = remove_background_file(str(src), "none", "1", False, None, "gemma3:4b",
                                          tmp_path / "outputs")

    assert out is not None and Path(out).exists()
    assert "Processed 1 image" in message


def test_remove_background_rejects_a_bad_colour(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = remove_background_file(str(src), "white", "", False, None, "gemma3:4b",
                                          tmp_path / "outputs")

    assert out is None
    assert message.startswith("Error:")


def test_labels_are_empty_and_explained_when_ollama_is_down(tmp_path, monkeypatch):
    src = make_subject_pdf(tmp_path / "subject.pdf")
    monkeypatch.setattr(classify_module, "_make_client", lambda host=None: FakeClient(down=True))

    rows, message, report = labels_file(str(src), "gemma3:4b", tmp_path / "outputs")

    assert rows == []
    assert "Classifier skipped" in message
    assert report is not None and Path(report).exists()


def test_pipeline_without_background_removal_only_fits(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = pipeline_file(str(src), False, "none", 2000, None, tmp_path / "outputs")

    assert out is not None and Path(out).exists()
    assert message.startswith("Pipeline finished") or "Fits:" in message


def test_pipeline_reports_an_impossible_limit_and_writes_nothing(tmp_path):
    src = make_subject_pdf(tmp_path / "subject.pdf")

    out, message = pipeline_file(str(src), False, "none", 0.0001, None, tmp_path / "outputs")

    assert out is None
    assert "No setting fits" in message or "stopped" in message.lower()


def test_remove_images_processes_only_the_named_full_page_image(tmp_path):
    from test_background import make_mixed_pdf
    from pdftoolkit.ui_actions import remove_images_file

    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    out, message = remove_images_file(str(src), "none", "1:Im0", None, tmp_path / "outputs")

    assert out is not None and Path(out).exists()
    assert message.startswith("Processed 1 image")


def test_remove_images_asks_for_a_name_when_blank(tmp_path):
    from pdftoolkit.ui_actions import remove_images_file

    out, message = remove_images_file("unused.pdf", "none", "", None, tmp_path / "outputs")

    assert out is None
    assert "Choose at least one image" in message


def test_image_choices_values_work_with_remove_images(tmp_path):
    from pdftoolkit.ui_actions import image_choices, remove_images_file

    src = make_mixed_pdf(tmp_path / "mixed.pdf")

    choices = image_choices(str(src))

    values = [value for _, value in choices]
    assert values == ["1:Im0", "1:Im1"]
    assert "covers 100%" in choices[0][0]
    out, message = remove_images_file(str(src), "none", values[0], None, tmp_path / "outputs")
    assert message.startswith("Processed 1 image")


def test_image_choices_is_empty_without_a_file():
    from pdftoolkit.ui_actions import image_choices

    assert image_choices(None) == []