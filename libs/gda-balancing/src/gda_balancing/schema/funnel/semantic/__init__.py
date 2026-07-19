"""Phase 2 — semantic: the rule registry and the report-all rule runner.

The semantic phase runs only after the structural phase produced no refusals
(bADR-0004): its rules presuppose well-formed shapes. It reports **all**
violations (report-all) by concatenating every registry rule's refusals; the
funnel's :mod:`report` assembler then dedups, orders, and truncates them.

:data:`SEMANTIC_RULES` is the one registry (bADR-0005); :func:`run` executes it.
``run`` takes both the typed :class:`DesignDocument` and the raw parsed dict —
the ``$schema`` and reserved-section rules read raw top-level keys the model
aliases (``$schema``) or excludes from serialization (reserved sections).
"""

from typing import Any

from gda_balancing.envelope import Refusal
from gda_balancing.schema.funnel.semantic.rules import SEMANTIC_RULES, SemanticRule
from gda_balancing.schema.model.document import DesignDocument

__all__ = ["SEMANTIC_RULES", "SemanticRule", "run"]


def run(doc: DesignDocument, raw: dict[str, Any]) -> list[Refusal]:
    """Every semantic refusal for ``doc`` — the concatenation of each rule's
    check (report-all, bADR-0004). Order/dedup/truncation is :mod:`report`'s."""
    refusals: list[Refusal] = []
    for rule in SEMANTIC_RULES:
        refusals.extend(rule.check(doc, raw))
    return refusals
