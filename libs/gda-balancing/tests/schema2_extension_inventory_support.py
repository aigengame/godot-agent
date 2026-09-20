"""Conformance-only semantic-token inventory derived from admitted machine laws.

The reader is intentionally separate from production resolution and evaluation.
An incomplete inventory is useful evidence, but cannot authorize a rename.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
import re

import jsonschema

from schema2_bootstrap_conformance_support import (
    _consumer_b_canonical_equal,
    _consumer_b_definition_is_closed,
    _consumer_b_contract_path,
    _consumer_b_fact_contract_at_path,
    _consumer_b_evidence_claim_kinds_are_closed,
    _consumer_b_evaluate_structured_value_vector,
    _consumer_b_formula_resolution_is_closed,
    _consumer_b_value_program_instruction_is_closed,
    _consumer_b_operation_composition_subjects,
    _consumer_b_operation_relation_is_satisfied,
    _consumer_b_package_evidence_vectors_are_closed,
    _consumer_b_project_metric_outcome_schema,
    _consumer_b_project_experiment_input,
    _consumer_b_project_publication_schema,
    _consumer_b_project_template_schema,
    _consumer_b_project_model_schema,
    _consumer_b_project_runtime_outputs,
    _consumer_b_project_rir_schema,
    _consumer_b_project_replay_schema,
    _consumer_b_source_equality_values,
    _consumer_b_source_equality_items,
    _consumer_b_project_source,
    _consumer_b_project_source_role,
    _consumer_b_source_role_member_paths,
    _consumer_b_source_roles_are_closed,
    _consumer_b_project_trace_schema,
    _consumer_b_project_runtime_evidence_schemas,
    _consumer_b_replay_comparison_vector_is_closed,
    _consumer_b_package_evidence_vector_header_is_closed,
    _consumer_b_scheduler_scenario_vector_is_closed,
    _consumer_b_vector_header_is_closed,
    _consumer_b_relation_paths_are_typed,
    _consumer_b_runtime_projection_is_closed,
    _consumer_b_schema_path,
    _consumer_b_semantic_item_contract,
    _consumer_b_source_fact_transport_is_supported,
    _consumer_b_template_admission_is_closed,
    _identity_from_kernel,
)

from schema2_value_program_reference_support import (
    reference_evaluate_value_program_vector,
)


class InventoryRefusal(ValueError):
    """The graph, coverage proof, or rename map does not close."""


@dataclass(frozen=True, order=True)
class AuthorityToken:
    role: str
    owner: tuple[str, ...]
    name: str


@dataclass(frozen=True, order=True)
class TokenOccurrence:
    token: AuthorityToken
    pointer: str
    use: str
    law: str
    location: str = "value"
    projection: str = ""


@dataclass(frozen=True, order=True)
class UncoveredRole:
    pointer: str
    law: str
    reason: str


@dataclass(frozen=True)
class ExtensionInventory:
    tokens: frozenset[AuthorityToken]
    occurrences: tuple[TokenOccurrence, ...]
    reserved: frozenset[AuthorityToken]
    uncovered: tuple[UncoveredRole, ...]

    def require_complete(self) -> None:
        if self.uncovered:
            first = self.uncovered[0]
            raise InventoryRefusal(
                f"uncovered semantic role at {first.pointer}: {first.reason}"
            )


def _child(pointer: str, key: str | int) -> str:
    return pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _at(value: Any, path: Sequence[str]) -> Any:
    for part in path:
        value = value[part]
    return value


def _pointer_value(graph: Any, pointer: str) -> Any:
    value = graph
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _json_pointer_segments(value: str) -> list[str]:
    """Decode exactly the Kernel's RFC6901 pointer grammar."""
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:/(?:[^~/]|~[01])*)*", value) is None
    ):
        raise InventoryRefusal("invalid RFC6901 pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in value.split("/")[1:]]


def _call_path_segments(value: str) -> list[str]:
    """Decode the Kernel invocation path without treating fold indices as names."""
    if not isinstance(value, str) or not value:
        raise InventoryRefusal("invalid Runtime call path")
    parts = value.split("/")
    if any(not part for part in parts):
        raise InventoryRefusal("invalid Runtime call path")
    decoded = []
    for part in parts:
        if re.fullmatch(r"@[0-9]+", part):
            decoded.append(part)
            continue
        if re.fullmatch(r"(?:[^~]|~[01])+", part) is None:
            raise InventoryRefusal("invalid Runtime call path segment")
        decoded.append(part.replace("~1", "/").replace("~0", "~"))
    return decoded


def _occurrence_value(
    graph: Any, occurrence: TokenOccurrence, formula_projections: Mapping[str, Any]
) -> Any:
    if occurrence.location == "formula":
        return _pointer_value(
            formula_projections[occurrence.pointer], occurrence.projection
        )
    if occurrence.location == "json-pointer":
        if (
            not occurrence.projection.isdecimal()
            or str(int(occurrence.projection)) != occurrence.projection
        ):
            raise InventoryRefusal("noncanonical JSON pointer projection")
        return _json_pointer_segments(_pointer_value(graph, occurrence.pointer))[
            int(occurrence.projection)
        ]
    if occurrence.location == "call-path":
        if (
            not occurrence.projection.isdecimal()
            or str(int(occurrence.projection)) != occurrence.projection
        ):
            raise InventoryRefusal("noncanonical call-path projection")
        return _call_path_segments(_pointer_value(graph, occurrence.pointer))[
            int(occurrence.projection)
        ]
    if occurrence.location == "snapshot-name":
        value = _pointer_value(graph, occurrence.pointer)
        prefix = occurrence.token.name + ":"
        if not isinstance(value, str) or not value.startswith(prefix):
            raise InventoryRefusal("invalid Snapshot display name")
        return occurrence.token.name
    if occurrence.projection:
        raise InventoryRefusal("only Formula occurrences may have an AST projection")
    if occurrence.location == "value":
        return _pointer_value(graph, occurrence.pointer)
    if occurrence.location == "key":
        parent, _, encoded = occurrence.pointer.rpartition("/")
        key = encoded.replace("~1", "/").replace("~0", "~")
        container = _pointer_value(graph, parent)
        if not isinstance(container, dict) or key not in container:
            raise InventoryRefusal("key occurrence does not identify an object member")
        return key
    raise InventoryRefusal("unknown occurrence location")


def _attached_language(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    language: dict[str, Any] = {"packages": graph["packages"]}
    for projection in kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]:
        path = projection["authority_path"].split(".")
        if path[0] != "language":
            continue
        target = language
        for segment in path[1:-1]:
            target = target.setdefault(segment, {})
        target[path[-1]] = [
            definition
            for package in graph["packages"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == projection["authority_path"]
            for definition in closure["definitions"]
        ]
    # Protocol projection writes only to the derived view. Both the generated
    # schemas and RIR identity projection must stay absent from the authored graph.
    for collection in ("artifact_wire_schemas", "artifact_contracts"):
        language[collection] = [dict(row) for row in language[collection]]
    try:
        _consumer_b_project_model_schema(dict(kernel), language)
        _consumer_b_project_runtime_outputs(dict(kernel), language)
        _consumer_b_project_template_schema(dict(kernel), language)
        _consumer_b_project_publication_schema(dict(kernel), language)
        _consumer_b_project_trace_schema(dict(kernel), language)
        _consumer_b_project_runtime_evidence_schemas(dict(kernel), language)
        _consumer_b_project_metric_outcome_schema(dict(kernel), language)
        _consumer_b_project_experiment_input(dict(kernel), language)
        _consumer_b_project_replay_schema(dict(kernel), language)
        _consumer_b_project_rir_schema(dict(kernel), language)
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise InventoryRefusal("wire protocol structure does not close") from error
    return {"language": language}


def _source_profile(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    profiles = [
        row
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language.resolution_profiles"
        )
        if row.get("default") is True
    ]
    if len(profiles) != 1:
        raise InventoryRefusal("Source has no unique default resolution profile")
    return profiles[0]


def _source_projection(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    if not graph.get("source"):
        return None
    try:
        return _consumer_b_project_source(
            graph["source"], kernel, _attached_language(kernel, graph)
        )
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError) as error:
        raise InventoryRefusal(
            "Source does not match its admitted closed wire schema or semantic roles"
        ) from error


def _source_pointer(projection, pointer: str) -> str:
    """Map semantic value addresses; field-name inventory already uses authored paths."""
    if not pointer.startswith("/source/"):
        return pointer
    if projection is None:
        raise InventoryRefusal("Source occurrence has no semantic projection")
    return "/source" + projection.authored_paths[pointer.removeprefix("/source")]


def _source_value_at(source: Any, pointer: str) -> Any:
    for segment in pointer.lstrip("/").split("/"):
        member = segment.replace("~1", "/").replace("~0", "~")
        source = source[int(member)] if isinstance(source, list) else source[member]
    return source


def _formula_policy_rows(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    return [
        (profile["formula_resolution"], pointer + "/formula_resolution", profile["id"])
        for _, profile, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.resolution_profiles"
        )
        if profile.get("default") is True
    ]


def _source_formula_requests_at(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
    source: Mapping[str, Any],
    root: str,
) -> dict[str, dict[str, Any]]:
    """Resolve Formula requests from one Source's semantic projection."""
    projection = _consumer_b_project_source(
        dict(source), kernel, _attached_language(kernel, graph)
    )
    projected_source = projection.value
    requests = {}
    modules = _source_value_at(
        projection.authored_source, projection.authored_paths["/modules"]
    )
    for mi, module in enumerate(projected_source["modules"]):
        mp = f"/modules/{mi}"
        for fi, formula in enumerate(module.get("formulas", [])):
            if "expression" not in formula:
                continue
            fp = f"{mp}/formulas/{fi}"
            requests[root + projection.authored_paths[fp + "/expression"]] = {
                "schema_version": projected_source["schema_version"],
                "package_requirements": projected_source["package_requirements"],
                "module": _source_value_at(
                    projection.authored_source, projection.authored_paths[mp]
                ),
                "modules": modules,
                "formula": _source_value_at(
                    projection.authored_source, projection.authored_paths[fp]
                ),
            }
    return requests


def source_formula_requests(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    source = graph.get("source")
    if isinstance(source, Mapping):
        requests.update(_source_formula_requests_at(kernel, graph, source, "/source"))
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            fixture = vector.get("source_fixture")
            expected = vector.get("expect")
            if (
                not isinstance(expected, Mapping)
                or expected.get("outcome") != "admitted"
                or not isinstance(fixture, Mapping)
                or fixture.get("mode") != "literal"
                or not isinstance(fixture.get("source"), Mapping)
            ):
                continue
            root = f"/vector_sets/{vi}/vector_definitions/{di}/source_fixture/source"
            requests.update(
                _source_formula_requests_at(kernel, graph, fixture["source"], root)
            )
    return requests


def _formula_projections(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
) -> dict[str, Any]:
    from schema2_formula_conformance_support import (
        parse_canonical,
        render_body,
        render_semantic_body,
    )

    language = _attached_language(kernel, graph)
    projections = {}
    for pointer, request in source_formula_requests(kernel, graph).items():
        formula = request["formula"]
        projected = _consumer_b_project_source_role(
            formula, "formula", kernel, language
        )
        expression = projected.value["expression"]
        try:
            parsed = parse_canonical(expression, request, language, kernel=dict(kernel))
            if (
                render_body(
                    _source_value_at(
                        formula,
                        projected.authored_paths["/body"],
                    ),
                    request,
                    language,
                    kernel=dict(kernel),
                )
                != expression
            ):
                raise InventoryRefusal("Formula body and expression disagree")
            if (
                render_semantic_body(parsed, request, language, kernel=dict(kernel))
                != expression
            ):
                raise InventoryRefusal("Formula expression is not canonical")
        except (KeyError, TypeError, ValueError) as error:
            if pointer.startswith("/vector_sets/"):
                vector = _pointer_value(graph, "/".join(pointer.split("/")[:5]))
                if vector["expect"]["outcome"] == "refused":
                    # No AST is published when this negative input cannot be
                    # parsed and rendered. Model coverage verifies its first fault.
                    continue
            raise InventoryRefusal(
                "Formula expression does not close independently"
            ) from error
        projections[pointer] = parsed
    return projections


def _walk_member_path(value: Any, pointer: str, members: Sequence[str]):
    """Follow the Kernel path language, retaining each authored array position."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk_member_path(item, _child(pointer, i), members)
    elif not members:
        yield value, pointer
    elif isinstance(value, dict) and members[0] in value:
        yield from _walk_member_path(
            value[members[0]], _child(pointer, members[0]), members[1:]
        )


def _authority_path_rows(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], path: str
):
    if path.startswith("kernel."):
        yield from (
            (None, value, pointer)
            for value, pointer in _walk_member_path(kernel, "", path.split(".")[1:])
        )
        return
    if not path.startswith("language_bundle."):
        raise InventoryRefusal("unknown authority path root")
    tail = path.removeprefix("language_bundle.")
    if tail == "language.packages" or tail.startswith("language.packages."):
        suffix = (
            tail.removeprefix("language.packages").lstrip(".").split(".")
            if tail != "language.packages"
            else []
        )
        for pi, package in enumerate(graph["packages"]):
            yield from (
                (package["id"], value, pointer)
                for value, pointer in _walk_member_path(
                    package, f"/packages/{pi}", suffix
                )
            )
        return
    if tail == "vectors" or tail.startswith("vectors."):
        suffix = (
            tail.removeprefix("vectors").lstrip(".").split(".")
            if tail != "vectors"
            else []
        )
        for vi, vector_set in enumerate(graph.get("vector_sets", [])):
            yield from (
                (vector_set["package_id"], value, pointer)
                for value, pointer in _walk_member_path(
                    vector_set["vector_definitions"],
                    f"/vector_sets/{vi}/vector_definitions",
                    suffix,
                )
            )
        return
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    matching = [
        row
        for row in projections
        if tail == row["authority_path"] or tail.startswith(row["authority_path"] + ".")
    ]
    if len(matching) != 1:
        raise InventoryRefusal("authority path has no unique authored projection")
    role = matching[0]["authority_path"]
    suffix = tail.removeprefix(role).lstrip(".").split(".") if tail != role else []
    for pi, package in enumerate(graph["packages"]):
        for ci, closure in enumerate(package["semantic_closure"]):
            if closure["authority_path"] == role:
                yield from (
                    (package["id"], value, pointer)
                    for value, pointer in _walk_member_path(
                        closure["definitions"],
                        f"/packages/{pi}/semantic_closure/{ci}/definitions",
                        suffix,
                    )
                )


def _declared_target_role(kernel: Mapping[str, Any], path: str) -> tuple[str, bool]:
    if path.startswith("kernel."):
        return path, False
    if path == "language_bundle.language.packages.id":
        return "namespace", False
    if path == "language_bundle.language.packages.exports.types.id":
        return "type", True
    if path == "language_bundle.vectors.id":
        return "vectors", False
    scoped = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.identifiers.unique"
    )["arguments"]["collections"]
    for projection in kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]:
        role = projection["authority_path"]
        target = (
            "language_bundle."
            + role
            + ("." + projection["key_member"] if projection["key_member"] else "")
        )
        if path == target:
            if role == "language.nominal_types":
                return "type", True
            return role, any(
                row["path"] == "language_bundle." + role
                and row.get("scope") == "package"
                for row in scoped
            )
    raise InventoryRefusal("reference target is not an authored identity inventory")


def _declared_metadata_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Interpret existing reference and equality laws, without scanning spellings."""
    li, law = next(
        (i, row)
        for i, row in enumerate(kernel["admission"]["laws"])
        if row["id"] == "kernel.vectors.closed"
    )
    arguments = law["arguments"]
    for ri, reference in enumerate(arguments["references"]):
        for owner, value, pointer in _authority_path_rows(
            kernel, graph, reference["owners"]
        ):
            for member_path, target in reference["targets"].items():
                for name, occurrence in _walk_member_path(
                    value, pointer, member_path.split(".")
                ):
                    yield (
                        owner,
                        name,
                        occurrence,
                        target,
                        f"/admission/laws/{li}/arguments/references/{ri}",
                    )
    for ei, equality in enumerate(arguments["equalities"]):
        target = equality["left"]
        if "right" in equality:
            selected = _authority_path_rows(kernel, graph, equality["right"])
        else:
            items = _consumer_b_source_equality_items(
                {
                    "kernel": dict(kernel),
                    "language_bundle": _attached_language(kernel, graph),
                },
                equality,
            )
            if items is None:
                raise InventoryRefusal(
                    "Source equality has no resolved semantic address"
                )
            schemas = list(
                _authority_path_rows(
                    kernel, graph, "language_bundle.language.wire_schemas"
                )
            )
            selected = []
            for path, value in items:
                if path[:3] != (
                    "language_bundle",
                    "language",
                    "wire_schemas",
                ) or not isinstance(path[3], int):
                    raise InventoryRefusal(
                        "Source equality does not address its Schema owner"
                    )
                owner, _, pointer = schemas[path[3]]
                for segment in path[4:]:
                    pointer = _child(pointer, segment)
                selected.append((owner, value, pointer))
        for owner, name, pointer in selected:
            yield (
                owner,
                name,
                pointer,
                target,
                f"/admission/laws/{li}/arguments/equalities/{ei}",
            )


def _replay_vector_rows(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    contract = kernel["meta_format"]["package_vector"]
    kind = next(row for row in contract["kinds"] if row["id"] == "replay-comparison")
    packages = {row["id"]: row for row in graph["packages"]}
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            if vector.get("kind") != kind["id"]:
                continue
            if (
                set(vector) != set(kind["required_members"])
                or vector["category"] not in contract["categories"]
                or not _consumer_b_replay_comparison_vector_is_closed(
                    packages[vector_set["package_id"]], vector, kind
                )
            ):
                raise InventoryRefusal(
                    "Replay vector does not close its actual comparison"
                )
            yield vector, f"/vector_sets/{vi}/vector_definitions/{di}"


def _replay_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    kinds = kernel["meta_format"]["package_vector"]["kinds"]
    selected = [
        (i, row) for i, row in enumerate(kinds) if row["id"] == "replay-comparison"
    ]
    if len(selected) != 1:
        raise InventoryRefusal("Replay policy has no unique Kernel observation")
    index, kind = selected[0]
    members = kind["observation_members"]
    contract = kernel["meta_format"]["language_definitions"]["collections"][
        "replay_comparison_policies"
    ]
    language = _attached_language(kernel, graph)
    for _, policy, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.replay_comparison_policies"
    ):
        if (
            not _consumer_b_definition_is_closed(policy, contract, language)
            or policy["checks"] != members
        ):
            raise InventoryRefusal(
                "Replay policy does not close its Kernel observation"
            )
        for i, member in enumerate(members):
            yield TokenOccurrence(
                AuthorityToken("kernel.replay-observation-member", (), member),
                f"{pointer}/checks/{i}",
                "reference",
                f"/meta_format/package_vector/kinds/{index}/observation_members/{i}",
            )

    for vector, pointer in _replay_vector_rows(kernel, graph):
        yield TokenOccurrence(
            AuthorityToken("language.replay_comparison_policies", (), vector["policy"]),
            pointer + "/policy",
            "reference",
            f"/meta_format/package_vector/kinds/{index}",
        )
        for i, member in enumerate(members):
            token = AuthorityToken("kernel.replay-observation-member", (), member)
            law = f"/meta_format/package_vector/kinds/{index}/observation_members/{i}"
            for side in kind["input_members"]:
                yield TokenOccurrence(
                    token,
                    _child(f"{pointer}/input/{side}", member),
                    "reference",
                    law,
                    location="key",
                )
            yield TokenOccurrence(
                token, f"{pointer}/expect/checks/{i}/key", "reference", law
            )


def _experiment_judgment_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Discriminator labels belong to their actual Kernel selector field path."""
    collections = kernel["meta_format"]["language_definitions"]["collections"]
    for name in ("experiment_metric_judgments", "experiment_acceptance_judgments"):
        contract = collections[name]
        law = "/meta_format/language_definitions/collections/" + name
        for _, definition, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language." + name
        ):
            if not _consumer_b_definition_is_closed(definition, contract, {}):
                raise InventoryRefusal(
                    "Experiment judgment does not close its record owner"
                )
            if name != "experiment_metric_judgments":
                continue

            def labels(value, shape, owner, position, field_law):
                if shape.get("type") == "non-empty-string":
                    yield TokenOccurrence(
                        AuthorityToken("experiment-metric-label", owner, value),
                        position,
                        "declaration",
                        field_law,
                    )
                elif shape.get("type") == "closed-object":
                    for member, child in shape["field_types"].items():
                        yield from labels(
                            value[member],
                            child,
                            (*owner, member),
                            _child(position, member),
                            _child(field_law + "/field_types", member),
                        )
                else:
                    raise InventoryRefusal("Metric discriminator has an unowned type")

            yield from labels(
                definition["selector"],
                contract["field_types"]["selector"],
                (),
                pointer + "/selector",
                law + "/field_types/selector",
            )


def _experiment_input_judgment_links(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
):
    experiment = graph.get("experiment")
    if experiment is None:
        return
    judgments = [
        definition
        for _, definition, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language.experiment_metric_judgments"
        )
    ]
    paths = (
        ("kind",),
        ("aggregation",),
        ("missing",),
        ("censoring",),
        ("replication", "unit"),
        ("window", "kind"),
        ("observation", "source"),
    )
    law = "/meta_format/language_definitions/wire_schema_protocol_roles/experiment_input_structure"
    for index, metric in enumerate(experiment["metrics"]):
        matches = [
            judgment
            for judgment in judgments
            if all(
                _at(judgment["selector"], path) == _at(metric, path) for path in paths
            )
        ]
        if len(matches) != 1:
            raise InventoryRefusal(
                "Experiment Metric selector has no unique judgment owner"
            )
        for path in paths:
            pointer = f"/experiment/metrics/{index}" + "".join(
                "/" + member for member in path
            )
            yield TokenOccurrence(
                AuthorityToken("experiment-metric-label", path, _at(metric, path)),
                pointer,
                "reference",
                law,
            )


def _resolved_judgment_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    results = graph.get("results")
    if not isinstance(results, dict):
        return ()
    profile_kind = _artifact_protocol_binding(
        kernel, graph, "resolved-runtime-profile"
    )[0]
    profiles = [
        (label, value)
        for label, value in results.items()
        if isinstance(value, dict) and value.get("artifact_kind") == profile_kind
    ]
    if len(profiles) != 1:
        raise InventoryRefusal("Runtime results have no unique resolved profile")
    label, profile = profiles[0]
    definitions = [
        (definition, pointer)
        for _, definition, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.experiment_metric_judgments"
        )
    ]
    projections: list[tuple[str, str]] = []
    root = _child("/results", label) + "/experiment_judgments/metrics"
    for index, row in enumerate(profile["experiment_judgments"]["metrics"]):
        matches = [
            pointer
            for definition, pointer in definitions
            if _consumer_b_canonical_equal(definition, row["judgment"])
        ]
        if len(matches) != 1:
            raise InventoryRefusal("resolved Metric judgment has no unique owner")
        projections.append((matches[0], f"{root}/{index}/judgment"))
    return _close_projection_occurrences(
        graph, tuple(_experiment_judgment_links(kernel, graph)), projections
    )


def _runtime_metric_selector_links(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> set[TokenOccurrence]:
    """Derive Runtime selector echoes from the authored Experiment Metric."""
    results = graph.get("results")
    experiment = graph.get("experiment")
    if not isinstance(results, dict) or not isinstance(experiment, dict):
        return set()
    metrics = {row["id"]: row for row in experiment["metrics"]}
    protocol_law = "/meta_format/language_definitions/wire_schema_protocol_roles"

    def member(role: str) -> tuple[dict[str, Any], str]:
        kind = _artifact_protocol_binding(kernel, graph, role)[0]
        rows = [
            (value, _child("/results", label))
            for label, value in results.items()
            if isinstance(value, dict) and value.get("artifact_kind") == kind
        ]
        if len(rows) != 1:
            raise InventoryRefusal(f"Runtime selector {role} member is ambiguous")
        return rows[0]

    expected: set[TokenOccurrence] = set()

    def add(
        metric: str, path: tuple[str, ...], value: str, pointer: str, law: str
    ) -> None:
        definition = metrics.get(metric)
        if definition is None or _at(definition, path) != value:
            raise InventoryRefusal("Runtime selector has no Experiment Metric owner")
        expected.add(
            TokenOccurrence(
                AuthorityToken("experiment-metric-label", path, value),
                pointer,
                "reference",
                law,
            )
        )

    trace, pointer = member("event-trace")
    for index, event in enumerate(trace["events"]):
        observation = event.get("observation")
        if observation is not None:
            add(
                observation["metric"],
                ("window", "kind"),
                observation["window"]["kind"],
                f"{pointer}/events/{index}/observation/window/kind",
                protocol_law + "/trace_structure",
            )
    dataset, pointer = member("metric-dataset")
    for index, sample in enumerate(dataset["samples"]):
        root = f"{pointer}/samples/{index}"
        add(
            sample["metric"],
            ("observation", "source"),
            sample["source"],
            root + "/source",
            protocol_law + "/metric_outcome_structure",
        )
        add(
            sample["metric"],
            ("observation", "source"),
            sample["provenance"]["observation_source"],
            root + "/provenance/observation_source",
            protocol_law + "/metric_outcome_structure",
        )
    return expected


def _evidence_claim_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Interpret the existing claim-local labels and closed eligibility grammar."""
    law = "/meta_format/language_definitions/collections/evidence_claim_kinds"
    contract = kernel["meta_format"]["language_definitions"]["collections"][
        "evidence_claim_kinds"
    ]
    language = _attached_language(kernel, graph)
    if not _consumer_b_evidence_claim_kinds_are_closed(language):
        raise InventoryRefusal("Evidence claim eligibility vectors do not close")
    vector_contract = contract["field_types"]["vectors"]["items"]
    input_contract = vector_contract["field_types"]["input"]

    def marker(value, field, pointer, field_law):
        if not (
            ("const" in field and _consumer_b_canonical_equal(value, field["const"]))
            or ("enum" in field and value in field["enum"])
        ):
            raise InventoryRefusal("Evidence marker has no actual Kernel enum or const")
        return TokenOccurrence(
            AuthorityToken("kernel.evidence-value", (field_law,), value),
            pointer,
            "reference",
            field_law,
        )

    for _, claim, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.evidence_claim_kinds"
    ):
        if set(claim) != {"id", "eligibility", "vectors"} or not (
            _consumer_b_definition_is_closed(claim, contract, language)
        ):
            raise InventoryRefusal("Evidence claim has unclassified members")
        for member, value in claim["eligibility"].items():
            if member == "producing_outcomes":
                field = input_contract["field_types"]["producing_outcome"]
                field_law = (
                    law
                    + "/field_types/vectors/items/field_types/input/field_types/producing_outcome"
                )
                for i, outcome in enumerate(value):
                    yield marker(
                        outcome, field, f"{pointer}/eligibility/{member}/{i}", field_law
                    )
            else:
                field = contract["field_types"]["eligibility"]["field_types"][member]
                yield marker(
                    value,
                    field,
                    f"{pointer}/eligibility/{member}",
                    f"{law}/field_types/eligibility/field_types/{member}",
                )
        for i, vector in enumerate(claim["vectors"]):
            vp = f"{pointer}/vectors/{i}"
            yield TokenOccurrence(
                AuthorityToken("claim-vector", (claim["id"],), vector["id"]),
                vp + "/id",
                "declaration",
                law + "/field_types/vectors/items/field_types/id",
            )
            for member in ("kind", "expect"):
                yield marker(
                    vector[member],
                    vector_contract["field_types"][member],
                    f"{vp}/{member}",
                    f"{law}/field_types/vectors/items/field_types/{member}",
                )
            for member, value in vector["input"].items():
                yield marker(
                    value,
                    input_contract["field_types"][member],
                    f"{vp}/input/{member}",
                    f"{law}/field_types/vectors/items/field_types/input/field_types/{member}",
                )


def _source_format_role(kernel: Mapping[str, Any], graph: Mapping[str, Any]) -> str:
    """Keep Source protocol format parameters distinct from nominal identities."""
    role = "language.model_source_schema_versions"
    left = "language_bundle." + role
    law = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.vectors.closed"
    )
    equalities = [
        row for row in law["arguments"]["equalities"] if row.get("left") == left
    ]
    if len(equalities) != 1:
        raise InventoryRefusal("Source format parameter has no unique wire equality")
    selected = _consumer_b_source_equality_values(
        {"kernel": dict(kernel), "language_bundle": _attached_language(kernel, graph)},
        equalities[0],
    )
    if selected is None:
        raise InventoryRefusal("Source format parameter has no resolved wire equality")
    actual = {value for _, value, _ in _authority_path_rows(kernel, graph, left)}
    source = _protocol_schema(kernel, graph, "model-source-package")
    version_fields = [
        child
        for child in source["schema"]["properties"].values()
        if child.get("semantic_member") == "schema_version"
    ]
    if len(version_fields) != 1:
        raise InventoryRefusal("Source format role is ambiguous")
    expected = {version_fields[0]["const"]}
    if set(selected) != expected:
        raise InventoryRefusal(
            "Source format equality does not select its actual field"
        )
    if actual != expected:
        raise InventoryRefusal(
            "Source format parameter does not match its wire contract"
        )
    return role


def _protocol_schema(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], role: str
) -> dict[str, Any]:
    declared = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]
    if role not in declared["identified_artifacts"] + declared["standalone_inputs"]:
        raise InventoryRefusal("wire protocol role is not declared by the Kernel")
    matches = [
        row
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language." + collection
        )
        if row.get("protocol_role") == role
    ]
    if len(matches) != 1:
        raise InventoryRefusal("wire protocol role has no unique schema owner")
    return matches[0]


def _artifact_protocol_binding(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], role: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Resolve one Kernel protocol role through its Schema to its producer kind."""
    schema = _protocol_schema(kernel, graph, role)
    schema_kind = schema["artifact_kind"]
    matches = [
        row
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language.artifact_contracts"
        )
        if row["schema_kind"] == schema_kind
    ]
    if len(matches) != 1:
        raise InventoryRefusal("artifact protocol role has no unique producer binding")
    contract = matches[0]
    effective = schema
    if "schema" not in effective:
        language = _attached_language(kernel, graph)["language"]
        projected = [
            row
            for row in language["artifact_wire_schemas"]
            if row["artifact_kind"] == schema_kind
        ]
        if len(projected) != 1 or "schema" not in projected[0]:
            raise InventoryRefusal(
                "artifact protocol role has no unique projected Schema"
            )
        effective = projected[0]
    return contract["artifact_kind"], effective["schema"], contract


def _wire_protocol_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Resolve the declared schema/producer join without equating their names."""
    meta = kernel["meta_format"]["language_definitions"]
    language = _attached_language(kernel, graph)
    schemas = {}
    roles = set()
    role_law = "/meta_format/language_definitions/wire_schema_protocol_roles"
    for collection in ("wire_schemas", "artifact_wire_schemas"):
        role = "language." + collection
        contract = meta["collections"][collection]
        for _, row, pointer in _authority_path_rows(
            kernel, graph, "language_bundle." + role
        ):
            if not _consumer_b_definition_is_closed(row, contract, language):
                raise InventoryRefusal("wire schema does not close its Kernel shape")
            name = row["artifact_kind"]
            if name in schemas:
                raise InventoryRefusal("wire schema identity is not unique")
            schemas[name] = (row, pointer, AuthorityToken(role, (), name))
            if "protocol_role" in row:
                protocol = row["protocol_role"]
                group = (
                    "standalone_inputs"
                    if "wire_schema_identity_domain" in row
                    else "identified_artifacts"
                )
                if (
                    protocol not in meta["wire_schema_protocol_roles"][group]
                    or protocol in roles
                ):
                    raise InventoryRefusal(
                        "wire protocol role has an invalid or duplicate owner"
                    )
                roles.add(protocol)
                yield (
                    AuthorityToken(
                        "kernel.meta_format.language_definitions.wire_schema_protocol_roles",
                        (),
                        protocol,
                    ),
                    pointer + "/protocol_role",
                    "reference",
                    role_law,
                )
    if roles != set(
        meta["wire_schema_protocol_roles"]["identified_artifacts"]
        + meta["wire_schema_protocol_roles"]["standalone_inputs"]
    ):
        raise InventoryRefusal("wire protocol role ownership is incomplete")
    producers = {}
    assigned = set()
    law = "/meta_format/language_definitions/collections/artifact_contracts"
    for _, row, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.artifact_contracts"
    ):
        if not _consumer_b_definition_is_closed(
            row, meta["collections"]["artifact_contracts"], language
        ):
            raise InventoryRefusal("artifact contract does not close its Kernel shape")
        name, schema_name = row["artifact_kind"], row["schema_kind"]
        if name in producers or schema_name in assigned or schema_name not in schemas:
            raise InventoryRefusal("artifact contract has no unique schema binding")
        schema, sp, token = schemas[schema_name]
        if "wire_schema_identity_domain" in schema:
            raise InventoryRefusal("wire schema has two identity-domain owners")
        assigned.add(schema_name)
        producer = AuthorityToken("language.artifact_contracts", (), name)
        producers[name] = producer
        yield token, pointer + "/schema_kind", "reference", law
        effective_schema = schema
        if "schema" not in schema:
            effective_schema = next(
                item
                for item in language["language"]["artifact_wire_schemas"]
                if item["artifact_kind"] == schema_name
            )
        identity_kind = (
            effective_schema["schema"].get("properties", {}).get("artifact_kind", {})
        )
        if identity_kind.get("const") != name:
            raise InventoryRefusal(
                "identified wire schema does not bind its producer kind"
            )
        if "schema" in schema:
            yield (
                producer,
                sp + "/schema/properties/artifact_kind/const",
                "reference",
                law,
            )
    standalone = {
        name: token
        for name, (row, _, token) in schemas.items()
        if "wire_schema_identity_domain" in row
    }
    if assigned | set(standalone) != set(schemas) or set(standalone) & set(producers):
        raise InventoryRefusal("wire schema identity ownership is not closed")
    kinds = standalone | producers
    for _, profile, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.template_admission_profiles"
    ):
        for i, row in enumerate(profile["member_roles"]):
            if row["member_kind"] not in kinds:
                raise InventoryRefusal(
                    "Template member kind has no declared identity owner"
                )
            yield (
                kinds[row["member_kind"]],
                f"{pointer}/member_roles/{i}/member_kind",
                "reference",
                "/meta_format/template_admission",
            )


def _source_address_links(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
):
    """Join actual Schema annotations and typed recipe/check addresses."""
    source = _protocol_schema(kernel, graph, "model-source-package")
    schema_rows = [
        (role, row, pointer)
        for role in ("language.wire_schemas", "language.artifact_wire_schemas")
        for _, row, pointer in _authority_path_rows(
            kernel, graph, "language_bundle." + role
        )
        if row.get("protocol_role") == "model-source-package"
    ]
    if len(schema_rows) != 1:
        raise InventoryRefusal("Source address has no unique schema owner")
    schema_role, _, schema_pointer = schema_rows[0]
    language = _attached_language(kernel, graph)
    law = "/meta_format/resolution_judgment/relation_recipe_format"
    if not _consumer_b_formula_resolution_is_closed(language, kernel["meta_format"]):
        raise InventoryRefusal("Formula Source selectors do not close their Schema")

    def pointer(root: str, path: Sequence[str | int]) -> str:
        for member in path:
            root = _child(root, member)
        return root

    def token(address: tuple[str | int, ...]) -> AuthorityToken:
        if len(address) < 2 or address[-2] != "properties":
            raise InventoryRefusal("typed selector did not select an object member")
        owner: tuple[str, ...] = (schema_role, source["artifact_kind"])
        index = 0
        while index < len(address) - 2:
            member = address[index + 1]
            if address[index] == "properties" and isinstance(member, str):
                owner = (*owner, "member", member)
                index += 2
            elif address[index] == "items":
                owner = (*owner, "items")
                index += 1
            else:
                raise InventoryRefusal(
                    "typed selector address has an unknown structural step"
                )
        name = address[-1]
        if not isinstance(name, str):
            raise InventoryRefusal("typed selector member name is not a string")
        return AuthorityToken("source-field", owner, name)

    def source_keys(value: Any, address: Sequence[str | int], path: str):
        if address[0] == "properties":
            member = address[1]
            if not isinstance(value, dict) or member not in value:
                return
            selected = _child(path, member)
            if len(address) == 2:
                yield selected
            else:
                yield from source_keys(value[member], address[2:], selected)
        elif address[0] == "items" and isinstance(value, list):
            for i, item in enumerate(value):
                yield from source_keys(item, address[1:], _child(path, i))

    def address_schemas(address: tuple[str | int, ...]):
        selected = [(source["schema"], ())]
        index = 0
        while index < len(address):
            step = address[index]
            if step == "properties":
                member = address[index + 1]
                selected = [
                    (schema["properties"][member], (*path, "properties", member))
                    for value, parent in selected
                    for schema, path in _same_instance_schemas(value, parent)
                    if member in schema.get("properties", {})
                ]
                index += 2
            elif step == "items":
                selected = [
                    (schema["items"], (*path, "items"))
                    for value, parent in selected
                    for schema, path in _same_instance_schemas(value, parent)
                    if isinstance(schema.get("items"), dict)
                ]
                index += 1
            else:
                raise InventoryRefusal(
                    "Source schema address has an unknown structural step"
                )
        return [
            (schema, path)
            for value, parent in selected
            for schema, path in _same_instance_schemas(value, parent)
        ]

    def schema_links(address: tuple[str | int, ...], selected_law: str):
        selected = token(address)
        for value, path in address_schemas(address[:-2]):
            if selected.name in value.get("properties", {}):
                yield (
                    selected,
                    pointer(
                        schema_pointer + "/schema", (*path, "properties", selected.name)
                    ),
                    "declaration",
                    "key",
                    "",
                    selected_law,
                )
            for index, member in enumerate(value.get("required", [])):
                if member == selected.name:
                    yield (
                        selected,
                        pointer(schema_pointer + "/schema", (*path, "required", index)),
                        "reference",
                        "value",
                        "",
                        selected_law,
                    )
        if graph.get("source"):
            for path in source_keys(graph["source"], address, "/source"):
                yield selected, path, "reference", "key", "", selected_law

    transport_law = "/meta_format/language_definitions/collections/model_lowerings/source_fact_transport"
    transport = kernel["meta_format"]["language_definitions"]["collections"][
        "model_lowerings"
    ].get("source_fact_transport")
    if not _consumer_b_source_fact_transport_is_supported(transport):
        raise InventoryRefusal("Source address transport law is unsupported")
    if not _consumer_b_source_roles_are_closed(language, kernel["meta_format"]):
        raise InventoryRefusal("Source semantic roles do not close")

    for _, profile, _ in _authority_path_rows(
        kernel, graph, "language_bundle.language.resolution_profiles"
    ):
        addresses: dict[tuple[str | int, ...], tuple[str | int, ...]] = {}
        if not _consumer_b_relation_paths_are_typed(
            profile,
            language,
            kernel["meta_format"]["package_release"],
            kernel["meta_format"],
            schema_addresses=addresses,
        ):
            raise InventoryRefusal("Source schema-address judgement did not close")
        for address in addresses.values():
            yield from schema_links(address, law)
        # Membership and contextual anchors are independently checked by B. The
        # annotation query supplies actual paths, not a second selector grammar.
        roles = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["source_notation"]["semantic_roles"]["roles"]
        annotated_addresses = set()
        for role, contract in roles.items():
            for member in contract["members"]:
                for members in _consumer_b_source_role_member_paths(
                    source["schema"], role, member
                ):
                    candidates = {()}
                    for part in members:
                        following = set()
                        for address in candidates:
                            current = address_schemas(address)
                            for schema, _ in current:
                                if part in schema.get("properties", {}):
                                    following.add((*address, "properties", part))
                                if isinstance(schema.get("items"), dict):
                                    if any(
                                        part in item.get("properties", {})
                                        for item, _ in address_schemas(
                                            (*address, "items")
                                        )
                                    ):
                                        following.add(
                                            (*address, "items", "properties", part)
                                        )
                        candidates = following
                    if not candidates:
                        raise InventoryRefusal(
                            "Source semantic member has no Schema address"
                        )
                    annotated_addresses.update(candidates)
        for address in annotated_addresses:
            yield from schema_links(address, transport_law)


def _scheduler_rule_vector_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> tuple[set[TokenOccurrence], set[str]]:
    """Interpret only scheduler identities and selected rule Fact contracts.

    Admission of these shapes does not execute their numeric oracles. The
    maintenance harness still checks scheduler observations and rule results.
    """
    meta = kernel["meta_format"]
    language = _attached_language(kernel, graph)
    rules = {row["id"]: row for row in language["language"]["rules"]}
    facts = {
        row["kind"]: meta["fact"]["field_contracts"][row["field_contract"]]
        for row in meta["fact"]["schemas"]
    }
    scheduler = meta["runtime_program"]["scheduler"]
    phases = set(
        next(row["rank"] for row in scheduler["ordering"] if row["member"] == "phase")
    )
    scheduler_kind = next(
        row
        for row in meta["package_vector"]["kinds"]
        if row["id"] == "scheduler-scenario"
    )
    rows: set[TokenOccurrence] = set()
    roots: set[str] = set()

    def emit(role, scope, value, pointer, use, law):
        rows.add(TokenOccurrence(AuthorityToken(role, scope, value), pointer, use, law))

    def fact_fields(value, contracts, pointer):
        # The actual Fact contract supplies each address and reference role.
        # Canonical data and nonempty-string coordinates are deliberately opaque.
        for field, contract in contracts.items():
            fp = _child(pointer, field)
            kind = contract.get("type")
            if kind == "inventory-member":
                role, scoped = _declared_target_role(
                    kernel, "language_bundle." + contract["path"]
                )
                if scoped:
                    raise InventoryRefusal(
                        "rule Fact has an unqualified scoped reference"
                    )
                emit(role, (), value[field], fp, "reference", "/meta_format/fact")
            elif kind == "closed-object":
                fact_fields(value[field], contract["field_types"], fp)
            elif (
                kind
                not in {"non-empty-string", "canonical-value", "closed-int64-interval"}
                and "const" not in contract
                and "enum" not in contract
            ):
                raise InventoryRefusal("rule Fact field has no interpreted role")

    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            pointer = f"/vector_sets/{vi}/vector_definitions/{di}"
            if vector.get("kind") == "scheduler-scenario":
                law = "/meta_format/package_vector/kinds/" + str(
                    meta["package_vector"]["kinds"].index(scheduler_kind)
                )
                if not _consumer_b_package_evidence_vector_header_is_closed(
                    vector, meta["package_vector"]
                ) or not _consumer_b_scheduler_scenario_vector_is_closed(
                    vector, scheduler_kind, phases
                ):
                    raise InventoryRefusal(
                        "scheduler vector does not close its declared shape"
                    )
                scope = (vector["id"],)
                inp, expect = vector["input"], vector["expect"]
                for i, state in enumerate(inp["initial_states"]):
                    emit(
                        "scheduler-scenario",
                        scope,
                        state["scenario"],
                        f"{pointer}/input/initial_states/{i}/scenario",
                        "declaration",
                        law,
                    )
                for i, event in enumerate(inp["events"]):
                    ep = f"{pointer}/input/events/{i}"
                    emit(
                        "scheduler-event",
                        scope,
                        event["id"],
                        ep + "/id",
                        "declaration",
                        law,
                    )
                    emit(
                        "scheduler-scenario",
                        scope,
                        event["scenario"],
                        ep + "/scenario",
                        "reference",
                        law,
                    )
                    if event["parent_id"] is not None:
                        emit(
                            "scheduler-event",
                            scope,
                            event["parent_id"],
                            ep + "/parent_id",
                            "reference",
                            law,
                        )
                for i, event in enumerate(expect["event_order"]):
                    emit(
                        "scheduler-event",
                        scope,
                        event,
                        f"{pointer}/expect/event_order/{i}",
                        "reference",
                        law,
                    )
                for i, observation in enumerate(expect["observations"]):
                    op = f"{pointer}/expect/observations/{i}"
                    emit(
                        "scheduler-event",
                        scope,
                        observation["event_id"],
                        op + "/event_id",
                        "reference",
                        law,
                    )
                    emit(
                        "scheduler-scenario",
                        scope,
                        observation["scenario"],
                        op + "/scenario",
                        "reference",
                        law,
                    )
                for i, state in enumerate(expect["terminal_states"]):
                    emit(
                        "scheduler-scenario",
                        scope,
                        state["scenario"],
                        f"{pointer}/expect/terminal_states/{i}/scenario",
                        "reference",
                        law,
                    )
            elif "rule" in vector:
                if not _consumer_b_vector_header_is_closed(vector, meta, language):
                    raise InventoryRefusal(
                        "rule vector does not close its declared Fact shape"
                    )
                invocation = vector["input"]
                matches = [
                    rule
                    for rule in rules.values()
                    if rule["phase"] == invocation["phase"]
                    and rule["judgment"] == invocation["judgment"]
                    and [row["fact_kind"] for row in rule["premises"]]
                    == [fact["kind"] for fact in invocation["facts"]]
                ]
                if (
                    len(matches) != 1
                    or matches[0]["id"] != vector["rule"]
                    or matches[0]["conclusion"]["fact_kind"] != vector["expect"]["kind"]
                ):
                    raise InventoryRefusal(
                        "rule vector does not select its declared rule"
                    )
                emit(
                    "language.rules",
                    (),
                    vector["rule"],
                    pointer + "/rule",
                    "reference",
                    "/meta_format/rule_selection",
                )
                emit(
                    "rule-judgment",
                    (),
                    invocation["judgment"],
                    pointer + "/input/judgment",
                    "reference",
                    "/meta_format/rule_selection",
                )
                for i, fact in enumerate(invocation["facts"]):
                    fact_fields(
                        fact["fields"],
                        facts[fact["kind"]],
                        f"{pointer}/input/facts/{i}/fields",
                    )
                fact = vector["expect"]
                fact_fields(
                    fact["fields"], facts[fact["kind"]], pointer + "/expect/fields"
                )
            else:
                continue
            roots.add(pointer)
    return rows, roots


def _reason_vector_rows(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    contract = kernel["meta_format"]["diagnostic_reason"]
    reasons = {
        row["id"]: row
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language.reasons"
        )
    }
    language = _attached_language(kernel, graph)
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            if "reason" not in vector and "matched" not in vector:
                continue
            if (
                set(vector) != set(contract["vector_required_members"])
                or vector["reason"] not in reasons
            ):
                raise InventoryRefusal(
                    "reason vector does not close its declared shape"
                )
            reason = reasons[vector["reason"]]
            schemas = [
                row
                for row in contract["predicate_schemas"]
                if row["operation"] == reason["predicate"]["operation"]
            ]
            if len(schemas) != 1:
                raise InventoryRefusal("reason vector has no declared predicate")
            schema = schemas[0]
            fields = {
                **contract["vector_member_types"],
                "input": {
                    "type": "closed-object",
                    "required_members": schema["input_members"],
                    "field_types": schema["input_member_types"],
                },
            }
            if not _consumer_b_definition_is_closed(
                vector,
                {
                    "required_members": contract["vector_required_members"],
                    "field_types": fields,
                },
                language,
            ):
                raise InventoryRefusal(
                    "reason vector input does not close its predicate shape"
                )
            if (
                vector["diagnostic"] != reason["diagnostic"]
                or vector["stage"] != reason["stage"]
            ):
                raise InventoryRefusal("reason vector diagnostic ownership disagrees")
            yield vector, reason, f"/vector_sets/{vi}/vector_definitions/{di}"


def _reason_vector_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    law = "/meta_format/diagnostic_reason"
    for vector, reason, pointer in _reason_vector_rows(kernel, graph):
        yield (
            AuthorityToken("language.reasons", (), reason["id"]),
            pointer + "/reason",
            "reference",
            law,
        )
        yield (
            AuthorityToken("diagnostics", (), reason["diagnostic"]),
            pointer + "/diagnostic",
            "reference",
            law,
        )
        predicate = reason["predicate"]
        if predicate["operation"] != "not-member":
            # These other predicates compare canonical data or numeric bounds;
            # their payload spelling does not resolve an authority identifier.
            continue
        target = "language_bundle." + predicate["inventory_path"]
        if "member_field" in predicate:
            target += "." + predicate["member_field"]
        role, scoped = _declared_target_role(kernel, target)
        if scoped:
            raise InventoryRefusal("lookup target has no unambiguous semantic owner")
        members = [value for _, value, _ in _authority_path_rows(kernel, graph, target)]
        value = vector["input"]["value"]
        absent = not any(
            _consumer_b_canonical_equal(value, member) for member in members
        )
        if vector["matched"] != absent:
            raise InventoryRefusal(
                "reason vector lookup absence disagrees with its expected outcome"
            )
        if not isinstance(value, str) or not value:
            continue
        yield (
            AuthorityToken(role, (), value),
            pointer + "/input/value",
            "unresolved-reference" if absent else "reference",
            law,
        )


def _constructor_member_selectors(constructor: Mapping[str, Any]):
    for selector, name in constructor["value_rule"].items():
        if selector.endswith("_member"):
            area = (
                "record-field"
                if selector in {"field_name_member", "field_type_member"}
                else "definition"
            )
            yield selector, name, area


def _projection_collection_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Interpret collection bindings in the declared Runtime projection DSL."""
    contract = kernel["meta_format"]["runtime_projection"]
    for _, lowering, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.model_lowerings"
    ):
        scope = (lowering["id"],)
        projection = lowering["runtime_projection"]
        pp = pointer + "/runtime_projection"
        names = [row["id"] for row in projection["collections"]]
        if len(names) != len(set(names)) or not all(
            isinstance(name, str) and name for name in names
        ):
            raise InventoryRefusal("projection collection declarations are not unique")
        for i, row in enumerate(projection["collections"]):
            required = set(contract["collection"]["required_members"])
            if set(row) != required:
                raise InventoryRefusal("projection collection has unknown members")
            yield (
                AuthorityToken("projection-collection", scope, row["id"]),
                f"{pp}/collections/{i}/id",
                "declaration",
                "/meta_format/runtime_projection/collection",
            )
        groups = (
            ("seeds", "seed", ("collection",)),
            ("edges", "edge", ("source_collection", "target_collection")),
            (
                "type_reference_closure",
                "type_reference_closure",
                (
                    "source_collection",
                    "target_type_collection",
                    "target_constructor_collection",
                ),
            ),
            ("operation_roots", "operation_roots", ("collection",)),
        )
        for member, grammar, references in groups:
            shape = contract[grammar]
            required = set(shape["required_members"])
            if not set(references) <= required:
                raise InventoryRefusal("projection collection role is not declared")
            value = projection[member]
            rows = enumerate(value) if isinstance(value, list) else ((None, value),)
            for i, row in rows:
                rp = pp + "/" + member + ("" if i is None else "/" + str(i))
                if (
                    not required
                    <= set(row)
                    <= required | set(shape.get("optional_members", []))
                ):
                    raise InventoryRefusal("projection clause has unknown members")
                for field in references:
                    if row[field] not in names:
                        raise InventoryRefusal(
                            "projection collection reference is unresolved"
                        )
                    yield (
                        AuthorityToken("projection-collection", scope, row[field]),
                        rp + "/" + field,
                        "reference",
                        "/meta_format/runtime_projection/" + grammar,
                    )


def _lowering_path_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Project addresses already interpreted by the independent lowering judgment.

    LDB identifiers are covered by metadata, rule, assignment and collection
    links. These additional occurrences address fixed Kernel contracts, not
    the values stored in the addressed fields.
    """
    meta = kernel["meta_format"]
    definitions = meta["language_definitions"]
    law = "/meta_format/language_definitions/collections/model_lowerings"
    grammar = definitions["collections"]["model_lowerings"]
    language = {**graph["ldb_root"], **_attached_language(kernel, graph)}
    rules = {row["id"]: row for row in language["language"]["rules"]}
    facts = {row["kind"]: row["field_contract"] for row in meta["fact"]["schemas"]}
    rir = next(
        row["schema"]
        for row in language["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == "rir-semantic-payload"
    )["properties"]["selected_semantics"]["properties"]

    def fixed(name, pointer, owner):
        return TokenOccurrence(
            AuthorityToken("kernel.lowering-address", (owner,), name),
            pointer,
            "reference",
            owner,
        )

    def path_links(path, pointer, contract, owner, *, schema=False):
        select = _consumer_b_schema_path if schema else _consumer_b_contract_path
        for i, name in enumerate(path):
            if select(contract, path[: i + 1]) is None:
                raise InventoryRefusal("lowering path has no declared field owner")
            yield fixed(name, f"{pointer}/{i}", owner + "/" + "/".join(path[:i]))

    def markers(value, contract, pointer, owner):
        # Only explicit enum/const declarations are primitive value owners.
        allowed = contract.get(
            "enum", [contract["const"]] if "const" in contract else []
        )
        if value not in allowed:
            raise InventoryRefusal("lowering marker has no Kernel value owner")
        yield fixed(value, pointer, owner)

    for _, lowering, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.model_lowerings"
    ):
        if not _consumer_b_definition_is_closed(lowering, grammar, language):
            raise InventoryRefusal(
                "lowering definition does not close its Kernel grammar"
            )
        terminals = []
        for member in ("rule_chain", "structured_rule_chain"):
            for i, step in enumerate(lowering[member]):
                rule = rules.get(step["rule"])
                if rule is None or any(
                    step[key] != rule[key] for key in ("phase", "judgment")
                ):
                    raise InventoryRefusal(
                        "lowering invocation has the wrong rule owner"
                    )
                yield from markers(
                    step["phase"],
                    grammar["field_types"][member]["items"]["field_types"]["phase"],
                    f"{pointer}/{member}/{i}/phase",
                    law + "/field_types/" + member,
                )
            if not lowering[member]:
                raise InventoryRefusal("lowering has no terminal rule")
            name = facts[rules[lowering[member][-1]["rule"]]["conclusion"]["fact_kind"]]
            fields = meta["fact"]["field_contracts"][name]
            terminals.append((fields, "/meta_format/fact/field_contracts/" + name))
            if not _consumer_b_runtime_projection_is_closed(
                lowering["runtime_projection"],
                meta["runtime_projection"],
                language,
                fields,
                definitions,
                meta,
            ):
                raise InventoryRefusal(
                    "lowering Runtime projection is not independently closed"
                )
            for ei, equality in enumerate(lowering["output_equalities"]):
                for side in ("left", "right"):
                    if (
                        _consumer_b_fact_contract_at_path(fields, equality[side])
                        is None
                    ):
                        raise InventoryRefusal(
                            "lowering equality has no terminal Fact owner"
                        )
                    yield from path_links(
                        equality[side],
                        f"{pointer}/output_equalities/{ei}/{side}",
                        {"field_types": fields},
                        terminals[-1][1],
                    )
        projection = lowering["runtime_projection"]
        pp = pointer + "/runtime_projection"
        shapes = {}
        for ci, collection in enumerate(projection["collections"]):
            source = collection["source"]
            cp = f"{pp}/collections/{ci}/source"
            if source["kind"] == "namespace-member":
                owner = (
                    "/meta_format/runtime_projection/path_typing/namespace/"
                    + source["member"]
                )
                shape = rir[source["member"]]["items"]
                shapes[collection["id"]] = (shape, owner, True)
                yield fixed(
                    source["member"],
                    cp + "/member",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/rir_structure/namespace_outputs",
                )
                yield from path_links(
                    source["package_path"],
                    cp + "/package_path",
                    shape,
                    owner,
                    schema=True,
                )
            else:
                shape = _consumer_b_semantic_item_contract(
                    source["authority_path"], definitions
                )
                if shape is None:
                    raise InventoryRefusal(
                        "lowering collection has no Kernel source owner"
                    )
                owner = "/meta_format/language_definitions/" + source["authority_path"]
                shapes[collection["id"]] = (shape, owner, False)
                yield fixed(
                    source["authority_path"],
                    cp + "/authority_path",
                    "/meta_format/package_release/semantic_closure/projections",
                )
            yield from markers(
                source["kind"],
                {"enum": meta["runtime_projection"]["collection_source_kinds"]},
                cp + "/kind",
                "/meta_format/runtime_projection/collection_source_kinds",
            )
        for si, seed in enumerate(projection["seeds"]):
            sp = f"{pp}/seeds/{si}"
            shape, owner, schema = shapes[seed["collection"]]
            yield from path_links(
                seed["target_path"], sp + "/target_path", shape, owner, schema=schema
            )
            applicable = [
                (fields, owner)
                for fields, owner in terminals
                if seed["applicability_member"] in fields
            ]
            if not applicable:
                raise InventoryRefusal("lowering seed has no applicable terminal Fact")
            for fields, owner in applicable:
                yield fixed(
                    seed["applicability_member"],
                    sp + "/applicability_member",
                    owner + "/",
                )
                for member in ("declaration_path", "declaration_package_path"):
                    yield from path_links(
                        seed[member], sp + "/" + member, {"field_types": fields}, owner
                    )
        for ei, edge in enumerate(projection["edges"]):
            for side in ("source", "target"):
                shape, owner, schema = shapes[edge[side + "_collection"]]
                yield from path_links(
                    edge[side + "_path"],
                    f"{pp}/edges/{ei}/{side}_path",
                    shape,
                    owner,
                    schema=schema,
                )
        closure = projection["type_reference_closure"]
        for member, collection in (
            ("source_definition_path", "source_collection"),
            ("constructor_kind_path", "target_constructor_collection"),
        ):
            shape, owner, schema = shapes[closure[collection]]
            yield from path_links(
                closure[member],
                pp + "/type_reference_closure/" + member,
                shape,
                owner,
                schema=schema,
            )
        policy = lowering["assignment_policy"]
        fields = grammar["field_types"]["assignment_policy"]["field_types"]["roles"][
            "items"
        ]["field_types"]
        for ri, role in enumerate(policy["roles"]):
            rp = f"{pointer}/assignment_policy/roles/{ri}"
            yield from markers(
                role["binding_kind"],
                fields["binding_kind"],
                rp + "/binding_kind",
                law + "/assignment_policy/roles/binding_kind",
            )
            # Access values are actual Operation formal access roles. Their
            # strings have no bearing on same-spelled assignment mode names.
            access = definitions["wire_schema_protocol_roles"]["rir_structure"][
                "containers"
            ]["argument"]["field_types"]["access"]
            for ai, name in enumerate(role["entrypoint_operand_access"]):
                yield from markers(
                    name,
                    access,
                    f"{rp}/entrypoint_operand_access/{ai}",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/rir_structure/containers/argument/field_types/access",
                )
            for mi, mode in enumerate(role["modes"]):
                for member, field in fields["modes"]["items"]["field_types"].items():
                    if "enum" in field:
                        yield from markers(
                            mode[member],
                            field,
                            f"{rp}/modes/{mi}/{member}",
                            law + "/assignment_policy/roles/modes/" + member,
                        )


def _resolution_binding_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Read lexical binding occurrences without re-evaluating relation recipes."""
    contract = kernel["meta_format"]["resolution_judgment"]
    grammar = contract["relation_recipe_format"]
    schemas = contract["relation_schemas"]
    for _, profile, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.resolution_profiles"
    ):
        for ji, judgment in enumerate(profile["judgment_chain"]):
            yield (
                AuthorityToken("resolution-judgment", (profile["id"],), judgment["id"]),
                f"{pointer}/judgment_chain/{ji}/id",
                "declaration",
                "/meta_format/language_definitions/collections/resolution_profiles",
            )
        recipes = profile["relation_recipes"]
        if [recipe["id"] for recipe in recipes] != [schema["id"] for schema in schemas]:
            raise InventoryRefusal("resolution recipes do not cover Kernel relations")
        for ri, (recipe, schema) in enumerate(zip(recipes, schemas, strict=True)):
            rp = f"{pointer}/relation_recipes/{ri}"
            if set(recipe) != {"id", "bindings", "predicates", "fields"}:
                raise InventoryRefusal("resolution recipe has unknown members")
            yield (
                AuthorityToken(
                    "kernel.meta_format.resolution_judgment.relation_schemas.id",
                    (),
                    recipe["id"],
                ),
                rp + "/id",
                "reference",
                "/meta_format/resolution_judgment/relation_schemas",
            )
            scope = (profile["id"], recipe["id"])
            bound: set[str] = set()

            def term(value: dict[str, Any], tp: str, *, source: bool = False):
                roots = grammar["binding_source_roots" if source else "term_roots"]
                root = value.get("root")
                required = {"root", "path"} | (
                    {"binding"} if root == "binding" else set()
                )
                if root not in roots or set(value) != required:
                    raise InventoryRefusal(
                        "resolution term has unknown members or root"
                    )
                if not isinstance(value["path"], list) or not all(
                    isinstance(segment, str) and segment for segment in value["path"]
                ):
                    raise InventoryRefusal("resolution term has no closed member path")
                if root == "binding":
                    if value["binding"] not in bound:
                        raise InventoryRefusal(
                            "resolution binding is not lexically available"
                        )
                    yield (
                        AuthorityToken("recipe-binding", scope, value["binding"]),
                        tp + "/binding",
                        "reference",
                        "/meta_format/resolution_judgment/relation_recipe_format/term",
                    )

            for bi, binding in enumerate(recipe["bindings"]):
                bp = f"{rp}/bindings/{bi}"
                if (
                    set(binding) != set(grammar["binding"]["required_members"])
                    or not isinstance(binding["name"], str)
                    or not binding["name"]
                    or binding["name"] in bound
                ):
                    raise InventoryRefusal(
                        "resolution binding declaration is not unique"
                    )
                yield from term(binding["source"], bp + "/source", source=True)
                yield (
                    AuthorityToken("recipe-binding", scope, binding["name"]),
                    bp + "/name",
                    "declaration",
                    "/meta_format/resolution_judgment/relation_recipe_format/binding",
                )
                bound.add(binding["name"])
            for pi, predicate in enumerate(recipe["predicates"]):
                pp = f"{rp}/predicates/{pi}"
                if (
                    set(predicate) != set(grammar["predicate"]["required_members"])
                    or predicate["operator"] not in grammar["predicate_operators"]
                ):
                    raise InventoryRefusal(
                        "resolution predicate does not close its grammar"
                    )
                for member in ("left", "right"):
                    yield from term(predicate[member], pp + "/" + member)
            if [field["name"] for field in recipe["fields"]] != schema["fields"]:
                raise InventoryRefusal("resolution fields do not cover Kernel relation")
            for fi, field in enumerate(recipe["fields"]):
                fp = f"{rp}/fields/{fi}"
                if set(field) != set(grammar["field"]["required_members"]) or field[
                    "pointer"
                ] != (field["name"] in schema["pointer_fields"]):
                    raise InventoryRefusal(
                        "resolution field does not close its grammar"
                    )
                yield (
                    AuthorityToken(
                        f"kernel.meta_format.resolution_judgment.relation_schemas.{ri}.fields",
                        (),
                        field["name"],
                    ),
                    fp + "/name",
                    "reference",
                    "/meta_format/resolution_judgment/relation_schemas",
                )
                yield from term(field["term"], fp + "/term")


def _resolution_policy_fixed_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Bind authored Resolution selectors to their fixed Kernel owners."""
    meta = kernel["meta_format"]
    operations = {row["id"] for row in meta["resolution_judgment"]["operations"]}
    formula_contract = meta["formula_resolution"]
    runtime = meta["runtime_program"]
    nodes = {row["id"]: row for row in runtime["nodes"]}
    fact_schemas = {row["kind"]: row for row in meta["fact"]["schemas"]}
    fact_contracts = meta["fact"]["field_contracts"]
    lowerings = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_lowerings")
    )
    law = "/meta_format/language_definitions/collections/resolution_profiles"
    for _, profile, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.resolution_profiles"
    ):
        for i, judgment in enumerate(profile["judgment_chain"]):
            operation = judgment["operation"]
            if operation not in operations:
                raise InventoryRefusal(
                    "Resolution judgment has no fixed Kernel operation owner"
                )
            yield (
                AuthorityToken(
                    "kernel.meta_format.resolution_judgment.operations",
                    (),
                    operation,
                ),
                f"{pointer}/judgment_chain/{i}/operation",
                "reference",
                law,
            )

        selected = [
            lowering
            for _, lowering, _ in lowerings
            if lowering["resolution_profile"] == profile["id"]
        ]
        if not selected:
            raise InventoryRefusal("Resolution profile has no Model lowering owner")
        fact_member = profile["symbol_fact_member"]
        field_contract_names: set[str] = set()
        for lowering in selected:
            for member in ("initial_fact_kind", "structured_initial_fact_kind"):
                schema = fact_schemas.get(lowering[member])
                if schema is None:
                    raise InventoryRefusal(
                        "Resolution Symbol selector has no initial Fact Schema"
                    )
                field_contract_names.add(schema["field_contract"])
        for field_contract in sorted(field_contract_names):
            if fact_member not in fact_contracts[field_contract]:
                raise InventoryRefusal(
                    "Resolution Symbol selector has no fixed Fact field owner"
                )
            yield (
                AuthorityToken(
                    "kernel.meta_format.fact.field_contracts",
                    (field_contract,),
                    fact_member,
                ),
                pointer + "/symbol_fact_member",
                "reference",
                law,
            )

        formula = profile["formula_resolution"]
        formula_pointer = pointer + "/formula_resolution"
        for i, alias in enumerate(formula["fixed_value_type_aliases"]):
            contract = alias["contract"]
            if contract not in runtime["fixed_value_contracts"]:
                raise InventoryRefusal(
                    "Formula fixed alias has no Kernel value contract owner"
                )
            yield (
                AuthorityToken(
                    "kernel.meta_format.runtime_program.fixed_value_contracts",
                    (),
                    contract,
                ),
                f"{formula_pointer}/fixed_value_type_aliases/{i}/contract",
                "reference",
                law,
            )

        inference = formula["notation_conversion"]["local_result_inference"]
        for i, row in enumerate(inference):
            row_pointer = (
                f"{formula_pointer}/notation_conversion/local_result_inference/{i}"
            )
            node = nodes.get(row["node"])
            if node is None:
                raise InventoryRefusal(
                    "Formula inference selector has no Kernel runtime node owner"
                )
            yield (
                AuthorityToken(
                    "kernel.meta_format.runtime_program.nodes", (), row["node"]
                ),
                row_pointer + "/node",
                "reference",
                law,
            )
            rule = row["rule"]
            if rule not in formula_contract["inference_operators"]:
                raise InventoryRefusal(
                    "Formula inference rule has no Kernel operator owner"
                )
            yield (
                AuthorityToken(
                    "kernel.meta_format.formula_resolution.inference_operators",
                    (),
                    rule,
                ),
                row_pointer + "/rule",
                "reference",
                law,
            )
            selectors = [
                (member, row[member])
                for member in ("target_member", "source_member", "literal_member")
                if member in row
            ]
            selectors.extend(
                (f"operand_members/{index}", member)
                for index, member in enumerate(row.get("operand_members", []))
            )
            for member_path, selected_member in selectors:
                if selected_member not in node["required_members"]:
                    raise InventoryRefusal(
                        "Formula inference selector has no Kernel node member owner"
                    )
                yield (
                    AuthorityToken(
                        "kernel.meta_format.runtime_program.node_member",
                        (node["id"],),
                        selected_member,
                    ),
                    row_pointer + "/" + member_path,
                    "reference",
                    law,
                )


def _close_projection_occurrences(graph, occurrences, projections):
    """Transport roles to a fixed point over existing canonical value positions.

    Projection values are already checked equal by their machine-law reader.
    Each step preserves an existing token and descendant position; it cannot
    manufacture roles for opaque data, even when projections form a cycle.
    """
    closed = set(occurrences)
    pending = list(closed)
    while pending:
        row = pending.pop()
        for source, target in projections:
            if not (
                (row.pointer == source and row.location != "key")
                or row.pointer.startswith(source + "/")
            ):
                continue
            pointer = target + row.pointer.removeprefix(source)
            # The graph is finite. A propagated address must name an actual
            # member, not a synthetic path produced by cycling projections.
            _pointer_value(graph, pointer)
            copied = TokenOccurrence(
                row.token, pointer, "reference", row.law, row.location, row.projection
            )
            if copied not in closed:
                closed.add(copied)
                pending.append(copied)
    return tuple(sorted(closed))


def _operation_relation_surfaces(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Join declared relation policies, selectors, and exact Operation projections.

    Canonical metadata is data, not an implicit namespace. Only addressed object
    members and values projected from an interpreted Operation acquire roles.
    """
    contract = kernel["meta_format"]["package_vector"]
    ki, kind = next(
        (i, row)
        for i, row in enumerate(contract["kinds"])
        if row["id"] == "operation-relation"
    )
    law = f"/meta_format/package_vector/kinds/{ki}"
    declaration_key, policy_key = (
        kind["declaration_extension"],
        kind["policy_extension"],
    )
    operations: dict[tuple[str, str], tuple[Any, str]] = {}
    for owner, value, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.operations"
    ):
        if not isinstance(owner, str):
            raise InventoryRefusal("Operation relation has no package owner")
        operations[(owner, value["id"])] = value, pointer
    links: set[TokenOccurrence] = set()
    projections: list[tuple[str, str]] = []
    covered: set[str] = set()
    handled: set[str] = set()
    policies: dict[tuple[str, str], tuple[Any, str]] = {}

    def occurrence(token, pointer, use, location="value"):
        links.add(TokenOccurrence(token, pointer, use, law, location))

    def marker(name, pointer, field):
        occurrence(
            AuthorityToken("kernel.operation-relation." + field, (), name),
            pointer,
            "reference",
            "key",
        )

    def project(source, target):
        if not _consumer_b_canonical_equal(
            _pointer_value(graph, source), _pointer_value(graph, target)
        ):
            raise InventoryRefusal(
                "Operation relation projection does not match its owner"
            )
        projections.append((source, target))

    def address(scope, path, pointer):
        operation, op = operations[scope]
        if (
            not isinstance(path, list)
            or not path
            or not all(isinstance(member, str) and member for member in path)
            or path[0] not in contract["operation_probe_roots"]
        ):
            raise InventoryRefusal("Operation relation selector has no declared root")
        selected, selected_pointer = operation, op
        for i, member in enumerate(path):
            if not isinstance(selected, dict) or member not in selected:
                raise InventoryRefusal("Operation relation selector does not resolve")
            selected_pointer = _child(selected_pointer, member)
            selected = selected[member]
            if path[0] == "extensions" and i > 0:
                token = AuthorityToken(
                    "operation-extension-member", (*scope, *path[1:i]), member
                )
                occurrence(token, selected_pointer, "declaration", "key")
                occurrence(token, f"{pointer}/{i}", "reference")
            elif i > 0:
                # Other Operation substructure has its own typed selectors. Do
                # not certify it using arbitrary dictionary traversal.
                raise InventoryRefusal(
                    "Operation relation selector needs an interpreted member owner"
                )
        return selected, selected_pointer

    for owner, definition, pointer in _authority_path_rows(
        kernel, graph, "language_bundle." + kind["policy_authority_path"]
    ):
        if not isinstance(owner, str):
            raise InventoryRefusal("Operation relation policy has no package owner")
        extension = definition.get("extensions", {}).get(policy_key)
        if extension is None:
            continue
        ep = _child(pointer + "/extensions", policy_key)
        if not isinstance(extension, list) or not extension:
            raise InventoryRefusal("Operation relation policy is empty or malformed")
        marker(policy_key, ep, "policy_extension")
        for i, policy in enumerate(extension):
            pp = f"{ep}/{i}"
            if (
                not isinstance(policy, dict)
                or set(policy) != set(kind["policy_members"])
                or not isinstance(policy["contract"], dict)
                or set(policy["contract"]) != set(kind["policy_contract_members"])
            ):
                raise InventoryRefusal(
                    "Operation relation policy has an undeclared shape"
                )
            scope = (owner, policy["operation"])
            if scope not in operations or scope in policies:
                raise InventoryRefusal(
                    "Operation relation policy owner is missing or duplicated"
                )
            policies[scope] = policy, pp
            occurrence(
                AuthorityToken("language.operations", (owner,), policy["operation"]),
                pp + "/operation",
                "reference",
            )
        covered.add(ep)

    declared: dict[tuple[str, str], dict[str, str]] = {}
    # A policy selects the actual canonical metadata object. Its label need not
    # equal the capability ID; that equality has no machine interpretation.
    for scope, (operation, op) in operations.items():
        declarations = operation.get("extensions", {}).get(declaration_key)
        if declarations is None:
            if scope in policies:
                raise InventoryRefusal("Operation relation policy has no declarations")
            continue
        if (
            scope not in policies
            or not isinstance(declarations, list)
            or not declarations
        ):
            raise InventoryRefusal(
                "Operation relation declarations have no unique policy"
            )
        policy, pp = policies[scope]
        metadata_path = policy["contract"]["path"]
        if (
            not isinstance(metadata_path, list)
            or len(metadata_path) != 2
            or metadata_path[0] != "extensions"
            or metadata_path[1] == declaration_key
        ):
            raise InventoryRefusal(
                "Operation relation metadata needs its own extension owner"
            )
        _, mp = address(scope, metadata_path, pp + "/contract/path")
        dp = _child(op + "/extensions", declaration_key)
        marker(declaration_key, dp, "declaration_extension")
        roles: dict[str, str] = {}
        for i, declaration in enumerate(declarations):
            rp = f"{dp}/{i}"
            if (
                not isinstance(declaration, dict)
                or set(declaration) != set(kind["declaration_members"])
                or not isinstance(declaration["id"], str)
                or not declaration["id"]
                or declaration["id"] in roles
            ):
                raise InventoryRefusal(
                    "Operation relation declaration is malformed or duplicated"
                )
            role = declaration["id"]
            probe = declaration["probe"]
            witness = {"role": role, "probe": probe}
            if not _consumer_b_operation_relation_is_satisfied(
                operation,
                witness,
                kind,
                contract["operation_probe_roots"],
                kernel["meta_format"]["runtime_program"]["nodes"],
            ):
                raise InventoryRefusal("Operation relation is not satisfied")
            roles[role] = rp
            occurrence(
                AuthorityToken("operation-relation", scope, role),
                rp + "/id",
                "declaration",
            )
            _, left = address(scope, probe["left_path"], rp + "/probe/left_path")
            right = rp + "/probe/right_value"
            if probe["right_path"] is not None:
                _, right = address(scope, probe["right_path"], rp + "/probe/right_path")
            operator = probe["operator"]
            if operator == "integer-range-equal":
                for member in kind["integer_range_members"]:
                    address(
                        scope,
                        _pointer_value(graph, right)[member],
                        _child(right, member),
                    )
            elif operator == "schedule-projection-equal":
                nodes = {
                    row["id"]
                    for row in kernel["meta_format"]["runtime_program"]["nodes"]
                    if row["semantics"]["operator"] == "schedule-operation"
                }
                instructions = _pointer_value(graph, left)
                selected = [
                    (j, row)
                    for j, row in enumerate(instructions)
                    if row["node"] in nodes
                    and all(
                        member in row for member in kind["schedule_projection_members"]
                    )
                ]
                for j, (index, _) in enumerate(selected):
                    for member in kind["schedule_projection_members"]:
                        project(f"{left}/{index}/{member}", f"{right}/{j}/{member}")
            elif operator == "canonical-equal":
                project(left, right)
                # Equality binds the addressed value roles in either direction;
                # neither operand is required to be the interpreted source.
                project(right, left)
            elif operator not in {
                "integer-equal",
                "integer-greater-than",
                "integer-less-than-or-equal",
            }:
                raise InventoryRefusal("Operation relation operator is unclassified")
        declared[scope] = roles
        # These copies join the same closure as body-derived roles. Contract
        # vectors subsequently project the complete authored subtrees.
        project(mp, pp + "/contract/expect")
        project(dp, pp + "/relations")
        covered.update((mp, dp))

    observed: dict[tuple[str, str], list[str]] = {}
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for i, vector in enumerate(vector_set["vector_definitions"]):
            if vector.get("kind") != kind["id"]:
                continue
            vp = f"/vector_sets/{vi}/vector_definitions/{i}"
            if (
                set(vector) != set(kind["required_members"])
                or vector["category"] not in contract["categories"]
            ):
                raise InventoryRefusal(
                    "Operation relation vector has an undeclared shape"
                )
            scope = (vector_set["package_id"], vector["operation"])
            role = vector["role"]
            if scope not in declared or role not in declared[scope]:
                raise InventoryRefusal(
                    "Operation relation vector has no declared owner"
                )
            occurrence(
                AuthorityToken("language.operations", scope[:1], scope[1]),
                vp + "/operation",
                "reference",
            )
            occurrence(
                AuthorityToken("operation-relation", scope, role),
                vp + "/role",
                "reference",
            )
            project(declared[scope][role] + "/probe", vp + "/probe")
            observed.setdefault(scope, []).append(role)
            handled.add(vp)
    if graph.get("vector_sets") is not None and {
        scope: sorted(roles) for scope, roles in declared.items()
    } != {scope: sorted(roles) for scope, roles in observed.items()}:
        raise InventoryRefusal("Operation relation vector coverage does not close")
    return links, projections, covered, handled


def _contract_vector_projections(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Locate exact authored-subtree projections declared by contract vectors."""
    contract = kernel["meta_format"]["package_vector"]
    kinds = {kind["id"]: kind for kind in contract["kinds"]}
    packages = {
        package["id"]: (i, package) for i, package in enumerate(graph["packages"])
    }
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        owner = vector_set["package_id"]
        pi, package = packages[owner]
        for di, vector in enumerate(vector_set["vector_definitions"]):
            kind = vector.get("kind")
            if kind not in {"package-contract", "operation-contract"}:
                continue
            vp = f"/vector_sets/{vi}/vector_definitions/{di}"
            shape = kinds[kind]
            if (
                set(vector) != set(shape["required_members"])
                or set(vector["probe"]) != set(shape["probe_members"])
                or vector["category"] not in contract["categories"]
            ):
                raise InventoryRefusal(
                    "contract vector does not close its Kernel shape"
                )
            if kind == "package-contract":
                selected, source = package, f"/packages/{pi}"
                roots = contract["package_probe_roots"]
                operation = None
            else:
                selected_rows = [
                    (
                        definition,
                        f"/packages/{pi}/semantic_closure/{ci}/definitions/{oi}",
                    )
                    for ci, closure in enumerate(package["semantic_closure"])
                    if closure["authority_path"] == "language.operations"
                    for oi, definition in enumerate(closure["definitions"])
                    if definition["id"] == vector["operation"]
                ]
                if len(selected_rows) != 1:
                    raise InventoryRefusal(
                        "contract vector Operation owner is unresolved"
                    )
                selected, source = selected_rows[0]
                roots = contract["operation_probe_roots"]
                operation = AuthorityToken(
                    "language.operations", (owner,), vector["operation"]
                )
            path = vector["probe"]["path"]
            if not isinstance(path, str) or path.split(".")[0] not in roots:
                raise InventoryRefusal("contract vector addresses an undeclared root")
            for member in path.split("."):
                if not isinstance(selected, dict) or member not in selected:
                    raise InventoryRefusal("contract vector path does not resolve")
                selected, source = selected[member], _child(source, member)
            if not _consumer_b_canonical_equal(selected, vector["expect"]):
                raise InventoryRefusal(
                    "contract vector expected subtree is not its declared projection"
                )
            yield source, vp + "/expect", vp, operation


def _typed_context(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    types = {
        (package["id"], row["id"]): row
        for package in graph["packages"]
        for row in package["exports"]["types"]
    }
    for owner, row, _ in _authority_path_rows(
        kernel, graph, "language_bundle.language.nominal_types"
    ):
        types[(owner, row["id"])] = row
    constructor_rows = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.constructors")
    )
    constructors = {}
    for _, row, pointer in constructor_rows:
        kind = row.get("value_rule", {}).get("definition_kind")
        if kind is None:
            continue
        if kind in constructors:
            raise InventoryRefusal("structured constructor role is not unique")
        constructors[kind] = (row, pointer)
    return types, constructors


def _lexical_child(owner, step, member=None):
    if owner is None:
        return None
    return (*owner, step) if member is None else (*owner, step, member)


def _typed_member_token(role, owner, lexical_owner, name):
    if owner is not None:
        return AuthorityToken(role, owner, name)
    if lexical_owner is not None:
        return AuthorityToken("vector-" + role, lexical_owner, name)
    return None


def _type_links(
    value, pointer, constructors, owner=None, *, lexical_owner=None, declaration=True
):
    law = "/meta_format/literal_typing/typed_envelope_profile/admission/nominal_type_reference"
    if not isinstance(value, dict):
        raise InventoryRefusal(f"Type reference is not an object at {pointer}")
    if "package" in value or "id" in value:
        if set(value) not in ({"package", "id"}, {"package", "id", "kind"}):
            raise InventoryRefusal(f"unknown Type reference shape at {pointer}")
        yield TokenOccurrence(
            AuthorityToken("namespace", (), value["package"]),
            pointer + "/package",
            "reference",
            law,
        )
        yield TokenOccurrence(
            AuthorityToken("type", (value["package"],), value["id"]),
            pointer + "/id",
            "reference",
            law,
        )
        return
    definition = value
    selected = constructors.get(definition.get("kind"))
    if selected is None:
        raise InventoryRefusal(f"unknown structured constructor at {pointer}")
    constructor, cp = selected
    if set(definition) != {"kind", *constructor["parameters"]}:
        raise InventoryRefusal(
            f"structured definition has undeclared members at {pointer}"
        )
    rule, law = constructor["value_rule"], cp + "/value_rule"
    for member in constructor["parameters"]:
        yield TokenOccurrence(
            AuthorityToken(
                "constructor-member", (constructor["id"], "definition"), member
            ),
            _child(pointer, member),
            "reference",
            law,
            "key",
        )
    operator = rule["operator"]
    if operator == "enum-member":
        member = rule["members_member"]
        for i, name in enumerate(definition[member]):
            token = _typed_member_token("enum-member", owner, lexical_owner, name)
            if token is None:
                yield UncoveredRole(
                    pointer, law, "anonymous Enum scope is not yet represented"
                )
                return
            yield TokenOccurrence(
                token,
                f"{pointer}/{member}/{i}",
                "declaration" if declaration else "reference",
                law,
            )
    elif operator == "bounded-list":
        yield from _type_links(
            definition[rule["element_member"]],
            _child(pointer, rule["element_member"]),
            constructors,
            lexical_owner=_lexical_child(lexical_owner, "element"),
            declaration=declaration,
        )
    elif operator == "closed-record":
        for i, field in enumerate(definition[rule["fields_member"]]):
            fp = f"{pointer}/{rule['fields_member']}/{i}"
            if set(field) != {rule["field_name_member"], rule["field_type_member"]}:
                raise InventoryRefusal(f"Record field has undeclared members at {fp}")
            for selector in ("field_name_member", "field_type_member"):
                member = rule[selector]
                yield TokenOccurrence(
                    AuthorityToken(
                        "constructor-member",
                        (constructor["id"], "record-field"),
                        member,
                    ),
                    _child(fp, member),
                    "reference",
                    law,
                    "key",
                )
            name = field[rule["field_name_member"]]
            token = _typed_member_token("record-field", owner, lexical_owner, name)
            if token is None:
                yield UncoveredRole(
                    fp, law, "anonymous Record scope is not yet represented"
                )
            else:
                yield TokenOccurrence(
                    token,
                    _child(fp, rule["field_name_member"]),
                    "declaration" if declaration else "reference",
                    law,
                )
            yield from _type_links(
                field[rule["field_type_member"]],
                _child(fp, rule["field_type_member"]),
                constructors,
                lexical_owner=_lexical_child(lexical_owner, "field", name),
                declaration=declaration,
            )
    elif operator == "canonical-ref-key":
        yield from _type_links(
            definition[rule["target_member"]],
            _child(pointer, rule["target_member"]),
            constructors,
            lexical_owner=_lexical_child(lexical_owner, "target"),
            declaration=declaration,
        )
    else:
        raise InventoryRefusal(f"unimplemented constructor law {operator} at {pointer}")


def _typed_value_links(
    reference,
    value,
    pointer,
    types,
    constructors,
    *,
    lexical_owner=None,
    allow_unresolved=False,
    path_roles=None,
):
    if "package" in reference:
        selected = types.get((reference["package"], reference["id"]))
        if selected is None or "definition" not in selected:
            return  # Scalar or Kernel value has no authored nested labels.
        owner = (reference["package"], reference["id"])
        definition = selected["definition"]
        lexical_owner = None
    else:
        definition, owner = reference, None
    selected = constructors.get(definition.get("kind"))
    if selected is None:
        raise InventoryRefusal(f"unknown typed value constructor at {pointer}")
    constructor, cp = selected
    rule, law = constructor["value_rule"], cp + "/value_rule"
    if rule["operator"] == "enum-member":
        if not isinstance(value, str) or not value:
            if allow_unresolved:
                return  # A malformed scalar is data, not a missing identifier.
            raise InventoryRefusal(f"unknown Enum member at {pointer}")
        token = _typed_member_token("enum-member", owner, lexical_owner, value)
        if token is None:
            yield UncoveredRole(
                pointer, law, "anonymous Enum value scope is unresolved"
            )
            return
        absent = value not in definition[rule["members_member"]]
        if absent and not allow_unresolved:
            raise InventoryRefusal(f"unknown Enum member at {pointer}")
        yield TokenOccurrence(
            token, pointer, "unresolved-reference" if absent else "reference", law
        )
    elif rule["operator"] == "bounded-list":
        if not isinstance(value, list):
            if allow_unresolved:
                return
            raise InventoryRefusal("typed List value is not an array")
        for i, item in enumerate(value):
            child = _child(pointer, i)
            if path_roles is not None:
                path_roles[child] = None  # List position is numeric data.
            yield from _typed_value_links(
                definition[rule["element_member"]],
                item,
                child,
                types,
                constructors,
                lexical_owner=_lexical_child(lexical_owner, "element"),
                allow_unresolved=allow_unresolved,
                path_roles=path_roles,
            )
    elif rule["operator"] == "closed-record":
        if not isinstance(value, dict):
            if allow_unresolved:
                return
            raise InventoryRefusal("typed Record value is not an object")
        fields = definition[rule["fields_member"]]
        names = {field[rule["field_name_member"]] for field in fields}
        for field in fields:
            name = field[rule["field_name_member"]]
            child = _child(pointer, name)
            token = _typed_member_token("record-field", owner, lexical_owner, name)
            if token is None:
                yield UncoveredRole(
                    pointer, law, "anonymous Record value scope is unresolved"
                )
            elif path_roles is not None:
                path_roles[child] = (token, "reference", law)
            if name not in value and allow_unresolved:
                continue  # The diagnostic references the existing field declaration.
            if token is not None:
                yield TokenOccurrence(token, child, "reference", law, "key")
            yield from _typed_value_links(
                field[rule["field_type_member"]],
                value[name],
                child,
                types,
                constructors,
                lexical_owner=_lexical_child(lexical_owner, "field", name),
                allow_unresolved=allow_unresolved,
                path_roles=path_roles,
            )
        for extra in value.keys() - names:
            if not allow_unresolved:
                raise InventoryRefusal("typed Record has an undeclared field")
            token = _typed_member_token("record-field", owner, lexical_owner, extra)
            child = _child(pointer, extra)
            if token is None:
                yield UncoveredRole(
                    child, law, "anonymous extra field scope is unresolved"
                )
                continue
            if path_roles is not None:
                path_roles[child] = (token, "unresolved-reference", law)
            yield TokenOccurrence(token, child, "unresolved-reference", law, "key")
            # The undeclared field's payload has no selected field type.
    elif rule["operator"] == "canonical-ref-key":
        if not isinstance(value, dict) or set(value) != set(rule["value_members"]):
            raise InventoryRefusal(
                "Ref value does not close its declared member addresses"
            )
        for member in rule["value_members"]:
            token = AuthorityToken(
                "constructor-member", (constructor["id"], "ref-value"), member
            )
            child = _child(pointer, member)
            if path_roles is not None:
                path_roles[child] = (token, "reference", law)
            yield TokenOccurrence(token, child, "reference", law, "key")
        # Key contents remain canonical instance data, including invalid patterns.
    else:
        raise InventoryRefusal(f"unknown typed value law at {pointer}")


def _operation_vector_rows(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Select package-owned vectors after the existing independent type check."""
    contract = kernel["meta_format"]["package_vector"]
    kind = next(row for row in contract["kinds"] if row["id"] == "operation-execution")
    packages = {row["id"]: row for row in graph["packages"]}
    runtime = kernel["meta_format"]["runtime_program"]
    language = None
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        if not any(
            v.get("kind") == kind["id"] for v in vector_set["vector_definitions"]
        ):
            continue
        package = packages[vector_set["package_id"]]
        if language is None:
            language = _attached_language(kernel, graph)
        if not _consumer_b_package_evidence_vectors_are_closed(
            package,
            vector_set,
            contract,
            runtime["named_rng"]["candidate_encoding"],
            runtime,
            dict(kernel),
            language,
        ):
            raise InventoryRefusal(
                "Operation vectors do not close their selected contracts"
            )
        operations = {
            row["id"]: row
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.operations"
            for row in closure["definitions"]
        }
        for di, vector in enumerate(vector_set["vector_definitions"]):
            if vector.get("kind") == kind["id"]:
                yield (
                    package["id"],
                    operations[vector["operation"]],
                    vector,
                    kind,
                    (f"/vector_sets/{vi}/vector_definitions/{di}"),
                )


def _operation_vector_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Follow formal value owners; never execute or rewrite numeric expectations."""
    types, constructors = _typed_context(kernel, graph)
    envelope = kernel["meta_format"]["literal_typing"]["typed_envelope_profile"]
    tm, vm = envelope["type_member"], envelope["value_member"]

    def value_links(formal, value, pointer):
        # Only a selected nominal formal grants the envelope meaning. A scalar,
        # Boolean, Unit or canonical Ref key never becomes a Type by its shape.
        if formal.get("value_kind") == "nominal-structured":
            yield from _type_links(value[tm], _child(pointer, tm), constructors)
            yield from _typed_value_links(
                formal["type"], value[vm], _child(pointer, vm), types, constructors
            )

    for owner, operation, vector, shape, pointer in _operation_vector_rows(
        kernel, graph
    ):
        law = "/meta_format/package_vector/kinds/" + str(
            kernel["meta_format"]["package_vector"]["kinds"].index(shape)
        )
        scope = (owner, operation["id"])
        yield TokenOccurrence(
            AuthorityToken("language.operations", (owner,), operation["id"]),
            pointer + "/operation",
            "reference",
            law,
        )
        for member, values, formals in (
            ("input/values", vector["input"]["values"], operation["inputs"]),
            (
                "expect/state_after",
                vector["expect"]["state_after"],
                [row for row in operation["inputs"] if row["access"] == "read-write"],
            ),
        ):
            for i, (value, formal) in enumerate(zip(values, formals, strict=True)):
                vp = f"{pointer}/{member}/{i}"
                yield TokenOccurrence(
                    AuthorityToken("operation-port", scope, formal["id"]),
                    vp + "/name",
                    "reference",
                    law,
                )
                yield from value_links(formal, value["value"], vp + "/value")
        completion = vector["expect"]["completion"]
        if completion["kind"] == "outcome":
            token = AuthorityToken("operation-outcome", scope, completion["id"])
            member = "id"
        else:
            token = AuthorityToken("language.reasons", (), completion["reason"])
            member = "reason"
        yield TokenOccurrence(
            token, pointer + "/expect/completion/" + member, "reference", law
        )
        result = vector["expect"]["result"]
        if result["kind"] == "value":
            yield from value_links(
                operation["result"], result["value"], pointer + "/expect/result/value"
            )
        for i, draw in enumerate(vector["expect"]["rng_draws"]):
            yield TokenOccurrence(
                AuthorityToken("named-stream", (), draw["stream"]),
                f"{pointer}/expect/rng_draws/{i}/stream",
                "reference",
                "/meta_format/runtime_program/named_rng/stream_derivation",
            )


def _value_vector_rows(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    contract = kernel["meta_format"]["package_vector"]
    kinds = {row["id"]: row for row in contract["kinds"]}
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            kind = vector.get("kind")
            if kind not in {"value-program", "structured-value"}:
                continue
            shape = kinds[kind]
            if (
                set(vector) != set(shape["required_members"])
                or vector["category"] not in contract["categories"]
                or not isinstance(vector["input"], dict)
                or set(vector["input"]) != set(shape["input_members"])
                or not isinstance(vector["expect"], dict)
                or set(vector["expect"]) != set(shape["expect_members"])
            ):
                raise InventoryRefusal("value vector has an unknown declared member")
            yield vector, shape, f"/vector_sets/{vi}/vector_definitions/{di}"


def _value_vector_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Interpret finite vector roles; observations stay with the independent owner.

    Numeric results/charges and canonical instance keys are never identifiers.
    This pass does not implement an evaluator or synthesize expected observations.
    """
    types, constructors = _typed_context(kernel, graph)
    nodes = {
        row["id"]: row for row in kernel["meta_format"]["runtime_program"]["nodes"]
    }
    diagnostic_key = next(
        row["key_member"]
        for row in kernel["meta_format"]["package_release"]["semantic_closure"][
            "projections"
        ]
        if row["authority_path"] == "diagnostics"
    )
    diagnostics = {
        row[diagnostic_key]
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.diagnostics"
        )
    }
    for vector, shape, pointer in _value_vector_rows(kernel, graph):
        inp, expect = vector["input"], vector["expect"]
        law = "/meta_format/package_vector/kinds/" + str(
            kernel["meta_format"]["package_vector"]["kinds"].index(shape)
        )
        if vector["kind"] == "value-program":
            if (
                not isinstance(inp["instructions"], list)
                or not inp["instructions"]
                or not all(
                    _consumer_b_value_program_instruction_is_closed(
                        row, set(shape["instruction_nodes"])
                    )
                    for row in inp["instructions"]
                )
                or set(inp["numeric"]) != {"minimum", "maximum"}
                or not isinstance(inp["operands"], list)
                or not all(set(row) == {"name", "value"} for row in inp["operands"])
                or len(inp["operands"]) != len({row["name"] for row in inp["operands"]})
            ):
                raise InventoryRefusal(
                    "value program does not close its instruction or operand shape"
                )
            try:
                observed = reference_evaluate_value_program_vector(vector)
            except (AssertionError, KeyError, TypeError, ValueError) as error:
                raise InventoryRefusal(
                    "value program has no independent observation"
                ) from error
            if not _consumer_b_canonical_equal(observed, expect):
                raise InventoryRefusal("value program expected observation disagrees")
            scope = (vector["id"],)
            bindings: dict[str, AuthorityToken] = {}
            for oi, operand in enumerate(inp["operands"]):
                token = AuthorityToken("vector-local", scope, operand["name"])
                bindings[token.name] = token
                yield TokenOccurrence(
                    token, f"{pointer}/input/operands/{oi}/name", "declaration", law
                )
            yield TokenOccurrence(
                AuthorityToken("vector-site", scope, inp["site"]),
                pointer + "/input/site",
                "declaration",
                law,
            )
            for ii, row in enumerate(inp["instructions"]):
                ip = f"{pointer}/input/instructions/{ii}"
                instruction = row["instruction"]
                node = nodes[instruction["node"]]
                if node["family"] != "expression" or set(instruction) != set(
                    node["required_members"]
                ):
                    raise InventoryRefusal(
                        "value program node has an unclassified member"
                    )
                yield TokenOccurrence(
                    AuthorityToken(
                        "vector-site", scope, row["evaluation_site_identity"]
                    ),
                    ip + "/evaluation_site_identity",
                    "declaration",
                    law,
                )
                members = {
                    member
                    for constraint in node["operand_constraints"]
                    for member in constraint.get("members", [])
                }
                typing = node["result"]["typing"]
                if typing["kind"] != "literal-profile":
                    members.update(typing.get("members", []))
                consumed = {"node", "target", *members}
                if typing["kind"] == "literal-profile":
                    consumed.update(typing["members"])
                if consumed != set(instruction):
                    raise InventoryRefusal("value program operand roles are incomplete")
                for member in members:
                    name = instruction[member]
                    if not isinstance(name, str) or name not in bindings:
                        raise InventoryRefusal(
                            "value program has an unresolved lexical operand"
                        )
                    yield TokenOccurrence(
                        bindings[name], ip + "/instruction/" + member, "reference", law
                    )
                token = AuthorityToken("vector-local", scope, instruction["target"])
                bindings[token.name] = token
                yield TokenOccurrence(
                    token, ip + "/instruction/target", "declaration", law
                )
            if inp["result"] not in bindings:
                raise InventoryRefusal("value program result has no lexical binding")
            yield TokenOccurrence(
                bindings[inp["result"]], pointer + "/input/result", "reference", law
            )
            yield TokenOccurrence(
                AuthorityToken("vector-site", scope, expect["site"]),
                pointer + "/expect/site",
                "reference",
                law,
            )
            continue
        yield from _structured_vector_links(
            kernel, graph, vector, shape, pointer, types, constructors, diagnostics
        )


def _structured_vector_links(
    kernel, graph, vector, shape, pointer, types, constructors, diagnostics
):
    inp, expect = vector["input"], vector["expect"]
    law = "/meta_format/package_vector/kinds/" + str(
        kernel["meta_format"]["package_vector"]["kinds"].index(shape)
    )
    if inp["action"] not in shape["actions"]:
        raise InventoryRefusal("structured vector action has no Kernel law")
    envelope = kernel["meta_format"]["literal_typing"]["typed_envelope_profile"]
    tm, vm = envelope["type_member"], envelope["value_member"]
    try:
        observed = _consumer_b_evaluate_structured_value_vector(
            vector,
            nominal_types=list(graph["packages"]),
            kernel=dict(kernel),
            resource_limit=graph["ldb_root"]["resources"]["max_rule_match_steps"],
        )
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise InventoryRefusal(
            "structured vector has no independent observation"
        ) from error
    if not _consumer_b_canonical_equal(observed, expect):
        yield UncoveredRole(
            pointer,
            law,
            "independent structured observation differs from the authored expectation; roles are not certified",
        )
        return
    # Structural equality compares the two annotations in one local comparison
    # scope. A member permutation cannot split equal types or capture unequal
    # member names into equality. Nominal references keep their attached owner.
    lexical = (vector["id"], "comparison" if inp["action"] == "equal" else "left")
    rows = []
    paths: dict[str, set[tuple[AuthorityToken, str, str] | None]] = {
        _child("", vm): {None},
        _child("", tm): {None},
        "/key": {None},
        "/left": {None},
        "/right": {None},
        _child("/left", tm): {None},
        _child("/right", tm): {None},
    }
    for member in ("left", "right"):
        value = inp[member]
        if member == "right" and inp["action"] != "equal":
            if value is not None:
                rows.append(
                    UncoveredRole(
                        pointer + "/input/right",
                        law,
                        "unused right input has no interpreted identity role",
                    )
                )
            continue
        ep = pointer + "/input/" + member
        if not isinstance(value, dict) or set(value) != {tm, vm}:
            rows.append(
                UncoveredRole(ep, law, "negative envelope shape is not yet traversed")
            )
            continue
        value_paths: dict[str, tuple[AuthorityToken, str, str] | None] = {}
        try:
            rows.extend(
                _type_links(
                    value[tm], _child(ep, tm), constructors, lexical_owner=lexical
                )
            )
            rows.extend(
                _typed_value_links(
                    value[tm],
                    value[vm],
                    _child(ep, vm),
                    types,
                    constructors,
                    lexical_owner=lexical,
                    allow_unresolved=True,
                    path_roles=value_paths,
                )
            )
        except InventoryRefusal as error:
            yield UncoveredRole(pointer, law, str(error))
            return
        for address, role in value_paths.items():
            paths.setdefault(address.removeprefix(ep), set()).add(role)
    output_scope = lexical
    if inp["action"] != "lookup" and inp["key"] is not None:
        rows.append(
            UncoveredRole(
                pointer + "/input/key",
                law,
                "unused lookup input has no interpreted identity role",
            )
        )
    if inp["action"] == "lookup":
        ref = inp["left"][tm]
        nominal_owner = (ref["package"], ref["id"]) if "package" in ref else None
        definition = types[nominal_owner]["definition"] if nominal_owner else ref
        constructor, cp = constructors[definition["kind"]]
        rule = constructor["value_rule"]
        lookups = [
            row
            for _, row, _ in _authority_path_rows(
                kernel, graph, "language_bundle.language.structured_operations"
            )
            if row["owner_constructor"] == constructor["id"]
            and row["law"].get("operator") == "bounded-lookup"
        ]
        if len(lookups) != 1:
            raise InventoryRefusal("structured lookup has no selected operation law")
        selector = lookups[0]["law"]["selector"]
        if selector == "static-field" and isinstance(inp["key"], str):
            names = {
                field[rule["field_name_member"]]
                for field in definition[rule["fields_member"]]
            }
            token = _typed_member_token(
                "record-field", nominal_owner, lexical, inp["key"]
            )
            if token is None:
                raise InventoryRefusal("lookup field scope is unresolved")
            rows.append(
                TokenOccurrence(
                    token,
                    pointer + "/input/key",
                    "reference" if inp["key"] in names else "unresolved-reference",
                    cp + "/value_rule",
                )
            )
            output_scope = (
                None if nominal_owner else _lexical_child(lexical, "field", inp["key"])
            )
        elif selector == "local-index":
            output_scope = None if nominal_owner else _lexical_child(lexical, "element")
        elif expect["outcome"] == "admitted":
            raise InventoryRefusal("admitted lookup key does not close its selector")
    if expect["type"] is not None:
        rows.extend(
            _type_links(
                expect["type"],
                pointer + "/expect/type",
                constructors,
                lexical_owner=output_scope,
                declaration=False,
            )
        )
        rows.extend(
            _typed_value_links(
                expect["type"],
                expect["value"],
                pointer + "/expect/value",
                types,
                constructors,
                lexical_owner=output_scope,
            )
        )
    if expect["code"] is not None:
        if expect["code"] not in diagnostics:
            raise InventoryRefusal("structured vector diagnostic is not declared")
        rows.append(
            TokenOccurrence(
                AuthorityToken("diagnostics", (), expect["code"]),
                pointer + "/expect/code",
                "reference",
                law,
            )
        )
        if kernel["meta_format"]["json_pointer"]["encoding"] != "RFC6901":
            raise InventoryRefusal("unsupported diagnostic pointer encoding")
        path = ""
        for index, member in enumerate(_json_pointer_segments(expect["pointer"])):
            path = _child(path, member)
            matches = paths.get(path, set())
            if len(matches) != 1:
                rows.append(
                    UncoveredRole(
                        pointer + "/expect/pointer",
                        law,
                        "diagnostic path has no unique interpreted value-field role",
                    )
                )
                break
            role = next(iter(matches))
            if role is not None:
                token, use, selected_law = role
                rows.append(
                    TokenOccurrence(
                        token,
                        pointer + "/expect/pointer",
                        use,
                        selected_law,
                        "json-pointer",
                        str(index),
                    )
                )
    yield from rows


@dataclass(frozen=True)
class _TemplateSelection:
    """A selected instance type and its existing Schema/Kernel field owner."""

    representation: str
    value: Any
    owner: tuple[str, ...] = ()
    pointer: str = ""
    nominal: str = ""


def _same_instance_schemas(value: Any, pointer):
    """Applicators retain one instance owner; properties/items change its path."""
    if not isinstance(value, dict):
        return
    yield value, pointer
    for applicator in ("oneOf", "anyOf", "allOf"):
        for i, branch in enumerate(value.get(applicator, [])):
            child = (
                f"{pointer}/{applicator}/{i}"
                if isinstance(pointer, str)
                else (*pointer, applicator, i)
            )
            yield from _same_instance_schemas(branch, child)


def _template_exhaustion_declaration(kernel, graph):
    """Resolve the one diagnostic declaration referenced by the Template law."""
    name = kernel["meta_format"]["template_admission"]["resource_accounting"][
        "exhaustion_diagnostic"
    ]
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    index, projection = next(
        (i, p)
        for i, p in enumerate(projections)
        if p["authority_path"] == "diagnostics"
    )
    key = projection["key_member"]
    matches = [
        pointer
        for _, row, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.diagnostics"
        )
        if row[key] == name
    ]
    if len(matches) != 1:
        raise InventoryRefusal(
            "Template exhaustion diagnostic has no unique declaration"
        )
    return TokenOccurrence(
        AuthorityToken("diagnostics", (), name),
        _child(matches[0], key),
        "declaration",
        f"/meta_format/package_release/semantic_closure/projections/{index}",
    )


def _template_inventory(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Close the existing Template program and its variable member Schema owners.

    Selectors traverse instance types, never strings found elsewhere in the graph.
    Fixed result origins reuse Source/Namespace/initial Fact contracts. No Template
    member role, derived name, judgment name or standalone Schema kind is built in.
    """
    meta = kernel["meta_format"]
    law = "/meta_format/template_admission"
    language = _attached_language(kernel, graph)
    language.update({key: value for key, value in graph["ldb_root"].items()})
    language["diagnostics"] = [
        row
        for _, row, _ in _authority_path_rows(
            kernel, graph, "language_bundle.diagnostics"
        )
    ]
    if not _consumer_b_template_admission_is_closed(dict(meta), language):
        raise InventoryRefusal(
            "Template program does not close its admitted primitive contracts"
        )
    contract = meta["template_admission"]
    primitives = {p["id"]: p for p in contract["primitive_spec"]["primitives"]}
    if not isinstance(primitives["model-source-admission"].get("results"), dict):
        raise InventoryRefusal("Template Model result origin contract is missing")
    operations = {o["id"]: o for o in contract["operations"]}
    argument_types = {t["id"]: t for t in contract["primitive_spec"]["argument_types"]}
    schemas = {
        row["artifact_kind"]: (role, row, pointer)
        for role in ("language.wire_schemas", "language.artifact_wire_schemas")
        for _, row, pointer in _authority_path_rows(
            kernel, graph, "language_bundle." + role
        )
    }
    rows: set[TokenOccurrence] = set()
    reserved: set[AuthorityToken] = set()
    roots: set[str] = set()
    variable_schemas: dict[str, _TemplateSelection] = {}
    literal_values: dict[tuple[str, ...], list[tuple[Any, str]]] = {}

    def emit(token, pointer, use="reference", *, location="value", owner_law=law):
        rows.add(TokenOccurrence(token, pointer, use, owner_law, location))
        if token.role.startswith("kernel."):
            reserved.add(token)

    def fixed(value, pointer, owner):
        emit(AuthorityToken("kernel.template-value", (owner,), value), pointer)

    def field_token(shape, member):
        role = (
            "template-field"
            if shape.representation == "schema"
            else "kernel.template-field"
        )
        if shape.representation == "source-schema":
            role = "source-field"
        return AuthorityToken(role, shape.owner, member)

    def schema_children(shape):
        return list(_same_instance_schemas(shape.value, shape.pointer))

    def schema_literal(selected, value, pointer):
        """Interpret const/enum data at its declared instance address, not by text."""
        closed = True
        if isinstance(value, dict):
            for member, child in value.items():
                children = [
                    _TemplateSelection(
                        "schema",
                        fields["properties"][member],
                        (*shape.owner, "member", member),
                        _child(sp + "/properties", member),
                    )
                    for shape in selected
                    for fields, sp in schema_children(shape)
                    if member in fields.get("properties", {})
                ]
                if not children:
                    closed = False
                    continue
                cp = _child(pointer, member)
                for shape in selected:
                    emit(field_token(shape, member), cp, location="key")
                closed = schema_literal(children, child, cp) and closed
        elif isinstance(value, list):
            children = [
                _TemplateSelection(
                    "schema", fields["items"], (*shape.owner, "items"), sp + "/items"
                )
                for shape in selected
                for fields, sp in schema_children(shape)
                if isinstance(fields.get("items"), dict)
            ]
            if value and not children:
                return False
            for i, child in enumerate(value):
                closed = schema_literal(children, child, f"{pointer}/{i}") and closed
        else:
            for shape in selected:
                literal_values.setdefault(shape.owner, []).append((value, pointer))
        return closed

    def schema_fields(shape):
        same = schema_children(shape)
        names = {name for value, _ in same for name in value.get("properties", {})}
        closed = True
        for value, pointer in same:
            for member, child in value.get("properties", {}).items():
                selected = field_token(shape, member)
                cp = _child(pointer + "/properties", member)
                emit(
                    selected, cp, "declaration", location="key", owner_law=shape.pointer
                )
                closed = (
                    schema_fields(
                        _TemplateSelection(
                            "schema", child, (*shape.owner, "member", member), cp
                        )
                    )
                    and closed
                )
            for i, member in enumerate(value.get("required", [])):
                if member not in names:
                    raise InventoryRefusal(
                        "Template Schema required member has no local property owner"
                    )
                emit(
                    field_token(shape, member),
                    f"{pointer}/required/{i}",
                    owner_law=shape.pointer,
                )
            if isinstance(value.get("items"), dict):
                closed = (
                    schema_fields(
                        _TemplateSelection(
                            "schema",
                            value["items"],
                            (*shape.owner, "items"),
                            pointer + "/items",
                        )
                    )
                    and closed
                )
            if "const" in value:
                closed = (
                    schema_literal([shape], value["const"], pointer + "/const")
                    and closed
                )
            for i, item in enumerate(value.get("enum", [])):
                closed = schema_literal([shape], item, f"{pointer}/enum/{i}") and closed
        return closed

    def step(selected, member, pointer):
        output = []
        for shape in selected:
            if shape.representation in {"schema", "source-schema"}:
                for value, sp in schema_children(shape):
                    if member == contract["selector"]["wildcard_segment"]:
                        if isinstance(value.get("items"), dict):
                            output.append(
                                _TemplateSelection(
                                    shape.representation,
                                    value["items"],
                                    (*shape.owner, "items"),
                                    sp + "/items",
                                    shape.nominal,
                                )
                            )
                    elif member in value.get("properties", {}):
                        emit(field_token(shape, member), pointer)
                        output.append(
                            _TemplateSelection(
                                shape.representation,
                                value["properties"][member],
                                (*shape.owner, "member", member),
                                _child(sp + "/properties", member),
                            )
                        )
            elif shape.representation == "list":
                if member == contract["selector"]["wildcard_segment"]:
                    output.extend(shape.value)
            elif shape.representation == "object":
                if member in shape.value:
                    emit(field_token(shape, member), pointer)
                    output.extend(shape.value[member])
            elif shape.representation == "field":
                value = shape.value
                if member == contract["selector"]["wildcard_segment"]:
                    if value.get("type") == "string-list":
                        output.append(
                            _TemplateSelection(
                                "field",
                                {"type": "non-empty-string"},
                                (*shape.owner, "items"),
                                shape.pointer,
                                shape.nominal,
                            )
                        )
                    elif isinstance(value.get("items"), dict):
                        output.append(
                            _TemplateSelection(
                                "field",
                                value["items"],
                                (*shape.owner, "items"),
                                shape.pointer + "/items",
                                shape.nominal,
                            )
                        )
                elif member in value.get("field_types", {}):
                    emit(field_token(shape, member), pointer)
                    output.append(
                        _TemplateSelection(
                            "field",
                            value["field_types"][member],
                            (*shape.owner, "member", member),
                            _child(shape.pointer + "/field_types", member),
                        )
                    )
                elif value.get("type") == "closed-int64-interval" and member in {
                    "minimum",
                    "maximum",
                }:
                    emit(field_token(shape, member), pointer)
                    output.append(
                        _TemplateSelection(
                            "field",
                            {"type": "int64"},
                            (*shape.owner, "member", member),
                            shape.pointer,
                        )
                    )
            elif shape.representation == "kernel":
                value = shape.value
                if member == contract["selector"]["wildcard_segment"] and isinstance(
                    value, list
                ):
                    output.extend(
                        _TemplateSelection(
                            "kernel", item, (*shape.owner, "items"), shape.pointer
                        )
                        for item in value
                    )
                elif isinstance(value, dict) and member in value:
                    emit(field_token(shape, member), pointer)
                    output.append(
                        _TemplateSelection(
                            "kernel",
                            value[member],
                            (*shape.owner, "member", member),
                            _child(shape.pointer, member),
                        )
                    )
        if not output:
            raise InventoryRefusal(
                f"Template selector has no typed member owner at {pointer}"
            )
        return output

    def path(selected, parts, pointer):
        for i, member in enumerate(parts):
            selected = step(selected, member, f"{pointer}/{i}")
        return selected

    def fields_shape(fields, owner, pointer):
        return _TemplateSelection(
            "field", {"type": "closed-object", "field_types": fields}, owner, pointer
        )

    # The virtual language index has the existing package semantic projections as
    # its collection owners. Only declared keys/field contracts are traversable.
    language_tree: dict[str, Any] = {}
    projections = {
        row["authority_path"]: row
        for row in meta["package_release"]["semantic_closure"]["projections"]
    }
    for projection in projections.values():
        authority_path = projection["authority_path"]
        pieces = authority_path.split(".")
        tree = language_tree
        for part in pieces[:-1]:
            tree = tree.setdefault(part, {})
        if authority_path == "diagnostics":
            fields = {projection["key_member"]: {"type": "non-empty-string"}}
        else:
            collection = pieces[-1]
            owner = meta["language_definitions"]
            if pieces[1:2] == ["quantity"]:
                owner = owner["quantity"]
            definition = owner["collections"].get(collection)
            if isinstance(definition, dict):
                fields = definition.get("field_types")
            elif authority_path == "language.reasons":
                fields = meta["diagnostic_reason"]["member_types"]
            else:
                # A projection itself declares its identity member. Other fields
                # of a specialized DSL are not made traversable by this fact.
                fields = (
                    {projection["key_member"]: {"type": "non-empty-string"}}
                    if projection["key_member"] is not None
                    else None
                )
        item = (
            fields_shape(fields, (authority_path,), law)
            if fields is not None
            else _TemplateSelection(
                "field",
                {"type": "non-empty-string"},
                (authority_path,),
                law,
                authority_path,
            )
        )
        if fields is not None and projection["key_member"] is not None:
            selected = dict(fields)
            key = projection["key_member"]
            children = {
                name: [
                    _TemplateSelection(
                        "field",
                        value,
                        (authority_path, "member", name),
                        law,
                        authority_path if name == key else "",
                    )
                ]
                for name, value in selected.items()
            }
            item = _TemplateSelection("object", children, (authority_path,), law)
        tree[pieces[-1]] = _TemplateSelection("list", [item], (authority_path,))
    package_fields = dict(meta["package_release"]["field_types"])
    package_item = _TemplateSelection(
        "object",
        {
            name: [
                _TemplateSelection(
                    "field",
                    value,
                    ("package", name),
                    law,
                    "namespace" if name == "id" else "",
                )
            ]
            for name, value in package_fields.items()
        },
        ("package",),
    )
    language_tree.setdefault("language", {})["packages"] = _TemplateSelection(
        "list", [package_item], ("package",)
    )
    for member in meta["language_bundle"]["required_members"]:
        if member != "language":
            language_tree[member] = _TemplateSelection(
                "kernel",
                graph["ldb_root"].get(member),
                ("language-bundle", member),
                law,
            )
    language_tree["resources"] = _TemplateSelection(
        "kernel", graph["ldb_root"]["resources"], ("language-bundle", "resources"), law
    )

    def tree_shape(value, owner=()):
        if isinstance(value, _TemplateSelection):
            return value
        return _TemplateSelection(
            "object",
            {
                name: [tree_shape(child, (*owner, name))]
                for name, child in value.items()
            },
            owner,
        )

    language_root = tree_shape(language_tree, ("language-bundle",))
    source_schema = _protocol_schema(kernel, graph, "model-source-package")
    source_role, _, source_pointer = schemas[source_schema["artifact_kind"]]
    source_type = _TemplateSelection(
        "source-schema",
        source_schema["schema"],
        (source_role, source_schema["artifact_kind"]),
        source_pointer + "/schema",
    )
    source_profile = _source_profile(kernel, graph)
    lowerings = [
        v
        for _, v, _ in _authority_path_rows(
            kernel, graph, "language_bundle.language.model_lowerings"
        )
        if v["resolution_profile"] == source_profile["id"]
        and v["id"] == source_profile["model_lowering"]
    ]
    if len(lowerings) != 1:
        raise InventoryRefusal("Template Model result has no unique selected lowering")
    lowering = lowerings[0]
    initial_kinds = {
        lowering[key] for key in ("initial_fact_kind", "structured_initial_fact_kind")
    }
    initial_fields = [
        fields_shape(
            meta["fact"]["field_contracts"][row["field_contract"]],
            ("fact", row["field_contract"]),
            "/meta_format/fact/field_contracts/" + row["field_contract"],
        )
        for row in meta["fact"]["schemas"]
        if row["kind"] in initial_kinds
    ]
    if len(initial_fields) != len(initial_kinds):
        raise InventoryRefusal("Template Source Fact result kinds do not close")

    def origin(result):
        kind = result["origin"]
        if kind == "selected-resolution-requirements":
            paths = _consumer_b_source_role_member_paths(
                source_schema["schema"], "source", "package_requirements"
            )
            if len(paths) != 1 or len(next(iter(paths))) != 1:
                raise InventoryRefusal(
                    "Template requirements have no Source role address"
                )
            member = next(iter(paths))[0]
            schema = source_schema["schema"]["properties"].get(member)
            if not isinstance(schema, dict) or schema.get("type") != "array":
                raise InventoryRefusal(
                    "Template requirements result has no Source list contract"
                )
            return [
                _TemplateSelection(
                    "source-schema",
                    schema,
                    (*source_type.owner, "member", member),
                    _child(source_type.pointer + "/properties", member),
                    "namespace",
                )
            ]
        if kind == "admitted-namespace-selection":
            return [
                _TemplateSelection(
                    "list",
                    [
                        _TemplateSelection(
                            "field",
                            meta["package_release"]["field_types"]["id"],
                            ("namespace",),
                            law,
                            "namespace",
                        )
                    ],
                )
            ]
        if kind == "admitted-initial-source-fact-fields":
            return [_TemplateSelection("list", initial_fields)]
        raise InventoryRefusal("Template result origin is unsupported")

    comparisons = []

    def constraints(selected, target):
        """Classify a Schema literal only when a real inventory relation binds it."""
        comparisons.append((selected, target))
        roles = {shape.nominal for shape in target if shape.nominal}
        if not roles:
            return
        if len(roles) != 1:
            raise InventoryRefusal(
                "Template Schema constant has conflicting inventory owners"
            )
        role = next(iter(roles))
        for shape in selected:
            if shape.representation != "schema":
                continue
            for item, ip in literal_values.get(shape.owner, []):
                if not isinstance(item, str):
                    raise InventoryRefusal("Template inventory literal is not a name")
                if role == "namespace":
                    candidates = [
                        AuthorityToken("namespace", (), p["id"])
                        for p in graph["packages"]
                        if p["id"] == item
                    ]
                else:
                    key = projections[role]["key_member"]
                    token_role, scoped = _declared_target_role(
                        kernel,
                        "language_bundle." + role + ("." + key if key else ""),
                    )
                    candidates = []
                    for owner, definition, _ in _authority_path_rows(
                        kernel, graph, "language_bundle." + role
                    ):
                        if (definition if key is None else definition[key]) != item:
                            continue
                        token_owner: tuple[str, ...] = ()
                        if scoped:
                            if not isinstance(owner, str):
                                raise InventoryRefusal(
                                    "Template inventory declaration has no namespace"
                                )
                            token_owner = (owner,)
                        candidates.append(AuthorityToken(token_role, token_owner, item))
                if not candidates:
                    raise InventoryRefusal(
                        "Template Schema literal has no selected inventory declaration"
                    )
                for token in candidates:
                    emit(token, ip)

    for _, profile, pp in _authority_path_rows(
        kernel, graph, "language_bundle.language.template_admission_profiles"
    ):
        roots.add(pp)
        scope = (profile["id"],)
        roles = {}
        derived = {}
        for member in ("resource_diagnostic", "structural_diagnostic"):
            emit(AuthorityToken("diagnostics", (), profile[member]), pp + "/" + member)
        exhaustion = meta["template_admission"]["resource_accounting"][
            "exhaustion_diagnostic"
        ]
        if profile["resource_diagnostic"] != exhaustion:
            raise InventoryRefusal(
                "Template resource diagnostic differs from its Kernel owner"
            )
        reserved.add(_template_exhaustion_declaration(kernel, graph).token)
        fixed(
            profile["max_steps_path"],
            pp + "/max_steps_path",
            law + "/resource_accounting/limit_path",
        )
        for i, row in enumerate(profile["member_roles"]):
            rp = f"{pp}/member_roles/{i}"
            emit(
                AuthorityToken("template-role", scope, row["role"]),
                rp + "/role",
                "declaration",
            )
            fixed(
                row["cardinality"],
                rp + "/cardinality",
                law + "/role_contract/cardinalities",
            )
            for oi, operation in enumerate(row["required_operations"]):
                fixed(operation, f"{rp}/required_operations/{oi}", law + "/operations")
            schema_role, schema, sp = schemas[row["member_kind"]]
            schema_contract = meta["language_definitions"]["collections"][
                schema_role.rsplit(".", 1)[1]
            ]
            if not _consumer_b_definition_is_closed(schema, schema_contract, language):
                raise InventoryRefusal(
                    "Template member Schema does not close its actual wire contract"
                )
            emit(
                AuthorityToken(schema_role, (), schema["artifact_kind"]),
                rp + "/member_kind",
            )
            if schema.get("protocol_role") == "model-source-package":
                roles[row["role"]] = [source_type]
            elif (
                "wire_schema_identity_domain" in schema
                and "protocol_role" not in schema
            ):
                shape = _TemplateSelection(
                    "schema",
                    schema["schema"],
                    (schema_role, schema["artifact_kind"]),
                    sp + "/schema",
                )
                roles[row["role"]] = [shape]
                if sp not in variable_schemas:
                    variable_schemas[sp] = shape
                    if schema_fields(shape):
                        roots.add(sp)
            else:
                raise InventoryRefusal(
                    "Template member is not a supported standalone Schema owner"
                )

        def selector(value, pointer):
            root, name = value["root"], value["name"]
            fixed(root, pointer + "/root", law + "/selector/roots")
            if root == "role":
                emit(AuthorityToken("template-role", scope, name), pointer + "/name")
                selected = roles[name]
            elif root == "derived":
                emit(AuthorityToken("template-derived", scope, name), pointer + "/name")
                selected = derived[name]
            elif root == "kernel":
                selected = [_TemplateSelection("kernel", kernel, ("kernel",), "")]
            elif root == "language-bundle":
                selected = [language_root]
            elif root == "release":
                raise InventoryRefusal(
                    "Template release selectors await their fixed wrapper inventory"
                )
            else:
                raise InventoryRefusal("Template selector root is unsupported")
            return path(selected, value["path"], pointer + "/path")

        for ji, judgment in enumerate(profile["judgments"]):
            jp = f"{pp}/judgments/{ji}"
            emit(
                AuthorityToken("template-judgment", scope, judgment["id"]),
                jp + "/id",
                "declaration",
            )
            emit(
                AuthorityToken("diagnostics", (), judgment["diagnostic"]),
                jp + "/diagnostic",
            )
            emit(
                AuthorityToken(
                    "kernel.meta_format.template_admission.operations.id",
                    (),
                    judgment["operation"],
                ),
                jp + "/operation",
            )
            primitive = primitives[
                operations[judgment["operation"]]["law"]["primitive"]
            ]
            evaluation = primitive["evaluation"]
            args = judgment["arguments"]
            ap = jp + "/arguments"
            selections = {}
            for member, type_id in primitive["argument_types"].items():
                kind = argument_types[type_id]["kind"]
                value = args[member]
                if kind == "selector":
                    selections[member] = selector(value, ap + "/" + member)
                elif kind == "non-empty-list":
                    selections[member] = [
                        s
                        for i, item in enumerate(value)
                        for s in selector(item, f"{ap}/{member}/{i}")
                    ]
                elif kind == "role-name":
                    emit(
                        AuthorityToken("template-role", scope, value), ap + "/" + member
                    )
                elif kind == "derived-name":
                    emit(
                        AuthorityToken("template-derived", scope, value),
                        ap + "/" + member,
                        "declaration",
                    )
                elif kind == "model-fact-bindings":
                    for bi, binding in enumerate(value):
                        bp = f"{ap}/{member}/{bi}"
                        fixed(
                            binding["source"],
                            bp + "/source",
                            law
                            + "/primitive_spec/primitives/model-source-admission/results",
                        )
                        emit(
                            AuthorityToken(
                                "template-derived", scope, binding["result"]
                            ),
                            bp + "/result",
                            "declaration",
                        )
                        derived[binding["result"]] = origin(
                            primitive["results"][binding["source"]]
                        )
                elif kind == "enum":
                    fixed(
                        value,
                        ap + "/" + member,
                        law + "/primitive_spec/argument_types/" + type_id,
                    )
                elif kind not in {"string", "string-list", "canonical-json"}:
                    raise InventoryRefusal(
                        "Template argument type has no inventory interpretation"
                    )
            kind = evaluation["kind"]
            if kind == "content-identity":
                derived[args[evaluation["result"]]] = [
                    _TemplateSelection("field", {"type": "non-empty-string"})
                ]
            elif kind == "concatenate-selections":
                derived[args[evaluation["result"]]] = [
                    _TemplateSelection("list", selections[evaluation["selectors"]])
                ]
            elif kind == "canonical-inventory":
                constraints(
                    selections[evaluation["selector"]],
                    selections[evaluation["inventory"]],
                )
            elif kind == "canonical-set-relation":
                constraints(
                    selections[evaluation["left"]], selections[evaluation["right"]]
                )
                constraints(
                    selections[evaluation["right"]], selections[evaluation["left"]]
                )
            elif kind in {"canonical-scoped-relation", "canonical-scoped-unique"}:
                for side in (
                    ["source", "target"]
                    if kind == "canonical-scoped-relation"
                    else ["selector"]
                ):
                    for suffix in ("scope_path", "values_path"):
                        key = (
                            side + "_" + suffix
                            if kind == "canonical-scoped-relation"
                            else suffix
                        )
                        member = evaluation[key]
                        selections[key] = path(
                            selections[evaluation[side]],
                            args[member],
                            ap + "/" + member,
                        )
                if kind == "canonical-scoped-relation":
                    for suffix in ("scope_path", "values_path"):
                        constraints(
                            selections["source_" + suffix],
                            selections["target_" + suffix],
                        )
                        constraints(
                            selections["target_" + suffix],
                            selections["source_" + suffix],
                        )
            elif kind in {"closed-int64-interval", "closed-int64-interval-join"}:
                if kind == "closed-int64-interval":
                    interval = selections[evaluation["selector"]]
                else:
                    for relative, base in (
                        ("source_key_path", "source"),
                        ("source_value_path", "source"),
                        ("target_key_path", "target"),
                    ):
                        member = evaluation[relative]
                        path(
                            selections[evaluation[base]],
                            args[member],
                            ap + "/" + member,
                        )
                    member = evaluation["target_interval_path"]
                    interval = path(
                        selections[evaluation["target"]],
                        args[member],
                        ap + "/" + member,
                    )
                for bound in ("minimum_member", "maximum_member"):
                    member = evaluation[bound]
                    step(interval, args[member], ap + "/" + member)
            elif kind == "model-source-vector":
                base = roles[args[evaluation["role"]]]
                for relative in (
                    "pointer_path",
                    "value_path",
                    "diagnostic_path",
                    "expected_path",
                ):
                    member = evaluation[relative]
                    if args[member]:
                        path(base, args[member], ap + "/" + member)
            elif kind not in {"model-source-admission", "canonical-unique"}:
                raise InventoryRefusal(
                    "Template primitive has no inventory interpretation"
                )

    # Exact object equality constrains declared member names across the compared
    # scopes even when a Schema makes a member optional or locates its property
    # under a same-instance applicator. Presence is a separate Schema constraint.
    def object_fields(shape):
        if shape.representation in {"schema", "source-schema"}:
            return {
                member: (
                    _TemplateSelection(
                        shape.representation,
                        child,
                        (*shape.owner, "member", member),
                        _child(sp + "/properties", member),
                    ),
                    field_token(shape, member),
                )
                for value, sp in schema_children(shape)
                for member, child in value.get("properties", {}).items()
            }
        if shape.representation == "field":
            return {
                member: (
                    _TemplateSelection(
                        "field",
                        child,
                        (*shape.owner, "member", member),
                        _child(shape.pointer + "/field_types", member),
                    ),
                    field_token(shape, member),
                )
                for member, child in shape.value.get("field_types", {}).items()
            }
        return {}

    bonds = []

    def compare(left, right):
        lf, rf = object_fields(left), object_fields(right)
        for member in lf.keys() & rf.keys():
            lc, lt = lf[member]
            rc, rt = rf[member]
            bonds.append((lt, rt))
            compare(lc, rc)

    for left, right in comparisons:
        for left_shape in left:
            for right_shape in right:
                compare(left_shape, right_shape)
    emitted_tokens = {row.token for row in rows}
    changed = True
    while changed:
        before = len(reserved)
        for left, right in bonds:
            if (
                left in reserved
                or right in reserved
                or left.role.startswith("kernel.")
                or right.role.startswith("kernel.")
            ):
                reserved.update(t for t in (left, right) if t in emitted_tokens)
        changed = len(reserved) != before
    if any(
        left != right
        and left not in reserved
        and right not in reserved
        and left.role == right.role == "template-field"
        for left, right in bonds
    ):
        raise InventoryRefusal(
            "Template object equality has unclosed cross-Schema field bindings"
        )
    return rows, reserved, roots, set(variable_schemas)


class _Reader:
    def __init__(self, kernel: Mapping[str, Any], graph: Mapping[str, Any]):
        self.kernel = kernel
        self.graph = graph
        self.meta = kernel["meta_format"]
        self.source_projection = _source_projection(kernel, graph)
        self.source_format_role = _source_format_role(kernel, graph)
        self.projections = self.meta["package_release"]["semantic_closure"][
            "projections"
        ]
        uniqueness = next(
            law
            for law in kernel["admission"]["laws"]
            if law["id"] == "kernel.identifiers.unique"
        )
        self.scoped = {
            row["path"].removeprefix("language_bundle.")
            for row in uniqueness["arguments"]["collections"]
            if row.get("scope") == "package"
        }
        self.tokens: set[AuthorityToken] = set()
        self.occurrences: set[TokenOccurrence] = set()
        self.occurrence_positions: set[
            tuple[AuthorityToken, str, str, str, str, str]
        ] = set()
        self.uncovered: set[UncoveredRole] = set()
        self.reserved: set[AuthorityToken] = set()
        self.definitions: dict[tuple[str, str, str], tuple[Any, str]] = {}
        self.types: dict[tuple[str, str], dict[str, Any]] = {}
        _, self.constructors = _typed_context(kernel, graph)
        self.nodes = {row["id"]: row for row in self.meta["runtime_program"]["nodes"]}
        self.kernel_node_tokens = {
            AuthorityToken("kernel.meta_format.runtime_program.nodes", (), name)
            for name in self.nodes
        }
        self.node_laws = {
            row["id"]: f"/meta_format/runtime_program/nodes/{i}"
            for i, row in enumerate(self.meta["runtime_program"]["nodes"])
        }
        self.formula_projections: dict[str, Any] = {}
        self.seeds: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        (
            self.relation_links,
            self.relation_projections,
            self.relation_extensions,
            self.relation_vectors,
        ) = _operation_relation_surfaces(kernel, graph)
        self.operand_contracts: dict[
            tuple[tuple[str, str], tuple[int, ...], str], tuple[dict[str, Any], ...]
        ] = {}

    def gap(self, pointer: str, law: str, reason: str) -> None:
        self.uncovered.add(UncoveredRole(pointer, law, reason))

    def occurrence(
        self,
        token: AuthorityToken,
        pointer: str,
        use: str,
        law: str,
        *,
        location: str = "value",
        projection: str = "",
    ) -> None:
        if token.role != "source-field":
            pointer = _source_pointer(self.source_projection, pointer)
        self.record_occurrence(
            TokenOccurrence(token, pointer, use, law, location, projection)
        )

    def record_occurrence(self, occurrence: TokenOccurrence) -> None:
        """Store an occurrence whose address already belongs to authored bytes."""
        token, pointer, use, location, projection = (
            occurrence.token,
            occurrence.pointer,
            occurrence.use,
            occurrence.location,
            occurrence.projection,
        )
        if not isinstance(token.name, str) or not token.name:
            raise InventoryRefusal(f"invalid token at {pointer}")
        if (
            _occurrence_value(self.graph, occurrence, self.formula_projections)
            != token.name
        ):
            raise InventoryRefusal(
                f"token occurrence does not match bytes at {pointer}"
            )
        self.tokens.add(token)
        # Preserve distinct consuming-law claims on the execution graph. Older
        # authority surfaces have their own projection verifiers and retain
        # their established one-position representation.
        execution_law = (
            occurrence.law
            if pointer.startswith(("/experiment/", "/artifacts/", "/results/"))
            else ""
        )
        position = (token, pointer, use, execution_law, location, projection)
        if position in self.occurrence_positions:
            return
        self.occurrence_positions.add(position)
        self.occurrences.add(occurrence)

    def declared(self, role: str, namespace: str, name: str) -> AuthorityToken:
        if role == "language.nominal_types":
            return AuthorityToken("type", (namespace,), name)
        return AuthorityToken(role, (namespace,) if role in self.scoped else (), name)

    def reference(
        self, role: str, name: str, pointer: str, law: str, namespace: str = ""
    ) -> None:
        token = self.declared(role, namespace, name)
        if token not in self.tokens and token not in self.reserved:
            raise InventoryRefusal(f"unresolved {role} reference at {pointer}: {name}")
        self.occurrence(token, pointer, "reference", law)

    def namespace(self, name: str, pointer: str, use: str, law: str) -> None:
        token = AuthorityToken("namespace", (), name)
        if (
            use == "reference"
            and token not in self.tokens
            and token not in self.reserved
        ):
            raise InventoryRefusal(f"unresolved namespace at {pointer}")
        self.occurrence(token, pointer, use, law)

    def index(self) -> None:
        allowed = {
            "packages",
            "ldb_root",
            "vector_sets",
            "source",
            "experiment",
            "artifacts",
            "results",
        }
        if set(self.graph) - allowed or "packages" not in self.graph:
            raise InventoryRefusal("unknown or missing witness graph surface")
        package_ids = [p["id"] for p in self.graph["packages"]]
        if len(package_ids) != len(set(package_ids)):
            raise InventoryRefusal("duplicate namespace")
        for pi, package in enumerate(self.graph["packages"]):
            pp = f"/packages/{pi}"
            self.namespace(
                package["id"], pp + "/id", "declaration", "/meta_format/package_release"
            )
            if len(package["semantic_closure"]) != len(self.projections):
                raise InventoryRefusal("semantic closure projection count changed")
            for ci, (entry, projection) in enumerate(
                zip(package["semantic_closure"], self.projections, strict=True)
            ):
                if entry["authority_path"] != projection["authority_path"]:
                    raise InventoryRefusal("semantic closure projection order changed")
                role = projection["authority_path"]
                law = f"/meta_format/package_release/semantic_closure/projections/{ci}"
                owners = _at(package, projection["owners_path"].split("."))
                definition_names = []
                for di, definition in enumerate(entry["definitions"]):
                    name = (
                        definition
                        if projection["key_member"] is None
                        else definition[projection["key_member"]]
                    )
                    definition_names.append(name)
                    coordinate = (package["id"], role, name)
                    if coordinate in self.definitions:
                        raise InventoryRefusal("duplicate owned definition")
                    dp = f"{pp}/semantic_closure/{ci}/definitions/{di}"
                    self.definitions[coordinate] = (definition, dp)
                    if role == self.source_format_role:
                        continue
                    kp = (
                        dp
                        if projection["key_member"] is None
                        else _child(dp, projection["key_member"])
                    )
                    token = self.declared(role, package["id"], name)
                    if token in self.tokens:
                        raise InventoryRefusal("duplicate semantic token owner")
                    self.occurrence(token, kp, "declaration", law)
                if sorted(definition_names) != sorted(owners) or len(owners) != len(
                    set(owners)
                ):
                    raise InventoryRefusal("export/definition set mismatch")
                for oi, name in enumerate(owners):
                    if role == self.source_format_role:
                        continue
                    self.occurrence(
                        self.declared(role, package["id"], name),
                        pp
                        + "/"
                        + projection["owners_path"].replace(".", "/")
                        + f"/{oi}",
                        "reference",
                        law,
                    )
            for ti, exported in enumerate(package["exports"]["types"]):
                coordinate = (package["id"], exported["id"])
                if coordinate in self.types:
                    raise InventoryRefusal("duplicate exported Type")
                self.types[coordinate] = exported
                self.occurrence(
                    AuthorityToken("type", coordinate[:1], coordinate[1]),
                    f"{pp}/exports/types/{ti}/id",
                    "declaration",
                    "/meta_format/package_release/type_export",
                )
        if "ldb_root" in self.graph:
            root = self.graph["ldb_root"]
            root_contract = self.meta["language_bundle"]
            if not _consumer_b_definition_is_closed(
                root,
                {
                    "required_members": root_contract["required_members"],
                    "field_types": root_contract["member_types"],
                },
                {},
            ) or not _consumer_b_definition_is_closed(
                root["resources"], root_contract["resources"], {}
            ):
                raise InventoryRefusal(
                    "LDB root does not close its Kernel member contracts"
                )
            if root["kernel_identity"] != self.kernel["content_identity"]:
                raise InventoryRefusal("LDB root does not bind the supplied Kernel")
            descriptors = root["package_descriptors"]
            if not all(
                _consumer_b_definition_is_closed(
                    row, root_contract["package_descriptor"], {}
                )
                for row in descriptors
            ):
                raise InventoryRefusal(
                    "LDB package descriptor does not close its Kernel contract"
                )
            if sorted(row["id"] for row in descriptors) != sorted(package_ids):
                raise InventoryRefusal(
                    "LDB descriptor graph does not exactly cover packages"
                )
            for i, descriptor in enumerate(descriptors):
                self.namespace(
                    descriptor["id"],
                    f"/ldb_root/package_descriptors/{i}/id",
                    "reference",
                    "/meta_format/language_bundle/package_descriptor",
                )
            # All remaining root fields are Kernel format/resource parameters or
            # generated identity/byte framing. Renaming's existing seal consumer
            # rederives that framing; it is not an authored nominal token.
        else:
            self.gap(
                "/ldb_root",
                "/meta_format/language_bundle",
                "exact reachable root descriptor graph was not supplied",
            )
        for vi, vectors in enumerate(self.graph.get("vector_sets", [])):
            vp = f"/vector_sets/{vi}"
            self.namespace(
                vectors["package_id"],
                vp + "/package_id",
                "reference",
                "/meta_format/package_conformance_vector_set",
            )
            definitions = vectors["vector_definitions"]
            if sorted(row["id"] for row in definitions) != sorted(vectors["vectors"]):
                raise InventoryRefusal("vector owner list does not close definitions")
            for di, definition in enumerate(definitions):
                token = self.declared(
                    "vectors", vectors["package_id"], definition["id"]
                )
                if token in self.tokens:
                    raise InventoryRefusal("duplicate vector identity")
                self.occurrence(
                    token,
                    f"{vp}/vector_definitions/{di}/id",
                    "declaration",
                    "/meta_format/package_conformance_vector_set",
                )
            for ri, name in enumerate(vectors["vectors"]):
                self.reference(
                    "vectors",
                    name,
                    f"{vp}/vectors/{ri}",
                    "/meta_format/package_conformance_vector_set",
                )
        for contract in self.meta["runtime_program"]["fixed_value_contracts"].values():
            ref = contract["type"]
            self.reserved.add(AuthorityToken("type", (ref["package"],), ref["id"]))
            self.reserved.add(AuthorityToken("namespace", (), ref["package"]))
        for (owner, role, name), (definition, pointer) in self.definitions.items():
            if role == "language.nominal_types":
                if (owner, name) not in self.types:
                    raise InventoryRefusal("nominal declaration has no exported Type")
                self.types[(owner, name)] = definition
            if role == "language.model_lowerings":
                projection = definition["runtime_projection"]
                collections = {row["id"]: row for row in projection["collections"]}
                for i, seed in enumerate(projection["seeds"]):
                    collection = collections[seed["collection"]]
                    self.seeds.append(
                        (seed, f"{pointer}/runtime_projection/seeds/{i}", collection)
                    )

    def operation_operand_projection(self) -> None:
        self.language = _attached_language(self.kernel, self.graph)
        closed: dict[tuple[str, str], tuple[set[str], set[str], int]] = {}
        subjects = _consumer_b_operation_composition_subjects(
            dict(self.kernel),
            self.language,
            closed_operations=closed,
            operand_contracts=self.operand_contracts,
        )
        expected = {
            (owner, name)
            for owner, role, name in self.definitions
            if role == "language.operations"
        }
        if subjects or set(closed) != expected:
            raise InventoryRefusal("independent Operation composition did not close")

    def typed_links(self, links) -> None:
        for row in links:
            if isinstance(row, UncoveredRole):
                self.uncovered.add(row)
                continue
            if (
                row.use == "reference"
                and row.token.role in {"namespace", "type", "enum-member"}
                and row.token not in self.tokens | self.reserved
            ):
                raise InventoryRefusal(f"unresolved typed reference at {row.pointer}")
            self.occurrence(
                row.token, row.pointer, row.use, row.law, location=row.location
            )

    def type_reference(self, value: Any, pointer: str) -> None:
        self.typed_links(_type_links(value, pointer, self.constructors))

    def structured_definition(self, definition, pointer, owner) -> None:
        self.typed_links(_type_links(definition, pointer, self.constructors, owner))

    def value_contract(self, value: dict[str, Any], pointer: str) -> None:
        if "type" in value:
            self.type_reference(value["type"], pointer + "/type")
        if "type" in value and any(
            value["type"] == contract["type"]
            for contract in self.meta["runtime_program"][
                "fixed_value_contracts"
            ].values()
        ):
            return
        for seed, law, collection in self.seeds:
            path = seed["declaration_path"]
            if len(path) != 1 or path[0] not in value:
                continue
            source = collection["source"]
            if source["kind"] != "semantic-closure":
                continue
            role = source["authority_path"]
            projection = next(
                p for p in self.projections if p["authority_path"] == role
            )
            target = (
                [] if projection["key_member"] is None else [projection["key_member"]]
            )
            if seed["target_path"] != target:
                continue  # This join selects on a value contract, not on an identity.
            self.reference(role, value[path[0]], _child(pointer, path[0]), law)

    def typed_literal(self, value: Any, pointer: str) -> None:
        if not isinstance(value, dict):
            return
        profile = self.meta["literal_typing"]["typed_envelope_profile"]
        tm, vm = profile["type_member"], profile["value_member"]
        if set(value) != {tm, vm}:
            raise InventoryRefusal(f"unknown typed literal shape at {pointer}")
        self.type_reference(value[tm], _child(pointer, tm))
        self.typed_value(value[tm], value[vm], _child(pointer, vm))

    def typed_value(self, reference: dict[str, Any], value: Any, pointer: str) -> None:
        self.typed_links(
            _typed_value_links(reference, value, pointer, self.types, self.constructors)
        )

    def metadata_links(self) -> None:
        for owner, name, pointer, target, law in _declared_metadata_links(
            self.kernel, self.graph
        ):
            role, scoped = _declared_target_role(self.kernel, target)
            if role == self.source_format_role:
                continue
            token = AuthorityToken(
                role, (owner,) if scoped and owner is not None else (), name
            )
            if target.startswith("kernel."):
                declared = {
                    value
                    for _, value, _ in _authority_path_rows(
                        self.kernel, self.graph, target
                    )
                }
                if name not in declared:
                    raise InventoryRefusal(
                        "reference does not name a declared Kernel primitive"
                    )
                self.reserved.add(token)
            elif token not in self.tokens:
                raise InventoryRefusal(
                    f"unresolved declared metadata reference at {pointer}"
                )
            self.occurrence(token, pointer, "reference", law)

    def metadata_definition(
        self, role: str, value: dict[str, Any], pointer: str
    ) -> bool:
        """Close simple declared contracts; unknown nested DSLs remain explicit."""
        if pointer in self.template_roots:
            # The Template pass closes the complete existing program and each
            # actual standalone member Schema, including addressed field names.
            return True
        if pointer in self.template_schemas:
            self.gap(
                pointer,
                "/meta_format/template_admission",
                "Template const/enum data has no declared instance field or item owner",
            )
            return True
        if role == "language.model_lowerings":
            # All remaining fields have their existing typed lowering owner.
            return True
        if role == "language.resolution_profiles":
            contract = self.meta["language_definitions"]["collections"][
                "resolution_profiles"
            ]
            if not _consumer_b_definition_is_closed(value, contract, self.language):
                raise InventoryRefusal(
                    "Resolution profile does not close its Kernel and Source contracts"
                )
            # Source field selectors are closed by _source_address_links;
            # relation bindings, judgment references, and Formula aliases each
            # have their own independent pass. Remaining values are fixed
            # structural policy, resource limits, or identity domains.
            return True
        if role in {
            "language.experiment_metric_judgments",
            "language.experiment_acceptance_judgments",
        }:
            # Complete label paths are owned by the independent judgment pass.
            return True
        if role == "language.replay_comparison_policies":
            # The independent observation-member pass closes the complete
            # policy shape and every actual check reference before this pass.
            return True
        if role == "language.evidence_claim_kinds":
            # The claim pass validates its complete current shape and actual
            # eligibility; local vector names have their claim as lexical owner.
            return True
        if role == "language.artifact_wire_schemas" and value.get("protocol_role") in {
            "build-receipt",
            "resolution-receipt",
            "resolved-model",
            "model-build-command-input",
            "debug-map",
            "package-lock",
            "capability-manifest",
            "model-explanation",
            "experiment-specification",
            "evaluator-capability-manifest",
            "resolved-runtime-profile",
            "metric-dataset",
            "evaluation-run",
            "experiment-verdict",
            "event-trace",
            "snapshot-series",
            "runtime-terminal-audit",
            "rir-semantic-payload",
            "artifact-set-receipt",
            "artifact-set-manifest",
            "publication-index",
            "replay-comparison",
            "template-release",
            "template-instantiate-command-input",
            "template-instantiation-receipt",
        }:
            # The protocol pass checks the physical declaration and producer
            # binding. The Kernel supplies structure; no authored field names
            # or independently configurable schema remain in this definition.
            return True
        if role == "language.artifact_contracts":
            # _wire_protocol_links has closed this definition's shape and its
            # schema binding. Domain separators are direct hashing inputs, not
            # identifiers resolved against another declaration inventory.
            # Member projections still need their addressed wire-field roles.
            if "semantic_identity_projection" in value:
                self.gap(
                    pointer + "/semantic_identity_projection",
                    "/meta_format/language_definitions/collections/artifact_contracts",
                    "semantic projection member-address roles are not yet complete",
                )
            return True
        if role == "language.rules":
            self.rule(value, pointer)
            return True
        if role in {
            "language.quantity.units",
            "language.components",
            "language.constructors",
            "language.conversions",
            "language.structured_operations",
        }:
            contracts = self.meta["language_definitions"]
            if role.startswith("language.quantity."):
                contracts = contracts["quantity"]
            contract = contracts["collections"][role.rsplit(".", 1)[1]]
            if not _consumer_b_definition_is_closed(value, contract, self.language):
                raise InventoryRefusal(
                    "typed metadata does not close its declared Kernel shape"
                )
            if role == "language.quantity.units":
                self.occurrence(
                    AuthorityToken("unit-dimension", (), value["dimension"]),
                    pointer + "/dimension",
                    "declaration",
                    "/meta_format/language_definitions/quantity/collections/units",
                )
            elif role == "language.components":
                self.reference(
                    "language.constructors",
                    value["constructor"],
                    pointer + "/constructor",
                    "/meta_format/language_definitions/collections/components",
                )
                fact_members = {
                    name
                    for fields in self.meta["fact"]["field_contracts"].values()
                    for name in fields
                }
                if not set(value["fields"]) <= fact_members:
                    raise InventoryRefusal(
                        "component field does not address a declared fact member"
                    )
            elif role == "language.constructors":
                rule = value.get("value_rule")
                if not isinstance(rule, dict):
                    raise InventoryRefusal("constructor has no declared value rule")
                if "definition_kind" in rule:
                    for selector, member, area in _constructor_member_selectors(value):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member", (value["id"], area), member
                            ),
                            pointer + "/value_rule/" + selector,
                            "declaration",
                            pointer + "/value_rule",
                        )
                    for i, member in enumerate(value["parameters"]):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member",
                                (value["id"], "definition"),
                                member,
                            ),
                            f"{pointer}/parameters/{i}",
                            "reference",
                            pointer + "/value_rule",
                        )
                    for i, member in enumerate(rule.get("value_members", [])):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member", (value["id"], "ref-value"), member
                            ),
                            f"{pointer}/value_rule/value_members/{i}",
                            "declaration",
                            pointer + "/value_rule",
                        )
                    nested = {"field_name_member", "field_type_member"}
                    members = {
                        item
                        for name, item in rule.items()
                        if name.endswith("_member") and name not in nested
                    }
                    if set(value["parameters"]) != members:
                        raise InventoryRefusal(
                            "constructor parameters do not close its definition member selectors"
                        )
                elif rule["operator"] == "exact-integer":
                    fields = {
                        name
                        for row in self.meta["fact"]["field_contracts"].values()
                        for name in row
                    }
                    if not set(value["parameters"]) <= fields:
                        raise InventoryRefusal(
                            "scalar constructor parameter has no declared fact field"
                        )
                else:
                    raise InventoryRefusal("constructor primitive rule is unclassified")
            elif role == "language.structured_operations":
                self.reference(
                    "language.constructors",
                    value["owner_constructor"],
                    pointer + "/owner_constructor",
                    "/meta_format/language_definitions/collections/structured_operations",
                )
                if "refusal_signal" in value["law"]:
                    signal = value["law"]["refusal_signal"]
                    token = AuthorityToken("diagnostic-signal", ("runtime",), signal)
                    self.occurrence(
                        token,
                        pointer + "/law/refusal_signal",
                        "reference",
                        "/meta_format/runtime_program/nodes",
                    )
                    if any(
                        signal in node.get("refusals", [])
                        for node in self.nodes.values()
                    ):
                        self.reserved.add(token)
            return True
        if role == "diagnostics":
            contract = self.meta["admitted_language_index"]["diagnostic"]
            if (
                set(value) != set(contract["required_members"])
                or value["stage"] not in self.kernel["admission"]["refusal_stages"]
            ):
                raise InventoryRefusal(
                    "diagnostic definition does not match Kernel contract"
                )
            return True
        if role in {
            "language.capabilities",
            "language.model_checks",
            "language.quantity.numeric_policies",
        }:
            parts = role.split(".")
            root = self.meta["language_definitions"]
            if len(parts) == 3:
                root = root[parts[1]]
            contract = root["collections"][parts[-1]]
            required, optional = (
                set(contract["required_members"]),
                set(contract.get("optional_members", [])),
            )
            if not required <= set(value) <= required | optional:
                raise InventoryRefusal("metadata definition has unknown members")
            for name, field in contract["field_types"].items():
                if name in value and (
                    ("const" in field and value[name] != field["const"])
                    or ("enum" in field and value[name] not in field["enum"])
                ):
                    raise InventoryRefusal(
                        "metadata primitive marker does not match Kernel contract"
                    )
            if any(
                _child(pointer + "/extensions", name) not in self.relation_extensions
                for name in value.get("extensions", {})
            ):
                self.gap(
                    pointer + "/extensions",
                    "/meta_format/language_definitions",
                    "metadata extension roles are not yet complete",
                )
            return True
        if role == "language.reasons":
            contract = self.meta["diagnostic_reason"]
            required, optional = (
                set(contract["required_members"]),
                set(contract["optional_members"]),
            )
            if not required <= set(value) <= required | optional:
                raise InventoryRefusal("reason has unknown members")
            self.reference(
                "diagnostics",
                value["diagnostic"],
                pointer + "/diagnostic",
                "/meta_format/diagnostic_reason",
            )
            if value["stage"] not in contract["member_types"]["stage"]["enum"]:
                raise InventoryRefusal("reason has unknown stage")
            predicate = value["predicate"]
            rules = [
                row
                for row in contract["predicate_schemas"]
                if row["operation"] == predicate.get("operation")
            ]
            if len(rules) != 1:
                raise InventoryRefusal("reason predicate has unknown operator")
            rule = rules[0]
            if (
                not set(rule["required_members"])
                <= set(predicate)
                <= set(rule["required_members"]) | set(rule["optional_members"])
            ):
                raise InventoryRefusal("reason predicate has unknown members")
            if "inventory_path" in predicate:
                projection = next(
                    (
                        row
                        for row in self.projections
                        if row["authority_path"] == predicate["inventory_path"]
                    ),
                    None,
                )
                if (
                    projection is None
                    or predicate.get("member_field") != projection["key_member"]
                ):
                    raise InventoryRefusal(
                        "reason predicate does not address a declared inventory key"
                    )
            if "limit_path" in predicate:
                member = predicate["limit_path"].removeprefix("resources.")
                if (
                    not predicate["limit_path"].startswith("resources.")
                    or member not in self.graph["ldb_root"]["resources"]
                ):
                    raise InventoryRefusal(
                        "reason predicate limit is not a declared resource"
                    )
            if "signal" in value:
                token = AuthorityToken(
                    "diagnostic-signal", (value["stage"],), value["signal"]
                )
                self.occurrence(
                    token,
                    pointer + "/signal",
                    "declaration",
                    "/meta_format/diagnostic_reason",
                )
                primitive_signals = {
                    ("runtime", signal)
                    for node in self.meta["runtime_program"]["nodes"]
                    for signal in node.get("refusals", [])
                } | {
                    (root["stage"], root["signal"])
                    for root in self.meta["runtime_projection"]["execution_closure"][
                        "reasons"
                    ]["roots"]
                    if "stage" in root and "signal" in root
                }
                if (value["stage"], value["signal"]) in primitive_signals:
                    self.reserved.add(token)
            return True
        if role == "language.literal_typing_profiles":
            if value.get("source_kind") == "typed-envelope":
                law = self.meta["literal_typing"]["typed_envelope_profile"]
                if (
                    set(value) != {"admission", "id", "source_kind", "value_kind"}
                    or value["admission"] != law["admission"]
                    or value["value_kind"] != law["value_kind"]
                ):
                    raise InventoryRefusal(
                        "typed profile does not match its primitive contract"
                    )
            elif value.get("source_kind") == "integer":
                allowed = {
                    "id",
                    "type",
                    "minimum",
                    "maximum",
                    "representation",
                    "kind",
                    "unit",
                    "domain",
                    "numeric_policy",
                    "source_kind",
                }
                if set(value) != allowed:
                    raise InventoryRefusal("integer profile has unclassified members")
                self.value_contract(value, pointer)
            else:
                raise InventoryRefusal("literal profile source kind is unclassified")
            return True
        if role == "language.runtime_profiles":
            for i, name in enumerate(value["effects"]):
                self.occurrence(
                    AuthorityToken("runtime-effect", (), name),
                    f"{pointer}/effects/{i}",
                    "declaration",
                    "/meta_format/runtime_profile_definition",
                )
            contract = self.meta["runtime_profile_definition"]["active_runtime"]
            if value["evaluation"] == self.meta["runtime_program"]["version"]:
                required, optional = (
                    set(contract["required_members"]),
                    set(contract["optional_members"]),
                )
                if not required <= set(value) <= required | optional:
                    raise InventoryRefusal(
                        "active Runtime profile has unclassified members"
                    )
            elif value["evaluation"] != "declaration-only" or set(value) != {
                "id",
                "numeric_policy",
                "effects",
                "evaluation",
                "resource_bounds",
            }:
                raise InventoryRefusal("Runtime profile evaluation law is unclassified")
            if value.get("extensions"):
                self.gap(
                    pointer + "/extensions",
                    "/meta_format/runtime_profile_definition",
                    "Runtime profile extension roles are not yet complete",
                )
            return True
        return False

    def rule(self, value: dict[str, Any], pointer: str) -> None:
        """Interpret the existing premise-binding and conclusion-term grammar."""
        contract = self.meta["rule"]
        if (
            set(value) != set(contract["required_members"])
            or value["phase"] not in contract["phases"]
        ):
            raise InventoryRefusal("Language rule has an unknown shape or phase")
        law = "/meta_format/binding_substitution"
        self.occurrence(
            AuthorityToken("rule-judgment", (), value["judgment"]),
            pointer + "/judgment",
            "declaration",
            "/meta_format/rule_selection",
        )
        schemas = {
            row["kind"]: self.meta["fact"]["field_contracts"][row["field_contract"]]
            for row in self.meta["fact"]["schemas"]
        }
        bindings: set[str] = set()
        for pi, premise in enumerate(value["premises"]):
            pp = f"{pointer}/premises/{pi}"
            if set(premise) != set(contract["premise_required_members"]):
                raise InventoryRefusal("Language rule premise has unknown members")
            fields = schemas.get(premise["fact_kind"])
            if fields is None or any(
                name not in fields for name in premise["bind"].values()
            ):
                raise InventoryRefusal(
                    "Language rule premise does not address a Kernel fact"
                )
            for name in premise["bind"]:
                bindings.add(name)
                self.occurrence(
                    AuthorityToken("rule-variable", (value["id"],), name),
                    _child(pp + "/bind", name),
                    "declaration",
                    law,
                    location="key",
                )
        conclusion = value["conclusion"]
        if set(conclusion) != set(contract["conclusion_required_members"]):
            raise InventoryRefusal("Language rule conclusion has unknown members")
        fields = schemas.get(conclusion["fact_kind"])
        if fields is None or set(conclusion["fields"]) != set(fields):
            raise InventoryRefusal(
                "Language rule conclusion does not close its Kernel fact"
            )
        constructors = {row["tag"]: row for row in self.meta["term"]["constructors"]}
        for field, term in conclusion["fields"].items():
            tp = _child(pointer + "/conclusion/fields", field)
            shape = constructors.get(term.get("tag"))
            if shape is None or set(term) != set(shape["required_members"]):
                raise InventoryRefusal("Language rule conclusion has an unknown term")
            if term["tag"] == "variable":
                if term["name"] not in bindings:
                    raise InventoryRefusal("Language rule term has an unbound variable")
                self.occurrence(
                    AuthorityToken("rule-variable", (value["id"],), term["name"]),
                    tp + "/name",
                    "reference",
                    law,
                )
            elif term["tag"] == "literal":
                field_contract = fields[field]
                if field_contract.get("type") == "inventory-member":
                    role, scoped = _declared_target_role(
                        self.kernel, "language_bundle." + field_contract["path"]
                    )
                    if scoped:
                        raise InventoryRefusal("unqualified scoped fact literal")
                    self.reference(role, term["value"], tp + "/value", law)
                else:
                    self.gap(
                        tp + "/value",
                        law,
                        "non-inventory fact literal requires its typed role traversal",
                    )

    def rule_chain_links(self) -> None:
        for (_, role, _), (value, pointer) in self.definitions.items():
            if role != "language.model_lowerings":
                continue
            for member in ("rule_chain", "structured_rule_chain"):
                for i, step in enumerate(value[member]):
                    self.occurrence(
                        AuthorityToken("rule-judgment", (), step["judgment"]),
                        f"{pointer}/{member}/{i}/judgment",
                        "reference",
                        "/meta_format/rule_selection",
                    )

    def assignment_policies(self) -> None:
        for (_, role, _), (lowering, pointer) in self.definitions.items():
            if role != "language.model_lowerings":
                continue
            policy = lowering["assignment_policy"]
            pp = pointer + "/assignment_policy"
            scope = (lowering["id"],)
            self.occurrence(
                AuthorityToken("assignment-policy", scope, policy["id"]),
                pp + "/id",
                "declaration",
                "/meta_format/language_definitions/collections/model_lowerings/field_types/assignment_policy",
            )
            for ri, row in enumerate(policy["roles"]):
                rp = f"{pp}/roles/{ri}"
                self.reference(
                    "language.quantity.symbol_roles", row["role"], rp + "/role", pp
                )
                names = [mode["id"] for mode in row["modes"]]
                if len(names) != len(set(names)):
                    raise InventoryRefusal(
                        "duplicate assignment mode within a Symbol role"
                    )
                for mi, mode in enumerate(row["modes"]):
                    self.occurrence(
                        AuthorityToken(
                            "assignment-mode",
                            (*scope, policy["id"], row["role"]),
                            mode["id"],
                        ),
                        f"{rp}/modes/{mi}/id",
                        "declaration",
                        pp,
                    )

    def source_assignment_policy(self) -> tuple[dict[str, Any], str, str]:
        profiles = [
            definition
            for (_, role, _), (definition, _) in self.definitions.items()
            if role == "language.resolution_profiles"
            and definition.get("default") is True
        ]
        if len(profiles) != 1:
            raise InventoryRefusal("Source has no unique default resolution profile")
        owners = [
            (definition, pointer)
            for (_, role, name), (definition, pointer) in self.definitions.items()
            if role == "language.model_lowerings"
            and name == profiles[0]["model_lowering"]
        ]
        if len(owners) != 1:
            raise InventoryRefusal(
                "Source assignment policy has no unique lowering owner"
            )
        lowering, pointer = owners[0]
        return (
            lowering["assignment_policy"],
            pointer + "/assignment_policy",
            lowering["id"],
        )

    def source_value_policy(self, symbol: dict[str, Any], pointer: str) -> None:
        policy, law, lowering = self.source_assignment_policy()
        roles = [row for row in policy["roles"] if row["role"] == symbol["role"]]
        if len(roles) != 1:
            raise InventoryRefusal(
                "Source Symbol role does not select one assignment contract"
            )
        value = symbol["value_policy"]
        modes = [mode for mode in roles[0]["modes"] if mode["id"] == value["mode"]]
        if len(modes) != 1:
            raise InventoryRefusal("Source value policy does not select one mode")
        expected = {"mode"} | (
            {"value"} if modes[0]["value_member"] == "required" else set()
        )
        if set(value) != expected:
            raise InventoryRefusal(
                "Source value policy does not match its mode's closed members"
            )
        self.occurrence(
            AuthorityToken(
                "assignment-mode",
                (lowering, policy["id"], symbol["role"]),
                value["mode"],
            ),
            pointer + "/value_policy/mode",
            "reference",
            law,
        )

    def packages(self) -> None:
        for pi, package in enumerate(self.graph["packages"]):
            pp = f"/packages/{pi}"
            for member in self.meta["package_release"]["nested_members"][
                "dependencies"
            ]:
                for i, name in enumerate(package["dependencies"][member]):
                    self.namespace(
                        name,
                        f"{pp}/dependencies/{member}/{i}",
                        "reference",
                        "/meta_format/package_release/nested_members/dependencies",
                    )
            for i, name in enumerate(package["capabilities"]["required"]):
                self.reference(
                    "language.capabilities",
                    name,
                    f"{pp}/capabilities/required/{i}",
                    "/meta_format/package_release/nested_members/capabilities",
                )
            for ti, exported in enumerate(package["exports"]["types"]):
                self.reference(
                    "language.constructors",
                    exported["constructor"],
                    f"{pp}/exports/types/{ti}/constructor",
                    "/meta_format/package_release/type_export",
                )
        for (owner, role, name), (definition, pointer) in self.definitions.items():
            if role == self.source_format_role:
                continue
            if role == "language.nominal_types":
                self.occurrence(
                    AuthorityToken("type", (owner,), name),
                    pointer + "/id",
                    "reference",
                    "/meta_format/runtime_projection/type_reference_closure",
                )
                self.reference(
                    "language.constructors",
                    definition["constructor"],
                    pointer + "/constructor",
                    "/meta_format/runtime_projection/type_reference_closure",
                )
                self.structured_definition(
                    definition["definition"], pointer + "/definition", (owner, name)
                )
            elif role == "language.operations":
                continue
            elif (
                role == "language.wire_schemas"
                and isinstance(definition, dict)
                and definition.get("protocol_role") == "model-source-package"
            ):
                # _wire_protocol_links closes the definition shape and unique
                # protocol owner; _source_address_links independently closes
                # every renameable physical Source address against the actual
                # schema annotations and consuming judgments.
                if definition != _protocol_schema(
                    self.kernel, self.graph, "model-source-package"
                ):
                    raise InventoryRefusal(
                        "Source wire schema does not match its protocol owner"
                    )
                continue
            elif isinstance(definition, dict) and self.metadata_definition(
                role, definition, pointer
            ):
                continue
            elif isinstance(definition, dict):
                self.gap(
                    pointer,
                    "/meta_format/language_definitions",
                    f"nested {role} roles are not yet traversed",
                )
            else:
                scalar_contracts = self.meta["language_definitions"]["quantity"][
                    "collections"
                ]
                member = role.removeprefix("language.quantity.")
                if (
                    member not in scalar_contracts
                    or scalar_contracts[member].get("item_type") != "non-empty-string"
                ):
                    self.gap(
                        pointer,
                        "/meta_format/language_definitions",
                        "Kernel-fixed versus renameable scalar declaration is not yet classified",
                    )
        for (owner, role, _), (definition, pointer) in self.definitions.items():
            if role == "language.operations":
                self.operation(owner, definition, pointer)

    def known(
        self,
        token: AuthorityToken,
        pointer: str,
        law: str,
        *,
        location: str = "value",
        projection: str = "",
    ) -> None:
        if token not in self.tokens | self.reserved:
            raise InventoryRefusal(f"generated reference has no owner at {pointer}")
        self.occurrence(
            token,
            pointer,
            "reference",
            law,
            location=location,
            projection=projection,
        )

    def kernel_node(self, name: str, pointer: str) -> None:
        token = AuthorityToken("kernel.meta_format.runtime_program.nodes", (), name)
        if token not in self.kernel_node_tokens:
            raise InventoryRefusal(
                f"generated instruction node has no Kernel owner at {pointer}"
            )
        self.reserved.add(token)
        self.occurrence(
            token,
            pointer,
            "reference",
            "/meta_format/runtime_program/nodes",
        )

    def source_coordinate(self, value: Any, pointer: str, law: str) -> None:
        if not isinstance(value, dict) or set(value) != {"model", "module", "name"}:
            raise InventoryRefusal(f"resolved Symbol has an unknown shape at {pointer}")
        model, module, name = value["model"], value["module"], value["name"]
        self.known(AuthorityToken("source-model", (), model), pointer + "/model", law)
        self.known(
            AuthorityToken("source-module", (model,), module),
            pointer + "/module",
            law,
        )
        self.known(
            AuthorityToken("source-symbol", (model, module), name),
            pointer + "/name",
            law,
        )

    def operation_reference(
        self, value: Any, pointer: str, law: str
    ) -> tuple[str, str]:
        if not isinstance(value, dict) or set(value) != {"package", "id"}:
            raise InventoryRefusal(
                f"Operation reference has an unknown shape at {pointer}"
            )
        owner, name = value["package"], value["id"]
        self.known(AuthorityToken("namespace", (), owner), pointer + "/package", law)
        self.known(
            AuthorityToken("language.operations", (owner,), name),
            pointer + "/id",
            law,
        )
        return owner, name

    def artifact_rows(
        self, surface: str, expected_roles: set[str]
    ) -> dict[str, tuple[dict[str, Any], str]]:
        values = self.graph.get(surface)
        if not isinstance(values, dict) or len(values) != len(expected_roles):
            raise InventoryRefusal(
                f"{surface} does not contain its complete member set"
            )
        bindings = {
            role: _artifact_protocol_binding(self.kernel, self.graph, role)
            for role in expected_roles
        }
        roles_by_kind = {kind: role for role, (kind, _, _) in bindings.items()}
        if len(roles_by_kind) != len(bindings):
            raise InventoryRefusal(f"{surface} protocol roles share a producer kind")
        result: dict[str, tuple[dict[str, Any], str]] = {}
        for label, value in values.items():
            pointer = _child("/" + surface, label)
            if not isinstance(value, dict):
                raise InventoryRefusal(f"{surface} member is not an Artifact")
            kind = value.get("artifact_kind")
            if not isinstance(kind, str):
                raise InventoryRefusal(f"{surface} Artifact has no producer kind")
            role = roles_by_kind.get(kind)
            if role is None or role in result:
                raise InventoryRefusal(
                    f"{surface} Artifact kind is missing or duplicated"
                )
            _, schema, contract = bindings[role]
            try:
                jsonschema.Draft202012Validator(schema).validate(value)
            except jsonschema.ValidationError as error:
                raise InventoryRefusal(
                    f"{surface} Artifact does not close its Wire Schema"
                ) from error
            expected_wire_identity = _identity_from_kernel(
                dict(self.kernel), contract["wire_schema_identity_domain"], schema
            )
            expected_content_identity = _identity_from_kernel(
                dict(self.kernel), contract["identity_domain"], value
            )
            if (
                value["wire_schema_identity"] != expected_wire_identity
                or value["content_identity"] != expected_content_identity
            ):
                raise InventoryRefusal(
                    f"{surface} Artifact identity does not close its declared contract"
                )
            self.known(
                AuthorityToken("language.artifact_contracts", (), kind),
                pointer + "/artifact_kind",
                "/meta_format/language_definitions/collections/artifact_contracts",
            )
            result[role] = value, pointer
        if set(result) != expected_roles:
            raise InventoryRefusal(f"{surface} Artifact roles do not close")
        return result

    def experiment_surface(self) -> None:
        value = self.graph.get("experiment")
        if value is None:
            return
        schema = next(
            row["schema"]
            for row in self.language["language"]["artifact_wire_schemas"]
            if row.get("protocol_role") == "experiment-specification"
        )
        try:
            jsonschema.Draft202012Validator(schema).validate(value)
        except jsonschema.ValidationError as error:
            raise InventoryRefusal(
                "Experiment input does not close its projected Schema"
            ) from error
        model_tokens = [token for token in self.tokens if token.role == "source-model"]
        if len(model_tokens) != 1:
            raise InventoryRefusal("Experiment input has no unique Source Model owner")
        model = model_tokens[0].name
        law = "/meta_format/language_definitions/wire_schema_protocol_roles/experiment_input_structure"
        experiment = AuthorityToken("experiment", (), value["id"])
        self.occurrence(experiment, "/experiment/id", "declaration", law)
        self.known(
            AuthorityToken(
                "language.runtime_profiles", (), value["runtime"]["profile"]
            ),
            "/experiment/runtime/profile",
            law,
        )
        self.known(
            AuthorityToken(
                "language.experiment_acceptance_judgments",
                (),
                value["acceptance"]["policy"],
            ),
            "/experiment/acceptance/policy",
            law,
        )
        metric_ids = [metric["id"] for metric in value["metrics"]]
        if len(metric_ids) != len(set(metric_ids)):
            raise InventoryRefusal("Experiment Metric declaration is duplicated")
        for mi, metric in enumerate(value["metrics"]):
            mp = f"/experiment/metrics/{mi}"
            metric_token = AuthorityToken(
                "experiment-metric", (value["id"],), metric["id"]
            )
            self.occurrence(metric_token, mp + "/id", "declaration", law)
            self.known(
                AuthorityToken("language.quantity.units", (), metric["unit"]),
                mp + "/unit",
                law,
            )
            member = metric["observation"]["member"]
            candidates = [
                token
                for token in self.tokens
                if token.role == "source-symbol" and token.name == member
            ]
            if len(candidates) != 1:
                raise InventoryRefusal(
                    "Metric observation member has no unique Symbol owner"
                )
            self.known(candidates[0], mp + "/observation/member", law)
            observation = AuthorityToken(
                "experiment-observation",
                (value["id"], metric["id"]),
                metric["observation"]["name"],
            )
            self.occurrence(observation, mp + "/observation/name", "declaration", law)
            window = AuthorityToken(
                "experiment-window",
                (value["id"], metric["id"]),
                metric["window"]["name"],
            )
            self.occurrence(window, mp + "/window/name", "declaration", law)
        for occurrence in _experiment_input_judgment_links(self.kernel, self.graph):
            self.known(
                occurrence.token,
                occurrence.pointer,
                occurrence.law,
                location=occurrence.location,
                projection=occurrence.projection,
            )
        scenario_ids = [scenario["id"] for scenario in value["scenarios"]]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise InventoryRefusal("Experiment Scenario declaration is duplicated")
        for si, scenario in enumerate(value["scenarios"]):
            sp = f"/experiment/scenarios/{si}"
            scenario_token = AuthorityToken(
                "experiment-scenario", (value["id"],), scenario["id"]
            )
            self.occurrence(scenario_token, sp + "/id", "declaration", law)
            roots: set[str] = set()
            for ai, assignment in enumerate(scenario["assignments"]):
                ap = f"{sp}/assignments/{ai}"
                self.source_coordinate(assignment["target"], ap + "/target", law)
                self.typed_literal(assignment["value"], ap + "/value")
            for ei, event in enumerate(scenario["event_plan"]):
                ep = f"{sp}/event_plan/{ei}"
                root = event["root_event_ref"]
                if root in roots:
                    raise InventoryRefusal(
                        "Experiment root Event reference is duplicated"
                    )
                roots.add(root)
                self.occurrence(
                    AuthorityToken(
                        "experiment-root-event", (value["id"], scenario["id"]), root
                    ),
                    ep + "/root_event_ref",
                    "declaration",
                    law,
                )
                if event["kind"] == "transition-invocation":
                    self.known(
                        AuthorityToken(
                            "source-entrypoint",
                            (model,),
                            event["entrypoint"],
                        ),
                        ep + "/entrypoint",
                        law,
                    )
                    for pi, payload in enumerate(event["payload"]):
                        pp = f"{ep}/payload/{pi}"
                        self.source_coordinate(payload["target"], pp + "/target", law)
                        self.typed_literal(payload["value"], pp + "/value")
                    for ri, reference in enumerate(event.get("event_references", [])):
                        self.known(
                            AuthorityToken(
                                "experiment-root-event",
                                (value["id"], scenario["id"]),
                                reference["root_event_ref"],
                            ),
                            f"{ep}/event_references/{ri}/root_event_ref",
                            law,
                        )
                else:
                    for fi, fact in enumerate(event["facts"]):
                        fp = f"{ep}/facts/{fi}"
                        self.source_coordinate(fact["target"], fp + "/target", law)
                        self.typed_literal(fact["value"], fp + "/value")

    def _projection(
        self, source: str, target: str, projections: list[tuple[str, str]]
    ) -> None:
        if not _consumer_b_canonical_equal(
            _pointer_value(self.graph, source), _pointer_value(self.graph, target)
        ):
            raise InventoryRefusal("generated projection does not equal its owner")
        projections.append((source, target))

    def _project_selected_rows(
        self,
        rows: list[Any],
        pointer: str,
        projections: list[tuple[str, str]],
        *,
        authority_path: str,
        excluded_members: tuple[str, ...] = (),
    ) -> None:
        """Join selected semantic rows to exact package-owned definitions."""
        sources = [
            (definition, source)
            for (_, role, _), (definition, source) in self.definitions.items()
            if role == authority_path
        ]
        for index, row in enumerate(rows):
            target = f"{pointer}/{index}"
            if isinstance(row, dict) and set(row) >= {"package", "definition"}:
                self.known(
                    AuthorityToken("namespace", (), row["package"]),
                    target + "/package",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
                candidates = [
                    (definition, source)
                    for (owner, role, _), (
                        definition,
                        source,
                    ) in self.definitions.items()
                    if owner == row["package"] and role == authority_path
                ]
                matches = [
                    source
                    for definition, source in candidates
                    if _consumer_b_canonical_equal(definition, row["definition"])
                ]
                target += "/definition"
                if not matches and isinstance(row["definition"], dict):
                    reduced = [
                        (definition, source)
                        for definition, source in candidates
                        if isinstance(definition, dict)
                        and set(definition) - set(row["definition"])
                        == set(excluded_members)
                        and all(
                            _consumer_b_canonical_equal(definition[member], value)
                            for member, value in row["definition"].items()
                        )
                    ]
                    if len(reduced) == 1:
                        definition, source = reduced[0]
                        for member in row["definition"]:
                            self._projection(
                                _child(source, member),
                                _child(target, member),
                                projections,
                            )
                        continue
            else:
                matches = [
                    source
                    for definition, source in sources
                    if _consumer_b_canonical_equal(definition, row)
                ]
            if len(matches) != 1:
                raise InventoryRefusal(
                    f"selected semantic row at {target} has no unique exact owner"
                )
            self._projection(matches[0], target, projections)

    def _rir_surfaces(
        self,
        rir: dict[str, Any],
        pointer: str,
        projections: list[tuple[str, str]],
    ) -> None:
        law = (
            "/meta_format/language_definitions/wire_schema_protocol_roles/rir_structure"
        )
        model_tokens = [token for token in self.tokens if token.role == "source-model"]
        if len(model_tokens) != 1:
            raise InventoryRefusal("RIR has no unique Source Model owner")
        model = model_tokens[0].name
        for di, declaration in enumerate(rir["declarations"]):
            dp = f"{pointer}/declarations/{di}"
            self.source_coordinate(
                declaration["resolved_symbol"], dp + "/resolved_symbol", law
            )
            coordinate = declaration["resolved_symbol"]
            self.known(
                AuthorityToken(
                    "source-symbol",
                    (coordinate["model"], coordinate["module"]),
                    declaration["symbol"],
                ),
                dp + "/symbol",
                law,
            )
            self.type_reference(declaration["type_identity"], dp + "/type_identity")
            self.value_contract(declaration, dp)

        def target_contract(value: dict[str, Any], target_pointer: str) -> None:
            target = value["target"]
            self.source_coordinate(target, target_pointer + "/target", law)
            if "value_contract" in value:
                self.value_contract(
                    value["value_contract"], target_pointer + "/value_contract"
                )

        def operation_binding(
            value: dict[str, Any], binding_pointer: str
        ) -> tuple[str, str]:
            coordinate = self.operation_reference(
                value["operation"], binding_pointer + "/operation", law
            )
            for ai, argument in enumerate(value["arguments"]):
                ap = f"{binding_pointer}/arguments/{ai}"
                port = argument["port"]
                owner = self.operation_reference(
                    port["operation"], ap + "/port/operation", law
                )
                self.known(
                    AuthorityToken("operation-port", owner, port["name"]),
                    ap + "/port/name",
                    law,
                )
                operand = argument["operand"]
                if operand["kind"] == "symbol":
                    self.source_coordinate(
                        operand["symbol"], ap + "/operand/symbol", law
                    )
                elif operand["kind"] == "port":
                    self.known(
                        AuthorityToken("operation-port", coordinate, operand["port"]),
                        ap + "/operand/port",
                        law,
                    )
                elif operand["kind"] == "local":
                    self.known(
                        AuthorityToken("operation-local", coordinate, operand["local"]),
                        ap + "/operand/local",
                        law,
                    )
                elif operand["kind"] == "literal":
                    self.typed_literal(operand["value"], ap + "/operand/value")
            closure = value.get("closure", {"effects": [], "refusals": []})
            for effect_index, effect in enumerate(closure["effects"]):
                self.known(
                    AuthorityToken("runtime-effect", (), effect),
                    f"{binding_pointer}/closure/effects/{effect_index}",
                    law,
                )
            for reason_index, reason in enumerate(closure["refusals"]):
                self.known(
                    AuthorityToken("language.reasons", (), reason),
                    f"{binding_pointer}/closure/refusals/{reason_index}",
                    law,
                )
            for oi, outcome in enumerate(value.get("outcomes", [])):
                op = f"{binding_pointer}/outcomes/{oi}"
                self.known(
                    AuthorityToken("operation-outcome", coordinate, outcome["outcome"]),
                    op + "/outcome",
                    law,
                )
                action = outcome["action"]
                if action["kind"] == "propagate":
                    self.known(
                        AuthorityToken(
                            "operation-outcome", coordinate, action["outcome"]
                        ),
                        op + "/action/outcome",
                        law,
                    )
            return coordinate

        for ei, entrypoint in enumerate(rir["entrypoints"]):
            ep = f"{pointer}/entrypoints/{ei}"
            self.known(
                AuthorityToken("source-entrypoint", (model,), entrypoint["id"]),
                ep + "/id",
                law,
            )
            coordinate = operation_binding(entrypoint, ep)
            for member in (
                "scenario_input_contract",
                "event_local_payload_contract",
                "external_fact_contract",
            ):
                for ti, target in enumerate(entrypoint[member]["targets"]):
                    target_contract(target, f"{ep}/{member}/targets/{ti}")
            for effect_index, effect in enumerate(entrypoint["effects"]):
                self.known(
                    AuthorityToken("runtime-effect", (), effect),
                    f"{ep}/effects/{effect_index}",
                    law,
                )
            for reason_index, reason in enumerate(entrypoint["refusals"]):
                self.known(
                    AuthorityToken("language.reasons", (), reason),
                    f"{ep}/refusals/{reason_index}",
                    law,
                )
            result = entrypoint["result"]
            if result["kind"] == "value":
                self.type_reference(result["type"], ep + "/result/type")
            if entrypoint.get("default_outcome") is not None:
                self.known(
                    AuthorityToken(
                        "operation-outcome", coordinate, entrypoint["default_outcome"]
                    ),
                    ep + "/default_outcome",
                    law,
                )
        for ci, call_site in enumerate(rir["call_sites"]):
            cp = f"{pointer}/call_sites/{ci}"
            parent = self.operation_reference(
                call_site["parent_operation"], cp + "/parent_operation", law
            )
            self.known(
                AuthorityToken("operation-site", parent, call_site["site"]),
                cp + "/site",
                law,
            )
            operation_binding(call_site, cp)
        selected = rir["selected_semantics"]
        roles = self.meta["language_definitions"]["wire_schema_protocol_roles"][
            "rir_structure"
        ]["selected_collections"]
        selected_sources: list[tuple[str | None, Any, str]] = []
        for source_member, source_rows in selected.items():
            if source_member in {
                "packages",
                "package_semantic_closures",
            } or not isinstance(source_rows, list):
                continue
            for source_index, source_row in enumerate(source_rows):
                source_pointer = (
                    f"{pointer}/selected_semantics/{source_member}/{source_index}"
                )
                if isinstance(source_row, dict) and set(source_row) >= {
                    "package",
                    "definition",
                }:
                    selected_sources.append(
                        (
                            source_row["package"],
                            source_row["definition"],
                            source_pointer + "/definition",
                        )
                    )
                else:
                    selected_sources.append((None, source_row, source_pointer))
        for member, rows in selected.items():
            if member == "packages":
                for index, row in enumerate(rows):
                    self.known(
                        AuthorityToken("namespace", (), row["id"]),
                        f"{pointer}/selected_semantics/packages/{index}/id",
                        law,
                    )
                continue
            if member == "capability_bindings":
                for index, row in enumerate(rows):
                    rp = f"{pointer}/selected_semantics/capability_bindings/{index}"
                    self.known(
                        AuthorityToken("language.capabilities", (), row["capability"]),
                        rp + "/capability",
                        law,
                    )
                    self.known(
                        AuthorityToken("namespace", (), row["provider_package"]),
                        rp + "/provider_package",
                        law,
                    )
                continue
            if member == "types":
                for index, row in enumerate(rows):
                    rp = f"{pointer}/selected_semantics/types/{index}"
                    self.known(
                        AuthorityToken("namespace", (), row["package"]),
                        rp + "/package",
                        law,
                    )
                    self.known(
                        AuthorityToken("type", (row["package"],), row["id"]),
                        rp + "/id",
                        law,
                    )
                    self.known(
                        AuthorityToken("language.constructors", (), row["constructor"]),
                        rp + "/constructor",
                        law,
                    )
                continue
            if member == "language_rules":
                for index, name in enumerate(rows):
                    self.known(
                        AuthorityToken("language.rules", (), name),
                        f"{pointer}/selected_semantics/language_rules/{index}",
                        law,
                    )
                continue
            if member == "package_semantic_closures":
                for closure_index, closure in enumerate(rows):
                    closure_pointer = (
                        f"{pointer}/selected_semantics/package_semantic_closures/"
                        f"{closure_index}"
                    )
                    package = closure["package"]
                    self.known(
                        AuthorityToken("namespace", (), package),
                        closure_pointer + "/package",
                        law,
                    )
                    for entry_index, entry in enumerate(closure["definitions"]):
                        for definition_index, definition in enumerate(
                            entry["definitions"]
                        ):
                            matches = [
                                source_pointer
                                for source_package, source_value, source_pointer in selected_sources
                                if source_package in {None, package}
                                and _consumer_b_canonical_equal(
                                    source_value, definition
                                )
                            ]
                            if not matches:
                                matches = [
                                    source_pointer
                                    for (
                                        owner,
                                        authority_path,
                                        _,
                                    ), (
                                        source_value,
                                        source_pointer,
                                    ) in self.definitions.items()
                                    if owner == package
                                    and authority_path == entry["authority_path"]
                                    and _consumer_b_canonical_equal(
                                        source_value, definition
                                    )
                                ]
                            if len(matches) != 1:
                                raise InventoryRefusal(
                                    "RIR closure definition at "
                                    f"{closure_pointer}/definitions/{entry_index}/"
                                    f"definitions/{definition_index} has "
                                    f"{len(matches)} selected owners"
                                )
                            self._projection(
                                matches[0],
                                f"{closure_pointer}/definitions/{entry_index}/"
                                f"definitions/{definition_index}",
                                projections,
                            )
                continue
            if isinstance(rows, list) and rows:
                excluded = tuple(roles.get(member, {}).get("excluded_members", []))
                if member not in roles:
                    # Runtime projection companions are owned by separate
                    # Kernel lanes, not RIR selected-collection selectors.
                    if member == "diagnostic_reasons":
                        authority_path = "language.reasons"
                    elif member == "diagnostics":
                        authority_path = "diagnostics"
                    else:
                        raise InventoryRefusal(
                            "RIR selected collection has no declared authority path"
                        )
                else:
                    authority_path = roles[member]["source"]["authority_path"]
                self._project_selected_rows(
                    rows,
                    f"{pointer}/selected_semantics/{member}",
                    projections,
                    authority_path=authority_path,
                    excluded_members=excluded,
                )

    def model_artifact_surface(self) -> None:
        if self.graph.get("artifacts") is None:
            return
        model = self.meta["language_definitions"]["wire_schema_protocol_roles"][
            "model_structure"
        ]
        expected = (set(model["containers"]) - {"model-build-command-input"}) | {
            "rir-semantic-payload"
        }
        rows = self.artifact_rows("artifacts", expected)
        projections: list[tuple[str, str]] = []
        lock, lp = rows["package-lock"]
        package_index = {
            package["id"]: (i, package)
            for i, package in enumerate(self.graph["packages"])
        }
        for i, package in enumerate(lock["packages"]):
            self.known(
                AuthorityToken("namespace", (), package["id"]),
                f"{lp}/packages/{i}/id",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        for i, name in enumerate(lock["root_requirements"]):
            self.known(
                AuthorityToken("namespace", (), name),
                f"{lp}/root_requirements/{i}",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        for i, edge in enumerate(lock["dependency_edges"]):
            for member in ("from_package", "to_package"):
                self.known(
                    AuthorityToken("namespace", (), edge[member]),
                    f"{lp}/dependency_edges/{i}/{member}",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
        for i, closure in enumerate(lock["package_semantic_closures"]):
            owner = closure["package"]
            self.known(
                AuthorityToken("namespace", (), owner),
                f"{lp}/package_semantic_closures/{i}/package",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            pi, package = package_index[owner]
            by_role = {
                entry["authority_path"]: (ci, entry)
                for ci, entry in enumerate(package["semantic_closure"])
            }
            for ci, entry in enumerate(closure["definitions"]):
                source_index, source_entry = by_role[entry["authority_path"]]
                source = f"/packages/{pi}/semantic_closure/{source_index}/definitions"
                target = (
                    f"{lp}/package_semantic_closures/{i}/definitions/{ci}/definitions"
                )
                if _consumer_b_canonical_equal(
                    source_entry["definitions"], entry["definitions"]
                ):
                    self._projection(source, target, projections)
                    continue
                key = next(
                    projection["key_member"]
                    for projection in self.projections
                    if projection["authority_path"] == entry["authority_path"]
                )
                if key is None:
                    raise InventoryRefusal("selected closure scalar projection changed")
                source_rows = {
                    row[key]: (j, row)
                    for j, row in enumerate(source_entry["definitions"])
                }
                for j, row in enumerate(entry["definitions"]):
                    source_j, source_row = source_rows[row[key]]
                    if set(source_row) - set(row) != {"extensions"} or any(
                        not _consumer_b_canonical_equal(source_row[member], value)
                        for member, value in row.items()
                    ):
                        raise InventoryRefusal(
                            "selected closure is not an exact extension-free projection"
                        )
                    for member in row:
                        self._projection(
                            f"{source}/{source_j}/{member}",
                            f"{target}/{j}/{member}",
                            projections,
                        )
        for member in model["namespace_structure"]["shared_collections"]:
            if member not in lock or not isinstance(lock[member], list):
                continue
            if member in {"capability_bindings", "types"}:
                continue
            if member == "language_rules":
                for i, name in enumerate(lock[member]):
                    self.known(
                        AuthorityToken("language.rules", (), name),
                        f"{lp}/{member}/{i}",
                        "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                    )
                continue
            source_contract = self.meta["language_definitions"][
                "wire_schema_protocol_roles"
            ]["rir_structure"]["selected_collections"][member]["source"]
            self._project_selected_rows(
                lock[member],
                f"{lp}/{member}",
                projections,
                authority_path=source_contract["authority_path"],
            )
        for i, row in enumerate(lock["types"]):
            tp = f"{lp}/types/{i}"
            self.known(
                AuthorityToken("namespace", (), row["package"]),
                tp + "/package",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            self.known(
                AuthorityToken("type", (row["package"],), row["id"]),
                tp + "/id",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            self.known(
                AuthorityToken("language.constructors", (), row["constructor"]),
                tp + "/constructor",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        for i, binding in enumerate(lock["capability_bindings"]):
            bp = f"{lp}/capability_bindings/{i}"
            self.known(
                AuthorityToken("language.capabilities", (), binding["capability"]),
                bp + "/capability",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            self.known(
                AuthorityToken("namespace", (), binding["provider_package"]),
                bp + "/provider_package",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        if lock["resolution_profile"]:
            matches = [
                source
                for (owner, role, _), (definition, source) in self.definitions.items()
                if role == "language.resolution_profiles"
                and _consumer_b_canonical_equal(definition, lock["resolution_profile"])
            ]
            if len(matches) != 1:
                raise InventoryRefusal(
                    "Package Lock resolution profile has no exact owner"
                )
            self._projection(matches[0], lp + "/resolution_profile", projections)
        for index, code in enumerate(lock["diagnostics"]):
            self.known(
                AuthorityToken("diagnostics", (), code),
                f"{lp}/diagnostics/{index}",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        self._project_selected_rows(
            lock["diagnostic_reasons"],
            lp + "/diagnostic_reasons",
            projections,
            authority_path="language.reasons",
        )
        for member, value in lock["selected_semantics"].items():
            if member in lock and _consumer_b_canonical_equal(lock[member], value):
                self._projection(
                    lp + "/" + member, lp + "/selected_semantics/" + member, projections
                )
            elif member == "packages":
                for index, row in enumerate(value):
                    self.known(
                        AuthorityToken("namespace", (), row["id"]),
                        f"{lp}/selected_semantics/packages/{index}/id",
                        "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                    )
            elif isinstance(value, list) and value:
                self._project_selected_rows(
                    value,
                    lp + "/selected_semantics/" + member,
                    projections,
                    authority_path=self.meta["language_definitions"][
                        "wire_schema_protocol_roles"
                    ]["rir_structure"]["selected_collections"][member]["source"][
                        "authority_path"
                    ],
                )
        capability, cp = rows["capability-manifest"]
        for index, package in enumerate(capability["packages"]):
            self.known(
                AuthorityToken("namespace", (), package["id"]),
                f"{cp}/packages/{index}/id",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        for member in model["namespace_structure"]["shared_collections"]:
            if member in capability and member in lock:
                self._projection(lp + "/" + member, cp + "/" + member, projections)
        rir, rp = rows["rir-semantic-payload"]
        self._rir_surfaces(rir, rp, projections)
        explanation, ep = rows["model-explanation"]
        for i, row in enumerate(explanation["declaration_explanations"]):
            target = f"{ep}/declaration_explanations/{i}"
            self.source_coordinate(
                row["resolved_symbol"],
                target + "/resolved_symbol",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            self.type_reference(row["type_identity"], target + "/type_identity")
        for i, row in enumerate(explanation["operation_explanations"]):
            target = f"{ep}/operation_explanations/{i}"
            coordinate = self.operation_reference(
                {"package": row["package"], "id": row["id"]},
                target,
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
            for j, effect in enumerate(row["effects"]):
                self.known(
                    AuthorityToken("runtime-effect", (), effect),
                    f"{target}/effects/{j}",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
            for j, reason in enumerate(row["refusals"]):
                self.known(
                    AuthorityToken("language.reasons", (), reason),
                    f"{target}/refusals/{j}",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
            for j, node in enumerate(row["control_nodes"]):
                self.kernel_node(node, f"{target}/control_nodes/{j}")
            for j, stream in enumerate(row["rng_streams"]):
                self.known(
                    AuthorityToken("named-stream", coordinate, stream),
                    f"{target}/rng_streams/{j}",
                    "/meta_format/runtime_program/named_rng",
                )
            for j, outcome in enumerate(row["outcomes"]):
                self.known(
                    AuthorityToken("operation-outcome", coordinate, outcome["id"]),
                    f"{target}/outcomes/{j}/id",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
            if row["default_outcome"] is not None:
                self.known(
                    AuthorityToken(
                        "operation-outcome", coordinate, row["default_outcome"]
                    ),
                    target + "/default_outcome",
                    "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                )
        debug, dp = rows["debug-map"]
        key_occurrences = {
            row.pointer: row.token
            for row in self.occurrences
            if row.location == "key" and row.token.role == "source-field"
        }
        for i, entry in enumerate(debug["entries"]):
            source_pointer = entry["source_pointer"]
            segments = _json_pointer_segments(source_pointer)
            current = "/source"
            for index, segment in enumerate(segments):
                current = _child(current, segment)
                token = key_occurrences.get(current)
                if token is not None:
                    self.known(
                        token,
                        f"{dp}/entries/{i}/source_pointer",
                        "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
                        location="json-pointer",
                        projection=str(index),
                    )
        receipt, receipt_pointer = rows["resolution-receipt"]
        self.known(
            AuthorityToken(
                "language.resolution_profiles", (), receipt["resolution_profile"]
            ),
            receipt_pointer + "/resolution_profile",
            "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
        )
        for index, code in enumerate(receipt["diagnostics"]):
            self.known(
                AuthorityToken("diagnostics", (), code),
                f"{receipt_pointer}/diagnostics/{index}",
                "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure",
            )
        for row in _close_projection_occurrences(
            self.graph, self.occurrences, projections
        ):
            self.occurrence(
                row.token,
                row.pointer,
                row.use,
                row.law,
                location=row.location,
                projection=row.projection,
            )

    def runtime_result_surface(self) -> None:
        if self.graph.get("results") is None:
            return
        if self.graph.get("experiment") is None or self.graph.get("artifacts") is None:
            raise InventoryRefusal(
                "Runtime results need their Experiment and Model owners"
            )
        protocols = self.meta["language_definitions"]["wire_schema_protocol_roles"]
        base_kinds = {
            "resolved-runtime-profile",
            "evaluator-capability-manifest",
            "event-trace",
            "snapshot-series",
            "metric-dataset",
        }
        actual_kinds = {
            value.get("artifact_kind") for value in self.graph["results"].values()
        }
        primary_roles = {
            role
            for role in protocols["metric_outcome_structure"]["outcomes"]
            if _artifact_protocol_binding(self.kernel, self.graph, role)[0]
            in actual_kinds
        }
        if len(primary_roles) != 1:
            raise InventoryRefusal(
                "Runtime output protocol does not select one primary outcome"
            )
        expected = base_kinds | primary_roles
        rows = self.artifact_rows("results", expected)
        experiment = self.graph["experiment"]
        exp_id = experiment["id"]
        artifacts = self.graph["artifacts"]
        rir_kind = _artifact_protocol_binding(
            self.kernel, self.graph, "rir-semantic-payload"
        )[0]
        rir = next(
            value
            for value in artifacts.values()
            if value.get("artifact_kind") == rir_kind
        )
        model_tokens = [token for token in self.tokens if token.role == "source-model"]
        if len(model_tokens) != 1:
            raise InventoryRefusal("Runtime result has no unique Model owner")
        model = model_tokens[0].name
        entrypoints = {row["id"]: row for row in rir["entrypoints"]}
        operations = {
            (row["package"], row["definition"]["id"]): row["definition"]
            for row in rir["selected_semantics"]["operations"]
        }
        runtime_law = rir["selected_semantics"]["execution_laws"]["runtime_program"]
        node_operators = {
            node["id"]: node["semantics"]["operator"] for node in runtime_law["nodes"]
        }
        schedule_domain = runtime_law["scheduler"]["call_site_identity"]["schedule"][
            "domain"
        ]
        declarations = {row["symbol"]: row for row in rir["declarations"]}
        if len(declarations) != len(rir["declarations"]):
            raise InventoryRefusal("Runtime Symbol display names are ambiguous")
        protocol_law = "/meta_format/language_definitions/wire_schema_protocol_roles"
        law = protocol_law + "/trace_structure"

        def scenario_token(name: str) -> AuthorityToken:
            return AuthorityToken("experiment-scenario", (exp_id,), name)

        def metric_token(name: str) -> AuthorityToken:
            return AuthorityToken("experiment-metric", (exp_id,), name)

        metric_definitions = {row["id"]: row for row in experiment["metrics"]}

        def metric_selector(
            metric_name: str, path: tuple[str, ...], value: str, pointer: str
        ) -> None:
            metric = metric_definitions.get(metric_name)
            if metric is None or _at(metric, path) != value:
                raise InventoryRefusal(
                    "Runtime Metric selector disagrees with its Experiment owner"
                )
            self.known(
                AuthorityToken("experiment-metric-label", path, value),
                pointer,
                law,
            )

        def root_token(scenario: str, name: str) -> AuthorityToken:
            return AuthorityToken("experiment-root-event", (exp_id, scenario), name)

        def symbol_name(name: str, pointer: str) -> None:
            declaration = declarations.get(name)
            if declaration is None:
                raise InventoryRefusal("Runtime value name has no RIR declaration")
            coordinate = declaration["resolved_symbol"]
            self.known(
                AuthorityToken(
                    "source-symbol", (coordinate["model"], coordinate["module"]), name
                ),
                pointer,
                law,
            )

        def named_value(row: dict[str, Any], pointer: str) -> None:
            symbol_name(row["name"], pointer + "/name")
            if "value" in row:
                self.typed_literal(row["value"], pointer + "/value")

        def root_map(value: list[dict[str, Any]], pointer: str) -> None:
            for i, row in enumerate(value):
                rp = f"{pointer}/{i}"
                self.known(scenario_token(row["scenario"]), rp + "/scenario", law)
                self.known(
                    root_token(row["scenario"], row["root_event_ref"]),
                    rp + "/root_event_ref",
                    law,
                )

        def terminal_statuses(value: list[dict[str, Any]], pointer: str) -> None:
            for i, row in enumerate(value):
                self.known(
                    scenario_token(row["scenario"]), f"{pointer}/{i}/scenario", law
                )

        call_sites = {
            row["identity"]: (
                (row["parent_operation"]["package"], row["parent_operation"]["id"]),
                row["site"],
                (row["operation"]["package"], row["operation"]["id"]),
            )
            for row in rir["call_sites"]
        }

        def call_path(value: str, pointer: str) -> tuple[str, str]:
            segments = _call_path_segments(value)
            root = segments[0]
            entrypoint = entrypoints.get(root)
            if entrypoint is None:
                raise InventoryRefusal("Runtime call path has no Entry Point root")
            self.known(
                AuthorityToken("source-entrypoint", (model,), root),
                pointer,
                law,
                location="call-path",
                projection="0",
            )
            parent = (entrypoint["operation"]["package"], entrypoint["operation"]["id"])
            for index, segment in enumerate(segments[1:], start=1):
                if re.fullmatch(r"@[0-9]+", segment):
                    continue
                candidates = [
                    row
                    for row in call_sites.values()
                    if row[0] == parent and row[1] == segment
                ]
                if len(candidates) != 1:
                    raise InventoryRefusal("Runtime call path site is unresolved")
                self.known(
                    AuthorityToken("operation-site", parent, segment),
                    pointer,
                    law,
                    location="call-path",
                    projection=str(index),
                )
                parent = candidates[0][2]
            return parent

        def event_spec(value: dict[str, Any], pointer: str) -> None:
            kind = value["kind"]
            if kind == "external-input":
                self.known(
                    root_token(current_scenario, value["root_event_ref"]),
                    pointer + "/root_event_ref",
                    law,
                )
                for i, fact in enumerate(value["facts"]):
                    fp = f"{pointer}/facts/{i}"
                    self.source_coordinate(fact["target"], fp + "/target", law)
                    self.typed_literal(fact["value"], fp + "/value")
            elif kind == "transition-invocation":
                self.known(
                    AuthorityToken("source-entrypoint", (model,), value["entrypoint"]),
                    pointer + "/entrypoint",
                    law,
                )
                self.known(
                    root_token(current_scenario, value["root_event_ref"]),
                    pointer + "/root_event_ref",
                    law,
                )
                for i, payload in enumerate(value["payload"]):
                    pp = f"{pointer}/payload/{i}"
                    self.source_coordinate(payload["target"], pp + "/target", law)
                    self.typed_literal(payload["value"], pp + "/value")
            elif kind == "scheduled-transition":
                coordinate = self.operation_reference(
                    value["operation"], pointer + "/operation", law
                )
                for i, argument in enumerate(value["arguments"]):
                    ap = f"{pointer}/arguments/{i}"
                    symbol_name(argument["name"], ap + "/name")
                    self.typed_literal(argument["value"], ap + "/value")
                for i, reference in enumerate(value["state_references"]):
                    rp = f"{pointer}/state_references/{i}"
                    symbol_name(reference["name"], rp + "/name")
                    self.source_coordinate(reference["target"], rp + "/target", law)
                if coordinate not in operations:
                    raise InventoryRefusal("scheduled Operation has no selected owner")
            elif kind != "observation":
                raise InventoryRefusal("Runtime Event Spec kind is unclassified")

        trace, tp = rows["event-trace"]
        current_scenario = trace["scenario"]
        schedule_provenance: dict[str, tuple[str, str, tuple[str, str]]] = {}
        for parent_event in trace["events"]:
            for schedule in parent_event["schedules"]:
                child = schedule["event_id"]
                if child in schedule_provenance:
                    raise InventoryRefusal(
                        "scheduled child Event provenance is ambiguous"
                    )
                schedule_provenance[child] = (
                    parent_event["event_id"],
                    schedule["call_site_identity"],
                    (schedule["operation"]["package"], schedule["operation"]["id"]),
                )
        self.known(scenario_token(current_scenario), tp + "/scenario", law)
        root_map(trace["root_event_map"], tp + "/root_event_map")
        terminal_statuses(trace["terminal_statuses"], tp + "/terminal_statuses")
        for i, event in enumerate(trace["events"]):
            ep = f"{tp}/events/{i}"
            event_operation: tuple[str, str] | None = None
            execution_paths: set[str] = set()
            if event.get("root_event_ref") is not None:
                self.known(
                    root_token(current_scenario, event["root_event_ref"]),
                    ep + "/root_event_ref",
                    law,
                )
            if event.get("entrypoint") is not None:
                execution_paths.add(event["entrypoint"]["id"])
                self.known(
                    AuthorityToken(
                        "source-entrypoint", (model,), event["entrypoint"]["id"]
                    ),
                    ep + "/entrypoint/id",
                    law,
                )
            if event.get("operation") is not None:
                if event.get("entrypoint") is not None:
                    entrypoint = entrypoints[event["entrypoint"]["id"]]
                    coordinate = (
                        entrypoint["operation"]["package"],
                        entrypoint["operation"]["id"],
                    )
                    if event["operation"] != coordinate[1]:
                        raise InventoryRefusal(
                            "Trace Operation disagrees with its RIR Entry Point owner"
                        )
                else:
                    provenance = schedule_provenance.get(event["event_id"])
                    if (
                        provenance is None
                        or event.get("parent_event_id") != provenance[0]
                        or event.get("schedule_call_site_identity") != provenance[1]
                    ):
                        raise InventoryRefusal(
                            "Trace Operation has no scheduled Event provenance owner"
                        )
                    coordinate = provenance[2]
                    if (
                        coordinate not in operations
                        or event["operation"] != coordinate[1]
                    ):
                        raise InventoryRefusal(
                            "scheduled Trace Operation disagrees with its RIR owner"
                        )
                self.known(
                    AuthorityToken(
                        "language.operations", coordinate[:1], coordinate[1]
                    ),
                    ep + "/operation",
                    law,
                )
                event_operation = coordinate
            if event_operation is not None:
                self.known(
                    AuthorityToken(
                        "operation-outcome",
                        event_operation,
                        event["outcome"]["id"],
                    ),
                    ep + "/outcome/id",
                    law,
                )
            for j, row in enumerate(event["facts"]):
                named_value(row, f"{ep}/facts/{j}")
            for member in ("state_before", "state_after"):
                for j, row in enumerate(event[member]):
                    named_value(row, f"{ep}/{member}/{j}")
            for j, call in enumerate(event["calls"]):
                cp = f"{ep}/calls/{j}"
                coordinate = self.operation_reference(
                    call["operation"], cp + "/operation", law
                )
                site = call_sites.get(call["call_site_identity"])
                if site is None or site[2] != coordinate:
                    raise InventoryRefusal("Trace call site has no RIR owner")
                segments = _call_path_segments(call["site"])
                if segments != [site[0][1], site[1]]:
                    raise InventoryRefusal(
                        "Trace call site label disagrees with its RIR owner"
                    )
                execution_paths.add(call["site"])
                self.known(
                    AuthorityToken("language.operations", site[0][:1], site[0][1]),
                    cp + "/site",
                    law,
                    location="call-path",
                    projection="0",
                )
                self.known(
                    AuthorityToken("operation-site", site[0], site[1]),
                    cp + "/site",
                    law,
                    location="call-path",
                    projection="1",
                )
                self.known(
                    AuthorityToken(
                        "operation-outcome", coordinate, call["outcome"]["id"]
                    ),
                    cp + "/outcome/id",
                    law,
                )
            for j, schedule in enumerate(event["schedules"]):
                sp = f"{ep}/schedules/{j}"
                scheduled = self.operation_reference(
                    schedule["operation"], sp + "/operation", law
                )
                if scheduled not in operations:
                    raise InventoryRefusal(
                        "scheduled child Operation has no selected RIR owner"
                    )
                if schedule["call_path"] not in execution_paths:
                    raise InventoryRefusal(
                        "scheduled call path has no selected execution owner"
                    )
                parent = call_path(schedule["call_path"], sp + "/call_path")
                if schedule["parent_operation"] != parent[1]:
                    raise InventoryRefusal(
                        "scheduled parent Operation disagrees with its call path"
                    )
                parent_definition = operations.get(parent)
                if parent_definition is None:
                    raise InventoryRefusal("scheduled parent has no selected RIR owner")

                def selected_schedule_instructions(
                    instructions: list[dict[str, Any]],
                ) -> list[dict[str, Any]]:
                    found: list[dict[str, Any]] = []
                    for instruction in instructions:
                        operator = node_operators.get(instruction["node"])
                        if operator == "schedule-operation":
                            found.append(instruction)
                        elif operator == "guarded-outcome-block":
                            found.extend(
                                selected_schedule_instructions(instruction["body"])
                            )
                    return found

                matches = [
                    instruction
                    for instruction in selected_schedule_instructions(
                        parent_definition["body"]
                    )
                    if instruction["operation"] == schedule["operation"]
                    and instruction["logical_time"]
                    == schedule["ordering_key"]["logical_time"]
                    and instruction["priority"] == schedule["ordering_key"]["priority"]
                    and _identity_from_kernel(
                        dict(self.kernel),
                        schedule_domain,
                        {
                            "parent_event_id": event["event_id"],
                            "parent_operation": parent[1],
                            "site": instruction["site"],
                            "operation": instruction["operation"],
                        },
                    )
                    == schedule["call_site_identity"]
                ]
                if len(matches) != 1:
                    raise InventoryRefusal(
                        "scheduled child has no exact selected instruction owner"
                    )
                self.known(
                    AuthorityToken("language.operations", parent[:1], parent[1]),
                    sp + "/parent_operation",
                    law,
                )
                for k, row in enumerate(schedule["arguments"]):
                    named_value(row, f"{sp}/arguments/{k}")
                for k, row in enumerate(schedule["state_references"]):
                    rp = f"{sp}/state_references/{k}"
                    symbol_name(row["name"], rp + "/name")
                    self.source_coordinate(row["target"], rp + "/target", law)
            observation = event.get("observation")
            if observation is not None:
                self.known(
                    metric_token(observation["metric"]), ep + "/observation/metric", law
                )
                self.known(
                    AuthorityToken(
                        "experiment-window",
                        (exp_id, observation["metric"]),
                        observation["window"]["name"],
                    ),
                    ep + "/observation/window/name",
                    law,
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
                self.known(
                    AuthorityToken(
                        "named-stream",
                        event_operation,
                        draw["stream"],
                    ),
                    f"{ep}/rng_draws/{j}/stream",
                    law,
                )

        law = protocol_law + "/runtime_evidence_structure"
        series, sp = rows["snapshot-series"]
        self.known(scenario_token(series["scenario"]), sp + "/scenario", law)
        root_map(series["root_event_map"], sp + "/root_event_map")
        for i, record in enumerate(series["event_catalog"]):
            rp = f"{sp}/event_catalog/{i}"
            self.known(scenario_token(record["scenario"]), rp + "/scenario", law)
            current_scenario = record["scenario"]
            event_spec(record["event_spec"], rp + "/event_spec")
        for i, snapshot in enumerate(series["snapshots"]):
            pp = f"{sp}/snapshots/{i}"
            self.known(scenario_token(snapshot["scenario"]), pp + "/scenario", law)
            self.known(
                scenario_token(snapshot["scenario"]),
                pp + "/name",
                law,
                location="snapshot-name",
            )
            for j, row in enumerate(snapshot["values"]):
                named_value(row, f"{pp}/values/{j}")

        law = protocol_law + "/metric_outcome_structure"
        dataset, dp = rows["metric-dataset"]
        for i, sample in enumerate(dataset["samples"]):
            pp = f"{dp}/samples/{i}"
            self.known(metric_token(sample["metric"]), pp + "/metric", law)
            metric_selector(
                sample["metric"],
                ("observation", "source"),
                sample["source"],
                pp + "/source",
            )
            metric_selector(
                sample["metric"],
                ("observation", "source"),
                sample["provenance"]["observation_source"],
                pp + "/provenance/observation_source",
            )
            self.known(scenario_token(sample["scenario"]), pp + "/scenario", law)
            if sample["replication_identity"] != sample["scenario"]:
                raise InventoryRefusal(
                    "scenario replication identity disagrees with its owner"
                )
            self.known(
                scenario_token(sample["replication_identity"]),
                pp + "/replication_identity",
                law,
            )
            self.known(
                AuthorityToken("language.quantity.units", (), sample["unit"]),
                pp + "/unit",
                law,
            )
            self.known(
                AuthorityToken(
                    "experiment-window", (exp_id, sample["metric"]), sample["window"]
                ),
                pp + "/window",
                law,
            )
            symbol_name(sample["member"], pp + "/member")
            self.known(
                scenario_token(sample["provenance"]["scenario"]),
                pp + "/provenance/scenario",
                law,
            )
            self.known(
                AuthorityToken(
                    "experiment-observation",
                    (exp_id, sample["metric"]),
                    sample["provenance"]["observation_name"],
                ),
                pp + "/provenance/observation_name",
                law,
            )
            symbol_name(
                sample["provenance"]["observation_member"],
                pp + "/provenance/observation_member",
            )

        law = protocol_law + "/runtime_capability_structure"
        profile, pp = rows["resolved-runtime-profile"]
        selected_profile = profile["runtime_profile"]
        matches = [
            source
            for (owner, role, _), (definition, source) in self.definitions.items()
            if role == "language.runtime_profiles"
            and _consumer_b_canonical_equal(definition, selected_profile)
        ]
        if len(matches) != 1:
            raise InventoryRefusal("resolved Runtime profile has no exact owner")
        projections: list[tuple[str, str]] = []
        self._projection(matches[0], pp + "/runtime_profile", projections)
        judgments = profile["experiment_judgments"]
        self.known(
            AuthorityToken(
                "language.experiment_acceptance_judgments",
                (),
                judgments["acceptance"]["id"],
            ),
            pp + "/experiment_judgments/acceptance/id",
            law,
        )
        for i, row in enumerate(judgments["metrics"]):
            jp = f"{pp}/experiment_judgments/metrics/{i}"
            self.known(metric_token(row["metric"]), jp + "/metric", law)
            matches = [
                source
                for (owner, role, _), (definition, source) in self.definitions.items()
                if role == "language.experiment_metric_judgments"
                and _consumer_b_canonical_equal(definition, row["judgment"])
            ]
            if len(matches) != 1:
                raise InventoryRefusal("resolved Metric judgment has no exact owner")
            self._projection(matches[0], jp + "/judgment", projections)

        manifest, mp = rows["evaluator-capability-manifest"]
        for i, effect in enumerate(manifest["effects"]):
            self.known(
                AuthorityToken("runtime-effect", (), effect), f"{mp}/effects/{i}", law
            )
        for i, policy in enumerate(manifest["numeric_policies"]):
            self.known(
                AuthorityToken("language.quantity.numeric_policies", (), policy),
                f"{mp}/numeric_policies/{i}",
                law,
            )
        for i, profile_name in enumerate(manifest["runtime_profiles"]):
            self.known(
                AuthorityToken("language.runtime_profiles", (), profile_name),
                f"{mp}/runtime_profiles/{i}",
                law,
            )
        for i, node in enumerate(manifest["instruction_nodes"]):
            self.kernel_node(node, f"{mp}/instruction_nodes/{i}")

        primary_role = next(iter(primary_roles))
        law = protocol_law + "/metric_outcome_structure"
        primary, primary_pointer = rows[primary_role]
        root_map(primary["root_event_map"], primary_pointer + "/root_event_map")
        terminal_statuses(
            primary["terminal_statuses"], primary_pointer + "/terminal_statuses"
        )
        for i, name in enumerate(primary.get("failed_metrics", [])):
            self.known(metric_token(name), f"{primary_pointer}/failed_metrics/{i}", law)
        self._projection(tp + "/root_event_map", sp + "/root_event_map", projections)
        self._projection(
            tp + "/root_event_map", primary_pointer + "/root_event_map", projections
        )
        self._projection(
            tp + "/terminal_statuses",
            primary_pointer + "/terminal_statuses",
            projections,
        )
        for row in _close_projection_occurrences(
            self.graph, self.occurrences, projections
        ):
            self.occurrence(
                row.token,
                row.pointer,
                row.use,
                row.law,
                location=row.location,
                projection=row.projection,
            )

    def contract_vectors(self) -> None:
        handled = (
            self.relation_vectors
            | self.scheduler_rule_roots
            | {
                pointer
                for _, _, pointer in _reason_vector_rows(self.kernel, self.graph)
            }
        )
        handled.update(self.model_vector_roots)
        handled.update(
            pointer for _, pointer in _replay_vector_rows(self.kernel, self.graph)
        )
        handled.update(
            pointer
            for *_, pointer in _operation_vector_rows(self.kernel, self.graph)
            if not any(
                gap.pointer == pointer or gap.pointer.startswith(pointer + "/")
                for gap in self.uncovered
            )
        )
        handled.update(
            pointer
            for _, _, pointer in _value_vector_rows(self.kernel, self.graph)
            if not any(
                gap.pointer == pointer or gap.pointer.startswith(pointer + "/")
                for gap in self.uncovered
            )
        )
        for source, target, vector, operation in _contract_vector_projections(
            self.kernel, self.graph
        ):
            law = "/meta_format/package_vector"
            if operation is not None:
                self.occurrence(operation, vector + "/operation", "reference", law)
            source_occurrences = tuple(
                o
                for o in self.occurrences
                if (o.pointer == source and o.location != "key")
                or o.pointer.startswith(source + "/")
            )
            for occurrence in source_occurrences:
                self.occurrence(
                    occurrence.token,
                    target + occurrence.pointer.removeprefix(source),
                    "reference",
                    law,
                    location=occurrence.location,
                    projection=occurrence.projection,
                )
            if any(
                gap.pointer == source
                or gap.pointer.startswith(source + "/")
                or source.startswith(gap.pointer + "/")
                for gap in self.uncovered
            ):
                self.gap(
                    vector,
                    law,
                    "projected authored subtree still has unclassified roles",
                )
            else:
                handled.add(vector)
        remaining = {
            vector.get("kind", "source-or-rule-or-reason")
            for vi, vector_set in enumerate(self.graph.get("vector_sets", []))
            for di, vector in enumerate(vector_set["vector_definitions"])
            if f"/vector_sets/{vi}/vector_definitions/{di}" not in handled
        }
        if remaining:
            self.gap(
                "/vector_sets",
                "/meta_format/package_vector",
                "remaining vector families: " + ", ".join(sorted(remaining)),
            )

    def operand(
        self,
        value: Any,
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
        law: str,
    ) -> None:
        if isinstance(value, str):
            token = bindings.get(value)
            if token is None:
                raise InventoryRefusal(
                    f"unresolved lexical operand at {pointer}: {value}"
                )
            self.occurrence(token, pointer, "reference", law)
        elif isinstance(value, dict):
            kind = value.get("kind")
            if kind in {"port", "local"}:
                member = kind
                self.operand(
                    value[member], _child(pointer, member), scope, bindings, law
                )
            elif kind == "literal":
                self.typed_literal(value["value"], pointer + "/value")
            else:
                self.gap(
                    pointer, law, "expression operand traversal is not yet complete"
                )
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise InventoryRefusal(f"unknown lexical operand shape at {pointer}")

    def operation(self, owner: str, operation: dict[str, Any], pointer: str) -> None:
        if not _consumer_b_definition_is_closed(
            operation,
            self.meta["language_definitions"]["collections"]["operations"],
            self.language,
        ):
            raise InventoryRefusal("Operation does not close its Kernel contract")
        scope = (owner, operation["id"])
        law = "/meta_format/runtime_program/invocation_contract"
        bindings: dict[str, AuthorityToken] = {}
        for i, port in enumerate(operation["inputs"]):
            token = AuthorityToken("operation-port", scope, port["id"])
            if port["id"] in bindings:
                raise InventoryRefusal("duplicate Operation port")
            bindings[port["id"]] = token
            self.occurrence(token, f"{pointer}/inputs/{i}/id", "declaration", law)
            self.value_contract(port, f"{pointer}/inputs/{i}")
        if isinstance(operation.get("result"), dict):
            result = operation["result"]
            self.occurrence(
                AuthorityToken("operation-result", scope, result["id"]),
                pointer + "/result/id",
                "declaration",
                law,
            )
            self.value_contract(result, pointer + "/result")
        for i, outcome in enumerate(operation.get("outcomes", [])):
            self.occurrence(
                AuthorityToken("operation-outcome", scope, outcome["id"]),
                f"{pointer}/outcomes/{i}/id",
                "declaration",
                "/meta_format/runtime_program/outcome_contract",
            )
        self.body(operation["body"], pointer + "/body", scope, bindings)
        result = operation.get("result", {})
        source = result.get("source")
        if isinstance(source, dict):
            if source["kind"] in {"port", "local"}:
                self.operand(
                    source["name"],
                    pointer + "/result/source/name",
                    scope,
                    bindings,
                    law,
                )
            elif source["kind"] == "operation-result":
                self.occurrence(
                    AuthorityToken("operation-site", scope, source["site"]),
                    pointer + "/result/source/site",
                    "reference",
                    law,
                )
            elif source["kind"] != "unit":
                raise InventoryRefusal("unknown Operation result source")
        if "default_outcome" in operation:
            self.occurrence(
                AuthorityToken(
                    "operation-outcome", scope, operation["default_outcome"]
                ),
                pointer + "/default_outcome",
                "reference",
                "/meta_format/runtime_program/outcome_contract",
            )
        for member, role in (
            ("rule", "language.rules"),
            ("runtime_profile", "language.runtime_profiles"),
            ("numeric_policy", "language.quantity.numeric_policies"),
        ):
            if member in operation:
                self.reference(
                    role,
                    operation[member],
                    pointer + "/" + member,
                    "/meta_format/language_definitions/collections/operations",
                )
        for i, reason in enumerate(operation.get("refusals", [])):
            self.reference(
                "language.reasons",
                reason,
                f"{pointer}/refusals/{i}",
                "/meta_format/language_definitions/collections/operations",
            )
        if self.graph.get("vector_sets"):
            for i, name in enumerate(operation.get("vectors", [])):
                self.reference(
                    "vectors",
                    name,
                    f"{pointer}/vectors/{i}",
                    "/meta_format/package_vector",
                )
        for gi, group in enumerate(
            operation.get("alias_policy", {}).get("writable_groups", [])
        ):
            for pi, name in enumerate(group["ports"]):
                self.occurrence(
                    AuthorityToken("operation-port", scope, name),
                    f"{pointer}/alias_policy/writable_groups/{gi}/ports/{pi}",
                    "reference",
                    law,
                )
        for i, effect in enumerate(operation.get("effects", [])):
            self.reference(
                "runtime-effect",
                effect,
                f"{pointer}/effects/{i}",
                "/meta_format/runtime_profile_definition",
            )
        self.operation_formula_extensions(operation, pointer, scope, bindings)

    def operation_formula_extensions(
        self,
        operation: dict[str, Any],
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
    ) -> None:
        notation_member = self.kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["source_notation"]["operation_source"]["extension_member"]
        for key, extension in operation.get("extensions", {}).items():
            ep = _child(pointer + "/extensions", key)
            if key == notation_member:
                if extension["kind"] == "function":
                    if set(extension) != {"kind", "name", "ordered_ports"}:
                        raise InventoryRefusal(
                            "Formula function notation has unknown members"
                        )
                    self.occurrence(
                        AuthorityToken("operation-notation", scope, extension["name"]),
                        ep + "/name",
                        "declaration",
                        ep,
                    )
                elif extension["kind"] == "infix":
                    if set(extension) != {
                        "kind",
                        "token",
                        "ordered_ports",
                        "precedence",
                        "associativity",
                    }:
                        raise InventoryRefusal(
                            "Formula infix notation has unknown members"
                        )
                    self.occurrence(
                        AuthorityToken("operation-notation", scope, extension["token"]),
                        ep + "/token",
                        "declaration",
                        ep,
                    )
                else:
                    raise InventoryRefusal("Formula notation kind is unknown")
                for i, port in enumerate(extension["ordered_ports"]):
                    self.occurrence(
                        AuthorityToken("operation-port", scope, port),
                        f"{ep}/ordered_ports/{i}",
                        "reference",
                        ep,
                    )
            elif key == "standard.formula-slots":
                if not isinstance(extension, list):
                    raise InventoryRefusal("Formula slots are not a list")
                for i, slot in enumerate(extension):
                    sp = f"{ep}/{i}"
                    if set(slot) != {
                        "id",
                        "context",
                        "parameters",
                        "permitted_refusals",
                        "placeholder_index",
                        "placeholder_length",
                        "resource_bounds",
                        "result",
                        "target",
                        "termination_measure",
                    }:
                        raise InventoryRefusal("Formula slot has unknown members")
                    slot_scope = (*scope, slot["id"])
                    self.occurrence(
                        AuthorityToken("operation-slot", scope, slot["id"]),
                        sp + "/id",
                        "declaration",
                        ep,
                    )
                    self.operand(slot["target"], sp + "/target", scope, bindings, ep)
                    self.value_contract(slot["result"], sp + "/result")
                    for pi, parameter in enumerate(slot["parameters"]):
                        pp = f"{sp}/parameters/{pi}"
                        self.occurrence(
                            AuthorityToken(
                                "operation-slot-parameter", slot_scope, parameter["id"]
                            ),
                            pp + "/id",
                            "declaration",
                            ep,
                        )
                        self.value_contract(parameter, pp)
                        source = parameter["source"]
                        if source["kind"] not in {"port", "local"}:
                            raise InventoryRefusal(
                                "unknown Formula slot parameter source"
                            )
                        self.operand(
                            source["name"], pp + "/source/name", scope, bindings, ep
                        )
                    for ri, reason in enumerate(slot["permitted_refusals"]):
                        self.reference(
                            "language.reasons",
                            reason,
                            f"{sp}/permitted_refusals/{ri}",
                            ep,
                        )
            elif ep not in self.relation_extensions:
                self.gap(
                    ep,
                    "/meta_format/language_definitions/collections/operations",
                    "Operation extension roles are not yet complete",
                )

    def callee(
        self, reference: dict[str, Any], pointer: str, law: str
    ) -> tuple[str, str]:
        self.namespace(reference["package"], pointer + "/package", "reference", law)
        self.reference(
            "language.operations",
            reference["id"],
            pointer + "/id",
            law,
            reference["package"],
        )
        return reference["package"], reference["id"]

    def body(
        self,
        body: list[dict[str, Any]],
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
        body_path: tuple[int, ...] = (),
    ) -> None:
        for i, instruction in enumerate(body):
            ip = _child(pointer, i)
            node = self.nodes.get(instruction.get("node"))
            if node is None:
                raise InventoryRefusal(f"unknown runtime node at {ip}")
            law = self.node_laws[node["id"]]
            if set(instruction) != set(node["required_members"]):
                raise InventoryRefusal(f"unknown runtime node members at {ip}")
            operator = node["semantics"]["operator"]
            members = {
                member
                for constraint in node["operand_constraints"]
                for member in constraint.get("members", [])
            }
            members.update(node["result"].get("typing", {}).get("members", []))
            consumed = {"node", "target"}
            if operator == "collection-is-empty":
                members.add("value")
            elif operator == "bounded-list-append":
                members.add("item")
            elif operator == "typed-require":
                member = node["semantics"]["refusal_reference"]["instruction_member"]
                self.reference(
                    "language.reasons", instruction[member], _child(ip, member), law
                )
                consumed.update({member, "expected"})
            elif operator == "gameplay-precondition":
                self.occurrence(
                    AuthorityToken("operation-outcome", scope, instruction["outcome"]),
                    ip + "/outcome",
                    "reference",
                    law,
                )
                consumed.add("outcome")
            elif operator == "named-integer-draw":
                self.occurrence(
                    AuthorityToken("named-stream", (), instruction["stream"]),
                    ip + "/stream",
                    "declaration",
                    "/meta_format/runtime_program/named_rng/stream_derivation",
                )
                consumed.add("stream")
            elif operator == "cancel-event":
                self.occurrence(
                    AuthorityToken("operation-site", scope, instruction["site"]),
                    ip + "/site",
                    "declaration",
                    law,
                )
                self.operand(instruction["event"], ip + "/event", scope, bindings, law)
                consumed.update({"event", "site"})
            if operator == "typed-literal":
                self.typed_literal(instruction["literal"], ip + "/literal")
                consumed.add("literal")
                members.discard("literal")
            if operator == "bounded-lookup":
                members.discard("key")
                consumed.add("key")
                candidates = self.operand_contracts.get(
                    (scope, (*body_path, i), "value")
                )
                if not candidates:
                    raise InventoryRefusal("lookup has no closed operand judgment")
                roles = set()
                for contract in candidates:
                    reference = contract["type"]
                    owner = (
                        (reference["package"], reference["id"])
                        if "package" in reference
                        else None
                    )
                    nominal = self.types[owner] if owner is not None else None
                    constructor, cp = next(
                        (definition, dp)
                        for (_, role, name), (
                            definition,
                            dp,
                        ) in self.definitions.items()
                        if role == "language.constructors"
                        and (
                            name == nominal["constructor"]
                            if nominal is not None
                            else definition.get("value_rule", {}).get("definition_kind")
                            == reference.get("kind")
                        )
                    )
                    kind = constructor["value_rule"]["operator"]
                    roles.add(kind)
                    if kind == "closed-record":
                        if owner is None:
                            self.gap(
                                ip + "/key",
                                law,
                                "anonymous Record lookup field scope is unresolved",
                            )
                            continue
                        self.occurrence(
                            AuthorityToken("record-field", owner, instruction["key"]),
                            ip + "/key",
                            "reference",
                            cp + "/value_rule",
                        )
                    elif kind == "bounded-list":
                        self.operand(
                            instruction["key"], ip + "/key", scope, bindings, law
                        )
                    else:
                        raise InventoryRefusal(
                            "lookup operand has an unknown consuming law"
                        )
                if len(roles) > 1:
                    raise InventoryRefusal("lookup key has conflicting semantic roles")
            if operator in {
                "bounded-pure-fold",
                "invoke-operation",
                "schedule-operation",
            }:
                consumed.update({"site", "operation", "arguments"})
                site = AuthorityToken("operation-site", scope, instruction["site"])
                self.occurrence(site, ip + "/site", "declaration", law)
                target_scope = self.callee(
                    instruction["operation"], ip + "/operation", law
                )
                for ai, argument in enumerate(instruction["arguments"]):
                    ap = f"{ip}/arguments/{ai}"
                    self.occurrence(
                        AuthorityToken(
                            "operation-port", target_scope, argument["port"]
                        ),
                        ap + "/port",
                        "reference",
                        law,
                    )
                    self.operand(
                        argument["operand"], ap + "/operand", scope, bindings, law
                    )
                if operator == "bounded-pure-fold":
                    members.update({"value", "initial"})
                    consumed.update({"accumulator_port", "item_port"})
                    for member in ("accumulator_port", "item_port"):
                        self.occurrence(
                            AuthorityToken(
                                "operation-port", target_scope, instruction[member]
                            ),
                            ip + "/" + member,
                            "reference",
                            law,
                        )
                else:
                    consumed.add("result")
                    if operator == "schedule-operation":
                        members.update({"logical_time", "priority"})
                    else:
                        consumed.add("outcomes")
                    result = instruction["result"]
                    if result["kind"] == "local":
                        token = AuthorityToken("operation-local", scope, result["name"])
                        self.occurrence(token, ip + "/result/name", "declaration", law)
                        bindings[result["name"]] = token
                    elif (
                        result["kind"]
                        not in self.meta["runtime_program"]["invocation_contract"][
                            "result_binding_kinds"
                        ]
                    ):
                        raise InventoryRefusal("unknown invocation result binding")
                    for oi, outcome in enumerate(instruction.get("outcomes", [])):
                        op = f"{ip}/outcomes/{oi}"
                        self.occurrence(
                            AuthorityToken(
                                "operation-outcome", target_scope, outcome["outcome"]
                            ),
                            op + "/outcome",
                            "reference",
                            law,
                        )
                        if outcome["action"]["kind"] == "propagate":
                            self.occurrence(
                                AuthorityToken(
                                    "operation-outcome",
                                    scope,
                                    outcome["action"]["outcome"],
                                ),
                                op + "/action/outcome",
                                "reference",
                                law,
                            )
            elif operator == "guarded-outcome-block":
                consumed.update({"body", "outcome"})
                self.body(
                    instruction["body"], ip + "/body", scope, bindings, (*body_path, i)
                )
                self.occurrence(
                    AuthorityToken("operation-outcome", scope, instruction["outcome"]),
                    ip + "/outcome",
                    "reference",
                    law,
                )
            for member in members:
                if member in instruction:
                    self.operand(
                        instruction[member], _child(ip, member), scope, bindings, law
                    )
                    consumed.add(member)
            if "target" in instruction and node["result"]["kind"] in {"local", "draw"}:
                token = AuthorityToken("operation-local", scope, instruction["target"])
                self.occurrence(token, ip + "/target", "declaration", law)
                bindings[instruction["target"]] = token
            remaining = set(instruction) - consumed
            if remaining:
                self.gap(
                    ip,
                    law,
                    "node roles not yet covered: " + ",".join(sorted(remaining)),
                )

    def source(self) -> None:
        projection = self.source_projection
        if projection is None:
            return
        source = projection.value
        self.formula_projections = _formula_projections(self.kernel, self.graph)
        self.source_structure(source)

    def source_alias(self, name, aliases, scope, pointer):
        alias = aliases.get(name)
        if alias is None:
            raise InventoryRefusal(f"unresolved Source Type alias at {pointer}")
        return alias

    def source_structure(self, source: dict[str, Any]) -> None:
        """Visit declared Source roles; the calling boundary owns admission."""
        law = "/meta_format/resolution_judgment"
        model = source["manifest"]["id"]
        self.occurrence(
            AuthorityToken("source-model", (), model),
            "/source/manifest/id",
            "declaration",
            law,
        )
        for i, name in enumerate(source["package_requirements"]):
            self.namespace(
                name,
                f"{_child('/source', 'package_requirements')}/{i}",
                "reference",
                law,
            )
        for mi, module in enumerate(source["modules"]):
            mp = f"{_child('/source', 'modules')}/{mi}"
            module_scope = (model, module["id"])
            self.occurrence(
                AuthorityToken(
                    "source-module",
                    (model,),
                    module["id"],
                ),
                _child(mp, "id"),
                "declaration",
                law,
            )
            aliases = {}
            for ii, import_ in enumerate(module["imports"]):
                ip = f"{_child(mp, 'imports')}/{ii}"
                alias = AuthorityToken(
                    "source-type-alias",
                    module_scope,
                    import_["alias"],
                )
                aliases[import_["alias"]] = alias
                self.occurrence(
                    alias,
                    _child(ip, "alias"),
                    "declaration",
                    law,
                )
                self.namespace(
                    import_["package"],
                    _child(ip, "package"),
                    "reference",
                    law,
                )
                self.occurrence(
                    AuthorityToken(
                        "type",
                        (import_["package"],),
                        import_["symbol"],
                    ),
                    _child(ip, "symbol"),
                    "reference",
                    law,
                )
            for si, symbol in enumerate(module["symbols"]):
                sp = f"{_child(mp, 'symbols')}/{si}"
                self.occurrence(
                    AuthorityToken(
                        "source-symbol",
                        module_scope,
                        symbol["symbol"],
                    ),
                    _child(sp, "symbol"),
                    "declaration",
                    law,
                )
                alias = self.source_alias(symbol["type"], aliases, module_scope, sp)
                self.occurrence(
                    alias,
                    _child(sp, "type"),
                    "reference",
                    law,
                )
                self.value_contract(
                    {
                        k: v
                        for k, v in symbol.items()
                        if k
                        not in {
                            "symbol",
                            "type",
                        }
                    },
                    sp,
                )
                self.source_value_policy(symbol, sp)
            if module.get("formulas"):
                self.formulas(source, module, mp, aliases)
        self.formula_bindings(source)
        entry = AuthorityToken(
            "source-module",
            (model,),
            source["manifest"]["entry_module"],
        )
        self.occurrence(
            entry,
            "/source/manifest/entry_module",
            "reference",
            law,
        )
        for ei, entrypoint in enumerate(source.get("entrypoints", [])):
            ep = _child(_child("/source", "entrypoints"), ei)
            self.occurrence(
                AuthorityToken("source-entrypoint", (model,), entrypoint["id"]),
                ep + "/id",
                "declaration",
                law,
            )
            target_scope = self.callee(entrypoint["operation"], ep + "/operation", law)
            for ai, argument in enumerate(entrypoint["arguments"]):
                ap = f"{ep}/arguments/{ai}"
                self.occurrence(
                    AuthorityToken("operation-port", target_scope, argument["port"]),
                    ap + "/port",
                    "reference",
                    law,
                )
                self.source_operand(argument["operand"], ap + "/operand", model, law)
            self.source_operand(entrypoint["result"], ep + "/result", model, law)

    def source_contract(
        self, value: dict[str, Any], pointer: str, aliases: Mapping[str, AuthorityToken]
    ) -> None:
        if "type" in value:
            name = value["type"]
            alias = aliases.get(name)
            if alias is None:
                policy, _, profile = self.formula_policy()
                fixed = {row["alias"] for row in policy["fixed_value_type_aliases"]}
                if name not in fixed:
                    raise InventoryRefusal(f"unknown Formula Type alias at {pointer}")
                alias = AuthorityToken("formula-fixed-alias", (profile,), name)
            self.occurrence(
                alias,
                pointer + "/type",
                "reference",
                "/meta_format/resolution_judgment",
            )
        self.value_contract(
            {key: val for key, val in value.items() if key != "type"}, pointer
        )

    def formulas(
        self,
        source: dict[str, Any],
        module: dict[str, Any],
        pointer: str,
        aliases: Mapping[str, AuthorityToken],
    ) -> None:
        policy, law, _ = self.formula_policy()
        model = source["manifest"]["id"]
        module_scope = (model, module["id"])
        for fi, formula in enumerate(module.get("formulas", [])):
            fp = f"{pointer}/{'formulas'}/{fi}"
            name = formula["id"]
            scope = (*module_scope, name)
            self.occurrence(
                AuthorityToken("source-formula", module_scope, name),
                fp + "/" + "id",
                "declaration",
                law,
            )
            parameters = {}
            for pi, parameter in enumerate(formula["parameters"]):
                pp = f"{fp}/{'parameters'}/{pi}"
                token = AuthorityToken(
                    "source-formula-parameter",
                    scope,
                    parameter["id"],
                )
                if token.name in parameters:
                    raise InventoryRefusal("duplicate Formula parameter")
                parameters[token.name] = token
                self.occurrence(token, pp + "/" + "id", "declaration", law)
                self.source_contract(parameter, pp, aliases)
            self.source_contract(
                formula["result"],
                fp + "/" + "result",
                aliases,
            )
            body = formula["body"]
            self.formula_body(
                body,
                fp + "/" + "body",
                scope,
                aliases,
                parameters,
                policy,
                law,
            )
            ep = fp + "/expression"
            authored_ep = _source_pointer(self.source_projection, ep)
            if authored_ep in self.formula_projections:
                self.formula_body(
                    self.formula_projections[authored_ep],
                    ep,
                    scope,
                    aliases,
                    parameters,
                    policy,
                    law,
                    projected=True,
                )

    def formula_body(
        self,
        body: dict[str, Any],
        pointer: str,
        scope: tuple[str, str, str],
        aliases: Mapping[str, AuthorityToken],
        parameters: Mapping[str, AuthorityToken],
        policy: Mapping[str, Any],
        law: str,
        *,
        projected: bool = False,
    ) -> None:
        locals_: dict[str, AuthorityToken] = {}

        def emit(token: AuthorityToken, path: str, use: str = "reference") -> None:
            self.occurrence(
                token,
                pointer if projected else pointer + path,
                use,
                law,
                location="formula" if projected else "value",
                projection=path if projected else "",
            )

        def contract(value: dict[str, Any], path: str) -> None:
            alias = aliases.get(value["type"])
            if alias is None:
                raise InventoryRefusal("unknown Formula result Type alias")
            emit(alias, path + "/type")
            # These are identity joins declared by the selected runtime projection,
            # not another Formula type inference algorithm.
            for seed, _, collection in self.seeds:
                member_path = seed["declaration_path"]
                if len(member_path) != 1 or member_path[0] not in value:
                    continue
                source = collection["source"]
                if source["kind"] != "semantic-closure":
                    continue
                role = source["authority_path"]
                projection = next(
                    row for row in self.projections if row["authority_path"] == role
                )
                if seed["target_path"] != (
                    []
                    if projection["key_member"] is None
                    else [projection["key_member"]]
                ):
                    continue
                emit(
                    self.declared(role, "", value[member_path[0]]),
                    path + "/" + member_path[0],
                )

        def operand(value: dict[str, Any], path: str) -> None:
            kind = value.get("kind")
            if kind not in self.meta["formula_resolution"]["operand_kinds"]:
                raise InventoryRefusal("unknown Formula operand kind")
            if kind == "parameter":
                token = parameters.get(value["parameter"])
                if token is None:
                    raise InventoryRefusal("unknown Formula parameter reference")
                emit(token, path + "/parameter")
            elif kind == "local":
                token = locals_.get(value["local"])
                if token is None:
                    raise InventoryRefusal("unknown Formula local reference")
                emit(token, path + "/local")
            elif kind == "symbol":
                emit(
                    AuthorityToken("source-module", scope[:1], value["module"]),
                    path + "/module",
                )
                emit(
                    AuthorityToken(
                        "source-symbol", (scope[0], value["module"]), value["symbol"]
                    ),
                    path + "/symbol",
                )
            elif type(value["value"]) is not int:
                raise InventoryRefusal("unknown Formula literal payload")

        if body.get("node") == "parameter":
            token = parameters.get(body["parameter"])
            if token is None:
                raise InventoryRefusal("unknown inline Formula parameter")
            emit(token, "/parameter")
            return
        for ni, node in enumerate(body["nodes"]):
            np = f"/{'nodes'}/{ni}"
            kind = node["node"]
            if kind not in self.meta["formula_resolution"]["body_nodes"]:
                raise InventoryRefusal("unknown Formula body node")
            if kind == "operation-call":
                coordinate = node["operation"]
                emit(
                    AuthorityToken("namespace", (), coordinate["package"]),
                    np + "/operation/package",
                )
                emit(
                    AuthorityToken(
                        "language.operations",
                        (coordinate["package"],),
                        coordinate["id"],
                    ),
                    np + "/operation/id",
                )
                for ai, argument in enumerate(node["arguments"]):
                    ap = f"{np}/arguments/{ai}"
                    emit(
                        AuthorityToken(
                            "operation-port",
                            (coordinate["package"], coordinate["id"]),
                            argument["port"],
                        ),
                        ap + "/port",
                    )
                    operand(argument["operand"], ap + "/operand")
            elif kind == "formula-call":
                coordinate = node["formula"]
                emit(
                    AuthorityToken("source-module", scope[:1], coordinate["module"]),
                    np + "/formula/module",
                )
                emit(
                    AuthorityToken(
                        "source-formula",
                        (scope[0], coordinate["module"]),
                        coordinate["id"],
                    ),
                    np + "/formula/id",
                )
                for ai, argument in enumerate(node["arguments"]):
                    ap = f"{np}/arguments/{ai}"
                    emit(
                        AuthorityToken(
                            "source-formula-parameter",
                            (scope[0], coordinate["module"], coordinate["id"]),
                            argument["parameter"],
                        ),
                        ap + "/parameter",
                    )
                    operand(argument["operand"], ap + "/operand")
            elif kind == "conditional":
                for member in ("condition", "when_true", "when_false"):
                    operand(node[member], np + "/" + member)
            contract(node["result"], np + "/result")
            name = node["id"]
            token = AuthorityToken("source-formula-local", scope, name)
            if name in locals_ or name in parameters:
                raise InventoryRefusal("duplicate or capturing Formula local")
            emit(token, np + "/" + "id", "declaration")
            locals_[name] = token
        operand(body["result"], "/" + "result")

    def source_operand(
        self, operand: dict[str, Any], pointer: str, model: str, law: str
    ) -> None:
        if operand["kind"] == "symbol":
            self.occurrence(
                AuthorityToken("source-module", (model,), operand["module"]),
                pointer + "/module",
                "reference",
                law,
            )
            self.occurrence(
                AuthorityToken(
                    "source-symbol", (model, operand["module"]), operand["symbol"]
                ),
                pointer + "/symbol",
                "reference",
                law,
            )
        elif operand["kind"] == "literal":
            self.typed_literal(operand["value"], pointer + "/value")
        elif operand["kind"] != "discard":
            self.gap(pointer, law, "Source operand form is not yet traversed")

    def formula_policy(self) -> tuple[dict[str, Any], str, str]:
        policies = _formula_policy_rows(self.kernel, self.graph)
        if len(policies) != 1:
            raise InventoryRefusal("Formula policy does not have one admitted owner")
        return policies[0]

    def formula_aliases(self) -> None:
        policy, pointer, profile = self.formula_policy()
        for i, alias in enumerate(policy["fixed_value_type_aliases"]):
            if (
                set(alias) != {"alias", "contract"}
                or alias["contract"]
                not in self.meta["runtime_program"]["fixed_value_contracts"]
            ):
                raise InventoryRefusal(
                    "Formula fixed alias does not address a Kernel contract"
                )
            self.occurrence(
                AuthorityToken("formula-fixed-alias", (profile,), alias["alias"]),
                f"{pointer}/fixed_value_type_aliases/{i}/alias",
                "declaration",
                pointer,
            )

    def formula_bindings(self, source: dict[str, Any]) -> None:
        policy, law, _ = self.formula_policy()
        model = source["manifest"]["id"]
        for i, binding in enumerate(source.get("formula_bindings", [])):
            bp = f"/source/{'formula_bindings'}/{i}"
            site = binding["site"]
            sp = _child(bp, "site")
            slot_scope = None
            if site["kind"] == "operation-slot":
                scope = self.callee(site["operation"], sp + "/operation", law)
                slot_scope = (*scope, site["slot"])
                self.occurrence(
                    AuthorityToken("operation-slot", scope, site["slot"]),
                    sp + "/slot",
                    "reference",
                    law,
                )
            elif site["kind"] == "derived-symbol":
                self.source_operand(
                    {
                        "kind": "symbol",
                        "module": site["module"],
                        "symbol": site["symbol"],
                    },
                    sp,
                    model,
                    law,
                )
            else:
                raise InventoryRefusal("unknown Formula binding site")
            formula = binding["formula"]
            fp = _child(bp, "formula")
            self.occurrence(
                AuthorityToken("source-module", (model,), formula["module"]),
                fp + "/module",
                "reference",
                law,
            )
            self.occurrence(
                AuthorityToken(
                    "source-formula", (model, formula["module"]), formula["id"]
                ),
                fp + "/id",
                "reference",
                law,
            )
            for ai, argument in enumerate(binding["arguments"]):
                ap = f"{bp}/{'arguments'}/{ai}"
                self.occurrence(
                    AuthorityToken(
                        "source-formula-parameter",
                        (model, formula["module"], formula["id"]),
                        argument["parameter"],
                    ),
                    _child(ap, "parameter"),
                    "reference",
                    law,
                )
                operand = argument["operand"]
                op = _child(ap, "operand")
                if operand["kind"] == "slot-parameter":
                    if slot_scope is None:
                        raise InventoryRefusal(
                            "slot parameter used outside Operation slot"
                        )
                    self.occurrence(
                        AuthorityToken(
                            "operation-slot-parameter", slot_scope, operand["parameter"]
                        ),
                        op + "/parameter",
                        "reference",
                        law,
                    )
                else:
                    self.source_operand(operand, op, model, law)

    def finish(self) -> ExtensionInventory:
        self.index()
        template_rows, template_reserved, self.template_roots, self.template_schemas = (
            _template_inventory(self.kernel, self.graph)
        )
        self.reserved.update(template_reserved)
        for occurrence in template_rows:
            self.occurrence(
                occurrence.token,
                occurrence.pointer,
                occurrence.use,
                occurrence.law,
                location=occurrence.location,
            )
        for occurrence in _experiment_judgment_links(self.kernel, self.graph):
            self.occurrence(
                occurrence.token, occurrence.pointer, occurrence.use, occurrence.law
            )
        for occurrence in _evidence_claim_links(self.kernel, self.graph):
            self.occurrence(
                occurrence.token,
                occurrence.pointer,
                occurrence.use,
                occurrence.law,
            )
            if occurrence.token.role.startswith("kernel."):
                self.reserved.add(occurrence.token)
        for occurrence in _replay_links(self.kernel, self.graph):
            self.occurrence(
                occurrence.token,
                occurrence.pointer,
                occurrence.use,
                occurrence.law,
                location=occurrence.location,
            )
            if occurrence.token.role.startswith("kernel."):
                self.reserved.add(occurrence.token)
        self.operation_operand_projection()
        self.metadata_links()
        for token, pointer, use, law in _wire_protocol_links(self.kernel, self.graph):
            self.occurrence(token, pointer, use, law)
            if token.role.startswith("kernel."):
                self.reserved.add(token)
        for token, pointer, use, location, projection, law in _source_address_links(
            self.kernel, self.graph
        ):
            self.occurrence(
                token, pointer, use, law, location=location, projection=projection
            )
        for token, pointer, use, law in _projection_collection_links(
            self.kernel, self.graph
        ):
            self.occurrence(token, pointer, use, law)
        for token, pointer, use, law in _resolution_binding_links(
            self.kernel, self.graph
        ):
            self.occurrence(token, pointer, use, law)
            if token.role.startswith("kernel."):
                self.reserved.add(token)
        for token, pointer, use, law in _resolution_policy_fixed_links(
            self.kernel, self.graph
        ):
            self.occurrence(token, pointer, use, law)
            self.reserved.add(token)
        self.packages()
        vector_links, self.scheduler_rule_roots = _scheduler_rule_vector_inventory(
            self.kernel, self.graph
        )
        for row in vector_links:
            self.occurrence(row.token, row.pointer, row.use, row.law)
        for row in _lowering_path_links(self.kernel, self.graph):
            self.occurrence(row.token, row.pointer, row.use, row.law)
            self.reserved.add(row.token)
        self.rule_chain_links()
        self.assignment_policies()
        self.formula_aliases()
        self.source()
        self.experiment_surface()
        self.model_artifact_surface()
        self.runtime_result_surface()
        for token, pointer, use, law in _reason_vector_links(self.kernel, self.graph):
            self.occurrence(token, pointer, use, law)
        for row in (
            *_value_vector_links(self.kernel, self.graph),
            *_operation_vector_links(self.kernel, self.graph),
        ):
            if isinstance(row, UncoveredRole):
                self.uncovered.add(row)
            else:
                self.occurrence(
                    row.token,
                    row.pointer,
                    row.use,
                    row.law,
                    location=row.location,
                    projection=row.projection,
                )
        for row in self.relation_links:
            self.occurrence(
                row.token, row.pointer, row.use, row.law, location=row.location
            )
            if row.token.role.startswith("kernel."):
                self.reserved.add(row.token)
        for row in _close_projection_occurrences(
            self.graph, self.occurrences, self.relation_projections
        ):
            self.record_occurrence(row)
        from schema2_model_vector_inventory_support import model_vector_inventory

        model_rows, self.model_vector_roots, model_projections, model_reserved = (
            model_vector_inventory(self.kernel, self.graph)
        )
        self.formula_projections.update(model_projections)
        self.reserved.update(model_reserved)
        for row in model_rows:
            self.record_occurrence(row)
        self.contract_vectors()
        declarations = {o.token for o in self.occurrences if o.use == "declaration"}
        free = {o.token for o in self.occurrences if o.use == "unresolved-reference"}
        unresolved = self.tokens - declarations - self.reserved - free
        unresolved |= {
            o.token
            for o in self.occurrences
            if o.use == "reference" and o.token not in declarations | self.reserved
        }
        if unresolved:
            # A not-yet-traversed provider is visible evidence, never a successful
            # lookup created simply by seeing a reference spelling.
            for token in unresolved:
                occurrence = next(o for o in self.occurrences if o.token == token)
                self.gap(
                    occurrence.pointer,
                    occurrence.law,
                    "reference has no traversed declaration",
                )
        return ExtensionInventory(
            frozenset(self.tokens),
            tuple(sorted(self.occurrences)),
            frozenset(self.reserved),
            tuple(sorted(self.uncovered)),
        )


def read_extension_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> ExtensionInventory:
    return _Reader(kernel, graph).finish()


def validate_inventory_occurrences(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Independently check exact bytes and uniqueness of a supplied occurrence set."""
    projections = _formula_projections(kernel, graph)
    positions = {
        (
            row.token,
            row.pointer,
            row.use,
            row.law
            if row.pointer.startswith(("/experiment/", "/artifacts/", "/results/"))
            else "",
            row.location,
            row.projection,
        )
        for row in inventory.occurrences
    }
    if len(inventory.occurrences) != len(positions):
        raise InventoryRefusal("duplicate token occurrence")
    for occurrence in inventory.occurrences:
        if occurrence.use not in {"declaration", "reference", "unresolved-reference"}:
            raise InventoryRefusal("unknown token occurrence use")
        try:
            value = _occurrence_value(graph, occurrence, projections)
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise InventoryRefusal("invalid token occurrence pointer") from error
        if occurrence.token not in inventory.tokens or value != occurrence.token.name:
            raise InventoryRefusal("token occurrence does not match graph")
    if {o.token for o in inventory.occurrences} != set(inventory.tokens):
        raise InventoryRefusal("inventory member has no occurrence")
    if not inventory.reserved <= inventory.tokens:
        raise InventoryRefusal("reserved token has no admitted occurrence")
    expected_free = {
        (token, pointer, use, "", "value", "")
        for token, pointer, use, _ in _reason_vector_links(kernel, graph)
        if use == "unresolved-reference"
    }
    expected_free.update(
        (row.token, row.pointer, row.use, "", row.location, row.projection)
        for row in _value_vector_links(kernel, graph)
        if isinstance(row, TokenOccurrence) and row.use == "unresolved-reference"
    )
    from schema2_model_vector_inventory_support import model_vector_inventory

    model_rows, _, _, _ = model_vector_inventory(kernel, graph)
    expected_free.update(
        (
            row.token,
            row.pointer,
            row.use,
            row.law
            if row.pointer.startswith(("/experiment/", "/artifacts/", "/results/"))
            else "",
            row.location,
            row.projection,
        )
        for row in model_rows
        if row.use == "unresolved-reference"
    )
    actual_free = {row for row in positions if row[2] == "unresolved-reference"}
    if expected_free != actual_free:
        raise InventoryRefusal(
            "unresolved-reference occurrence is omitted, forged, or misowned"
        )


def validate_token_bijection(
    inventory: ExtensionInventory,
    pairs: Sequence[tuple[AuthorityToken, AuthorityToken]],
) -> None:
    """Check exact token-domain and owner-role preservation; never waive coverage."""
    sources, targets = [p[0] for p in pairs], [p[1] for p in pairs]
    if len(sources) != len(set(sources)) or len(targets) != len(set(targets)):
        raise InventoryRefusal("duplicate source or target in token bijection")
    if any(token in inventory.reserved for token in sources + targets):
        raise InventoryRefusal("Kernel-reserved token in bijection")
    if set(sources) != set(inventory.tokens - inventory.reserved):
        raise InventoryRefusal("bijection domain is not the complete inventory")
    if any(source.name == target.name for source, target in pairs):
        raise InventoryRefusal("token bijection leaves a non-Kernel name unchanged")
    correspondence = dict(pairs)
    if any(
        source.role != target.role
        or target.owner != _renamed_owner(source, correspondence)
        or not target.name
        for source, target in pairs
    ):
        raise InventoryRefusal("token role or owner changed inconsistently")
    shared_positions: dict[tuple[str, str, str], set[str]] = {}
    for occurrence in inventory.occurrences:
        target = correspondence.get(occurrence.token, occurrence.token)
        position = (occurrence.pointer, occurrence.location, occurrence.projection)
        shared_positions.setdefault(position, set()).add(target.name)
    if any(len(names) != 1 for names in shared_positions.values()):
        raise InventoryRefusal(
            "bijection splits one shared authored reference occurrence"
        )
    inventory.require_complete()


def _verify_constructor_address_coverage(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Reverse-check constructor declarations and addressed keys; no type inference."""
    expected = set()
    constructors = {}

    def required(
        token: AuthorityToken,
        pointer: str,
        use: str = "reference",
        location: str = "value",
    ) -> None:
        expected.add((token, pointer, use, location))

    for _, constructor, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.constructors"
    ):
        rule = constructor.get("value_rule", {})
        if "definition_kind" not in rule:
            continue
        constructors[rule["definition_kind"]] = constructor
        for selector, member, area in _constructor_member_selectors(constructor):
            required(
                AuthorityToken("constructor-member", (constructor["id"], area), member),
                pointer + "/value_rule/" + selector,
                "declaration",
            )
        for i, member in enumerate(constructor["parameters"]):
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "definition"), member
                ),
                f"{pointer}/parameters/{i}",
            )
        for i, member in enumerate(rule.get("value_members", [])):
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "ref-value"), member
                ),
                f"{pointer}/value_rule/value_members/{i}",
                "declaration",
            )

    def definition(
        value: dict[str, Any], pointer: str, owner: tuple[str, str] | None
    ) -> None:
        if "package" in value:
            required(
                AuthorityToken("namespace", (), value["package"]), pointer + "/package"
            )
            required(
                AuthorityToken("type", (value["package"],), value["id"]),
                pointer + "/id",
            )
            return
        constructor = constructors[value["kind"]]
        rule = constructor["value_rule"]
        for member in constructor["parameters"]:
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "definition"), member
                ),
                _child(pointer, member),
                location="key",
            )
        if rule["operator"] == "enum-member" and owner is not None:
            for i, member in enumerate(value[rule["members_member"]]):
                required(
                    AuthorityToken("enum-member", owner, member),
                    f"{pointer}/{rule['members_member']}/{i}",
                    "declaration",
                )
        elif rule["operator"] == "bounded-list":
            definition(
                value[rule["element_member"]],
                _child(pointer, rule["element_member"]),
                None,
            )
        elif rule["operator"] == "canonical-ref-key":
            definition(
                value[rule["target_member"]],
                _child(pointer, rule["target_member"]),
                None,
            )
        elif rule["operator"] == "closed-record":
            for i, field in enumerate(value[rule["fields_member"]]):
                fp = f"{pointer}/{rule['fields_member']}/{i}"
                for selector in ("field_name_member", "field_type_member"):
                    required(
                        AuthorityToken(
                            "constructor-member",
                            (constructor["id"], "record-field"),
                            rule[selector],
                        ),
                        _child(fp, rule[selector]),
                        location="key",
                    )
                if owner is not None:
                    required(
                        AuthorityToken(
                            "record-field", owner, field[rule["field_name_member"]]
                        ),
                        _child(fp, rule["field_name_member"]),
                        "declaration",
                    )
                definition(
                    field[rule["field_type_member"]],
                    _child(fp, rule["field_type_member"]),
                    None,
                )

    for namespace, nominal, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.nominal_types"
    ):
        if not isinstance(namespace, str):
            raise InventoryRefusal("nominal definition has no attached owner")
        definition(
            nominal["definition"], pointer + "/definition", (namespace, nominal["id"])
        )
    actual = {(o.token, o.pointer, o.use, o.location) for o in inventory.occurrences}
    if not expected <= actual:
        raise InventoryRefusal(
            "constructor address or nominal member coverage is incomplete"
        )
    positions = {row[1:] for row in expected}
    if any(row[1:] in positions and row not in expected for row in actual):
        raise InventoryRefusal(
            "constructor address or nominal member has the wrong owner"
        )


def _verify_formula_coverage(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    found = {
        (o.token, o.pointer, o.use, o.location, o.projection)
        for o in inventory.occurrences
    }
    expected: set[tuple[AuthorityToken, str, str, str, str]] = set()

    def field(token: AuthorityToken, pointer: str, use: str = "reference") -> None:
        expected.add((token, pointer, use, "value", ""))

    notation_source = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]["operation_source"]
    notation_member = notation_source["extension_member"]
    for owner, operation, pointer in _authority_path_rows(
        kernel, graph, "language_bundle." + notation_source["authority_path"]
    ):
        if not isinstance(owner, str):
            raise InventoryRefusal(
                "Formula Operation declaration has no attached owner"
            )
        scope = (owner, operation["id"])
        extensions = operation.get("extensions", {})
        notation = extensions.get(notation_member)
        if notation is not None:
            np = _child(pointer + "/extensions", notation_member)
            member = "name" if notation["kind"] == "function" else "token"
            field(
                AuthorityToken("operation-notation", scope, notation[member]),
                np + "/" + member,
                "declaration",
            )
            for i, port in enumerate(notation["ordered_ports"]):
                field(
                    AuthorityToken("operation-port", scope, port),
                    f"{np}/ordered_ports/{i}",
                )
        for i, slot in enumerate(extensions.get("standard.formula-slots", [])):
            sp = f"{pointer}/extensions/standard.formula-slots/{i}"
            field(
                AuthorityToken("operation-slot", scope, slot["id"]),
                sp + "/id",
                "declaration",
            )
            field(
                AuthorityToken("operation-local", scope, slot["target"]), sp + "/target"
            )
            for pi, parameter in enumerate(slot["parameters"]):
                pp = f"{sp}/parameters/{pi}"
                field(
                    AuthorityToken(
                        "operation-slot-parameter",
                        (*scope, slot["id"]),
                        parameter["id"],
                    ),
                    pp + "/id",
                    "declaration",
                )
                source = parameter["source"]
                field(
                    AuthorityToken(
                        "operation-" + source["kind"], scope, source["name"]
                    ),
                    pp + "/source/name",
                )
    for _, profile, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.resolution_profiles"
    ):
        policy = profile["formula_resolution"]
        for i, alias in enumerate(policy["fixed_value_type_aliases"]):
            field(
                AuthorityToken("formula-fixed-alias", (profile["id"],), alias["alias"]),
                f"{pointer}/formula_resolution/fixed_value_type_aliases/{i}/alias",
                "declaration",
            )
    source_projection = _source_projection(kernel, graph)
    source = source_projection.value if source_projection is not None else None
    if not source:
        if not expected <= found:
            raise InventoryRefusal(
                "Formula declaration or reference coverage is incomplete or misowned"
            )
        return
    projections = _formula_projections(kernel, graph)
    model = source["manifest"]["id"]
    bindings_member = "formula_bindings"
    for i, binding in enumerate(source.get(bindings_member, [])):
        bp = _child(_child("/source", bindings_member), i)
        formula = binding["formula"]
        fs = (model, formula["module"], formula["id"])
        field(
            AuthorityToken("source-module", (model,), formula["module"]),
            bp + "/formula/module",
        )
        field(
            AuthorityToken("source-formula", fs[:2], formula["id"]), bp + "/formula/id"
        )
        site = binding["site"]
        if site["kind"] == "operation-slot":
            ref = site["operation"]
            scope = (ref["package"], ref["id"])
            field(
                AuthorityToken("namespace", (), ref["package"]),
                bp + "/site/operation/package",
            )
            field(
                AuthorityToken("language.operations", scope[:1], ref["id"]),
                bp + "/site/operation/id",
            )
            field(
                AuthorityToken("operation-slot", scope, site["slot"]), bp + "/site/slot"
            )
        elif site["kind"] == "derived-symbol":
            field(
                AuthorityToken("source-module", (model,), site["module"]),
                bp + "/site/module",
            )
            field(
                AuthorityToken(
                    "source-symbol", (model, site["module"]), site["symbol"]
                ),
                bp + "/site/symbol",
            )
        for ai, argument in enumerate(binding["arguments"]):
            ap = f"{bp}/arguments/{ai}"
            field(
                AuthorityToken("source-formula-parameter", fs, argument["parameter"]),
                ap + "/parameter",
            )
            operand = argument["operand"]
            if operand["kind"] == "slot-parameter":
                field(
                    AuthorityToken(
                        "operation-slot-parameter",
                        (
                            site["operation"]["package"],
                            site["operation"]["id"],
                            site["slot"],
                        ),
                        operand["parameter"],
                    ),
                    ap + "/operand/parameter",
                )
            elif operand["kind"] == "symbol":
                field(
                    AuthorityToken("source-module", (model,), operand["module"]),
                    ap + "/operand/module",
                )
                field(
                    AuthorityToken(
                        "source-symbol", (model, operand["module"]), operand["symbol"]
                    ),
                    ap + "/operand/symbol",
                )
    for mi, module in enumerate(source["modules"]):
        ms = (model, module["id"])
        for fi, formula in enumerate(module.get("formulas", [])):
            fp = f"{_child('/source', 'modules')}/{mi}/formulas/{fi}"
            fs = (*ms, formula["id"])
            expected.add(
                (
                    AuthorityToken("source-formula", ms, formula["id"]),
                    fp + "/id",
                    "declaration",
                    "value",
                    "",
                )
            )
            for pi, parameter in enumerate(formula["parameters"]):
                expected.add(
                    (
                        AuthorityToken("source-formula-parameter", fs, parameter["id"]),
                        f"{fp}/parameters/{pi}/id",
                        "declaration",
                        "value",
                        "",
                    )
                )
            bodies = [(formula["body"], fp + "/body", "value")]
            if _source_pointer(source_projection, fp + "/expression") in projections:
                bodies.append(
                    (
                        projections[
                            _source_pointer(source_projection, fp + "/expression")
                        ],
                        fp + "/expression",
                        "formula",
                    )
                )
            for body, base, location in bodies:

                def needed(
                    token: AuthorityToken, path: str, use: str = "reference"
                ) -> None:
                    expected.add(
                        (
                            token,
                            base + path if location == "value" else base,
                            use,
                            location,
                            path if location == "formula" else "",
                        )
                    )

                if body.get("node") == "parameter":
                    needed(
                        AuthorityToken(
                            "source-formula-parameter", fs, body["parameter"]
                        ),
                        "/parameter",
                    )
                    continue
                references = [(body["result"], "/result")]
                for ni, node in enumerate(body["nodes"]):
                    np = f"/nodes/{ni}"
                    needed(
                        AuthorityToken("source-formula-local", fs, node["id"]),
                        np + "/id",
                        "declaration",
                    )
                    if node["node"] == "operation-call":
                        ref = node["operation"]
                        needed(
                            AuthorityToken("namespace", (), ref["package"]),
                            np + "/operation/package",
                        )
                        needed(
                            AuthorityToken(
                                "language.operations", (ref["package"],), ref["id"]
                            ),
                            np + "/operation/id",
                        )
                        for ai, argument in enumerate(node["arguments"]):
                            ap = f"{np}/arguments/{ai}"
                            needed(
                                AuthorityToken(
                                    "operation-port",
                                    (ref["package"], ref["id"]),
                                    argument["port"],
                                ),
                                ap + "/port",
                            )
                            references.append((argument["operand"], ap + "/operand"))
                    elif node["node"] == "formula-call":
                        ref = node["formula"]
                        needed(
                            AuthorityToken("source-module", (model,), ref["module"]),
                            np + "/formula/module",
                        )
                        needed(
                            AuthorityToken(
                                "source-formula", (model, ref["module"]), ref["id"]
                            ),
                            np + "/formula/id",
                        )
                        for ai, argument in enumerate(node["arguments"]):
                            ap = f"{np}/arguments/{ai}"
                            needed(
                                AuthorityToken(
                                    "source-formula-parameter",
                                    (model, ref["module"], ref["id"]),
                                    argument["parameter"],
                                ),
                                ap + "/parameter",
                            )
                            references.append((argument["operand"], ap + "/operand"))
                    elif node["node"] == "conditional":
                        references.extend(
                            (node[member], np + "/" + member)
                            for member in ("condition", "when_true", "when_false")
                        )
                    else:
                        raise InventoryRefusal("unclassified Formula AST node")
                for operand, path in references:
                    if operand["kind"] == "parameter":
                        needed(
                            AuthorityToken(
                                "source-formula-parameter", fs, operand["parameter"]
                            ),
                            path + "/parameter",
                        )
                    elif operand["kind"] == "local":
                        needed(
                            AuthorityToken(
                                "source-formula-local", fs, operand["local"]
                            ),
                            path + "/local",
                        )
                    elif operand["kind"] == "symbol":
                        needed(
                            AuthorityToken(
                                "source-module", (model,), operand["module"]
                            ),
                            path + "/module",
                        )
                        needed(
                            AuthorityToken(
                                "source-symbol",
                                (model, operand["module"]),
                                operand["symbol"],
                            ),
                            path + "/symbol",
                        )
                    elif operand["kind"] != "literal":
                        raise InventoryRefusal("unclassified Formula AST operand")
    expected = {
        (token, _source_pointer(source_projection, pointer), use, location, projection)
        for token, pointer, use, location, projection in expected
    }
    if not expected <= found:
        raise InventoryRefusal(
            "Formula declaration or reference coverage is incomplete or misowned"
        )
    owned_paths = {(row[1], row[2], row[3], row[4]) for row in expected}
    if any(row[1:] in owned_paths and row not in expected for row in found):
        raise InventoryRefusal("extra incorrectly owned Formula occurrence")


def _verify_execution_artifact_graph(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> None:
    """Independently verify generated Artifact identities and graph edges."""
    _attached_language(kernel, graph)

    def surface(name: str, roles: set[str]) -> dict[str, dict[str, Any]]:
        values = graph.get(name)
        if values is None:
            return {}
        if not isinstance(values, dict) or len(values) != len(roles):
            raise InventoryRefusal(f"{name} Artifact graph is incomplete")
        bindings = {
            role: _artifact_protocol_binding(kernel, graph, role) for role in roles
        }
        by_kind = {kind: role for role, (kind, _, _) in bindings.items()}
        if len(by_kind) != len(bindings):
            raise InventoryRefusal(f"{name} Artifact protocol binding is ambiguous")
        result = {}
        for value in values.values():
            if not isinstance(value, dict):
                raise InventoryRefusal(f"{name} Artifact is malformed")
            kind = value.get("artifact_kind")
            if not isinstance(kind, str):
                raise InventoryRefusal(f"{name} Artifact has no producer kind")
            role = by_kind.get(kind)
            if role is None or role in result:
                raise InventoryRefusal(f"{name} Artifact producer binding is invalid")
            _, schema, contract = bindings[role]
            try:
                jsonschema.Draft202012Validator(schema).validate(value)
            except jsonschema.ValidationError as error:
                raise InventoryRefusal(
                    f"{name} Artifact does not close its protocol Schema"
                ) from error
            if value["wire_schema_identity"] != _identity_from_kernel(
                dict(kernel), contract["wire_schema_identity_domain"], schema
            ) or value["content_identity"] != _identity_from_kernel(
                dict(kernel), contract["identity_domain"], value
            ):
                raise InventoryRefusal(
                    f"{name} Artifact content or Wire Schema identity is stale"
                )
            result[role] = value
        if set(result) != roles:
            raise InventoryRefusal(f"{name} Artifact protocol roles are incomplete")
        return result

    model_roles: set[str] = set()
    if graph.get("artifacts") is not None:
        model = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["model_structure"]
        model_roles = (set(model["containers"]) - {"model-build-command-input"}) | {
            "rir-semantic-payload"
        }
    artifacts = surface("artifacts", model_roles)
    if artifacts:
        language_identity = graph["ldb_root"]["content_identity"]
        source = graph.get("source")
        if not isinstance(source, dict):
            raise InventoryRefusal("Model Artifacts have no Source owner")
        source_identity = _identity_from_kernel(
            dict(kernel),
            _source_profile(kernel, graph)["source_identity_domain"],
            source,
        )
        identities = {role: row["content_identity"] for role, row in artifacts.items()}
        rir = artifacts["rir-semantic-payload"]
        expected = {
            "build-receipt": {
                "source_identity": source_identity,
                "kernel_identity": kernel["content_identity"],
                "language_bundle_identity": language_identity,
                **{
                    member: identities[role]
                    for member, role in (
                        ("package_lock_identity", "package-lock"),
                        ("rir_identity", "rir-semantic-payload"),
                        ("resolved_model_identity", "resolved-model"),
                        ("capability_manifest_identity", "capability-manifest"),
                        ("debug_map_identity", "debug-map"),
                        ("model_explanation_identity", "model-explanation"),
                        ("resolution_receipt_identity", "resolution-receipt"),
                    )
                },
            },
            "capability-manifest": {
                "package_lock_identity": identities["package-lock"],
                "resolved_model_identity": identities["resolved-model"],
                "rir_identity": identities["rir-semantic-payload"],
            },
            "debug-map": {
                "source_identity": source_identity,
                "rir_identity": identities["rir-semantic-payload"],
            },
            "model-explanation": {
                "debug_map_identity": identities["debug-map"],
                "rir_identity": identities["rir-semantic-payload"],
            },
            "resolution-receipt": {
                "source_identity": source_identity,
                "kernel_identity": kernel["content_identity"],
                "language_bundle_identity": language_identity,
                "package_lock_identity": identities["package-lock"],
            },
            "resolved-model": {
                "kernel_identity": kernel["content_identity"],
                "language_bundle_identity": language_identity,
                "package_lock_identity": identities["package-lock"],
                "rir_content_identity": identities["rir-semantic-payload"],
                "rir_semantic_identity": rir["semantic_identity"],
            },
        }
        for role, fields in expected.items():
            if any(
                artifacts[role].get(member) != value for member, value in fields.items()
            ):
                raise InventoryRefusal("Model Artifact graph identity binding is stale")

    result_roles: set[str] = set()
    if graph.get("results") is not None:
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
        actual_kinds = {
            row.get("artifact_kind")
            for row in graph["results"].values()
            if isinstance(row, dict)
        }
        primary = {
            role
            for role in protocol["metric_outcome_structure"]["outcomes"]
            if _artifact_protocol_binding(kernel, graph, role)[0] in actual_kinds
        }
        if len(primary) != 1:
            raise InventoryRefusal("Runtime Artifact graph has no unique outcome")
        result_roles = fixed | primary
    results = surface("results", result_roles)
    if results:
        if not artifacts or not isinstance(graph.get("experiment"), dict):
            raise InventoryRefusal("Runtime Artifacts have no input graph owners")
        experiment_identity = _identity_from_kernel(
            dict(kernel),
            kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
                "experiment_input_structure"
            ]["identity"]["domain"],
            graph["experiment"],
        )
        profile_identity = results["resolved-runtime-profile"]["content_identity"]
        trace_identity = results["event-trace"]["content_identity"]
        snapshot_identity = results["snapshot-series"]["content_identity"]
        dataset_identity = results["metric-dataset"]["content_identity"]
        primary_role = next(
            iter(
                result_roles
                - {
                    "resolved-runtime-profile",
                    "evaluator-capability-manifest",
                    "event-trace",
                    "snapshot-series",
                    "metric-dataset",
                }
            )
        )
        expected = {
            "resolved-runtime-profile": {
                "experiment_identity": experiment_identity,
                "rir_semantic_identity": artifacts["rir-semantic-payload"][
                    "semantic_identity"
                ],
            },
            "event-trace": {
                "experiment_identity": experiment_identity,
                "resolved_runtime_profile_identity": profile_identity,
            },
            "snapshot-series": {
                "experiment_identity": experiment_identity,
                "resolved_runtime_profile_identity": profile_identity,
                "event_trace_identity": trace_identity,
            },
            "metric-dataset": {
                "experiment_identity": experiment_identity,
                "resolved_runtime_profile_identity": profile_identity,
            },
            primary_role: {
                "experiment_identity": experiment_identity,
                "resolved_runtime_profile_identity": profile_identity,
                "event_trace_identity": trace_identity,
                "snapshot_series_identity": snapshot_identity,
                "metric_dataset_identity": dataset_identity,
            },
        }
        for role, fields in expected.items():
            if any(
                results[role].get(member) != value for member, value in fields.items()
            ):
                raise InventoryRefusal(
                    "Runtime Artifact graph identity binding is stale"
                )


def _verify_execution_compound_coverage(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
    inventory: ExtensionInventory,
) -> None:
    """Reverse-check compound generated addresses from their actual owners."""
    found = {
        row
        for row in inventory.occurrences
        if row.pointer.startswith(("/artifacts/", "/results/"))
        and row.location in {"json-pointer", "call-path", "snapshot-name"}
    }
    expected: set[TokenOccurrence] = set()
    law = "/meta_format/language_definitions/wire_schema_protocol_roles/trace_structure"
    evidence_law = (
        "/meta_format/language_definitions/wire_schema_protocol_roles/"
        "runtime_evidence_structure"
    )

    def member(surface: str, role: str) -> tuple[dict[str, Any], str]:
        values = graph.get(surface)
        if not isinstance(values, dict):
            raise InventoryRefusal(f"{surface} is missing for compound coverage")
        kind = _artifact_protocol_binding(kernel, graph, role)[0]
        rows = [
            (value, _child("/" + surface, label))
            for label, value in values.items()
            if isinstance(value, dict) and value.get("artifact_kind") == kind
        ]
        if len(rows) != 1:
            raise InventoryRefusal(f"{role} has no unique generated member")
        return rows[0]

    if graph.get("artifacts") is not None:
        debug, pointer = member("artifacts", "debug-map")
        source_keys = {
            source_pointer: token
            for token, source_pointer, _, location, _, _ in _source_address_links(
                kernel, graph
            )
            if location == "key" and token.role == "source-field"
        }
        model_law = "/meta_format/language_definitions/wire_schema_protocol_roles/model_structure"
        for index, entry in enumerate(debug["entries"]):
            current = "/source"
            target = f"{pointer}/entries/{index}/source_pointer"
            for projection, segment in enumerate(
                _json_pointer_segments(entry["source_pointer"])
            ):
                current = _child(current, segment)
                token = source_keys.get(current)
                if token is not None:
                    expected.add(
                        TokenOccurrence(
                            token,
                            target,
                            "reference",
                            model_law,
                            "json-pointer",
                            str(projection),
                        )
                    )

    if graph.get("results") is not None:
        if not isinstance(graph.get("artifacts"), dict) or not isinstance(
            graph.get("experiment"), dict
        ):
            raise InventoryRefusal("Runtime compound addresses have no owner graph")
        rir, _ = member("artifacts", "rir-semantic-payload")
        trace, trace_pointer = member("results", "event-trace")
        series, series_pointer = member("results", "snapshot-series")
        experiment = graph["experiment"]
        source = graph.get("source")
        if not isinstance(source, dict):
            raise InventoryRefusal("Runtime compound addresses have no Source owner")
        source_projection = _source_projection(kernel, graph)
        if source_projection is None:
            raise InventoryRefusal(
                "Runtime compound addresses have no Source projection"
            )
        model = source_projection.value["manifest"]["id"]
        exp_id = experiment["id"]
        entrypoints = {row["id"]: row for row in rir["entrypoints"]}
        call_sites = {
            row["identity"]: (
                (row["parent_operation"]["package"], row["parent_operation"]["id"]),
                row["site"],
                (row["operation"]["package"], row["operation"]["id"]),
            )
            for row in rir["call_sites"]
        }

        def call_path(value: str, pointer: str) -> None:
            segments = _call_path_segments(value)
            entrypoint = entrypoints.get(segments[0])
            if entrypoint is None:
                raise InventoryRefusal("Runtime call path has no Entry Point owner")
            expected.add(
                TokenOccurrence(
                    AuthorityToken("source-entrypoint", (model,), segments[0]),
                    pointer,
                    "reference",
                    law,
                    "call-path",
                    "0",
                )
            )
            parent = (
                entrypoint["operation"]["package"],
                entrypoint["operation"]["id"],
            )
            for index, segment in enumerate(segments[1:], start=1):
                if re.fullmatch(r"@[0-9]+", segment):
                    continue
                matches = [
                    row for row in call_sites.values() if row[:2] == (parent, segment)
                ]
                if len(matches) != 1:
                    raise InventoryRefusal("Runtime call path site has no RIR owner")
                expected.add(
                    TokenOccurrence(
                        AuthorityToken("operation-site", parent, segment),
                        pointer,
                        "reference",
                        law,
                        "call-path",
                        str(index),
                    )
                )
                parent = matches[0][2]

        for event_index, event in enumerate(trace["events"]):
            event_pointer = f"{trace_pointer}/events/{event_index}"
            for call_index, call in enumerate(event["calls"]):
                pointer = f"{event_pointer}/calls/{call_index}/site"
                site = call_sites.get(call["call_site_identity"])
                if site is None:
                    raise InventoryRefusal("Trace call has no RIR call-site owner")
                expected.update(
                    {
                        TokenOccurrence(
                            AuthorityToken(
                                "language.operations", site[0][:1], site[0][1]
                            ),
                            pointer,
                            "reference",
                            law,
                            "call-path",
                            "0",
                        ),
                        TokenOccurrence(
                            AuthorityToken("operation-site", site[0], site[1]),
                            pointer,
                            "reference",
                            law,
                            "call-path",
                            "1",
                        ),
                    }
                )
            for schedule_index, schedule in enumerate(event["schedules"]):
                call_path(
                    schedule["call_path"],
                    f"{event_pointer}/schedules/{schedule_index}/call_path",
                )
        for index, snapshot in enumerate(series["snapshots"]):
            expected.add(
                TokenOccurrence(
                    AuthorityToken(
                        "experiment-scenario", (exp_id,), snapshot["scenario"]
                    ),
                    f"{series_pointer}/snapshots/{index}/name",
                    "reference",
                    evidence_law,
                    "snapshot-name",
                    "",
                )
            )
    if found != expected:
        raise InventoryRefusal(
            "generated compound address coverage is incomplete or misowned"
        )


def validate_extension_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Reverse-check authored owners and declaration coverage independently.

    This verifier does not call the reader. Nested reference coverage remains an
    explicit unfinished obligation until the corresponding consuming-law pass
    is implemented; require_complete still refuses that inventory.
    """
    _verify_execution_artifact_graph(kernel, graph)
    source_projection = _source_projection(kernel, graph)
    validate_inventory_occurrences(kernel, graph, inventory)
    _verify_execution_compound_coverage(kernel, graph, inventory)
    # The execution projection verifier consumes external positions as seeds;
    # the remaining reverse checks below still validate those seeds before
    # this validation can succeed.
    from schema2_execution_coverage_support import validate_execution_coverage

    validate_execution_coverage(kernel, graph, inventory)
    judgment_expected = {
        *_experiment_judgment_links(kernel, graph),
        *_experiment_input_judgment_links(kernel, graph),
        *_resolved_judgment_links(kernel, graph),
        *_runtime_metric_selector_links(kernel, graph),
    }
    judgment_roots = {
        pointer + "/selector"
        for _, _, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.experiment_metric_judgments"
        )
    }
    judgment_actual = {
        row
        for row in inventory.occurrences
        if row.token.role == "experiment-metric-label"
        or any(
            row.pointer == root or row.pointer.startswith(root + "/")
            for root in judgment_roots
        )
    }
    if (
        judgment_actual != judgment_expected
        or inventory.reserved & {row.token for row in judgment_expected}
        or any(
            gap.pointer == root or gap.pointer.startswith(root + "/")
            for gap in inventory.uncovered
            for root in judgment_roots
        )
    ):
        raise InventoryRefusal("Experiment judgment labels are incomplete or misowned")
    lowering_links = set(_lowering_path_links(kernel, graph))
    lowering_roots = [
        pointer
        for _, _, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.model_lowerings"
        )
    ]

    def in_lowering(pointer):
        return any(
            pointer == root or pointer.startswith(root + "/") for root in lowering_roots
        )

    if any(in_lowering(gap.pointer) for gap in inventory.uncovered):
        raise InventoryRefusal("lowering has an invented unresolved owner")
    lowering_expected = set(
        _close_projection_occurrences(
            graph,
            lowering_links,
            [
                (source, target)
                for source, target, _, _ in _contract_vector_projections(kernel, graph)
            ],
        )
    )
    lowering_positions = {row.pointer for row in lowering_expected}
    lowering_actual = {
        row
        for row in inventory.occurrences
        if row.pointer in lowering_positions
        or row.token.role == "kernel.lowering-address"
    }

    def interpreted_lowering(rows):
        return {
            (row.token, row.pointer, row.use, row.location, row.projection)
            for row in rows
        }

    if interpreted_lowering(lowering_actual) != interpreted_lowering(
        lowering_expected
    ) or {row.token for row in lowering_expected} != {
        token for token in inventory.reserved if token.role == "kernel.lowering-address"
    }:
        raise InventoryRefusal("lowering address coverage is incomplete or misowned")
    fixed_tokens = {row.token for row in lowering_expected}
    for _, name, pointer, target, _ in _declared_metadata_links(kernel, graph):
        if in_lowering(pointer) and target.startswith("kernel."):
            role, scoped = _declared_target_role(kernel, target)
            if scoped:
                raise InventoryRefusal(
                    "lowering Kernel reference has an unexpected scope"
                )
            fixed_tokens.add(AuthorityToken(role, (), name))
    lowering_tokens = {
        row.token for row in inventory.occurrences if in_lowering(row.pointer)
    }
    if inventory.reserved & lowering_tokens != fixed_tokens:
        raise InventoryRefusal(
            "lowering nominal and Kernel token partition is incorrect"
        )
    template_expected, template_reserved, template_roots, template_schemas = (
        _template_inventory(kernel, graph)
    )
    template_actual = {
        row
        for row in inventory.occurrences
        if any(
            row.pointer.startswith(root + "/")
            and row.pointer not in {root + "/id", root + "/artifact_kind"}
            for root in template_roots | template_schemas
        )
    }
    exhaustion_declaration = _template_exhaustion_declaration(kernel, graph)
    if [
        row
        for row in inventory.occurrences
        if row.token == exhaustion_declaration.token and row.use == "declaration"
    ] != [exhaustion_declaration]:
        raise InventoryRefusal(
            "Template exhaustion diagnostic declaration is omitted, duplicated, or misowned"
        )
    template_tokens = {row.token for row in template_expected}
    if (
        template_actual != template_expected
        or inventory.reserved & template_tokens != template_reserved
        or {
            gap.pointer
            for gap in inventory.uncovered
            if gap.pointer in template_schemas
        }
        != template_schemas - template_roots
    ):
        raise InventoryRefusal("Template occurrence coverage is incomplete or misowned")
    evidence_expected = set(_evidence_claim_links(kernel, graph))
    evidence_roots = [
        pointer
        for _, _, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.evidence_claim_kinds"
        )
    ]
    evidence_actual = {
        row
        for row in inventory.occurrences
        if any(
            row.pointer.startswith(root + "/") and row.pointer != root + "/id"
            for root in evidence_roots
        )
    }
    evidence_tokens = {row.token for row in evidence_expected}
    evidence_reserved = {
        token for token in evidence_tokens if token.role.startswith("kernel.")
    }
    if (
        evidence_actual != evidence_expected
        or inventory.reserved.intersection(evidence_tokens) != evidence_reserved
    ):
        raise InventoryRefusal(
            "Evidence claim occurrence coverage is incomplete or misowned"
        )
    replay_expected = set(_replay_links(kernel, graph))
    replay_positions = {o.pointer for o in replay_expected}
    if {
        o for o in inventory.occurrences if o.pointer in replay_positions
    } != replay_expected or not {
        o.token for o in replay_expected if o.token.role.startswith("kernel.")
    } <= inventory.reserved:
        raise InventoryRefusal(
            "Replay observation reference coverage is incomplete or misowned"
        )
    from schema2_model_vector_inventory_support import model_vector_inventory

    model_expected, model_roots, _, model_reserved = model_vector_inventory(
        kernel, graph
    )
    model_actual = {
        row
        for row in inventory.occurrences
        if any(
            row.pointer.startswith(root + "/") and row.pointer != root + "/id"
            for root in model_roots
        )
    }
    if (
        model_actual != model_expected
        or inventory.reserved.intersection(row.token for row in model_expected)
        != model_reserved
    ):
        raise InventoryRefusal(
            "Model vector occurrence coverage is incomplete or misowned"
        )
    scheduler_rule_expected, scheduler_rule_roots = _scheduler_rule_vector_inventory(
        kernel, graph
    )
    scheduler_rule_actual = {
        row
        for row in inventory.occurrences
        if any(
            row.pointer.startswith(root + "/") and row.pointer != root + "/id"
            for root in scheduler_rule_roots
        )
    }
    if (
        scheduler_rule_actual != scheduler_rule_expected
        or inventory.reserved.intersection(row.token for row in scheduler_rule_expected)
    ):
        raise InventoryRefusal(
            "scheduler/rule vector coverage is incomplete or misowned"
        )
    _verify_constructor_address_coverage(kernel, graph, inventory)
    operation_expected = {
        row
        for row in _operation_vector_links(kernel, graph)
        if isinstance(row, TokenOccurrence)
    }
    operation_roots = {pointer for *_, pointer in _operation_vector_rows(kernel, graph)}
    operation_actual = {
        row
        for row in inventory.occurrences
        if any(
            row.pointer.startswith(root + "/") and row.pointer != root + "/id"
            for root in operation_roots
        )
    }
    if operation_actual != operation_expected:
        raise InventoryRefusal(
            "Operation vector occurrence coverage is incomplete or misowned"
        )
    vector_expected = {
        (row.token, row.pointer, row.use, row.location, row.projection)
        for row in _value_vector_links(kernel, graph)
        if isinstance(row, TokenOccurrence)
    }
    vector_actual = {
        (row.token, row.pointer, row.use, row.location, row.projection)
        for row in inventory.occurrences
    }
    if not vector_expected <= vector_actual:
        raise InventoryRefusal(
            "value vector occurrence coverage is incomplete or misowned"
        )
    vector_roots = {pointer for _, _, pointer in _value_vector_rows(kernel, graph)}
    vector_observed_positions = {
        row
        for row in vector_actual
        if any(
            row[1].startswith(root + "/") and row[1] != root + "/id"
            for root in vector_roots
        )
    }
    if not vector_observed_positions <= vector_expected:
        raise InventoryRefusal(
            "value vector occurrence has no interpreted identity role"
        )
    if any(
        row[3] == "json-pointer"
        and row not in vector_expected
        and row
        not in {
            (o.token, o.pointer, o.use, o.location, o.projection)
            for o in model_expected
        }
        and not row[1].startswith("/artifacts/")
        for row in vector_actual
    ):
        raise InventoryRefusal(
            "json-pointer occurrence has no declared path projection"
        )
    vector_positions = {row[1:] for row in vector_expected}
    if any(
        row[1:] in vector_positions and row not in vector_expected
        for row in vector_actual
    ):
        raise InventoryRefusal("value vector occurrence has the wrong role or owner")
    address_expected = {
        (token, pointer, use, location, projection)
        for token, pointer, use, location, projection, _ in _source_address_links(
            kernel, graph
        )
    }
    address_actual = {
        (o.token, o.pointer, o.use, o.location, o.projection)
        for o in inventory.occurrences
    }
    if not address_expected <= address_actual:
        raise InventoryRefusal(
            "Source field address coverage is incomplete or misowned"
        )
    profile_roots = {
        pointer
        for _, _, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.resolution_profiles"
        )
    }
    profile_expected = {
        row
        for row in address_expected
        if any(
            row[1] == root or row[1].startswith(root + "/") for root in profile_roots
        )
    }
    profile_actual = {
        row
        for row in address_actual
        if row[0].role == "source-field"
        and any(
            row[1] == root or row[1].startswith(root + "/") for root in profile_roots
        )
    }
    if profile_actual != profile_expected:
        raise InventoryRefusal(
            "Source field address occurrence is extra, incomplete, or misowned"
        )
    source_fields = {row[0] for row in address_expected}
    if inventory.reserved & source_fields:
        raise InventoryRefusal("Source annotated field ownership is misclassified")
    address_positions = {row[1:] for row in address_expected}
    if any(
        row[1:] in address_positions and row not in address_expected
        for row in address_actual
    ):
        raise InventoryRefusal("Source field address occurrence has a wrong owner")
    if any(
        row[3] == "member-path"
        and row not in address_expected
        and not row[1].startswith(("/artifacts/", "/results/"))
        for row in address_actual
    ):
        raise InventoryRefusal(
            "member-path occurrence has no declared address projection"
        )
    source_format_role = _source_format_role(kernel, graph)
    _verify_formula_coverage(kernel, graph, inventory)
    rule_required = set()
    for _, rule, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.rules"
    ):
        rule_required.add(
            (
                AuthorityToken("rule-judgment", (), rule["judgment"]),
                pointer + "/judgment",
                "declaration",
                "value",
            )
        )
        for pi, premise in enumerate(rule["premises"]):
            for variable in premise["bind"]:
                rule_required.add(
                    (
                        AuthorityToken("rule-variable", (rule["id"],), variable),
                        _child(f"{pointer}/premises/{pi}/bind", variable),
                        "declaration",
                        "key",
                    )
                )
        for field, term in rule["conclusion"]["fields"].items():
            if term["tag"] == "variable":
                rule_required.add(
                    (
                        AuthorityToken("rule-variable", (rule["id"],), term["name"]),
                        _child(pointer + "/conclusion/fields", field) + "/name",
                        "reference",
                        "value",
                    )
                )
    for _, lowering, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.model_lowerings"
    ):
        for member in ("rule_chain", "structured_rule_chain"):
            for i, step in enumerate(lowering[member]):
                rule_required.add(
                    (
                        AuthorityToken("rule-judgment", (), step["judgment"]),
                        f"{pointer}/{member}/{i}/judgment",
                        "reference",
                        "value",
                    )
                )
    rule_actual = {
        (o.token, o.pointer, o.use, o.location) for o in inventory.occurrences
    }
    if not rule_required <= rule_actual:
        raise InventoryRefusal(
            "Language rule binding or selection coverage is incomplete"
        )
    rule_positions = {
        (pointer, use, location) for _, pointer, use, location in rule_required
    }
    if any(
        row[1:] in rule_positions and row not in rule_required for row in rule_actual
    ):
        raise InventoryRefusal(
            "Language rule occurrence has an incorrect role or owner"
        )
    meta = kernel["meta_format"]
    if "ldb_root" in graph:
        root, shape = graph["ldb_root"], meta["language_bundle"]
        if (
            not _consumer_b_definition_is_closed(
                root,
                {
                    "required_members": shape["required_members"],
                    "field_types": shape["member_types"],
                },
                {},
            )
            or not _consumer_b_definition_is_closed(
                root["resources"], shape["resources"], {}
            )
            or root["kernel_identity"] != kernel["content_identity"]
            or not all(
                _consumer_b_definition_is_closed(row, shape["package_descriptor"], {})
                for row in root["package_descriptors"]
            )
        ):
            raise InventoryRefusal(
                "LDB root or descriptor has an unclassified member or binding"
            )
    projections = meta["package_release"]["semantic_closure"]["projections"]
    unique = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.identifiers.unique"
    )
    scopes = {
        row["path"].removeprefix("language_bundle."): row.get("scope")
        for row in unique["arguments"]["collections"]
    }
    actual = {
        (o.token, o.pointer, o.use)
        for o in inventory.occurrences
        if o.location == "value"
    }
    required: set[tuple[AuthorityToken, str, str]] = set()
    required.update(
        (token, pointer, use)
        for token, pointer, use, _ in _reason_vector_links(kernel, graph)
    )
    for token, pointer, use, _ in _wire_protocol_links(kernel, graph):
        required.add((token, pointer, use))
        if token.role.startswith("kernel.") and token not in inventory.reserved:
            raise InventoryRefusal("Kernel wire protocol role was made renameable")
    required.update(
        (token, pointer, use)
        for token, pointer, use, _ in _projection_collection_links(kernel, graph)
    )
    all_occurrences = {
        (o.token, o.pointer, o.use, o.location, o.projection)
        for o in inventory.occurrences
    }
    relation_links, relation_projections, relation_surfaces, relation_vectors = (
        _operation_relation_surfaces(kernel, graph)
    )

    def relation_position(pointer):
        return any(
            pointer == root or pointer.startswith(root + "/")
            for root in relation_surfaces
        ) or any(
            pointer.startswith(root + "/") and pointer != root + "/id"
            for root in relation_vectors
        )

    # Recompute the complete projection closure from independently derived
    # relation roles and already-owned external instruction occurrences. Never
    # seed it with the caller's claimed roles inside the relation surfaces.
    seeds = relation_links | {
        row for row in inventory.occurrences if not relation_position(row.pointer)
    }
    expected_relations = {
        (row.token, row.pointer, row.use, row.location, row.projection)
        for row in _close_projection_occurrences(graph, seeds, relation_projections)
        if relation_position(row.pointer)
    }
    observed_relations = {row for row in all_occurrences if relation_position(row[1])}
    if (
        expected_relations != observed_relations
        or not {o.token for o in relation_links if o.token.role.startswith("kernel.")}
        <= inventory.reserved
    ):
        raise InventoryRefusal("Operation relation coverage is incomplete or misowned")
    for source, target, vector, operation in _contract_vector_projections(
        kernel, graph
    ):
        if operation is not None:
            required.add((operation, vector + "/operation", "reference"))
        source_occurrences = [
            o
            for o in inventory.occurrences
            if (o.pointer == source and o.location != "key")
            or o.pointer.startswith(source + "/")
        ]
        expected_occurrences = set()
        for occurrence in source_occurrences:
            expected = (
                occurrence.token,
                target + occurrence.pointer.removeprefix(source),
                "reference",
                occurrence.location,
                occurrence.projection,
            )
            expected_occurrences.add(expected)
            if expected not in all_occurrences:
                raise InventoryRefusal(
                    "contract vector projection coverage is incomplete"
                )
        if any(
            row not in expected_occurrences
            for row in all_occurrences
            if row[1] == target or row[1].startswith(target + "/")
        ):
            raise InventoryRefusal(
                "contract vector projection contains a wrong semantic role"
            )
    for token, pointer, use, _ in _resolution_binding_links(kernel, graph):
        required.add((token, pointer, use))
        if token.role.startswith("kernel.") and token not in inventory.reserved:
            raise InventoryRefusal("Kernel relation role was made renameable")
    for token, pointer, use, _ in _resolution_policy_fixed_links(kernel, graph):
        required.add((token, pointer, use))
        if token not in inventory.reserved:
            raise InventoryRefusal("Kernel Resolution selector was made renameable")
    lowering_rows = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_lowerings")
    )
    for _, lowering, pointer in lowering_rows:
        policy = lowering["assignment_policy"]
        pp = pointer + "/assignment_policy"
        required.add(
            (
                AuthorityToken("assignment-policy", (lowering["id"],), policy["id"]),
                pp + "/id",
                "declaration",
            )
        )
        for ri, row in enumerate(policy["roles"]):
            rp = f"{pp}/roles/{ri}"
            required.add(
                (
                    AuthorityToken("language.quantity.symbol_roles", (), row["role"]),
                    rp + "/role",
                    "reference",
                )
            )
            for mi, mode in enumerate(row["modes"]):
                required.add(
                    (
                        AuthorityToken(
                            "assignment-mode",
                            (lowering["id"], policy["id"], row["role"]),
                            mode["id"],
                        ),
                        f"{rp}/modes/{mi}/id",
                        "declaration",
                    )
                )
    if source_projection is not None:
        default_profiles = [
            profile
            for _, profile, _ in _authority_path_rows(
                kernel, graph, "language_bundle.language.resolution_profiles"
            )
            if profile.get("default") is True
        ]
        if len(default_profiles) != 1:
            raise InventoryRefusal("Source has no unique default profile")
        selected = [
            row
            for _, row, _ in lowering_rows
            if row["id"] == default_profiles[0]["model_lowering"]
        ]
        if len(selected) != 1:
            raise InventoryRefusal("Source has no unique assignment policy")
        lowering = selected[0]
        for mi, module in enumerate(source_projection.value["modules"]):
            module_pointer = f"{_child('/source', 'modules')}/{mi}"
            symbols_pointer = _child(module_pointer, "symbols")
            for si, symbol in enumerate(module["symbols"]):
                required.add(
                    (
                        AuthorityToken(
                            "assignment-mode",
                            (
                                lowering["id"],
                                lowering["assignment_policy"]["id"],
                                symbol["role"],
                            ),
                            symbol["value_policy"]["mode"],
                        ),
                        f"{symbols_pointer}/{si}/value_policy/mode",
                        "reference",
                    )
                )
    for _, unit, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.quantity.units"
    ):
        required.add(
            (
                AuthorityToken("unit-dimension", (), unit["dimension"]),
                pointer + "/dimension",
                "declaration",
            )
        )
    for _, definition, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.structured_operations"
    ):
        required.add(
            (
                AuthorityToken(
                    "language.constructors", (), definition["owner_constructor"]
                ),
                pointer + "/owner_constructor",
                "reference",
            )
        )
        if "refusal_signal" in definition["law"]:
            required.add(
                (
                    AuthorityToken(
                        "diagnostic-signal",
                        ("runtime",),
                        definition["law"]["refusal_signal"],
                    ),
                    pointer + "/law/refusal_signal",
                    "reference",
                )
            )
    for owner, name, pointer, target, _ in _declared_metadata_links(kernel, graph):
        role, scoped = _declared_target_role(kernel, target)
        if role == source_format_role:
            continue
        token = AuthorityToken(
            role, (owner,) if scoped and owner is not None else (), name
        )
        required.add((token, pointer, "reference"))
        if target.startswith("kernel.") and token not in inventory.reserved:
            raise InventoryRefusal("declared Kernel primitive was made renameable")
    for pi, package in enumerate(graph["packages"]):
        owner, pp = package["id"], f"/packages/{pi}"
        required.add(
            (AuthorityToken("namespace", (), owner), pp + "/id", "declaration")
        )
        for projection in projections:
            if projection["authority_path"] == source_format_role:
                continue
            ci, entry = next(
                (i, e)
                for i, e in enumerate(package["semantic_closure"])
                if e["authority_path"] == projection["authority_path"]
            )
            root, member = projection["owners_path"].split(".")
            for ei, exported in enumerate(package[root][member]):
                di, definition = next(
                    (i, d)
                    for i, d in enumerate(entry["definitions"])
                    if (
                        d
                        if projection["key_member"] is None
                        else d[projection["key_member"]]
                    )
                    == exported
                )
                role = projection["authority_path"]
                scope = (owner,) if scopes.get(role) == "package" else ()
                if role == "language.nominal_types":
                    role, scope = "type", (owner,)
                token = AuthorityToken(role, scope, exported)
                dp = f"{pp}/semantic_closure/{ci}/definitions/{di}"
                if projection["key_member"] is not None:
                    dp += "/" + projection["key_member"]
                required.add((token, dp, "declaration"))
                required.add((token, f"{pp}/{root}/{member}/{ei}", "reference"))
                if projection["authority_path"] == "language.operations":
                    op = definition
                    op_scope, op_path = (owner, op["id"]), dp.rsplit("/", 1)[0]
                    for i, port in enumerate(op["inputs"]):
                        required.add(
                            (
                                AuthorityToken("operation-port", op_scope, port["id"]),
                                f"{op_path}/inputs/{i}/id",
                                "declaration",
                            )
                        )
                    if isinstance(op.get("result"), dict):
                        required.add(
                            (
                                AuthorityToken(
                                    "operation-result", op_scope, op["result"]["id"]
                                ),
                                op_path + "/result/id",
                                "declaration",
                            )
                        )
                    for i, outcome in enumerate(op.get("outcomes", [])):
                        required.add(
                            (
                                AuthorityToken(
                                    "operation-outcome", op_scope, outcome["id"]
                                ),
                                f"{op_path}/outcomes/{i}/id",
                                "declaration",
                            )
                        )
                    nodes = {
                        node["id"]: node for node in meta["runtime_program"]["nodes"]
                    }
                    pending = [(op["body"], op_path + "/body")]
                    while pending:
                        body, body_path = pending.pop()
                        for i, instruction in enumerate(body):
                            node, ip = nodes[instruction["node"]], f"{body_path}/{i}"
                            if node["result"]["kind"] in {"local", "draw"}:
                                required.add(
                                    (
                                        AuthorityToken(
                                            "operation-local",
                                            op_scope,
                                            instruction["target"],
                                        ),
                                        ip + "/target",
                                        "declaration",
                                    )
                                )
                            if node["semantics"]["operator"] in {
                                "bounded-pure-fold",
                                "invoke-operation",
                                "schedule-operation",
                                "cancel-event",
                            }:
                                required.add(
                                    (
                                        AuthorityToken(
                                            "operation-site",
                                            op_scope,
                                            instruction["site"],
                                        ),
                                        ip + "/site",
                                        "declaration",
                                    )
                                )
                            if node["result"]["kind"] in {
                                "composition",
                                "scheduled-event",
                            }:
                                result = instruction["result"]
                                if result["kind"] == "local":
                                    required.add(
                                        (
                                            AuthorityToken(
                                                "operation-local",
                                                op_scope,
                                                result["name"],
                                            ),
                                            ip + "/result/name",
                                            "declaration",
                                        )
                                    )
                            if node["semantics"]["operator"] == "named-integer-draw":
                                required.add(
                                    (
                                        AuthorityToken(
                                            "named-stream", (), instruction["stream"]
                                        ),
                                        ip + "/stream",
                                        "declaration",
                                    )
                                )
                            if node["semantics"]["operator"] == "guarded-outcome-block":
                                pending.append((instruction["body"], ip + "/body"))
        for i, exported in enumerate(package["exports"]["types"]):
            required.add(
                (
                    AuthorityToken("type", (owner,), exported["id"]),
                    f"{pp}/exports/types/{i}/id",
                    "declaration",
                )
            )
    for i, descriptor in enumerate(
        graph.get("ldb_root", {}).get("package_descriptors", [])
    ):
        required.add(
            (
                AuthorityToken("namespace", (), descriptor["id"]),
                f"/ldb_root/package_descriptors/{i}/id",
                "reference",
            )
        )
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        vp = f"/vector_sets/{vi}"
        required.add(
            (
                AuthorityToken("namespace", (), vector_set["package_id"]),
                vp + "/package_id",
                "reference",
            )
        )
        for member, use in (
            ("vector_definitions", "declaration"),
            ("vectors", "reference"),
        ):
            for i, row in enumerate(vector_set[member]):
                name = row["id"] if use == "declaration" else row
                path = f"{vp}/{member}/{i}" + ("/id" if use == "declaration" else "")
                owner = (
                    (vector_set["package_id"],)
                    if scopes.get("vectors") == "package"
                    else ()
                )
                required.add((AuthorityToken("vectors", owner, name), path, use))
    source_projection = _source_projection(kernel, graph)
    source = source_projection.value if source_projection is not None else None
    if source:
        model = source["manifest"]["id"]
        required.add(
            (
                AuthorityToken("source-model", (), model),
                "/source/manifest/id",
                "declaration",
            )
        )
        required.add(
            (
                AuthorityToken(
                    "source-module",
                    (model,),
                    _at(source, "manifest.entry_module".split(".")),
                ),
                "/source/manifest/entry_module",
                "reference",
            )
        )
        for i, namespace in enumerate(source["package_requirements"]):
            required.add(
                (
                    AuthorityToken("namespace", (), namespace),
                    f"{_child('/source', 'package_requirements')}/{i}",
                    "reference",
                )
            )
        for mi, module in enumerate(source["modules"]):
            scope, mp = (
                (model, module["id"]),
                f"{_child('/source', 'modules')}/{mi}",
            )
            required.add(
                (
                    AuthorityToken(
                        "source-module",
                        (model,),
                        module["id"],
                    ),
                    _child(mp, "id"),
                    "declaration",
                )
            )
            for ii, row in enumerate(module["imports"]):
                ip = f"{_child(mp, 'imports')}/{ii}"
                required.add(
                    (
                        AuthorityToken(
                            "source-type-alias",
                            scope,
                            row["alias"],
                        ),
                        _child(ip, "alias"),
                        "declaration",
                    )
                )
                required.add(
                    (
                        AuthorityToken(
                            "namespace",
                            (),
                            row["package"],
                        ),
                        _child(ip, "package"),
                        "reference",
                    )
                )
                required.add(
                    (
                        AuthorityToken(
                            "type",
                            (row["package"],),
                            row["symbol"],
                        ),
                        _child(ip, "symbol"),
                        "reference",
                    )
                )
            for si, row in enumerate(module["symbols"]):
                sp = f"{_child(mp, 'symbols')}/{si}"
                required.add(
                    (
                        AuthorityToken(
                            "source-symbol",
                            scope,
                            row["symbol"],
                        ),
                        _child(sp, "symbol"),
                        "declaration",
                    )
                )
                required.add(
                    (
                        AuthorityToken(
                            "source-type-alias",
                            scope,
                            row["type"],
                        ),
                        _child(sp, "type"),
                        "reference",
                    )
                )
        for ei, entry in enumerate(source.get("entrypoints", [])):
            ep = _child(_child("/source", "entrypoints"), ei)
            operation = entry["operation"]
            callee = (operation["package"], operation["id"])
            required.add(
                (
                    AuthorityToken("source-entrypoint", (model,), entry["id"]),
                    ep + "/id",
                    "declaration",
                )
            )
            required.add(
                (
                    AuthorityToken("namespace", (), callee[0]),
                    ep + "/operation/package",
                    "reference",
                )
            )
            required.add(
                (
                    AuthorityToken("language.operations", (), callee[1])
                    if scopes.get("language.operations") != "package"
                    else AuthorityToken("language.operations", callee[:1], callee[1]),
                    ep + "/operation/id",
                    "reference",
                )
            )
            operands = [(entry["result"], ep + "/result")]
            for ai, argument in enumerate(entry["arguments"]):
                ap = f"{ep}/arguments/{ai}"
                required.add(
                    (
                        AuthorityToken("operation-port", callee, argument["port"]),
                        ap + "/port",
                        "reference",
                    )
                )
                operands.append((argument["operand"], ap + "/operand"))
            for operand, op in operands:
                if operand["kind"] == "symbol":
                    required.add(
                        (
                            AuthorityToken(
                                "source-module", (model,), operand["module"]
                            ),
                            op + "/module",
                            "reference",
                        )
                    )
                    required.add(
                        (
                            AuthorityToken(
                                "source-symbol",
                                (model, operand["module"]),
                                operand["symbol"],
                            ),
                            op + "/symbol",
                            "reference",
                        )
                    )
    required = {
        (token, _source_pointer(source_projection, pointer), use)
        for token, pointer, use in required
    }
    if not required <= actual:
        first = sorted(required - actual, key=lambda row: row[1])[0]
        raise InventoryRefusal(
            f"missing or incorrectly owned declaration/export occurrence at {first[1]}"
        )
    required_paths = {(pointer, use) for _, pointer, use in required}
    for token, pointer, use in actual:
        if (pointer, use) in required_paths and (token, pointer, use) not in required:
            raise InventoryRefusal(f"wrong role or owner at {pointer}")


def _renamed_owner(
    token: AuthorityToken, correspondence: Mapping[AuthorityToken, AuthorityToken]
) -> tuple[str, ...]:
    def name(owner_token: AuthorityToken) -> str:
        target = correspondence.get(owner_token)
        return owner_token.name if target is None else target.name

    if token.role.startswith("model-vector-source-"):
        vector, *scope = token.owner
        transported = (name(AuthorityToken("vectors", (), vector)),)
        if not scope:
            return transported
        transported += (
            name(AuthorityToken("model-vector-source-model", (vector,), scope[0])),
        )
        if len(scope) == 1:
            return transported
        transported += (
            name(
                AuthorityToken(
                    "model-vector-source-module", (vector, scope[0]), scope[1]
                )
            ),
        )
        if len(scope) == 2:
            return transported
        if len(scope) == 3 and token.role.startswith("model-vector-source-formula-"):
            return (
                *transported,
                name(
                    AuthorityToken(
                        "model-vector-source-formula", (vector, *scope[:2]), scope[2]
                    )
                ),
            )
        raise InventoryRefusal("unknown Model vector Source token owner")
    if token.role in {"source-field", "template-field"}:
        schema_role, schema_id, *path = token.owner
        renamed = (schema_role, name(AuthorityToken(schema_role, (), schema_id)))
        original = (schema_role, schema_id)
        index = 0
        while index < len(path):
            if path[index] == "member" and index + 1 < len(path):
                member = path[index + 1]
                renamed = (
                    *renamed,
                    "member",
                    name(AuthorityToken(token.role, original, member)),
                )
                original = (*original, "member", member)
                index += 2
            elif path[index] == "items":
                renamed, original = (*renamed, "items"), (*original, "items")
                index += 1
            else:
                raise InventoryRefusal("Source field owner has an unknown data path")
        return renamed

    if not token.owner:
        return ()
    if token.role in {"vector-enum-member", "vector-record-field"}:
        if len(token.owner) < 2 or token.owner[1] not in {"comparison", "left"}:
            raise InventoryRefusal("unknown anonymous Type scope")
        original = token.owner[:2]
        transported = (
            name(AuthorityToken("vectors", (), token.owner[0])),
            token.owner[1],
        )
        i = 2
        while i < len(token.owner):
            step = token.owner[i]
            if step in {"element", "target"}:
                original, transported = (*original, step), (*transported, step)
                i += 1
            elif step == "field" and i + 1 < len(token.owner):
                field = token.owner[i + 1]
                renamed = name(AuthorityToken("vector-record-field", original, field))
                original, transported = (
                    (*original, "field", field),
                    (*transported, "field", renamed),
                )
                i += 2
            else:
                raise InventoryRefusal(
                    "anonymous Type owner has an unknown structural step"
                )
        return transported
    if token.role in {
        "vector-local",
        "vector-site",
        "scheduler-event",
        "scheduler-scenario",
    }:
        return (name(AuthorityToken("vectors", (), token.owner[0])),)
    if token.role == "claim-vector":
        return (
            name(AuthorityToken("language.evidence_claim_kinds", (), token.owner[0])),
        )
    if token.role == "rule-variable":
        return (name(AuthorityToken("language.rules", (), token.owner[0])),)
    if token.role == "constructor-member":
        return (
            name(AuthorityToken("language.constructors", (), token.owner[0])),
            token.owner[1],
        )
    if token.role in {"template-role", "template-derived", "template-judgment"}:
        return (
            name(
                AuthorityToken(
                    "language.template_admission_profiles", (), token.owner[0]
                )
            ),
        )
    if token.role == "formula-fixed-alias":
        return (
            name(AuthorityToken("language.resolution_profiles", (), token.owner[0])),
        )
    if token.role in {"recipe-binding", "resolution-judgment"}:
        return (
            name(AuthorityToken("language.resolution_profiles", (), token.owner[0])),
            *token.owner[1:],
        )
    if token.role in {"assignment-policy", "projection-collection"}:
        return (name(AuthorityToken("language.model_lowerings", (), token.owner[0])),)
    if token.role in {"experiment-scenario", "experiment-metric"}:
        return (name(AuthorityToken("experiment", (), token.owner[0])),)
    if token.role == "experiment-root-event":
        return (
            name(AuthorityToken("experiment", (), token.owner[0])),
            name(
                AuthorityToken("experiment-scenario", token.owner[:1], token.owner[1])
            ),
        )
    if token.role in {"experiment-observation", "experiment-window"}:
        return (
            name(AuthorityToken("experiment", (), token.owner[0])),
            name(AuthorityToken("experiment-metric", token.owner[:1], token.owner[1])),
        )
    if token.role == "assignment-mode":
        return (
            name(AuthorityToken("language.model_lowerings", (), token.owner[0])),
            name(AuthorityToken("assignment-policy", token.owner[:1], token.owner[1])),
            name(AuthorityToken("language.quantity.symbol_roles", (), token.owner[2])),
        )
    if token.role == "experiment-metric-label":
        return token.owner  # The selector path consists of fixed Kernel fields.
    if token.role == "diagnostic-signal":
        return token.owner  # Stage is the Kernel refusal-stage enum, not a namespace.
    if token.role.startswith("source-"):
        model = name(AuthorityToken("source-model", (), token.owner[0]))
        if len(token.owner) == 1:
            return (model,)
        module = name(AuthorityToken("source-module", token.owner[:1], token.owner[1]))
        if len(token.owner) == 2:
            return (model, module)
        if len(token.owner) == 3 and token.role.startswith("source-formula-"):
            formula = name(
                AuthorityToken("source-formula", token.owner[:2], token.owner[2])
            )
            return (model, module, formula)
        raise InventoryRefusal("unknown Source token owner")
    namespace = name(AuthorityToken("namespace", (), token.owner[0]))
    if len(token.owner) == 1:
        return (namespace,)
    if token.role in {"enum-member", "record-field"}:
        return (
            namespace,
            name(AuthorityToken("type", token.owner[:1], token.owner[1])),
        )
    if token.role == "operation-extension-member":
        original = token.owner[:2]
        transported = (
            namespace,
            name(
                AuthorityToken("language.operations", token.owner[:1], token.owner[1])
            ),
        )
        for member in token.owner[2:]:
            transported = (
                *transported,
                name(AuthorityToken(token.role, original, member)),
            )
            original = (*original, member)
        return transported
    if token.role.startswith("operation-"):
        owner = (
            namespace,
            name(
                AuthorityToken("language.operations", token.owner[:1], token.owner[1])
            ),
        )
        if token.role == "operation-slot-parameter":
            return (
                *owner,
                name(AuthorityToken("operation-slot", token.owner[:2], token.owner[2])),
            )
        return owner
    raise InventoryRefusal("unknown token ownership role")


def token_bijection_from_names(
    inventory: ExtensionInventory, names: Mapping[AuthorityToken, str]
) -> tuple[tuple[AuthorityToken, AuthorityToken], ...]:
    """Transport owner coordinates through a caller-provided name permutation.

    This constructs a candidate map; validation and complete coverage remain
    mandatory before a graph can be renamed.
    """
    provisional = {
        source: AuthorityToken(source.role, source.owner, name)
        for source, name in names.items()
    }
    return tuple(
        (
            source,
            AuthorityToken(
                source.role, _renamed_owner(source, provisional), target.name
            ),
        )
        for source, target in provisional.items()
    )
