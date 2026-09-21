"""Template protocol kinds, member kinds and publication labels are independent."""

from copy import deepcopy
from dataclasses import replace
import json
from typing import Any, cast

import pytest

from gda_balancing.domain.artifact_set import ProtocolArtifactSetMemberSpec
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.template import minimal_release
from gda_balancing.interfaces.cli.template_instantiation import (
    TEMPLATE_INSTANTIATE,
    template_instantiate_handler,
)
from gda_balancing.interfaces.cli.template_catalog import (
    TEMPLATE_GET,
    template_get_handler,
)
from schema2_authority_support import mutable_authorities
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_template_cli import _reidentify_language_bundle, _reidentify_release


_KINDS = (
    "model-source-package",
    "template-release",
    "template-instantiate-command-input",
    "template-instantiation-receipt",
    "experiment-template",
    "declared-package-dependencies",
    "template-defaults",
    "template-compatibility",
    "template-documentation",
    "genre-coverage-matrix",
    "golden-scenario",
    "negative-vector",
    "boundary-vector",
)
_RENAMES = {kind: f"probe.{kind}" for kind in _KINDS}


def _rename_kinds(value, renames):
    if isinstance(value, dict):
        for key in value:
            # Protocol roles are fixed responsibilities, distinct from LDB kind names.
            if key not in {"protocol_role", "role"} and not (
                value.get("root") == "role" and key == "name"
            ):
                value[key] = _rename_kinds(value[key], renames)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _rename_kinds(item, renames)
    elif isinstance(value, str):
        return renames.get(value, value)
    return value


@pytest.fixture(scope="module", params=("original", "template-kinds", "renamed-kinds"))
def template_context(request):
    kernel, language = mutable_authorities()
    original_kernel = deepcopy(kernel)
    renames = {
        kind: renamed
        for kind, renamed in _RENAMES.items()
        if request.param == "renamed-kinds"
        or (request.param == "template-kinds" and kind != "model-source-package")
    }
    if renames:
        _rename_kinds(language, renames)
        _reidentify_language_bundle(kernel, language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert kernel == original_kernel
    return (
        context,
        {kind: renames.get(kind, kind) for kind in _KINDS},
        (kernel, language),
    )


def test_public_template_kind_rename_instantiates_editable_source(
    template_context, tmp_path
):
    context, kinds, authority = template_context
    candidate = _PublicCandidate(tmp_path, authorities=authority)
    release = candidate.cli("template", "get", "--id", "standard.quantity-minimal")
    assert release["artifact_kind"] == kinds["template-release"]
    assert {member["member_kind"] for member in release["members"]} == {
        kinds[kind]
        for kind in _KINDS
        if kind
        not in {
            "template-release",
            "template-instantiate-command-input",
            "template-instantiation-receipt",
        }
    }
    out = tmp_path / "editable.json"
    receipt = candidate.cli(
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--package-id",
        "example.template-role",
        "--out",
        str(out),
        "--invocation-key",
        "91" * 32,
    )
    members = _members(receipt)
    assert (
        members["template-instantiation-receipt"]["artifact_kind"]
        == kinds["template-instantiation-receipt"]
    )
    source = json.loads(out.read_text())
    assert source["manifest"]["id"] == "example.template-role"
    assert (
        source["manifest"]["template_provenance"]["template_identity"]
        == release["content_identity"]
    )
    module = source["modules"][0]
    for symbol in module["symbols"]:
        symbol["domain"]["maximum"] = 250
    for formula in module["formulas"]:
        for parameter in formula["parameters"]:
            parameter["domain"]["maximum"] = 250
        formula["result"]["domain"]["maximum"] = 250
        for node in formula["body"]["nodes"]:
            node["result"]["domain"]["maximum"] = 250
    out.write_text(json.dumps(source))
    assert candidate.cli("model", "check", str(out))["checked"]
    build = candidate.cli(
        "model",
        "build",
        str(out),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "92" * 32,
    )
    assert len(_members(build)) == 8


def test_template_publication_labels_do_not_select_semantics(
    template_context, tmp_path, run_cli
):
    context, kinds, authority = template_context
    plan = (
        ProtocolArtifactSetMemberSpec(
            "model-source-package", logical_name="editable-source", role="primary"
        ),
        ProtocolArtifactSetMemberSpec(
            "template-instantiation-receipt", logical_name="model-source-package"
        ),
    )
    descriptor = replace(
        TEMPLATE_INSTANTIATE,
        artifact_set=plan,
        handler=template_instantiate_handler(
            minimal_release,
            authority_context_provider=lambda: context,
            artifact_set=plan,
        ),
    )
    out = tmp_path / "labels.json"
    code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--package-id",
            "example.labels",
            "--out",
            str(out),
            "--invocation-key",
            "93" * 32,
        ],
        registry=(descriptor,),
    )
    assert (code, stderr) == (0, ""), stdout
    members = _members(json.loads(stdout))
    assert set(members) == {"editable-source", "model-source-package"}
    assert members["editable-source"]["manifest"]["id"] == "example.labels"
    assert (
        members["model-source-package"]["artifact_kind"]
        == kinds["template-instantiation-receipt"]
    )
    assert json.loads(out.read_text()) == members["editable-source"]


@pytest.mark.parametrize("mutation", ("unbound-evidence", "wrong-release-kind"))
def test_renamed_template_still_refuses_reidentified_semantic_drift(
    template_context, run_cli, mutation
):
    context, kinds, authority = template_context
    release = cast(dict[str, Any], minimal_release(context))
    if mutation == "unbound-evidence":
        golden = next(
            member
            for member in release["members"]
            if member["member_kind"] == kinds["golden-scenario"]
        )
        golden["payload"]["experiment"] = "absent.experiment"
    else:
        release["artifact_kind"] = "unselected.template-release"
    _reidentify_release(release)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _context: deepcopy(release),
            authority_context_provider=lambda: context,
        ),
    )
    code, stdout, stderr = run_cli(
        ["template", "get", "--id", "standard.quantity-minimal"], registry=(descriptor,)
    )
    assert (code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == "language.source_contract_mismatch"
