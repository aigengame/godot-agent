"""The `template` command group and the Genre-template contract (bADR-0012).

Covers the #505 surface in layers: the ``meta.genre`` lineage field on the
document envelope, then the ``template list`` / ``template get`` commands and
the shipped RPG template's own validity and canonical-bytes discipline.
"""

import json
from collections.abc import Callable
from pathlib import Path

RunResult = tuple[int, str, str]


def _genre_document(minimal_design_path: Path) -> dict[str, object]:
    document = json.loads(minimal_design_path.read_text(encoding="utf-8"))
    meta = document["meta"]
    assert isinstance(meta, dict)
    meta["genre"] = {"family": "rpg", "variant": "crpg"}
    return document


class TestMetaGenreLineage:
    """The optional, purely descriptive ``meta.genre`` field (bADR-0001's
    genre lineage, landed by #505)."""

    def test_document_with_genre_lineage_validates(
        self,
        run_cli: Callable[..., RunResult],
        minimal_design_path: Path,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "genre.json"
        path.write_text(json.dumps(_genre_document(minimal_design_path)))
        code, out, _ = run_cli(["design", "validate", str(path)])
        assert code == 0, out
        assert json.loads(out) == {"valid": True}

    def test_genre_lineage_round_trips_through_format(
        self,
        run_cli: Callable[..., RunResult],
        minimal_design_path: Path,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "genre.json"
        path.write_text(json.dumps(_genre_document(minimal_design_path)))
        code, out, _ = run_cli(["design", "format", str(path)])
        assert code == 0, out
        assert json.loads(out)["meta"]["genre"] == {
            "family": "rpg",
            "variant": "crpg",
        }

    def test_genre_lineage_unknown_subkey_is_refused(
        self,
        run_cli: Callable[..., RunResult],
        minimal_design_path: Path,
        tmp_path: Path,
    ) -> None:
        document = _genre_document(minimal_design_path)
        meta = document["meta"]
        assert isinstance(meta, dict)
        meta["genre"]["era"] = "golden"
        path = tmp_path / "genre.json"
        path.write_text(json.dumps(document))
        code, out, _ = run_cli(["design", "validate", str(path)])
        assert code == 2
        refusals = json.loads(out)["error"]["refusals"]
        assert {r["code"] for r in refusals} == {"structural_violation"}
        assert refusals[0]["path"] == "/meta/genre/era"
