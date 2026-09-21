"""Template inventory follows real local bindings and standalone Schema fields."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from conftest import _run
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.template import minimal_release, validate_template_release
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from gda_balancing.domain.model._resolution import ModelSourceContext
from gda_balancing.domain.wire_schema import wire_schema_identity_for_kind
from gda_balancing.interfaces.cli.template_catalog import (
    TEMPLATE_GET,
    template_get_handler,
)
from gda_balancing.interfaces.cli.template_instantiation import (
    TEMPLATE_INSTANTIATE,
    template_instantiate_handler,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _authority_path_rows,
    _renamed_owner,
    _template_inventory,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
    validate_token_bijection,
)
from schema2_extension_renaming_support import _rewrite_positions
from test_schema2_model_lowerer_conformance import _reference_check_source
from test_schema2_template_cli import _reidentify_release, _reference_template_admission
from test_trace_protocol_structure import _authored, _graph, _index


@pytest.fixture(scope="module")
def witness():
    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    inventory = read_extension_inventory(kernel, graph)
    return kernel, graph, inventory


def _schemas(kernel, graph):
    return {
        row["artifact_kind"]: (row, pointer)
        for _, row, pointer in _authority_path_rows(
            kernel, graph, "language_bundle.language.artifact_wire_schemas"
        )
    }


def _profile(kernel, graph):
    return next(
        _authority_path_rows(
            kernel, graph, "language_bundle.language.template_admission_profiles"
        )
    )[1]


def _scope_rename(graph, inventory, names):
    assert names.keys() <= inventory.tokens - inventory.reserved
    values, keys = {}, {}
    for row in inventory.occurrences:
        if row.token not in names:
            continue
        assert row.location in {"key", "value"}
        (keys if row.location == "key" else values)[row.pointer] = names[row.token]
    return _rewrite_positions(graph, values, keys)


def test_template_profile_and_all_nine_variable_schemas_have_complete_owners(witness):
    kernel, graph, inventory = witness
    validate_extension_inventory(kernel, graph, inventory)
    rows, reserved, roots, schemas = _template_inventory(kernel, graph)
    assert len(schemas) == 9
    assert len(roots) == 10
    assert not any(g.pointer in roots for g in inventory.uncovered)
    assert not inventory.uncovered
    for role in ("template-role", "template-derived", "template-judgment"):
        declared = {
            o.token for o in rows if o.token.role == role and o.use == "declaration"
        }
        assert declared
        assert not declared & inventory.reserved
        assert all(o.token in declared for o in rows if o.token.role == role)
    schema_tokens = {o.token for o in rows if o.token.role == "template-field"}
    assert {t.owner[1] for t in schema_tokens} == {
        row["member_kind"]
        for row in _profile(kernel, graph)["member_roles"]
        if row["member_kind"] != "model-source-package"
    }
    # Canonical equality to the admitted Fact coordinate fixes these actual
    # object fields; equally-spelled unrelated fields do not inherit that owner.
    bound = schema_tokens & reserved
    assert {t.name for t in bound} == {"model", "module", "name"}
    assert {t.owner[1] for t in bound} == {"template-defaults", "golden-scenario"}
    assert len(bound) == 6
    scalar = [o for o in rows if o.pointer.endswith("/properties/kind/const")]
    assert len(scalar) == 1
    assert scalar[0].token == AuthorityToken("language.quantity.kinds", (), "scalar")
    assert not any(o.token.name in {"text/markdown", "accepted", "2.0.0"} for o in rows)


@pytest.mark.parametrize(
    "category",
    ["role", "derived", "judgment", "schema-key", "required", "relative", "kind-const"],
)
@pytest.mark.parametrize("mutation", ["omitted", "misowned"])
def test_template_reverse_coverage_rejects_missing_and_misowned_occurrences(
    witness, category, mutation
):
    kernel, graph, inventory = witness
    rows, _, _, _ = _template_inventory(kernel, graph)
    predicates = {
        "role": lambda o: o.token.role == "template-role" and o.use == "declaration",
        "derived": lambda o: (
            o.token.role == "template-derived" and o.use == "reference"
        ),
        "judgment": lambda o: o.token.role == "template-judgment",
        "schema-key": lambda o: (
            o.token.role == "template-field" and o.location == "key"
        ),
        "required": lambda o: (
            o.token.role == "template-field" and "/required/" in o.pointer
        ),
        "relative": lambda o: "/arguments/source_scope_path/" in o.pointer,
        "kind-const": lambda o: o.pointer.endswith("/properties/kind/const"),
    }
    selected = next(o for o in rows if predicates[category](o))
    occurrences = list(inventory.occurrences)
    tokens = set(inventory.tokens)
    if mutation == "omitted":
        occurrences.remove(selected)
        if not any(o.token == selected.token for o in occurrences):
            tokens.remove(selected.token)
    else:
        wrong = replace(selected, token=replace(selected.token, owner=("other-owner",)))
        occurrences[occurrences.index(selected)] = wrong
        tokens.add(wrong.token)
        if not any(o.token == selected.token for o in occurrences):
            tokens.remove(selected.token)
    forged = replace(
        inventory, tokens=frozenset(tokens), occurrences=tuple(occurrences)
    )
    with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
        validate_extension_inventory(kernel, graph, forged)


def test_template_schema_member_omission_and_false_reservations_refuse(witness):
    kernel, graph, inventory = witness
    schemas = _schemas(kernel, graph)
    _, pointer = schemas["template-documentation"]
    kept = tuple(
        o
        for o in inventory.occurrences
        if not o.pointer.startswith(pointer + "/schema/")
    )
    forged = replace(
        inventory, occurrences=kept, tokens=frozenset(o.token for o in kept)
    )
    with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
        validate_extension_inventory(kernel, graph, forged)
    role = next(t for t in inventory.tokens if t.role == "template-role")
    bound = next(t for t in inventory.reserved if t.role == "template-field")
    for reserved in (inventory.reserved | {role}, inventory.reserved - {bound}):
        with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
            validate_extension_inventory(
                kernel, graph, replace(inventory, reserved=frozenset(reserved))
            )


def test_template_reserved_field_names_keep_their_owner_bijection(witness):
    kernel, graph, inventory = witness
    schema_ids = {t.owner[1] for t in inventory.tokens if t.role == "template-field"}
    names = {
        token: "owner_" + token.name.replace("-", "_")
        for token in inventory.tokens - inventory.reserved
        if token.role == "language.artifact_wire_schemas" and token.name in schema_ids
    }
    candidate = _scope_rename(graph, inventory, names)
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    correspondence = dict(token_bijection_from_names(inventory, names))
    expected = {
        AuthorityToken(
            token.role,
            _renamed_owner(token, correspondence),
            token.name,
        )
        for token in inventory.reserved
        if token.role == "template-field"
    }

    assert {
        token for token in renamed_inventory.reserved if token.role == "template-field"
    } == expected


def _renamed_payload(value, schema, owner, names):
    """Explicitly author a member against its old instance Schema coordinates."""
    if isinstance(value, dict):
        assert schema["type"] == "object"
        return {
            names.get(
                AuthorityToken("template-field", owner, key), key
            ): _renamed_payload(
                child, schema["properties"][key], (*owner, "member", key), names
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        assert schema["type"] == "array"
        return [
            _renamed_payload(child, schema["items"], (*owner, "items"), names)
            for child in value
        ]
    return deepcopy(value)


def test_coherent_template_local_and_member_schema_rename_uses_real_public_provider(
    witness, tmp_path
):
    kernel, original, inventory = witness
    names = {
        token: f"local_{i}"
        for i, token in enumerate(sorted(inventory.tokens))
        if token.role in {"template-role", "template-derived", "template-judgment"}
    }
    profile_token = AuthorityToken(
        "language.template_admission_profiles", (), _profile(kernel, original)["id"]
    )
    names[profile_token] = "renamed_template_profile"
    schema_ids = {t.owner[1] for t in inventory.tokens if t.role == "template-field"}
    for token in inventory.tokens:
        if token.role == "language.artifact_wire_schemas" and token.name in schema_ids:
            names[token] = "member_" + token.name.replace("-", "_")
        if token.role != "template-field" or token in inventory.reserved:
            continue
        # Every member gets an actual field rename. Nested/relative selectors and
        # independent same-spelling Schema owners are exercised without rewriting
        # the negative vector's Source-value object or its Source pointer bytes.
        selected = {
            "declared-package-dependencies": {"packages"},
            "template-defaults": {"symbol_values", "value"},
            "template-compatibility": {"packages"},
            "template-documentation": {"text", "schema_version"},
            "genre-coverage-matrix": {"rows", "capabilities"},
            "golden-scenario": {"symbol", "value"},
            "negative-vector": {"mutation"},
            "boundary-vector": {"pointer", "expected"},
            "experiment-template": {"metrics", "id", "minimum", "maximum"},
        }
        if token.name in selected[token.owner[1]]:
            names[token] = "field_" + token.name
    candidate = _scope_rename(original, inventory, names)
    original_schema_rows = _schemas(kernel, original)
    original_context = admit_authority_context(
        kernel, _index(kernel, _graph(kernel, deepcopy(original)))
    )
    assert isinstance(original_context, AdmittedAuthorityContext)
    release = json.loads(canonical_bytes(minimal_release(original_context)))
    old_release = deepcopy(release)
    authored = _graph(kernel, candidate)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    context = admit_authority_context(kernel, _index(kernel, authored))
    assert isinstance(context, AdmittedAuthorityContext)
    for member in release["members"]:
        old_kind = member["member_kind"]
        if old_kind not in schema_ids:
            continue
        schema = original_schema_rows[old_kind][0]["schema"]
        member["payload"] = _renamed_payload(
            member["payload"],
            schema,
            ("language.artifact_wire_schemas", old_kind),
            names,
        )
        kind = names.get(
            AuthorityToken("language.artifact_wire_schemas", (), old_kind), old_kind
        )
        assert isinstance(kind, str)
        member["member_kind"] = kind
        member["member_schema_identity"] = wire_schema_identity_for_kind(
            context.language_bundle, kind
        )
        # Explicitly re-author exact authority bindings; never relabel an observed
        # result or ask the built-in quantity_minimal author to adapt to new roles.
        for key in ("language_bundle_identity",):
            if key in member["payload"]:
                member["payload"][key] = context.language_bundle["content_identity"]
    release["language_bundle_identity"] = context.language_bundle["content_identity"]
    _reidentify_release(release)
    assert (
        validate_template_release(
            release, context.kernel, context.language_bundle, context
        )
        is None
    )
    assert _reference_template_admission(
        release, context.kernel, context.language_bundle
    ) == (True, None)
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    correspondence = dict(token_bijection_from_names(inventory, names))
    for old, new in correspondence.items():
        assert old not in renamed_inventory.tokens
        assert new in renamed_inventory.tokens
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, out, err = _run(
        ["template", "get", "--id", release["id"]], registry=(descriptor,)
    )
    assert (code, err) == (0, "")
    assert json.loads(out) == release
    get_receipt = {"exit": code, "stdout": out, "stderr": err}
    instantiate = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda _: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, instantiate_out, err = _run(
        [
            "template",
            "instantiate",
            "--id",
            release["id"],
            "--package-id",
            "example.inventory-template",
            "--out",
            str(tmp_path / "instance.json"),
            "--invocation-key",
            "9" * 64,
        ],
        registry=(instantiate,),
    )
    assert (code, err) == (0, "")
    instance_receipt = {"exit": code, "stdout": instantiate_out, "stderr": err}
    instance = json.loads((tmp_path / "instance.json").read_bytes())
    assert instance["manifest"]["id"] == "example.inventory-template"
    assert isinstance(
        check_model_source_value(instance, authority_context=context), CheckedModel
    )
    assert isinstance(
        _reference_check_source(instance, context.kernel, context.language_bundle),
        ModelSourceContext,
    )
    # An unchanged payload under the real new Schema must fail member validation.
    old_documentation = next(
        m["payload"]
        for m in old_release["members"]
        if m["member_kind"] == "template-documentation"
    )
    bad = deepcopy(release)
    next(
        m
        for m in bad["members"]
        if m["member_kind"]
        == names[
            AuthorityToken(
                "language.artifact_wire_schemas", (), "template-documentation"
            )
        ]
    )["payload"] = old_documentation
    _reidentify_release(bad)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _: deepcopy(bad), authority_context_provider=lambda: context
        ),
    )
    code, bad_out, err = _run(
        ["template", "get", "--id", bad["id"]], registry=(descriptor,)
    )
    assert (code, err) == (2, "")
    (tmp_path / "public-receipt.json").write_text(
        json.dumps(
            {
                "renamed_tokens": [
                    {
                        "role": token.role,
                        "owner": token.owner,
                        "old": token.name,
                        "new": new,
                    }
                    for token, new in sorted(names.items())
                ],
                "get": get_receipt,
                "instantiate": instance_receipt,
                "emitted_source_admitted_by_a_and_b": True,
                "old_member": {"exit": code, "stdout": bad_out, "stderr": err},
            },
            indent=2,
        )
        + "\n"
    )


def test_template_schema_literal_parameters_do_not_capture_equal_names(witness):
    kernel, original, _ = witness
    graph = deepcopy(original)
    documentation, pointer = _schemas(kernel, graph)["template-documentation"]
    # A new unrelated member has the same spelling as a Kernel coordinate field;
    # its regex and literal also equal authored names in other semantic owners.
    documentation["schema"]["properties"]["model"] = {
        "type": "string",
        "const": "source_symbols",
        "pattern": "^source_symbols$",
    }
    documentation["schema"]["required"].append("model")
    authored = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    member = AuthorityToken(
        "template-field",
        ("language.artifact_wire_schemas", "template-documentation"),
        "model",
    )
    assert member in inventory.tokens - inventory.reserved
    assert not any(
        row.pointer
        in {
            pointer + "/schema/properties/model/const",
            pointer + "/schema/properties/model/pattern",
        }
        for row in inventory.occurrences
    )
    context = admit_authority_context(kernel, _index(kernel, authored))
    assert isinstance(context, AdmittedAuthorityContext)
    release = json.loads(canonical_bytes(minimal_release(context)))
    next(
        m["payload"]
        for m in release["members"]
        if m["member_kind"] == "template-documentation"
    )["model"] = "source_symbols"
    _reidentify_release(release)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, _, err = _run(
        ["template", "get", "--id", release["id"]], registry=(descriptor,)
    )
    assert (code, err) == (0, "")


def test_required_coordinate_field_rename_changes_real_template_relation(witness):
    kernel, original, inventory = witness
    names = {
        token: "other_model"
        for token in inventory.reserved
        if token.role == "template-field" and token.name == "model"
    }
    assert len(names) == 2
    # Deliberately violate the proved binding; this is not an authorized bijection.
    values, keys = {}, {}
    for row in inventory.occurrences:
        if row.token in names:
            (keys if row.location == "key" else values)[row.pointer] = names[row.token]
    graph = _rewrite_positions(original, values, keys)
    authored = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    original_context = admit_authority_context(
        kernel, _index(kernel, _graph(kernel, deepcopy(original)))
    )
    context = admit_authority_context(kernel, _index(kernel, authored))
    assert isinstance(original_context, AdmittedAuthorityContext)
    assert isinstance(context, AdmittedAuthorityContext)
    release = json.loads(canonical_bytes(minimal_release(original_context)))
    schemas = _schemas(kernel, original)
    for member in release["members"]:
        kind = member["member_kind"]
        if kind in {"template-defaults", "golden-scenario"}:
            member["payload"] = _renamed_payload(
                member["payload"],
                schemas[kind][0]["schema"],
                ("language.artifact_wire_schemas", kind),
                names,
            )
            member["member_schema_identity"] = wire_schema_identity_for_kind(
                context.language_bundle, kind
            )
        if "language_bundle_identity" in member["payload"]:
            member["payload"]["language_bundle_identity"] = context.language_bundle[
                "content_identity"
            ]
    release["language_bundle_identity"] = context.language_bundle["content_identity"]
    _reidentify_release(release)
    refusal = validate_template_release(
        release, context.kernel, context.language_bundle, context
    )
    assert refusal is not None
    assert _reference_template_admission(
        release, context.kernel, context.language_bundle
    ) == (False, "language.source_contract_mismatch")
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, out, err = _run(
        ["template", "get", "--id", release["id"]], registry=(descriptor,)
    )
    assert (code, err) == (2, "")
    assert (
        "template.default-symbols"
        in json.loads(out)["error"]["diagnostics"][0]["message"]
    )


def _admitted_template_graph(kernel, graph):
    authored = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, authored)
        assert result["admitted"], result["diagnostics"]
    context = admit_authority_context(kernel, _index(kernel, authored))
    assert isinstance(context, AdmittedAuthorityContext)
    return context


def _get_rebound_release(context, seed):
    release = deepcopy(seed)
    for member in release["members"]:
        member["member_schema_identity"] = wire_schema_identity_for_kind(
            context.language_bundle, member["member_kind"]
        )
        if "language_bundle_identity" in member["payload"]:
            member["payload"]["language_bundle_identity"] = context.language_bundle[
                "content_identity"
            ]
    release["language_bundle_identity"] = context.language_bundle["content_identity"]
    _reidentify_release(release)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, stdout, stderr = _run(
        ["template", "get", "--id", release["id"]], registry=(descriptor,)
    )
    assert stderr == ""
    return code, json.loads(stdout)


@pytest.mark.parametrize("keyword", ["const", "enum"])
@pytest.mark.parametrize("location", ["plain", "root", "nested", "array"])
def test_template_literal_keys_follow_the_public_member_schema(
    witness, tmp_path, keyword, location
):
    kernel, original, baseline_inventory = witness
    graph = deepcopy(original)
    context = _admitted_template_graph(kernel, deepcopy(original))
    seed = json.loads(canonical_bytes(minimal_release(context)))
    payload = next(
        m["payload"]
        for m in seed["members"]
        if m["member_kind"] == "template-documentation"
    )
    definition, pointer = _schemas(kernel, graph)["template-documentation"]
    schema = definition["schema"]
    # The scalar intentionally equals a field name: it remains literal text.
    details_schema = {
        "type": "object",
        "unevaluatedProperties": False,
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "unevaluatedProperties": False,
                    "properties": {"note": {"type": "string"}},
                    "required": ["note"],
                },
            }
        },
        "required": ["entries"],
    }
    if location != "plain":
        payload["details"] = {"entries": [{"note": "text"}]}
        schema["properties"]["details"] = details_schema
        schema["required"].append("details")
    selected_schema, selected_value = schema, payload
    if location in {"nested", "array"}:
        selected_schema = selected_schema["properties"]["details"]
        selected_value = selected_value["details"]
    if location == "array":
        selected_schema = selected_schema["properties"]["entries"]
        selected_value = selected_value["entries"]
    selected_schema[keyword] = deepcopy(
        selected_value if keyword == "const" else [selected_value]
    )
    context = _admitted_template_graph(kernel, deepcopy(graph))
    control = _get_rebound_release(context, seed)
    assert control[0] == 0
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert inventory.uncovered == baseline_inventory.uncovered
    names = {
        token: "renamed_" + token.name
        for token in inventory.tokens - inventory.reserved
        if token.role == "template-field"
        and token.owner[1] == "template-documentation"
        and token.name in {"text", "details", "entries", "note"}
    }
    assert len(names) == (1 if location == "plain" else 4)
    candidate = _scope_rename(graph, inventory, names)
    renamed_seed = deepcopy(seed)
    next(
        m
        for m in renamed_seed["members"]
        if m["member_kind"] == "template-documentation"
    )["payload"] = _renamed_payload(
        payload,
        schema,
        ("language.artifact_wire_schemas", "template-documentation"),
        names,
    )
    renamed_context = _admitted_template_graph(kernel, candidate)
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    assert renamed_inventory.uncovered == inventory.uncovered
    result = _get_rebound_release(renamed_context, renamed_seed)
    (tmp_path / "public-receipt.json").write_text(
        json.dumps(
            {
                "control": control,
                "renamed": result,
                "keyword": keyword,
                "location": location,
            },
            indent=2,
        )
        + "\n"
    )
    assert result[0] == 0
    assert _get_rebound_release(renamed_context, seed)[0] == 2
    literal_rows = [
        row
        for row in inventory.occurrences
        if row.pointer.startswith(pointer + "/schema/")
        and ("/const/" in row.pointer or "/enum/" in row.pointer)
    ]
    assert literal_rows and all(row.location == "key" for row in literal_rows)
    leaf = "text" if location == "plain" else "note"
    assert any(row.token.name == leaf for row in literal_rows)
    selected = next(row for row in literal_rows if row.token.name == leaf)
    for mutation in ("missing", "wrong-owner"):
        rows = list(inventory.occurrences)
        if mutation == "missing":
            rows.remove(selected)
        else:
            rows[rows.index(selected)] = replace(
                selected, token=replace(selected.token, owner=("other-instance",))
            )
        forged = replace(
            inventory, occurrences=tuple(rows), tokens=frozenset(r.token for r in rows)
        )
        with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
            validate_extension_inventory(kernel, graph, forged)


@pytest.mark.parametrize("shape", ["optional", "oneOf", "anyOf"])
def test_template_coordinate_relation_owns_optional_and_applicator_fields(
    witness, shape, tmp_path
):
    kernel, original, baseline_inventory = witness
    graph = deepcopy(original)
    schemas = _schemas(kernel, graph)
    for kind in ("template-defaults", "golden-scenario"):
        properties = schemas[kind][0]["schema"]["properties"]
        if kind == "template-defaults":
            properties = properties["symbol_values"]["items"]["properties"]
        coordinate = properties["symbol"]
        if shape == "optional":
            if kind == "template-defaults":
                coordinate["required"].remove("model")
        else:
            coordinate[shape] = [
                {
                    "type": "object",
                    "unevaluatedProperties": False,
                    "properties": coordinate.pop("properties"),
                }
            ]
    context = _admitted_template_graph(kernel, deepcopy(graph))
    release = json.loads(canonical_bytes(minimal_release(context)))
    assert _reference_template_admission(
        release, context.kernel, context.language_bundle
    ) == (True, None)
    control = _get_rebound_release(context, release)
    assert control[0] == 0
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert inventory.uncovered == baseline_inventory.uncovered
    bound = {
        t
        for t in inventory.tokens
        if t.role == "template-field"
        and t.owner[1] in {"template-defaults", "golden-scenario"}
        and t.name in {"model", "module", "name"}
    }
    assert len(bound) == 6
    assert bound <= inventory.reserved
    names = {t: "other_model" for t in bound if t.name == "model"}
    with pytest.raises(InventoryRefusal, match="reserved"):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )
    # Force the forbidden change to retain its actual public falsifier.
    values, keys = {}, {}
    for row in inventory.occurrences:
        if row.token in names:
            (keys if row.location == "key" else values)[row.pointer] = names[row.token]
    candidate = _rewrite_positions(graph, values, keys)
    changed = deepcopy(release)
    for member in changed["members"]:
        if member["member_kind"] == "template-defaults":
            coordinates = [row["symbol"] for row in member["payload"]["symbol_values"]]
        elif member["member_kind"] == "golden-scenario":
            coordinates = [member["payload"]["symbol"]]
        else:
            continue
        for coordinate in coordinates:
            coordinate["other_model"] = coordinate.pop("model")
    renamed_context = _admitted_template_graph(kernel, candidate)
    result = _get_rebound_release(renamed_context, changed)
    (tmp_path / "public-receipt.json").write_text(
        json.dumps(
            {
                "control": control,
                "forced_coordinate_rename": result,
            },
            indent=2,
        )
        + "\n"
    )
    assert result[0] == 2


def test_template_parent_literal_retains_the_selected_nominal_value_owner(witness):
    kernel, original, baseline_inventory = witness
    graph = deepcopy(original)
    context = _admitted_template_graph(kernel, deepcopy(original))
    release = json.loads(canonical_bytes(minimal_release(context)))
    metrics = next(
        row["payload"]["metrics"]
        for row in release["members"]
        if row["member_kind"] == "experiment-template"
    )
    definition, pointer = _schemas(kernel, graph)["experiment-template"]
    definition["schema"]["properties"]["metrics"]["const"] = deepcopy(metrics)
    context = _admitted_template_graph(kernel, deepcopy(graph))
    assert _get_rebound_release(context, release)[0] == 0
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert inventory.uncovered == baseline_inventory.uncovered
    occurrences = [
        row
        for row in inventory.occurrences
        if row.pointer == pointer + "/schema/properties/metrics/const/0/kind"
        and row.location == "value"
    ]
    assert len(occurrences) == 1
    assert occurrences[0].token == AuthorityToken(
        "language.quantity.kinds", (), "scalar"
    )
    forged = replace(
        inventory,
        occurrences=tuple(
            row for row in inventory.occurrences if row not in occurrences
        ),
    )
    with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
        validate_extension_inventory(kernel, graph, forged)


@pytest.mark.parametrize("value", [{"undeclared": "text"}, [{"undeclared": "text"}]])
def test_template_literal_without_an_instance_field_contract_retains_a_gap(
    witness, value
):
    kernel, original, baseline_inventory = witness
    graph = deepcopy(original)
    definition, pointer = _schemas(kernel, graph)["template-documentation"]
    definition["schema"]["properties"]["opaque"] = {"const": value}
    definition["schema"]["required"].append("opaque")
    context = _admitted_template_graph(kernel, deepcopy(graph))
    release = json.loads(canonical_bytes(minimal_release(context)))
    next(
        row
        for row in release["members"]
        if row["member_kind"] == "template-documentation"
    )["payload"]["opaque"] = deepcopy(value)
    assert _get_rebound_release(context, release)[0] == 0
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    extra = set(inventory.uncovered) - set(baseline_inventory.uncovered)
    assert len(extra) == 1
    assert next(iter(extra)).pointer == pointer
    assert not set(baseline_inventory.uncovered) - set(inventory.uncovered)
    assert not any(row.token.name == "undeclared" for row in inventory.occurrences)
    forged = replace(inventory, uncovered=baseline_inventory.uncovered)
    with pytest.raises(InventoryRefusal, match="Template occurrence coverage"):
        validate_extension_inventory(kernel, graph, forged)
