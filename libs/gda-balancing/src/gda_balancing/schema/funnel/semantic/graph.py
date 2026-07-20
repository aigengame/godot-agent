"""The base-formula dependency graph — one graph authority (bADR-0002/0003).

The nodes are the declared attributes; there is an edge ``A -> B`` iff ``A``'s
**base formula** references attribute ``B`` (an ``attr`` node or a named form's
``attr`` input; parameters are constants and add no edges, bADR-0002). Two
consumers share this one authority:

* the semantic phase's ``base_formula_cycle`` rule reads
  :func:`cyclic_components` / :func:`cycle_members` (the graph must be acyclic);
* the formula seam's ``evaluate_bases`` reads :func:`topological_order` — the
  definition-time evaluation order (bADR-0003: an ``attr`` node reads the
  referenced attribute's definition-time final value).

The formula **reference walker** (:func:`iter_references`) lives here too: it is
the single place that enumerates a formula's ``attr``/``param`` references with
node-precise RFC 6901 pointer tokens, reused by the reference-integrity rules
(bADR-0004) and — with the effects section (#510) — by effect-magnitude formulas,
which pass their own base-pointer tokens.
"""

from collections.abc import Iterator
from typing import Literal

from gda_balancing.schema.model.formula import (
    AttrRef,
    BinaryOp,
    ExponentialForm,
    Formula,
    FormulaBase,
    LinearForm,
    LiteralNode,
    LookupTableForm,
    NaryOp,
    ParamRef,
    PiecewiseLinearForm,
    PolynomialForm,
    ScalarField,
    UnaryOp,
)

# The concrete operator-node classes — ``OpNode`` is a discriminated-``Union``
# alias (a subscripted generic), so ``isinstance`` must name the members.
_OP_TYPES = (NaryOp, BinaryOp, UnaryOp)

# One reference the walker yields: its kind, the referenced id, and the RFC 6901
# pointer tokens down to the referencing node/field.
RefKind = Literal["attr", "param"]
Tokens = tuple[str | int, ...]
Reference = tuple[RefKind, str, Tokens]

# The v1 named-form kinds (bADR-0003): a formula that is one of these is a form,
# otherwise it is an expression-tree :data:`Node`.
_FORM_TYPES = (
    LinearForm,
    PiecewiseLinearForm,
    PolynomialForm,
    ExponentialForm,
    LookupTableForm,
)


def iter_references(formula: Formula, base_tokens: Tokens) -> Iterator[Reference]:
    """Yield every ``attr``/``param`` reference in ``formula``.

    ``base_tokens`` points at the formula root (e.g. ``("attributes", "items",
    "strike", "base", "formula")``); each yielded reference carries the pointer
    tokens down to the referencing node — a tree leaf (``.../args/1/args/0``), a
    named form's ``input`` (``.../input``), or a scalar param field
    (``.../per_point``). Collection elements (``points``/``coefficients``/
    ``table``) are literals only in v1 (bADR-0003), so they yield nothing.
    """
    if isinstance(formula, _FORM_TYPES):
        yield from _form_references(formula, base_tokens)
    else:
        yield from _node_references(formula, base_tokens)


def _node_references(node: object, tokens: Tokens) -> Iterator[Reference]:
    if isinstance(node, AttrRef):
        yield ("attr", node.attr, tokens)
    elif isinstance(node, ParamRef):
        yield ("param", node.param, tokens)
    elif isinstance(node, LiteralNode):
        return
    elif isinstance(node, _OP_TYPES):
        for index, arg in enumerate(node.args):
            yield from _node_references(arg, (*tokens, "args", index))


def _form_references(
    form: LinearForm
    | PiecewiseLinearForm
    | PolynomialForm
    | ExponentialForm
    | LookupTableForm,
    tokens: Tokens,
) -> Iterator[Reference]:
    # A form's `input` is a typed reference node — its own attr/param edge.
    input_ref = form.input
    if isinstance(input_ref, AttrRef):
        yield ("attr", input_ref.attr, (*tokens, "input"))
    else:
        yield ("param", input_ref.param, (*tokens, "input"))
    # Scalar fields may be parameter knobs; only `linear`/`exponential` have any.
    if isinstance(form, LinearForm):
        yield from _scalar_reference(form.base, (*tokens, "base"))
        yield from _scalar_reference(form.per_point, (*tokens, "per_point"))
    elif isinstance(form, ExponentialForm):
        yield from _scalar_reference(form.coefficient, (*tokens, "coefficient"))
        yield from _scalar_reference(form.growth_rate, (*tokens, "growth_rate"))


def _scalar_reference(field: ScalarField, tokens: Tokens) -> Iterator[Reference]:
    if isinstance(field, ParamRef):
        yield ("param", field.param, tokens)


# --- The dependency graph over declared attributes -------------------------

# The document's attribute map is `DesignDocument.attributes.items`; typing it
# structurally here keeps graph.py dependent on the model shape, not on importing
# the full document model (which would broaden the import surface needlessly).


def _base_formula_edges(document: object) -> dict[str, set[str]]:
    """Adjacency: attribute id -> the declared attribute ids its base formula
    reads. Edges only from base-formula ``attr`` refs; a ref to an *undeclared*
    attribute (the ``attribute_reference_undefined`` rule's job) adds no edge, so
    it can never fabricate a phantom cycle."""
    items = document.attributes.items  # type: ignore[attr-defined]
    edges: dict[str, set[str]] = {}
    for attr_id, attribute in items.items():
        deps: set[str] = set()
        base = attribute.base
        if isinstance(base, FormulaBase):
            for kind, ref_id, _tokens in iter_references(base.formula, ()):
                if kind == "attr" and ref_id in items:
                    deps.add(ref_id)
        edges[attr_id] = deps
    return edges


def cyclic_components(document: object) -> list[list[str]]:
    """The base-formula reference cycles, each a sorted id list.

    A cycle is a strongly-connected component with an internal edge — a
    multi-node SCC, or a single attribute whose base formula references itself.
    The list is deterministic: components sorted, ids within each sorted."""
    edges = _base_formula_edges(document)
    cycles: list[list[str]] = []
    for component in _strongly_connected_components(edges):
        cyclic = len(component) > 1 or any(node in edges[node] for node in component)
        if cyclic:
            cycles.append(sorted(component))
    return sorted(cycles)


def cycle_members(document: object) -> set[str]:
    """Every attribute participating in a base-formula reference cycle."""
    return {member for component in cyclic_components(document) for member in component}


def topological_order(document: object) -> list[str]:
    """A definition-time evaluation order — dependencies before dependents.

    Kahn's algorithm with a **sorted ready-set**, so the order is deterministic.
    The precondition is an acyclic graph (guaranteed once the funnel's
    ``base_formula_cycle`` rule has passed); a cyclic graph would leave its
    members unplaced (a caller bug the funnel prevents)."""
    edges = _base_formula_edges(document)
    indegree = {node: len(deps) for node, deps in edges.items()}
    dependents: dict[str, set[str]] = {node: set() for node in edges}
    for node, deps in edges.items():
        for dep in deps:
            dependents[dep].add(node)
    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        newly: list[str] = []
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                newly.append(dependent)
        if newly:
            ready = sorted(ready + newly)
    return order


def _strongly_connected_components(edges: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan's SCC, iterative (attribute count can reach the collection cap, so
    recursion is unsafe). Deterministic: roots and neighbors visited sorted."""
    index_of: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    tarjan_stack: list[str] = []
    components: list[set[str]] = []
    counter = 0

    for start in sorted(edges):
        if start in index_of:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, i = work[-1]
            if i == 0:
                index_of[node] = counter
                lowlink[node] = counter
                counter += 1
                tarjan_stack.append(node)
                on_stack.add(node)
            neighbors = sorted(edges[node])
            recurse = False
            while i < len(neighbors):
                nxt = neighbors[i]
                if nxt not in index_of:
                    work[-1] = (node, i + 1)
                    work.append((nxt, 0))
                    recurse = True
                    break
                if nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index_of[nxt])
                i += 1
            if recurse:
                continue
            work.pop()
            if lowlink[node] == index_of[node]:
                component: set[str] = set()
                while True:
                    member = tarjan_stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                components.append(component)
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
    return components
