"""The base-formula dependency graph — one graph authority (bADR-0002/0003).

Direct coverage of the two public graph queries the semantic phase and the
formula seam share: :func:`cycle_members` (the ``base_formula_cycle`` rule) and
:func:`topological_order` (the seam's ``evaluate_bases``). The graph is built
from typed documents constructed straight through the model — these are unit
tests of the graph, below the funnel.
"""

from gda_balancing.schema.funnel.semantic.graph import cycle_members, topological_order
from gda_balancing.schema.model.document import DesignDocument


def _document(items: dict) -> DesignDocument:
    return DesignDocument.model_validate(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "graph"},
            "attributes": {"items": items},
        }
    )


def _direct(value: float) -> dict:
    return {"domain": "number", "base": {"direct": value}}


def _reads(*attr_ids: str) -> dict:
    # A base formula that reads the given attributes (an add over attr nodes, or
    # a bare attr node for a single dependency).
    if len(attr_ids) == 1:
        formula: dict = {"attr": attr_ids[0]}
    else:
        formula = {"op": "add", "args": [{"attr": a} for a in attr_ids]}
    return {"domain": "number", "base": {"formula": formula}}


def test_topological_order_places_dependencies_first():
    # `derived` reads `mid`, which reads `root`; params/literals add no edges.
    document = _document(
        {"root": _direct(1), "mid": _reads("root"), "derived": _reads("mid")}
    )
    order = topological_order(document)
    assert order.index("root") < order.index("mid") < order.index("derived")


def test_topological_order_is_deterministic_via_sorted_ready_set():
    # Three independent roots and one dependent: the ready-set is emitted sorted,
    # so the order is fully determined (not insertion- or hash-dependent). After
    # `beta` is placed, `dependent` becomes ready and is re-sorted against the
    # still-pending `gamma` — and `"dependent" < "gamma"`, so it lands first.
    document = _document(
        {
            "gamma": _direct(1),
            "alpha": _direct(2),
            "beta": _direct(3),
            "dependent": _reads("alpha", "beta"),
        }
    )
    order = topological_order(document)
    assert order == ["alpha", "beta", "dependent", "gamma"]


def test_cycle_members_empty_when_acyclic():
    document = _document({"root": _direct(1), "leaf": _reads("root")})
    assert cycle_members(document) == set()


def test_cycle_members_reports_mutual_cycle():
    document = _document({"alpha": _reads("beta"), "beta": _reads("alpha")})
    assert cycle_members(document) == {"alpha", "beta"}


def test_cycle_members_excludes_a_node_merely_downstream_of_a_cycle():
    # `tail` depends on the a<->b cycle but is not itself cyclic.
    document = _document(
        {
            "a": _reads("b"),
            "b": _reads("a"),
            "tail": _reads("a"),
        }
    )
    assert cycle_members(document) == {"a", "b"}
