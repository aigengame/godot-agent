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

from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.model import _admission, _compilation, _lowering
from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import _model_source, _reidentify_language_bundle


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
                budget = frame.f_locals["budget"]
                self.charges.append((owner, budget.used, budget.limit))
                if owner == "source" and result is not None:
                    self.projections.append(deepcopy(result))
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
    assert {used for _, used, _ in trace.charges} == {318}
    assert {
        name: trace.calls["source", name]
        for name in (
            "_resolved_source_symbols",
            "lowering_inputs",
            "_resolved_formulas_and_bindings",
            "_runtime_projection",
        )
    } == {
        "_resolved_source_symbols": 1,
        "lowering_inputs": 1,
        "_resolved_formulas_and_bindings": 1,
        "_runtime_projection": 1,
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


@pytest.mark.parametrize("limit", [232, 233, 234])
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

    if limit == 232:
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
        assert ("source", 233, limit) in trace.charges
        assert ("imported-artifact", 233, limit) in trace.charges
    assert trace.charges
    assert all(
        used == min(limit, 233) and admitted_limit == limit
        for _, used, admitted_limit in trace.charges
    )
