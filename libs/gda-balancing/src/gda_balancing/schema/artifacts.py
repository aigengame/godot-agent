"""The generated structural schema artifact (bADR-0005).

The published **structural schema** is a JSON Schema 2020-12 document whose
instances are Design documents; it is *generated* from the pydantic document
model (:class:`gda_balancing.schema.model.document.DesignDocument`), never
hand-maintained — one authority, a projection around it (bADR-0005 anti-drift).
It is emitted verbatim by ``schema get structural`` and is the schema the
funnel's structural phase runs against.

**Portability rationale — why the newline guards exist.** A published pattern
must remain ECMA-262-valid (JSON Schema's regex dialect), so ``\\Z`` may *never*
appear in the artifact — only ``^``/``$`` anchoring is portable. Under ECMA,
``$`` already anchors at true end of input, so the guards this module adds are
no-ops for ecosystem validators. Under Python's ``re`` — the engine our *own*
structural phase (``jsonschema``) runs on — ``$`` (and an unanchored ``pattern``
search) also matches *before a trailing newline*, so without a guard a key or id
like ``"ab\\n"`` would **pass** the structural phase and then **fail** pydantic's
Rust-regex construction, turning a refusable document into an exit-4 crash. Two
guards close that hole so structural-pass ⇒ model-construction-success:

* every ``patternProperties`` node gains ``additionalProperties: false`` (keys
  matching no pattern are refused) **and** ``propertyNames: {"not": {"pattern":
  "\\n"}}`` (no key may contain a newline — the case ``$``-leniency would admit);
* every id-valued ``pattern`` node (the ``^[a-z]…$`` scalar ids) gains a sibling
  ``not: {"pattern": "\\n"}``.

Precedent: :data:`gda_balancing.interfaces.cli.envelope._JSON_POINTER_SCHEMA`'s ``anyOf`` guard
— the same Python-``re`` vs Rust-regex trailing-newline divergence, fixed in the
same structural style rather than by sharing a raw pattern string.

**Optional is absent-or-typed, never null — why the null arms are dropped.** An
optional document member is either *absent* or carries a *typed value*; an
explicit ``null`` is neither (bADR-0005). pydantic projects an ``X | None``
field as an ``anyOf``/``oneOf`` carrying a ``{"type": "null"}`` arm plus a
``"default": null`` annotation — which would *admit* an explicit ``null`` and
coerce it to the field default. :func:`_strip_nullability` removes that: every
null union arm is dropped (a now one-armed union collapses to its sole arm) and
every ``"default": null`` annotation is stripped, while genuine domain defaults
(``"default": []``) are kept. The published schema thereby becomes **stricter**
than pydantic construction — it refuses an explicit ``null`` *before* the model
would coerce it — so the funnel's structural-pass ⇒ model-construction-success
invariant (bADR-0004/0005) is preserved by construction. The reserved-section
``Any`` fields are untouched by design: their permissive ``{}`` schema stays
(stripping their bare ``"default": null`` leaves exactly ``{}``), so an explicit
``"builds": null`` still passes the structural phase and is refused by the
semantic ``reserved_section_present`` rule, which keys on the raw key's presence,
not its value.

**Linear-time expression-tree validation — why the OpNode reshape exists.**
pydantic emits the expression-tree node as a *smart-union projection*: an
operator application is a three-variant ``oneOf`` (n-ary / binary / unary), each
variant recursing into ``args.items`` — the full node union again. ``jsonschema``
evaluates every ``oneOf`` branch independently (a failed ``op`` enum does **not**
prune that branch's ``args`` recursion), so a depth-``d`` tree costs ``~3**d``:
0.13 s at depth 8, 1.2 s at 10, 10.6 s at 12 (PR #527 review) — exponential, and
a legal depth-≤32 formula (bADR-0003) is unvalidatable. The reshape
(:func:`_linearize_op_nodes`) collapses those three variants into **one**
``$defs/OpNode`` object schema whose ``args.items`` references the node union
**exactly once**, with arity carried by an ``allOf`` of three ``if``/``then``
clauses that constrain only ``args`` **counts** (``minItems``/``maxItems``) and
recurse into nothing. The single ``args.items`` recursion per level makes
validation linear; the ``if``/``then``/``allOf`` keywords are core 2020-12, so
the artifact stays ECMA-262-portable. This mirrors the model-side
single-dispatch discrimination (:mod:`gda_balancing.schema.model.formula`) — one
authority, a linear projection around it (bADR-0005 anti-drift), the two engines
kept in lockstep by :mod:`gda_balancing.tests.test_engine_parity`.
"""

import copy
from typing import Any

from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.model.ids import ID_PATTERN
from gda_balancing.schema.version import SCHEMA_VERSION, STRUCTURAL_SCHEMA_ID

# The JSON Schema dialect the artifact declares itself in (2020-12, bADR-0005).
_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# The trailing-newline guard, shared by both fix sites (see module docstring).
_NO_NEWLINE: dict[str, Any] = {"not": {"pattern": "\\n"}}

# The closed operator set (bADR-0003), grouped by arity. The base OpNode schema
# admits any of them with `args` `minItems: 1`; the if/then clauses tighten the
# count per arity — n-ary `≥ 2`, binary/unary exactly `2`/`1`. This must mirror
# the operator literals of the model's `NaryOp`/`BinaryOp`/`UnaryOp` (a divergence
# would refuse a legal operator or admit an illegal arity); the engine-parity
# tests hold the two in lockstep.
_NARY_OPS = ("add", "multiply", "min", "max")
_BINARY_OPS = ("subtract", "divide", "power")
_UNARY_OPS = ("floor", "ceil", "round")
_ALL_OPS = (*_NARY_OPS, *_BINARY_OPS, *_UNARY_OPS)

# The consolidated $defs entries the reshape introduces, and the ones it retires.
_OPNODE_REF = "#/$defs/OpNode"
_NODE_REF = "#/$defs/Node"
_LEAF_REFS = ("#/$defs/LiteralNode", "#/$defs/AttrRef", "#/$defs/ParamRef")
_RETIRED_OP_DEFS = ("NaryOp", "BinaryOp", "UnaryOp")


def generate_structural_schema() -> dict[str, Any]:
    """Build the published structural schema from :class:`DesignDocument`.

    Deterministic and side-effect-free: the pydantic validation-mode schema is
    deep-copied, then post-processed in place — top-level dialect/``$id`` set,
    the exponential-prone OpNode smart-union projection reshaped into the linear
    single-``$defs/OpNode`` form (see the module docstring), the ``X | None``
    null arms dropped so an optional member is absent-or-typed (never null),
    every ``title`` stripped (snapshot stability across pydantic versions), and
    the two newline guards applied wherever they apply.
    """
    schema = copy.deepcopy(DesignDocument.model_json_schema())
    schema["$schema"] = _DIALECT
    schema["$id"] = STRUCTURAL_SCHEMA_ID
    _linearize_op_nodes(schema)
    _strip_nullability(schema)
    _harden(schema)
    return schema


def generate_catalog() -> dict[str, Any]:
    """Build the published **semantic rule catalog** (bADR-0005).

    A machine-readable index of the semantic phase's rules — each entry is
    ``{id, scope, description, since_version}`` — **projected** from the single
    rule registry (:data:`gda_balancing.schema.funnel.semantic.SEMANTIC_RULES`),
    never hand-written: the rule id *is* the refusal code (bADR-0004), so the
    catalog cannot drift from the validator. Entries are sorted by id for a
    stable artifact.

    ``scope`` is emitted as a JSON **array** of RFC 6901 pointer templates.
    bADR-0005 calls a rule's scope "a JSON Pointer template"; a rule may apply
    at more than one site (the two reference-integrity rules walk both attribute
    base formulas and effect magnitudes), so the field carries **one template
    per site** — a single-site rule is a one-element array. Machine-readable by
    construction: consumers read the array, never split a comma-joined string.

    ``since_version`` is line-granular (``"1.0"``), matching bADR-0001's
    acceptance granularity — a validator serving ``X.Y`` ships every rule of
    ``X.0 … X.Y`` — while the top-level ``schema_version`` is the full version
    the artifact set was published at.
    """
    # Lazy import keeps the structural-schema generation path (the funnel's hot
    # path) decoupled from the semantic layer.
    from gda_balancing.schema.funnel.semantic import SEMANTIC_RULES

    return {
        "schema_version": SCHEMA_VERSION,
        "rules": [
            {
                "id": rule.code,
                "scope": list(rule.scope),
                "description": rule.description,
                "since_version": rule.since_version,
            }
            for rule in sorted(SEMANTIC_RULES, key=lambda r: r.code)
        ],
    }


def _linearize_op_nodes(schema: dict[str, Any]) -> None:
    """Reshape the OpNode smart-union projection into the linear form, in place.

    Two deterministic steps (see the module docstring for the *why*):

    1. Walk the whole schema **bottom-up** and collapse each inlined union:
       every three-variant operator ``oneOf`` (fingerprinted by its OpenAPI
       ``discriminator.propertyName == "op"`` — ``jsonschema`` ignores that
       keyword, so it is free identity, not semantics) becomes a ``$ref`` to the
       single :data:`_OPNODE_REF`, and the four-arm node union that wraps it
       becomes a ``$ref`` to :data:`_NODE_REF`. Bottom-up order means the op
       ``$ref`` is already in place when the enclosing node union is tested.
    2. Retire the now-unreferenced ``NaryOp``/``BinaryOp``/``UnaryOp`` ``$defs``
       (their only references were inside the collapsed op unions) and install
       the consolidated ``OpNode`` (the one recursive ``args.items``, arity by
       ``if``/``then``) and ``Node`` (the leaf ∪ op union) definitions.

    The consolidated defs are installed **after** the walk so the walk never
    rewrites them (``Node`` is itself a four-ref union — it would otherwise be
    collapsed into a self-``$ref``).
    """
    _collapse_unions(schema)
    defs = schema["$defs"]
    for name in _RETIRED_OP_DEFS:
        defs.pop(name, None)
    defs["OpNode"] = _op_node_def()
    defs["Node"] = _node_def()


def _collapse_unions(container: object) -> None:
    """Rewrite a container's child values in place, collapsing the op/node
    unions to ``$ref``s (recurses children first, so replacements compose)."""
    if isinstance(container, dict):
        for key, value in list(container.items()):
            container[key] = _collapsed(value)
    elif isinstance(container, list):
        for index, value in enumerate(container):
            container[index] = _collapsed(value)


def _collapsed(value: object) -> object:
    if isinstance(value, dict):
        _collapse_unions(value)
        if _is_op_union(value):
            return {"$ref": _OPNODE_REF}
        if _is_node_union(value):
            return {"$ref": _NODE_REF}
        return value
    if isinstance(value, list):
        _collapse_unions(value)
    return value


def _is_op_union(node: dict[str, Any]) -> bool:
    """A three-variant operator ``oneOf``, identified by the OpenAPI operator
    discriminator pydantic emits on it (``propertyName == "op"``)."""
    discriminator = node.get("discriminator")
    return isinstance(discriminator, dict) and discriminator.get("propertyName") == "op"


def _is_node_union(node: dict[str, Any]) -> bool:
    """The four-arm expression-tree node union: a bare ``oneOf`` of exactly the
    op ``$ref`` (already collapsed) plus the three leaf ``$ref``s — nothing else.
    A ``title`` is tolerated (pydantic labels the top-level alias); it is stripped
    by :func:`_harden` regardless."""
    if set(node) - {"title"} != {"oneOf"}:
        return False
    arms = node["oneOf"]
    if not isinstance(arms, list) or len(arms) != 4:
        return False
    refs = {
        arm.get("$ref")
        for arm in arms
        if isinstance(arm, dict) and set(arm) == {"$ref"}
    }
    return refs == {_OPNODE_REF, *_LEAF_REFS}


def _op_node_def() -> dict[str, Any]:
    """The single consolidated operator-node schema. ``args.items`` references the
    node union **once**; arity is an ``allOf`` of ``if``/``then`` clauses that
    constrain only the ``args`` count — no clause recurses, so validation stays
    linear in tree size."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "op": {"type": "string", "enum": list(_ALL_OPS)},
            "args": {"type": "array", "minItems": 1, "items": {"$ref": _NODE_REF}},
        },
        "required": ["op", "args"],
        "allOf": [
            _arity_clause(_NARY_OPS, min_items=2, max_items=None),
            _arity_clause(_BINARY_OPS, min_items=2, max_items=2),
            _arity_clause(_UNARY_OPS, min_items=1, max_items=1),
        ],
    }


def _arity_clause(
    ops: tuple[str, ...], *, min_items: int, max_items: int | None
) -> dict[str, Any]:
    """One arity ``if``/``then``: when ``op`` is in ``ops``, constrain the
    ``args`` count. The ``if`` reads only ``op`` (never ``args``), and the
    ``then`` carries only count keywords — no recursive subschema."""
    constraint: dict[str, Any] = {"minItems": min_items}
    if max_items is not None:
        constraint["maxItems"] = max_items
    return {
        "if": {"properties": {"op": {"enum": list(ops)}}, "required": ["op"]},
        "then": {"properties": {"args": constraint}},
    }


def _node_def() -> dict[str, Any]:
    """The expression-tree node union: an operator application or one of the three
    leaves. The single recursion seam every ``args.items`` and formula/magnitude
    tree arm now references."""
    return {
        "oneOf": [
            {"$ref": _OPNODE_REF},
            *({"$ref": ref} for ref in _LEAF_REFS),
        ]
    }


def _strip_nullability(node: object) -> None:
    """Recursively enforce optional≠nullable on the generated schema, in place.

    Two deterministic edits per object node (children are visited first, so a
    collapsed arm is already settled when its enclosing node is rewritten):

    1. **Drop the null union arm.** For an ``anyOf``/``oneOf`` (the pydantic
       ``X | None`` projection), remove every ``{"type": "null"}`` arm. If the
       filtered union has exactly one arm left, collapse it: pop the keyword and
       merge that lone arm's keys into the node (the optional field's schema *is*
       its typed arm). A multi-arm union keeps the filtered list.
    2. **Strip a null default.** Remove a ``"default": null`` annotation (the
       companion of an ``X | None`` field, and the bare annotation on a reserved
       section — stripping it there leaves the permissive ``{}``). A genuine
       domain default (``"default": []``) is kept.

    The result is **stricter** than pydantic construction — an explicit ``null``
    is refused structurally before the model would coerce it to the field default
    — so structural-pass ⇒ construction-success still holds (bADR-0004/0005).
    """
    if isinstance(node, dict):
        for value in list(node.values()):
            _strip_nullability(value)
        if "default" in node and node["default"] is None:
            del node["default"]
        for keyword in ("anyOf", "oneOf"):
            arms = node.get(keyword)
            if not isinstance(arms, list):
                continue
            kept = [arm for arm in arms if arm != {"type": "null"}]
            if len(kept) == len(arms):
                continue
            if len(kept) == 1:
                del node[keyword]
                node.update(kept[0])
            else:
                node[keyword] = kept
    elif isinstance(node, list):
        for item in node:
            _strip_nullability(item)


def _harden(node: object) -> None:
    """Recursively strip titles and apply the newline guards, in place.

    Children are visited *before* this node's own mutations so the guard keys we
    add are never re-walked (they carry no ``title`` and the ``"\\n"`` guard
    pattern is not :data:`ID_PATTERN`, so a second pass would be a no-op anyway).
    """
    if isinstance(node, dict):
        for value in list(node.values()):
            _harden(value)
        node.pop("title", None)
        if "patternProperties" in node:
            # `additionalProperties: false` refuses keys matching no pattern;
            # `propertyNames` refuses any key carrying a newline (the case the
            # Python-`re` `$`-leniency would otherwise admit). `setdefault`
            # never clobbers an author-declared keyword — the generated schema
            # carries neither on any patternProperties node today.
            node.setdefault("additionalProperties", False)
            node.setdefault("propertyNames", copy.deepcopy(_NO_NEWLINE))
        if node.get("pattern") == ID_PATTERN:
            node.setdefault("not", copy.deepcopy(_NO_NEWLINE["not"]))
    elif isinstance(node, list):
        for item in node:
            _harden(item)
