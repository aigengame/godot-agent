"""Source diagnostics follow the validated Schema owner at the authored address."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import check_model_source_value
from test_source_model_check_selectors import _renamed_candidate
from test_source_semantic_roles import _candidate
from test_trace_protocol_structure import _graph, _index


@pytest.mark.parametrize("renamed", [False, True])
def test_symbol_schema_branch_refusal_keeps_its_owner_after_source_rename(renamed):
    _kernel, _sealed, context, source, original = _candidate("routing")
    if renamed:
        symbol = source["sections/~"][0]["declarations/~"][0]
        # The former authored spelling is now an extra property, not an alias.
        symbol["symbol"] = symbol["name/~"]
        pointer = "/sections~1~0/0/declarations~1~0/0/symbol"
    else:
        source = original
        context = packaged_authority_context()
        source["modules"][0]["symbols"][0]["unexpected_member"] = "extra"
        pointer = "/modules/0/symbols/0/unexpected_member"
    result = check_model_source_value(source, authority_context=context)
    assert isinstance(result, Schema2RefusalReport)
    assert [
        (row.code, row.primary.model_dump()["pointer"]) for row in result.diagnostics
    ] == [("language.source_contract_mismatch", pointer)]


def test_true_symbol_resource_refusal_survives_the_renamed_schema_boundary():
    kernel, language, authored, _original, source, member = _renamed_candidate()
    bound = language["resources"]["max_symbols"]
    module = source[member][0]
    nominal = module["symbols"][0]
    module["symbols"] = [
        {**deepcopy(nominal), "symbol": f"item_{i}"} for i in range(bound + 1)
    ]
    assert len(json.dumps(source).encode()) < language["resources"]["max_source_bytes"]
    result = check_model_source_value(
        source, kernel=kernel, language_bundle=_index(kernel, _graph(kernel, authored))
    )
    assert isinstance(result, Schema2RefusalReport)
    assert any(
        row.code == "language.resource_exhausted"
        and row.primary.model_dump()["pointer"]
        == f"/source.modules~1~0/0/symbols/{bound}"
        for row in result.diagnostics
    )
