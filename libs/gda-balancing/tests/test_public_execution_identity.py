"""Public execution follows selected meaning across unrelated Build changes."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

import gda_balancing.domain.authority.context as authority
import gda_balancing.domain.model._compilation as compilation
from gda_balancing.domain.canonical import canonical_bytes
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root


_EXAMPLE = Path(__file__).parents[1] / "examples" / "schema2" / "roguelike-reward-build"


def _success(run_cli, argv):
    exit_code, stdout, stderr = run_cli(argv)
    assert (exit_code, stderr) == (0, ""), (argv, stdout, stderr)
    return json.loads(stdout)


def _members(receipt):
    members = {}
    for row in receipt["member_locators"]:
        data = Path(row["locator"]).read_bytes()
        value = json.loads(data)
        assert data == canonical_bytes(value)
        members[row["logical_name"]] = value
    return members


def _changed_authorities(context, mutation):
    kernel, bundle = context.mutable_pair()
    reference_change = mutation in {
        "selected-vector-reference-order",
        "selected-vector-reference-addition",
    }
    namespace = (
        "game.generation"
        if reference_change
        else "game.combat"
        if mutation == "unselected-package-semantics"
        else "core.quantity"
    )
    package = next(
        row for row in bundle["language"]["packages"] if row["id"] == namespace
    )
    previous_semantic_identity = package["semantic_identity"]
    vectors = next(
        row
        for row in bundle.package_conformance_vector_sets
        if row["package_id"] == namespace
    )
    previous_vectors = canonical_bytes(vectors)
    if reference_change:
        operation = next(
            definition
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.operations"
            for definition in closure["definitions"]
            if definition["id"] == "game.generation.select-reward-v1"
        )
        if mutation == "selected-vector-reference-order":
            operation["vectors"].reverse()
        else:
            vector = deepcopy(
                next(
                    row
                    for row in vectors["vector_definitions"]
                    if row["id"] == "generation.select.effects"
                )
            )
            vector["id"] = "generation.select.additional-effect-witness"
            vectors["vectors"].append(vector["id"])
            vectors["vector_definitions"].append(vector)
            operation["vectors"].append(vector["id"])
    elif mutation == "unselected-package-semantics":
        operations = next(
            row["definitions"]
            for row in package["semantic_closure"]
            if row["authority_path"] == "language.operations"
        )
        operation = next(
            row for row in operations if row["id"] == "game.combat.cast-v1"
        )
        operation["resource_bounds"]["max_steps"] += 1
        next(
            row
            for row in vectors["vector_definitions"]
            if row["id"] == "game.combat.cast.resource-bound"
        )["expect"] += 1
    elif mutation == "selected-vector-order":
        vectors["vectors"].reverse()
        vectors["vector_definitions"].reverse()
    else:
        assert mutation == "selected-vector-content"
        vector = next(
            row
            for row in vectors["vector_definitions"]
            if row["id"] == "quantity.accept.domain"
        )
        assert vector["input"] == {"minimum": 1, "maximum": 1}
        vector["input"] = {"minimum": 2, "maximum": 2}
        assert vector["matched"] is False
    _bind_package_vector_set(package, vectors)
    assert (canonical_bytes(vectors) != previous_vectors) == (
        mutation != "selected-vector-reference-order"
    )
    assert (package["semantic_identity"] != previous_semantic_identity) == (
        mutation == "unselected-package-semantics" or reference_change
    )
    _reidentify_graph_root(bundle)
    changed = authority.admit_authority_context(kernel, bundle)
    assert isinstance(changed, authority.AdmittedAuthorityContext), changed
    assert changed.kernel == context.kernel
    assert (
        changed.language_bundle["content_identity"]
        != context.language_bundle["content_identity"]
    )
    return changed


@pytest.mark.parametrize(
    "mutation",
    (
        "compiler-build-label",
        "unselected-package-semantics",
        "selected-vector-order",
        "selected-vector-content",
        "selected-vector-reference-order",
        "selected-vector-reference-addition",
    ),
)
def test_public_execution_and_replay_ignore_unrelated_build_changes(
    tmp_path, run_cli, monkeypatch, mutation
):
    source = tmp_path / "source.json"
    specification = tmp_path / "experiment.json"
    source.write_bytes((_EXAMPLE / "model-source.json").read_bytes())
    specification.write_bytes((_EXAMPLE / "experiment.json").read_bytes())
    original_inputs = (source.read_bytes(), specification.read_bytes())
    context = authority.packaged_authority_context()

    def build(token):
        return _success(
            run_cli,
            [
                "model",
                "build",
                str(source),
                "--out",
                str(tmp_path / f"build-{token}.json"),
                "--invocation-key",
                f"{token:064x}",
            ],
        )

    original_build = _members(build(1))
    assert len(original_build) == 8
    original_rir = original_build["rir-semantic-payload"]
    assert all(
        "vectors" not in row["definition"]
        for row in original_rir["selected_semantics"]["operations"]
    )
    selected_packages = {
        row["id"] for row in original_build["package-lock"]["packages"]
    }
    assert "core.quantity" in selected_packages
    assert "game.combat" not in selected_packages
    rir = tmp_path / "original-rir.json"
    rir.write_bytes(canonical_bytes(original_rir))
    original_rir_bytes = rir.read_bytes()

    def check():
        return _success(
            run_cli,
            ["experiment", "check", str(specification), "--rir", str(rir)],
        )

    def run(token):
        return _success(
            run_cli,
            [
                "experiment",
                "run",
                str(specification),
                "--rir",
                str(rir),
                "--out",
                str(tmp_path / f"run-{token}.json"),
                "--invocation-key",
                f"{token:064x}",
            ],
        )

    original_check = check()
    original_receipt = run(2)
    original = _members(original_receipt)
    assert set(original) == {
        "evaluation-run",
        "event-trace",
        "snapshot-series",
        "metric-dataset",
        "resolved-runtime-profile",
        "evaluator-capability-manifest",
    }
    events = original["event-trace"]["events"]
    assert events and any(event["rng_draws"] for event in events)
    typed_facts = [
        fact["value"]
        for event in events
        for fact in event["facts"]
        if isinstance(fact.get("value"), dict) and "type" in fact["value"]
    ]
    assert typed_facts
    assert any(value["type"]["package"] == "game.generation" for value in typed_facts)
    assert len(original["snapshot-series"]["snapshots"]) > 1
    assert original["metric-dataset"]["samples"]
    original_receipt_path = tmp_path / "original-run-receipt.json"
    original_receipt_path.write_bytes(canonical_bytes(original_receipt))

    if mutation == "compiler-build-label":
        monkeypatch.setattr(
            compilation,
            "_LOWERER_IMPLEMENTATION_IDENTITY",
            compilation._LOWERER_IMPLEMENTATION_IDENTITY + ".public-identity-witness",
        )
    else:
        changed = _changed_authorities(context, mutation)
        # Install the actually admitted context at the existing process cache seam.
        monkeypatch.setattr(authority, "_PACKAGED_CONTEXT", changed)
        assert authority.packaged_authority_context() is changed

    current_build = _members(build(3))
    assert set(current_build) == set(original_build)
    assert canonical_bytes(current_build["rir-semantic-payload"]) == original_rir_bytes
    assert (
        current_build["rir-semantic-payload"]["semantic_identity"]
        == (original_rir["semantic_identity"])
    )
    before, after = original_build["build-receipt"], current_build["build-receipt"]
    assert before["source_identity"] == after["source_identity"]
    assert before["content_identity"] != after["content_identity"]
    if mutation == "compiler-build-label":
        assert before["compiler"] != after["compiler"]
        assert {
            name: value
            for name, value in current_build.items()
            if name != "build-receipt"
        } == {
            name: value
            for name, value in original_build.items()
            if name != "build-receipt"
        }
    else:
        assert before["compiler"] == after["compiler"]
        assert before["language_bundle_identity"] != after["language_bundle_identity"]
    assert check() == original_check
    current = _members(run(4))
    assert {name: canonical_bytes(value) for name, value in current.items()} == {
        name: canonical_bytes(value) for name, value in original.items()
    }

    replay_result = _success(
        run_cli,
        [
            "experiment",
            "replay",
            str(specification),
            "--rir",
            str(rir),
            "--original-experiment-run-artifact-set-receipt",
            str(original_receipt_path),
            "--out",
            str(tmp_path / "replay.json"),
            "--invocation-key",
            f"{5:064x}",
        ],
    )
    assert replay_result["claim_state"] == "candidate"
    replay = _members(replay_result["artifact_set"])
    comparison = replay.pop("replay-comparison")
    assert comparison["result"] == "matched"
    assert comparison["checks"] and all(row["match"] for row in comparison["checks"])
    assert {name: canonical_bytes(value) for name, value in replay.items()} == {
        name: canonical_bytes(value) for name, value in original.items()
    }
    assert (source.read_bytes(), specification.read_bytes()) == original_inputs
    assert rir.read_bytes() == original_rir_bytes
    assert original_receipt_path.read_bytes() == canonical_bytes(original_receipt)
