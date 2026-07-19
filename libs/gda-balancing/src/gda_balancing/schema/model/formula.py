"""Formula-as-data models (bADR-0003).

The two authoritative formula representations, as pydantic models: the
**named form** (a declared, parameterized formula shape) and the **expression
tree** (a JSON AST over a closed operator set). References are typed at the
node (``attr`` / ``param``), so an id living in both namespaces (legal,
bADR-0002) is never ambiguous.

Model constraints follow the placement rule of :mod:`gda_balancing.schema.model`:
these classes own **local shape only** — node kinds, operator arity, the
literal-only rule for collection elements. Every *value* constraint bADR-0003
names — strictly-increasing ``x``, positivity, entry counts — is a
semantic-phase rule (bADR-0004), enforced after parameter resolution and
deliberately **not** encoded here.

The public evaluators and re-exports live in :mod:`gda_balancing.formula`, the
one sanctioned formula seam (bADR-0003); import the vocabulary from there.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.schema.model.ids import IdStr

# --- Reference / leaf nodes ------------------------------------------------


class AttrRef(BaseModel):
    """A typed reference to an attribute value (``{"attr": "vit"}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attr: IdStr


class ParamRef(BaseModel):
    """A typed reference to a declared parameter (``{"param": "hp_per_vit"}``).

    A parameter reference is the sole *tuning knob* form a scalar can take; a
    literal is a deliberate non-knob (bADR-0003).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    param: IdStr


class LiteralNode(BaseModel):
    """A literal number leaf (``{"literal": 20}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    literal: float


# --- Aliases ---------------------------------------------------------------

# A named form's independent variable: a single typed reference (bADR-0003).
InputRef = Union[AttrRef, ParamRef]

# A named form's scalar field: a literal number or a parameter knob. The
# `parameters` section is the sole declaration home — a form only references
# (bADR-0003).
ScalarField = Union[float, ParamRef]

# One `[x, y]` sample. Collection elements are literals only in v1, so a
# `{"param": ...}` inside a pair fails model validation (V3, structural).
FormPair = tuple[float, float]


# --- Named forms (discriminated on `form`) ---------------------------------


class LinearForm(BaseModel):
    """``base + per_point·x`` (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["linear"]
    input: InputRef
    base: ScalarField
    per_point: ScalarField


class PiecewiseLinearForm(BaseModel):
    """Linear interpolation between neighboring ``points``; inputs outside the
    range clamp to the first/last ``y`` (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["piecewise_linear"]
    input: InputRef
    points: tuple[FormPair, ...]


class PolynomialForm(BaseModel):
    """``c0 + c1·x + … + cn·xⁿ``, coefficients in ascending degree
    (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["polynomial"]
    input: InputRef
    coefficients: tuple[float, ...]


class ExponentialForm(BaseModel):
    """``coefficient · growth_rate^x`` under the ``power`` semantics
    (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["exponential"]
    input: InputRef
    coefficient: ScalarField
    growth_rate: ScalarField


class LookupTableForm(BaseModel):
    """A step function: the ``y`` of the greatest table ``x ≤ input``; below
    the first ``x`` takes the first ``y``. Never interpolates (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["lookup_table"]
    input: InputRef
    table: tuple[FormPair, ...]


NamedForm = Annotated[
    Union[
        LinearForm,
        PiecewiseLinearForm,
        PolynomialForm,
        ExponentialForm,
        LookupTableForm,
    ],
    Field(discriminator="form"),
]


# --- Expression tree (arity structural, discriminated on `op`) -------------


class NaryOp(BaseModel):
    """An n-ary operator (≥ 2 args), folded strictly left-to-right
    (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["add", "multiply", "min", "max"]
    args: tuple["Node", ...] = Field(min_length=2)


class BinaryOp(BaseModel):
    """A binary operator applied as ``args[0] op args[1]`` (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["subtract", "divide", "power"]
    args: tuple["Node", ...] = Field(min_length=2, max_length=2)


class UnaryOp(BaseModel):
    """A unary operator (exactly one arg): ``floor``/``ceil``/``round``
    (bADR-0003)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["floor", "ceil", "round"]
    args: tuple["Node", ...] = Field(min_length=1, max_length=1)


OpNode = Annotated[
    Union[NaryOp, BinaryOp, UnaryOp],
    Field(discriminator="op"),
]

# The expression-tree node: a leaf or an operator application. Not a
# `Field(discriminator=…)` union — the leaf kinds carry distinct required
# fields (`literal`/`attr`/`param`) rather than a shared tag, so a smart union
# under `extra="forbid"` disambiguates them.
Node = Union[LiteralNode, AttrRef, ParamRef, OpNode]


# --- The formula (either representation) -----------------------------------

Formula = Union[NamedForm, Node]


# --- Base facet wrappers (bADR-0002; consumed by a later stage) ------------


class DirectBase(BaseModel):
    """A base declared as a direct scalar (``{"direct": 5}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direct: float


class FormulaBase(BaseModel):
    """A base declared as a formula (``{"formula": {…}}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: Formula


Base = Union[DirectBase, FormulaBase]


# Resolve the recursive `"Node"` forward references and the `Formula` alias
# used inside the operator/base wrappers.
NaryOp.model_rebuild()
BinaryOp.model_rebuild()
UnaryOp.model_rebuild()
FormulaBase.model_rebuild()
