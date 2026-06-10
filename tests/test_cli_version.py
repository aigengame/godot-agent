"""Root CLI metadata options."""

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app

ROOT = Path(__file__).resolve().parents[1]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def test_root_version_option_prints_package_version():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"gda {version('gda')}\n"
    assert result.stderr == ""


def test_root_help_advertises_version_option():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--version" in _plain(result.stdout)


def test_root_version_option_does_not_require_godot(monkeypatch):
    monkeypatch.setenv("GDA_GODOT", "/definitely/missing/Godot")

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"gda {version('gda')}\n"
    assert result.stderr == ""


def test_package_metadata_version_matches_pyproject():
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert version("gda") == pyproject["project"]["version"]
