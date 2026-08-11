"""The semantic rule registry, its conformance walk, and the published catalog.

The registry (:data:`SEMANTIC_RULES`) is the one authority; the catalog artifact
and this conformance walk are both projections of it (bADR-0005 anti-drift).

Two conformance surfaces:

* **Per (rule, scope template)** (bADR-0004: "each rule refuses its violation
  fixture", sharpened in #527 recheck-3) — a rule carries **one violation fixture
  per scope template, positionally aligned**, each a valid-except-for-this-rule
  document that the semantic phase refuses with *exactly* this rule's code, and
  whose emitted path matches **specifically its aligned template** (not merely
  some template of the rule). Asserted both at the semantic-phase layer (on the
  typed document) and end to end through the CLI. Together with the global
  soundness walk below this makes anti-drift executable in **both** directions:
  emitted ⊆ declared (no emitted path escapes a template) *and* declared ⊆
  exercised (every declared template has a fixture that lands on it), so a future
  third formula consumer that a rule grows but the corpus omits fails the test.
  No rule is shadowed by an earlier phase any longer: once the nesting cap
  composes with the formula depth limit (96 ≥ a legal depth-≤32 tree, #527) and
  structural validation is linear, a depth-33 tree clears preflight and the
  structural phase and is refused by ``expression_tree_too_deep`` itself (see
  ``test_deep_expression_tree_is_refused`` in test_validate_vectors.py).
* **Catalog↔registry identity** — the historical 1.x catalog projection's rule
  ids equal the sorted registry codes, each entry carries the full metadata, and
  the bytes match a committed golden.
"""

import json
from pathlib import Path

from gda_balancing.interfaces.cli.rendering import canonical_json
from gda_balancing.schema.bundle import current_bundle
from gda_balancing.schema.funnel import semantic
from gda_balancing.schema.funnel.semantic import SEMANTIC_RULES
from gda_balancing.schema.model.document import DesignDocument

import pytest

_GOLDEN = Path(__file__).parent / "goldens" / "semantic_catalog.json"


# One conformance case per aligned (violation fixture, scope template): a rule
# with N scope templates yields N cases, and `violation_fixtures[i]` is the
# fixture that must refuse specifically at `scope[i]` (bADR-0005 anti-drift,
# declared ⊆ exercised, #527 recheck-3). The dataclass `__post_init__` already
# guarantees `len(violation_fixtures) == len(scope)`.
_RULE_TEMPLATE_CASES = [
    (rule, index) for rule in SEMANTIC_RULES for index in range(len(rule.scope))
]
_CASE_IDS = [f"{rule.code}[{index}]" for rule, index in _RULE_TEMPLATE_CASES]


@pytest.mark.parametrize(("rule", "index"), _RULE_TEMPLATE_CASES, ids=_CASE_IDS)
def test_rule_refuses_exactly_its_violation_fixture(rule, index) -> None:
    """The semantic-layer walk — a **supplemental internal diagnostic** (#504's
    external-boundary criterion): it asserts each rule at the semantic phase on
    the typed document, for **every** aligned fixture, while the acceptance
    evidence lives at the CLI/JSON surface (``test_rule_fixture_refuses_end_to_end``
    runs the same fixtures through ``design validate``) and the public formula
    seam."""
    # Each aligned fixture is a complete, structurally valid document (it
    # constructs), so the semantic phase is what refuses it.
    raw = rule.violation_fixtures[index]
    doc = DesignDocument.model_validate(raw)

    # The rule's own check yields only its code (a rule owns one code).
    own = rule.check(doc, raw)
    assert own, f"{rule.code} did not refuse fixture {index}"
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


@pytest.mark.parametrize(("rule", "index"), _RULE_TEMPLATE_CASES, ids=_CASE_IDS)
def test_rule_fixture_refuses_end_to_end(rule, index, run_legacy_cli, tmp_path) -> None:
    # The CLI route: an agent submitting the fixture gets exit 2 carrying
    # exactly this rule's code — funnel reachability as an executable
    # invariant, not an assumption the semantic-layer walk leaves open.
    if rule.code in _FUNNEL_SHADOWED:
        pytest.skip("structurally shadowed by an earlier funnel phase")
    template = rule.scope[index]
    doc_path = tmp_path / "fixture.json"
    doc_path.write_text(json.dumps(rule.violation_fixtures[index]), encoding="utf-8")
    exit_code, stdout, stderr = run_legacy_cli(["design", "validate", str(doc_path)])
    assert (exit_code, stderr) == (2, "")
    refusals = json.loads(stdout)["error"]["refusals"]
    # (a) Exactly this rule's code (a rule owns one code, no cascade).
    assert {r["code"] for r in refusals} == {rule.code}
    # (b) At least one emitted path matches SPECIFICALLY this fixture's aligned
    # scope template — declared ⊆ exercised per (rule, template), not merely
    # "some template of the rule" (which the global soundness walk covers).
    assert any(_scope_matches(template, r["path"]) for r in refusals), (
        f"{rule.code}[{index}] emitted {[r['path'] for r in refusals]}, "
        f"none matching its aligned template {template!r}"
    )


def test_registry_codes_are_unique() -> None:
    codes = [rule.code for rule in SEMANTIC_RULES]
    assert len(codes) == len(set(codes))


# --- Historical 1.x catalog projection ↔ registry identity ----------------


def _catalog() -> dict:
    return current_bundle().catalog()


def test_catalog_ids_match_the_registry() -> None:
    catalog = _catalog()
    ids = [entry["id"] for entry in catalog["rules"]]
    assert ids == sorted(rule.code for rule in SEMANTIC_RULES)


def test_catalog_entries_carry_full_metadata() -> None:
    catalog = _catalog()
    by_id = {entry["id"]: entry for entry in catalog["rules"]}
    for rule in SEMANTIC_RULES:
        entry = by_id[rule.code]
        # `scope` is a JSON array of RFC 6901 pointer templates — one element
        # per site a rule applies to (a single-site rule is a one-element array;
        # the two reference-integrity rules carry both their formula and their
        # magnitude sites).
        assert isinstance(entry["scope"], list)
        assert entry["scope"] == list(rule.scope)
        assert entry["description"] == rule.description
        assert entry["since_version"] == rule.since_version
        assert sorted(entry) == ["description", "id", "scope", "since_version"]


def test_catalog_declares_the_schema_version() -> None:
    from gda_balancing.schema.version import SCHEMA_VERSION

    assert _catalog()["schema_version"] == SCHEMA_VERSION


def test_historical_catalog_projection_matches_golden() -> None:
    # Byte-for-byte against the committed golden. To regenerate after a reviewed
    # rule change, overwrite it deliberately and review the diff:
    stdout = canonical_json(_catalog())
    assert stdout.encode("utf-8") == _GOLDEN.read_bytes()
    # The golden is canonical (sorted keys, single trailing LF).
    assert stdout == canonical_json(json.loads(stdout))


# --- Behavioral scope anti-drift (bADR-0005 amendment, #527 recheck-4) -------
#
# The catalog↔registry identity tests pin the scope *arrays* byte-for-byte, but
# byte-identity alone cannot tell whether a rule's templates actually describe
# WHERE it refuses. This is the behavioral guard: run a broad corpus of refusing
# documents through the real funnel and assert every emitted refusal path is
# matched by one of its rule's scope templates. A rule that grows a new refusal
# site without enumerating it in `scope` fails here — the under-enumeration this
# recheck found (a shared formula rule firing at an effect magnitude the scope
# never listed) becomes an executable, not disciplinary, invariant.
#
# Matching contract (the tightest workable one, read off what the checks emit):
#   * A template splits into RFC 6901 tokens; a `{...}` token (`{id}`,
#     `{index}`, `{section}`) is a single-token wildcard, every other token
#     matches literally.
#   * A template whose final token is a **formula root** (`formula` or
#     `magnitude`) matches a concrete path that has the template as a token-wise
#     *prefix*: the reference rules descend into tree nodes below the root
#     (`.../formula/args/0`, `.../magnitude/input`) and the tree-cap rules sit
#     exactly at the root. Every OTHER template must match token-for-token
#     (equal length), so a form-field rule ending at its named field
#     (`.../points`, `.../coefficients`, `.../tier`) can neither absorb a deeper
#     pointer nor be satisfied by a shallower enclosing one.
#
# Soundness (no emitted path escapes its templates — emitted ⊆ declared) is what
# THIS walk asserts; completeness (declared ⊆ exercised — every listed template
# has a fixture that lands on it) is pinned by the per-(rule, template)
# end-to-end test above, whose aligned fixtures each refuse specifically at their
# own template. The two together make anti-drift executable in both directions.

_FORMULA_ROOT_TOKENS = frozenset({"formula", "magnitude"})


def _pointer_tokens(pointer: str) -> list[str]:
    # RFC 6901: "" is the document root; otherwise a leading "/" yields a leading
    # "" that we drop, so `/a/b` → ["a", "b"].
    return pointer.split("/")[1:] if pointer else []


def _token_matches(template_token: str, path_token: str) -> bool:
    if template_token.startswith("{") and template_token.endswith("}"):
        return True  # a single-token placeholder wildcard
    return template_token == path_token


def _scope_matches(template: str, path: str) -> bool:
    t_tokens = _pointer_tokens(template)
    p_tokens = _pointer_tokens(path)
    if t_tokens and t_tokens[-1] in _FORMULA_ROOT_TOKENS:
        # A formula-root template matches its whole formula subtree: the concrete
        # path may descend past the root, so compare only the shared prefix.
        if len(p_tokens) < len(t_tokens):
            return False
        p_tokens = p_tokens[: len(t_tokens)]
    if len(t_tokens) != len(p_tokens):
        return False
    return all(_token_matches(t, p) for t, p in zip(t_tokens, p_tokens))


def test_every_emitted_refusal_path_matches_a_scope_template(
    run_legacy_cli, tmp_path
) -> None:
    """Every refusal the funnel emits over the corpus is matched by one of its
    rule's scope templates (see the contract note above). The corpus is **every**
    aligned violation fixture of every rule — which now covers both the
    `.../base/formula` and the `.../magnitude` site of each shared formula rule,
    so the separate magnitude probes this test used to carry are subsumed. This is
    the behavioral soundness half (emitted ⊆ declared): byte-identity pins WHAT
    the templates are, this pins that no emitted refusal escapes them."""
    rules_by_code = {rule.code: rule for rule in SEMANTIC_RULES}
    corpus = [fixture for rule in SEMANTIC_RULES for fixture in rule.violation_fixtures]
    doc_path = tmp_path / "doc.json"
    for document in corpus:
        doc_path.write_text(json.dumps(document), encoding="utf-8")
        exit_code, stdout, stderr = run_legacy_cli(
            ["design", "validate", str(doc_path)]
        )
        assert (exit_code, stderr) == (2, ""), stdout
        refusals = json.loads(stdout)["error"]["refusals"]
        assert refusals, document
        for refusal in refusals:
            code, path = refusal["code"], refusal["path"]
            rule = rules_by_code.get(code)
            assert rule is not None, f"uncatalogued refusal code {code!r}"
            assert any(_scope_matches(t, path) for t in rule.scope), (
                f"{code} emitted path {path!r}, matched by no scope template "
                f"in {rule.scope}"
            )
