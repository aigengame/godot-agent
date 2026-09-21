"""Public scalar Formula returns follow the admitted Operation result contract."""

from copy import deepcopy
import json

import pytest

from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import _model_source, _use_derived_value
from test_trace_protocol_structure import _authored, _graph
from test_current_namespace_public import _PublicCandidate, _members


def _return_case(kind):
    """Author raw inputs only; each consumer owns admission and interpretation."""
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    operations = {
        row["id"]: row
        for package in authored["packages"]
        if package["id"] == "core.quantity"
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
    }
    operation = operations["quantity.identity"]
    if kind in {"port", "empty-port"}:
        operation["result"]["source"] = {"kind": "port", "name": "value"}
    if kind == "empty-port":
        operation["body"] = []
    if kind in {"nested-local", "nested-operation-result", "unit-discard"}:
        child = operations["quantity.floor-zero"]
        binding = (
            {"kind": "operation-result"}
            if kind == "nested-operation-result"
            else {"kind": "local", "name": "result"}
        )
        operation["body"] = [
            {
                "node": "invoke",
                "site": "child",
                "operation": {"package": "core.quantity", "id": child["id"]},
                "arguments": [
                    {"port": "value", "operand": {"kind": "port", "port": "value"}}
                ],
                "result": binding,
                "outcomes": [],
            }
        ]
        operation["result"]["source"] = (
            {"kind": "operation-result", "site": "child"}
            if kind == "nested-operation-result"
            else {"kind": "local", "name": "result"}
        )
        if kind == "unit-discard":
            child["body"] = []
            child["result"] = {
                **deepcopy(
                    kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
                        "kernel-unit"
                    ]
                ),
                "access": "read",
                "id": "result",
                "discardable": True,
                "source": {"kind": "unit"},
            }
            child["resource_bounds"]["max_steps"] = 1
            operation["body"][0]["result"] = {"kind": "discard"}
            operation["body"].append(
                {"node": "copy", "target": "result", "value": "value"}
            )
        operation["resource_bounds"]["max_steps"] = (
            len(operation["body"]) + child["resource_bounds"]["max_steps"]
        )
    contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source = _model_source()
    formula = {
        "id": "derived-formula",
        "parameters": [{"id": "value", **deepcopy(contract)}],
        "result": deepcopy(contract),
        "body": {
            "nodes": [
                {
                    "id": "same",
                    "node": "operation-call",
                    "operation": {
                        "package": "core.quantity",
                        "id": "quantity.identity",
                    },
                    "arguments": [
                        {
                            "port": "value",
                            "operand": {"kind": "parameter", "parameter": "value"},
                        }
                    ],
                    "result": deepcopy(contract),
                }
            ],
            "result": {"kind": "local", "local": "same"},
        },
        "expression": "let same = identity(value);\nsame",
    }
    source["modules"][0]["formulas"] = [formula]
    source["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derived-formula"},
            "arguments": [
                {
                    "parameter": "value",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source)
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "module": source["modules"][0],
        "modules": source["modules"],
        "formula": formula,
    }
    return kernel, authored, source, request


@pytest.mark.parametrize(
    "kind", ["local", "port", "empty-port", "nested-local", "nested-operation-result"]
)
def test_scalar_formula_returns_compile_through_public_commands(tmp_path, kind):
    kernel, authored, source, request = _return_case(kind)
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.write_source(source)
    request_path = tmp_path / "formula.json"
    request_path.write_text(json.dumps(request))
    parsed = public.cli("formula", "parse", str(request_path))
    rendered = public.cli("formula", "render", str(request_path))
    assert parsed["body"] == request["formula"]["body"]
    assert rendered["expression"] == request["formula"]["expression"]
    assert public.cli("model", "check", str(public.source))["checked"] is True
    artifacts = _members(
        public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "35" * 32,
        )
    )
    assert len(artifacts) == 8


def test_unit_discard_requires_a_real_formula_invocation_program_boundary(tmp_path):
    kernel, authored, source, request = _return_case("unit-discard")
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.write_source(source)
    path = tmp_path / "formula.json"
    path.write_text(json.dumps(request))
    for command in ("parse", "render"):
        result = public.cli("formula", command, str(path), success=False)
        assert result["error"]["category"] == "refusal"
        assert (
            result["error"]["diagnostics"][0]["code"]
            == "language.formula_type_mismatch"
        )
    for command in ("check", "build"):
        args = ["model", command, str(public.source)]
        if command == "build":
            args.extend(
                ["--out", str(tmp_path / "build"), "--invocation-key", "46" * 32]
            )
        result = public.cli(*args, success=False)
        assert result["error"]["category"] == "refusal"
        assert (
            result["error"]["diagnostics"][0]["code"]
            == "language.formula_type_mismatch"
        )
    assert not (tmp_path / "build").exists()


def _runtime_case(kind):
    from test_schema2_experiment_cli import _rpg_model_source

    kernel, authored, _source, _request = _return_case(kind)
    source = _rpg_model_source()
    for formula in source["modules"][0]["formulas"]:
        parameter = formula["parameters"][0]
        contract = {
            key: deepcopy(value) for key, value in parameter.items() if key != "id"
        }
        formula["body"] = {
            "nodes": [
                {
                    "id": "returned",
                    "node": "operation-call",
                    "operation": {
                        "package": "core.quantity",
                        "id": "quantity.identity",
                    },
                    "arguments": [
                        {
                            "port": "value",
                            "operand": {
                                "kind": "parameter",
                                "parameter": parameter["id"],
                            },
                        }
                    ],
                    "result": contract,
                }
            ],
            "result": {"kind": "local", "local": "returned"},
        }
        formula["expression"] = f"let returned = identity({parameter['id']});\nreturned"
    return kernel, authored, source


@pytest.mark.parametrize("kind", ["port", "nested-operation-result"])
def test_scalar_returns_reach_initialization_event_observation_and_public_replay(
    tmp_path, kind
):
    from test_schema2_experiment_cli import _experiment
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import AdmittedRir, admit_rir
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from test_trace_protocol_structure import _index

    kernel, authored, source = _runtime_case(kind)
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.write_source(source)
    receipt = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "57" * 32,
    )
    rir = _members(receipt)["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = _experiment(build_receipt=receipt, base_damage=24)

    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(specification))
    assert (
        public.cli("experiment", "check", str(path), "--rir", rir_path)["checked"]
        is True
    )
    run = public.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        rir_path,
        "--out",
        str(tmp_path / "run"),
        "--invocation-key",
        "68" * 32,
    )
    members = _members(run)
    context = admit_authority_context(kernel, _index(kernel, public.ldb))
    assert isinstance(context, AdmittedAuthorityContext)
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment)
    assert validate_experiment_artifact_set(checked, members)
    (tmp_path / "actual-members.json").write_text(json.dumps(members, indent=2))
    original_receipt = str(
        __import__("pathlib").Path(run["manifest_locator"]).parent
        / "artifact-set-receipt.json"
    )
    replay = public.cli(
        "experiment",
        "replay",
        str(path),
        "--rir",
        rir_path,
        "--original-experiment-run-artifact-set-receipt",
        original_receipt,
        "--out",
        str(tmp_path / "replay"),
        "--invocation-key",
        "79" * 32,
    )
    assert _members(replay["artifact_set"])["replay-comparison"]["result"] == "matched"
    events = [
        row for row in members["event-trace"]["events"] if row["observation"] is None
    ]
    assert len(events) == 1
    assert events[0]["state_after"] == [
        {"name": "actor_mana", "value": 22},
        {"name": "target_health", "value": 76},
    ]
    assert any(row["result"] == 24 for row in events[0]["formula_evaluations"])


@pytest.mark.parametrize("field", ["operation_result_source", "result_source"])
def test_resealed_result_selector_and_renamed_substitute_refuse(field):
    from schema2_bootstrap_production_support import _consumer_a
    from test_trace_protocol_structure import _index

    kernel, authored, _source, _request = _return_case("local")
    profile = next(
        row
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
        for row in closure["definitions"]
        if row["default"]
    )
    profile["formula_resolution"]["notation_conversion"][field] = {
        "kind": "local",
        "source_member": "source",
        "name_member": "name",
    }
    report = _consumer_a(kernel, _index(kernel, _graph(kernel, authored)))
    assert report["admitted"] is False
    assert report["diagnostics"]


@pytest.mark.parametrize(
    "fault",
    ["unknown-kind", "missing-local", "missing-site", "wrong-owner", "discarded-site"],
)
def test_actual_return_producer_and_namespace_must_remain_closed(fault):
    from schema2_bootstrap_production_support import _consumer_a
    from test_trace_protocol_structure import _index

    kernel, authored, _source, _request = _return_case("nested-operation-result")
    operation = next(
        row
        for package in authored["packages"]
        if package["id"] == "core.quantity"
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "quantity.identity"
    )
    if fault == "unknown-kind":
        operation["result"]["source"] = {"kind": "foreign"}
    elif fault == "missing-local":
        operation["result"]["source"] = {"kind": "local", "name": "absent"}
    elif fault == "missing-site":
        operation["result"]["source"]["site"] = "absent"
    elif fault == "wrong-owner":
        operation["body"][0]["operation"]["package"] = "game.combat"
    else:
        operation["body"][0]["result"] = {"kind": "discard"}
    report = _consumer_a(kernel, _index(kernel, _graph(kernel, authored)))
    assert report["admitted"] is False
    assert report["diagnostics"]


def _renamed_return_case():
    """Keep a same-id decoy while an explicit new owner/formal/site returns input."""
    kernel, authored, source, request = _return_case("nested-operation-result")
    quantity = next(row for row in authored["packages"] if row["id"] == "core.quantity")
    original = next(
        row
        for closure in quantity["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "quantity.identity"
    )
    operation = deepcopy(original)
    owner = "example.returnowner"
    operation["inputs"][0]["id"] = "source_value"
    operation["body"][0]["arguments"][0]["operand"]["port"] = "source_value"
    operation["body"][0]["site"] = "child/~.site"
    operation["result"]["source"]["site"] = "child/~.site"
    notation = operation["extensions"]["standard.formula-notation"]
    notation["ordered_ports"] = ["source_value"]
    notation["name"] = "return_from_other_owner"
    vector_ids = [
        f"{owner}.{key}" for key in ("body", "effects", "resource_bounds", "extensions")
    ]
    operation["vectors"] = vector_ids
    package = deepcopy(
        next(row for row in authored["packages"] if row["id"] == "standard.compiler")
    )
    package["id"] = owner
    package["dependencies"] = {"required": ["core.quantity"], "optional": []}
    package["capabilities"] = {"provided": [], "required": ["quantity.lower"]}
    package["exports"] = {key: [] for key in package["exports"]}
    package["exports"]["operations"] = [operation["id"]]
    package["profiles"] = {key: [] for key in package["profiles"]}
    package["runtime_semantic_paths"] = ["language.operations"]
    for closure in package["semantic_closure"]:
        closure["definitions"] = (
            [operation] if closure["authority_path"] == "language.operations" else []
        )
    vectors = deepcopy(authored["vector_sets"][0])
    vectors["package_id"] = owner
    vectors["vectors"] = vector_ids
    vectors["vector_definitions"] = [
        {
            "id": identity,
            "kind": "operation-contract",
            "category": "positive",
            "operation": operation["id"],
            "probe": {"path": member},
            "expect": deepcopy(operation[member]),
        }
        for identity, member in zip(
            vector_ids,
            ("body", "effects", "resource_bounds", "extensions"),
            strict=True,
        )
    ]
    authored["packages"].append(package)
    authored["vector_sets"].append(vectors)
    descriptor = deepcopy(authored["ldb_root"]["package_descriptors"][0])
    descriptor["id"] = owner
    authored["ldb_root"]["package_descriptors"].append(descriptor)
    # The old owner still defines the same local id with a different result.
    original["body"] = [{"node": "constant", "target": "result", "literal": 0}]
    original["result"]["source"] = {"kind": "local", "name": "result"}
    original["resource_bounds"]["max_steps"] = 1
    source["package_requirements"].append(owner)
    formula = request["formula"]
    formula["body"]["nodes"][0]["operation"]["package"] = owner
    formula["body"]["nodes"][0]["arguments"][0]["port"] = "source_value"
    formula["expression"] = "let same = return_from_other_owner(value);\nsame"
    source["entrypoints"][0]["operation"]["package"] = owner
    source["entrypoints"][0]["arguments"][0]["port"] = "source_value"
    return kernel, authored, source, request


def _prepared_runtime_cli(
    tmp_path, run_cli, monkeypatch, *, limit=None, eager_fault=False
):
    """Install an admitted raw graph before the real CLI reads either input."""
    import gda_balancing.domain.authority.context as authority
    from test_trace_protocol_structure import _index
    from test_public_formula_runtime_seam import _build, _write_specification
    from test_schema2_experiment_cli import _experiment

    kernel, authored, source = _runtime_case("nested-operation-result")
    if limit is not None:
        profile = next(
            row
            for package in authored["packages"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.runtime_profiles"
            for row in closure["definitions"]
            if row["id"] == "standard.exact-int64-event-v1"
        )
        profile["resource_bounds"]["max_node_steps"] = limit
    if eager_fault:
        operation = next(
            row
            for package in authored["packages"]
            if package["id"] == "core.quantity"
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.operations"
            for row in closure["definitions"]
            if row["id"] == "quantity.identity"
        )
        # Returning an input does not erase this later, unused authored work.
        operation["result"]["source"] = {"kind": "port", "name": "value"}
        operation["body"].extend(
            [
                {"node": "constant", "target": "maximum", "literal": 2**63 - 1},
                {"node": "constant", "target": "one", "literal": 1},
                {"node": "add", "target": "unused", "left": "maximum", "right": "one"},
            ]
        )
        operation["resource_bounds"]["max_steps"] += 3
        # This witness targets initializer eagerness. Keep the original bounded
        # damage slot, whose smaller resource contract must still refuse 8 steps.
        from test_schema2_experiment_cli import _rpg_model_source

        original = next(
            row
            for row in _rpg_model_source()["modules"][0]["formulas"]
            if row["id"] == "mitigated-damage"
        )
        source["modules"][0]["formulas"] = [
            deepcopy(original) if row["id"] == original["id"] else row
            for row in source["modules"][0]["formulas"]
        ]
    context = authority.admit_authority_context(
        kernel, _index(kernel, _graph(kernel, authored))
    )
    assert isinstance(context, authority.AdmittedAuthorityContext), context
    monkeypatch.setattr(authority, "_PACKAGED_CONTEXT", context)
    receipt, rir_path, rir = _build(tmp_path, run_cli, source)
    specification = _experiment(build_receipt=receipt, base_damage=24)
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    return context, rir, rir_path, specification, spec_path


@pytest.mark.parametrize(
    ("phase", "before", "charged"),
    [
        ("initialization", 0, 5),
        ("event", 5, 10),
        ("observation", 32, 37),
    ],
)
@pytest.mark.parametrize("offset", [-1, 0, 1], ids=["below", "at", "above"])
def test_nested_scalar_returns_preserve_exact_formula_reservation_boundaries(
    tmp_path, run_cli, monkeypatch, phase, before, charged, offset
):
    from test_public_formula_runtime_seam import _observe_programs, _run, _initial_frame
    from gda_balancing.domain.model import admit_rir
    from gda_balancing.domain.experiment import (
        check_experiment_value,
        CheckedExperiment,
    )
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )

    limit = charged + offset
    context, rir, rir_path, specification, spec_path = _prepared_runtime_cli(
        tmp_path, run_cli, monkeypatch, limit=limit
    )
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert stderr == ""
    target = next(row for row in calls if row["phase"] == phase)
    program = target["program"]
    assert [row["instruction"]["node"] for row in program["body"]] == [
        "constant",
        "less-than",
        "if",
        "copy",
        "copy",
    ]
    assert program["resource_bounds"]["max_steps"] == 5
    assert target["before"] == before
    assert target["after"] == charged
    if offset < 0:
        fault = target["fault"]
        assert fault.signal == "step-limit"
        assert fault.program == program["identity"]
        assert fault.frame_identity == target["frame"]
    else:
        assert "fault" not in target
        assert target["value"] == 85
    result = json.loads(stdout)
    if phase == "observation" and offset >= 0:
        assert code == 0, stdout
        members = _members(result)
        assert (
            members["snapshot-series"]["snapshots"][-1]["continuation"][
                "resource_ledger"
            ]["node_steps"]
            == charged
        )
    else:
        assert code == 2, stdout
        error = result["error"]
        assert error["stage"] == "runtime"
        assert error["diagnostics"][0]["code"] == "runtime.step_limit_exceeded"
        if phase == "initialization" and offset < 0:
            assert target["frame"] == _initial_frame(rir, specification)
            assert "terminal_audit" not in error
            assert not (tmp_path / "run-02").exists()
            return
        members = _members(error["terminal_audit"])
        audit = members["runtime-terminal-audit"]
        committed = int(phase == "observation")
        assert len(audit["committed_trace_prefix"]) == committed
        assert audit["last_snapshot_record"]["values"] == [
            {"name": "actor_mana", "value": 22 if committed else 30},
            {"name": "target_health", "value": 76 if committed else 100},
        ]
        assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
        if offset < 0:
            assert audit["budget_counters"]["node_steps"] == charged
            assert audit["last_snapshot_identity"] == target["frame"]
    checked = check_experiment_value(
        specification,
        admit_rir(rir, authority_context=context),
        authority_context=context,
    )
    assert isinstance(checked, CheckedExperiment)
    assert validate_experiment_artifact_set(checked, members)


def test_nested_scalar_cache_hits_reserve_the_same_work_and_preserve_all_artifacts(
    tmp_path, run_cli, monkeypatch
):
    from test_public_formula_runtime_seam import _observe_programs, _run

    _context, _rir, rir_path, _specification, spec_path = _prepared_runtime_cli(
        tmp_path, run_cli, monkeypatch
    )
    outputs = []
    for prewarm, key in ((False, "92"), (True, "93")):
        with monkeypatch.context() as scoped:
            calls = _observe_programs(scoped, prewarm=prewarm)
            code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path, key)
        assert (code, stderr) == (0, ""), stdout
        assert [(row["phase"], row["before"], row["after"]) for row in calls] == [
            ("initialization", 0, 5),
            ("event", 5, 10),
            ("observation", 32, 37),
        ]
        assert all(row["cache_growth"] == (0 if prewarm else 1) for row in calls)
        outputs.append(_members(json.loads(stdout)))
    assert outputs[0] == outputs[1]


def test_returned_port_does_not_skip_unused_nested_or_overflowing_work(
    tmp_path, run_cli, monkeypatch
):
    from test_public_formula_runtime_seam import _observe_programs, _run, _initial_frame

    _context, rir, rir_path, specification, spec_path = _prepared_runtime_cli(
        tmp_path, run_cli, monkeypatch, eager_fault=True
    )
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert (code, stderr) == (2, ""), stdout
    assert len(calls) == 1
    call = calls[0]
    assert call["phase"] == "initialization"
    assert call["before"] == 0
    assert call["after"] == 8
    assert call["fault"].signal == "numeric-overflow"
    assert call["fault"].frame_identity == _initial_frame(rir, specification)
    assert [row["instruction"]["node"] for row in call["program"]["body"]] == [
        "constant",
        "less-than",
        "if",
        "copy",
        "constant",
        "constant",
        "add",
        "copy",
    ]
    result = json.loads(stdout)["error"]
    assert result["diagnostics"][0]["code"] == "runtime.numeric_overflow"
    assert "terminal_audit" not in result
    assert not (tmp_path / "run-02").exists()


def test_public_scalar_return_keeps_namespace_formal_and_site_ownership(tmp_path):
    kernel, authored, source, request = _renamed_return_case()
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.write_source(source)
    path = tmp_path / "formula.json"
    path.write_text(json.dumps(request))
    assert (
        public.cli("formula", "parse", str(path))["body"] == request["formula"]["body"]
    )
    assert (
        public.cli("formula", "render", str(path))["expression"]
        == request["formula"]["expression"]
    )
    assert public.cli("model", "check", str(public.source))["checked"] is True
    members = _members(
        public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "81" * 32,
        )
    )
    formula = members["rir-semantic-payload"]["formulas"][0]
    assert formula["body"]["nodes"][0]["operation"]["package"] == "example.returnowner"
    assert formula["body"]["nodes"][0]["result"]["domain"] == {
        "minimum": 0,
        "maximum": 100,
    }


def _two_formal_return_case(return_port):
    """Notation order differs from canonical formal order; one actual is literal."""
    kernel, authored, source, request = _return_case("empty-port")
    operation = next(
        row
        for package in authored["packages"]
        if package["id"] == "core.quantity"
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for row in closure["definitions"]
        if row["id"] == "quantity.identity"
    )
    formal = operation["inputs"][0]
    operation["inputs"] = [
        {**deepcopy(formal), "id": name} for name in ("first", "second")
    ]
    for selected_formal in operation["inputs"]:
        # Reuse the admitted positive integer literal profile's exact formal
        # contract; arbitrary closed intervals do not select that profile.
        selected_formal["domain"] = {
            "kind": "closed-interval",
            "minimum": 1,
            "maximum": 2**63 - 1,
        }
    operation["result"]["domain"] = deepcopy(operation["inputs"][0]["domain"])
    operation["result"]["source"]["name"] = return_port
    operation["extensions"]["standard.formula-notation"]["ordered_ports"] = [
        "second",
        "first",
    ]
    vector = next(
        row
        for vector_set in authored["vector_sets"]
        if vector_set["package_id"] == "core.quantity"
        for row in vector_set["vector_definitions"]
        if row["id"] == "formula.notation.quantity.identity"
    )
    vector["expect"] = deepcopy(operation["extensions"])
    request["formula"]["parameters"][0]["domain"]["minimum"] = 1
    request["formula"]["result"]["domain"]["minimum"] = 1
    for symbol in source["modules"][0]["symbols"]:
        symbol["domain"]["minimum"] = 1
    node = request["formula"]["body"]["nodes"][0]
    node["arguments"] = [
        {"port": "first", "operand": {"kind": "parameter", "parameter": "value"}},
        {"port": "second", "operand": {"kind": "literal", "value": 7}},
    ]
    node["result"]["domain"] = (
        {"minimum": 7, "maximum": 7}
        if return_port == "second"
        else {"minimum": 1, "maximum": 100}
    )
    request["formula"]["result"]["domain"] = deepcopy(node["result"]["domain"])
    for symbol in source["modules"][0]["symbols"]:
        if symbol["symbol"] == "derived_value":
            symbol["domain"] = deepcopy(node["result"]["domain"])
        elif symbol["symbol"] == "output_value":
            symbol["domain"] = {"minimum": 1, "maximum": 2**63 - 1}
    request["formula"]["expression"] = "let same = identity(7, value);\nsame"
    argument = source["entrypoints"][0]["arguments"][0]
    source["entrypoints"][0]["arguments"] = [
        {**deepcopy(argument), "port": name} for name in ("first", "second")
    ]
    return kernel, authored, source, request


@pytest.mark.parametrize("return_port", ["first", "second"])
def test_scalar_return_uses_formal_identity_and_actual_literal_contract(
    tmp_path, run_cli, monkeypatch, return_port
):
    import gda_balancing.domain.authority.context as authority
    from test_trace_protocol_structure import _index
    from test_public_formula_runtime_seam import _build
    from gda_balancing.domain.model import admit_rir, AdmittedRir

    kernel, authored, source, request = _two_formal_return_case(return_port)
    context = authority.admit_authority_context(
        kernel, _index(kernel, _graph(kernel, authored))
    )
    assert isinstance(context, authority.AdmittedAuthorityContext), context
    monkeypatch.setattr(authority, "_PACKAGED_CONTEXT", context)
    path = tmp_path / "formula.json"
    path.write_text(json.dumps(request))
    for command, member in (("parse", "body"), ("render", "expression")):
        code, out, err = run_cli(["formula", command, str(path)])
        assert (code, err) == (0, ""), out
        assert json.loads(out)[member] == request["formula"][member]
    _receipt, _rir_path, rir = _build(tmp_path, run_cli, source)
    assert isinstance(admit_rir(rir, authority_context=context), AdmittedRir)
    assert (
        rir["formulas"][0]["body"]["nodes"][0]["result"]["domain"]
        == request["formula"]["body"]["nodes"][0]["result"]["domain"]
    )
