"""Real Experiment, Model-build, and Runtime-result inventory coverage."""

from copy import deepcopy
from dataclasses import replace

import pytest

from gda_balancing.application.experiment_execution import (
    ExperimentExecutionSuccess,
    execute_checked_experiment,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from priority_protocol_support import authorities, source, specification
from schema2_extension_inventory_support import (
    InventoryRefusal,
    _call_path_segments,
    _json_pointer_segments,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
)
from schema2_extension_renaming_support import (
    _call_path_values,
    _json_pointer_values,
    _snapshot_name_values,
)


@pytest.fixture(scope="module")
def priority_build_graph():
    kernel, language, turn = authorities()
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    model_source = source(turn)
    model = check_model_source_value(model_source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    admitted = admit_rir(rir, authority_context=context)
    assert isinstance(admitted, AdmittedRir), admitted
    authored = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
        "source": model_source,
    }
    baseline = read_extension_inventory(kernel, authored)
    return kernel, context, admitted, artifacts, authored, baseline


@pytest.fixture(scope="module", params=[False, True], ids=["baseline", "variant"])
def priority_full_graph(priority_build_graph, request):
    kernel, context, admitted, artifacts, authored, baseline = priority_build_graph
    experiment = specification(artifacts["rir-semantic-payload"], request.param)
    checked = check_experiment_value(experiment, admitted, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    execution = execute_checked_experiment(checked)
    assert isinstance(execution, ExperimentExecutionSuccess), execution
    results = {
        name: deepcopy(member.value) for name, member in execution.members.items()
    }
    assert len(results) == 6
    graph = {
        **authored,
        "experiment": experiment,
        "artifacts": artifacts,
        "results": results,
    }
    inventory = read_extension_inventory(kernel, graph)
    return kernel, graph, inventory, baseline


def test_real_build8_run6_replace_the_three_placeholder_gaps(priority_full_graph):
    kernel, graph, inventory, baseline = priority_full_graph
    validate_extension_inventory(kernel, graph, inventory)
    assert inventory.uncovered == baseline.uncovered
    assert {gap.pointer for gap in inventory.uncovered} == {
        "/packages/14/semantic_closure/25/definitions/0",
        "/vector_sets",
    }
    assert not any(
        gap.pointer == root or gap.pointer.startswith(root + "/")
        for gap in inventory.uncovered
        for root in ("/experiment", "/artifacts", "/results")
    )
    assert {value["artifact_kind"] for value in graph["artifacts"].values()} == {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
    assert {value["artifact_kind"] for value in graph["results"].values()} == {
        "evaluation-run",
        "evaluator-capability-manifest",
        "event-trace",
        "metric-dataset",
        "resolved-runtime-profile",
        "snapshot-series",
    }
    assert {token.name for token in inventory.tokens if token.role == "experiment"} == {
        graph["experiment"]["id"]
    }
    expected_roots = {
        event["root_event_ref"]
        for scenario in graph["experiment"]["scenarios"]
        for event in scenario["event_plan"]
    }
    assert {
        token.name
        for token in inventory.tokens
        if token.role == "experiment-root-event"
    } == expected_roots
    assert len(inventory.tokens) > len(baseline.tokens)
    assert len(inventory.occurrences) > len(baseline.occurrences)


@pytest.mark.parametrize("surface", ["experiment", "artifacts", "results"])
@pytest.mark.parametrize("mutation", ["omission", "misowner", "duplicate", "extra"])
def test_full_graph_surfaces_refuse_missing_or_forged_members(
    priority_full_graph, surface, mutation
):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    if surface == "experiment":
        experiment = graph["experiment"]
        if mutation == "omission":
            del experiment["acceptance"]
        elif mutation == "misowner":
            experiment["runtime"]["profile"] = "missing.runtime-profile"
        elif mutation == "duplicate":
            experiment["scenarios"].append(deepcopy(experiment["scenarios"][0]))
        else:
            experiment["unexpected_member"] = "forged"
    else:
        values = graph[surface]
        if mutation == "omission":
            values.pop(next(iter(values)))
        elif mutation == "duplicate":
            values["duplicate-member"] = deepcopy(next(iter(values.values())))
        elif mutation == "extra":
            next(iter(values.values()))["unexpected_member"] = "forged"
        elif surface == "artifacts":
            manifest = next(
                value
                for value in values.values()
                if value["artifact_kind"] == "capability-manifest"
            )
            manifest["packages"][0]["id"] = "missing.package"
        else:
            trace = next(
                value
                for value in values.values()
                if value["artifact_kind"] == "event-trace"
            )
            event = next(row for row in trace["events"] if row["operation"] is not None)
            event["operation"] = "missing-operation"
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, graph)


def test_compound_runtime_addresses_are_owned_without_hash_tokens(priority_full_graph):
    _, _, inventory, _ = priority_full_graph
    assert any(
        row.pointer.startswith("/artifacts/") and row.location == "json-pointer"
        for row in inventory.occurrences
    )
    assert any(
        row.pointer.startswith("/results/")
        and "/calls/" in row.pointer
        and row.pointer.endswith("/site")
        and row.location == "call-path"
        for row in inventory.occurrences
    )
    assert any(
        row.pointer.startswith("/results/")
        and row.pointer.endswith("/call_path")
        and row.location == "call-path"
        for row in inventory.occurrences
    )
    assert any(
        row.pointer.startswith("/results/")
        and row.pointer.endswith("/name")
        and row.location == "snapshot-name"
        for row in inventory.occurrences
    )
    assert not any(token.name.startswith("sha256:") for token in inventory.tokens)


def test_compound_address_rewriters_change_only_owner_derived_segments(
    priority_full_graph,
):
    _, graph, inventory, _ = priority_full_graph
    json_occurrence = next(
        row
        for row in inventory.occurrences
        if row.pointer.startswith("/artifacts/") and row.location == "json-pointer"
    )
    json_rows = [
        row
        for row in inventory.occurrences
        if row.pointer == json_occurrence.pointer and row.location == "json-pointer"
    ]
    json_edits = {
        int(row.projection): f"renamed/json~{index}"
        for index, row in enumerate(json_rows)
    }
    rewritten_pointer = _json_pointer_values(
        graph, {json_occurrence.pointer: json_edits}
    )[json_occurrence.pointer]
    pointer_segments = _json_pointer_segments(rewritten_pointer)
    assert all(
        pointer_segments[index] == target for index, target in json_edits.items()
    )

    call_occurrence = next(
        row
        for row in inventory.occurrences
        if row.pointer.startswith("/results/")
        and row.location == "call-path"
        and "/calls/" in row.pointer
    )
    call_rows = [
        row
        for row in inventory.occurrences
        if row.pointer == call_occurrence.pointer and row.location == "call-path"
    ]
    call_edits = {
        int(row.projection): f"renamed/call~{index}"
        for index, row in enumerate(call_rows)
    }
    rewritten_call = _call_path_values(graph, {call_occurrence.pointer: call_edits})[
        call_occurrence.pointer
    ]
    call_segments = _call_path_segments(rewritten_call)
    assert all(call_segments[index] == target for index, target in call_edits.items())

    snapshot = next(
        row for row in inventory.occurrences if row.location == "snapshot-name"
    )
    original_name = graph
    for segment in snapshot.pointer.split("/")[1:]:
        original_name = (
            original_name[int(segment)]
            if isinstance(original_name, list)
            else original_name[segment]
        )
    target = "renamed:scenario"
    rewritten_name = _snapshot_name_values(
        graph, {snapshot.pointer: (snapshot.token.name, target)}
    )[snapshot.pointer]
    assert rewritten_name == target + original_name[len(snapshot.token.name) :]


@pytest.mark.parametrize("surface", ["/experiment", "/results"])
@pytest.mark.parametrize("mutation", ["omission", "misowner", "extra-reserved"])
def test_metric_judgment_consumers_refuse_incomplete_or_forged_inventory(
    priority_full_graph, surface, mutation
):
    kernel, graph, inventory, _ = priority_full_graph
    occurrence = next(
        row
        for row in inventory.occurrences
        if row.pointer.startswith(surface + "/")
        and row.token.role == "experiment-metric-label"
    )
    if mutation == "omission":
        changed = replace(
            inventory,
            occurrences=tuple(
                row for row in inventory.occurrences if row != occurrence
            ),
        )
    elif mutation == "misowner":
        forged = replace(occurrence.token, owner=("forged-owner",))
        changed = replace(
            inventory,
            tokens=inventory.tokens | {forged},
            occurrences=tuple(
                replace(row, token=forged) if row == occurrence else row
                for row in inventory.occurrences
            ),
        )
    else:
        changed = replace(inventory, reserved=inventory.reserved | {occurrence.token})
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, changed)


@pytest.mark.parametrize(
    ("artifact_kind", "member"),
    [
        ("model-explanation", "control_nodes"),
        ("evaluator-capability-manifest", "instruction_nodes"),
    ],
)
def test_generated_node_lists_cannot_expand_kernel_reserved_owners(
    priority_full_graph, artifact_kind, member
):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    surface = "artifacts" if artifact_kind == "model-explanation" else "results"
    artifact = next(
        value
        for value in graph[surface].values()
        if value["artifact_kind"] == artifact_kind
    )
    if artifact_kind == "model-explanation":
        target = next(row for row in artifact["operation_explanations"] if row[member])[
            member
        ]
    else:
        target = artifact[member]
    target[0] = "forged-instruction-node"
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, graph)


def test_full_graph_bijection_transports_experiment_owner_scopes(priority_full_graph):
    _, _, inventory, _ = priority_full_graph
    renameable = sorted(inventory.tokens - inventory.reserved)
    pairs = dict(
        token_bijection_from_names(
            inventory,
            {token: f"mapped_{index}" for index, token in enumerate(renameable)},
        )
    )
    assert set(pairs) == set(renameable)
    experiment = next(token for token in renameable if token.role == "experiment")
    scenario = next(
        token for token in renameable if token.role == "experiment-scenario"
    )
    root = next(token for token in renameable if token.role == "experiment-root-event")
    assert pairs[scenario].owner == (pairs[experiment].name,)
    assert pairs[root].owner == (pairs[experiment].name, pairs[scenario].name)
