"""The package order of ADR-0045, read off every import statement under ``src/gda``.

ADR-0045 §1 orders gda's packages by their imports, and §6 makes that order a gate
rather than a review habit: an edge that points up the order fails here, as does any
edge that breaks the three properties of ``gda.core`` (closed, framework-free,
process-free) or its packages-only layout. The imports are read statically with
``ast``, so an edge is caught whether or not a test happens to import the module that
adds it, and an import under ``if TYPE_CHECKING:`` or inside a function counts too.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
GDA = SRC / "gda"
CORE = GDA / "core"

# ADR-0045 §1, bottom to top. `__main__` and `mcp` sit above `cli`; `ops` and `skill`
# hold no Python module. A module at either end of a `gda.*` import is ranked by the
# longest entry its dotted name is, or starts with; one that matches no entry fails
# the test until §1 places it.
ORDER = (
    ("gda.exit_codes",),
    ("gda.core.project",),
    ("gda.core.engine",),
    ("gda.core.contract",),
    ("gda.core.failure",),
    ("gda.core.steps",),
    ("gda.daemon",),
    ("gda.harness",),
    ("gda.surface",),
    ("gda.commands",),
    ("gda.cli",),
    ("gda.__main__", "gda.mcp"),
)
CLI_FRAMEWORKS = {"typer", "click", "rich"}


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _is_module(dotted: str) -> bool:
    path = SRC.joinpath(*dotted.split("."))
    return path.with_suffix(".py").is_file() or path.is_dir()


def _imports() -> list[tuple[str, str]]:
    """Every ``(importer, imported)`` pair under ``src/gda``, imported by its full
    dotted name: ``from gda.x import y`` names ``gda.x.y`` when ``y`` is a module."""
    edges = []
    for path in sorted(GDA.rglob("*.py")):
        importer = _module_name(path)
        package = (
            importer if path.name == "__init__.py" else importer.rpartition(".")[0]
        )
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                edges += [(importer, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.rsplit(".", node.level - 1)[0]
                    base = f"{anchor}.{base}" if base else anchor
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    edges.append((importer, full if _is_module(full) else base))
    return edges


def _rank(module: str) -> int:
    matches = [
        (len(entry), rank)
        for rank, entries in enumerate(ORDER)
        for entry in entries
        if module == entry or module.startswith(entry + ".")
    ]
    assert matches, f"{module} has no rank: place its package in ADR-0045 §1 first"
    return max(matches)[1]


def _in_core(module: str) -> bool:
    return module == "gda.core" or module.startswith("gda.core.")


def _gda_edges() -> list[tuple[str, str]]:
    return [(a, b) for a, b in _imports() if b == "gda" or b.startswith("gda.")]


def test_every_import_points_down_the_package_order():
    upward = sorted(
        f"{importer} -> {imported}"
        for importer, imported in _gda_edges()
        if _rank(imported) > _rank(importer)
    )

    assert not upward, f"imports that point up the ADR-0045 §1 order: {upward}"


def test_the_core_imports_only_itself_and_the_exit_codes():
    outside = sorted(
        f"{importer} -> {imported}"
        for importer, imported in _gda_edges()
        if _in_core(importer)
        and not _in_core(imported)
        and imported != "gda.exit_codes"
    )

    assert not outside, f"gda.core is closed (ADR-0045 §1), but: {outside}"


def test_the_core_imports_no_cli_framework():
    framework = sorted(
        f"{importer} -> {imported}"
        for importer, imported in _imports()
        if _in_core(importer) and imported.split(".")[0] in CLI_FRAMEWORKS
    )

    assert not framework, f"gda.core is framework-free (ADR-0045 §1), but: {framework}"


def test_the_core_holds_packages_only_and_no_entry_point():
    entry_points = sorted(
        p.relative_to(GDA).as_posix() for p in CORE.rglob("__main__.py")
    )
    loose = sorted(p.name for p in CORE.glob("*.py") if p.name != "__init__.py")
    initializer = (CORE / "__init__.py").read_text(encoding="utf-8")

    assert not entry_points, f"gda.core is process-free (ADR-0045 §1): {entry_points}"
    assert not loose, f"gda.core holds packages only (ADR-0045 §1): {loose}"
    assert not initializer, (
        f"gda.core's __init__.py is empty (ADR-0045 §3): {initializer!r}"
    )
