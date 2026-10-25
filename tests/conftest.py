from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "test_banner.pdf"


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    if not SAMPLE.exists():
        from make_sample import build_sample

        build_sample(SAMPLE)
    return SAMPLE
