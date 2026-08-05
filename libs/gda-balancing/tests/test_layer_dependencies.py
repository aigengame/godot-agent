"""Dependency rules for the incrementally migrated production layers."""

import ast
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys


_SOURCE_ROOT = Path(__file__).parents[1] / "src" / "gda_balancing"
_LAYERS = ("infrastructure", "domain", "application", "interfaces")
_LAYER_RANK = {layer: rank for rank, layer in enumerate(_LAYERS)}
_OBSOLETE_UI_MODULES = (
    "cli.py",
    "commands/__init__.py",
    "descriptors.py",
    "dispatch.py",
    "emit.py",
    "envelope.py",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(_SOURCE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("gda_balancing", *parts))


def _resolved_imports(
    module: str,
    path: Path,
    known_modules: set[str],
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name(f"{'.' * node.level}{base}", package)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                imports.add(candidate if candidate in known_modules else base)
    return imports


def test_import_resolution_includes_relative_imports(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "from ..interfaces.cli import package_list\n",
        encoding="utf-8",
    )

    assert _resolved_imports(
        "gda_balancing.domain.sample",
        source,
        {"gda_balancing.interfaces.cli.package_list"},
    ) == {"gda_balancing.interfaces.cli.package_list"}


def test_import_resolution_includes_imported_package_members(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "from gda_balancing.application import package_list\n",
        encoding="utf-8",
    )

    assert _resolved_imports(
        "gda_balancing.interfaces.cli.sample",
        source,
        {"gda_balancing.application.package_list"},
    ) == {"gda_balancing.application.package_list"}


def _migrated_modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for layer in _LAYERS
        for path in (_SOURCE_ROOT / layer).rglob("*.py")
    }


def _production_modules() -> set[str]:
    return {_module_name(path) for path in _SOURCE_ROOT.rglob("*.py")}


def test_each_layer_contains_a_production_module() -> None:
    missing = [
        layer
        for layer in _LAYERS
        if not any(
            path.name != "__init__.py" for path in (_SOURCE_ROOT / layer).rglob("*.py")
        )
    ]

    assert missing == []


def test_migrated_layers_do_not_import_upward() -> None:
    known_modules = _production_modules()
    violations: list[str] = []
    for module, path in _migrated_modules().items():
        source_layer = module.split(".")[1]
        for imported in _resolved_imports(module, path, known_modules):
            parts = imported.split(".")
            if len(parts) < 2 or parts[0] != "gda_balancing":
                continue
            target_layer = parts[1]
            if target_layer in _LAYER_RANK and (
                _LAYER_RANK[target_layer] > _LAYER_RANK[source_layer]
            ):
                violations.append(f"{module} imports upward from {imported}")

    assert violations == []


def test_obsolete_top_level_ui_modules_are_removed() -> None:
    assert [
        name for name in _OBSOLETE_UI_MODULES if (_SOURCE_ROOT / name).is_file()
    ] == []


def test_migrated_modules_are_acyclic() -> None:
    modules = _migrated_modules()
    edges = {
        module: {
            imported
            for imported in _resolved_imports(module, path, set(modules))
            if imported in modules
        }
        for module, path in modules.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(module: str) -> None:
        if module in visiting:
            start = visiting.index(module)
            cycles.append(" -> ".join((*visiting[start:], module)))
            return
        if module in visited:
            return
        visiting.append(module)
        for imported in sorted(edges[module]):
            visit(imported)
        visiting.pop()
        visited.add(module)

    for module in sorted(modules):
        visit(module)

    assert cycles == []


def test_package_list_cli_adapter_cold_imports_without_a_registry_cycle() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gda_balancing.interfaces.cli.package_list import PACKAGE_LIST",
        ],
        cwd=_SOURCE_ROOT.parents[1],
        capture_output=True,
        text=True,
    )

    assert (completed.returncode, completed.stderr) == (0, "")


def test_cli_composition_root_cold_imports_without_a_registry_cycle() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gda_balancing.interfaces.cli.main import main",
        ],
        cwd=_SOURCE_ROOT.parents[1],
        capture_output=True,
        text=True,
    )

    assert (completed.returncode, completed.stderr) == (0, "")
