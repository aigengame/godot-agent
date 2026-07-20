"""The effects-core document model (bADR-0006).

An **effect** is a declared, time-scoped carrier of numeric influence; a
**modifier** is one numeric operation inside an effect. Both are first-class
schema citizens beside attributes — simulation consumes their numbers directly
from the Design document (bADR-0006). This module owns the **local shape** of
that model: the field types, the enum vocabularies, the optional/default
structure. Every constraint that needs cross-element context — target integrity,
stacking-type reference integrity, application/duration legality, the
`period`/`application` consistency rules, the temporal-validity bounds, and the
magnitude formula rules (bADR-0003) — is a semantic-phase rule (bADR-0004),
enforced by the funnel after this shape and deliberately **not** encoded here.

The **magnitude** of a modifier is formula-capable (bADR-0003): a bare scalar
number, a named form, or an expression tree — the same two representations an
attribute base uses, but **unwrapped** (no ``direct``/``formula`` envelope, since
a magnitude is a value, not a facet). It reuses the one formula vocabulary
(:mod:`gda_balancing.schema.model.formula`).
"""

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.schema.model.formula import Formula
from gda_balancing.schema.model.ids import IdStr

# How same-type instances aggregate in stacking selection (bADR-0006): `stack`
# keeps every instance; `keep_best` keeps the strongest bonus and penalty per
# group. What a re-application does to duration is the orthogonal `lifetime`.
Aggregation = Literal["stack", "keep_best"]

# What a re-application does to the effect's own remaining duration (bADR-0006):
# `independent` instances vs a `refresh` of the existing one. Orthogonal to
# `aggregation`.
Lifetime = Literal["independent", "refresh"]

# A modifier's numeric operation (bADR-0006): add/multiply/override — the shapes
# attested in the #503 engine-practice research.
Operation = Literal["add", "multiply", "override"]

# How a modifier applies (bADR-0006): `continuous` contributes to the target's
# computed final while active; `one_shot` is a delta applied once at
# application; `periodic` is a per-tick delta. `one_shot` names the apply-once
# delta so it can never be confused with the `instant` *duration*.
Application = Literal["continuous", "one_shot", "periodic"]

# A modifier's magnitude (bADR-0006/0003): a bare scalar number, a named form, or
# an expression tree — the formula representations, unwrapped (a magnitude is a
# value, not a `base` facet, so it carries no `direct`/`formula` envelope). A
# float is a scalar; the two `Formula` arms are objects, so the union
# disambiguates without a discriminator.
Magnitude = Union[float, Formula]


class StackingType(BaseModel):
    """One entry of the document-level ``stacking_types`` catalog (bADR-0006):
    stacking-type id → its aggregation policy. Same-type resolution is defined
    **once per type** here — two effects can never assign conflicting rules to
    one type. Its map key is the single id authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aggregation: Aggregation


class Stacking(BaseModel):
    """A persistent effect's stacking declaration (bADR-0006): the
    ``type`` it references from the catalog, plus the ``lifetime`` governing
    re-application. Required for ``timed``/``infinite`` effects, forbidden on
    ``instant`` — both element-level semantic rules, not local shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: IdStr
    lifetime: Lifetime


class TimedDuration(BaseModel):
    """A ``timed`` duration carrying its length in seconds (bADR-0006). The
    valueless durations — ``instant`` and ``infinite`` — are bare strings; only
    ``timed`` carries a value, so it is the one object arm (mirroring the
    ``base`` facet's tagged-object shape). The positivity/finiteness of
    ``timed`` is a semantic rule (bADR-0006), not encoded here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timed: float


# The three effect durations (bADR-0006): `instant`/`infinite` are valueless
# (bare strings), `timed` carries seconds.
Duration = Union[Literal["instant", "infinite"], TimedDuration]


class Modifier(BaseModel):
    """One numeric operation inside an effect (bADR-0006). It names its
    ``target`` attribute, its ``operation`` and ``application``, and its
    ``magnitude``. Target integrity, application/duration legality, the
    ``override``-on-delta refusal, and the magnitude formula rules are all
    semantic-phase rules (bADR-0004/0006)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: IdStr
    operation: Operation
    application: Application
    magnitude: Magnitude


class Effect(BaseModel):
    """One declared, time-scoped effect (bADR-0006). Its map key is the single id
    authority; the declaration carries no ``id`` field. ``modifiers`` and
    ``duration`` are required; ``period`` and ``stacking`` are optional shapes
    whose *presence* obligations are semantic rules (bADR-0006): ``period`` is
    required for a ``periodic`` modifier and forbidden when every modifier is
    ``one_shot``; ``stacking`` is required for a persistent effect and forbidden
    on an ``instant`` one. An effect carries numeric influence, so it declares at
    least one modifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modifiers: tuple[Modifier, ...] = Field(min_length=1)
    duration: Duration
    period: float | None = None
    stacking: Stacking | None = None


class Effects(BaseModel):
    """The ``effects`` section (bADR-0006): the document-level stacking-type
    catalog and the effect declarations, each an id-keyed map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stacking_types: dict[IdStr, StackingType] = Field(default_factory=dict)
    items: dict[IdStr, Effect] = Field(default_factory=dict)
