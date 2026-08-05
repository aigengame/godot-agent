"""Phase 2 — semantic: the rule registry and the report-all rule runner.

The semantic phase runs only after the structural phase produced no refusals
(bADR-0004): its rules presuppose well-formed shapes. It reports **all**
violations (report-all) by concatenating every registry rule's refusals; the
funnel's :mod:`report` assembler then dedups, orders, and truncates them.

:data:`SEMANTIC_RULES` is the v1 line's registry (bADR-0005); :func:`run`
executes a rule set. The funnel passes the **resolved bundle's** rules so a
document is checked under the line it declared; :data:`SEMANTIC_RULES` is the
default for direct/line-agnostic callers (it is the 1.0 bundle's rule set).
``run`` takes both the typed :class:`DesignDocument` and the raw parsed dict —
the ``$schema`` and reserved-section rules read raw top-level keys the model
aliases (``$schema``) or excludes from serialization (reserved sections).
"""

from typing import Any

from gda_balancing.schema.refusal import Refusal
from gda_balancing.schema.funnel.semantic.rules import SEMANTIC_RULES, SemanticRule
from gda_balancing.schema.model.document import DesignDocument

__all__ = ["SEMANTIC_RULES", "SemanticRule", "run"]


def run(
    doc: DesignDocument,
    raw: dict[str, Any],
    rules: tuple[SemanticRule, ...] = SEMANTIC_RULES,
) -> list[Refusal]:
    """Every semantic refusal for ``doc`` under ``rules`` — the concatenation of
    each rule's check (report-all, bADR-0004). Order/dedup/truncation is
    :mod:`report`'s. ``rules`` defaults to the v1 registry; the funnel passes the
    resolved bundle's rule set."""
    refusals: list[Refusal] = []
    for rule in rules:
        refusals.extend(rule.check(doc, raw))
    return refusals
