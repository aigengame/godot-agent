"""``gda.dispatch.params_or_bad_parameter``'s usage-error rendering (issue #713).

``params_or_bad_parameter`` is the shared argv seam every ``set``/``validate``-style
params model runs through (ADR-0015): a model-construction failure becomes a Click
usage error (exit 2). Its rendering used to be ``str(exc)`` on whatever pydantic
raised, which for a ``ValidationError`` dumps the model's class name, a
``[type=..., input_value=..., input_type=...]`` tag PER ERROR, and a
``pydantic.dev`` URL — and can echo an arbitrary caller value (e.g. a
``script set --content`` payload) back inside ``input_value=`` (found in PR #754's
review). These tests pin the clean replacement: the validator's own sentence(s),
with none of that dump noise and no leaked caller value, for a plain
``ValueError``, a single-error ``ValidationError`` (both a model-level and a
field-level validator), and a multi-error ``ValidationError``.
"""

import typer
import pytest
from pydantic import BaseModel, field_validator, model_validator

from gda.dispatch import params_or_bad_parameter

# The exact dump fragments str(ValidationError) used to leak (PR #754 review).
_FORBIDDEN_FRAGMENTS = ("pydantic.dev", "input_value=", "[type=")


def _assert_clean(message: str) -> None:
    for fragment in _FORBIDDEN_FRAGMENTS:
        assert fragment not in message, f"{fragment!r} leaked into {message!r}"


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


class _RawValueErrorModel:
    """Not a pydantic model: raises a bare ValueError straight out of __init__.

    Exercises params_or_bad_parameter's OTHER except clause directly — pydantic
    itself always wraps a validator's ValueError into ValidationError (verified:
    every mode='before'/'after'/field validator wraps), so this simulates the
    one caller shape pydantic can never produce, standing in for it.
    """

    def __init__(self, **kwargs: object) -> None:
        raise ValueError("a plain refusal sentence.")


def test_plain_value_error_passes_through_as_the_bare_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_RawValueErrorModel)  # type: ignore[arg-type]

    message = str(exc_info.value)
    assert message == "a plain refusal sentence."
    _assert_clean(message)


def test_model_level_validation_error_renders_the_validators_own_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_ModelLevelRuleModel, search="foo", replace=None)

    message = str(exc_info.value)
    assert message == "'search' and 'replace' must be used together."
    _assert_clean(message)


def test_field_level_validation_error_renders_the_validators_own_sentence():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_FieldLevelRuleModel, name="")

    message = str(exc_info.value)
    assert message == "name: 'name' must not be empty."
    _assert_clean(message)


def test_multi_error_validation_error_joins_each_fields_own_message():
    with pytest.raises(typer.BadParameter) as exc_info:
        params_or_bad_parameter(_TwoIndependentFieldsModel, a="x", b="y")

    message = str(exc_info.value)
    assert "a: " in message and "b: " in message
    assert "; " in message  # the stated join separator
    _assert_clean(message)


def test_no_caller_value_leaks_into_the_refusal(monkeypatch):
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
    _assert_clean(message)
