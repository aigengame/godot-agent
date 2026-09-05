"""The argv and ``--params-json`` model-refusal rendering (issue #713).

Both input channels construct a command's params model directly from
caller-supplied values (ADR-0015) and must translate a construction failure
into a human message: the argv path's
:func:`~gda.dispatch.params_or_bad_parameter` and the ``--params-json``
path's ``invoke()`` (:mod:`gda.headless`). Both used to render a pydantic
``ValidationError`` with its own ``str()``, which dumps the model's class
name, a ``[type=..., input_value=..., input_type=...]`` tag PER ERROR, and a
``pydantic.dev`` URL — and echoes an arbitrary caller value (e.g. a
``script set --content`` payload) back inside ``input_value=`` (found in PR
#754's review, round 2 for argv, round 3 for ``--params-json``).

Both now go through the ONE shared renderer, :func:`gda.errors.validation_error_message`
(round 3: moved out of ``gda.dispatch`` to a home below both channels, since
``gda.dispatch`` imports ``gda.headless`` and the reverse would cycle). These
tests pin the clean replacement directly against ``params_or_bad_parameter``
(the validator's own sentence(s), for a plain ``ValueError``, a single-error
``ValidationError`` — model-level and field-level — and a multi-error
``ValidationError``), then pin the SAME clean shape end-to-end through an
actual command's ``--params-json`` route, and finally assert the two channels
report byte-identical sentences for the identical refusal.
"""

import json

import typer
import pytest
from pydantic import BaseModel, field_validator, model_validator
from typer.testing import CliRunner

from gda.cli import app
from gda.dispatch import params_or_bad_parameter
from tests.support import assert_no_pydantic_dump, usage_error_text


def _argv_usage_error_message(result) -> str:
    # The Rich-panel normalization is shared (tests/support.py,
    # `usage_error_text`) — the SAME one tests/live/test_screen_commands.py uses —
    # so only the "Invalid value: " extraction is specific to this module.
    plain = usage_error_text(result)
    # The panel is preceded by the "Usage: ..." / "Try '... --help'" preamble
    # and an "Error" heading, so find the marker rather than assume it leads.
    prefix = "Invalid value: "
    marker = plain.rfind(prefix)
    assert marker != -1, plain
    return plain[marker + len(prefix) :]


def _params_json_invalid_params_message(result) -> str:
    assert result.exit_code != 0, result.stdout
    data = json.loads(result.stdout)
    assert data["error"]["code"] == "invalid_params", data
    message = data["error"]["message"]
    prefix = "--params-json is not a valid params object: "
    assert message.startswith(prefix), message
    return message[len(prefix) :]


class _ModelLevelRuleModel(BaseModel):
    """Mirrors ScriptSetParams's shape: a model-level mutual-exclusion rule."""

    search: str | None = None
    replace: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "_ModelLevelRuleModel":
        if (self.search is None) != (self.replace is None):
            raise ValueError("'search' and 'replace' must be used together.")
        return self


class _FieldLevelRuleModel(BaseModel):
    """A field-level validator's raised ValueError, the other value_error shape."""

    name: str

    @field_validator("name")
    @classmethod
    def _check(cls, value: str) -> str:
        if not value:
            raise ValueError("'name' must not be empty.")
        return value


class _TwoIndependentFieldsModel(BaseModel):
    """Two fields that can each fail independently, for the multi-error join."""

    a: int
    b: int


class _RawValueErrorModel(BaseModel):
    """A real BaseModel subclass that raises a bare ValueError from __init__.

    Exercises params_or_bad_parameter's OTHER except clause with a genuine
    ``P`` (bound to BaseModel) — in contract, not a bypass of it (PR #754
    review, round 5). A field or model validator can't reach this branch:
    pydantic always wraps a validator's raised ValueError into
    ValidationError, and ``model_post_init`` gets the same wrapping
    (verified). Overriding ``__init__`` is the one route that escapes it —
    the override runs before pydantic's own validation machinery does, so
    the plain ValueError it raises here propagates untouched. This is why
    ``params_or_bad_parameter`` must catch ``ValidationError`` before
    ``ValueError``: ``ValidationError`` is itself a ``ValueError`` subclass,
    and this class is the sibling shape a ValidationError-raising validator
    can never produce.
    """

    a: int = 1

    def __init__(self, **kwargs: object) -> None:
        raise ValueError("a plain refusal sentence.")


def test_plain_value_error_passes_through_as_the_bare_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_RawValueErrorModel)

    message = str(exc_info.value)
    assert message == "a plain refusal sentence."
    assert_no_pydantic_dump(message)


def test_model_level_validation_error_renders_the_validators_own_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_ModelLevelRuleModel, search="foo", replace=None)

    message = str(exc_info.value)
    assert message == "'search' and 'replace' must be used together."
    assert_no_pydantic_dump(message)


def test_field_level_validation_error_renders_the_validators_own_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_FieldLevelRuleModel, name="")

    message = str(exc_info.value)
    assert message == "name: 'name' must not be empty."
    assert_no_pydantic_dump(message)


def test_multi_error_validation_error_joins_each_fields_own_message():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_TwoIndependentFieldsModel, a="x", b="y")

    message = str(exc_info.value)
    assert "a: " in message and "b: " in message
    assert "; " in message  # the stated join separator
    assert_no_pydantic_dump(message)


def test_no_caller_value_leaks_into_the_refusal():
    # The concrete leak PR #754's review reproduced: a large/sensitive field
    # value must never ride along in the refusal, even though the refused
    # field itself carries it.
    secret = "SECRET_MARKER_abcdefghijklmnopqrstuvwxyz0123456789_END"

    class _CarriesASecretField(BaseModel):
        search: str | None = None
        replace: str | None = None
        content: str | None = None

        @model_validator(mode="after")
        def _check(self) -> "_CarriesASecretField":
            if (self.search is None) != (self.replace is None):
                raise ValueError("'search' and 'replace' must be used together.")
            return self

    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(
            _CarriesASecretField, search="foo", replace=None, content=secret
        )

    message = str(exc_info.value)
    assert secret not in message
    assert message == "'search' and 'replace' must be used together."
    assert_no_pydantic_dump(message)


# --- end-to-end: --params-json through an actual command (round 3) ------------


def test_params_json_validation_error_is_also_rendered_clean():
    # script set's search/replace mutual-exclusion rule (resolve_set_mode),
    # refused via --params-json this time, not argv.
    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "--params-json",
            json.dumps({"path": "/tmp/nonexist.gd", "search": "foo"}),
            "--json",
        ],
    )

    message = _params_json_invalid_params_message(result)
    assert message == "'search' and 'replace' must be used together."
    assert_no_pydantic_dump(message)


def test_params_json_does_not_leak_the_callers_other_field_value():
    # The exact channel this round's review caught: --content rode inside
    # input_value= in the structured envelope's message, secret and all.
    secret = "SECRET_MARKER_abcdefghijklmnopqrstuvwxyz0123456789_END"
    result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "--params-json",
            json.dumps(
                {"path": "/tmp/nonexist.gd", "search": "foo", "content": secret}
            ),
            "--json",
        ],
    )

    message = _params_json_invalid_params_message(result)
    assert secret not in message
    assert message == "'search' and 'replace' must be used together."
    assert_no_pydantic_dump(message)


def test_argv_and_params_json_report_the_identical_sentence():
    # #713's own acceptance criterion 2 pairs the two channels ("the same
    # error class"); this pins them to the same MESSAGE too, not just the
    # same class, for the identical refusal.
    argv_result = CliRunner().invoke(
        app, ["script", "set", "/tmp/nonexist.gd", "--search", "foo", "--json"]
    )
    params_json_result = CliRunner().invoke(
        app,
        [
            "script",
            "set",
            "--params-json",
            json.dumps({"path": "/tmp/nonexist.gd", "search": "foo"}),
            "--json",
        ],
    )

    argv_message = _argv_usage_error_message(argv_result)
    params_json_message = _params_json_invalid_params_message(params_json_result)
    assert (
        argv_message
        == params_json_message
        == ("'search' and 'replace' must be used together.")
    )
