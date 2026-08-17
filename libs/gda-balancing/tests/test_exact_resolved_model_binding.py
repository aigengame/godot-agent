"""Exact Resolved Model binding shared by committed and in-memory paths."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.artifacts import identified_artifact
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
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
