"""Tests for the print copy that drops Adobe editing data (/PieceInfo)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Dictionary, Name, Pdf, Stream

from _builders import add_page, gradient_image, image_xobject, jpeg_bytes, save
from pdftoolkit.editing import drop_editing_data, main

PIECE_BYTES = 3 * 1024 * 1024  # incompressible, so its size shows in the output file


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_layered_pdf(path: Path) -> Path:
    """One page with a JPEG image, a /PieceInfo on the page and on the catalog."""
    pdf = Pdf.new()
    img = gradient_image(400, 300)
    image = image_xobject(pdf, jpeg_bytes(img), 400, 300)
    content = b"q 612 0 0 792 0 0 cm /Im0 Do Q"
    page = add_page(pdf, content, xobjects={"/Im0": image})

    piece = Stream(pdf, os.urandom(PIECE_BYTES))
    page[Name.PieceInfo] = Dictionary(Layered=Dictionary(Private=piece))
    pdf.Root[Name.PieceInfo] = Dictionary(Private=Dictionary(Note=pikepdf.String("editing data")))
    return save(pdf, path)


def make_plain_pdf(path: Path) -> Path:
    pdf = Pdf.new()
    add_page(pdf, b"0 0 1 rg 10 10 100 100 re f", size=(300, 200))
    add_page(pdf, b"0 1 0 rg 10 10 100 100 re f", size=(400, 500))
    return save(pdf, path)


def test_piece_info_removed_from_page_and_catalog(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    out = tmp_path / "print.pdf"

    report = drop_editing_data(src, out)

    with Pdf.open(out) as pdf:
        assert "/PieceInfo" not in pdf.pages[0].obj
        assert "/PieceInfo" not in pdf.Root
    assert report["removed"] == ["page 1 /PieceInfo", "catalog /PieceInfo"]


def test_output_is_much_smaller_when_editing_data_is_large(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    out = tmp_path / "print.pdf"

    report = drop_editing_data(src, out)

    assert report["output_bytes"] < report["input_bytes"] - PIECE_BYTES * 0.9
    assert report["input_bytes"] == src.stat().st_size
    assert report["output_bytes"] == out.stat().st_size


def test_input_file_is_not_changed(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    before = sha256(src)

    drop_editing_data(src, tmp_path / "print.pdf")

    assert sha256(src) == before
    with Pdf.open(src) as pdf:  # original still has its editing data
        assert "/PieceInfo" in pdf.pages[0].obj


def test_refuses_to_overwrite_input(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    before = sha256(src)

    with pytest.raises(ValueError, match="overwrite"):
        drop_editing_data(src, src)

    assert sha256(src) == before


def test_page_content_and_image_bytes_are_identical(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    out = tmp_path / "print.pdf"

    drop_editing_data(src, out)

    with Pdf.open(src) as before, Pdf.open(out) as after:
        assert after.pages[0].Contents.read_bytes() == before.pages[0].Contents.read_bytes()
        img_before = before.pages[0].Resources.XObject["/Im0"]
        img_after = after.pages[0].Resources.XObject["/Im0"]
        assert img_after.read_raw_bytes() == img_before.read_raw_bytes()
        assert int(img_after.Width) == 400
        assert int(img_after.Height) == 300


def test_page_count_and_sizes_unchanged(tmp_path):
    src = make_plain_pdf(tmp_path / "plain.pdf")
    out = tmp_path / "print.pdf"

    report = drop_editing_data(src, out)

    with Pdf.open(src) as before, Pdf.open(out) as after:
        assert len(after.pages) == len(before.pages) == report["page_count"] == 2
        for a, b in zip(after.pages, before.pages):
            assert [float(v) for v in a.MediaBox] == [float(v) for v in b.MediaBox]


def test_file_without_editing_data_is_copied_with_nothing_removed(tmp_path):
    src = make_plain_pdf(tmp_path / "plain.pdf")
    out = tmp_path / "print.pdf"

    report = drop_editing_data(src, out)

    assert report["removed"] == []
    assert out.exists()


def test_report_is_written_as_json(tmp_path):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    out = tmp_path / "print.pdf"
    report_path = tmp_path / "reports" / "print_report.json"

    report = drop_editing_data(src, out, report_path)

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["operation"] == "print_copy"
    assert saved["ok"] is True
    assert saved["removed"] == report["removed"]
    assert report["report_path"] == str(report_path)


def test_output_folder_is_created(tmp_path):
    src = make_plain_pdf(tmp_path / "plain.pdf")
    out = tmp_path / "new" / "deep" / "print.pdf"

    drop_editing_data(src, out)

    assert out.exists()


def test_command_line_writes_print_copy_and_report(tmp_path, capsys):
    src = make_layered_pdf(tmp_path / "layered.pdf")
    before = sha256(src)
    out = tmp_path / "print.pdf"
    report = tmp_path / "print_report.json"

    main([str(src), str(out), "--report", str(report)])

    assert out.exists()
    assert report.exists()
    assert sha256(src) == before
    printed = capsys.readouterr().out
    assert "print copy" in printed
    assert "page 1 /PieceInfo" in printed