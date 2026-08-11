"""The boundary funnel — the one validation boundary every document crosses.

Every Design document crosses this single boundary before any use; downstream
code never re-validates and never defends (bADR-0004). This package is the
funnel's public face. It runs Phase 0 (preflight), Phase 1 (structural), then
Phase 2 (semantic), each gating the next, and returns the **typed Design
document** on success. The semantic phase's rule codes union into
:func:`refusal_code_namespace`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from gda_balancing.schema.refusal import RefusalReport
from gda_balancing.schema.funnel import report, semantic
from gda_balancing.schema.funnel.preflight import (
    PREFLIGHT_CODES,
    preflight,
)
from gda_balancing.schema.funnel.structural import STRUCTURAL_VIOLATION, structural
from gda_balancing.schema.model.document import DesignDocument

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from gda_balancing.schema.bundle import VersionBundle

__all__ = ["validate", "refusal_code_namespace"]


def validate(
    data: bytes,
    resolve: Callable[[str], VersionBundle | None] | None = None,
) -> DesignDocument | RefusalReport:
    """Run the funnel over the document bytes, phase by phase.

    Preflight (Phase 0) resolves the declared line to a **version bundle** and
    then structural (Phase 1) and semantic (Phase 2) validate the document
    against *that bundle's* schema, model, and rules — never a process-global
    "current" set — so a ``1.0`` document keeps 1.0's envelope even on a
    validator that also serves a newer minor (bADR-0001). The first phase to
    produce refusals returns them as an assembled :class:`RefusalReport` (the
    dispatch tail maps it onto the `refusal` envelope / exit 2).

    Construction **must** succeed after a structural pass — the bundle's
    structural schema is hardened so structural-pass ⇒ model-construction-success
    (bADR-0005; :mod:`gda_balancing.schema.artifacts`). A ``ValidationError``
    here is therefore an *engine-parity bug*, not a user error: it is re-raised
    as a :class:`RuntimeError` so it takes the internal path (exit 4), never a
    silent refusal. The engine-parity tests exist to keep this unreachable.

    ``resolve`` maps a well-formed ``major.minor`` line to its bundle; it
    defaults to the real registry (:func:`gda_balancing.schema.bundle.resolve`,
    imported lazily to keep the funnel free of a load-time ``bundle``
    dependency). Tests inject a synthetic registry through it.
    """
    if resolve is None:
        from gda_balancing.schema.bundle import resolve as resolve

    pre_refusals, root, maybe_bundle = preflight(data, resolve)
    preflight_report = report.assemble(pre_refusals)
    if preflight_report is not None:
        return preflight_report

    # An empty preflight refusal list implies version dispatch resolved a bundle
    # (sub-step 6); the cast records that invariant without an input-boundary
    # assert, mirroring the `root` cast below.
    bundle = cast("VersionBundle", maybe_bundle)

    structural_report = report.assemble(structural(root, bundle))
    if structural_report is not None:
        return structural_report

    try:
        document = bundle.document_model.model_validate(root)
    except ValidationError as exc:
        raise RuntimeError(
            "structural schema passed but model construction failed — "
            f"engine-parity bug: {exc}"
        ) from exc

    # `root` is a parsed object; the semantic rules that read raw top-level keys
    # (`$schema`, reserved sections) need a dict. Preflight already refused a
    # non-object root as `malformed_schema_version`, and the structural phase
    # re-validates the closed object envelope — so by here `root` is a dict. The
    # cast records that invariant without an input-boundary assert.
    raw = cast(dict[str, Any], root)
    semantic_report = report.assemble(
        semantic.run(document, raw, bundle.semantic_rules)
    )
    if semantic_report is not None:
        return semantic_report

    return document


def refusal_code_namespace(
    bundles: Mapping[str, VersionBundle] | None = None,
) -> frozenset[str]:
    """Every stable refusal code the funnel can emit.

    The preflight family, the single structural code, and every semantic rule's
    code across **all registered bundles** (the rule id *is* its refusal code,
    bADR-0004/0005) — a validator serving several lines can emit any line's
    codes. ``bundles`` defaults to the real registry
    (:data:`gda_balancing.schema.bundle.BUNDLES`, imported lazily); tests pass a
    synthetic registry. The conformance harness asserts every emitted refusal
    code resolves against this namespace, so the CLI can never grow a second
    refusal-code registry (bADR-0011).
    """
    if bundles is None:
        from gda_balancing.schema.bundle import BUNDLES

        bundles = BUNDLES
    return (
        PREFLIGHT_CODES
        | {STRUCTURAL_VIOLATION}
        | {rule.code for bundle in bundles.values() for rule in bundle.semantic_rules}
    )
