"""Static pure calls retain real operand and result identities before traversal."""

from copy import deepcopy
from typing import Any, cast

import pytest

from gda_balancing.domain.model._lowering import _resolved_call_sites
from schema2_authority_support import mutable_authorities


def _pure_call(*, prior_local: bool, site: str):
    kernel, language_bundle = mutable_authorities()
    quantity = next(
        package
        for package in language_bundle["language"]["packages"]
        if package["id"] == "core.quantity"
    )
    child = deepcopy(
        next(
            operation
            for closure in quantity["semantic_closure"]
            if closure["authority_path"] == "language.operations"
            for operation in closure["definitions"]
            if operation["id"] == "quantity.add"
        )
    )
    parent = deepcopy(child)
    parent["id"] = "bounded.numeric-step"
    parent["body"] = (
        [{"node": "copy", "target": "rebound", "value": "left"}] if prior_local else []
    )
    parent["body"].append(
        {
            "node": "invoke",
            "site": site,
            "operation": {"package": "core.quantity", "id": "quantity.add"},
            "arguments": [
                {
                    "port": "left",
                    "operand": (
                        {"kind": "local", "local": "rebound"}
                        if prior_local
                        else {"kind": "port", "port": "left"}
                    ),
                },
                {"port": "right", "operand": {"kind": "port", "port": "right"}},
            ],
            "result": {"kind": "local", "name": "result"},
            "outcomes": [],
        }
    )
    parent["resource_bounds"]["max_steps"] = 3 if prior_local else 2
    selected = {
        "operations": [
            {"package": "core.quantity", "definition": parent},
            {"package": "core.quantity", "definition": child},
        ]
    }
    return kernel, language_bundle, selected


@pytest.mark.parametrize("prior_local", [False, True], ids=["port", "value-local"])
@pytest.mark.parametrize("site", ["sum", "@0", "x/@0", "x~1@0"])
def test_pure_call_projection_has_real_binding_and_no_event_outcome(
    prior_local: bool, site: str
):
    kernel, language_bundle, selected = _pure_call(prior_local=prior_local, site=site)

    calls = cast(
        list[dict[str, Any]],
        _resolved_call_sites(
            kernel, selected, language_bundle=language_bundle, declarations=[]
        ),
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["site"] == site  # Static identity uses the authored name.
    assert call["outcomes"] == []
    assert call["closure"] == {
        "effects": [],
        "refusals": ["runtime.reason.numeric-overflow"],
        "resource_charge": 2,
    }
    assert call["result"]["binding"] == {"kind": "local", "name": "result"}
    assert [row["port"]["name"] for row in call["arguments"]] == ["left", "right"]
    assert call["arguments"][0]["operand"]["kind"] == (
        "local" if prior_local else "port"
    )
    assert all(row["port"]["identity"] for row in call["arguments"])
    assert len({row["operand"]["identity"] for row in call["arguments"]}) == 2


def test_distinct_pure_sites_keep_distinct_static_identities():
    identities = set()
    for site in ("@0", "x/@0", "x~1@0"):
        kernel, language_bundle, selected = _pure_call(prior_local=True, site=site)
        identities.add(
            _resolved_call_sites(
                kernel, selected, language_bundle=language_bundle, declarations=[]
            )[0]["identity"]
        )
    assert len(identities) == 3
