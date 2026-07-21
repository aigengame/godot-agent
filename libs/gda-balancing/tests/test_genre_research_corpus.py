"""Structural checks for the non-authoritative Schema 2.0 research corpus."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "schema2-genre-conformance"


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_research_schemas_are_valid_draft_2020_12() -> None:
    for name in ("corpus.schema.json", "findings.schema.json"):
        Draft202012Validator.check_schema(_load(RESEARCH / name))


def test_every_research_instance_conforms_to_shared_contracts() -> None:
    corpus_validator = Draft202012Validator(_load(RESEARCH / "corpus.schema.json"))
    findings_validator = Draft202012Validator(_load(RESEARCH / "findings.schema.json"))

    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        findings = _load(game_dir / "findings.json")
        corpus_validator.validate(corpus)
        findings_validator.validate(findings)
        assert corpus["game"]["id"] == game_dir.name
        assert findings["game_id"] == game_dir.name
