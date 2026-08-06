"""Read immutable bytes from an installed Python package resource tree."""

from importlib.resources import files


def read_package_resource(
    package: str,
    name: str,
) -> bytes:
    """Read one explicitly named resource without discovering membership."""
    return files(package).joinpath(*name.split("/")).read_bytes()
