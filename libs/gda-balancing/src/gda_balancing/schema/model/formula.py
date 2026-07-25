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

The clean-forward product retains these models only as the private migration
input grammar. Historical executable evaluator vectors live under ``tests``;
Schema 2.0 ships no 1.x evaluator/runtime seam.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

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


# --- Single-dispatch discrimination (linear validation) --------------------
#
# The four node kinds and the two formula/base representations are disjoint on
# a single dict key each — leaf/op nodes by `op`/`literal`/`attr`/`param`, a
# formula by `form`, a base by `direct`/`formula`. Encoding that as a **callable
# discriminator** (`pydantic.Discriminator` keying on key presence) makes
# validation single-dispatch: pydantic descends the one matching arm rather than
# trying every arm of a smart union. A smart union's retry cost compounds with
# tree depth; single-dispatch keeps a legal depth-≤32 tree (bADR-0003) linear on
# the pydantic side, the mirror of the published schema's linear reshape
# (bADR-0005; :mod:`gda_balancing.schema.artifacts`). The wire format is
# unchanged — the discriminator reads the same keys the smart union did, and the
# generated JSON schema loses only the (non-normative) OpenAPI `discriminator`
# annotation, emitting a plain ``oneOf`` the reshape step then linearizes.
#
# Each discriminator accepts **both** a raw dict (first validation) and a model
# instance (re-validation / round-trip), and returns ``None`` on an
# unrecognizable input so pydantic raises a clean union error rather than
# mis-dispatching.


def _node_tag(value: object) -> str | None:
    """Tag an expression-tree node by its sole distinguishing key."""
    if isinstance(value, dict):
        for key in ("op", "literal", "attr", "param"):
            if key in value:
                return key
        return None
    if isinstance(value, (NaryOp, BinaryOp, UnaryOp)):
        return "op"
    if isinstance(value, LiteralNode):
        return "literal"
    if isinstance(value, AttrRef):
        return "attr"
    if isinstance(value, ParamRef):
        return "param"
    return None


# The expression-tree node: a leaf or an operator application. Single-dispatch
# on the distinguishing key (`op` ⇒ an operator application — itself discriminated
# on `op` — else the leaf named by its lone key).
Node = Annotated[
    Union[
        Annotated[OpNode, Tag("op")],
        Annotated[LiteralNode, Tag("literal")],
        Annotated[AttrRef, Tag("attr")],
        Annotated[ParamRef, Tag("param")],
    ],
    Discriminator(_node_tag),
]


# --- The formula (either representation) -----------------------------------


def _formula_tag(value: object) -> str | None:
    """A formula is a **named form** (carries ``form``) or else an expression
    **tree** node."""
    if isinstance(value, dict):
        return "form" if "form" in value else "node"
    if isinstance(
        value,
        (
            LinearForm,
            PiecewiseLinearForm,
            PolynomialForm,
            ExponentialForm,
            LookupTableForm,
        ),
    ):
        return "form"
    if isinstance(value, (NaryOp, BinaryOp, UnaryOp, LiteralNode, AttrRef, ParamRef)):
        return "node"
    return None


Formula = Annotated[
    Union[
        Annotated[NamedForm, Tag("form")],
        Annotated[Node, Tag("node")],
    ],
    Discriminator(_formula_tag),
]


# --- Base facet wrappers (bADR-0002; consumed by a later stage) ------------


class DirectBase(BaseModel):
    """A base declared as a direct scalar (``{"direct": 5}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direct: float


class FormulaBase(BaseModel):
    """A base declared as a formula (``{"formula": {…}}``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: Formula


def _base_tag(value: object) -> str | None:
    """A base is a direct scalar (``direct``) or a formula (``formula``)."""
    if isinstance(value, dict):
        if "direct" in value:
            return "direct"
        if "formula" in value:
            return "formula"
        return None
    if isinstance(value, DirectBase):
        return "direct"
    if isinstance(value, FormulaBase):
        return "formula"
    return None


Base = Annotated[
    Union[
        Annotated[DirectBase, Tag("direct")],
        Annotated[FormulaBase, Tag("formula")],
    ],
    Discriminator(_base_tag),
]


# Resolve the recursive `"Node"` forward references and the `Formula` alias
# used inside the operator/base wrappers.
NaryOp.model_rebuild()
BinaryOp.model_rebuild()
UnaryOp.model_rebuild()
FormulaBase.model_rebuild()
