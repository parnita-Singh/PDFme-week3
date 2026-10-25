"""The web page builds, and it listens on this computer only."""

import pytest

gr = pytest.importorskip("gradio")

import app  # noqa: E402


def test_page_builds_with_every_tab():
    demo = app.build_app()
    tabs = [b.label for b in demo.blocks.values() if type(b).__name__ == "Tab"]
    assert tabs == [
        "Inspect", "Compress", "Print copy", "Merge and split",
        "Remove background", "Page labels", "Pipeline",
    ]


def test_page_listens_on_localhost_only():
    assert app.HOST == "127.0.0.1"