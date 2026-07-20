"""The `template` command group and the Genre-template contract (bADR-0012).

Covers the #505 surface in layers: the ``meta.genre`` lineage field on the
document envelope, then the ``template list`` / ``template get`` commands and
the shipped RPG template's own validity and canonical-bytes discipline.
"""

import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import get_args

RunResult = tuple[int, str, str]


def _template_bytes() -> bytes:
    """The committed RPG Genre template — the packaged single authority."""
    return (resources.files("gda_balancing.templates") / "rpg.json").read_bytes()


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


class TestTemplateCommands:
    """`template list` / `template get` (bADR-0007's template group; the
    instantiation shape decided by bADR-0012: get *is* instantiate)."""

    def test_template_list_names_the_rpg_template(
        self, run_cli: Callable[..., RunResult]
    ) -> None:
        code, out, _ = run_cli(["template", "list"])
        assert code == 0, out
        entries = json.loads(out)["templates"]
        rpg = next(e for e in entries if e["id"] == "rpg")
        assert rpg["summary"]

    def test_template_get_emits_the_committed_bytes(
        self, run_cli: Callable[..., RunResult]
    ) -> None:
        code, out, _ = run_cli(["template", "get", "rpg"])
        assert code == 0, out
        assert out.encode("utf-8") == _template_bytes()

    def test_template_get_unknown_id_is_a_usage_error(
        self, run_cli: Callable[..., RunResult]
    ) -> None:
        code, _, err = run_cli(["template", "get", "unheard_of"])
        assert code == 3
        assert json.loads(err)["error"]["category"] == "usage"

    def test_template_ids_have_one_authority(self) -> None:
        """The Literal contract, the summary registry, and the packaged
        resources name the same template set (bADR-0012)."""
        from gda_balancing.commands.template import _TEMPLATES, TemplateGetInput

        annotation = TemplateGetInput.model_fields["template"].annotation
        assert set(_TEMPLATES) == set(get_args(annotation))
        for template_id in _TEMPLATES:
            resource = resources.files("gda_balancing.templates").joinpath(
                f"{template_id}.json"
            )
            assert resource.is_file(), template_id


class TestShippedRpgTemplate:
    """The RPG family Genre template itself — a plain Standard Schema
    instance (AC1), canonical-committed, declaring the bADR-0002 tiers."""

    def test_rpg_template_validates_as_a_plain_schema_instance(
        self, run_cli: Callable[..., RunResult], tmp_path: Path
    ) -> None:
        path = tmp_path / "rpg.json"
        path.write_bytes(_template_bytes())
        code, out, _ = run_cli(["design", "validate", str(path)])
        assert code == 0, out
        assert json.loads(out) == {"valid": True}

    def test_rpg_template_is_committed_in_canonical_form(
        self, run_cli: Callable[..., RunResult], tmp_path: Path
    ) -> None:
        """`design format` of the committed bytes is the committed bytes —
        which also makes `template get` ≡ `design format` (both emit the same
        canonical dump of the same document)."""
        path = tmp_path / "rpg.json"
        path.write_bytes(_template_bytes())
        code, out, _ = run_cli(["design", "format", str(path)])
        assert code == 0, out
        assert out.encode("utf-8") == _template_bytes()

    def test_rpg_template_declares_the_family_tier_vocabulary(self) -> None:
        document = json.loads(_template_bytes())
        tiers = document["attributes"]["tiers"]
        assert set(tiers) == {"primary", "derived", "tertiary"}
        assert tiers["primary"] == {
            "domain": "number",
            "base": "direct",
            "accepts": ["allocation", "effects"],
        }
        assert tiers["derived"] == {
            "domain": "number",
            "base": "formula",
            "accepts": ["effects"],
        }
        assert tiers["tertiary"] == {"accepts": ["effects"]}
        items = document["attributes"]["items"]
        by_tier: dict[str, list[str]] = {}
        for attr_id, attribute in items.items():
            by_tier.setdefault(attribute.get("tier", ""), []).append(attr_id)
        assert len(by_tier.get("primary", [])) >= 4
        assert len(by_tier.get("derived", [])) >= 4
        assert len(by_tier.get("tertiary", [])) >= 2

    def test_rpg_template_genre_lineage_and_schema_ref(self) -> None:
        document = json.loads(_template_bytes())
        assert document["meta"]["genre"] == {"family": "rpg"}
        assert document["$schema"] == "urn:gda-balancing:standard-schema:1.0.0"

    def test_rpg_template_knobs_are_parameters_not_literals(self) -> None:
        """Every declared parameter is referenced by some formula or effect
        magnitude — parameters are the sole tuning knobs (bADR-0003), so an
        unreferenced one would be a dead knob."""
        document = json.loads(_template_bytes())

        def param_refs(node: object) -> set[str]:
            refs: set[str] = set()
            if isinstance(node, dict):
                if set(node) == {"param"} and isinstance(node["param"], str):
                    refs.add(node["param"])
                for value in node.values():
                    refs |= param_refs(value)
            elif isinstance(node, list):
                for value in node:
                    refs |= param_refs(value)
            return refs

        referenced = param_refs([document["attributes"], document["effects"]])
        assert set(document["parameters"]) == referenced
