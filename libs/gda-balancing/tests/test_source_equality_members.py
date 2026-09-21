"""Source equality projections follow semantic annotations, not authored keys."""

from copy import deepcopy
import json
from pathlib import Path
from typing import cast

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    admit_resolved_model,
)
from gda_balancing.domain.model._compilation import lower_checked_model
from gda_balancing.domain.model._lowering import _resolved_source_symbols
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_resolved_symbols,
    _reference_semantic_artifacts,
    _reference_admits_semantic_artifacts,
)
from test_source_semantic_roles import _rename_role_field
from test_source_wire_owners import _source_schema
from test_trace_protocol_structure import _authored, _graph, _index


@pytest.mark.parametrize(
    "member",
    [
        "domain",
        "domain_kind",
        "kind",
        "numeric_policy",
        "representation",
        "role",
        "unit",
        "value_policy",
    ],
)
def test_annotated_symbol_members_reach_public_compilation_and_identical_facts(
    tmp_path, member
):
    kernel, language = mutable_authorities()
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    control = check_model_source_value(source, kernel=kernel, language_bundle=language)
    assert isinstance(control, CheckedModel)
    expected_facts = [
        fields
        for fields, _ in _resolved_source_symbols(
            control.source_projection, language, kernel
        )
    ]
    assert len(expected_facts) == 5
    assert sum(member in row for row in expected_facts) >= 3
    expected_rir = lower_checked_model(control)["rir-semantic-payload"]
    authored = _authored(language)
    schema = _source_schema(authored)
    target = "wire/" + member + "~"
    _rename_role_field(schema, {"symbol"}, member, target)
    renamed = deepcopy(source)
    changed = 0
    for module in renamed["modules"]:
        for symbol in module["symbols"]:
            if member in symbol:
                symbol[target] = symbol.pop(member)
                changed += 1
    assert changed >= 3
    sealed = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, sealed)
        assert result["admitted"], (consumer.__name__, result)
    context = admit_authority_context(kernel, _index(kernel, sealed))
    assert isinstance(context, AdmittedAuthorityContext)
    checked = check_model_source_value(renamed, authority_context=context)
    independent = _reference_check_source(renamed, kernel, context.language_bundle)
    assert isinstance(checked, CheckedModel), checked
    assert isinstance(independent, ModelSourceContext), independent
    for rows in (
        _resolved_source_symbols(
            checked.source_projection, context.language_bundle, kernel
        ),
        _reference_resolved_symbols(independent),
    ):
        assert canonical_bytes([fields for fields, _ in rows]) == canonical_bytes(
            cast(JsonValue, expected_facts)
        )
    public = _PublicCandidate(tmp_path, authorities=(kernel, sealed))
    public.write_source(renamed)
    public.cli("model", "check", str(public.source))
    built = _members(
        public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "ec" * 32,
        )
    )
    assert len(built) == 8
    assert canonical_bytes(built["rir-semantic-payload"]) == canonical_bytes(
        expected_rir
    )
    expected = _reference_semantic_artifacts(independent)
    assert len(expected) == 4
    assert all(
        canonical_bytes(built[role]) == canonical_bytes(value)
        for role, value in expected.items()
    )
    assert _reference_admits_semantic_artifacts(built, independent)
    assert admit_resolved_model(
        {
            role: expected[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted


@pytest.mark.parametrize("member", ["minimum", "maximum"])
def test_native_interval_payload_has_no_source_member_rename_authority(member):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = _source_schema(authored)
    interval = schema["properties"]["modules"]["items"]["properties"]["symbols"][
        "items"
    ]["properties"]["domain"]
    assert "semantic_role" not in interval
    assert "semantic_member" not in interval["properties"][member]
    interval["properties"]["wire_" + member] = interval["properties"].pop(member)
    interval["required"] = [
        "wire_" + member if name == member else name for name in interval["required"]
    ]
    sealed = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, sealed)["admitted"]
