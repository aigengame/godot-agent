"""Report-all assembly — the deterministic, bounded refusal list (bADR-0004).

Every executed funnel phase collects *all* its violations rather than failing
fast (an agent fixes a batch per round trip). This module turns a phase's raw
refusals into the reported list: deduplicated on ``(code, path)``, ordered by
``(path, code)``, and truncated to :data:`REFUSAL_BOUND` with an explicit
``truncated`` marker so "1000 refusals" is never mistaken for "all refusals".
One assembler, reused by preflight now and by the structural/semantic phases
later.
"""

from collections.abc import Iterable

from gda_balancing.schema.refusal import REFUSAL_BOUND, Refusal, RefusalReport


def assemble(refusals: Iterable[Refusal]) -> RefusalReport | None:
    """Assemble raw refusals into the reported list, or ``None`` when empty.

    ``None`` means the phase produced no refusals — the funnel reads it as
    "passed"; a non-``None`` report is what the dispatch tail maps onto the
    `refusal` envelope / exit 2 (bADR-0008).
    """
    unique: dict[tuple[str, str], Refusal] = {}
    for refusal in refusals:
        unique.setdefault((refusal.code, refusal.path), refusal)
    ordered = sorted(unique.values(), key=lambda r: (r.path, r.code))
    if not ordered:
        return None
    truncated = len(ordered) > REFUSAL_BOUND
    return RefusalReport(refusals=tuple(ordered[:REFUSAL_BOUND]), truncated=truncated)
