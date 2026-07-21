"""Independent compiler/lowerer A."""

from __future__ import annotations

from typing import Any

from canonical import artifact, clone


class CompilerA:
    implementation = "compiler-a-map-lowerer-v1"

    def compile(
        self,
        kernel: dict[str, Any],
        bundle: dict[str, Any],
        source: dict[str, Any],
        package_lock: dict[str, Any],
        resolution_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        source_artifact = artifact("model-source-package", clone(source))
        ast = artifact(
            "authoring-ast",
            {
                "source": source_artifact["identity"],
                "nodes": [
                    {
                        "module": module["name"],
                        "declarations": clone(module["declarations"]),
                    }
                    for module in source["modules"]
                ],
            },
        )
        constants: dict[str, int] = {}
        entries: list[dict[str, Any]] = []
        aliases = source.get("imports", {})
        for module in source["modules"]:
            for declaration in module["declarations"]:
                if declaration["kind"] == "constant":
                    value = declaration["value"]
                    if type(value) is not int:
                        raise ValueError("compile.constant-not-int")
                    constants[declaration["name"]] = value
        for module in source["modules"]:
            for declaration in module["declarations"]:
                if declaration["kind"] == "entry":
                    operation = aliases.get(
                        declaration["operation"], declaration["operation"]
                    )
                    arguments: dict[str, int] = {}
                    for name, expression in declaration["arguments"].items():
                        reference = expression.get("ref")
                        if reference not in constants:
                            raise ValueError("compile.reference-unresolved")
                        arguments[name] = constants[reference]
                    entries.append(
                        {
                            "id": f"{module['name']}.{declaration['name']}",
                            "operation": operation,
                            "arguments": arguments,
                        }
                    )
        operations = {
            fact["id"]: fact for fact in bundle["facts"] if fact["kind"] == "operation"
        }
        for entry in entries:
            specification = operations.get(entry["operation"])
            if specification is None:
                raise ValueError("compile.operation-unresolved")
            if sorted(entry["arguments"]) != sorted(specification["parameters"]):
                raise ValueError("compile.arguments-mismatch")
        hir = artifact(
            "typed-hir",
            {
                "source": source_artifact["identity"],
                "entries": sorted(clone(entries), key=lambda row: row["id"]),
                "types": {name: "Int" for name in sorted(constants)},
            },
        )
        selected_operations = self._operation_closure(entries, operations)
        capability_manifest = {
            "packages": [item["package"] for item in package_lock["selected"]],
            "capabilities": sorted(package_lock["capability_providers"]),
            "operations": sorted(selected_operations),
            "types": ["Int", "Record", "Variant"],
            "conversions": [],
            "runtime_profiles": ["portable-exact-v1"],
        }
        semantic = {
            "schema_major": 2,
            "kernel": kernel["identity"],
            "language_bundle": bundle["identity"],
            "package_lock": package_lock["identity"],
            "runtime_profile": "portable-exact-v1",
            "capability_manifest": capability_manifest,
            "entries": sorted(entries, key=lambda row: row["id"]),
            "operations": [
                {
                    "body": clone(operations[name]["body"]),
                    "effects": sorted(operations[name]["effects"]),
                    "id": name,
                    "parameters": {
                        key: operations[name]["parameters"][key]
                        for key in sorted(operations[name]["parameters"])
                    },
                    "result": operations[name]["result"],
                }
                for name in sorted(selected_operations)
            ],
        }
        rir = artifact("resolved-model", semantic)
        debug_map = artifact(
            "debug-map",
            {
                "compiler": self.implementation,
                "rir": rir["identity"],
                "source": source_artifact["identity"],
                "ast": ast["identity"],
                "hir": hir["identity"],
                "mapping": [
                    {"entry": row["id"], "span": "probe:1:1"} for row in entries
                ],
            },
        )
        build_receipt = artifact(
            "build-receipt",
            {
                "compiler": self.implementation,
                "kernel": kernel["identity"],
                "language_bundle": bundle["identity"],
                "source": source_artifact["identity"],
                "package_lock": package_lock["identity"],
                "resolution_receipt": resolution_receipt["identity"],
                "rir": rir["identity"],
                "debug_map": debug_map["identity"],
                "ast": ast["identity"],
                "hir": hir["identity"],
            },
        )
        return {
            "source": source_artifact,
            "ast": ast,
            "hir": hir,
            "rir": rir,
            "debug_map": debug_map,
            "build_receipt": build_receipt,
        }

    def _operation_closure(
        self, entries: list[dict[str, Any]], operations: dict[str, dict[str, Any]]
    ) -> set[str]:
        selected = {entry["operation"] for entry in entries}
        pending = list(selected)
        while pending:
            name = pending.pop()
            body = operations[name]["body"]
            calls = self._find_calls(body)
            for called in calls:
                if called not in operations:
                    raise ValueError("compile.operation-unresolved")
                if called not in selected:
                    selected.add(called)
                    pending.append(called)
        return selected

    def _find_calls(self, value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            if value.get("node") == "call":
                found.add(value["operation"])
            for child in value.values():
                found.update(self._find_calls(child))
        elif isinstance(value, list):
            for child in value:
                found.update(self._find_calls(child))
        return found


def semantic_bytes(result: dict[str, Any]) -> bytes:
    """Used only by tests to make the intended equality visible."""
    from canonical import canonical_bytes

    return canonical_bytes(result["rir"])
