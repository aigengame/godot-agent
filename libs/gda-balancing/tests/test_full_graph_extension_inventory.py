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
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from priority_protocol_support import authorities, source, specification
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _artifact_protocol_binding,
    _call_path_segments,
    _renamed_owner,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
    validate_token_bijection,
)
from schema2_extension_renaming_support import (
    _apply_validated_extension_renaming,
)


def _member(kernel, graph, surface, role):
    kind = _artifact_protocol_binding(kernel, graph, role)[0]
    return next(
        value for value in graph[surface].values() if value["artifact_kind"] == kind
    )


def _reseal_result_graph(kernel, graph, *roles):
    """Reseal only the named generated results and their explicit identity edges."""
    from schema2_bootstrap_conformance_support import _identity_from_kernel

    for role in roles:
        artifact = _member(kernel, graph, "results", role)
        contract = _artifact_protocol_binding(kernel, graph, role)[2]
        artifact["content_identity"] = _identity_from_kernel(
            kernel, contract["identity_domain"], artifact
        )
        if role == "event-trace":
            _member(kernel, graph, "results", "snapshot-series")[
                "event_trace_identity"
            ] = artifact["content_identity"]
            primary = _member(kernel, graph, "results", "evaluation-run")
            primary["event_trace_identity"] = artifact["content_identity"]
        elif role == "snapshot-series":
            _member(kernel, graph, "results", "evaluation-run")[
                "snapshot_series_identity"
            ] = artifact["content_identity"]
        elif role == "metric-dataset":
            _member(kernel, graph, "results", "evaluation-run")[
                "metric_dataset_identity"
            ] = artifact["content_identity"]


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


@pytest.fixture(scope="module")
def priority_full_graphs(priority_build_graph):
    kernel, context, admitted, artifacts, authored, baseline = priority_build_graph
    graphs = {}
    authored_graphs = {}
    for variant in (False, True):
        experiment = specification(artifacts["rir-semantic-payload"], variant)
        checked = check_experiment_value(
            experiment, admitted, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        execution = execute_checked_experiment(checked)
        assert isinstance(execution, ExperimentExecutionSuccess), execution
        results = {
            name: deepcopy(member.value) for name, member in execution.members.items()
        }
        assert len(results) == 6
        authored_graph = {
            **authored,
            "experiment": experiment,
        }
        graph = {
            **authored_graph,
            "artifacts": artifacts,
            "results": results,
        }
        authored_graphs[variant] = authored_graph
        graphs[variant] = (graph, read_extension_inventory(kernel, graph))
    return kernel, graphs, baseline, authored_graphs


@pytest.fixture(scope="module", params=[False, True], ids=["baseline", "variant"])
def priority_full_graph(priority_full_graphs, request):
    kernel, graphs, baseline, _ = priority_full_graphs
    graph, inventory = graphs[request.param]
    return kernel, graph, inventory, baseline


@pytest.fixture(scope="module")
def priority_duplicate_local_graph():
    kernel, language, turn = authorities()
    packages = language["language"]["packages"]
    action = next(row for row in packages if row["id"] == "game.action")
    owner = next(row for row in packages if row["id"] == "game.turn")

    def operations(package):
        return next(
            row["definitions"]
            for row in package["semantic_closure"]
            if row["authority_path"] == "language.operations"
        )

    duplicate = deepcopy(
        next(row for row in operations(action) if row["id"] == "resolve")
    )
    assert all(row["id"] != "resolve" for row in operations(owner))
    duplicate["vectors"] = [
        name.replace("game.action.", "game.turn.") for name in duplicate["vectors"]
    ]
    operations(owner).append(duplicate)
    owner["exports"]["operations"].append("resolve")
    vector_sets = language.package_conformance_vector_sets
    action_vectors = next(
        row for row in vector_sets if row["package_id"] == "game.action"
    )
    owner_vectors = next(row for row in vector_sets if row["package_id"] == "game.turn")
    new_vectors = [
        {
            **deepcopy(row),
            "id": row["id"].replace("game.action.", "game.turn."),
        }
        for row in action_vectors["vector_definitions"]
        if row["id"]
        in next(op for op in operations(action) if op["id"] == "resolve")["vectors"]
    ]
    owner_vectors["vector_definitions"].extend(new_vectors)
    owner_vectors["vectors"].extend(row["id"] for row in new_vectors)
    _bind_package_vector_set(owner, owner_vectors, kernel=kernel)
    _reidentify_graph_root(language)
    model_source = source({**turn, ("game.turn", "resolve"): duplicate})
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    checked_model = check_model_source_value(model_source, authority_context=context)
    assert isinstance(checked_model, CheckedModel), checked_model
    artifacts = compile_checked_model(checked_model)
    rir = artifacts["rir-semantic-payload"]
    admitted = admit_rir(rir, authority_context=context)
    assert isinstance(admitted, AdmittedRir), admitted
    experiment = specification(rir, False)
    checked = check_experiment_value(experiment, admitted, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    execution = execute_checked_experiment(checked)
    assert isinstance(execution, ExperimentExecutionSuccess), execution
    graph = {
        "packages": deepcopy(language.package_releases),
        "ldb_root": deepcopy(language.root),
        "vector_sets": deepcopy(language.package_conformance_vector_sets),
        "source": model_source,
        "experiment": experiment,
        "artifacts": artifacts,
        "results": {
            name: deepcopy(member.value) for name, member in execution.members.items()
        },
    }
    return kernel, graph


def test_same_local_operation_id_keeps_distinct_selected_namespace_owners(
    priority_duplicate_local_graph,
):
    kernel, graph = priority_duplicate_local_graph
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert {
        AuthorityToken("language.operations", (namespace,), "resolve")
        for namespace in ("game.action", "game.turn")
    } <= inventory.tokens


def test_same_local_id_cannot_forge_scheduled_namespace_after_reseal(
    priority_duplicate_local_graph,
):
    kernel, original = priority_duplicate_local_graph
    graph = deepcopy(original)
    trace = _member(kernel, graph, "results", "event-trace")
    schedule = next(row for event in trace["events"] for row in event["schedules"])
    assert schedule["operation"] == {"package": "game.action", "id": "resolve"}
    schedule["operation"]["package"] = "game.turn"
    series = _member(kernel, graph, "results", "snapshot-series")
    catalog = next(
        row
        for row in series["event_catalog"]
        if row["event_id"] == schedule["event_id"]
    )
    catalog["event_spec"]["operation"]["package"] = "game.turn"
    _reseal_result_graph(
        kernel, graph, "event-trace", "snapshot-series", "evaluation-run"
    )
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, graph)


def test_real_build8_run6_closes_the_reachable_extension_graph(priority_full_graph):
    kernel, graph, inventory, baseline = priority_full_graph
    validate_extension_inventory(kernel, graph, inventory)
    baseline.require_complete()
    inventory.require_complete()
    assert inventory.uncovered == baseline.uncovered == ()
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


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
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


def test_runtime_metric_selector_projections_are_in_inventory(priority_full_graph):
    kernel, graph, inventory, _ = priority_full_graph
    trace = _member(kernel, graph, "results", "event-trace")
    trace_name = next(
        name for name, value in graph["results"].items() if value is trace
    )
    observed = next(
        index for index, event in enumerate(trace["events"]) if event.get("observation")
    )
    dataset = _member(kernel, graph, "results", "metric-dataset")
    dataset_name = next(
        name for name, value in graph["results"].items() if value is dataset
    )
    metric_labels = {
        row.pointer
        for row in inventory.occurrences
        if row.token.role == "experiment-metric-label"
    }
    assert {
        f"/results/{trace_name}/events/{observed}/observation/window/kind",
        f"/results/{dataset_name}/samples/0/source",
        f"/results/{dataset_name}/samples/0/provenance/observation_source",
    } <= metric_labels


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
@pytest.mark.parametrize("kind", ["stale", "resealed"])
def test_metric_sample_selector_refuses_even_after_coordinated_reseal(
    priority_full_graph, kind
):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    sample = _member(kernel, graph, "results", "metric-dataset")["samples"][0]
    assert (
        sample["source"] == graph["experiment"]["metrics"][0]["observation"]["source"]
    )
    sample["source"] = "event" if sample["source"] == "snapshot" else "snapshot"
    if kind == "resealed":
        _reseal_result_graph(kernel, graph, "metric-dataset", "evaluation-run")
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, graph)
    if kind == "resealed":
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(
                kernel, graph, read_extension_inventory(kernel, original)
            )


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
@pytest.mark.parametrize("location", ["json-pointer", "call-path", "snapshot-name"])
@pytest.mark.parametrize("mutation", ["omission", "owner", "use", "law"])
def test_generated_compound_coverage_refuses_missing_or_forged_claims(
    priority_full_graph, location, mutation
):
    kernel, graph, inventory, _ = priority_full_graph
    occurrence = next(
        row
        for row in inventory.occurrences
        if row.location == location
        and row.pointer.startswith(("/artifacts/", "/results/"))
    )
    forged = replace(
        occurrence,
        token=replace(occurrence.token, owner=("foreign.namespace",)),
    )

    def corrupt(row):
        if row != occurrence:
            return row
        if mutation == "owner":
            return forged
        if mutation == "use":
            return replace(row, use="declaration")
        if mutation == "law":
            return replace(row, law="/forged/law")
        return row

    changed = replace(
        inventory,
        tokens=inventory.tokens | ({forged.token} if mutation == "owner" else set()),
        occurrences=tuple(
            corrupt(row)
            for row in inventory.occurrences
            if row != occurrence or mutation != "omission"
        ),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, changed)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_generated_call_path_index_cannot_be_invented(priority_full_graph):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    trace = _member(kernel, graph, "results", "event-trace")
    schedule = next(row for event in trace["events"] for row in event["schedules"])
    original_path = schedule["call_path"]
    schedule["call_path"] += "/@17"
    assert _call_path_segments(schedule["call_path"]) == [original_path, "@17"]
    _reseal_result_graph(
        kernel, graph, "event-trace", "snapshot-series", "evaluation-run"
    )
    with pytest.raises(InventoryRefusal, match="scheduled call path"):
        read_extension_inventory(kernel, graph)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_schedule_rejects_unselected_existing_operation_after_reseal(
    priority_full_graph,
):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    trace = _member(kernel, graph, "results", "event-trace")
    schedule = next(row for event in trace["events"] for row in event["schedules"])
    schedule["operation"] = {"package": "core.quantity", "id": "quantity.add"}
    _reseal_result_graph(
        kernel, graph, "event-trace", "snapshot-series", "evaluation-run"
    )
    with pytest.raises(InventoryRefusal, match="selected RIR owner"):
        read_extension_inventory(kernel, graph)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_schedule_rejects_a_different_selected_target_with_child_echoes_resealed(
    priority_full_graph,
):
    kernel, original, _, _ = priority_full_graph
    graph = deepcopy(original)
    trace = _member(kernel, graph, "results", "event-trace")
    schedule = next(row for event in trace["events"] for row in event["schedules"])
    assert schedule["operation"] == {"package": "game.action", "id": "resolve"}
    schedule["operation"]["id"] = "append-counter"
    child = next(
        row for row in trace["events"] if row["event_id"] == schedule["event_id"]
    )
    child["operation"] = "append-counter"
    series = _member(kernel, graph, "results", "snapshot-series")
    catalog = next(
        row
        for row in series["event_catalog"]
        if row["event_id"] == schedule["event_id"]
    )
    catalog["event_spec"]["operation"]["id"] = "append-counter"
    _reseal_result_graph(
        kernel, graph, "event-trace", "snapshot-series", "evaluation-run"
    )
    with pytest.raises(InventoryRefusal, match="scheduled|schedule"):
        read_extension_inventory(kernel, graph)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_generated_operation_local_name_keeps_namespace_owner(
    priority_full_graph,
):
    kernel, graph, inventory, _ = priority_full_graph
    occurrence = next(
        row
        for row in inventory.occurrences
        if row.pointer.startswith("/results/")
        and row.pointer.endswith("/operation/id")
        and row.token.role == "language.operations"
        and row.token.owner == ("game.action",)
    )
    forged = replace(
        occurrence,
        token=AuthorityToken(
            "language.operations", ("game.turn",), occurrence.token.name
        ),
    )
    changed = replace(
        inventory,
        tokens=inventory.tokens | {forged.token},
        occurrences=tuple(
            forged if row == occurrence else row for row in inventory.occurrences
        ),
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, changed)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_every_new_generated_occurrence_is_required_by_reverse_coverage(
    priority_full_graph,
):
    kernel, graph, inventory, baseline = priority_full_graph
    baseline_rows = set(baseline.occurrences)
    roots = ("/experiment/", "/artifacts/", "/results/")
    assert not any(row.pointer.startswith(roots) for row in baseline_rows)
    generated = [
        row
        for row in inventory.occurrences
        if row.pointer.startswith(roots) and not row.token.role.startswith("kernel.")
    ]
    assert {row.pointer.split("/")[1] for row in generated} == {
        "experiment",
        "artifacts",
        "results",
    }
    # Batches keep this differential test bounded while including every new
    # generated occurrence at least once. The focused tests above remove a
    # single compound use and forge individual owners and laws.
    chunks = [set(generated[index::16]) for index in range(16)]
    assert set().union(*chunks) == set(generated)
    assert sum(map(len, chunks)) == len(generated)
    for removed in chunks:
        changed = replace(
            inventory,
            occurrences=tuple(
                value for value in inventory.occurrences if value not in removed
            ),
        )
        with pytest.raises(InventoryRefusal):
            validate_extension_inventory(kernel, graph, changed)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
def test_reverse_rejects_unobserved_forged_kernel_reserved_token(priority_full_graph):
    kernel, graph, inventory, _ = priority_full_graph
    forged = AuthorityToken("kernel.meta_format.runtime_program.nodes", (), "forged")
    assert forged not in inventory.tokens
    assert forged not in inventory.reserved
    changed = replace(inventory, reserved=inventory.reserved | {forged})
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, changed)


@pytest.mark.parametrize(
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
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
    "priority_full_graph", [False], indirect=True, ids=["baseline"]
)
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


def _stable_union_bijection(inventories):
    """Build one deterministic rename relation for every supplied full graph."""
    renameable = set().union(
        *(inventory.tokens - inventory.reserved for inventory in inventories)
    )
    parent = {token: token for token in renameable}

    def find(token):
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    # One authored position can carry several authority roles. Those roles must
    # receive one spelling even though their complete token identities remain
    # distinct. Positions from separate graphs are intentionally not conflated.
    for inventory in inventories:
        by_position = {}
        for occurrence in inventory.occurrences:
            if occurrence.token not in renameable:
                continue
            position = (
                occurrence.pointer,
                occurrence.location,
                occurrence.projection,
            )
            by_position.setdefault(position, set()).add(occurrence.token)
        for tokens in by_position.values():
            first, *remaining = sorted(tokens)
            for token in remaining:
                union(first, token)

    components = {}
    for token in sorted(renameable):
        components.setdefault(find(token), []).append(token)
    original_names = {
        token.name
        for inventory in inventories
        for token in inventory.tokens | inventory.reserved
    }
    names = {}
    next_name = 0
    for tokens in sorted(components.values(), key=lambda values: values[0]):
        candidate = f"renamed{next_name}"
        while candidate in original_names:
            next_name += 1
            candidate = f"renamed{next_name}"
        names.update({token: candidate for token in tokens})
        next_name += 1

    pairs = tuple(sorted(token_bijection_from_names(inventories[0], names)))
    sources = [source for source, _ in pairs]
    targets = [target for _, target in pairs]
    assert set(sources) == renameable
    assert len(sources) == len(set(sources))
    assert len(targets) == len(set(targets))
    assert all(source.name != target.name for source, target in pairs)
    return pairs


@pytest.fixture(scope="module")
def priority_full_graph_bijection(priority_full_graphs):
    _, graphs, _, _ = priority_full_graphs
    inventories = tuple(graphs[variant][1] for variant in (False, True))
    return _stable_union_bijection(inventories)


def test_full_authored_graphs_apply_one_exhaustive_injective_union_bijection(
    priority_full_graphs, priority_full_graph_bijection
):
    kernel, graphs, _, authored_graphs = priority_full_graphs
    union_pairs = priority_full_graph_bijection
    union_map = dict(union_pairs)
    inventories = {variant: graphs[variant][1] for variant in (False, True)}
    union_domain = set().union(
        *(inventory.tokens - inventory.reserved for inventory in inventories.values())
    )
    assert set(union_map) == union_domain
    assert len(union_map) == len(set(union_map.values()))

    common = set(inventories[False].tokens - inventories[False].reserved) & set(
        inventories[True].tokens - inventories[True].reserved
    )
    case_maps = {}
    for variant, (graph, inventory) in graphs.items():
        validate_extension_inventory(kernel, graph, inventory)
        inventory.require_complete()
        renameable = inventory.tokens - inventory.reserved
        pairs = tuple(pair for pair in union_pairs if pair[0] in renameable)
        case_maps[variant] = dict(pairs)

        # This check is independent from the authoring helper, which validates
        # the relation again before changing any input.
        validate_token_bijection(inventory, pairs)
        assert set(case_maps[variant]) == renameable
        assert len(pairs) == len(set(case_maps[variant].values()))
        assert renameable <= {
            occurrence.token
            for occurrence in inventory.occurrences
            if not occurrence.pointer.startswith(("/artifacts/", "/results/"))
        }

        original_authored = authored_graphs[variant]
        authored_tokens = {
            occurrence.token
            for occurrence in inventory.occurrences
            if not occurrence.pointer.startswith(("/artifacts/", "/results/"))
        }
        authored_reserved = inventory.reserved & authored_tokens
        assert authored_tokens - authored_reserved == renameable
        renamed = _apply_validated_extension_renaming(kernel, graph, inventory, pairs)
        renamed_inventory = read_extension_inventory(kernel, renamed)
        validate_extension_inventory(kernel, renamed, renamed_inventory)
        renamed_inventory.require_complete()
        transported_reserved = frozenset(
            AuthorityToken(
                token.role,
                _renamed_owner(token, case_maps[variant])
                if token.role in {"source-field", "template-field"}
                else token.owner,
                token.name,
            )
            for token in authored_reserved
        )
        assert renamed_inventory.reserved == transported_reserved
        assert renamed_inventory.tokens - renamed_inventory.reserved == set(
            case_maps[variant].values()
        )
        assert renameable.isdisjoint(renamed_inventory.tokens)

        inverse_pairs = tuple((target, source) for source, target in pairs)
        restored = _apply_validated_extension_renaming(
            kernel, renamed, renamed_inventory, inverse_pairs
        )
        assert canonical_bytes(restored) == canonical_bytes(original_authored)

    assert {token: case_maps[False][token] for token in common} == {
        token: case_maps[True][token] for token in common
    }


@pytest.mark.parametrize("variant", [False, True], ids=["baseline", "variant"])
@pytest.mark.parametrize("mutation", ["omission", "duplicate"])
def test_full_graph_union_bijection_refuses_omitted_or_duplicate_map_member(
    priority_full_graphs, priority_full_graph_bijection, variant, mutation
):
    _, graphs, _, _ = priority_full_graphs
    inventory = graphs[variant][1]
    renameable = inventory.tokens - inventory.reserved
    pairs = [pair for pair in priority_full_graph_bijection if pair[0] in renameable]
    if mutation == "omission":
        pairs.pop()
        match = "domain is not the complete inventory"
    else:
        pairs[1] = (pairs[1][0], pairs[0][1])
        match = "duplicate source or target"
    with pytest.raises(InventoryRefusal, match=match):
        validate_token_bijection(inventory, pairs)
