"""Read immutable bytes from an installed Python package resource tree."""

from collections.abc import Callable
from importlib.resources.abc import Traversable


def read_package_resource(
    resource_root: Callable[[str], Traversable],
    package: str,
    name: str,
) -> bytes:
    """Read one explicitly named resource without discovering membership."""
    return resource_root(package).joinpath(*name.split("/")).read_bytes()
