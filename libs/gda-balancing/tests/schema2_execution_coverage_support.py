"""Independent reverse coverage of the Experiment/build/run witness surfaces.

This module interprets the selected Kernel/LDB owners and actual generated
artifacts. It never invokes the inventory reader, and never infers a semantic
role from a string's spelling. Only explicit owner fields and equal canonical
projections can introduce an expected occurrence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import re


def validate_execution_coverage(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: Any
) -> None:
    # Local import deliberately keeps the reader independent of this verifier.
    from schema2_extension_inventory_support import (
        AuthorityToken,
        InventoryRefusal,
        TokenOccurrence,
        _artifact_protocol_binding,
        _at,
        _authority_path_rows,
        _child,
        _close_projection_occurrences,
        _consumer_b_canonical_equal,
        _json_pointer_segments,
        _call_path_segments,
        _pointer_value,
        _source_projection,
        _template_inventory,
        _type_links,
        _typed_context,
        _typed_value_links,
        _experiment_input_judgment_links,
        _resolved_judgment_links,
    )
    from schema2_source_inventory_reverse_support import source_key_tokens

    roots = ("/experiment/", "/artifacts/", "/results/")
    law_exp = "/meta_format/language_definitions/wire_schema_protocol_roles/experiment_input_structure"
    law_model = (
        "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure"
    )
    law_rir = (
        "/meta_format/language_definitions/wire_schema_protocol_roles/rir_structure"
    )
    law_trace = (
        "/meta_format/language_definitions/wire_schema_protocol_roles/trace_structure"
    )
    law_artifact = "/meta_format/language_definitions/collections/artifact_contracts"
    expected: set[TokenOccurrence] = set()
    projections: list[tuple[str, str]] = []
    types, constructors = _typed_context(kernel, graph)

    def source_model() -> str:
        projection = _source_projection(kernel, graph)
        if projection is None:
            raise InventoryRefusal("execution surface has no Source projection")
        return projection.value["manifest"]["id"]

    def token(role: str, owner: tuple[str, ...], name: str) -> Any:
        return AuthorityToken(role, owner, name)

    def add(
        tok: Any,
        pointer: str,
        law: str,
        *,
        use: str = "reference",
        location: str = "value",
        projection: str = "",
    ) -> None:
        row = TokenOccurrence(tok, pointer, use, law, location, projection)
        expected.add(row)

    def add_links(rows: Any) -> None:
        for row in rows:
            if not isinstance(row, TokenOccurrence):
                raise InventoryRefusal("generated typed value has an unresolved scope")
            expected.add(row)

    def copy(source: str, target: str) -> None:
        if not _consumer_b_canonical_equal(
            _pointer_value(graph, source), _pointer_value(graph, target)
        ):
            raise InventoryRefusal("generated semantic projection changed its owner")
        projections.append((source, target))

    def type_ref(value: Any, pointer: str) -> None:
        add_links(_type_links(value, pointer, constructors))

    def typed_literal(value: Any, pointer: str) -> None:
        if not isinstance(value, dict):
            return
        envelope = kernel["meta_format"]["literal_typing"]["typed_envelope_profile"]
        tm, vm = envelope["type_member"], envelope["value_member"]
        if set(value) != {tm, vm}:
            raise InventoryRefusal("generated typed literal has unclassified members")
        type_ref(value[tm], _child(pointer, tm))
        add_links(
            _typed_value_links(
                value[tm], value[vm], _child(pointer, vm), types, constructors
            )
        )

    def source_coord(value: Any, pointer: str, law: str) -> None:
        if not isinstance(value, dict) or set(value) != {"model", "module", "name"}:
            raise InventoryRefusal("generated Symbol coordinate is unclassified")
        model, module = value["model"], value["module"]
        add(token("source-model", (), model), pointer + "/model", law)
        add(token("source-module", (model,), module), pointer + "/module", law)
        add(
            token("source-symbol", (model, module), value["name"]),
            pointer + "/name",
            law,
        )

    def operation_ref(value: Any, pointer: str, law: str) -> tuple[str, str]:
        if not isinstance(value, dict) or set(value) != {"package", "id"}:
            raise InventoryRefusal("generated Operation coordinate is unclassified")
        package, name = value["package"], value["id"]
        add(token("namespace", (), package), pointer + "/package", law)
        add(token("language.operations", (package,), name), pointer + "/id", law)
        return package, name

    def member(surface: str, role: str) -> tuple[dict[str, Any], str]:
        values = graph.get(surface)
        if not isinstance(values, dict):
            raise InventoryRefusal("generated Artifact surface is missing")
        kind = _artifact_protocol_binding(kernel, graph, role)[0]
        selected = [
            (value, _child("/" + surface, label))
            for label, value in values.items()
            if isinstance(value, dict) and value.get("artifact_kind") == kind
        ]
        if len(selected) != 1:
            raise InventoryRefusal(f"{role} has no unique generated Artifact")
        return selected[0]

    selected_contract = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["rir_structure"]["selected_collections"]

    def authority_for_member(member_name: str) -> str:
        source = selected_contract.get(member_name, {}).get("source", {})
        execution_reasons = kernel["meta_format"]["runtime_projection"][
            "execution_closure"
        ]["reasons"]
        if member_name == "diagnostic_reasons":
            return execution_reasons["authority_path"]
        if member_name == "diagnostics":
            return execution_reasons["diagnostic_authority_path"]
        if source.get("kind") != "semantic-closure" or not isinstance(
            source.get("authority_path"), str
        ):
            raise InventoryRefusal(
                f"{member_name} has no declared semantic-closure projection"
            )
        return source["authority_path"]

    def selected_rows(
        rows: list[Any],
        pointer: str,
        authority_path: str,
        *,
        excluded: tuple[str, ...] = (),
    ) -> None:
        sources = [
            (definition, source)
            for _, definition, source in _authority_path_rows(
                kernel, graph, "language_bundle." + authority_path
            )
        ]
        for index, row in enumerate(rows):
            target = f"{pointer}/{index}"
            if isinstance(row, dict) and {"package", "definition"} <= set(row):
                owner = row["package"]
                add(token("namespace", (), owner), target + "/package", law_model)
                candidates = [
                    (definition, source)
                    for package, definition, source in _authority_path_rows(
                        kernel, graph, "language_bundle." + authority_path
                    )
                    if package == owner
                ]
                target += "/definition"
                value = row["definition"]
                matches = [
                    source
                    for definition, source in candidates
                    if _consumer_b_canonical_equal(definition, value)
                ]
                if not matches and isinstance(value, dict):
                    matches = [
                        source
                        for definition, source in candidates
                        if isinstance(definition, dict)
                        and set(definition) - set(value) == set(excluded)
                        and all(
                            _consumer_b_canonical_equal(definition[key], item)
                            for key, item in value.items()
                        )
                    ]
                    if len(matches) == 1:
                        for key in value:
                            copy(_child(matches[0], key), _child(target, key))
                        continue
            else:
                value = row
                matches = [
                    source
                    for definition, source in sources
                    if _consumer_b_canonical_equal(definition, value)
                ]
            if len(matches) != 1:
                raise InventoryRefusal(
                    f"selected semantic row has no exact authority at {target}"
                )
            copy(matches[0], target)

    def value_contract(value: dict[str, Any], pointer: str) -> None:
        if "type" in value:
            type_ref(value["type"], pointer + "/type")
        fixed = kernel["meta_format"]["runtime_program"]["fixed_value_contracts"]
        if "type" in value and any(
            value["type"] == row["type"] for row in fixed.values()
        ):
            return
        for _, lowering, lower_pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.model_lowerings"
        ):
            collections = {
                row["id"]: row for row in lowering["runtime_projection"]["collections"]
            }
            for index, seed in enumerate(lowering["runtime_projection"]["seeds"]):
                path = seed["declaration_path"]
                if len(path) != 1 or path[0] not in value:
                    continue
                source = collections[seed["collection"]]["source"]
                if source["kind"] != "semantic-closure":
                    continue
                role = source["authority_path"]
                projection = next(
                    row
                    for row in kernel["meta_format"]["package_release"][
                        "semantic_closure"
                    ]["projections"]
                    if row["authority_path"] == role
                )
                target = (
                    []
                    if projection["key_member"] is None
                    else [projection["key_member"]]
                )
                if seed["target_path"] == target:
                    add(
                        token(role, (), value[path[0]]),
                        _child(pointer, path[0]),
                        f"{lower_pointer}/runtime_projection/seeds/{index}",
                    )

    def operation_binding(value: dict[str, Any], pointer: str) -> tuple[str, str]:
        coordinate = operation_ref(value["operation"], pointer + "/operation", law_rir)
        for index, argument in enumerate(value["arguments"]):
            ap = f"{pointer}/arguments/{index}"
            port_owner = operation_ref(
                argument["port"]["operation"], ap + "/port/operation", law_rir
            )
            add(
                token("operation-port", port_owner, argument["port"]["name"]),
                ap + "/port/name",
                law_rir,
            )
            operand = argument["operand"]
            if operand["kind"] == "symbol":
                source_coord(operand["symbol"], ap + "/operand/symbol", law_rir)
            elif operand["kind"] in {"port", "local"}:
                member_name = operand["kind"]
                add(
                    token("operation-" + member_name, coordinate, operand[member_name]),
                    ap + "/operand/" + member_name,
                    law_rir,
                )
            elif operand["kind"] == "literal":
                typed_literal(operand["value"], ap + "/operand/value")
            else:
                raise InventoryRefusal("RIR operand is unclassified")
        closure = value.get("closure", {"effects": [], "refusals": []})
        for index, effect in enumerate(closure["effects"]):
            add(
                token("runtime-effect", (), effect),
                f"{pointer}/closure/effects/{index}",
                law_rir,
            )
        for index, reason in enumerate(closure["refusals"]):
            add(
                token("language.reasons", (), reason),
                f"{pointer}/closure/refusals/{index}",
                law_rir,
            )
        for index, outcome in enumerate(value.get("outcomes", [])):
            op = f"{pointer}/outcomes/{index}"
            add(
                token("operation-outcome", coordinate, outcome["outcome"]),
                op + "/outcome",
                law_rir,
            )
            if outcome["action"]["kind"] == "propagate":
                add(
                    token(
                        "operation-outcome", coordinate, outcome["action"]["outcome"]
                    ),
                    op + "/action/outcome",
                    law_rir,
                )
        return coordinate

    def rir_occurrences(rir: dict[str, Any], root: str) -> None:
        source = graph.get("source")
        if not isinstance(source, dict):
            raise InventoryRefusal("RIR has no Source owner")
        model = source_model()
        for index, declaration in enumerate(rir["declarations"]):
            dp = f"{root}/declarations/{index}"
            source_coord(
                declaration["resolved_symbol"], dp + "/resolved_symbol", law_rir
            )
            coordinate = declaration["resolved_symbol"]
            add(
                token(
                    "source-symbol",
                    (coordinate["model"], coordinate["module"]),
                    declaration["symbol"],
                ),
                dp + "/symbol",
                law_rir,
            )
            type_ref(declaration["type_identity"], dp + "/type_identity")
            value_contract(declaration, dp)
        for index, entry in enumerate(rir["entrypoints"]):
            ep = f"{root}/entrypoints/{index}"
            add(token("source-entrypoint", (model,), entry["id"]), ep + "/id", law_rir)
            coordinate = operation_binding(entry, ep)
            for member_name in (
                "scenario_input_contract",
                "event_local_payload_contract",
                "external_fact_contract",
            ):
                for ti, row in enumerate(entry[member_name]["targets"]):
                    tp = f"{ep}/{member_name}/targets/{ti}"
                    source_coord(row["target"], tp + "/target", law_rir)
                    if "value_contract" in row:
                        value_contract(row["value_contract"], tp + "/value_contract")
            for member_name, role in (
                ("effects", "runtime-effect"),
                ("refusals", "language.reasons"),
            ):
                for ei, value in enumerate(entry[member_name]):
                    add(token(role, (), value), f"{ep}/{member_name}/{ei}", law_rir)
            if entry["result"]["kind"] == "value":
                type_ref(entry["result"]["type"], ep + "/result/type")
            if entry.get("default_outcome") is not None:
                add(
                    token("operation-outcome", coordinate, entry["default_outcome"]),
                    ep + "/default_outcome",
                    law_rir,
                )
        for index, site in enumerate(rir["call_sites"]):
            cp = f"{root}/call_sites/{index}"
            parent = operation_ref(
                site["parent_operation"], cp + "/parent_operation", law_rir
            )
            add(token("operation-site", parent, site["site"]), cp + "/site", law_rir)
            operation_binding(site, cp)
        selected = rir["selected_semantics"]
        selected_sources: list[tuple[str | None, Any, str]] = []
        for member_name, rows in selected.items():
            if member_name in {
                "packages",
                "package_semantic_closures",
            } or not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                path = f"{root}/selected_semantics/{member_name}/{index}"
                if isinstance(row, dict) and {"package", "definition"} <= set(row):
                    selected_sources.append(
                        (row["package"], row["definition"], path + "/definition")
                    )
                else:
                    selected_sources.append((None, row, path))
        for member_name, rows in selected.items():
            pointer = f"{root}/selected_semantics/{member_name}"
            if member_name == "packages":
                for index, row in enumerate(rows):
                    add(
                        token("namespace", (), row["id"]),
                        f"{pointer}/{index}/id",
                        law_rir,
                    )
            elif member_name == "capability_bindings":
                for index, row in enumerate(rows):
                    rp = f"{pointer}/{index}"
                    add(
                        token("language.capabilities", (), row["capability"]),
                        rp + "/capability",
                        law_rir,
                    )
                    add(
                        token("namespace", (), row["provider_package"]),
                        rp + "/provider_package",
                        law_rir,
                    )
            elif member_name == "types":
                for index, row in enumerate(rows):
                    rp = f"{pointer}/{index}"
                    add(
                        token("namespace", (), row["package"]), rp + "/package", law_rir
                    )
                    add(
                        token("type", (row["package"],), row["id"]), rp + "/id", law_rir
                    )
                    add(
                        token("language.constructors", (), row["constructor"]),
                        rp + "/constructor",
                        law_rir,
                    )
            elif member_name == "language_rules":
                for index, name in enumerate(rows):
                    add(
                        token("language.rules", (), name), f"{pointer}/{index}", law_rir
                    )
            elif member_name == "package_semantic_closures":
                for ci, closure in enumerate(rows):
                    cp = f"{pointer}/{ci}"
                    owner = closure["package"]
                    add(token("namespace", (), owner), cp + "/package", law_rir)
                    for ei, entry in enumerate(closure["definitions"]):
                        for di, definition in enumerate(entry["definitions"]):
                            matches = [
                                source
                                for package, value, source in selected_sources
                                if package in {None, owner}
                                and _consumer_b_canonical_equal(value, definition)
                            ]
                            if not matches:
                                matches = [
                                    source
                                    for package, value, source in _authority_path_rows(
                                        kernel,
                                        graph,
                                        "language_bundle." + entry["authority_path"],
                                    )
                                    if package == owner
                                    and _consumer_b_canonical_equal(value, definition)
                                ]
                            if len(matches) != 1:
                                raise InventoryRefusal(
                                    "RIR closure has no unique selected owner"
                                )
                            copy(matches[0], f"{cp}/definitions/{ei}/definitions/{di}")
            elif isinstance(rows, list) and rows:
                excluded = tuple(
                    selected_contract.get(member_name, {}).get("excluded_members", [])
                )
                selected_rows(
                    rows, pointer, authority_for_member(member_name), excluded=excluded
                )

    # Independently declared lexical roles in the Experiment input.
    experiment = graph.get("experiment")
    if experiment is not None:
        if not isinstance(experiment, dict) or not isinstance(
            graph.get("source"), dict
        ):
            raise InventoryRefusal("Experiment has no Model Source owner")
        source_projection = _source_projection(kernel, graph)
        if source_projection is None:
            raise InventoryRefusal("Experiment has no semantic Source projection")
        source = source_projection.value
        model = source_model()
        exp_id = experiment["id"]
        add(
            token("experiment", (), exp_id),
            "/experiment/id",
            law_exp,
            use="declaration",
        )
        add(
            token("language.runtime_profiles", (), experiment["runtime"]["profile"]),
            "/experiment/runtime/profile",
            law_exp,
        )
        add(
            token(
                "language.experiment_acceptance_judgments",
                (),
                experiment["acceptance"]["policy"],
            ),
            "/experiment/acceptance/policy",
            law_exp,
        )
        for mi, metric in enumerate(experiment["metrics"]):
            mp = f"/experiment/metrics/{mi}"
            name = metric["id"]
            add(
                token("experiment-metric", (exp_id,), name),
                mp + "/id",
                law_exp,
                use="declaration",
            )
            add(
                token("language.quantity.units", (), metric["unit"]),
                mp + "/unit",
                law_exp,
            )
            # The selected observation member must have a unique authored Symbol owner.
            candidates = [
                (
                    module["id"],
                    symbol["symbol"],
                )
                for module in source["modules"]
                for symbol in module["symbols"]
                if symbol["symbol"] == metric["observation"]["member"]
            ]
            if len(candidates) != 1:
                raise InventoryRefusal("Metric member has no unique Source Symbol")
            add(
                token("source-symbol", (model, candidates[0][0]), candidates[0][1]),
                mp + "/observation/member",
                law_exp,
            )
            add(
                token(
                    "experiment-observation",
                    (exp_id, name),
                    metric["observation"]["name"],
                ),
                mp + "/observation/name",
                law_exp,
                use="declaration",
            )
            add(
                token("experiment-window", (exp_id, name), metric["window"]["name"]),
                mp + "/window/name",
                law_exp,
                use="declaration",
            )
        add_links(_experiment_input_judgment_links(kernel, graph))
        for si, scenario in enumerate(experiment["scenarios"]):
            sp = f"/experiment/scenarios/{si}"
            scope = (exp_id, scenario["id"])
            add(
                token("experiment-scenario", (exp_id,), scenario["id"]),
                sp + "/id",
                law_exp,
                use="declaration",
            )
            for ai, assignment in enumerate(scenario["assignments"]):
                ap = f"{sp}/assignments/{ai}"
                source_coord(assignment["target"], ap + "/target", law_exp)
                typed_literal(assignment["value"], ap + "/value")
            for ei, event in enumerate(scenario["event_plan"]):
                ep = f"{sp}/event_plan/{ei}"
                add(
                    token("experiment-root-event", scope, event["root_event_ref"]),
                    ep + "/root_event_ref",
                    law_exp,
                    use="declaration",
                )
                if event["kind"] == "transition-invocation":
                    add(
                        token("source-entrypoint", (model,), event["entrypoint"]),
                        ep + "/entrypoint",
                        law_exp,
                    )
                    for pi, payload in enumerate(event["payload"]):
                        pp = f"{ep}/payload/{pi}"
                        source_coord(payload["target"], pp + "/target", law_exp)
                        typed_literal(payload["value"], pp + "/value")
                    for ri, reference in enumerate(event.get("event_references", [])):
                        add(
                            token(
                                "experiment-root-event",
                                scope,
                                reference["root_event_ref"],
                            ),
                            f"{ep}/event_references/{ri}/root_event_ref",
                            law_exp,
                        )
                elif event["kind"] == "external-input":
                    for fi, fact in enumerate(event["facts"]):
                        fp = f"{ep}/facts/{fi}"
                        source_coord(fact["target"], fp + "/target", law_exp)
                        typed_literal(fact["value"], fp + "/value")
                else:
                    raise InventoryRefusal("Experiment Event kind is unclassified")

    artifacts = graph.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, dict):
            raise InventoryRefusal("Model Artifact surface is unclassified")
        model_contract = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["model_structure"]
        roles = (set(model_contract["containers"]) - {"model-build-command-input"}) | {
            "rir-semantic-payload"
        }
        for role in roles:
            value, pointer = member("artifacts", role)
            add(
                token("language.artifact_contracts", (), value["artifact_kind"]),
                pointer + "/artifact_kind",
                law_artifact,
            )
        lock, lp = member("artifacts", "package-lock")
        packages = {
            row["id"]: (index, row) for index, row in enumerate(graph["packages"])
        }
        for index, row in enumerate(lock["packages"]):
            add(
                token("namespace", (), row["id"]),
                f"{lp}/packages/{index}/id",
                law_model,
            )
        for index, name in enumerate(lock["root_requirements"]):
            add(
                token("namespace", (), name),
                f"{lp}/root_requirements/{index}",
                law_model,
            )
        for index, edge in enumerate(lock["dependency_edges"]):
            for member_name in ("from_package", "to_package"):
                add(
                    token("namespace", (), edge[member_name]),
                    f"{lp}/dependency_edges/{index}/{member_name}",
                    law_model,
                )
        projection_shapes = {
            row["authority_path"]: row
            for row in kernel["meta_format"]["package_release"]["semantic_closure"][
                "projections"
            ]
        }
        for index, closure in enumerate(lock["package_semantic_closures"]):
            cp = f"{lp}/package_semantic_closures/{index}"
            package_index, package = packages[closure["package"]]
            add(token("namespace", (), closure["package"]), cp + "/package", law_model)
            source_entries = {
                row["authority_path"]: (i, row)
                for i, row in enumerate(package["semantic_closure"])
            }
            for ci, entry in enumerate(closure["definitions"]):
                source_index, source_entry = source_entries[entry["authority_path"]]
                source = f"/packages/{package_index}/semantic_closure/{source_index}/definitions"
                target = f"{cp}/definitions/{ci}/definitions"
                if _consumer_b_canonical_equal(
                    source_entry["definitions"], entry["definitions"]
                ):
                    copy(source, target)
                    continue
                key = projection_shapes[entry["authority_path"]]["key_member"]
                if key is None:
                    raise InventoryRefusal("selected scalar closure changed")
                candidates = {
                    row[key]: (i, row)
                    for i, row in enumerate(source_entry["definitions"])
                }
                for di, definition in enumerate(entry["definitions"]):
                    source_i, original = candidates[definition[key]]
                    if set(original) - set(definition) != {"extensions"} or any(
                        not _consumer_b_canonical_equal(original[k], v)
                        for k, v in definition.items()
                    ):
                        raise InventoryRefusal(
                            "selected closure has no exact source projection"
                        )
                    for key_name in definition:
                        copy(
                            f"{source}/{source_i}/{key_name}",
                            f"{target}/{di}/{key_name}",
                        )
        shared = model_contract["namespace_structure"]["shared_collections"]
        for member_name in shared:
            if (
                member_name not in lock
                or not isinstance(lock[member_name], list)
                or member_name in {"capability_bindings", "types"}
            ):
                continue
            if member_name == "language_rules":
                for index, name in enumerate(lock[member_name]):
                    add(
                        token("language.rules", (), name),
                        f"{lp}/{member_name}/{index}",
                        law_model,
                    )
            else:
                selected_rows(
                    lock[member_name],
                    f"{lp}/{member_name}",
                    authority_for_member(member_name),
                )
        for index, row in enumerate(lock["types"]):
            tp = f"{lp}/types/{index}"
            add(token("namespace", (), row["package"]), tp + "/package", law_model)
            add(token("type", (row["package"],), row["id"]), tp + "/id", law_model)
            add(
                token("language.constructors", (), row["constructor"]),
                tp + "/constructor",
                law_model,
            )
        for index, binding in enumerate(lock["capability_bindings"]):
            bp = f"{lp}/capability_bindings/{index}"
            add(
                token("language.capabilities", (), binding["capability"]),
                bp + "/capability",
                law_model,
            )
            add(
                token("namespace", (), binding["provider_package"]),
                bp + "/provider_package",
                law_model,
            )
        if lock["resolution_profile"]:
            matches = [
                source
                for _, row, source in _authority_path_rows(
                    kernel, graph, "language_bundle.language.resolution_profiles"
                )
                if _consumer_b_canonical_equal(row, lock["resolution_profile"])
            ]
            if len(matches) != 1:
                raise InventoryRefusal(
                    "selected resolution profile has no unique owner"
                )
            copy(matches[0], lp + "/resolution_profile")
        for index, code in enumerate(lock["diagnostics"]):
            add(token("diagnostics", (), code), f"{lp}/diagnostics/{index}", law_model)
        selected_rows(
            lock["diagnostic_reasons"],
            lp + "/diagnostic_reasons",
            authority_for_member("diagnostic_reasons"),
        )
        for member_name, value in lock["selected_semantics"].items():
            target = f"{lp}/selected_semantics/{member_name}"
            if member_name in lock and _consumer_b_canonical_equal(
                lock[member_name], value
            ):
                copy(lp + "/" + member_name, target)
            elif member_name == "packages":
                for index, row in enumerate(value):
                    add(
                        token("namespace", (), row["id"]),
                        f"{target}/{index}/id",
                        law_model,
                    )
            elif isinstance(value, list) and value:
                selected_rows(value, target, authority_for_member(member_name))
        capability, cp = member("artifacts", "capability-manifest")
        for index, row in enumerate(capability["packages"]):
            add(
                token("namespace", (), row["id"]),
                f"{cp}/packages/{index}/id",
                law_model,
            )
        for member_name in shared:
            if member_name in capability and member_name in lock:
                copy(lp + "/" + member_name, cp + "/" + member_name)
        rir, rp = member("artifacts", "rir-semantic-payload")
        rir_occurrences(rir, rp)
        explanation, ep = member("artifacts", "model-explanation")
        for index, row in enumerate(explanation["declaration_explanations"]):
            pointer = f"{ep}/declaration_explanations/{index}"
            source_coord(
                row["resolved_symbol"], pointer + "/resolved_symbol", law_model
            )
            type_ref(row["type_identity"], pointer + "/type_identity")
        for index, row in enumerate(explanation["operation_explanations"]):
            pointer = f"{ep}/operation_explanations/{index}"
            coord = operation_ref(
                {"package": row["package"], "id": row["id"]}, pointer, law_model
            )
            for name, role in (
                ("effects", "runtime-effect"),
                ("refusals", "language.reasons"),
            ):
                for j, value in enumerate(row[name]):
                    add(token(role, (), value), f"{pointer}/{name}/{j}", law_model)
            for j, name in enumerate(row["control_nodes"]):
                add(
                    token("kernel.meta_format.runtime_program.nodes", (), name),
                    f"{pointer}/control_nodes/{j}",
                    "/meta_format/runtime_program/nodes",
                )
            for j, name in enumerate(row["rng_streams"]):
                add(
                    token("named-stream", coord, name),
                    f"{pointer}/rng_streams/{j}",
                    "/meta_format/runtime_program/named_rng",
                )
            for j, outcome in enumerate(row["outcomes"]):
                add(
                    token("operation-outcome", coord, outcome["id"]),
                    f"{pointer}/outcomes/{j}/id",
                    law_model,
                )
            if row["default_outcome"] is not None:
                add(
                    token("operation-outcome", coord, row["default_outcome"]),
                    pointer + "/default_outcome",
                    law_model,
                )
        debug, dp = member("artifacts", "debug-map")
        source_keys = source_key_tokens(kernel, graph)
        for index, entry in enumerate(debug["entries"]):
            current, target = "/source", f"{dp}/entries/{index}/source_pointer"
            for part_index, part in enumerate(
                _json_pointer_segments(entry["source_pointer"])
            ):
                current = _child(current, part)
                if current in source_keys:
                    add(
                        source_keys[current],
                        target,
                        law_model,
                        location="json-pointer",
                        projection=str(part_index),
                    )
        receipt, receipt_pointer = member("artifacts", "resolution-receipt")
        add(
            token("language.resolution_profiles", (), receipt["resolution_profile"]),
            receipt_pointer + "/resolution_profile",
            law_model,
        )
        for index, code in enumerate(receipt["diagnostics"]):
            add(
                token("diagnostics", (), code),
                f"{receipt_pointer}/diagnostics/{index}",
                law_model,
            )

    results = graph.get("results")
    if results is not None:
        if not isinstance(results, dict) or experiment is None or artifacts is None:
            raise InventoryRefusal(
                "Runtime results have no Experiment and Model owners"
            )
        protocol = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]
        fixed = {
            "resolved-runtime-profile",
            "evaluator-capability-manifest",
            "event-trace",
            "snapshot-series",
            "metric-dataset",
        }
        kinds = {row["artifact_kind"] for row in results.values()}
        primary_roles = {
            role
            for role in protocol["metric_outcome_structure"]["outcomes"]
            if _artifact_protocol_binding(kernel, graph, role)[0] in kinds
        }
        if len(primary_roles) != 1:
            raise InventoryRefusal("Runtime outcome has no unique protocol owner")
        roles = fixed | primary_roles
        for role in roles:
            value, pointer = member("results", role)
            add(
                token("language.artifact_contracts", (), value["artifact_kind"]),
                pointer + "/artifact_kind",
                law_artifact,
            )
        rir, _ = member("artifacts", "rir-semantic-payload")
        model = source_model()
        exp_id = experiment["id"]
        entrypoints = {row["id"]: row for row in rir["entrypoints"]}
        operations = {
            (row["package"], row["definition"]["id"]): row["definition"]
            for row in rir["selected_semantics"]["operations"]
        }
        declarations = {row["symbol"]: row for row in rir["declarations"]}
        call_sites = {
            row["identity"]: (
                (row["parent_operation"]["package"], row["parent_operation"]["id"]),
                row["site"],
                (row["operation"]["package"], row["operation"]["id"]),
            )
            for row in rir["call_sites"]
        }
        metrics = {row["id"]: row for row in experiment["metrics"]}

        def scenario_token(name: str) -> Any:
            return token("experiment-scenario", (exp_id,), name)

        def metric_token(name: str) -> Any:
            return token("experiment-metric", (exp_id,), name)

        def root_event(scenario_name: str, name: str) -> Any:
            return token("experiment-root-event", (exp_id, scenario_name), name)

        def metric_selector(
            metric_name: str, path: tuple[str, ...], value: str, pointer: str
        ) -> None:
            definition = metrics.get(metric_name)
            if definition is None or _at(definition, path) != value:
                raise InventoryRefusal(
                    "Runtime Metric selector is not Experiment-owned"
                )
            add(token("experiment-metric-label", path, value), pointer, law_trace)

        def symbol_name(name: str, pointer: str) -> None:
            declaration = declarations.get(name)
            if declaration is None:
                raise InventoryRefusal("Runtime Symbol display has no RIR declaration")
            coordinate = declaration["resolved_symbol"]
            add(
                token(
                    "source-symbol", (coordinate["model"], coordinate["module"]), name
                ),
                pointer,
                law_trace,
            )

        def named_value(row: dict[str, Any], pointer: str) -> None:
            symbol_name(row["name"], pointer + "/name")
            if "value" in row:
                typed_literal(row["value"], pointer + "/value")

        def root_map(rows: list[dict[str, Any]], pointer: str) -> None:
            for index, row in enumerate(rows):
                rp = f"{pointer}/{index}"
                add(scenario_token(row["scenario"]), rp + "/scenario", law_trace)
                add(
                    root_event(row["scenario"], row["root_event_ref"]),
                    rp + "/root_event_ref",
                    law_trace,
                )

        def terminal(rows: list[dict[str, Any]], pointer: str) -> None:
            for index, row in enumerate(rows):
                add(
                    scenario_token(row["scenario"]),
                    f"{pointer}/{index}/scenario",
                    law_trace,
                )

        def call_path(value: str, pointer: str) -> tuple[str, str]:
            segments = _call_path_segments(value)
            start = entrypoints.get(segments[0])
            if start is None:
                raise InventoryRefusal("Runtime call path has no Entry Point owner")
            add(
                token("source-entrypoint", (model,), segments[0]),
                pointer,
                law_trace,
                location="call-path",
                projection="0",
            )
            parent = (start["operation"]["package"], start["operation"]["id"])
            for index, part in enumerate(segments[1:], start=1):
                if re.fullmatch(r"@[0-9]+", part):
                    continue
                matches = [
                    row for row in call_sites.values() if row[:2] == (parent, part)
                ]
                if len(matches) != 1:
                    raise InventoryRefusal("Runtime call path site has no RIR owner")
                add(
                    token("operation-site", parent, part),
                    pointer,
                    law_trace,
                    location="call-path",
                    projection=str(index),
                )
                parent = matches[0][2]
            return parent

        def event_spec(value: dict[str, Any], pointer: str, scenario_name: str) -> None:
            kind = value["kind"]
            if kind == "external-input":
                add(
                    root_event(scenario_name, value["root_event_ref"]),
                    pointer + "/root_event_ref",
                    law_trace,
                )
                for index, fact in enumerate(value["facts"]):
                    fp = f"{pointer}/facts/{index}"
                    source_coord(fact["target"], fp + "/target", law_trace)
                    typed_literal(fact["value"], fp + "/value")
            elif kind == "transition-invocation":
                add(
                    token("source-entrypoint", (model,), value["entrypoint"]),
                    pointer + "/entrypoint",
                    law_trace,
                )
                add(
                    root_event(scenario_name, value["root_event_ref"]),
                    pointer + "/root_event_ref",
                    law_trace,
                )
                for index, payload in enumerate(value["payload"]):
                    pp = f"{pointer}/payload/{index}"
                    source_coord(payload["target"], pp + "/target", law_trace)
                    typed_literal(payload["value"], pp + "/value")
            elif kind == "scheduled-transition":
                coordinate = operation_ref(
                    value["operation"], pointer + "/operation", law_trace
                )
                if coordinate not in operations:
                    raise InventoryRefusal("scheduled Event has no selected Operation")
                for index, argument in enumerate(value["arguments"]):
                    ap = f"{pointer}/arguments/{index}"
                    symbol_name(argument["name"], ap + "/name")
                    typed_literal(argument["value"], ap + "/value")
                for index, reference in enumerate(value["state_references"]):
                    rp = f"{pointer}/state_references/{index}"
                    symbol_name(reference["name"], rp + "/name")
                    source_coord(reference["target"], rp + "/target", law_trace)
            elif kind != "observation":
                raise InventoryRefusal("Runtime Event Spec kind is unclassified")

        trace, tp = member("results", "event-trace")
        current_scenario = trace["scenario"]
        add(scenario_token(current_scenario), tp + "/scenario", law_trace)
        root_map(trace["root_event_map"], tp + "/root_event_map")
        terminal(trace["terminal_statuses"], tp + "/terminal_statuses")
        scheduled_by_event = {}
        for parent_event in trace["events"]:
            for schedule in parent_event["schedules"]:
                child = schedule["event_id"]
                if child in scheduled_by_event:
                    raise InventoryRefusal("scheduled Event provenance is ambiguous")
                scheduled_by_event[child] = (
                    parent_event["event_id"],
                    schedule["call_site_identity"],
                    (schedule["operation"]["package"], schedule["operation"]["id"]),
                )
        for index, event in enumerate(trace["events"]):
            ep = f"{tp}/events/{index}"
            executed = set()
            event_operation = None
            if event.get("root_event_ref") is not None:
                add(
                    root_event(current_scenario, event["root_event_ref"]),
                    ep + "/root_event_ref",
                    law_trace,
                )
            if event.get("entrypoint") is not None:
                name = event["entrypoint"]["id"]
                executed.add(name)
                add(
                    token("source-entrypoint", (model,), name),
                    ep + "/entrypoint/id",
                    law_trace,
                )
            if event.get("operation") is not None:
                if event.get("entrypoint") is not None:
                    start = entrypoints[event["entrypoint"]["id"]]
                    coordinate = (
                        start["operation"]["package"],
                        start["operation"]["id"],
                    )
                else:
                    provenance = scheduled_by_event.get(event["event_id"])
                    if (
                        provenance is None
                        or (
                            event.get("parent_event_id"),
                            event.get("schedule_call_site_identity"),
                        )
                        != provenance[:2]
                    ):
                        raise InventoryRefusal(
                            "Trace Operation has no scheduled provenance"
                        )
                    coordinate = provenance[2]
                if coordinate not in operations or event["operation"] != coordinate[1]:
                    raise InventoryRefusal("Trace Operation disagrees with its owner")
                add(
                    token("language.operations", coordinate[:1], coordinate[1]),
                    ep + "/operation",
                    law_trace,
                )
                event_operation = coordinate
                add(
                    token("operation-outcome", coordinate, event["outcome"]["id"]),
                    ep + "/outcome/id",
                    law_trace,
                )
            for index2, row in enumerate(event["facts"]):
                named_value(row, f"{ep}/facts/{index2}")
            for member_name in ("state_before", "state_after"):
                for index2, row in enumerate(event[member_name]):
                    named_value(row, f"{ep}/{member_name}/{index2}")
            for index2, call in enumerate(event["calls"]):
                cp = f"{ep}/calls/{index2}"
                coordinate = operation_ref(
                    call["operation"], cp + "/operation", law_trace
                )
                site = call_sites.get(call["call_site_identity"])
                if site is None or site[2] != coordinate:
                    raise InventoryRefusal("Trace call has no RIR Call Site owner")
                parts = _call_path_segments(call["site"])
                if parts != [site[0][1], site[1]]:
                    raise InventoryRefusal(
                        "Trace call label disagrees with its RIR owner"
                    )
                executed.add(call["site"])
                add(
                    token("language.operations", site[0][:1], site[0][1]),
                    cp + "/site",
                    law_trace,
                    location="call-path",
                    projection="0",
                )
                add(
                    token("operation-site", site[0], site[1]),
                    cp + "/site",
                    law_trace,
                    location="call-path",
                    projection="1",
                )
                add(
                    token("operation-outcome", coordinate, call["outcome"]["id"]),
                    cp + "/outcome/id",
                    law_trace,
                )
            for index2, schedule in enumerate(event["schedules"]):
                sp = f"{ep}/schedules/{index2}"
                coordinate = operation_ref(
                    schedule["operation"], sp + "/operation", law_trace
                )
                if (
                    coordinate not in operations
                    or schedule["call_path"] not in executed
                ):
                    raise InventoryRefusal(
                        "scheduled call has no selected execution owner"
                    )
                parent = call_path(schedule["call_path"], sp + "/call_path")
                if schedule["parent_operation"] != parent[1]:
                    raise InventoryRefusal("scheduled parent differs from call path")
                add(
                    token("language.operations", parent[:1], parent[1]),
                    sp + "/parent_operation",
                    law_trace,
                )
                for j, row in enumerate(schedule["arguments"]):
                    named_value(row, f"{sp}/arguments/{j}")
                for j, row in enumerate(schedule["state_references"]):
                    rp = f"{sp}/state_references/{j}"
                    symbol_name(row["name"], rp + "/name")
                    source_coord(row["target"], rp + "/target", law_trace)
            if event.get("observation") is not None:
                observation = event["observation"]
                add(
                    metric_token(observation["metric"]),
                    ep + "/observation/metric",
                    law_trace,
                )
                add(
                    token(
                        "experiment-window",
                        (exp_id, observation["metric"]),
                        observation["window"]["name"],
                    ),
                    ep + "/observation/window/name",
                    law_trace,
                )
                metric_selector(
                    observation["metric"],
                    ("window", "kind"),
                    observation["window"]["kind"],
                    ep + "/observation/window/kind",
                )
            for j, draw in enumerate(event["rng_draws"]):
                if event_operation is None:
                    raise InventoryRefusal("RNG draw has no Operation owner")
                add(
                    token("named-stream", event_operation, draw["stream"]),
                    f"{ep}/rng_draws/{j}/stream",
                    law_trace,
                )
        series, sp = member("results", "snapshot-series")
        law_trace = "/meta_format/language_definitions/wire_schema_protocol_roles/runtime_evidence_structure"
        add(scenario_token(series["scenario"]), sp + "/scenario", law_trace)
        root_map(series["root_event_map"], sp + "/root_event_map")
        for index, record in enumerate(series["event_catalog"]):
            rp = f"{sp}/event_catalog/{index}"
            add(scenario_token(record["scenario"]), rp + "/scenario", law_trace)
            event_spec(record["event_spec"], rp + "/event_spec", record["scenario"])
        for index, snapshot in enumerate(series["snapshots"]):
            pp = f"{sp}/snapshots/{index}"
            add(scenario_token(snapshot["scenario"]), pp + "/scenario", law_trace)
            add(
                scenario_token(snapshot["scenario"]),
                pp + "/name",
                law_trace,
                location="snapshot-name",
            )
            for j, row in enumerate(snapshot["values"]):
                named_value(row, f"{pp}/values/{j}")
        dataset, dp = member("results", "metric-dataset")
        law_trace = "/meta_format/language_definitions/wire_schema_protocol_roles/metric_outcome_structure"
        for index, sample in enumerate(dataset["samples"]):
            pp = f"{dp}/samples/{index}"
            add(metric_token(sample["metric"]), pp + "/metric", law_trace)
            metric_selector(
                sample["metric"],
                ("observation", "source"),
                sample["source"],
                pp + "/source",
            )
            provenance = sample["provenance"]
            metric_selector(
                sample["metric"],
                ("observation", "source"),
                provenance["observation_source"],
                pp + "/provenance/observation_source",
            )
            add(scenario_token(sample["scenario"]), pp + "/scenario", law_trace)
            if sample["replication_identity"] != sample["scenario"]:
                raise InventoryRefusal("Metric replication has no Scenario owner")
            add(
                scenario_token(sample["replication_identity"]),
                pp + "/replication_identity",
                law_trace,
            )
            add(
                token("language.quantity.units", (), sample["unit"]),
                pp + "/unit",
                law_trace,
            )
            add(
                token(
                    "experiment-window", (exp_id, sample["metric"]), sample["window"]
                ),
                pp + "/window",
                law_trace,
            )
            symbol_name(sample["member"], pp + "/member")
            add(
                scenario_token(provenance["scenario"]),
                pp + "/provenance/scenario",
                law_trace,
            )
            add(
                token(
                    "experiment-observation",
                    (exp_id, sample["metric"]),
                    provenance["observation_name"],
                ),
                pp + "/provenance/observation_name",
                law_trace,
            )
            symbol_name(
                provenance["observation_member"], pp + "/provenance/observation_member"
            )
        profile, pp = member("results", "resolved-runtime-profile")
        law_trace = "/meta_format/language_definitions/wire_schema_protocol_roles/runtime_capability_structure"
        matches = [
            source
            for _, row, source in _authority_path_rows(
                kernel, graph, "language_bundle.language.runtime_profiles"
            )
            if _consumer_b_canonical_equal(row, profile["runtime_profile"])
        ]
        if len(matches) != 1:
            raise InventoryRefusal("Resolved Runtime profile has no unique authority")
        copy(matches[0], pp + "/runtime_profile")
        judgments = profile["experiment_judgments"]
        add(
            token(
                "language.experiment_acceptance_judgments",
                (),
                judgments["acceptance"]["id"],
            ),
            pp + "/experiment_judgments/acceptance/id",
            law_trace,
        )
        for index, row in enumerate(judgments["metrics"]):
            jp = f"{pp}/experiment_judgments/metrics/{index}"
            add(metric_token(row["metric"]), jp + "/metric", law_trace)
            matches = [
                source
                for _, definition, source in _authority_path_rows(
                    kernel,
                    graph,
                    "language_bundle.language.experiment_metric_judgments",
                )
                if _consumer_b_canonical_equal(definition, row["judgment"])
            ]
            if len(matches) != 1:
                raise InventoryRefusal(
                    "Resolved Metric judgment has no unique authority"
                )
            copy(matches[0], jp + "/judgment")
        manifest, mp = member("results", "evaluator-capability-manifest")
        for name, role in (
            ("effects", "runtime-effect"),
            ("numeric_policies", "language.quantity.numeric_policies"),
            ("runtime_profiles", "language.runtime_profiles"),
        ):
            for index, value in enumerate(manifest[name]):
                add(token(role, (), value), f"{mp}/{name}/{index}", law_trace)
        for index, name in enumerate(manifest["instruction_nodes"]):
            add(
                token("kernel.meta_format.runtime_program.nodes", (), name),
                f"{mp}/instruction_nodes/{index}",
                "/meta_format/runtime_program/nodes",
            )
        primary, primary_pointer = member("results", next(iter(primary_roles)))
        law_trace = "/meta_format/language_definitions/wire_schema_protocol_roles/metric_outcome_structure"
        root_map(primary["root_event_map"], primary_pointer + "/root_event_map")
        terminal(primary["terminal_statuses"], primary_pointer + "/terminal_statuses")
        for index, name in enumerate(primary.get("failed_metrics", [])):
            add(
                metric_token(name),
                f"{primary_pointer}/failed_metrics/{index}",
                law_trace,
            )
        copy(tp + "/root_event_map", sp + "/root_event_map")
        copy(tp + "/root_event_map", primary_pointer + "/root_event_map")
        copy(tp + "/terminal_statuses", primary_pointer + "/terminal_statuses")
        add_links(_resolved_judgment_links(kernel, graph))

    # Compare only after all direct roles and checked projections are assembled.
    # The caller's target-root occurrences are never a seed for projection closure.
    external = {
        row for row in inventory.occurrences if not row.pointer.startswith(roots)
    }
    inferred = set(
        _close_projection_occurrences(graph, external | expected, projections)
    )
    required = {row for row in inferred if row.pointer.startswith(roots)}
    actual = {row for row in inventory.occurrences if row.pointer.startswith(roots)}
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        first = missing[0].pointer if missing else extra[0].pointer
        raise InventoryRefusal(
            f"execution occurrence coverage is incomplete or misowned at {first}: missing={len(missing)} extra={len(extra)}"
        )
    fixed_tokens = {
        row.token for row in required if row.token.role.startswith("kernel.")
    }
    for contract in kernel["meta_format"]["runtime_program"][
        "fixed_value_contracts"
    ].values():
        ref = contract["type"]
        fixed_tokens.add(token("namespace", (), ref["package"]))
        fixed_tokens.add(token("type", (ref["package"],), ref["id"]))
    primitive_signals = {
        ("runtime", signal)
        for node in kernel["meta_format"]["runtime_program"]["nodes"]
        for signal in node.get("refusals", [])
    } | {
        (row["stage"], row["signal"])
        for row in kernel["meta_format"]["runtime_projection"]["execution_closure"][
            "reasons"
        ]["roots"]
        if "stage" in row and "signal" in row
    }
    fixed_tokens.update(
        token("diagnostic-signal", (stage,), signal)
        for stage, signal in primitive_signals
    )
    _, template_fixed, _, _ = _template_inventory(kernel, graph)
    fixed_tokens.update(template_fixed)
    target_tokens = {row.token for row in required}
    if inventory.reserved & target_tokens != fixed_tokens & target_tokens:
        raise InventoryRefusal(
            "execution token reserved partition differs from machine authority"
        )
    if any(gap.pointer.startswith(roots) for gap in inventory.uncovered):
        raise InventoryRefusal("execution surface retains an uncovered semantic role")
