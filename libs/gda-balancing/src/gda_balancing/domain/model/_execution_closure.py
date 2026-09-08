"""Close final RIR execution dependencies through the Kernel projection contract."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.operation_program import (
    operation_body_instructions,
    selected_operation_index,
)
from gda_balancing.domain.program_reachability import (
    project_reachable_program_structure,
)


def _path(value: Any, path: list[str]) -> Any:
    for member in path:
        if not isinstance(value, dict) or member not in value:
            raise ValueError("execution dependency selector is outside its authority")
        value = value[member]
    return value


def _assign(value: dict[str, Any], path: list[str], selected: Any) -> None:
    for member in path[:-1]:
        value = value.setdefault(member, {})
    if path[-1] in value:
        raise ValueError("execution dependency output is duplicated")
    value[path[-1]] = deepcopy(selected)


def close_execution_dependencies(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    rir: dict[str, Any],
    consume: Callable[[], None],
) -> dict[str, Any]:
    """Return selected semantics with every declared final-program dependency.

    Both the compiler and independent import admission call this projection on
    final specialized instructions. It never executes the program or trusts a
    dependency payload supplied by the producer.
    """
    meta = cast(dict[str, Any], kernel["meta_format"])
    contract = cast(dict[str, Any], meta["runtime_projection"]["execution_closure"])
    selected = deepcopy(cast(dict[str, Any], rir["selected_semantics"]))
    if any(member in selected for member in contract["output_members"]):
        raise ValueError(
            "execution dependencies must be derived from unsupplemented RIR"
        )
    program = project_reachable_program_structure(
        rir, rir["entrypoints"], runtime=meta["runtime_program"]
    )
    typed = any(
        row["definition"]["source_kind"] == "typed-envelope"
        for row in selected["literal_typing_profiles"]
    )
    applicable = {
        "always": True,
        "executable": bool(rir["entrypoints"] or program.runtime_node_ids),
        "typed-values": typed,
    }
    laws: dict[str, Any] = {}
    for selector in cast(list[dict[str, Any]], contract["law_selectors"]):
        consume()
        if applicable[selector["when"]]:
            _assign(laws, selector["output_path"], _path(meta, selector["source_path"]))

    node_selection = contract["nodes"]
    nodes = {
        row[node_selection["id_member"]]: row
        for row in _path(meta, node_selection["source_path"])
    }
    if not program.runtime_node_ids <= nodes.keys():
        raise ValueError("final RIR instruction has no Kernel execution law")
    selected_nodes = [nodes[name] for name in sorted(program.runtime_node_ids)]
    for _node in selected_nodes:
        consume()
    _assign(laws, node_selection["output_path"], selected_nodes)

    resources: dict[str, int] = {}
    for selector in cast(list[dict[str, str]], contract["resources"]):
        consume()
        if not applicable[selector["when"]]:
            continue
        limit = language_bundle["resources"][selector["source_member"]]
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("execution resource dependency is not a positive limit")
        resources[selector["output_member"]] = limit

    reason_contract = cast(dict[str, Any], contract["reasons"])
    reason_path = cast(str, reason_contract["authority_path"])
    diagnostic_path = cast(str, reason_contract["diagnostic_authority_path"])
    reason_key = cast(str, reason_contract["id_member"])
    diagnostic_key = cast(str, reason_contract["diagnostic_member"])
    owned: dict[str, dict[str, dict[str, Any]]] = {
        reason_path: {},
        diagnostic_path: {},
    }
    reason_signals: dict[tuple[str, str], list[str]] = {}
    for package in language_bundle["language"]["packages"]:
        for closure in package["semantic_closure"]:
            path = closure["authority_path"]
            if path not in owned:
                continue
            key_member = reason_key if path == reason_path else diagnostic_key
            for definition in closure["definitions"]:
                consume()  # Existing catalog-row charge, shared with initial selection.
                key = definition[key_member]
                if key in owned[path]:
                    raise ValueError(
                        "execution reason or diagnostic owner is ambiguous"
                    )
                owned[path][key] = {
                    "package": package["id"],
                    "definition": definition,
                }
                if path == reason_path and "signal" in definition:
                    signal = (definition["stage"], definition["signal"])
                    reason_signals.setdefault(signal, []).append(key)
    reasons = owned[reason_path]
    reason_ids: set[str] = set()
    signals: set[tuple[str, str]] = set()
    for root in reason_contract["roots"]:
        if not applicable[root["when"]]:
            continue
        signals.add((root["stage"], root["signal"]))
    for node in selected_nodes:
        signals.update(
            (reason_contract["node_signal_stage"], signal)
            for signal in node[reason_contract["node_signal_member"]]
        )
    operations = selected_operation_index(selected)
    for coordinate in sorted(program.operation_coordinates):
        operation = operations[coordinate]
        reason_ids.update(operation[reason_contract["operation_reason_member"]])
        for instruction in operation_body_instructions(operation["body"]):
            consume()
            node = nodes[instruction[node_selection["instruction_member"]]]
            reference = node["semantics"].get(reason_contract["instruction_reference"])
            if reference is not None:
                reason_ids.add(instruction[reference["instruction_member"]])
    for stage, signal in signals:
        matches = reason_signals.get((stage, signal), [])
        if len(matches) != 1:
            raise ValueError("execution signal has no unique owned diagnostic reason")
        reason_ids.add(matches[0])
    if not reason_ids <= reasons.keys():
        raise ValueError("final RIR refusal has no owned reason definition")
    selected_reasons = [deepcopy(reasons[name]) for name in sorted(reason_ids)]
    diagnostic_ids: set[str] = set()
    for row in selected_reasons:
        consume()
        reason = row["definition"]
        code = reason["diagnostic"]
        diagnostic = owned[diagnostic_path].get(code)
        if diagnostic is None or diagnostic["definition"]["stage"] != reason["stage"]:
            raise ValueError(
                "execution reason does not close its diagnostic declaration"
            )
        diagnostic_ids.add(code)
    selected_diagnostics = [
        deepcopy(owned[diagnostic_path][code]) for code in sorted(diagnostic_ids)
    ]
    for _diagnostic in selected_diagnostics:
        consume()

    selected["execution_laws"] = laws
    selected["execution_resources"] = resources
    selected["diagnostic_reasons"] = selected_reasons
    selected["diagnostics"] = selected_diagnostics

    # Match the existing RIR owner/closure views, including implicit Runtime and
    # evaluation dependencies that were not authored Source requirements.
    packages = {row["id"] for row in selected["packages"]}
    closures = {row["package"]: row for row in selected["package_semantic_closures"]}
    for path, rows in (
        (reason_path, selected_reasons),
        (diagnostic_path, selected_diagnostics),
    ):
        owners = sorted({row["package"] for row in rows})
        for owner in owners:
            packages.add(owner)
            closure = closures.setdefault(owner, {"package": owner, "definitions": []})
            definitions = [row["definition"] for row in rows if row["package"] == owner]
            if any(entry["authority_path"] == path for entry in closure["definitions"]):
                raise ValueError("execution reason closure was already materialized")
            closure["definitions"].append(
                {"authority_path": path, "definitions": deepcopy(definitions)}
            )
            closure["definitions"].sort(key=lambda row: row["authority_path"])
    selected["packages"] = [{"id": owner} for owner in sorted(packages)]
    selected["package_semantic_closures"] = [
        closures[owner] for owner in sorted(closures)
    ]
    return selected
