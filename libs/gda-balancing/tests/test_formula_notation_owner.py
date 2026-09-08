"""Formula Model admission follows the admitted schema owner namespace."""

from copy import deepcopy

import pytest

from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _bind_package_vector_set,
    _reidentify_package_release,
)
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_experiment_cli import _rpg_model_source
from test_schema2_model_cli import _model_source


def _rename_schema_namespace(value):
    # This bounded witness changes namespace references, not Kernel-owned
    # constructor/profile/reason tokens that merely share the same prefix.
    if isinstance(value, dict):
        for key in value:
            value[key] = _rename_schema_namespace(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _rename_schema_namespace(item)
    elif value == "standard.schema":
        return "probe.schema"
    return value


@pytest.mark.parametrize(
    "source_factory", (_rpg_model_source, _model_source), ids=("formula", "symbols")
)
def test_public_model_uses_the_renamed_admitted_schema_owner(tmp_path, source_factory):
    kernel, baseline = mutable_authorities()
    original_kernel = deepcopy(kernel)
    renamed = deepcopy(baseline)
    _rename_schema_namespace(renamed)
    _rename_schema_namespace(renamed.package_conformance_vector_sets)
    vector_sets = {
        row["package_id"]: row for row in renamed.package_conformance_vector_sets
    }
    for package in renamed["language"]["packages"]:
        _bind_package_vector_set(package, vector_sets[package["id"]])
    _reidentify_graph_root(renamed)

    source = source_factory()
    source_bytes = []
    kernel_bytes = []
    notation_definitions = []
    for namespace, language in (
        ("standard.schema", baseline),
        ("probe.schema", renamed),
    ):
        context = admit_authority_context(kernel, language)
        assert isinstance(context, AdmittedAuthorityContext), context
        # Derive the expected owner directly from the admitted graph; do not
        # consult the host Formula owner resolver under test.
        schemas = [
            (package["id"], definition)
            for package in language.package_releases
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.wire_schemas"
            for definition in closure["definitions"]
            if definition.get("artifact_kind") == "model-source-package"
        ]
        assert [owner for owner, _schema in schemas] == [namespace]
        definitions = schemas[0][1]
        notation_definitions.append(
            [
                definitions["formula_grammar"],
                definitions["operation_notation_schema"],
            ]
        )
        candidate = _PublicCandidate(
            tmp_path / namespace, authorities=(kernel, language)
        )
        candidate.write_source(source)
        source_bytes.append(candidate.source.read_bytes())
        kernel_bytes.append(
            (
                candidate.runtime / "gda_balancing/schema2/authorities/kernel.json"
            ).read_bytes()
        )
        checked = candidate.cli("model", "check", str(candidate.source))
        assert checked["checked"] is True
        assert checked["kernel_identity"] == original_kernel["content_identity"]
        receipt = candidate.cli(
            "model",
            "build",
            str(candidate.source),
            "--out",
            str(candidate.directory / "build"),
            "--invocation-key",
            "06" * 32,
        )
        assert set(_members(receipt)) == {
            "build-receipt",
            "capability-manifest",
            "debug-map",
            "model-explanation",
            "package-lock",
            "resolution-receipt",
            "resolved-model",
            "rir-semantic-payload",
        }

    assert kernel == original_kernel
    assert source_bytes[0] == source_bytes[1]
    assert kernel_bytes[0] == kernel_bytes[1]
    assert notation_definitions[0] == notation_definitions[1]


@pytest.mark.parametrize("mutation", ("duplicate", "missing"))
def test_formula_schema_owner_must_be_unique_at_authority_admission(mutation):
    kernel, language = mutable_authorities()
    assert isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    package = next(
        package
        for package in language["language"]["packages"]
        if package["id"] == "standard.schema"
    )
    closure = next(
        closure
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.wire_schemas"
    )
    if mutation == "duplicate":
        closure["definitions"].append(deepcopy(closure["definitions"][0]))
    else:
        closure["definitions"].clear()
        package["exports"]["wire_schemas"].clear()
    vector_set = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == package["id"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(language)
    resealed = deepcopy(package)
    _reidentify_package_release(resealed)
    assert resealed == package

    # The real Authority boundary refuses the graph before Formula lookup. The
    # duplicate is structurally invalid even with freshly recomputed identities.
    result = admit_authority_context(kernel, language)
    assert isinstance(result, BootstrapAdmission)
    assert result.admitted is False
    assert {(row.code, row.stage) for row in result.diagnostics} == (
        {("kernel.identity_mismatch", "ingress")}
        if mutation == "duplicate"
        else {("kernel.vector_mismatch", "static")}
    )
