"""The semantic rule registry, its conformance walk, and the published catalog.

The registry (:data:`SEMANTIC_RULES`) is the one authority; the catalog artifact
and this conformance walk are both projections of it (bADR-0005 anti-drift).

Two conformance surfaces:

* **Per-rule** (bADR-0004: "each rule refuses its violation fixture") — for every
  registered rule, its ``violation_fixture`` is a valid-except-for-this-rule
  document that the semantic phase refuses with *exactly* this rule's code. This
  is asserted at the semantic-phase layer (on the typed document), because one
  rule — ``expression_tree_too_deep`` — is structurally shadowed at the full
  funnel by the preflight JSON-nesting cap (any depth-33 tree has JSON nesting
  > 64, so preflight refuses it terminally before the semantic phase; see
  ``test_deep_expression_tree_is_refused`` in test_validate_vectors.py).
* **Catalog↔registry identity** — the published ``schema get catalog`` artifact's
  rule ids equal the sorted registry codes, each entry carries the full metadata,
  and the bytes match a committed golden.
"""

import json
from pathlib import Path

from gda_balancing.emit import canonical_json
from gda_balancing.schema.funnel import semantic
from gda_balancing.schema.funnel.semantic import SEMANTIC_RULES
from gda_balancing.schema.model.document import DesignDocument

import pytest

_GOLDEN = Path(__file__).parent / "goldens" / "semantic_catalog.json"


@pytest.mark.parametrize("rule", SEMANTIC_RULES, ids=[r.code for r in SEMANTIC_RULES])
def test_rule_refuses_exactly_its_violation_fixture(rule) -> None:
    # The fixture is a complete, structurally valid document (it constructs), so
    # the semantic phase is what refuses it.
    raw = rule.violation_fixture
    doc = DesignDocument.model_validate(raw)

    # The rule's own check yields only its code (a rule owns one code).
    own = rule.check(doc, raw)
    assert own, f"{rule.code} did not refuse its own fixture"
    assert {r.code for r in own} == {rule.code}

    # Across the whole registry the fixture trips this rule and nothing else —
    # "valid except for this one rule".
    assert {r.code for r in semantic.run(doc, raw)} == {rule.code}


def test_registry_codes_are_unique() -> None:
    codes = [rule.code for rule in SEMANTIC_RULES]
    assert len(codes) == len(set(codes))


# --- Catalog artifact ↔ registry identity (via the CLI) --------------------


def _catalog(run_cli) -> dict:
    exit_code, stdout, stderr = run_cli(["schema", "get", "catalog"])
    assert (exit_code, stderr) == (0, "")
    return json.loads(stdout)


def test_catalog_ids_match_the_registry(run_cli) -> None:
    catalog = _catalog(run_cli)
    ids = [entry["id"] for entry in catalog["rules"]]
    assert ids == sorted(rule.code for rule in SEMANTIC_RULES)


def test_catalog_entries_carry_full_metadata(run_cli) -> None:
    catalog = _catalog(run_cli)
    by_id = {entry["id"]: entry for entry in catalog["rules"]}
    for rule in SEMANTIC_RULES:
        entry = by_id[rule.code]
        assert entry["scope"] == rule.scope
        assert entry["description"] == rule.description
        assert entry["since_version"] == rule.since_version
        assert sorted(entry) == ["description", "id", "scope", "since_version"]


def test_catalog_declares_the_schema_version(run_cli) -> None:
    from gda_balancing.schema.version import SCHEMA_VERSION

    assert _catalog(run_cli)["schema_version"] == SCHEMA_VERSION


def test_schema_get_catalog_matches_golden(run_cli) -> None:
    # Byte-for-byte against the committed golden. To regenerate after a reviewed
    # rule change, overwrite it deliberately and review the diff:
    #   uv run gda-balancing schema get catalog \
    #     > libs/gda-balancing/tests/goldens/semantic_catalog.json
    exit_code, stdout, stderr = run_cli(["schema", "get", "catalog"])
    assert (exit_code, stderr) == (0, "")
    assert stdout.encode("utf-8") == _GOLDEN.read_bytes()
    # The golden is canonical (sorted keys, single trailing LF).
    assert stdout == canonical_json(json.loads(stdout))
