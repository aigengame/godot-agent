"""Request preparation reuse and alias-independent Model specialization (#873)."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Barrier
from types import FrameType
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.admission import admit_authorities
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.model import _admission, _compilation, _lowering
from gda_balancing.domain.model._execution_closure import close_execution_dependencies
from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import (
    _model_source,
    _package_vector_set,
    _reidentify_language_bundle,
)


_EXAMPLES = Path(__file__).parents[1] / "examples" / "schema2"
_ARTIFACTS = {
    "build-receipt",
    "capability-manifest",
    "debug-map",
    "model-explanation",
    "package-lock",
    "resolution-receipt",
    "resolved-model",
    "rir-semantic-payload",
}


class _PreparationTrace:
    """Observe real calls without replacing a compiler or admission implementation."""

    def __init__(self) -> None:
        self.calls: Counter[tuple[str, str]] = Counter()
        self.projections: list[dict[str, Any]] = []
        self.formula_results: list[tuple[Any, Any, Any]] = []
        self.charges: list[tuple[str, int, int]] = []
        self.specialized = False
        self.post_specialization_checks: set[str] = set()
        self._watched = {
            function.__code__: function.__name__
            for function in (
                _lowering.lowering_inputs,
                _lowering._resolved_source_symbols,
                _lowering._resolved_formulas_and_bindings,
                _lowering._runtime_projection,
                close_execution_dependencies,
                _lowering._specialize_operation_formula_slots,
                _lowering._resolved_entrypoints,
                _lowering._resolved_call_sites,
                _admission.admit_resolved_model,
                _compilation.validate_compiled_artifacts,
            )
        }

    def profile(self, frame: FrameType, event: str, result: Any) -> None:
        name = self._watched.get(frame.f_code)
        if name is None:
            return
        parent = frame
        owner = "source"
        while parent is not None:
            if parent.f_code is _admission.admit_resolved_model.__code__:
                owner = "imported-artifact"
                break
            parent = parent.f_back
        if event == "call":
            self.calls[owner, name] += 1
            if owner == "source" and self.specialized:
                self.post_specialization_checks.add(name)
        elif event == "return":
            if name == "_specialize_operation_formula_slots" and owner == "source":
                self.specialized = True
            if name == "_runtime_projection":
                if owner == "source" and result is not None:
                    self.projections.append(deepcopy(result))
            elif name == "close_execution_dependencies":
                budget = frame.f_locals["consume"].__self__
                self.charges.append((owner, budget.used, budget.limit))
            elif name == "_resolved_formulas_and_bindings" and owner == "source":
                self.formula_results.append(deepcopy(result))


@contextmanager
def _observe_preparation():
    trace = _PreparationTrace()
    previous = sys.getprofile()
    sys.setprofile(trace.profile)
    try:
        yield trace
    finally:
        sys.setprofile(previous)


def _checked(source: dict[str, Any]) -> CheckedModel:
    checked = check_model_source_value(source)
    assert isinstance(checked, CheckedModel), checked
    return checked


def _artifact_bytes(checked: CheckedModel) -> dict[str, bytes]:
    artifacts = compile_checked_model(checked)
    assert set(artifacts) == _ARTIFACTS
    return {name: canonical_bytes(value) for name, value in artifacts.items()}


@pytest.mark.parametrize("command", ["check", "build"])
def test_public_model_request_prepares_once_and_keeps_artifact_admission(
    command, run_cli, tmp_path
):
    source_path = _EXAMPLES / "progression-periodic-effect" / "model-source.json"
    expected = _artifact_bytes(_checked(json.loads(source_path.read_bytes())))
    argv = ["model", command, str(source_path)]
    if command == "build":
        argv += ["--out", str(tmp_path / "artifacts"), "--invocation-key", "c7" * 32]

    with _observe_preparation() as trace:
        code, stdout, stderr = run_cli(argv)

    assert (code, stderr) == (0, ""), stdout
    if command == "build":
        receipt = json.loads(stdout)
        published = {
            row["logical_name"]: Path(row["locator"]).read_bytes()
            for row in receipt["member_locators"]
        }
        assert published == expected
    # Compilation always self-admits; a fresh publication validates again.
    independent_boundaries = 1 if command == "check" else 2
    assert (
        trace.calls["imported-artifact", "admit_resolved_model"]
        == independent_boundaries
    )
    assert (
        trace.calls["imported-artifact", "_runtime_projection"]
        == independent_boundaries
    )
    assert (
        trace.calls["source", "validate_compiled_artifacts"] == independent_boundaries
    )
    assert {
        "_resolved_entrypoints",
        "_resolved_call_sites",
    } <= trace.post_specialization_checks
    # The append capacity reason and diagnostic each add one catalog-row charge.
    assert {used for _, used, _ in trace.charges} == {508}
    assert {
        name: trace.calls["source", name]
        for name in (
            "_resolved_source_symbols",
            "lowering_inputs",
            "_resolved_formulas_and_bindings",
            "_runtime_projection",
            "_specialize_operation_formula_slots",
            "close_execution_dependencies",
        )
    } == {
        "_resolved_source_symbols": 1,
        "lowering_inputs": 1,
        "_resolved_formulas_and_bindings": 1,
        "_runtime_projection": 1,
        "_specialize_operation_formula_slots": 1,
        "close_execution_dependencies": 1,
    }


@pytest.mark.parametrize(
    "fixture", ["progression-periodic-effect", "roguelike-reward-build"]
)
def test_specialization_is_value_based_in_operations_and_package_closures(fixture):
    source = json.loads((_EXAMPLES / fixture / "model-source.json").read_bytes())
    before_source = canonical_bytes(source)
    with _observe_preparation() as trace:
        checked = _checked(source)
    original = trace.projections[0]
    formulas, bindings, _ = trace.formula_results[0]
    before_authority = canonical_bytes(checked.language_bundle)
    inputs = [original, deepcopy(original), json.loads(canonical_bytes(original))]
    before = canonical_bytes(original)
    assert all(
        value == original and canonical_bytes(value) == before for value in inputs
    )
    outputs = [
        _lowering._specialize_operation_formula_slots(value, formulas, bindings)
        for value in inputs
    ]
    assert all(canonical_bytes(value) == before for value in inputs)
    assert canonical_bytes(source) == before_source
    assert canonical_bytes(checked.language_bundle) == before_authority
    # The roguelike counterexample changes provenance only: body-only comparison
    # would miss it. Require the entire output and both emitted definition views.
    assert outputs[0] == outputs[1] == outputs[2]
    assert len({canonical_bytes(value) for value in outputs}) == 1
    specialized = cast(dict[str, Any], outputs[0])
    closures = {
        (closure["package"], definition["id"]): definition
        for closure in specialized["package_semantic_closures"]
        for entry in closure["definitions"]
        if entry["authority_path"] == "language.operations"
        for definition in entry["definitions"]
    }
    changed = 0
    for row, prior in zip(
        specialized["operations"], original["operations"], strict=True
    ):
        definition = row["definition"]
        assert closures[row["package"], definition["id"]] == definition
        if definition != prior["definition"]:
            changed += 1
            assert "standard.instruction-provenance" in definition["extensions"]
    assert changed > 0
    # Admission must independently reproduce the same specialization from RIR.
    assert _artifact_bytes(checked)


def _effect_copy_candidate():
    """Keep two legal, value-equal Operations under distinct namespace owners."""
    kernel, language_bundle = mutable_authorities()
    language = language_bundle["language"]
    original = next(row for row in language["packages"] if row["id"] == "game.effect")
    copied = deepcopy(original)
    copied["id"] = "test.effectcopy"
    copied["runtime_semantic_excluded_extensions"] = []
    copied["capabilities"]["provided"] = ["test.effectcopy.periodic"]
    copied["dependencies"]["required"].append("game.effect")
    capability = deepcopy(
        next(
            row
            for row in language["capabilities"]
            if row["id"] == "game.effect.periodic"
        )
    )
    capability["id"] = "test.effectcopy.periodic"
    language["capabilities"].append(capability)
    vectors = deepcopy(
        next(
            row["vector_definitions"]
            for row in language_bundle.package_conformance_vector_sets
            if row["package_id"] == "game.effect"
        )
    )
    vector_ids = {row["id"]: "test.copy." + row["id"] for row in vectors}

    def probe(value, path):
        for segment in path.split("."):
            value = value[segment]
        return deepcopy(value)

    for vector in vectors:
        vector["id"] = vector_ids[vector["id"]]
        if vector["kind"] == "package-contract":
            vector["expect"] = probe(copied, vector["probe"]["path"])
    # Both equivalent definitions declare the union of their actual vector
    # witnesses; each namespace still owns its distinct, complete vector set.
    operation_groups = [
        [
            row
            for row in language["operations"]
            if row["id"] in copied["exports"]["operations"]
        ],
        *[
            entry["definitions"]
            for package in (original, copied)
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        ],
    ]
    for operations in operation_groups:
        for operation in operations:
            operation["vectors"] += [
                vector_ids[identifier]
                for identifier in operation["vectors"]
                if identifier in vector_ids
            ]
    for entry in copied["semantic_closure"]:
        if entry["authority_path"] == "language.capabilities":
            entry["definitions"] = [deepcopy(capability)]
        elif entry["authority_path"] == "language.operations":
            for operation in entry["definitions"]:
                # The global Formula notation has one provider; copying its
                # spelling would invalidate the authority before this witness.
                operation.get("extensions", {}).pop("standard.formula-notation", None)
                if operation not in language["operations"]:
                    language["operations"].append(deepcopy(operation))
    copied_operations = {
        operation["id"]: operation
        for entry in copied["semantic_closure"]
        if entry["authority_path"] == "language.operations"
        for operation in entry["definitions"]
    }
    for vector in vectors:
        if vector["kind"] == "operation-contract":
            vector["expect"] = probe(
                copied_operations[vector["operation"]], vector["probe"]["path"]
            )
    language["packages"].append(copied)
    language_bundle.package_conformance_vector_sets.append(
        _package_vector_set(copied["id"], vectors)
    )
    _reidentify_language_bundle(language_bundle)
    return kernel, language_bundle


def test_specialization_does_not_bind_a_value_equal_operation_in_another_namespace():
    kernel, language_bundle = _effect_copy_candidate()
    admission = admit_authorities(kernel, language_bundle)
    assert admission.admitted, admission.diagnostics
    source = json.loads(
        (_EXAMPLES / "progression-periodic-effect" / "model-source.json").read_bytes()
    )
    source["package_requirements"].append("test.effectcopy")
    source_before = canonical_bytes(source)
    authority_before = canonical_bytes(language_bundle)
    with _observe_preparation() as trace:
        checked = check_model_source_value(
            source, kernel=kernel, language_bundle=language_bundle
        )
    assert isinstance(checked, CheckedModel), checked
    assert set(_artifact_bytes(checked)) == _ARTIFACTS
    formulas, bindings, _ = trace.formula_results[0]
    reference = next(
        binding["site"]["operation"]
        for binding in bindings
        if binding["site"]["kind"] == "operation-slot"
        and binding["site"]["operation"]["package"] == "game.effect"
    )
    assert not any(
        binding["site"]["kind"] == "operation-slot"
        and binding["site"]["operation"]["package"] == "test.effectcopy"
        for binding in bindings
    )

    def operation(projection, namespace):
        return next(
            row
            for row in projection["operations"]
            if row["package"] == namespace
            and row["definition"]["id"] == reference["id"]
        )

    independent = trace.projections[0]
    bound = operation(independent, "game.effect")["definition"]
    unbound = operation(independent, "test.effectcopy")["definition"]
    assert bound == unbound and bound is not unbound
    aliased = deepcopy(independent)
    operation(aliased, "test.effectcopy")["definition"] = operation(
        aliased, "game.effect"
    )["definition"]
    inputs = [independent, aliased, json.loads(canonical_bytes(aliased))]
    before = canonical_bytes(independent)
    assert all(
        value == independent and canonical_bytes(value) == before for value in inputs
    )
    outputs = [
        cast(
            dict[str, Any],
            _lowering._specialize_operation_formula_slots(value, formulas, bindings),
        )
        for value in inputs
    ]
    assert all(canonical_bytes(value) == before for value in inputs)
    assert canonical_bytes(source) == source_before
    assert canonical_bytes(language_bundle) == authority_before
    for output in outputs:
        assert operation(output, "game.effect")["definition"] != bound
        # The complete unbound definition, including body and provenance, must
        # remain unchanged in both projections even if its input was aliased.
        assert operation(output, "test.effectcopy")["definition"] == unbound
        closure_definition = next(
            definition
            for closure in output["package_semantic_closures"]
            if closure["package"] == "test.effectcopy"
            for entry in closure["definitions"]
            if entry["authority_path"] == "language.operations"
            for definition in entry["definitions"]
            if definition["id"] == reference["id"]
        )
        assert closure_definition == unbound
    assert outputs[0] == outputs[1] == outputs[2]
    assert len({canonical_bytes(value) for value in outputs}) == 1


def test_checked_request_and_all_artifact_outputs_are_isolated_from_mutation():
    source = _model_source()
    checked = _checked(source)
    expected = _artifact_bytes(checked)
    source["modules"][0]["symbols"][0]["value_policy"]["value"] = 2
    assert _artifact_bytes(checked) == expected
    assert _artifact_bytes(_checked(source)) != expected

    # A caller may inspect an old CheckedModel; mutable views must not become a
    # back door into its prepared meaning. Immutable views may reject the write.
    try:
        checked.source["modules"][0]["symbols"][0]["value_policy"]["value"] = 99
    except TypeError:
        pass
    assert _artifact_bytes(checked) == expected
    emitted = compile_checked_model(checked)
    assert set(emitted) == _ARTIFACTS
    for artifact in emitted.values():
        for member in artifact.values():
            if isinstance(member, (dict, list)):
                try:
                    member.clear()
                except TypeError:
                    pass
                break
        artifact.clear()
    assert _artifact_bytes(checked) == expected

    sources = [deepcopy(source), deepcopy(source)]
    for value, candidate in enumerate(sources, start=3):
        candidate["modules"][0]["symbols"][0]["value_policy"]["value"] = value
    sequential = [_artifact_bytes(_checked(candidate)) for candidate in sources]
    assert sequential[0] != sequential[1]
    barrier = Barrier(2)

    def compile_concurrently(candidate):
        barrier.wait(timeout=10)
        return _artifact_bytes(_checked(candidate))

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(compile_concurrently, sources))
    assert concurrent == sequential
    assert _artifact_bytes(checked) == expected


@pytest.mark.parametrize("limit", [374, 375, 376])
def test_preparation_keeps_exact_projection_charge_and_complete_refusal(limit):
    kernel, language_bundle = mutable_authorities()
    language_bundle["resources"]["max_runtime_projection_steps"] = limit
    for identifier, value in (
        ("model.accept.runtime-projection-step-boundary", limit),
        ("model.refuse.runtime-projection-step-budget", limit + 1),
    ):
        vector = next(
            row for row in language_bundle["vectors"] if row["id"] == identifier
        )
        vector["input"]["value"] = value
    _reidentify_language_bundle(language_bundle)

    with _observe_preparation() as trace:
        checked = check_model_source_value(
            _model_source(), kernel=kernel, language_bundle=language_bundle
        )
        if isinstance(checked, CheckedModel):
            artifacts = _artifact_bytes(checked)
            assert artifacts

    if limit == 374:
        assert isinstance(checked, Schema2RefusalReport)
        assert checked.model_dump(mode="json") == {
            "stage": "static",
            "variant": None,
            "diagnostics": [
                {
                    "code": "language.resource_exhausted",
                    "message": "Model Source runtime projection exhausted its admitted step budget",
                    "primary": {
                        "kind": "artifact",
                        "content_identity": "sha256:a16a065314a420f1403e008d961a77a35004b17a518d8de94a26bbf37300b00b",
                        "pointer": "",
                    },
                    "related": [],
                }
            ],
            "truncated": False,
            "terminal_audit": None,
        }
        assert trace.calls["imported-artifact", "admit_resolved_model"] == 0
    else:
        assert isinstance(checked, CheckedModel), checked
        assert trace.calls["imported-artifact", "admit_resolved_model"] == 1
        assert ("source", 375, limit) in trace.charges
        assert ("imported-artifact", 375, limit) in trace.charges
    assert trace.charges
    assert all(
        used == min(limit, 375) and admitted_limit == limit
        for _, used, admitted_limit in trace.charges
    )
