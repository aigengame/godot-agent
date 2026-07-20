"""The resolved version bundle and the funnel seam that threads it (#504).

bADR-0001 pins an accepted document to the definition of the ``major.minor`` it
declares; bADR-0005 ships every minor ``X.0 … X.Y`` as its own artifact set. The
bundle is that per-line artifact set, and the funnel resolves the declared line
to one bundle and validates against *its* members. With only ``1.0`` registered
that seam is invisible, so these tests inject a *synthetic* second line through a
test-scoped ``resolve`` (dependency injection — no global is mutated) to prove a
newer minor validates under its own bundle while an older document keeps its own.
"""

import json

from gda_balancing.envelope import Refusal, RefusalReport
from gda_balancing.schema.bundle import (
    BUNDLES,
    SUPPORTED_LINES,
    VersionBundle,
    current_bundle,
    resolve,
)
from gda_balancing.schema.funnel import refusal_code_namespace, validate
from gda_balancing.schema.funnel.semantic.rules import SemanticRule
from gda_balancing.schema.version import (
    SCHEMA_VERSION,
    STRUCTURAL_SCHEMA_ID,
    SUPPORTED_LINE,
)

_SYNTHETIC_CODE = "synthetic_second_line_only"


# --- The real (v1) registry ------------------------------------------------


def test_resolve_returns_the_v1_bundle_for_the_supported_line() -> None:
    bundle = resolve(SUPPORTED_LINE)
    assert bundle is not None
    assert bundle.line == SUPPORTED_LINE
    assert bundle.version == SCHEMA_VERSION
    assert bundle.structural_schema_id == STRUCTURAL_SCHEMA_ID


def test_resolve_returns_none_for_unregistered_lines() -> None:
    # A newer minor and an unknown major alike are simply not in the registry.
    assert resolve("1.7") is None
    assert resolve("2.0") is None


def test_supported_lines_derive_from_the_registry_keys() -> None:
    assert SUPPORTED_LINES == frozenset(BUNDLES)
    assert SUPPORTED_LINES == frozenset({SUPPORTED_LINE})


def test_current_bundle_is_the_newest_registered_line() -> None:
    assert current_bundle().line == SUPPORTED_LINE


def test_bundle_structural_schema_is_the_generated_artifact() -> None:
    schema = current_bundle().structural_schema()
    assert schema["$id"] == STRUCTURAL_SCHEMA_ID


# --- A synthetic second line, injected via a test-scoped resolve -----------


def _synthetic_second_line() -> VersionBundle:
    """A ``1.1`` bundle reusing the v1 bundle's structural schema, model, and
    catalog, plus one extra rule that always refuses — the marker proving *this*
    bundle (not the v1 one) validated a ``1.1`` document."""
    base = current_bundle()
    extra = SemanticRule(
        code=_SYNTHETIC_CODE,
        scope="/",
        description="synthetic marker rule for the second-line seam test",
        since_version="1.1",
        check=lambda _doc, _raw: [
            Refusal(code=_SYNTHETIC_CODE, path="", detail="second-line marker")
        ],
        violation_fixture={},
    )
    return VersionBundle(
        line="1.1",
        version="1.1.0",
        structural_schema=base.structural_schema,
        document_model=base.document_model,
        semantic_rules=(*base.semantic_rules, extra),
        catalog=base.catalog,
        structural_schema_id=base.structural_schema_id,
    )


def _resolve_with_second_line(line: str) -> VersionBundle | None:
    bundles = {**BUNDLES, "1.1": _synthetic_second_line()}
    return bundles.get(line)


def _document(version: str) -> bytes:
    return json.dumps({"schema_version": version, "meta": {"name": "seam"}}).encode(
        "utf-8"
    )


def test_newer_minor_validates_against_its_own_bundle() -> None:
    # A 1.1.0 document resolves to the synthetic 1.1 bundle, so its extra rule
    # fires — proof the resolved bundle's members, not the v1 globals, ran.
    outcome = validate(_document("1.1.0"), resolve=_resolve_with_second_line)
    assert isinstance(outcome, RefusalReport)
    assert {r.code for r in outcome.refusals} == {_SYNTHETIC_CODE}


def test_older_document_does_not_see_the_newer_minors_rule() -> None:
    # The same registry, but a 1.0.0 document resolves to the v1 bundle, whose
    # rule set never contains the synthetic marker — so it still validates.
    outcome = validate(_document("1.0.0"), resolve=_resolve_with_second_line)
    assert not isinstance(outcome, RefusalReport)
    assert outcome.schema_version == "1.0.0"


def test_refusal_namespace_unions_every_registered_bundles_codes() -> None:
    bundles = {**BUNDLES, "1.1": _synthetic_second_line()}
    namespace = refusal_code_namespace(bundles=bundles)
    assert _SYNTHETIC_CODE in namespace
    # Every v1 semantic code is still present alongside the injected one.
    assert {rule.code for rule in current_bundle().semantic_rules} <= namespace


def test_synthetic_line_never_leaks_into_the_real_namespace() -> None:
    # The default namespace reads the real registry only — the injected code is
    # absent, so the multi-line fixtures cannot contaminate the real surface.
    assert _SYNTHETIC_CODE not in refusal_code_namespace()
