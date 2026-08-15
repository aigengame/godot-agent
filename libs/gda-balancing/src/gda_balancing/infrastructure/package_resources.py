"""Read immutable bytes from an installed Python package resource tree."""

from importlib.resources import files
from importlib.resources.abc import Traversable


def read_package_resource(
    package: str,
    name: str,
) -> bytes:
    """Read one explicitly named resource without discovering membership."""
    return files(package).joinpath(*name.split("/")).read_bytes()


def list_package_resources(package: str) -> tuple[str, ...]:
    """List file names from one package resource tree without reading them."""
    return tuple(_resource_names(files(package)))


def _resource_names(
    root: Traversable,
    prefix: tuple[str, ...] = (),
) -> list[str]:
    names: list[str] = []
    for child in root.iterdir():
        path = (*prefix, child.name)
        if child.is_dir():
            names.extend(_resource_names(child, path))
        else:
            names.append("/".join(path))
    return names
