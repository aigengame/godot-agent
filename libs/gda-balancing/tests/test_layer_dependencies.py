"""Dependency rules for the incrementally migrated production layers."""

import ast
from pathlib import Path
import subprocess
import sys


_SOURCE_ROOT = Path(__file__).parents[1] / "src" / "gda_balancing"
_LAYERS = ("infrastructure", "domain", "application", "interfaces")
_LAYER_RANK = {layer: rank for rank, layer in enumerate(_LAYERS)}
_LEGACY_UI_PREFIXES = (
    "gda_balancing.commands",
    "gda_balancing.descriptors",
    "gda_balancing.dispatch",
    "gda_balancing.emit",
    "gda_balancing.envelope",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(_SOURCE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("gda_balancing", *parts))


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def _migrated_modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for layer in _LAYERS
        for path in (_SOURCE_ROOT / layer).rglob("*.py")
    }


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
    violations: list[str] = []
    for module, path in _migrated_modules().items():
        source_layer = module.split(".")[1]
        for imported in _absolute_imports(path):
            parts = imported.split(".")
            if len(parts) < 2 or parts[0] != "gda_balancing":
                continue
            target_layer = parts[1]
            if target_layer in _LAYER_RANK and (
                _LAYER_RANK[target_layer] > _LAYER_RANK[source_layer]
            ):
                violations.append(f"{module} imports upward from {imported}")

    assert violations == []


def test_migrated_layers_do_not_depend_on_legacy_command_modules() -> None:
    violations: list[str] = []
    for module, path in _migrated_modules().items():
        source_layer = module.split(".")[1]
        for imported in _absolute_imports(path):
            forbidden = (
                imported.startswith(_LEGACY_UI_PREFIXES)
                if source_layer != "interfaces"
                else imported.startswith("gda_balancing.commands")
            )
            if forbidden:
                violations.append(f"{module} imports legacy UI module {imported}")

    assert violations == []


def test_migrated_modules_are_acyclic() -> None:
    modules = _migrated_modules()
    edges = {
        module: {
            imported for imported in _absolute_imports(path) if imported in modules
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
