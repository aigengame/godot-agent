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
import pytest
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


def test_skill_ignores_an_invalid_inherited_gda_project(tmp_path, monkeypatch):
    # `gda skill` is a projectless meta emitter (ADR-0024): it reads the bundled
    # SKILL.md and never resolves a Godot project. An inherited $GDA_PROJECT that
    # is not a project must NOT make it fail — it stays projectless, unlike the
    # project-using recipes that structure an invalid --project as project_not_found
    # (#353). Guards against the shared-resolver refactor over-reaching to meta.
    not_a_project = tmp_path / "not-a-godot-project"
    not_a_project.mkdir()
    monkeypatch.setenv("GDA_PROJECT", str(not_a_project))

    result = CliRunner().invoke(app, ["skill", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["name"] == "gda"


def test_skill_json_content_round_trips_the_bundled_file():
    data = json.loads(CliRunner().invoke(app, ["skill", "--json"]).stdout)
    assert data["content"] == SKILL_MD.read_text(encoding="utf-8")


def test_skill_documents_json_container_number_preservation():
    # #427: the packaged gda skill is the agent-facing command catalog, so it
    # must teach the same Dictionary/Array JSON number rule that --schema exposes.
    lower = BUNDLED.lower()
    assert "json integer" in lower
    assert "json float" in lower


def test_skill_documents_script_validate_valid_verdict():
    # #463: `script validate` reports a compile failure as a success-shaped
    # result, so the agent-facing Skill must teach agents to inspect `valid`.
    assert "gda script validate --json" in BUNDLED
    assert "valid=false" in BUNDLED
    assert "top-level `error`" in BUNDLED


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
    output_schema = json.loads(CliRunner().invoke(app, ["skill", "--schema"]).stdout)[
        "output"
    ]
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


def test_skill_install_without_dir_is_a_usage_error():
    # ADR-0024: core has no default skills dir; --install requires an explicit --dir,
    # so an install with no target is rejected (a non-zero usage exit; the exact
    # error rendering/stream varies by tty width, so assert on the exit code).
    result = CliRunner().invoke(app, ["skill", "--install"])

    assert result.exit_code != 0
    # Nothing was written: a plain `gda skill` (no install) still succeeds.
    assert CliRunner().invoke(app, ["skill"]).exit_code == 0


def test_skill_build_result_install_without_dir_raises():
    # The core backstop behind the CLI guard: no default install location.
    from gda.skill_ops import build_skill_result

    with pytest.raises(ValueError):
        build_skill_result(install=True, install_dir=None)


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


def test_skill_params_json_dir_alone_installs(tmp_path):
    # ADR-0015 parity: install_dir alone (no explicit install) installs, exactly as
    # argv `--dir` does — the model normalizes both to the same params.
    result = CliRunner().invoke(
        app,
        [
            "skill",
            "--params-json",
            json.dumps({"install_dir": str(tmp_path)}),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["installed_path"] == str(tmp_path / "SKILL.md")
    assert (tmp_path / "SKILL.md").is_file()


# --- packaging: the bundled SKILL.md must resolve at runtime AND ship in the wheel ---


def test_bundled_skill_resolves_at_runtime():
    # The manifest is resolved package-relative (like operations.gd), so it is
    # present both in a source checkout and an installed wheel.
    assert SKILL_MD.is_file()
    assert SKILL_MD.name == "SKILL.md"
    assert SKILL_MD.parent.name == "skill"
    assert SKILL_MD.read_text(encoding="utf-8").startswith("---")


def test_bundled_skill_is_included_in_the_built_wheel(tmp_path):
    # The wheel must carry the manifest under gda/skill/SKILL.md, the same way it
    # carries the GDScript payload — otherwise an installed `gda skill` would have
    # nothing to emit. Build a wheel on demand (into a tmp dir) so this actually GATES
    # in PR CI regardless of whether `uv build` has run yet — it does not depend on dist/.
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wheels = sorted(tmp_path.glob("gda-*.whl"))
    assert wheels, f"no wheel built:\n{proc.stdout}{proc.stderr}"
    with zipfile.ZipFile(wheels[-1]) as zf:
        names = zf.namelist()
    assert any(name.endswith("gda/skill/SKILL.md") for name in names), (
        f"gda/skill/SKILL.md missing from {wheels[-1].name}: {names}"
    )


# --- `--provider`/`--scope` convenience install (ADR-0027) -------------------------
#
# `gda skill --install --provider <agent> --scope <scope>` resolves a known agent's
# skills directory and reuses the same `--dir` install path. Project scope is exercised
# in a tmp CWD; user scope is asserted via the resolution table and a HOME-pinned run, so
# CI never writes into the real home directory.

from gda.skill_targets import (  # noqa: E402  (grouped with the feature it tests)
    PROVIDER_SKILL_DIRS,
    SkillProvider,
    SkillScope,
    resolve_skill_dir,
)


@pytest.mark.parametrize(
    "provider, scope, expected",
    [
        (SkillProvider.CLAUDE, SkillScope.PROJECT, ".claude/skills/gda"),
        (SkillProvider.CLAUDE, SkillScope.USER, "~/.claude/skills/gda"),
        (SkillProvider.CODEX, SkillScope.PROJECT, ".agents/skills/gda"),
        (SkillProvider.CODEX, SkillScope.USER, "~/.agents/skills/gda"),
    ],
)
def test_resolve_skill_dir_maps_every_provider_scope(provider, scope, expected):
    # The known-agent table covers all four combos and matches docs/gda-skill.md; user
    # scope is asserted here WITHOUT touching the real HOME. Codex uses the cross-agent
    # `.agents/skills` namespace (OpenAI Codex docs), not `.codex/skills`.
    assert resolve_skill_dir(provider, scope) == expected
    assert PROVIDER_SKILL_DIRS[provider][scope] == expected


def test_skill_install_provider_claude_project_writes_into_dot_claude(
    tmp_path, monkeypatch
):
    # `--provider claude --scope project` resolves to `.claude/skills/gda`, relative to
    # the CWD — install it into a tmp project dir.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["skill", "--install", "--provider", "claude", "--scope", "project"]
    )

    assert result.exit_code == 0
    written = tmp_path / ".claude" / "skills" / "gda" / "SKILL.md"
    assert written.read_text(encoding="utf-8") == BUNDLED


def test_skill_install_provider_codex_project_uses_agents_namespace(
    tmp_path, monkeypatch
):
    # Codex follows the cross-agent `.agents/skills` namespace, NOT `.codex/skills`.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["skill", "--install", "--provider", "codex", "--scope", "project"]
    )

    assert result.exit_code == 0
    written = tmp_path / ".agents" / "skills" / "gda" / "SKILL.md"
    assert written.read_text(encoding="utf-8") == BUNDLED


def test_skill_provider_implies_install_and_defaults_to_user_scope(
    tmp_path, monkeypatch
):
    # Naming a provider implies an install (like --dir does), and --scope defaults to
    # user — under HOME. Pin HOME at a tmp dir so we never touch the real one.
    monkeypatch.setenv("HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["skill", "--provider", "claude", "--json"])

    assert result.exit_code == 0
    written = tmp_path / ".claude" / "skills" / "gda" / "SKILL.md"
    assert written.read_text(encoding="utf-8") == BUNDLED
    assert json.loads(result.stdout)["installed_path"] == str(written)


def test_skill_dir_and_provider_are_mutually_exclusive(tmp_path):
    # --dir and --provider name the SAME target two ways; giving both is ambiguous.
    result = CliRunner().invoke(
        app, ["skill", "--dir", str(tmp_path), "--provider", "claude"]
    )

    assert result.exit_code != 0
    assert not (tmp_path / "SKILL.md").exists()


def test_skill_unknown_provider_is_a_usage_error():
    # A closed enum: an unlisted agent is rejected, not guessed (it falls back to --dir).
    result = CliRunner().invoke(app, ["skill", "--provider", "gemini"])

    assert result.exit_code != 0


def test_skill_provider_params_json_drives_the_same_resolution(tmp_path, monkeypatch):
    # ADR-0015: --params-json resolves provider/scope identically to the argv flags.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "skill",
            "--params-json",
            json.dumps({"provider": "claude", "scope": "project"}),
            "--json",
        ],
    )

    assert result.exit_code == 0
    written = tmp_path / ".claude" / "skills" / "gda" / "SKILL.md"
    assert written.read_text(encoding="utf-8") == BUNDLED
    # Project scope resolves to a CWD-relative dir, so the reported path is relative —
    # consistent with how a relative `--dir` already behaves.
    assert json.loads(result.stdout)["installed_path"] == ".claude/skills/gda/SKILL.md"


def test_skill_params_provider_and_dir_conflict_raises():
    # The core backstop behind the CLI guard: provider and install_dir are exclusive.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SkillParams(provider=SkillProvider.CLAUDE, install_dir="/tmp/x")


def test_skill_schema_input_constrains_provider_and_scope():
    # provider/scope become first-class params, so the input schema gains enum-constrained
    # fields and gda-mcp generates a closed-choice tool (ADR-0012). The enum may render via
    # $defs/$ref, so assert the constrained values appear in the input schema blob.
    doc = json.loads(CliRunner().invoke(app, ["skill", "--schema"]).stdout)
    props = doc["input"]["properties"]
    assert "provider" in props and "scope" in props
    blob = json.dumps(doc["input"])
    assert "claude" in blob and "codex" in blob
    assert "project" in blob and "user" in blob
