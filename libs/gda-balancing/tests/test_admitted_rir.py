"""Standalone RIR admission separates execution input from producing wrappers."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

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
    RirAdmissionError,
    admit_resolved_model,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
    read_rir,
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
