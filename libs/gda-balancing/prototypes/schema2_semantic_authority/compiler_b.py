"""Independent compiler/lowerer B using sorted symbol tables and an iterative call scan."""

from __future__ import annotations

from typing import Any

from canonical import artifact, clone


class CompilerB:
    implementation = "compiler-b-table-lowerer-v1"

    def compile(
        self,
        kernel: dict[str, Any],
        bundle: dict[str, Any],
        source: dict[str, Any],
        package_lock: dict[str, Any],
        resolution_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        source_copy = clone(source)
        source_artifact = artifact("model-source-package", source_copy)
        flat: list[tuple[str, dict[str, Any]]] = []
        for module in source_copy["modules"]:
            for declaration in module["declarations"]:
                flat.append((module["name"], declaration))
        ast = artifact(
            "authoring-ast",
            {
                "parser": self.implementation,
                "source": source_artifact["identity"],
                "flat_nodes": [
                    {"module": module, "ordinal": index, "declaration": declaration}
                    for index, (module, declaration) in enumerate(flat)
                ],
            },
        )
        values: dict[str, int] = {}
        entry_declarations: list[tuple[str, dict[str, Any]]] = []
        for module, declaration in flat:
            tag = declaration.get("kind")
            if tag == "constant":
                if type(declaration.get("value")) is not int:
                    raise ValueError("compile.constant-not-int")
                values[str(declaration["name"])] = declaration["value"]
            if tag == "entry":
                entry_declarations.append((module, declaration))
        aliases = dict(source_copy.get("imports", {}))
        lowered_entries: list[dict[str, Any]] = []
        for module, declaration in sorted(
            entry_declarations, key=lambda item: item[1]["name"]
        ):
            argument_values: dict[str, int] = {}
            for argument_name in sorted(declaration["arguments"]):
                reference = declaration["arguments"][argument_name].get("ref")
                if reference not in values:
                    raise ValueError("compile.reference-unresolved")
                argument_values[argument_name] = values[reference]
            spelling = str(declaration["operation"])
            lowered_entries.append(
                {
                    "id": f"{module}.{declaration['name']}",
                    "operation": aliases[spelling] if spelling in aliases else spelling,
                    "arguments": argument_values,
                }
            )
        operation_table: dict[str, dict[str, Any]] = {}
        for fact in bundle["facts"]:
            if fact.get("kind") == "operation":
                operation_table[str(fact["id"])] = fact
        for entry in lowered_entries:
            spec = operation_table.get(entry["operation"])
            if spec is None:
                raise ValueError("compile.operation-unresolved")
            if set(entry["arguments"]) != set(spec["parameters"]):
                raise ValueError("compile.arguments-mismatch")
        hir = artifact(
            "typed-hir",
            {
                "lowerer": self.implementation,
                "source": source_artifact["identity"],
                "symbols": [
                    {"name": key, "resolved_type": "Int", "value": values[key]}
                    for key in sorted(values)
                ],
                "resolved_entries": clone(lowered_entries),
            },
        )

        needed = {entry["operation"] for entry in lowered_entries}
        frontier = sorted(needed)
        while frontier:
            operation_name = frontier.pop(0)
            if operation_name not in operation_table:
                raise ValueError("compile.operation-unresolved")
            stack: list[Any] = [operation_table[operation_name]["body"]]
            while stack:
                token = stack.pop()
                if type(token) is list:
                    stack.extend(token)
                elif type(token) is dict:
                    if token.get("node") == "call":
                        target = str(token["operation"])
                        if target not in operation_table:
                            raise ValueError("compile.operation-unresolved")
                        if target not in needed:
                            needed.add(target)
                            frontier.append(target)
                            frontier.sort()
                    stack.extend(token.values())
        manifest = {
            "packages": sorted(row["package"] for row in package_lock["selected"]),
            "capabilities": sorted(package_lock["capability_providers"].keys()),
            "operations": sorted(needed),
            "types": ["Int", "Record", "Variant"],
            "conversions": [],
            "runtime_profiles": ["portable-exact-v1"],
        }
        normalized_operations: list[dict[str, Any]] = []
        for name in sorted(needed):
            spec = operation_table[name]
            normalized_operations.append(
                {
                    "body": clone(spec["body"]),
                    "effects": sorted(spec["effects"]),
                    "id": name,
                    "parameters": {
                        key: spec["parameters"][key]
                        for key in sorted(spec["parameters"])
                    },
                    "result": spec["result"],
                }
            )
        rir = artifact(
            "resolved-model",
            {
                "schema_major": 2,
                "kernel": kernel["identity"],
                "language_bundle": bundle["identity"],
                "package_lock": package_lock["identity"],
                "runtime_profile": "portable-exact-v1",
                "capability_manifest": manifest,
                "entries": sorted(lowered_entries, key=lambda row: row["id"]),
                "operations": normalized_operations,
            },
        )
        debug_map = artifact(
            "debug-map",
            {
                "compiler": self.implementation,
                "rir": rir["identity"],
                "source": source_artifact["identity"],
                "ast": ast["identity"],
                "hir": hir["identity"],
                "mapping": [
                    {"entry": entry["id"], "source_node": index}
                    for index, entry in enumerate(lowered_entries)
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
