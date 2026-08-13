"""Dependency rules for the incrementally migrated production layers."""

import ast
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys


_SOURCE_ROOT = Path(__file__).parents[1] / "src" / "gda_balancing"
_LAYERS = ("infrastructure", "domain", "application", "interfaces")
_LAYER_RANK = {layer: rank for rank, layer in enumerate(_LAYERS)}
_ROOT_ENTRYPOINTS = frozenset({"__init__.py", "__main__.py"})
_SCHEMA2_RESOURCE_PACKAGES = frozenset(
    {"schema2/__init__.py", "schema2/authorities/__init__.py"}
)
_SCHEMA1_MIGRATION_CONSUMERS = frozenset({"gda_balancing.application.migration"})


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


def _architectural_modules() -> dict[str, Path]:
    return {
        _module_name(path): path
        for layer in _LAYERS
        for path in (_SOURCE_ROOT / layer).rglob("*.py")
    }


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "gda_balancing":
        return None
    namespace = parts[1]
    return namespace if namespace in _LAYER_RANK else None


def _production_modules() -> set[str]:
    return {_module_name(path) for path in _SOURCE_ROOT.rglob("*.py")}


def _declared_owner(path: Path) -> str | None:
    relative = path.relative_to(_SOURCE_ROOT)
    if relative.as_posix() in _ROOT_ENTRYPOINTS:
        return "entrypoint"
    if relative.parts[0] in _LAYERS:
        return relative.parts[0]
    if relative.parts[0] == "schema":
        return "schema1-migration-input"
    if relative.as_posix() in _SCHEMA2_RESOURCE_PACKAGES:
        return "schema2-authority-resources"
    return None


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
    for module, path in _architectural_modules().items():
        source_layer = _layer(module)
        assert source_layer is not None
        for imported in _resolved_imports(module, path, known_modules):
            parts = imported.split(".")
            if len(parts) < 2 or parts[0] != "gda_balancing":
                continue
            target_layer = _layer(imported)
            if target_layer is not None and (
                _LAYER_RANK[target_layer] > _LAYER_RANK[source_layer]
            ):
                violations.append(f"{module} imports upward from {imported}")

    assert violations == []


def test_every_production_module_has_one_declared_owner() -> None:
    unowned = [
        str(path.relative_to(_SOURCE_ROOT))
        for path in _SOURCE_ROOT.rglob("*.py")
        if _declared_owner(path) is None
    ]

    assert unowned == []


def test_unowned_production_namespaces_cannot_bypass_the_layer_gate() -> None:
    assert _declared_owner(_SOURCE_ROOT / "commands" / "new.py") is None
    assert _declared_owner(_SOURCE_ROOT / "schema2" / "new.py") is None
    assert _declared_owner(_SOURCE_ROOT / "new.py") is None


def test_schema1_is_imported_only_by_the_model_migration_boundary() -> None:
    known_modules = _production_modules()
    violations: list[str] = []
    for path in _SOURCE_ROOT.rglob("*.py"):
        module = _module_name(path)
        if module.startswith("gda_balancing.schema"):
            continue
        schema_imports = {
            imported
            for imported in _resolved_imports(module, path, known_modules)
            if imported == "gda_balancing.schema"
            or imported.startswith("gda_balancing.schema.")
        }
        if schema_imports and module not in _SCHEMA1_MIGRATION_CONSUMERS:
            violations.append(f"{module} imports {sorted(schema_imports)}")

    assert violations == []


def test_schema1_migration_input_does_not_import_active_layers() -> None:
    known_modules = _production_modules()
    violations = [
        f"{_module_name(path)} imports active layer {imported}"
        for path in (_SOURCE_ROOT / "schema").rglob("*.py")
        for imported in _resolved_imports(_module_name(path), path, known_modules)
        if _layer(imported) is not None
    ]

    assert violations == []


def test_architectural_modules_are_acyclic() -> None:
    modules = _architectural_modules()
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


def test_evidence_replay_does_not_import_the_production_executor() -> None:
    violations = [
        module
        for module in (
            "gda_balancing.domain.evidence",
            "gda_balancing.domain.evidence_replay",
        )
        if "gda_balancing.domain.runtime.execution"
        in _resolved_imports(
            module,
            _SOURCE_ROOT.joinpath(*module.split(".")[1:]).with_suffix(".py"),
            _production_modules(),
        )
    ]

    assert violations == []


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
