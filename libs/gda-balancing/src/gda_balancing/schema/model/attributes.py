"""The attributes-core document model (bADR-0002).

An attribute declaration is a **composition of orthogonal facets** — ``domain``,
``base``, ``accepts``, ``bounds``, ``category`` — not a fixed tier taxonomy;
tiers are *template compositions* (facet patterns), declared data rather than
schema law. This module owns the **local shape** of that model: the facet field
types, the enum vocabularies, the optional/default structure. Every constraint
that needs cross-element context — the bounds obligation by domain, tier-pattern
satisfaction, the allocation-onto-formula cross-facet rule, formula acyclicity —
is a semantic-phase rule (bADR-0004), enforced by the funnel after this shape,
and deliberately **not** encoded here.

The ``base`` facet reuses :data:`gda_balancing.schema.model.formula.Base`, the
single scalar authority for an attribute (bADR-0002): exactly one of a ``direct``
value or a ``formula`` — there is no separate ``default`` field.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.schema.model.formula import Base
from gda_balancing.schema.model.ids import IdStr

# The value space a facet declares. `percentage` is a fraction (0.3 = 30%);
# `probability` implies [0,1]. The 0-100 scale never appears (bADR-0002).
Domain = Literal["number", "percentage", "probability"]

# The two base kinds — a configured value or a named form / expression tree.
BaseKind = Literal["direct", "formula"]

# The contribution channels an attribute may accept (bADR-0002/0006).
Channel = Literal["allocation", "effects"]


class Bounds(BaseModel):
    """Optional ``floor``/``cap`` clamps (bADR-0002).

    Both sides are optional here; the *obligation* to declare bounds when the
    domain is ``percentage``/``probability`` is a semantic rule (bADR-0004),
    not a local shape constraint.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    floor: float | None = None
    cap: float | None = None


class Tier(BaseModel):
    """A tier is a **named facet pattern** a genre template groups attributes by
    (bADR-0002) — declared data, not schema law.

    A pattern may constrain any subset of ``domain``, ``base`` (by kind), and
    ``accepts`` (by exact set equality); an omitted facet — ``None`` — is
    *unconstrained*, which is distinct from a present-and-empty ``accepts``
    (the pattern "accepts exactly nothing"). Pattern *satisfaction* is a
    semantic rule (bADR-0004).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: Domain | None = None
    base: BaseKind | None = None
    accepts: tuple[Channel, ...] | None = None


class Attribute(BaseModel):
    """One attribute declaration — a composition of orthogonal facets
    (bADR-0002). Its map key is the single id authority; the declaration carries
    no ``id`` field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: Domain
    base: Base
    # `accepts` has a defined default `()` (bADR-0002/0005 round-trip contract):
    # an attribute that declares nothing accepts nothing. Canonical emission
    # materializes the empty list; an absent `accepts` is semantically equal.
    accepts: tuple[Channel, ...] = ()
    bounds: Bounds | None = None
    category: str | None = None
    tier: str | None = None


class Attributes(BaseModel):
    """The ``attributes`` section (bADR-0002): the tier vocabulary and the
    attribute declarations, each an id-keyed map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tiers: dict[IdStr, Tier] = Field(default_factory=dict)
    items: dict[IdStr, Attribute] = Field(default_factory=dict)
