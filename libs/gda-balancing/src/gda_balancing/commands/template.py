"""The `template` command group — Genre-template delivery (bADR-0007/0012).

``template list`` enumerates the shipped Genre templates; ``template get``
emits one as a canonical Design document. **Get is instantiate** (bADR-0012):
a Genre template already *is* a valid Design document, so instantiation is
obtaining it (``--out`` writes it as the consumer's starting document); naming
the game and extending or overriding the baseline are the consumer's edits
(the declared mechanism lands with #508).

The handler parses the packaged JSON directly — it never runs the funnel, so
``template get`` never refuses (mirroring ``schema get``): a shipped
template's validity is guaranteed by the test suite, not re-checked per
invocation. An unknown template id fails input binding → the usage
`invalid_argument` boundary / exit 3, automatically (bADR-0008).
"""

from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.descriptors import (
    ArtifactReceipt,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.schema.model.document import DesignDocument

# The authored template registry: id → one-line summary. The ids double as
# resource names (`<id>.json` in this package's `templates` directory) and are
# mirrored by `TemplateGetInput.template`'s Literal — a consistency test holds
# the three views together (bADR-0012).
_TEMPLATES: dict[str, str] = {
    "rpg": (
        "RPG family (CRPG/JRPG/ARPG): allocatable primary stats, "
        "formula-derived resource/offense/defense/mobility stats, "
        "bounded tertiary rates."
    ),
}

_RESOURCE_PACKAGE = "gda_balancing.templates"


class TemplateListInput(BaseModel):
    """`template list` takes no arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TemplateSummary(BaseModel):
    """One shipped Genre template: its id (the `template get` argument) and a
    one-line summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    summary: str


class TemplateListResult(BaseModel):
    """The shipped Genre templates, in registry order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    templates: tuple[TemplateSummary, ...]


def run_template_list(_: TemplateListInput) -> TemplateListResult:
    return TemplateListResult(
        templates=tuple(
            TemplateSummary(id=template_id, summary=summary)
            for template_id, summary in _TEMPLATES.items()
        )
    )


TEMPLATE_LIST = CommandDescriptor(
    group="template",
    command="list",
    description="List the shipped Genre templates (id + one-line summary).",
    input_model=TemplateListInput,
    output_model=TemplateListResult,
    handler=run_template_list,
    fixtures=ConformanceFixtures(),
)


class TemplateGetInput(BaseModel):
    """`template get` takes exactly the template id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: Literal["rpg"]


class TemplateGetOutput(RootModel[DesignDocument | ArtifactReceipt]):
    """The Genre template as a bare canonical Design document (bADR-0008's
    no-wrapper law) — or, when ``--out`` was given, the
    :class:`ArtifactReceipt` the dispatch tail substitutes (bADR-0009)."""


def run_template_get(inp: TemplateGetInput) -> TemplateGetOutput:
    text = (
        resources.files(_RESOURCE_PACKAGE)
        .joinpath(f"{inp.template}.json")
        .read_text(encoding="utf-8")
    )
    return TemplateGetOutput(root=DesignDocument.model_validate_json(text))


TEMPLATE_GET = CommandDescriptor(
    group="template",
    command="get",
    description="Emit a Genre template as a canonical Design document (bADR-0012).",
    input_model=TemplateGetInput,
    output_model=TemplateGetOutput,
    handler=run_template_get,
    positional_field="template",
    artifact_sink=True,
    fixtures=ConformanceFixtures(valid_args=("rpg",)),
)
