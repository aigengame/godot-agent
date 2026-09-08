from pathlib import Path

import pytest

from gda_assets.domain.prompt import (
    PromptOutputRequest,
    resolve_prompt,
    validate_options,
    validate_output_request,
)


def test_plain_dollar_text_is_unchanged_and_style_is_ordered():
    assert resolve_prompt(
        text="cost is $5", template_text=None, style_text="ink style", variables={}
    ) == ("plain", "ink style\n\ncost is $5")


def test_template_requires_exact_variables_and_supports_braced_names():
    assert resolve_prompt(
        text=None,
        template_text="A $subject in ${place}; $$ literal",
        style_text=None,
        variables={"subject": "fox", "place": "snow"},
    ) == ("template", "A fox in snow; $ literal")
    with pytest.raises(ValueError, match="exactly match"):
        resolve_prompt(
            text=None,
            template_text="$subject",
            style_text=None,
            variables={"subject": "fox", "unused": "x"},
        )


def test_options_reject_unlisted_or_nonfinite_values():
    with pytest.raises(ValueError, match="unsupported"):
        validate_options({"api_key": "secret"})
    with pytest.raises(ValueError, match="finite"):
        validate_options({"seed": float("nan")})
    with pytest.raises(ValueError, match="must be boolean"):
        validate_output_request(
            PromptOutputRequest(
                Path("record"),
                Path("result.png"),
                "result.png",
                caller_declarations={"generation_completed": "yes"},
            )
        )
