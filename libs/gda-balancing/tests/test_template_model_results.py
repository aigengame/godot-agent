"""Template Model results retain admitted Fact coordinates without textual aliases."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from typing import Any, cast

import pytest

from conftest import _run
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.template_validation import (
    _template_admission_profiles_are_closed,
)
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    checked_model_template_facts,
    model_source_identity_domain,
)
from gda_balancing.domain.template import minimal_release, validate_template_release
from gda_balancing.domain.template._release_semantics import (
    _template_primitive_execution_is_supported,
)
from gda_balancing.interfaces.cli.template_catalog import (
    TEMPLATE_GET,
    template_get_handler,
)
from gda_balancing.interfaces.cli.template_instantiation import (
    TEMPLATE_INSTANTIATE,
    template_instantiate_handler,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _source as _structured_source
from test_schema2_template_cli import _reidentify_release


def _model_primitive(kernel):
    return next(
        primitive
        for primitive in kernel["meta_format"]["template_admission"]["primitive_spec"][
            "primitives"
        ]
        if primitive["id"] == "model-source-admission"
    )


def _payload(release, kind):
    return next(
        row["payload"] for row in release["members"] if row["member_kind"] == kind
    )


def _release_case(context, *, collision=False, mutation=None):
    """Author exact Source coordinates and defaults, without reading Model results."""
    release = minimal_release(context)
    source = _payload(release, "model-source-package")
    if collision:
        symbol = deepcopy(source["modules"][0]["symbols"][0])
        imports = deepcopy(source["modules"][0]["imports"])
        symbol["role"] = "constant"
        symbol["value_policy"] = {"mode": "model-fixed", "value": 50}
        source["manifest"] = {
            "id": "example.qualified-collision",
            "entry_module": "left",
        }
        source["modules"] = [
            {
                "id": module,
                "imports": deepcopy(imports),
                "symbols": [
                    {
                        **deepcopy(symbol),
                        "symbol": name,
                        "domain": {"minimum": minimum, "maximum": maximum},
                    }
                ],
            }
            for module, name, minimum, maximum in (
                ("left.part", "value", 0, 60),
                ("left", "part.value", 40, 100),
            )
        ]
        source["entrypoints"] = []
        del source["formula_bindings"]
    source_identity = content_identity(
        model_source_identity_domain(context.language_bundle), source
    )
    _payload(release, "experiment-template")["model_source_identity"] = source_identity
    golden = _payload(release, "golden-scenario")
    golden["model_source_identity"] = source_identity
    coordinates = (
        [
            {"model": source["manifest"]["id"], "module": "left.part", "name": "value"},
            {"model": source["manifest"]["id"], "module": "left", "name": "part.value"},
        ]
        if collision
        else [{"model": source["manifest"]["id"], "module": "main", "name": "value"}]
    )
    values = [30, 70] if collision else [50]
    defaults = _payload(release, "template-defaults")
    defaults["symbol_values"] = [
        {"symbol": deepcopy(coordinate), "value": value}
        for coordinate, value in zip(coordinates, values, strict=True)
    ]
    golden["symbol"] = deepcopy(coordinates[0])
    golden["value"] = values[0]
    if mutation == "unknown-coordinate":
        defaults["symbol_values"][0]["symbol"]["name"] = "absent"
    elif mutation == "wrong-model":
        defaults["symbol_values"][0]["symbol"]["model"] = "example.other-model"
    elif mutation == "wrong-interval":
        assert collision
        defaults["symbol_values"][0]["value"] = 70
        golden["value"] = 70
    elif mutation == "old-string":
        defaults["symbol_values"][0]["symbol"] = (
            "left.part.value" if collision else "main.value"
        )
        golden["symbol"] = defaults["symbol_values"][0]["symbol"]
    elif mutation is not None:
        raise AssertionError(f"unknown authoring mutation: {mutation}")
    return _reidentify_release(release)


@pytest.mark.parametrize(
    "mutation",
    [
        "old-result-members",
        "old-and-new",
        "missing-results",
        "missing-result",
        "extra-result",
        "unknown-origin",
        "swapped-origins",
        "extra-origin-field",
    ],
)
def test_template_model_result_contract_is_executable_and_closed(mutation):
    kernel, ldb = mutable_authorities()
    assert _template_admission_profiles_are_closed(ldb, kernel["meta_format"])
    primitive = _model_primitive(kernel)
    assert _template_primitive_execution_is_supported(primitive)
    if mutation == "old-result-members":
        primitive["result_members"] = list(primitive.pop("results"))
    elif mutation == "old-and-new":
        primitive["result_members"] = list(primitive["results"])
    elif mutation == "missing-results":
        del primitive["results"]
    elif mutation == "missing-result":
        del primitive["results"]["source_symbols"]
    elif mutation == "extra-result":
        primitive["results"]["opaque"] = {"origin": "admitted-namespace-selection"}
    elif mutation == "unknown-origin":
        primitive["results"]["source_symbols"]["origin"] = "opaque-source"
    elif mutation == "swapped-origins":
        (
            primitive["results"]["source_symbols"],
            primitive["results"]["resolved_packages"],
        ) = (
            primitive["results"]["resolved_packages"],
            primitive["results"]["source_symbols"],
        )
    else:
        primitive["results"]["source_symbols"]["schema"] = {}
    # Exercise the actual law checker before the separate Kernel fingerprint gate.
    assert not _template_admission_profiles_are_closed(ldb, kernel["meta_format"])
    assert not _template_primitive_execution_is_supported(primitive)
    assert _consumer_a(kernel, ldb)["admitted"] is False


@pytest.mark.parametrize("structured", [False, True], ids=["quantity", "structured"])
def test_template_results_preserve_each_admitted_initial_fact_field(structured):
    context = packaged_authority_context()
    source = (
        _structured_source()
        if structured
        else _payload(minimal_release(context), "model-source-package")
    )
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel)
    facts: dict[str, Any] = checked_model_template_facts(checked)
    assert set(facts) == set(_model_primitive(context.kernel)["results"])
    assert facts["root_requirements"] == source["package_requirements"]
    assert facts["resolved_packages"] == [
        package.namespace for package in checked.namespace_selection.packages
    ]
    assert canonical_bytes(facts["source_symbols"]) == canonical_bytes(
        [fields for fields, _ in checked.hir.source_rows]
    )
    assert all("id" not in row for row in facts["source_symbols"])
    if structured:
        typed = [
            row
            for row in facts["source_symbols"]
            if row["type_identity"]
            == {"package": "standard.conformance.structured", "id": "IntList4"}
        ]
        assert typed
        assert all("domain" not in row for row in typed)
        assert all(
            set(row["resolved_symbol"]) == {"model", "module", "name"} for row in typed
        )


@pytest.mark.parametrize("collision", [False, True], ids=["minimal", "colliding-text"])
def test_public_template_coordinates_instantiate_without_changing_the_release(
    tmp_path, monkeypatch, collision
):
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a5" * 32)
    context = packaged_authority_context()
    release = _release_case(context, collision=collision)
    before = canonical_bytes(release)
    source = _payload(release, "model-source-package")
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel)
    if collision:
        coordinates = [
            row["resolved_symbol"]
            for row in cast(
                list[dict[str, Any]],
                checked_model_template_facts(checked)["source_symbols"],
            )
        ]
        assert len({canonical_bytes(coordinate) for coordinate in coordinates}) == 2
        assert (
            len(
                {
                    coordinate["module"] + "." + coordinate["name"]
                    for coordinate in coordinates
                }
            )
            == 1
        )
    descriptors = (
        replace(
            TEMPLATE_GET,
            handler=template_get_handler(
                lambda _ctx: deepcopy(release),
                authority_context_provider=lambda: context,
            ),
        ),
        replace(
            TEMPLATE_INSTANTIATE,
            handler=template_instantiate_handler(
                lambda _ctx: deepcopy(release),
                authority_context_provider=lambda: context,
            ),
        ),
    )
    observations = []
    args = ["template", "get", "--id", release["id"]]
    code, stdout, stderr = _run(args, registry=descriptors)
    observations.append(
        {"argv": args, "code": code, "stdout": stdout, "stderr": stderr}
    )
    assert (code, stderr) == (0, "")
    output = tmp_path / "instantiated.json"
    model = (
        "example.instantiated-collision"
        if collision
        else "example.instantiated-minimal"
    )
    args = [
        "template",
        "instantiate",
        "--id",
        release["id"],
        "--package-id",
        model,
        "--out",
        str(output),
        "--invocation-key",
        hashlib.sha256(model.encode()).hexdigest(),
    ]
    code, stdout, stderr = _run(args, registry=descriptors)
    observations.append(
        {"argv": args, "code": code, "stdout": stdout, "stderr": stderr}
    )
    (tmp_path / "public-receipt.json").write_text(json.dumps(observations, indent=2))
    assert (code, stderr) == (0, "")
    instance = json.loads(output.read_bytes())
    expected = deepcopy(source)
    expected["manifest"]["id"] = model
    expected["manifest"]["template_provenance"] = {
        "template_id": release["id"],
        "template_identity": release["content_identity"],
        "starter_identity": content_identity(
            model_source_identity_domain(context.language_bundle), source
        ),
    }
    assert instance == expected
    admitted = check_model_source_value(instance, authority_context=context)
    assert isinstance(admitted, CheckedModel)
    assert all(
        row["resolved_symbol"]["model"] == model
        for row in cast(
            list[dict[str, Any]],
            checked_model_template_facts(admitted)["source_symbols"],
        )
    )
    assert canonical_bytes(release) == before
    assert (
        validate_template_release(
            release, context.kernel, context.language_bundle, context
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation", ["unknown-coordinate", "wrong-model", "wrong-interval", "old-string"]
)
def test_public_template_rejects_wrong_coordinate_contracts(tmp_path, mutation):
    context = packaged_authority_context()
    release = _release_case(context, collision=True, mutation=mutation)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _ctx: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    args = ["template", "get", "--id", release["id"]]
    code, stdout, stderr = _run(args, registry=(descriptor,))
    (tmp_path / "public-refusal.json").write_text(
        json.dumps(
            {"argv": args, "code": code, "stdout": stdout, "stderr": stderr}, indent=2
        )
    )
    assert (code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["category"] == "refusal"
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == "language.source_contract_mismatch"
    assert error["diagnostics"][0]["primary"]["pointer"] == "/members"
    if mutation != "old-string":
        judgment = (
            "template.default-domain"
            if mutation == "wrong-interval"
            else "template.default-symbols"
        )
        assert judgment in error["diagnostics"][0]["message"]
