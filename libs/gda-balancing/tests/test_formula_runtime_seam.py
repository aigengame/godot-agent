"""Formula conformance reaches the same evaluator and preserves frame semantics."""

import ast
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.domain.runtime.execution as runtime
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
)
import schema2_value_program_reference_support as reference
from schema2_value_program_production_support import evaluate_value_program_vector
from gda_balancing.domain.program_reachability import formula_lifecycle_phases


@pytest.fixture(scope="module")
def compiled_programs():
    source = (
        Path(__file__).parents[1]
        / "examples/schema2/progression-periodic-effect/model-source.json"
    )
    checked = check_model_source_value(json.loads(source.read_bytes()))
    assert isinstance(checked, CheckedModel), checked
    rir = cast(dict[str, Any], compile_checked_model(checked)["rir-semantic-payload"])
    contract = rir["selected_semantics"]["execution_laws"]["runtime_program"]
    return (
        {p["site"]["context"]["phase"]: p for p in rir["initialization_programs"]},
        contract["numeric"],
        {row["id"]: row for row in contract["nodes"]},
        formula_lifecycle_phases(contract),
    )


def test_vectors_observe_the_actual_formula_evaluator(monkeypatch):
    context = packaged_authority_context()
    bundle = cast(LanguageBundleIndex, context.language_bundle)
    vector = next(
        vector
        for vector_set in bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "formula.runtime.accept.initialization-and-event-frames"
    )

    def disabled_formula_evaluator(*args, **kwargs):
        raise RuntimeError("actual Formula evaluator disabled")

    monkeypatch.setattr(
        runtime, "_evaluate_formula_program", disabled_formula_evaluator
    )
    with pytest.raises(RuntimeError, match="actual Formula evaluator disabled"):
        evaluate_value_program_vector(context.kernel, vector, phase="initialization")
    assert reference.reference_evaluate_value_program_vector(vector) == vector["expect"]


@pytest.mark.parametrize("phase", ("initialization", "event", "observation"))
def test_formula_charge_precedes_cache_and_uses_compiled_bound(
    compiled_programs, phase
):
    programs, numeric, nodes, phases = compiled_programs
    program = programs[phase]
    assert len(program["body"]) == 2
    assert program["resource_bounds"]["max_steps"] == 3
    cache = {}
    kwargs: dict[str, Any] = dict(
        numeric=numeric,
        runtime_nodes=nodes,
        lifecycle_phases=phases,
        phase=phase,
        frame_identity="frame.first",
        runtime_limit=8,
        cache=cache,
    )
    operands = {"level": 2, "damage_per_level": 3}
    first = runtime._evaluate_formula_program(
        program, operands, consumed_steps=0, **kwargs
    )
    assert (first.value, first.consumed_steps, len(cache)) == (6, 3, 1)
    second = runtime._evaluate_formula_program(
        program, operands, consumed_steps=first.consumed_steps, **kwargs
    )
    assert (second.value, second.consumed_steps, len(cache)) == (6, 6, 1)
    retained = deepcopy(cache)
    with pytest.raises(runtime._InitializationProgramFault) as error:
        runtime._evaluate_formula_program(
            program, operands, consumed_steps=second.consumed_steps, **kwargs
        )
    fault = error.value
    assert (fault.signal, fault.consumed_steps) == ("step-limit", 9)
    assert fault.program == program["identity"]
    assert fault.evaluation_site_identity == program["site"]["identity"]
    assert fault.frame_identity == "frame.first"
    assert cache == retained


@pytest.mark.parametrize("phase", ("initialization", "event", "observation"))
def test_same_formula_operands_in_new_frames_have_distinct_cache_entries(
    compiled_programs, phase
):
    programs, numeric, nodes, phases = compiled_programs
    cache = {}
    consumed = 0
    for frame, expected_entries in (("first", 1), ("second", 2), ("first", 2)):
        result = runtime._evaluate_formula_program(
            programs[phase],
            {"level": 2, "damage_per_level": 3},
            numeric=numeric,
            runtime_nodes=nodes,
            lifecycle_phases=phases,
            frame_identity=frame,
            phase=phase,
            consumed_steps=consumed,
            runtime_limit=9,
            cache=cache,
        )
        consumed = result.consumed_steps
        assert result.value == 6
        assert len(cache) == expected_entries
    assert consumed == 9


def test_formula_numeric_refusal_preserves_the_actual_site_and_frame(compiled_programs):
    programs, _numeric, nodes, phases = compiled_programs
    program = programs["event"]
    cache = {}
    with pytest.raises(runtime._InitializationProgramFault) as error:
        runtime._evaluate_formula_program(
            program,
            {"level": 2, "damage_per_level": 3},
            numeric={"minimum": 0, "maximum": 5},
            runtime_nodes=nodes,
            lifecycle_phases=phases,
            frame_identity="refusing-event",
            phase="event",
            consumed_steps=1,
            runtime_limit=4,
            cache=cache,
        )
    fault = error.value
    assert (fault.signal, fault.consumed_steps) == ("numeric-overflow", 4)
    assert fault.program == program["identity"]
    assert (
        fault.evaluation_site_identity == program["body"][0]["evaluation_site_identity"]
    )
    assert fault.frame_identity == "refusing-event"
    assert cache == {}


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-node",
        "unsupported-node",
        "missing-member",
        "context",
        "phase",
        "frame",
        "numeric",
        "missing-value",
    ),
)
def test_invalid_formula_requests_do_not_pollute_or_hide_behind_cache(
    compiled_programs, mutation
):
    programs, numeric, nodes, phases = compiled_programs
    program = deepcopy(programs["initialization"])
    operands = {"level": 2, "damage_per_level": 3}
    cache = {}
    kwargs: dict[str, Any] = dict(
        numeric=numeric,
        runtime_nodes=nodes,
        lifecycle_phases=phases,
        frame_identity="frame",
        phase="initialization",
        consumed_steps=0,
        runtime_limit=3,
        cache=cache,
    )
    assert runtime._evaluate_formula_program(program, operands, **kwargs).value == 6
    retained = deepcopy(cache)
    if mutation == "unknown-node":
        program["body"][0]["instruction"]["node"] = "unknown"
    elif mutation == "unsupported-node":
        program["body"][0]["instruction"]["node"] = next(
            name
            for name, contract in nodes.items()
            if contract["family"] != "expression"
        )
    elif mutation == "missing-member":
        del program["body"][0]["instruction"]["right"]
    elif mutation == "context":
        program["site"]["context"]["phase"] = "event"
    elif mutation == "phase":
        kwargs["phase"] = "unknown"
    elif mutation == "frame":
        kwargs["frame_identity"] = ""
    elif mutation == "numeric":
        kwargs["numeric"] = {"minimum": 2, "maximum": 1}
    else:
        assert mutation == "missing-value"
        del operands["level"]
    with pytest.raises(ValueError):
        runtime._evaluate_formula_program(program, operands, **kwargs)
    assert cache == retained


def test_adapter_does_not_relabel_an_unexpected_numeric_error(monkeypatch):
    context = packaged_authority_context()
    bundle = cast(LanguageBundleIndex, context.language_bundle)
    vector = next(
        vector
        for vector_set in bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.runtime"
        for vector in vector_set["vector_definitions"]
        if vector["id"] == "formula.runtime.floor-divide.exact"
    )

    def unexpected_value_error(*args, **kwargs):
        raise ValueError("floor-divide divisor must be positive")

    monkeypatch.setattr(runtime, "_execute_value_instruction", unexpected_value_error)
    with pytest.raises(ValueError, match="floor-divide divisor must be positive"):
        evaluate_value_program_vector(context.kernel, vector, phase="event")


def test_reference_value_program_consumer_has_no_runtime_or_admission_imports():
    source = Path(reference.__file__).read_text(encoding="utf-8")
    modules = [
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    ]
    modules.extend(
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert all(
        not module.startswith("gda_balancing")
        or module == "gda_balancing.domain.canonical"
        for module in modules
        if module is not None
    )


@pytest.mark.parametrize(
    ("numeric", "left", "right", "expected"),
    (
        ({"minimum": 2, "maximum": 7}, 3, 4, 4),
        ({"minimum": -7, "maximum": -2}, -3, -4, -3),
    ),
)
def test_composed_maximum_boolean_intermediate_is_outside_numeric_domain(
    numeric, left, right, expected
):
    context = packaged_authority_context()
    bundle = cast(LanguageBundleIndex, context.language_bundle)
    vector = deepcopy(
        next(
            vector
            for vector_set in bundle.package_conformance_vector_sets
            if vector_set["package_id"] == "standard.runtime"
            for vector in vector_set["vector_definitions"]
            if vector["id"] == "formula.runtime.maximum.extrema"
        )
    )
    vector["input"]["numeric"] = numeric
    vector["input"]["operands"] = [
        {"name": "left", "value": left},
        {"name": "right", "value": right},
    ]
    expectation = {
        "cache_entries": 0,
        "charge": 2,
        "outcome": "admitted",
        "result": expected,
        "result_artifact": True,
        "signal": None,
        "site": vector["input"]["site"],
    }
    assert reference.reference_evaluate_value_program_vector(vector) == expectation
    for phase in ("initialization", "event", "observation"):
        assert (
            evaluate_value_program_vector(context.kernel, vector, phase=phase)
            == expectation
        )
