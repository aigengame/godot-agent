"""A real published Runtime Profile cannot restore the retired extension field."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from gda_balancing.domain.artifacts import select_protocol_artifact_contract
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import content_identity
from test_public_formula_runtime_seam import (
    _EXAMPLE,
    _build,
    _members,
    _run,
    _write_specification,
)


def test_published_runtime_profile_wire_refuses_reidentified_retired_extension(
    tmp_path, run_cli
):
    _, rir_path, rir = _build(tmp_path, run_cli)
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert (code, stderr) == (0, ""), stdout
    published = _members(json.loads(stdout))["resolved-runtime-profile"]
    contract = select_protocol_artifact_contract(
        packaged_authority_context().language_bundle, "resolved-runtime-profile"
    )
    assert contract.verify(published)
    assert "extensions" not in published["runtime_profile"]

    forged = deepcopy(published)
    forged["runtime_profile"]["extensions"] = {"standard.formula": {"contexts": []}}
    excluded = set(contract.definition["identity_excluded_members"])
    forged["content_identity"] = content_identity(
        contract.definition["identity_domain"],
        {
            key: value
            for key, value in forged.items()
            if key != "content_identity" and key not in excluded
        },
    )
    assert forged["content_identity"] != published["content_identity"]
    with pytest.raises(ValidationError) as refusal:
        Draft202012Validator(contract.schema).validate(forged)
    assert list(refusal.value.path) == ["runtime_profile"]
    assert refusal.value.validator == "unevaluatedProperties"
    assert not contract.verify(forged)
