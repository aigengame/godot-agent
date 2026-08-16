"""`gda --version --json` reports which gda ran, and from where (issue #659).

Two dogfooding findings drive this surface. GDA-DF-018: `gda --version --json`
was rejected, so an evidence collector had to parse one human line. GDA-DF-043:
the `gda` a `PATH` lookup resolved was an *editable* install whose source checkout
changed revision mid-run, and the output disclosed none of it.

So these tests pin three things:

- **both argv orders.** `gda --version --json` (the spelling the report used) and
  `gda --json --version` must produce the same payload. Click processes eager
  parameters in argv order, so this only holds because `--version` is deliberately
  NOT eager and therefore sorts after the eager `--json` in both orders.
- **both install kinds.** Editable and wheel installs are covered by faking the
  PEP 610 `direct_url.json` record — a real wheel install cannot be produced from
  inside the editable checkout the suite runs in.
- **no engine launch.** The motivating environment is one where spawning Godot
  crashes, so a provenance preflight that spawned Godot would be useless there.

These are fast tests: nothing here spawns Godot.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from typer.testing import CliRunner

import gda.provenance as provenance
from gda.cli import app
from gda.provenance import (
    InstallKind,
    build_version_provenance,
    read_direct_url,
)
from tests.support import GDA_CMD, plain_text

# A git environment that ignores the machine's user/system config, so a CI runner
# with no `user.email` (or with commit signing on) still builds the fixture repo.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "gda tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "gda tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    )
    return done.stdout


def make_git_checkout(repo: Path) -> str:
    """Create a one-commit git repository at ``repo``; return its HEAD revision.

    The committed file carries the repository's own path, so two fixture repos
    never share a tree and therefore never share a revision — which is what lets a
    test tell "read the right repository" from "read any repository".
    """
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", str(repo)], check=True, capture_output=True, env=GIT_ENV
    )
    (repo / "pyproject.toml").write_text(f"# {repo}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return _git(repo, "rev-parse", "HEAD").strip()


def fake_editable_install(monkeypatch, root: Path) -> None:
    """Make gda look like an editable install rooted at ``root`` (PEP 610)."""
    record = {"url": root.as_uri(), "dir_info": {"editable": True}}
    monkeypatch.setattr(provenance, "read_direct_url", lambda *a, **k: record)


def fake_wheel_install(monkeypatch) -> None:
    """Make gda look like an ordinary built install: no PEP 610 record at all."""
    monkeypatch.setattr(provenance, "read_direct_url", lambda *a, **k: None)


# --- the two argv orders ------------------------------------------------------


def test_version_json_works_in_both_argv_orders():
    # `gda --version --json` is the exact spelling GDA-DF-018 reported as
    # rejected; `gda --json --version` is the spelling the root-flag rule
    # (#671, "always pass --json") produces. Both must mean the same thing.
    after = CliRunner().invoke(app, ["--version", "--json"])
    before = CliRunner().invoke(app, ["--json", "--version"])

    assert after.exit_code == 0, after.stdout
    assert before.exit_code == 0, before.stdout
    assert after.stdout == before.stdout
    assert json.loads(after.stdout)["gda_version"]


def test_bare_version_stays_the_human_one_liner():
    # The default is unchanged: a human still gets one line, not a JSON blob.
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert not result.stdout.startswith("{")
    assert result.stdout.startswith("gda ")


def test_help_wins_over_version_when_both_are_given():
    # The deliberate trade for making `--version` non-eager: click's own eager
    # `--help` now takes precedence, which is the conventional order anyway.
    result = CliRunner().invoke(app, ["--version", "--help"])

    assert result.exit_code == 0, result.stdout
    assert "Usage: gda" in plain_text(result.stdout)


# --- the payload --------------------------------------------------------------


def test_payload_carries_the_required_provenance_fields():
    result = CliRunner().invoke(app, ["--version", "--json"])

    payload = json.loads(result.stdout)
    assert set(payload) == {
        "gda_version",
        "executable",
        "interpreter",
        "package_path",
        "install_kind",
        "source",
        "godot",
    }
    assert payload["install_kind"] in {"wheel", "editable"}
    assert Path(payload["executable"]).is_absolute()
    assert Path(payload["interpreter"]).is_absolute()
    assert Path(payload["package_path"]).is_absolute()


def test_payload_declares_no_schema_or_protocol_version():
    # gda has no schema/protocol version; inventing one would create a contract
    # nothing else honors (#659 says so explicitly).
    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert not [key for key in payload if "protocol" in key or "schema" in key]


def test_help_advertises_the_structured_form():
    result = CliRunner().invoke(app, ["--help"])

    assert "install provenance" in plain_text(result.stdout)


# --- editable installs --------------------------------------------------------


def test_editable_install_reports_its_checkout_and_revision(monkeypatch, tmp_path):
    checkout = tmp_path / "src-checkout"
    revision = make_git_checkout(checkout)
    fake_editable_install(monkeypatch, checkout)

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.EDITABLE
    assert payload.source is not None
    assert payload.source.root == str(checkout)
    assert payload.source.revision == revision
    assert payload.source.dirty is False


def test_editable_install_reports_a_dirty_working_tree(monkeypatch, tmp_path):
    # The GDA-DF-043 signal: the checkout the running code is imported from does
    # not match any committed revision, so the revision alone would mislead.
    checkout = tmp_path / "src-checkout"
    make_git_checkout(checkout)
    (checkout / "scratch.py").write_text("# untracked\n", encoding="utf-8")
    fake_editable_install(monkeypatch, checkout)

    payload = build_version_provenance()

    assert payload.source is not None
    assert payload.source.dirty is True


def test_editable_install_outside_git_reports_null_revision(monkeypatch, tmp_path):
    # "when resolvable": no repository means null, never a guessed revision.
    missing = tmp_path / "not-a-repo-and-not-even-there"
    fake_editable_install(monkeypatch, missing)

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.EDITABLE
    assert payload.source is not None
    assert payload.source.root == str(missing)
    assert payload.source.revision is None
    assert payload.source.dirty is None


def test_an_inherited_git_dir_cannot_redirect_the_revision(monkeypatch, tmp_path):
    # `$GIT_DIR` WINS over `git -C`, and gda is invoked from exactly the places
    # that set it — a git hook, `git rebase --exec`, `git bisect run`, a CI
    # wrapper. Unscrubbed, the payload paired THIS checkout's `root` with ANOTHER
    # repository's `revision`, silently: worse than the null this surface promises
    # when it cannot answer.
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    our_revision = make_git_checkout(ours)
    their_revision = make_git_checkout(theirs)
    assert our_revision != their_revision  # the fixture can tell them apart

    monkeypatch.setenv("GIT_DIR", str(theirs / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(theirs))
    fake_editable_install(monkeypatch, ours)

    payload = build_version_provenance()

    assert payload.source is not None
    assert payload.source.root == str(ours)
    assert payload.source.revision == our_revision
    assert payload.source.revision != their_revision


def test_editable_install_with_a_non_local_url_reports_no_checkout(monkeypatch):
    # Editable is read from `dir_info.editable`; only a `file:` URL names a
    # directory on this machine, so a non-local origin stays honestly null
    # instead of being turned into a fabricated path.
    monkeypatch.setattr(
        provenance,
        "read_direct_url",
        lambda *a, **k: {
            "url": "https://example.invalid/gda.tar.gz",
            "dir_info": {"editable": True},
        },
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.EDITABLE
    assert payload.source is None


def test_the_editable_payload_reaches_the_cli(monkeypatch, tmp_path):
    checkout = tmp_path / "src-checkout"
    revision = make_git_checkout(checkout)
    fake_editable_install(monkeypatch, checkout)

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["install_kind"] == "editable"
    assert payload["source"] == {
        "root": str(checkout),
        "revision": revision,
        "dirty": False,
    }


# --- wheel installs -----------------------------------------------------------


def test_wheel_install_reports_no_source_checkout(monkeypatch):
    # A real wheel install is not producible from inside this editable checkout,
    # so the distribution metadata is faked: an ordinary index install records no
    # PEP 610 `direct_url.json` at all.
    fake_wheel_install(monkeypatch)

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None
    assert payload.gda_version


def test_a_built_local_wheel_is_still_a_wheel(monkeypatch, tmp_path):
    # `pip install ./dist/gda-*.whl` DOES record a direct_url.json — with
    # `archive_info`, not an editable `dir_info`. The code that runs is still a
    # copy, so there is no checkout to report.
    monkeypatch.setattr(
        provenance,
        "read_direct_url",
        lambda *a, **k: {
            "url": (tmp_path / "gda-0.0.0-py3-none-any.whl").as_uri(),
            "archive_info": {},
        },
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None


def test_a_non_editable_directory_install_is_a_wheel(monkeypatch, tmp_path):
    # `pip install .` records `dir_info` with `editable` absent/false; it builds a
    # wheel, so the checkout it was built from is not what runs.
    monkeypatch.setattr(
        provenance,
        "read_direct_url",
        lambda *a, **k: {"url": tmp_path.as_uri(), "dir_info": {}},
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None


def test_the_wheel_payload_reaches_the_cli(monkeypatch):
    fake_wheel_install(monkeypatch)

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["install_kind"] == "wheel"
    assert payload["source"] is None


# --- the imported package, not just the recorded install ----------------------


def test_package_path_names_the_module_that_actually_ran():
    payload = build_version_provenance()

    assert payload.package_path == str(Path(provenance.__file__).parent)


def test_package_path_exposes_a_sys_path_shadow(tmp_path):
    # The falsifiability check. `install_kind`, `source` and the version all come
    # from distribution METADATA, which describes what an installer recorded — not
    # what Python loaded. Put a copy of the package earlier on sys.path and the
    # metadata keeps describing the installed one while a different tree runs, so
    # without this field the payload would be confidently wrong about the code its
    # evidence came from.
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()
    installed = Path(provenance.__file__).parent
    shutil.copytree(installed, shadow_root / "gda")

    env = {
        **os.environ,
        "PYTHONPATH": str(shadow_root),
        "PYTHONSAFEPATH": "1",  # keep the cwd from shadowing it back
    }
    done = subprocess.run(
        [*GDA_CMD, "--version", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["package_path"] == str(shadow_root / "gda")
    assert payload["package_path"] != str(installed)


# --- the direct_url seam ------------------------------------------------------


def test_read_direct_url_is_none_for_an_uninstalled_distribution():
    # The seam degrades to "nothing to disclose" rather than raising, so a
    # preflight never fails on missing metadata.
    assert read_direct_url("definitely-not-an-installed-distribution") is None


def test_read_direct_url_ignores_a_malformed_record(monkeypatch, tmp_path):
    class _Dist:
        def read_text(self, name: str) -> str:
            return "{not json"

    monkeypatch.setattr(provenance.Distribution, "from_name", lambda name: _Dist())

    assert read_direct_url() is None


# --- the engine side is resolved WITHOUT a launch -----------------------------


def test_godot_version_is_omitted_with_a_stated_reason(monkeypatch):
    monkeypatch.setenv("GDA_GODOT", "/definitely/missing/Godot")

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["godot"]["binary"] == "/definitely/missing/Godot"
    assert payload["godot"]["version"] is None
    assert payload["godot"]["version_unavailable_reason"]


def test_the_surface_never_launches_godot(monkeypatch):
    # The whole point: the motivating environment is a restricted profile where an
    # engine spawn crashes. `gda.runner.launch` is the ONE headless-launch
    # primitive every engine-spawning channel shares, so tripping it here proves a
    # launch happened.
    def _no_launch(*args, **kwargs):
        raise AssertionError("the provenance surface must not launch Godot")

    monkeypatch.setattr("gda.runner.launch", _no_launch)
    monkeypatch.setenv("GDA_GODOT", "/definitely/missing/Godot")

    spawned: list[list[str]] = []
    real_run = subprocess.run

    def _spy(cmd, *args, **kwargs):
        spawned.append([str(part) for part in cmd])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)

    result = CliRunner().invoke(app, ["--version", "--json"])

    assert result.exit_code == 0, result.stdout
    # Whatever it did spawn, it was git resolving the checkout — never the engine.
    # `assert spawned` first: this checkout IS an editable install, so git runs;
    # without it, an empty list would satisfy the `all(...)` below vacuously and
    # the guard would keep passing after it stopped guarding anything.
    assert spawned
    assert all(cmd[:1] == ["git"] for cmd in spawned), spawned
    assert not [cmd for cmd in spawned if "Godot" in " ".join(cmd)]


# --- the real out-of-process CLI ---------------------------------------------


def test_real_out_of_process_cli_emits_the_payload():
    # Through a REAL process, so the payload describes an actual invocation rather
    # than the in-process test runner. Deliberately not marked `e2e`: this repo's
    # `e2e` marker means "spawns a real Godot process", and this must not.
    done = subprocess.run(
        [*GDA_CMD, "--version", "--json"], capture_output=True, text=True
    )

    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["gda_version"]
    # `python -m gda` runs the package's __main__, and that is what is reported —
    # the entry point that actually ran, not a re-guessed `which gda`.
    assert payload["executable"].endswith(os.path.join("gda", "__main__.py"))
    assert payload["interpreter"]
