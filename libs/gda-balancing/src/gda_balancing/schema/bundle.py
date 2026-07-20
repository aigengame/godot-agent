"""The resolved version bundle — everything one Standard Schema line pins.

bADR-0001 requires an accepted document to be validated **against the definition
of the ``major.minor`` line it declares**, and bADR-0005 requires a validator
serving ``X.Y`` to ship every minor ``X.0 … X.Y`` in its **own** artifact set. A
:class:`VersionBundle` is that per-line artifact set made explicit: the
structural schema, document model, semantic rules, catalog, and structural
``$id`` a single line resolves to. The boundary funnel resolves the declared
line to one immutable bundle and validates against *its* members — never a
process-global "current" schema/model/rule set — so the first additive minor
can never silently validate an older document under newer rules.

**Layering — why this module sits *above* the funnel, acyclically.** The bundle
needs the document model, the generated artifacts, and the semantic rule
registry; the registry lives under :mod:`gda_balancing.schema.funnel.semantic`,
so importing it runs the ``funnel`` package. The funnel therefore must not import
this module at load time, or the two would form a cycle. It does not:
:mod:`~gda_balancing.schema.funnel.preflight` and
:mod:`~gda_balancing.schema.funnel.structural` receive a resolved bundle (or a
``resolve`` callable) as a **parameter** and name :class:`VersionBundle` only
under ``TYPE_CHECKING``; :func:`gda_balancing.schema.funnel.validate` and
:func:`gda_balancing.schema.funnel.refusal_code_namespace` reach for
:func:`resolve` / :data:`BUNDLES` **lazily**, at call time. The one runtime
import edge is thus ``bundle`` → funnel, and it is acyclic.

:mod:`gda_balancing.schema.version` stays the dependency-free base
(``SCHEMA_VERSION``, ``SUPPORTED_LINE``, ``STRUCTURAL_SCHEMA_ID``,
``parse_line``); this module composes those primitives with the
model/artifacts/rules into the per-line bundle. :data:`BUNDLES` is the single
supported-lines authority — :data:`SUPPORTED_LINES` derives from its keys, and
registry membership *is* the acceptance test (bADR-0001).
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from gda_balancing.schema.artifacts import generate_catalog, generate_structural_schema
from gda_balancing.schema.funnel.semantic import SEMANTIC_RULES, SemanticRule
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.version import (
    SCHEMA_VERSION,
    STRUCTURAL_SCHEMA_ID,
    SUPPORTED_LINE,
)


@dataclass(frozen=True)
class VersionBundle:
    """The immutable artifact set one Standard Schema line resolves to.

    ``line`` is the ``major.minor`` this bundle serves; ``version`` is the full
    shipped patch. ``structural_schema`` and ``catalog`` are zero-arg callables
    (lazy, cached) that build *this line's* generated artifacts;
    ``document_model`` is the pydantic model construction uses;
    ``semantic_rules`` are the rules the semantic phase runs; and
    ``structural_schema_id`` is the ``$id`` a document's ``$schema`` must agree
    with (bADR-0001). Nothing here is a process-global: a funnel phase reads the
    resolved bundle, so a ``1.0`` document keeps 1.0's envelope even on a
    validator that also serves a newer minor.
    """

    line: str
    version: str
    structural_schema: Callable[[], dict[str, Any]]
    document_model: type[DesignDocument]
    semantic_rules: tuple[SemanticRule, ...]
    catalog: Callable[[], dict[str, Any]]
    structural_schema_id: str


# The v1 line's bundle: version.py's primitives composed with the generated
# artifacts, the document model, and the one semantic rule registry. Both
# generators are wrapped in `functools.cache` so each line's structural schema /
# catalog is built at most once and shared by the funnel's structural phase and
# the `schema get` surface.
_V1_0 = VersionBundle(
    line=SUPPORTED_LINE,
    version=SCHEMA_VERSION,
    structural_schema=functools.cache(generate_structural_schema),
    document_model=DesignDocument,
    semantic_rules=SEMANTIC_RULES,
    catalog=functools.cache(generate_catalog),
    structural_schema_id=STRUCTURAL_SCHEMA_ID,
)


# The bundle registry — the single supported-lines authority (bADR-0005): one
# entry per minor line this validator serves. v1 ships exactly the 1.0 line.
BUNDLES: Mapping[str, VersionBundle] = {_V1_0.line: _V1_0}

# Every supported line, derived from the registry keys — not a second hardcoded
# list (the registry IS the source of truth).
SUPPORTED_LINES: frozenset[str] = frozenset(BUNDLES)


def resolve(line: str) -> VersionBundle | None:
    """The bundle serving ``line`` (a well-formed ``major.minor``), or ``None``
    when this validator does not serve it.

    Registry membership is the acceptance test (bADR-0001): because a validator
    serving ``X.Y`` registers every minor ``X.0 … X.Y`` (bADR-0005), "in the
    registry" is exactly "major ``X``, minor ``≤ Y``" — no separate arithmetic
    gate, one authority.
    """
    return BUNDLES.get(line)


def current_bundle() -> VersionBundle:
    """The newest supported bundle — the one the line-agnostic surfaces
    (``schema get structural|catalog``, ``version``) describe. Newest is the
    highest ``(major, minor)`` in the registry."""
    return max(BUNDLES.values(), key=lambda bundle: _line_ordinal(bundle.line))


def _line_ordinal(line: str) -> tuple[int, ...]:
    return tuple(int(part) for part in line.split("."))
