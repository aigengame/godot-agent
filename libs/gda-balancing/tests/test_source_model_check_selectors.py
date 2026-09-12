"""Model checks select semantic members without a second authored Source path."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.model._resolution import _model_check_diagnostics
from gda_balancing.domain.diagnostics import ArtifactLocation
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_resolution_parse_reason import _definitions, _profile
from test_source_semantic_roles import _rename_role_field
from test_source_wire_owners import _source_schema
from test_trace_protocol_structure import _authored, _graph, _index


def _renamed_candidate():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    schema = _source_schema(authored)
    target = "source.modules/~"
    _rename_role_field(schema, {"source"}, "modules", target)
    for recipe in _profile(authored)["relation_recipes"]:
        terms = [binding["source"] for binding in recipe["bindings"]]
        terms.extend(field["term"] for field in recipe["fields"])
        terms.extend(
            predicate[side]
            for predicate in recipe["predicates"]
            for side in ("left", "right")
        )
        for term in terms:
            if term["root"] == "source" and term["path"][:1] == ["modules"]:
                term["path"][0] = target
    renamed = deepcopy(source)
    renamed[target] = renamed.pop("modules")
    return kernel, language, authored, source, renamed, target


def test_semantic_model_checks_keep_their_meaning_through_public_source_rename(
    tmp_path,
):
    kernel, language, authored, source, renamed, target = _renamed_candidate()
    checks = _definitions(authored, "language.model_checks")
    assert len(checks) == 5
    assert all(
        "selector" not in check and "scope_selector" not in check for check in checks
    )
    assert checks == language["language"]["model_checks"]
    graph = _graph(kernel, authored)
    assert _consumer_a(kernel, graph)["admitted"]
    index = _index(kernel, graph)
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext)
    candidate = _PublicCandidate(tmp_path / "renamed", authorities=(kernel, index))
    candidate.write_source(renamed)
    candidate.cli("model", "check", str(candidate.source))
    built = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "built"),
        "--invocation-key",
        "ad" * 32,
    )
    assert len(_members(built)) == 8

    # These checks run even before Source validation succeeds. Their selected
    # row and diagnostic address must keep the renamed authored container.
    for value, root in ((source, "modules"), (renamed, target)):
        symbol = value[root][0]["symbols"][0]
        symbol["domain"] = {"minimum": 2, "maximum": 1}
    original = _model_check_diagnostics(source, "source", language)
    changed = _model_check_diagnostics(renamed, "source", index)
    assert len(original) == len(changed) == 1
    assert changed[0].code == original[0].code
    assert isinstance(changed[0].primary, ArtifactLocation)
    assert isinstance(original[0].primary, ArtifactLocation)
    assert changed[0].primary.pointer == original[0].primary.pointer.replace(
        "/modules/", "/source.modules~1~0/", 1
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "old-selector",
        "old-scope",
        "missing",
        "empty",
        "unknown",
        "unknown-scope",
        "wildcard-scalar",
        "authored-spelling",
    ],
)
def test_model_check_semantic_selector_must_resolve_to_its_declared_source_owner(
    mutation,
):
    kernel, _language, authored, _source, _renamed, target = _renamed_candidate()
    checks = _definitions(authored, "language.model_checks")
    check = checks[0]
    if mutation == "old-selector":
        check["selector"] = check.pop("semantic_selector")
    elif mutation == "old-scope":
        scoped = next(row for row in checks if "semantic_scope_selector" in row)
        scoped["scope_selector"] = scoped.pop("semantic_scope_selector")
    elif mutation == "missing":
        del check["semantic_selector"]
    elif mutation == "empty":
        check["semantic_selector"] = []
    elif mutation == "unknown":
        check["semantic_selector"][-1] = "unknown-member"
    elif mutation == "unknown-scope":
        check["semantic_scope_selector"] = ["unknown-role"]
    elif mutation == "wildcard-scalar":
        check["semantic_selector"] = ["schema_version", "*"]
    else:
        check["semantic_selector"][0] = target
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert not result["admitted"]
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]
