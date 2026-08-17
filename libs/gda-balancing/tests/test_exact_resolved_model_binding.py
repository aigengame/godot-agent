"""Exact Resolved Model binding shared by committed and in-memory paths."""

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.domain.publication as publication_module
from gda_balancing.domain.artifact_errors import PublishedArtifactIntegrityError
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.artifacts import identified_artifact
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.model import (
    CheckedModel,
    ExactResolvedModelBinding,
    ExactResolvedModelBindingError,
    authority_context_for_checked,
    check_model_source_value,
    compile_checked_model,
    project_compiled_model_binding,
    resolve_published_model_binding,
)


_PACKAGE_ROOT = Path(__file__).parents[1]
_EXAMPLE = _PACKAGE_ROOT / "examples" / "schema2" / "roguelike-reward-build"


def _compiled_model() -> tuple[
    dict[str, dict[str, JsonValue]],
    AdmittedAuthorityContext,
]:
    source = json.loads((_EXAMPLE / "model-source.json").read_text(encoding="utf-8"))
    checked = check_model_source_value(source)
    assert isinstance(checked, CheckedModel)
    context = authority_context_for_checked(checked)
    return compile_checked_model(checked), context


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


def _publish_example_model(
    tmp_path: Path,
    run_cli,
    invocation_key: str,
) -> tuple[
    AdmittedAuthorityContext,
    Path,
    dict[str, str],
]:
    artifacts, context = _compiled_model()
    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(_EXAMPLE / "model-source.json"),
            "--out",
            str(tmp_path / f"resolved-model-{invocation_key[0]}.json"),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    identities = {
        name: cast(str, artifacts[name]["content_identity"])
        for name in (
            "build-receipt",
            "package-lock",
            "resolved-model",
            "rir-semantic-payload",
        )
    }
    return context, Path(receipt["manifest_locator"]).parent, identities


def test_exact_binding_requires_admission() -> None:
    with pytest.raises(TypeError, match="come from Model binding admission"):
        ExactResolvedModelBinding()


def test_compiled_model_projects_one_detached_exact_binding() -> None:
    artifacts, context = _compiled_model()
    expected = {
        name: canonical_bytes(cast(JsonValue, artifacts[name]))
        for name in (
            "build-receipt",
            "package-lock",
            "resolved-model",
            "rir-semantic-payload",
        )
    }

    binding = project_compiled_model_binding(artifacts, context)
    projected = binding.artifacts()

    assert set(projected) == set(expected)
    assert {
        name: canonical_bytes(cast(JsonValue, artifact))
        for name, artifact in projected.items()
    } == expected
    assert (
        binding.resolved_model_identity
        == artifacts["resolved-model"]["content_identity"]
    )

    cast(dict[str, Any], artifacts["build-receipt"])["source_identity"] = "changed"
    cast(list[Any], artifacts["rir-semantic-payload"]["entrypoints"]).clear()
    projected["package-lock"].clear()

    assert {
        name: canonical_bytes(cast(JsonValue, artifact))
        for name, artifact in binding.artifacts().items()
    } == expected


@pytest.mark.parametrize(
    ("mutation", "reason", "member"),
    (
        (
            lambda values: values.pop("package-lock"),
            "member-set-mismatch",
            "package-lock",
        ),
        (
            lambda values: values["package-lock"].__setitem__(
                "artifact_kind", "resolved-model"
            ),
            "member-admission-failed",
            "package-lock",
        ),
        (
            lambda values: values["build-receipt"].__setitem__(
                "rir_identity", "sha256:" + ("0" * 64)
            ),
            "member-admission-failed",
            "build-receipt",
        ),
    ),
)
def test_compiled_model_binding_closes_member_and_relationship_drift(
    mutation,
    reason: str,
    member: str,
) -> None:
    artifacts, context = _compiled_model()
    candidate = deepcopy(artifacts)
    mutation(candidate)

    with pytest.raises(ExactResolvedModelBindingError) as caught:
        project_compiled_model_binding(candidate, context)

    assert caught.value.reason == reason
    assert caught.value.member == member


def test_exact_binding_rejects_a_self_valid_build_receipt_with_wrong_relation() -> None:
    artifacts, context = _compiled_model()
    candidate = deepcopy(artifacts)
    build = cast(dict[str, JsonValue], deepcopy(candidate["build-receipt"]))
    build["rir_identity"] = "sha256:" + ("0" * 64)
    payload = {
        name: value
        for name, value in build.items()
        if name
        not in {
            "artifact_kind",
            "artifact_version",
            "content_identity",
            "wire_schema_identity",
        }
    }
    candidate["build-receipt"] = identified_artifact(
        context.language_bundle,
        "build-receipt",
        payload,
    )

    with pytest.raises(ExactResolvedModelBindingError) as caught:
        project_compiled_model_binding(candidate, context)

    assert caught.value.reason == "build-receipt-binding-mismatch"
    assert caught.value.member == "build-receipt"


def test_committed_and_compiled_adapters_produce_the_same_exact_binding(
    tmp_path: Path,
    run_cli,
) -> None:
    artifacts, context = _compiled_model()
    exit_code, _stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(_EXAMPLE / "model-source.json"),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "a" * 64,
        ]
    )
    assert (exit_code, stderr) == (0, "")

    compiled = project_compiled_model_binding(artifacts, context)
    committed = resolve_published_model_binding(
        {
            name: cast(str, artifact["content_identity"])
            for name, artifact in compiled.artifacts().items()
        },
        context,
    )

    assert {
        name: canonical_bytes(cast(JsonValue, artifact))
        for name, artifact in committed.artifacts().items()
    } == {
        name: canonical_bytes(cast(JsonValue, artifact))
        for name, artifact in compiled.artifacts().items()
    }


def test_published_binding_rejects_damage_to_an_unrequested_member(
    tmp_path: Path,
    run_cli,
) -> None:
    context, publication_dir, identities = _publish_example_model(
        tmp_path,
        run_cli,
        "b" * 64,
    )
    member_path = publication_dir / "capability-manifest.json"
    original_bytes = member_path.read_bytes()
    original = json.loads(original_bytes)

    def assert_refused() -> None:
        with pytest.raises(PublishedArtifactIntegrityError) as caught:
            resolve_published_model_binding(identities, context)
        assert caught.value.logical_name == "build-receipt"

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
    replacement = identified_artifact(
        context.language_bundle,
        "capability-manifest",
        cast(dict[str, JsonValue], payload),
    )
    assert replacement["content_identity"] != original["content_identity"]
    member_path.write_bytes(canonical_bytes(cast(JsonValue, replacement)))
    assert_refused()


def test_published_binding_rejects_an_ambiguous_descriptor_before_fallback(
    tmp_path: Path,
    run_cli,
) -> None:
    invocation_key = "c" * 64
    context, publication_dir, identities = _publish_example_model(
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

    with pytest.raises(PublishedArtifactIntegrityError) as caught:
        resolve_published_model_binding(identities, context)

    assert caught.value.logical_name == "build-receipt"
