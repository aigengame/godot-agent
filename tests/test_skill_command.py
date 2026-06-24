"""`gda skill` — emit / install the bundled Agent Skill (issue #266, ADR-0024).

`gda skill` is a pure local emitter meta command: it reads the in-package
`SKILL.md` and emits or installs it, spawning no Godot. These are unit tests only
(no engine), exercising the four surfaces — plain text, `--json`, `--schema`,
`--install` — plus the packaging guarantee that the manifest ships in the wheel.
"""

import json
import zipfile
from importlib.metadata import version as package_version
from pathlib import Path

import jsonschema
from typer.testing import CliRunner

from gda.cli import app
from gda.models import GdaErrorEnvelope, SkillParams, SkillResult
from gda.skill_ops import SKILL_MD, read_skill_text

BUNDLED = read_skill_text()


def test_skill_prints_the_raw_manifest_text():
    # The default (human) render prints the raw SKILL.md verbatim so
    # `gda skill > .../SKILL.md` drops the manifest straight to disk.
    result = CliRunner().invoke(app, ["skill"])

    assert result.exit_code == 0
    assert result.stdout.startswith("---")
    assert "name: gda" in result.stdout
    # The full body — not just the frontmatter — is emitted.
    assert "## Grammar" in result.stdout


def test_skill_json_emits_name_version_content():
    result = CliRunner().invoke(app, ["skill", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data) >= {"name", "version", "content"}
    assert data["name"] == "gda"
    # The version is read from the installed distribution metadata, so the
    # guidance is version-locked to the CLI it describes (ADR-0024).
    assert data["version"] == package_version("gda")
    # `content` is the full manifest, frontmatter included.
    assert data["content"].startswith("---")
    assert "name: gda" in data["content"]
    assert data["content"] == BUNDLED
    # A plain emit reports no install path.
    assert data.get("installed_path") is None


def test_skill_json_content_round_trips_the_bundled_file():
    data = json.loads(CliRunner().invoke(app, ["skill", "--json"]).stdout)
    assert data["content"] == SKILL_MD.read_text(encoding="utf-8")


def test_skill_description_is_within_the_skill_frontmatter_limit():
    # An Agent Skill `description` is the one thing an agent sees when deciding to
    # load the Skill; the SKILL.md spec caps it at 1024 chars.
    front = BUNDLED.split("---", 2)[1]
    description = ""
    for line in front.splitlines():
        if line.startswith("description:"):
            description = line[len("description:") :].strip()
            break
    assert description, "the SKILL.md frontmatter must carry a description"
    assert len(description) <= 1024


def test_skill_schema_emits_valid_input_output_error_schemas():
    result = CliRunner().invoke(app, ["skill", "--schema"])

    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert set(doc) >= {"input", "output", "error"}
    # Model-derived, like every meta command (ADR-0004).
    assert doc["input"] == SkillParams.model_json_schema()
    assert doc["output"] == SkillResult.model_json_schema()
    assert doc["error"] == GdaErrorEnvelope.model_json_schema()
    # Each half is itself well-formed JSON Schema.
    jsonschema.Draft202012Validator.check_schema(doc["input"])
    jsonschema.Draft202012Validator.check_schema(doc["output"])
    jsonschema.Draft202012Validator.check_schema(doc["error"])


def test_skill_schema_reports_kind_headless():
    # `skill` spawns no Godot but is not a live command; it carries the default
    # HEADLESS channel in its self-description.
    doc = json.loads(CliRunner().invoke(app, ["skill", "--schema"]).stdout)
    assert doc["kind"] == "headless"


def test_skill_sample_result_validates_against_emitted_output_schema():
    output_schema = json.loads(
        CliRunner().invoke(app, ["skill", "--schema"]).stdout
    )["output"]
    sample = json.loads(CliRunner().invoke(app, ["skill", "--json"]).stdout)
    jsonschema.validate(instance=sample, schema=output_schema)


def test_skill_install_writes_the_manifest_into_the_target_dir(tmp_path):
    result = CliRunner().invoke(app, ["skill", "--install", "--dir", str(tmp_path)])

    assert result.exit_code == 0
    written = tmp_path / "SKILL.md"
    assert written.is_file()
    # The written file round-trips the bundled manifest byte for byte.
    assert written.read_text(encoding="utf-8") == BUNDLED
    # The human render names the path it wrote.
    assert str(written) in result.stdout


def test_skill_install_json_reports_the_written_path(tmp_path):
    result = CliRunner().invoke(
        app, ["skill", "--install", "--dir", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["installed_path"] == str(tmp_path / "SKILL.md")
    assert data["name"] == "gda"
    assert data["content"] == BUNDLED


def test_skill_dir_implies_install(tmp_path):
    # Naming a target directory means "install there" — no separate --install flag.
    result = CliRunner().invoke(app, ["skill", "--dir", str(tmp_path), "--json"])

    assert result.exit_code == 0
    assert (tmp_path / "SKILL.md").is_file()
    assert json.loads(result.stdout)["installed_path"] == str(tmp_path / "SKILL.md")


def test_skill_install_creates_missing_parent_dirs(tmp_path):
    nested = tmp_path / "a" / "b" / "gda"
    result = CliRunner().invoke(app, ["skill", "--install", "--dir", str(nested)])

    assert result.exit_code == 0
    assert (nested / "SKILL.md").read_text(encoding="utf-8") == BUNDLED


def test_skill_install_overwrites_an_existing_file(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("stale content", encoding="utf-8")

    result = CliRunner().invoke(app, ["skill", "--install", "--dir", str(tmp_path)])

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == BUNDLED


def test_skill_spawns_no_godot(monkeypatch):
    # `skill` is a pure local emitter: it must never reach the engine path, even
    # when binary resolution and the runner are rigged to explode.
    def boom(*args, **kwargs):
        raise AssertionError("gda skill must not touch the engine")

    monkeypatch.setattr("gda.headless.resolve_godot_binary", boom)
    monkeypatch.setattr("gda.cli._make_runner", boom)

    result = CliRunner().invoke(app, ["skill", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["name"] == "gda"


def test_skill_params_json_drives_the_same_path(tmp_path):
    # gda-mcp forwards an MCP tool's input object verbatim via --params-json
    # (ADR-0015); it must drive the SAME outcome as the argv flags.
    result = CliRunner().invoke(
        app,
        [
            "skill",
            "--params-json",
            json.dumps({"install": True, "install_dir": str(tmp_path)}),
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["installed_path"] == str(tmp_path / "SKILL.md")
    assert (tmp_path / "SKILL.md").read_text(encoding="utf-8") == BUNDLED


# --- packaging: the bundled SKILL.md must resolve at runtime AND ship in the wheel ---


def test_bundled_skill_resolves_at_runtime():
    # The manifest is resolved package-relative (like operations.gd), so it is
    # present both in a source checkout and an installed wheel.
    assert SKILL_MD.is_file()
    assert SKILL_MD.name == "SKILL.md"
    assert SKILL_MD.parent.name == "skill"
    assert SKILL_MD.read_text(encoding="utf-8").startswith("---")


def test_bundled_skill_is_included_in_the_built_wheel():
    # The wheel must carry the manifest under gda/skill/SKILL.md, the same way it
    # carries the GDScript payload — otherwise an installed `gda skill` would have
    # nothing to emit. Skipped (not failed) when no wheel has been built yet, so
    # the suite stays runnable without a build step; CI builds and runs it.
    import pytest

    repo_root = Path(__file__).resolve().parents[1]
    wheels = sorted((repo_root / "dist").glob("gda-*.whl"))
    if not wheels:
        pytest.skip("no built wheel in dist/ — run `uv build` first")
    newest = wheels[-1]
    with zipfile.ZipFile(newest) as zf:
        names = zf.namelist()
    assert any(
        name.endswith("gda/skill/SKILL.md") for name in names
    ), f"gda/skill/SKILL.md missing from {newest.name}: {names}"
