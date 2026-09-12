"""A case-mismatched path is refused by the path authority, on every platform (#845).

Dogfooding GDA-DF-062: ``gda script validate res://Content/combat_session.gd``
returned ``valid: true`` on macOS while the tracked file is ``res://content/…``.
Godot opened the file (APFS is case-insensitive by default) and warned that the
same path will not open on a case-sensitive platform, but the warning is a
``WARN_PRINT`` the script-error classifier skips by contract, so a portability gate
passed a path that fails on Linux and on a case-sensitive export host.

gda now decides the spelling itself, at ADR-0006's path authority
(:func:`gda.project.case_mismatch`) and through the ONE containment gate
(:func:`gda.errors.containment_refusal`), so the three commands the gate protects —
``script validate``, ``script run``, ``resource import`` — all report the typed
``path_case_mismatch``. The rest of the surface is deliberately untouched: it hands
the ``res://`` string to the engine and never consults the authority for a target
(issue #845's 2026-09-05 scope note), which ``scene get`` pins below.

**Why the host's filesystem is PROBED rather than assumed.** The decision reads the
directory's own entries instead of asking whether a path exists, so it reaches the
same verdict on both kinds of filesystem — that is the point of the fix, not an
accident of the host. What DOES differ per host is the premise each branch states:
on a case-insensitive filesystem the mis-cased path really would have opened, and on
a case-sensitive one it really is absent. Each branch therefore asserts its own
premise and skips where the host cannot provide it, so this module says something
true on macOS (this repo's development host) and something true on Linux CI, and
neither branch silently passes as a no-op.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.project import case_mismatch
from gda.runner import RunResult
from tests.support import (
    inject_runner,
    invoke_operation_error,
    minimal_project,
)

runner_cli = CliRunner()

#: The tracked spelling, and the one a caller typed with the wrong case.
STORED_SCRIPT = "content/combat_session.gd"
REQUESTED_SCRIPT = "Content/combat_session.gd"
STORED_ASSET = "content/art/icon.png"
REQUESTED_ASSET = "Content/art/icon.png"


def _case_insensitive(directory: Path) -> bool:
    """Does ``directory``'s filesystem open one file under two cases?

    Probed with a real file rather than inferred from ``sys.platform``: macOS can
    be formatted case-sensitively, a Linux host can mount a case-insensitive
    volume, and a CI runner's temp directory is not always the boot volume.
    """
    probe = directory / "gda_case_probe"
    probe.write_text("", encoding="utf-8")
    try:
        return (directory / "GDA_CASE_PROBE").exists()
    finally:
        probe.unlink()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project holding the two lower-case entries the tests mis-spell."""
    root = minimal_project(tmp_path / "game")
    script = root / STORED_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("extends Node\n", encoding="utf-8")
    asset = root / STORED_ASSET
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def _refusal(project: Path, *argv: str) -> dict:
    result = runner_cli.invoke(
        app, [*argv, "--project", str(project), "--json"], catch_exceptions=False
    )
    assert result.exit_code == 4, result.stdout + result.stderr
    return json.loads(result.stdout)["error"]


# --- the authority itself -----------------------------------------------------


def test_the_authority_names_the_requested_and_the_stored_spelling(project):
    # The whole decision: resolve the requested path against the project, compare
    # each component with the directory entry's ACTUAL spelling, and report both
    # addresses. Both are res:// addresses, because that is the namespace the
    # project stores the entry in and the spelling all three gated commands accept
    # back.
    violation = case_mismatch(f"res://{REQUESTED_SCRIPT}", project)

    assert violation is not None
    assert violation.requested == f"res://{REQUESTED_SCRIPT}"
    assert violation.stored == f"res://{STORED_SCRIPT}"


def test_a_directory_component_is_compared_too(project):
    # The comparison is per COMPONENT, not on the file name alone: GDA-DF-062's own
    # mis-spelling was a directory (`Content/`), and the file name was exact.
    violation = case_mismatch(f"res://Content/{Path(STORED_SCRIPT).name}", project)

    assert violation is not None
    assert violation.stored == f"res://{STORED_SCRIPT}"


def test_the_stored_spelling_is_not_a_mismatch(project):
    assert case_mismatch(f"res://{STORED_SCRIPT}", project) is None


def test_a_filesystem_spelling_is_answered_in_the_project_namespace(project):
    # The gated commands also take a project-relative path, so the check anchors it
    # the way the engine does and still reports both addresses as res:// — the one
    # form every one of them accepts back.
    violation = case_mismatch(REQUESTED_SCRIPT, project)

    assert violation is not None
    assert violation.requested == f"res://{REQUESTED_SCRIPT}"
    assert violation.stored == f"res://{STORED_SCRIPT}"


def test_a_name_no_entry_matches_is_left_to_the_operation(project):
    # The other half of the case-sensitive clause: with no case-variant entry there
    # is no mismatch to report, so the authority says nothing and the operation
    # reports its own `path_not_found`.
    assert case_mismatch("res://content/absent.gd", project) is None
    assert case_mismatch("res://absent/combat_session.gd", project) is None
    # ...and the shape where the early return actually decides something: a
    # mis-cased DIRECTORY with an absent leaf. Some components DO name an entry, so
    # a walk that carried the requested spelling forward for the one that does not
    # would answer `path_case_mismatch` and offer `res://content/absent.gd` as the
    # "stored" spelling of a file that exists under neither case — a false
    # correction in place of the true `path_not_found`.
    assert case_mismatch("res://Content/absent.gd", project) is None


def test_the_project_root_itself_is_not_compared(project):
    # A case-differing PROJECT spelling is a separate, still-open gap (ADR-0006's
    # "Not closed here"), so the walk starts BELOW the root and says nothing about it.
    assert case_mismatch("res://", project) is None


# --- the two filesystem behaviours, each asserting its own premise -------------


def test_a_case_insensitive_host_would_have_opened_the_mis_cased_path(project):
    if not _case_insensitive(project):
        pytest.skip("this host's filesystem is case-sensitive")

    # The premise: without the refusal the engine opens the file and validates it,
    # which is exactly the false `valid: true` GDA-DF-062 reported.
    assert (project / REQUESTED_SCRIPT).exists()

    error = _refusal(project, "script", "validate", f"res://{REQUESTED_SCRIPT}")

    assert error["code"] == "path_case_mismatch"


def test_a_case_sensitive_host_reports_the_mismatch_rather_than_a_missing_file(project):
    if _case_insensitive(project):
        pytest.skip("this host's filesystem is case-insensitive")

    # The premise: here the requested path really is absent, so without the check
    # the caller would get `path_not_found` — a different code for the same mistake.
    assert not (project / REQUESTED_SCRIPT).exists()

    error = _refusal(project, "script", "validate", f"res://{REQUESTED_SCRIPT}")

    assert error["code"] == "path_case_mismatch"


def test_a_case_sensitive_host_answers_with_the_spelling_the_caller_named(project):
    if _case_insensitive(project):
        pytest.skip("this host's filesystem cannot hold both spellings at once")

    # The other thing only a case-sensitive filesystem can state: it holds `content`
    # and `Content` as two SEPARATE directories, so both spellings name a file that
    # really opens and neither is a mistake. `_stored_entry` prefers the exact match
    # for exactly this case; without that preference `os.listdir` order picks the
    # answer, and one of the two callers is refused with a "stored" spelling for a
    # file that exists precisely as they asked for it.
    other = project / "Content"
    other.mkdir()
    (other / Path(STORED_SCRIPT).name).write_text("extends Node\n", encoding="utf-8")

    assert case_mismatch(f"res://{STORED_SCRIPT}", project) is None
    assert case_mismatch(f"res://{REQUESTED_SCRIPT}", project) is None


# --- the three commands the gate protects, and the rest of the surface ---------


def test_script_validate_reports_both_spellings_typed_and_in_the_message(project):
    error = _refusal(project, "script", "validate", f"res://{REQUESTED_SCRIPT}")

    assert error["code"] == "path_case_mismatch"
    assert error["category"] == "operation"
    assert error["evidence"] == {
        "requested_path": f"res://{REQUESTED_SCRIPT}",
        "stored_path": f"res://{STORED_SCRIPT}",
    }
    assert f"res://{REQUESTED_SCRIPT}" in error["message"]
    assert f"res://{STORED_SCRIPT}" in error["message"]
    # No `hint`: the envelope's hint is one corrected invocation from the curated
    # near-miss table (ADR-0004's #670 note), and a case mismatch is not a near
    # miss — the corrected spelling is the typed `stored_path`.
    assert "hint" not in error


def test_script_run_reports_the_same_refusal(project):
    error = _refusal(project, "script", "run", f"res://{REQUESTED_SCRIPT}")

    assert error["code"] == "path_case_mismatch"
    assert error["evidence"]["stored_path"] == f"res://{STORED_SCRIPT}"


def test_resource_import_reports_the_same_refusal(project):
    # AC3's proof that the check sits in the shared authority BEHIND the gate and
    # not in the `script` group: a different command group, a different asset kind,
    # one code and one pair of spellings.
    error = _refusal(project, "resource", "import", f"res://{REQUESTED_ASSET}")

    assert error["code"] == "path_case_mismatch"
    assert error["evidence"] == {
        "requested_path": f"res://{REQUESTED_ASSET}",
        "stored_path": f"res://{STORED_ASSET}",
    }


def test_scene_get_with_the_same_misspelling_is_unchanged(monkeypatch):
    # The scope line (#845, 2026-09-05): every other command hands its res:// target
    # to the engine and never consults the authority, so gda adds no refusal there —
    # the engine's own behaviour stands. Widening that is an ADR-0006 design change
    # with its own issue, not a side effect of this fix.
    result = invoke_operation_error(
        monkeypatch,
        ["scene", "get", "res://Content/main.tscn", "--json"],
        "path_not_found",
        "scene file does not exist: res://Content/main.tscn",
        "scene-get",
    )

    assert json.loads(result.stdout)["error"]["code"] == "path_not_found"


# --- the two input paths, and the published contract --------------------------


def test_argv_and_params_json_refuse_identically(project):
    argv = runner_cli.invoke(
        app,
        [
            "script",
            "validate",
            f"res://{REQUESTED_SCRIPT}",
            "--project",
            str(project),
            "--json",
        ],
    )
    params_json = runner_cli.invoke(
        app,
        [
            "script",
            "validate",
            "--params-json",
            json.dumps({"paths": [f"res://{REQUESTED_SCRIPT}"]}),
            "--project",
            str(project),
            "--json",
        ],
    )

    assert argv.exit_code == params_json.exit_code == 4
    assert json.loads(argv.stdout) == json.loads(params_json.stdout)


def test_the_published_error_schema_carries_both_evidence_fields():
    # ADR-0004: the failure envelope is ONE schema for every command, so the two
    # fields are published wherever it is. Read off a gated command's own contract.
    result = runner_cli.invoke(app, ["script", "validate", "--schema"])

    schema = json.loads(result.stdout)
    evidence = schema["error"]["$defs"]["FailureEvidence"]["properties"]

    assert "requested_path" in evidence
    assert "stored_path" in evidence


def test_the_human_rendering_names_both_spellings(project):
    result = runner_cli.invoke(
        app,
        ["script", "validate", f"res://{REQUESTED_SCRIPT}", "--project", str(project)],
    )

    assert result.exit_code == 4
    assert "error: path_case_mismatch (operation)" in result.stdout
    assert f"  requested path: res://{REQUESTED_SCRIPT}" in result.stdout
    assert f"  stored path: res://{STORED_SCRIPT}" in result.stdout


def test_a_correctly_spelled_target_still_reaches_the_engine(project, monkeypatch):
    # The refusal must not become a gate that stops the exact spelling too.
    fake = inject_runner(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))
    runner_cli.invoke(
        app,
        ["script", "validate", f"res://{STORED_SCRIPT}", "--project", str(project)],
    )

    assert fake.calls
