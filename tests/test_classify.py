"""Tests for the Gemma page classifier. Gemma is replaced by a fake client, so no model is needed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Name

from _builders import add_page, gradient_image, image_xobject, jpeg_bytes, save
from pdftoolkit.classify import (
    OllamaUnavailable,
    classify_and_remove,
    classify_pdf,
    classify_to_report,
    parse_label,
    render_page_png,
)


class FakeClient:
    """Stands in for ollama.Client. replies are returned in order, one per page."""

    def __init__(self, replies=(), error=None, down=False):
        self.replies = list(replies)
        self.error = error
        self.down = down
        self.calls = 0

    def list(self):
        if self.down:
            raise ConnectionError("connection refused")
        return {"models": []}

    def chat(self, model, messages, format=None, options=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        text = self.replies.pop(0) if self.replies else '{"label": "keep_as_is", "reason": "none"}'
        return {"message": {"content": text}}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reply(label: str, reason: str = "test") -> str:
    return json.dumps({"label": label, "reason": reason})


def make_two_subject_pages(path: Path) -> Path:
    """Two pages, each with its own 2-inch subject image (a red circle on blue)."""
    pdf = pikepdf.Pdf.new()
    for _ in range(2):
        img = gradient_image(300, 300)
        xobj = image_xobject(pdf, jpeg_bytes(img, 95), 300, 300)
        add_page(pdf, b"q 144 0 0 144 234 324 cm /Im1 Do Q", xobjects={"/Im1": xobj})
    return save(pdf, path)


@pytest.fixture
def two_pages(tmp_path) -> Path:
    return make_two_subject_pages(tmp_path / "two.pdf")


# ---------------------------------------------------------------------------
# Reading the reply
# ---------------------------------------------------------------------------

def test_parse_label_reads_a_valid_reply():
    result = parse_label(reply("subject_photo", "a person"))
    assert result == {"label": "subject_photo", "reason": "a person", "parsed": True}


def test_parse_label_finds_json_inside_extra_text():
    text = "Here you go:\n```json\n" + reply("logo") + "\n```"
    assert parse_label(text)["label"] == "logo"


@pytest.mark.parametrize("text", ["", "I cannot tell", "{not json}", '["a", "list"]'])
def test_unreadable_reply_falls_back_to_keep_as_is(text):
    result = parse_label(text)
    assert result["label"] == "keep_as_is"
    assert result["parsed"] is False
    assert result["reason"]


def test_label_outside_the_allowed_list_falls_back_to_keep_as_is():
    result = parse_label(reply("delete_everything"))
    assert result["label"] == "keep_as_is"
    assert result["parsed"] is False
    assert "not one of the allowed labels" in result["reason"]


# ---------------------------------------------------------------------------
# Classifying pages
# ---------------------------------------------------------------------------

def test_each_page_gets_its_own_label(two_pages):
    client = FakeClient([reply("subject_photo"), reply("text_page")])

    rows = classify_pdf(two_pages, client=client)

    assert [(r["page"], r["label"]) for r in rows] == [(1, "subject_photo"), (2, "text_page")]
    assert all(r["parsed"] for r in rows)


def test_unreadable_page_is_kept_as_is(two_pages):
    client = FakeClient([reply("logo"), "this is not json"])

    rows = classify_pdf(two_pages, client=client)

    assert rows[1]["label"] == "keep_as_is"
    assert rows[1]["parsed"] is False


def test_failed_gemma_call_is_recorded_and_the_page_is_kept_as_is(two_pages):
    client = FakeClient(error=RuntimeError("model not found"))

    rows = classify_pdf(two_pages, client=client)

    assert all(r["label"] == "keep_as_is" for r in rows)
    assert all("Gemma call failed" in r["reason"] for r in rows)


def test_classifier_raises_when_ollama_is_not_running(two_pages):
    with pytest.raises(OllamaUnavailable, match="Ollama is not running"):
        classify_pdf(two_pages, client=FakeClient(down=True))


def test_render_page_png_gives_a_png_about_1000_px_wide(two_pages):
    import io

    from PIL import Image

    png = render_page_png(two_pages, 1)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert abs(Image.open(io.BytesIO(png)).width - 1000) <= 2


# ---------------------------------------------------------------------------
# Classifying and removing backgrounds
# ---------------------------------------------------------------------------

def test_only_pages_labelled_subject_photo_or_logo_are_processed(two_pages, tmp_path):
    client = FakeClient([reply("subject_photo"), reply("text_page")])
    out = tmp_path / "out.pdf"

    report = classify_and_remove(two_pages, out, client=client, report_path=tmp_path / "r.json")

    rows = {r["page"]: r for r in report["background"]["images"]}
    assert rows[1]["action"] == "processed"
    assert rows[2]["action"] == "not_processed"
    assert rows[2]["reason"] == "page not selected"
    with pikepdf.open(out) as pdf:
        assert "/SMask" in pdf.pages[0].Resources.XObject["/Im1"]
        assert "/SMask" not in pdf.pages[1].Resources.XObject["/Im1"]


def test_unreadable_replies_change_nothing(two_pages, tmp_path):
    before = sha256(two_pages)
    client = FakeClient(["garbage", "more garbage"])
    out = tmp_path / "out.pdf"

    report = classify_and_remove(two_pages, out, client=client, report_path=tmp_path / "r.json")

    assert report["ok"] is True
    assert all(r["action"] == "not_processed" for r in report["background"]["images"])
    assert any("keep_as_is" in w for w in report["warnings"])
    with pikepdf.open(out) as pdf:
        assert all("/SMask" not in p.Resources.XObject["/Im1"] for p in pdf.pages)
    assert sha256(two_pages) == before


def test_ollama_down_skips_the_classifier_and_uses_the_default_rule(two_pages, tmp_path):
    out = tmp_path / "out.pdf"

    report = classify_and_remove(two_pages, out, client=FakeClient(down=True),
                                 report_path=tmp_path / "r.json")

    assert report["classification"]["status"] == "skipped"
    assert "Ollama is not running" in report["classification"]["reason"]
    assert report["ok"] is True
    assert out.exists()
    assert "default rule" in report["selection"]
    assert all(r["action"] == "processed" for r in report["background"]["images"])


def test_every_failed_call_gets_a_pull_hint(two_pages, tmp_path):
    client = FakeClient(error=RuntimeError("model not found"))

    report = classify_and_remove(two_pages, tmp_path / "out.pdf", client=client,
                                 report_path=tmp_path / "r.json")

    assert any("ollama pull" in w for w in report["warnings"])


def test_classify_and_remove_does_not_change_the_input(two_pages, tmp_path):
    before = sha256(two_pages)

    classify_and_remove(two_pages, tmp_path / "out.pdf",
                        client=FakeClient([reply("subject_photo"), reply("logo")]),
                        report_path=tmp_path / "r.json")

    assert sha256(two_pages) == before


def test_classify_and_remove_refuses_to_overwrite_the_input(two_pages):
    with pytest.raises(ValueError, match="overwrite"):
        classify_and_remove(two_pages, two_pages, client=FakeClient())


# ---------------------------------------------------------------------------
# Labels only
# ---------------------------------------------------------------------------

def test_classify_to_report_writes_labels_and_changes_nothing(two_pages, tmp_path):
    before = sha256(two_pages)
    report_path = tmp_path / "labels.json"

    report = classify_to_report(two_pages, report_path,
                                client=FakeClient([reply("subject_photo"), reply("logo")]))

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert [p["label"] for p in saved["pages"]] == ["subject_photo", "logo"]
    assert report["ok"] is True
    assert sha256(two_pages) == before


def test_classify_to_report_when_ollama_is_down(two_pages, tmp_path):
    report = classify_to_report(two_pages, tmp_path / "labels.json", client=FakeClient(down=True))

    assert report["ok"] is False
    assert report["status"] == "skipped"
    assert "Classifier skipped" in report["message"]