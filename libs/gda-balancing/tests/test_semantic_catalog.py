"""The semantic rule registry, its conformance walk, and the published catalog.

The registry (:data:`SEMANTIC_RULES`) is the one authority; the catalog artifact
and this conformance walk are both projections of it (bADR-0005 anti-drift).

Two conformance surfaces:

* **Per-rule** (bADR-0004: "each rule refuses its violation fixture") — for every
  registered rule, its ``violation_fixture`` is a valid-except-for-this-rule
  document that the semantic phase refuses with *exactly* this rule's code,
  asserted both at the semantic-phase layer (on the typed document) and end to
  end through the CLI. No rule is shadowed by an earlier phase any longer: once
  the nesting cap composes with the formula depth limit (96 ≥ a legal depth-≤32
  tree, #527) and structural validation is linear, a depth-33 tree clears
  preflight and the structural phase and is refused by ``expression_tree_too_deep``
  itself (see ``test_deep_expression_tree_is_refused`` in test_validate_vectors.py).
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


# No rule is shadowed by an earlier phase: the nesting cap now composes with the
# formula depth limit (96 clears a legal depth-≤32 tree, #527) and structural
# validation is linear, so `expression_tree_too_deep`'s depth-33 fixture reaches
# the semantic phase and refuses with its own code end to end. The mechanism is
# kept (empty) so a NEW earlier-phase shadowing of any rule is a deliberate,
# documented exception here rather than a silent gap.
_FUNNEL_SHADOWED: frozenset[str] = frozenset()


@pytest.mark.parametrize("rule", SEMANTIC_RULES, ids=[r.code for r in SEMANTIC_RULES])
def test_rule_fixture_refuses_end_to_end(rule, run_cli, tmp_path) -> None:
    # The CLI route: an agent submitting the fixture gets exit 2 carrying
    # exactly this rule's code — funnel reachability as an executable
    # invariant, not an assumption the semantic-layer walk leaves open.
    if rule.code in _FUNNEL_SHADOWED:
        pytest.skip("structurally shadowed by an earlier funnel phase")
    doc_path = tmp_path / "fixture.json"
    doc_path.write_text(json.dumps(rule.violation_fixture), encoding="utf-8")
    exit_code, stdout, stderr = run_cli(["design", "validate", str(doc_path)])
    assert (exit_code, stderr) == (2, "")
    codes = {r["code"] for r in json.loads(stdout)["error"]["refusals"]}
    assert codes == {rule.code}


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
