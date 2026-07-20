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
    """The semantic-layer walk — a **supplemental internal diagnostic** (#504's
    external-boundary criterion): it asserts each rule at the semantic phase on
    the typed document, while the acceptance evidence lives at the CLI/JSON
    surface (``test_rule_fixture_refuses_end_to_end`` runs the same fixtures
    through ``design validate``) and the public formula seam."""
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
        # `scope` is a JSON array of RFC 6901 pointer templates — one element
        # per site a rule applies to (a single-site rule is a one-element array;
        # the two reference-integrity rules carry both their formula and their
        # magnitude sites).
        assert isinstance(entry["scope"], list)
        assert entry["scope"] == list(rule.scope)
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
# Soundness (no emitted path escapes its templates) is what this asserts;
# completeness of each array — that every listed template is reachable — is
# pinned by the golden + metadata identity tests above.

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


def _unary_chain(depth: int) -> dict:
    """A ``floor`` chain of expression-tree depth ``depth`` (``depth - 1`` ops
    around a literal leaf)."""
    node: dict = {"literal": 1}
    for _ in range(depth - 1):
        node = {"op": "floor", "args": [node]}
    return node


def _magnitude_probe(magnitude: dict) -> dict:
    """A document valid except for one effect magnitude — the corpus rows that
    exercise the shared formula rules at their `.../magnitude` site (the attribute
    `.../base/formula` site is exercised by each rule's own violation fixture)."""
    return {
        "schema_version": "1.0.0",
        "meta": {"name": "magnitude-probe"},
        "attributes": {
            "items": {
                "power": {
                    "domain": "number",
                    "base": {"direct": 10},
                    "accepts": ["effects"],
                }
            }
        },
        "effects": {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "regen": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": magnitude,
                        }
                    ],
                    "duration": "infinite",
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        },
    }


# Magnitude-site probes for every shared formula rule: the form-field rules at
# `points`/`table`/`coefficients`/`growth_rate`, the tree caps exactly at the
# magnitude root, and the reference rules descending BELOW the root (the
# formula-root prefix case — an undefined ref nested in a tree arm).
_MAGNITUDE_PROBES = [
    _magnitude_probe({"form": "lookup_table", "input": {"attr": "power"}, "table": []}),
    _magnitude_probe(
        {
            "form": "piecewise_linear",
            "input": {"attr": "power"},
            "points": [[5, 30], [1, 10]],
        }
    ),
    _magnitude_probe(
        {
            "form": "polynomial",
            "input": {"attr": "power"},
            "coefficients": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        }
    ),
    _magnitude_probe(
        {
            "form": "exponential",
            "input": {"attr": "power"},
            "coefficient": 1,
            "growth_rate": 0,
        }
    ),
    _magnitude_probe(_unary_chain(33)),
    _magnitude_probe({"op": "add", "args": [{"literal": 1} for _ in range(256)]}),
    _magnitude_probe({"op": "add", "args": [{"attr": "ghost"}, {"literal": 1}]}),
    _magnitude_probe({"op": "add", "args": [{"param": "ghost"}, {"literal": 1}]}),
]


def test_every_emitted_refusal_path_matches_a_scope_template(run_cli, tmp_path) -> None:
    """Every refusal the funnel emits over the corpus is matched by one of its
    rule's scope templates (see the contract note above). The corpus is each
    rule's own violation fixture (the attribute-base and effect sites) plus the
    magnitude probes (the `.../magnitude` sites the shared formula rules gained
    in #527). This is the behavioral half of the catalog contract: byte-identity
    pins WHAT the templates are, this pins that they describe where refusals
    actually land."""
    rules_by_code = {rule.code: rule for rule in SEMANTIC_RULES}
    corpus = [rule.violation_fixture for rule in SEMANTIC_RULES] + _MAGNITUDE_PROBES
    doc_path = tmp_path / "doc.json"
    for document in corpus:
        doc_path.write_text(json.dumps(document), encoding="utf-8")
        exit_code, stdout, stderr = run_cli(["design", "validate", str(doc_path)])
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
