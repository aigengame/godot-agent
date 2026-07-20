"""The root Design-document model (bADR-0001) — one document per game.

A game's complete numeric design is a single JSON document with a **closed
top-level envelope**: a fixed set of named keys, unknown keys refused
structurally (bADR-0004). This module owns that envelope's local shape; it is
the single source of truth the published structural schema is generated from
(bADR-0005).

The **designed v1 sections** carried here are ``parameters`` (bADR-0003),
``attributes`` (bADR-0002), and ``effects`` (bADR-0006). The **reserved
sections** are declared permissively so a document *using* one clears the
structural phase and is refused by the semantic phase with its dedicated
``reserved_section_present`` code and a precise pointer (bADR-0001, "refused
until designed"; V12) — see :class:`DesignDocument`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.schema.model.attributes import Attributes
from gda_balancing.schema.model.effects import Effects
from gda_balancing.schema.model.ids import IdStr


class GenreLineage(BaseModel):
    """Descriptive genre lineage (bADR-0001, landed by #505/bADR-0012): the
    Genre-template family a document descends from (``family``, e.g. a genre
    family id) and optionally the subtype within it (``variant``). Purely
    informational — no toolkit code branches on it; genre templates are data,
    never code paths (bADR-0002)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family: IdStr
    variant: IdStr | None = None


class Meta(BaseModel):
    """Design identity (bADR-0001): the *document* names its game, the
    *toolkit* stays game-agnostic. ``name`` is the only required subfield;
    ``description`` and the ``genre`` lineage are optional.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str | None = None
    genre: GenreLineage | None = None


class DesignDocument(BaseModel):
    """The closed root envelope (bADR-0001).

    ``schema_version`` is deliberately loose here — a plain string — because the
    funnel's **preflight** phase owns the semver acceptance gate (bADR-0004);
    encoding a semver pattern here would fork that authority.

    ``$schema`` is the optional bADR-0001 mirror: validated from parsed JSON via
    its alias, it points at the versioned structural schema ``$id`` so ecosystem
    editors get ambient validation; ``schema_version`` remains the single
    authority ($schema-agreement is a semantic rule).

    The six **reserved sections** — ``combat``/``encounters``/``builds``/
    ``growth``/``economy``/``targets`` — are each declared ``Any`` and
    ``exclude=True``. Declaring them keeps the generated structural schema and
    pydantic construction **permissive** for these keys, so the *semantic* phase
    can refuse a document using one with its dedicated ``reserved_section_present``
    code and a precise pointer (bADR-0001, V12) — while a truly-unknown top-level
    key still refuses *structurally* via the closed envelope. ``exclude=True``
    keeps them out of every serialization, so canonical emission never
    materializes a reserved section.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    meta: Meta
    schema_ref: str | None = Field(default=None, alias="$schema")
    parameters: dict[IdStr, float] = Field(default_factory=dict)
    attributes: Attributes = Field(default_factory=Attributes)
    effects: Effects = Field(default_factory=Effects)

    # Reserved sections (bADR-0001): permissive shape, refused in the semantic
    # phase; excluded from serialization so canonical emission never carries one.
    combat: Any = Field(default=None, exclude=True)
    encounters: Any = Field(default=None, exclude=True)
    builds: Any = Field(default=None, exclude=True)
    growth: Any = Field(default=None, exclude=True)
    economy: Any = Field(default=None, exclude=True)
    targets: Any = Field(default=None, exclude=True)
