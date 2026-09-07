"""Standalone RIR admission separates execution input from producing wrappers."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.domain.publication as publication_module

from gda_balancing.domain.artifacts import select_artifact_contract
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.authority.graph import derive_language_index
from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    CompiledArtifactAdmissionError,
    RirAdmissionError,
    admit_resolved_model,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
    read_rir,
    validate_compiled_artifacts,
)
from gda_balancing.domain.model import _admission, _lowering


_EXAMPLES = Path(__file__).parents[1] / "examples" / "schema2"
_MODELS = tuple(
    sorted(path.parent.name for path in _EXAMPLES.glob("*/model-source.json"))
)


@pytest.fixture(scope="module")
def context():
    return packaged_authority_context()


@pytest.fixture(scope="module")
def compiled(context):
    artifacts = {}
    for name in _MODELS:
        value = json.loads((_EXAMPLES / name / "model-source.json").read_bytes())
        checked = check_model_source_value(value, authority_context=context)
        assert isinstance(checked, CheckedModel), checked
        artifacts[name] = compile_checked_model(checked)
    return artifacts


@pytest.mark.parametrize("name", _MODELS)
def test_maintained_rir_and_exact_build_admission_share_semantic_checks(
    name, compiled, context
):
    artifacts = compiled[name]
    assert admit_resolved_model(
        {
            key: artifacts[key]
            for key in ("package-lock", "resolved-model", "rir-semantic-payload")
        },
        authority_context=context,
    ).admitted
    rir = artifacts["rir-semantic-payload"]
    admitted = admit_rir(rir, authority_context=context)
    assert admitted.artifact() == rir
    assert admitted.content_identity == rir["content_identity"]
    assert admitted.semantic_identity == rir["semantic_identity"]


def test_admitted_rir_detaches_input_and_materializations(compiled, context):
    candidate = deepcopy(compiled["structured-selection"]["rir-semantic-payload"])
    admitted = admit_rir(candidate, authority_context=context)
    expected = canonical_bytes(candidate)
    candidate["selected_semantics"]["nominal_types"].clear()
    materialized = admitted.artifact()
    materialized["selected_semantics"]["nominal_types"].clear()
    assert canonical_bytes(admitted.artifact()) == expected
    with pytest.raises(FrozenInstanceError):
        setattr(admitted, "semantic_identity", "mutated")
    with pytest.raises(TypeError, match="Model RIR admission"):
        AdmittedRir()


def test_standalone_admission_never_constructs_a_package_lock(
    compiled, context, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("RIR admission consulted a producing wrapper")

    monkeypatch.setattr(_lowering, "_package_lock", forbidden)
    monkeypatch.setattr(_admission, "_package_lock", forbidden)
    for artifacts in compiled.values():
        assert admit_rir(artifacts["rir-semantic-payload"], authority_context=context)


def _seal(value, domain):
    value["content_identity"] = content_identity(
        domain, {key: item for key, item in value.items() if key != "content_identity"}
    )


def _changed_context(context, mutate):
    kernel, language = context.mutable_pair()
    packages = language.package_releases
    vectors = language.package_conformance_vector_sets
    mutate(packages, vectors)
    vectors_by_package = {item["package_id"]: item for item in vectors}
    for package in packages:
        vector_set = vectors_by_package[package["id"]]
        _seal(vector_set, "package-conformance-vector-set-v2")
        package["conformance_vectors"] = {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": len(canonical_bytes(vector_set)),
            "content_identity": vector_set["content_identity"],
        }
        package["semantic_identity"] = content_identity(
            "domain-package-semantic-closure-v2",
            cast(
                JsonValue,
                package_runtime_semantic_closure(
                    package,
                    kernel["meta_format"]["package_release"][
                        "semantic_identity_projection"
                    ],
                ),
            ),
        )
        _seal(package, "domain-package-release-v2")
    root = language.root
    root["package_descriptors"] = [
        {
            "artifact_kind": package["artifact_kind"],
            "byte_size": len(canonical_bytes(package)),
            "content_identity": package["content_identity"],
            "id": package["id"],
        }
        for package in packages
    ]
    _seal(root, "language-definition-bundle-v2")
    graph = derive_language_index(
        root,
        packages,
        vectors,
        kernel["admission"]["required_language_members"],
        root_byte_size=len(canonical_bytes(root)),
        package_byte_sizes=[len(canonical_bytes(package)) for package in packages],
        vector_set_byte_sizes=[len(canonical_bytes(vector)) for vector in vectors],
        descriptor_order=kernel["meta_format"]["language_bundle"]["package_descriptor"][
            "canonical_order"
        ],
    )
    changed = admit_authority_context(kernel, graph)
    assert isinstance(changed, AdmittedAuthorityContext), changed
    assert (
        changed.language_bundle["content_identity"]
        != context.language_bundle["content_identity"]
    )
    return changed


def _owned_definitions(packages, namespace, path):
    package = next(item for item in packages if item["id"] == namespace)
    return next(
        entry["definitions"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == path
    )


@pytest.mark.parametrize(
    "mutation", ("selected-vector-order", "unselected-operation-law")
)
def test_old_rir_admits_after_provenance_only_authority_changes(
    mutation, compiled, context
):
    def mutate(packages, vectors):
        if mutation == "selected-vector-order":
            vector_set = next(
                item for item in vectors if item["package_id"] == "core.quantity"
            )
            vector_set["vectors"].reverse()
            vector_set["vector_definitions"].reverse()
        else:
            operations = _owned_definitions(
                packages, "game.combat", "language.operations"
            )
            next(item for item in operations if item["id"] == "game.combat.cast-v1")[
                "resource_bounds"
            ]["max_steps"] += 1
            vector_set = next(
                item for item in vectors if item["package_id"] == "game.combat"
            )
            next(
                item
                for item in vector_set["vector_definitions"]
                if item["id"] == "game.combat.cast.resource-bound"
            )["expect"] += 1

    changed = _changed_context(context, mutate)
    original = compiled["roguelike-reward-build"]["rir-semantic-payload"]
    assert admit_rir(original, authority_context=changed).artifact() == original
    # Build verification still truthfully rejects the obsolete exact wrapper.
    artifacts = compiled["roguelike-reward-build"]
    assert not admit_resolved_model(
        {
            key: artifacts[key]
            for key in ("package-lock", "resolved-model", "rir-semantic-payload")
        },
        authority_context=changed,
    ).admitted


def test_rir_formula_pair_uses_only_actual_body_operation_notations(compiled, context):
    def mutate(packages, vectors):
        operations = _owned_definitions(
            packages, "core.quantity", "language.operations"
        )
        unused = next(item for item in operations if item["id"] == "quantity.identity")
        unused["extensions"]["standard.formula-notation"]["name"] = "max"
        vector_set = next(
            item for item in vectors if item["package_id"] == "core.quantity"
        )
        vector = next(
            item
            for item in vector_set["vector_definitions"]
            if item["id"] == "formula.notation.quantity.identity"
        )
        vector["expect"] = deepcopy(unused["extensions"])

    changed = _changed_context(context, mutate)
    rir = compiled["progression-periodic-effect"]["rir-semantic-payload"]
    assert admit_rir(rir, authority_context=changed).artifact() == rir
    # The complete Source/Build context continues to reject notation ambiguity.
    requirements = compiled["progression-periodic-effect"]["package-lock"][
        "root_requirements"
    ]
    assert not _admission._formula_pairs_are_admitted(
        rir["formulas"], rir["declarations"], requirements, changed
    )


def _reidentified_rir(candidate, context):
    candidate.pop("content_identity", None)
    candidate["semantic_identity"] = _lowering._rir_semantic_identity(
        context.language_bundle, candidate
    )
    return select_artifact_contract(
        context.language_bundle, "rir-semantic-payload"
    ).identify(candidate)


@pytest.mark.parametrize(
    "mutation",
    (
        "nominal-owner",
        "owned-reason",
        "structured-resource",
        "operation-charge",
        "formula-expression",
    ),
)
def test_coherently_reidentified_rir_tampering_is_refused(mutation, compiled, context):
    name = (
        "progression-periodic-effect"
        if mutation == "formula-expression"
        else "structured-selection"
    )
    candidate = deepcopy(compiled[name]["rir-semantic-payload"])
    selected = candidate["selected_semantics"]
    if mutation == "nominal-owner":
        selected["nominal_types"][0]["package"] = "other.owner"
    elif mutation == "owned-reason":
        selected["diagnostic_reasons"][0]["package"] = "other.owner"
    elif mutation == "structured-resource":
        selected["execution_resources"]["max_rule_match_steps"] += 1
    elif mutation == "operation-charge":
        selected["operations"][0]["definition"]["resource_bounds"]["max_steps"] += 1
    else:
        candidate["formulas"][0]["expression"] += " "
    candidate = _reidentified_rir(candidate, context)
    assert select_artifact_contract(
        context.language_bundle, "rir-semantic-payload"
    ).verify(candidate)
    with pytest.raises(RirAdmissionError) as error:
        admit_rir(candidate, authority_context=context)
    assert error.value.reason == "model.reason.resolved-authority-mismatch"
    assert error.value.diagnostic == "language.resolved_authority_mismatch"


@pytest.mark.parametrize("copy", ("direct", "closure"))
def test_rir_rejects_reinserted_operation_vector_references(copy, compiled, context):
    candidate = deepcopy(compiled["structured-selection"]["rir-semantic-payload"])
    selected = candidate["selected_semantics"]
    direct = selected["operations"][0]
    mirror = next(
        definition
        for closure in selected["package_semantic_closures"]
        if closure["package"] == direct["package"]
        for entry in closure["definitions"]
        if entry["authority_path"] == "language.operations"
        for definition in entry["definitions"]
        if definition["id"] == direct["definition"]["id"]
    )
    assert "vectors" not in direct["definition"] and "vectors" not in mirror
    original = next(
        definition
        for package in context.language_bundle["language"]["packages"]
        if package["id"] == direct["package"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
        if definition["id"] == direct["definition"]["id"]
    )
    assert original["vectors"]
    target = direct["definition"] if copy == "direct" else mirror
    target["vectors"] = deepcopy(original["vectors"])
    candidate.pop("content_identity")
    candidate["semantic_identity"] = _lowering._rir_semantic_identity(
        context.language_bundle, candidate
    )
    contract = select_artifact_contract(context.language_bundle, "rir-semantic-payload")
    _reidentify(candidate, contract.definition["identity_domain"])
    assert contract.verify(candidate) is (copy == "closure")
    with pytest.raises(RirAdmissionError):
        admit_rir(candidate, authority_context=context)


def test_explicit_rir_file_ingress_retains_format_and_file_checks(
    tmp_path, compiled, context
):
    path = tmp_path / "selected-rir.json"
    rir = compiled["roguelike-reward-build"]["rir-semantic-payload"]
    path.write_bytes(canonical_bytes(rir))
    result = read_rir(str(path), authority_context=context)
    assert isinstance(result, AdmittedRir)
    assert result.artifact() == rir
    alias = tmp_path / "rir-alias.json"
    alias.symlink_to(path)
    assert isinstance(read_rir(str(alias), authority_context=context), AdmittedRir)
    for data in (b'{"duplicate":1,"duplicate":2}', b"[]", b"\xff", b"[" * 2000):
        path.write_bytes(data)
        refusal = read_rir(str(path), authority_context=context)
        assert isinstance(refusal, Schema2RefusalReport)
        assert isinstance(refusal.diagnostics[0].primary, ArtifactLocation)
        assert (
            refusal.diagnostics[0].primary.content_identity
            == "sha256:" + hashlib.sha256(data).hexdigest()
        )
    with pytest.raises(UnreadableInputError):
        read_rir(str(tmp_path / "absent.json"), authority_context=context)
    with pytest.raises(UnreadableInputError):
        read_rir(str(tmp_path), authority_context=context)


@pytest.mark.parametrize("mutation", ["missing-member", "kind", "digest"])
def test_standalone_rir_rejects_member_kind_and_digest_drift(
    mutation, compiled, context
):
    candidate = deepcopy(compiled["roguelike-reward-build"]["rir-semantic-payload"])
    if mutation == "missing-member":
        del candidate["selected_semantics"]
    elif mutation == "kind":
        candidate["artifact_kind"] = "resolved-model"
    else:
        candidate["content_identity"] = "sha256:" + "0" * 64
    with pytest.raises(RirAdmissionError):
        admit_rir(candidate, authority_context=context)


@pytest.mark.parametrize("reseal", [False, True])
def test_exact_build_retains_receipt_relationship_checks(reseal, compiled, context):
    artifacts = deepcopy(compiled["roguelike-reward-build"])
    receipt = artifacts["build-receipt"]
    receipt["rir_identity"] = "sha256:" + "0" * 64
    contract = select_artifact_contract(context.language_bundle, "build-receipt")
    if reseal:
        artifacts["build-receipt"] = contract.identify(
            {
                key: value
                for key, value in receipt.items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
        )
        assert contract.verify(artifacts["build-receipt"])
    else:
        assert not contract.verify(receipt)
    with pytest.raises(
        CompiledArtifactAdmissionError, match="build receipt has invalid bindings"
    ):
        validate_compiled_artifacts(artifacts, receipt["source_identity"], context)
    assert admit_rir(artifacts["rir-semantic-payload"], authority_context=context)


@pytest.mark.parametrize("mutation", ["missing-member", "kind"])
def test_exact_trio_retains_member_set_and_kind_checks(mutation, compiled, context):
    artifacts = deepcopy(compiled["roguelike-reward-build"])
    trio = {
        name: artifacts[name]
        for name in ("package-lock", "rir-semantic-payload", "resolved-model")
    }
    if mutation == "missing-member":
        del trio["package-lock"]
    else:
        trio["package-lock"]["artifact_kind"] = "resolved-model"
    assert not admit_resolved_model(trio, authority_context=context).admitted
    assert admit_rir(artifacts["rir-semantic-payload"], authority_context=context)


def _publish_example_model(tmp_path, run_cli, invocation_key):
    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(_EXAMPLES / "roguelike-reward-build" / "model-source.json"),
            "--out",
            str(tmp_path / f"resolved-model-{invocation_key[0]}.json"),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    return Path(receipt["manifest_locator"]).parent


def _assert_publication_refused(publication_dir, run_cli, context, code, pointer):
    exit_code, stdout, stderr = run_cli(
        ["model", "inspect", str(publication_dir / "artifact-set-receipt.json")]
    )
    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert len(error["diagnostics"]) == 1
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == code
    assert diagnostic["primary"]["pointer"] == pointer
    # RIR input has its own exact file/semantic admission. An unrelated damaged
    # member in the producing publication does not replace that contract.
    assert isinstance(
        read_rir(
            str(publication_dir / "rir-semantic-payload.json"),
            authority_context=context,
        ),
        AdmittedRir,
    )


def test_published_and_in_memory_rir_admission_preserve_identical_bytes(
    tmp_path, run_cli, compiled, context
):
    publication_dir = _publish_example_model(tmp_path, run_cli, "a" * 64)
    actual = read_rir(
        str(publication_dir / "rir-semantic-payload.json"), authority_context=context
    )
    assert isinstance(actual, AdmittedRir)
    expected = admit_rir(
        compiled["roguelike-reward-build"]["rir-semantic-payload"],
        authority_context=context,
    )
    assert canonical_bytes(actual.artifact()) == canonical_bytes(expected.artifact())
    assert actual.semantic_identity == expected.semantic_identity


def _reidentify(artifact: dict[str, Any], domain: str) -> None:
    excluded = (
        {"manifest_locator", "member_locators"}
        if domain == "artifact-set-receipt-v2"
        else set()
    )
    artifact["content_identity"] = content_identity(
        domain,
        cast(
            JsonValue,
            {
                key: value
                for key, value in artifact.items()
                if key != "content_identity" and key not in excluded
            },
        ),
    )


def test_model_publication_rejects_damage_to_an_unrequested_member(
    tmp_path: Path,
    run_cli,
    context,
) -> None:
    publication_dir = _publish_example_model(
        tmp_path,
        run_cli,
        "b" * 64,
    )
    member_path = publication_dir / "capability-manifest.json"
    original_bytes = member_path.read_bytes()
    original = json.loads(original_bytes)

    def assert_refused() -> None:
        _assert_publication_refused(
            publication_dir,
            run_cli,
            context,
            "kernel.binding_mismatch",
            "/capability-manifest",
        )

    member_path.unlink()
    assert_refused()
    member_path.write_bytes(original_bytes)

    member_path.write_bytes(b"not-json")
    assert_refused()
    member_path.write_bytes(original_bytes)

    payload = {
        key: value
        for key, value in original.items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "content_identity",
            "wire_schema_identity",
        }
    }
    payload["package_lock_identity"] = "sha256:" + ("0" * 64)
    replacement = select_artifact_contract(
        context.language_bundle, "capability-manifest"
    ).identify(cast(dict[str, JsonValue], payload))
    assert replacement["content_identity"] != original["content_identity"]
    member_path.write_bytes(canonical_bytes(cast(JsonValue, replacement)))
    assert_refused()


def test_model_publication_rejects_an_ambiguous_descriptor(
    tmp_path: Path,
    run_cli,
    context,
) -> None:
    invocation_key = "c" * 64
    publication_dir = _publish_example_model(
        tmp_path,
        run_cli,
        invocation_key,
    )
    _publish_example_model(tmp_path, run_cli, "d" * 64)

    manifest_path = publication_dir / "artifact-set-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = deepcopy(
        next(
            row for row in manifest["members"] if row["logical_name"] == "build-receipt"
        )
    )
    descriptor["wire_schema_identity"] = "sha256:" + ("0" * 64)
    manifest["members"].append(descriptor)
    _reidentify(manifest, "artifact-set-manifest-v2")
    manifest_path.write_bytes(canonical_bytes(cast(JsonValue, manifest)))

    receipt_path = publication_dir / "artifact-set-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["manifest_identity"] = manifest["content_identity"]
    receipt["member_locators"].append(
        {
            "logical_name": "build-receipt",
            "locator": str((publication_dir / "build-receipt.json").absolute()),
        }
    )
    _reidentify(receipt, "artifact-set-receipt-v2")
    receipt_path.write_bytes(canonical_bytes(cast(JsonValue, receipt)))

    index_path = publication_dir / "publication-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["receipt_identity"] = receipt["content_identity"]
    _reidentify(index, "publication-index-v2")
    index_path.write_bytes(canonical_bytes(cast(JsonValue, index)))

    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    anchor_path = next((store / "anchors").glob(f"*/{invocation_key}.json"))
    anchor_path.unlink()
    anchor_path.write_bytes(
        canonical_bytes(
            cast(
                JsonValue,
                publication_module._authenticated_anchor(
                    index,
                    publication_module.publication_authentication_key(),
                ),
            )
        )
    )
    anchor_path.chmod(0o444)

    _assert_publication_refused(
        publication_dir,
        run_cli,
        context,
        "kernel.member_set_mismatch",
        "/manifest/members",
    )
