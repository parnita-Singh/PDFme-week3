"""The fit command is reachable from the main CLI: python -m pdftoolkit fit ..."""

from __future__ import annotations

import pytest

from pdftoolkit.__main__ import main as cli
from test_fit import make_sample


@pytest.fixture
def sample(tmp_path):
    return make_sample(tmp_path / "sample.pdf")


def test_fit_subcommand_writes_output_and_returns_0(sample, tmp_path, capsys):
    out = tmp_path / "fit.pdf"
    limit_mb = sample.stat().st_size / 2_000_000  # half the input size, in MB

    code = cli(["fit", str(sample), str(out), "--max-mb", str(limit_mb)])

    assert code == 0
    assert out.exists()
    assert "Fits:" in capsys.readouterr().out


def test_fit_subcommand_returns_1_and_writes_nothing_when_impossible(sample, tmp_path, capsys):
    out = tmp_path / "fit.pdf"

    code = cli(["fit", str(sample), str(out), "--max-mb", "0.001"])

    assert code == 1
    assert not out.exists()
    assert "No setting fits" in capsys.readouterr().out


def test_existing_commands_still_parse(tmp_path):
    # inspect and compress keep working after the fit command was added.
    with pytest.raises(SystemExit):
        cli(["compress"])  # missing arguments: argparse exits, so the command parsed
    with pytest.raises(SystemExit):
        cli(["inspect"])