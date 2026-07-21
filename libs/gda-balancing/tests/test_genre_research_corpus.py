"""Structural checks for the non-authoritative Schema 2.0 research corpus."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "schema2-genre-conformance"
COVERAGE = ROOT / "docs" / "standard-schema-2.0" / "genre-coverage.md"
QUANTITY_COLUMNS = (
    "mechanic_id",
    "id",
    "representation",
    "kind",
    "unit",
    "role",
    "domain",
    "rounding",
    "cap",
    "source_refs",
)
COVERAGE_ID_PATTERN = re.compile(r"^(?:RPG|ROGUE)-[A-Z]+(?:-[A-Z]+)*-[0-9]{2}$")
OPERATION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]*(?:@[0-9]+)?$")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_unique(records: list[dict[str, Any]], field: str, label: str) -> None:
    values = [record[field] for record in records]
    assert len(values) == len(set(values)), f"duplicate {label}: {values}"


def _coverage_ids() -> frozenset[str]:
    return frozenset(
        re.findall(
            r"`((?:RPG|ROGUE)-[A-Z]+(?:-[A-Z]+)*-[0-9]{2})`",
            COVERAGE.read_text(),
        )
    )


def _operation_ids() -> frozenset[str]:
    return frozenset(re.findall(r"`([a-z][a-z0-9._-]*@[0-9]+)`", COVERAGE.read_text()))


def _quantity_rows(corpus: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for mechanic in corpus["mechanics"]:
        for quantity in mechanic["quantities"]:
            rows.append(
                {
                    "mechanic_id": mechanic["id"],
                    "id": quantity["id"],
                    "representation": quantity["representation"],
                    "kind": quantity["kind"],
                    "unit": quantity["unit"] or "",
                    "role": quantity["role"],
                    "domain": quantity["domain"],
                    "rounding": quantity["rounding"] or "",
                    "cap": quantity["cap"] or "",
                    "source_refs": ";".join(sorted(quantity["source_refs"])),
                }
            )
    return sorted(rows, key=lambda row: (row["mechanic_id"], row["id"]))


def test_research_schemas_are_valid_draft_2020_12() -> None:
    for name in ("corpus.schema.json", "findings.schema.json"):
        Draft202012Validator.check_schema(_load(RESEARCH / name))


def test_authoritative_coverage_ids_are_accepted_by_research_contract() -> None:
    coverage_ids = _coverage_ids()
    assert len(coverage_ids) == 30
    assert all(COVERAGE_ID_PATTERN.fullmatch(item) for item in coverage_ids)
    assert "RPG-TURN-SPATIAL-01" in coverage_ids


def test_authoritative_operation_ids_are_accepted_by_research_contract() -> None:
    operation_ids = _operation_ids()
    assert len(operation_ids) == 36
    assert all(OPERATION_ID_PATTERN.fullmatch(item) for item in operation_ids)
    assert "game.spatial.query@1" in operation_ids


def test_every_research_instance_conforms_to_shared_contracts() -> None:
    corpus_validator = Draft202012Validator(_load(RESEARCH / "corpus.schema.json"))
    findings_validator = Draft202012Validator(_load(RESEARCH / "findings.schema.json"))

    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        findings = _load(game_dir / "findings.json")
        assert isinstance(corpus, dict)
        assert isinstance(findings, dict)
        corpus_validator.validate(corpus)
        findings_validator.validate(findings)
        assert corpus["game"]["id"] == game_dir.name
        assert findings["game_id"] == game_dir.name


def test_research_references_and_oracles_are_closed() -> None:
    coverage_ids = _coverage_ids()
    assert coverage_ids
    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        findings = _load(game_dir / "findings.json")
        assert isinstance(corpus, dict)
        assert isinstance(findings, dict)

        sources = corpus["sources"]
        mechanics = corpus["mechanics"]
        finding_rows = findings["findings"]
        _assert_unique(sources, "id", "source id")
        _assert_unique(mechanics, "id", "mechanic id")
        _assert_unique(finding_rows, "id", "finding id")
        source_by_id = {source["id"]: source for source in sources}
        mechanic_ids = {mechanic["id"] for mechanic in mechanics}

        for mechanic in mechanics:
            assert set(mechanic["coverage_rows"]) <= coverage_ids
            assert set(mechanic["source_refs"]) <= set(source_by_id)
            _assert_unique(
                mechanic["quantities"], "id", f"{mechanic['id']} quantity id"
            )
            _assert_unique(mechanic["state_slots"], "id", f"{mechanic['id']} state id")
            _assert_unique(
                mechanic["operations"], "id", f"{mechanic['id']} operation id"
            )
            _assert_unique(
                mechanic["oracle_vectors"], "id", f"{mechanic['id']} oracle id"
            )
            kinds = {oracle["kind"] for oracle in mechanic["oracle_vectors"]}
            assert "positive" in kinds, f"{mechanic['id']} has no positive oracle"
            assert kinds - {"positive"}, f"{mechanic['id']} has no non-positive oracle"
            for record in [
                *mechanic["quantities"],
                *mechanic["state_slots"],
                *mechanic["operations"],
            ]:
                assert set(record["source_refs"]) <= set(source_by_id)
            for oracle in mechanic["oracle_vectors"]:
                assert set(oracle["source_refs"]) <= set(source_by_id)
                assert any(
                    source_by_id[source_id]["confidence"] != "provisional"
                    for source_id in oracle["source_refs"]
                ), f"{oracle['id']} relies only on provisional sources"

        assert {finding["mechanic_id"] for finding in finding_rows} == mechanic_ids
        for finding in finding_rows:
            assert set(finding["affected_coverage_rows"]) <= coverage_ids


def test_quantity_csv_is_an_exact_sorted_projection() -> None:
    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        assert isinstance(corpus, dict)
        with (game_dir / "quantities.csv").open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert tuple(reader.fieldnames or ()) == QUANTITY_COLUMNS
            actual = list(reader)
        assert actual == _quantity_rows(corpus)
