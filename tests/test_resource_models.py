"""S2: the resource uid command's typed models (issue #113, ADR-0004).

`gda resource uid`'s result is carried by `ResourceUidResult` and its params by
`ResourceUidParams`, so the same models both serialize the `--json` output and
derive the `--schema` document. These unit tests pin the model shapes — both
resolution directions converge on one `{queried, uid, path}` result — without a
real engine.
"""

import json

import jsonschema

from gda.models import (
    ResourceDeleteParams,
    ResourceDeleteResult,
    ResourceSetParams,
    ResourceSetResult,
    ResourceUidParams,
    ResourceUidResult,
)


def test_params_carry_the_single_target_argument():
    params = ResourceUidParams(target="uid://caax1gby1api1")

    assert params.target == "uid://caax1gby1api1"
    # The params serialize to exactly the operation payload the runner dispatches.
    assert params.model_dump() == {"target": "uid://caax1gby1api1"}


def test_result_validates_a_uid_to_path_payload():
    # The uid->path direction: the sentinel payload the operation emits.
    payload = {"queried": "uid", "uid": "uid://caax1gby1api1", "path": "res://data.tres"}

    result = ResourceUidResult.model_validate(payload)

    assert result.queried == "uid"
    assert result.uid == "uid://caax1gby1api1"
    assert result.path == "res://data.tres"


def test_result_validates_a_path_to_uid_payload():
    # The path->uid direction shares the same shape; only `queried` differs.
    payload = {"queried": "path", "uid": "uid://caax1gby1api1", "path": "res://data.tres"}

    result = ResourceUidResult.model_validate(payload)

    assert result.queried == "path"
    assert result.uid == "uid://caax1gby1api1"
    assert result.path == "res://data.tres"


def test_result_round_trips_to_json_object():
    payload = {"queried": "uid", "uid": "uid://abc", "path": "res://x.tres"}

    result = ResourceUidResult.model_validate(payload)

    assert json.loads(result.model_dump_json()) == payload


def test_result_schema_is_valid_json_schema_with_the_three_fields():
    schema = ResourceUidResult.model_json_schema()

    jsonschema.Draft202012Validator.check_schema(schema)
    assert {"queried", "uid", "path"} <= set(schema["properties"])


# --- resource set / delete models (issue #120) ---------------------------


def test_set_params_carry_path_property_and_string_value():
    params = ResourceSetParams(
        path="res://palette.tres", property="interpolation_mode", value="1"
    )

    # The CLI value rides through as a string; the operation owns the coercion.
    assert params.model_dump() == {
        "path": "res://palette.tres",
        "property": "interpolation_mode",
        "value": "1",
    }


def test_set_result_carries_the_coerced_value_projection():
    # The result reports the coerced value in the JSON projection get reports, so
    # a set round-trips through a get (the declared int type, not the string).
    payload = {
        "path": "res://palette.tres",
        "property": "interpolation_mode",
        "type": "int",
        "value": 1,
    }

    result = ResourceSetResult.model_validate(payload)

    assert result.property == "interpolation_mode"
    assert result.type == "int"
    assert result.value == 1
    assert json.loads(result.model_dump_json()) == payload


def test_delete_params_carry_the_single_path_argument():
    params = ResourceDeleteParams(path="res://palette.tres")

    assert params.model_dump() == {"path": "res://palette.tres"}


def test_delete_result_names_the_removed_path_and_type():
    payload = {"path": "res://palette.tres", "type": "Gradient"}

    result = ResourceDeleteResult.model_validate(payload)

    assert result.path == "res://palette.tres"
    assert result.type == "Gradient"
    assert json.loads(result.model_dump_json()) == payload
