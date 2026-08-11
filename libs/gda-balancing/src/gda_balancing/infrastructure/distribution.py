"""Installed Python distribution metadata."""

from importlib.metadata import version


def distribution_version(name: str) -> str:
    """Return the installed version of one named distribution."""
    return version(name)
