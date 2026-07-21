"""Structural checks for the non-authoritative Schema 2.0 research corpus."""

from __future__ import annotations

import csv
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError


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
PRIMARY_OBSERVATION_KINDS = {"shipped_data", "runtime_observation"}


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


def _assert_oracle_provenance(corpus: dict[str, Any]) -> None:
    source_by_id = {source["id"]: source for source in corpus["sources"]}
    for mechanic in corpus["mechanics"]:
        for oracle in mechanic["oracle_vectors"]:
            evidence_refs = oracle["evidence_refs"]
            flattened_refs = [
                source_id
                for authority_domain in (
                    "external_game",
                    "research_synthesis",
                    "schema_contract",
                )
                for source_id in evidence_refs[authority_domain]
            ]
            assert len(flattened_refs) == len(set(flattened_refs)), (
                f"{oracle['id']} repeats a source across authority domains"
            )
            for authority_domain, source_refs in evidence_refs.items():
                for source_id in source_refs:
                    assert source_id in source_by_id, (
                        f"{oracle['id']} references unknown source {source_id}"
                    )
                    assert (
                        source_by_id[source_id]["authority_domain"] == authority_domain
                    ), (
                        f"{oracle['id']} puts {source_id} in {authority_domain}, but the source "
                        f"belongs to {source_by_id[source_id]['authority_domain']}"
                    )

            claim_status = oracle["claim_status"]
            external_sources = [
                source_by_id[source_id] for source_id in evidence_refs["external_game"]
            ]
            if claim_status == "candidate":
                assert oracle["claim_subject"] == "game_mapping"
                assert external_sources or evidence_refs["research_synthesis"]
            elif claim_status == "corroborated":
                assert oracle["claim_subject"] == "game_mapping"
                assert any(
                    source["confidence"] in {"primary", "corroborated"}
                    for source in external_sources
                ), f"{oracle['id']} has no non-provisional external-game evidence"
            elif claim_status == "observed":
                assert oracle["claim_subject"] == "game_mapping"
                assert any(
                    source["confidence"] == "primary"
                    and source["kind"] in PRIMARY_OBSERVATION_KINDS
                    for source in external_sources
                ), f"{oracle['id']} has no primary shipped-data/runtime observation"
            else:
                assert claim_status == "contractual"
                assert oracle["claim_subject"] == "schema_boundary"
                assert evidence_refs["schema_contract"], (
                    f"{oracle['id']} has no Schema-contract evidence"
                )


def _validate_corpus(corpus: dict[str, Any]) -> None:
    Draft202012Validator(_load(RESEARCH / "corpus.schema.json")).validate(corpus)
    _assert_oracle_provenance(corpus)


def test_research_schemas_are_valid_draft_2020_12() -> None:
    for name in ("corpus.schema.json", "findings.schema.json"):
        Draft202012Validator.check_schema(_load(RESEARCH / name))


def test_authoritative_coverage_ids_are_accepted_by_research_contract() -> None:
    coverage_ids = _coverage_ids()
    assert len(coverage_ids) == 32
    assert all(COVERAGE_ID_PATTERN.fullmatch(item) for item in coverage_ids)
    assert "RPG-TURN-SPATIAL-01" in coverage_ids
    assert "RPG-DECISION-INTENT-01" in coverage_ids
    assert "ROGUE-DECK-ZONE-01" in coverage_ids


def test_authoritative_operation_ids_are_accepted_by_research_contract() -> None:
    operation_ids = _operation_ids()
    assert len(operation_ids) == 43
    assert all(OPERATION_ID_PATTERN.fullmatch(item) for item in operation_ids)
    assert "game.spatial.query@1" in operation_ids
    assert "game.collection.move@1" in operation_ids
    assert "game.decision.plan@1" in operation_ids


def test_every_research_instance_conforms_to_shared_contracts() -> None:
    findings_validator = Draft202012Validator(_load(RESEARCH / "findings.schema.json"))

    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        findings = _load(game_dir / "findings.json")
        assert isinstance(corpus, dict)
        assert isinstance(findings, dict)
        _validate_corpus(corpus)
        findings_validator.validate(findings)
        assert corpus["game"]["id"] == game_dir.name
        assert findings["game_id"] == game_dir.name


def test_research_permanent_operation_refs_are_authoritative() -> None:
    operation_ids = _operation_ids()
    for game_dir in sorted((RESEARCH / "games").glob("*")):
        if not game_dir.is_dir():
            continue
        corpus = _load(game_dir / "corpus.json")
        for mechanic in corpus["mechanics"]:
            permanent_refs = {
                operation["id"]
                for operation in mechanic["operations"]
                if "@" in operation["id"]
            }
            assert permanent_refs <= operation_ids


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
            assert all(
                oracle["conformance_effect"] == "does_not_close_coverage"
                for oracle in mechanic["oracle_vectors"]
            )

        assert {finding["mechanic_id"] for finding in finding_rows} == mechanic_ids
        for finding in finding_rows:
            assert set(finding["affected_coverage_rows"]) <= coverage_ids


def test_oracle_rejects_source_assigned_to_the_wrong_authority_domain() -> None:
    corpus = _load(RESEARCH / "games" / "vampire-survivors" / "corpus.json")
    oracle = corpus["mechanics"][0]["oracle_vectors"][0]
    source_id = oracle["evidence_refs"]["schema_contract"].pop()
    oracle["evidence_refs"]["external_game"].append(source_id)

    with pytest.raises(AssertionError, match="belongs to schema_contract"):
        _validate_corpus(corpus)


def test_schema_contract_cannot_promote_provisional_game_evidence() -> None:
    corpus = _load(RESEARCH / "games" / "vampire-survivors" / "corpus.json")
    oracle = corpus["mechanics"][0]["oracle_vectors"][0]
    assert oracle["claim_status"] == "candidate"
    oracle["claim_status"] = "corroborated"

    with pytest.raises(
        AssertionError, match="no non-provisional external-game evidence"
    ):
        _validate_corpus(corpus)


def test_oracle_rejects_omitted_explicit_claim_status() -> None:
    corpus = _load(RESEARCH / "games" / "vampire-survivors" / "corpus.json")
    del corpus["mechanics"][0]["oracle_vectors"][0]["claim_status"]

    with pytest.raises(ValidationError):
        _validate_corpus(corpus)


def test_schema_boundary_requires_schema_contract_evidence() -> None:
    corpus = _load(RESEARCH / "games" / "vampire-survivors" / "corpus.json")
    oracle = deepcopy(corpus["mechanics"][0]["oracle_vectors"][1])
    assert oracle["claim_subject"] == "schema_boundary"
    oracle["evidence_refs"]["schema_contract"] = []
    corpus["mechanics"][0]["oracle_vectors"][1] = oracle

    with pytest.raises(ValidationError):
        _validate_corpus(corpus)


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
