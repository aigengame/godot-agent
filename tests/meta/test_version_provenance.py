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
- **both install kinds, and the refusal to pick one.** Editable and wheel installs
  are covered by faking the PEP 610 `direct_url.json` record — a real wheel install
  cannot be produced from inside the editable checkout the suite runs in. Only a
  genuinely ABSENT record earns a confident `wheel`; a record gda cannot read as a
  PEP 610 document — malformed, whitespace-only, or unretrievable — is `unknown`.
- **no engine launch.** The motivating environment is one where spawning Godot
  crashes, so a provenance preflight that spawned Godot would be useless there.

These are fast tests: nothing here spawns Godot.
"""

import json
import os
import shutil
import subprocess
from importlib.metadata import version as installed_version
from pathlib import Path

from typer.testing import CliRunner

import gda.provenance as provenance
from gda.cli import app
from gda.provenance import (
    DirectUrlRecord,
    InstallKind,
    RecordState,
    build_version_provenance,
    classify_install,
    read_direct_url_record,
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


def fake_direct_url(monkeypatch, raw: str | None) -> None:
    """Serve ``raw`` as the running gda's PEP 610 record; ``None`` means no record.

    The seam hands over RAW text, so a fake can supply a malformed document as
    easily as a well-formed one — which is the point: the three read arms must reach
    different conclusions. This helper covers the ABSENT and PRESENT arms; the
    UNREADABLE and ABSENT arms are driven through the real reader by
    :func:`real_metadata_dist`, because a faked verdict would not prove the
    reader produces them.
    """
    record = (
        DirectUrlRecord(RecordState.ABSENT)
        if raw is None
        else DirectUrlRecord(RecordState.PRESENT, raw)
    )
    monkeypatch.setattr(provenance, "read_direct_url_record", lambda *a, **k: record)


def real_metadata_dist(
    monkeypatch,
    tmp_path,
    *,
    record: str | None = None,
    mode: int | None = None,
    as_directory: bool = False,
) -> Path:
    """Point gda's metadata at a REAL dist-info directory built on disk.

    Drives the true :func:`read_direct_url_record` end to end — ``locate_file``
    plus a genuine filesystem read — so every arm is produced by the real
    reader's behavior (a missing entry, an unreadable mode, a directory sitting
    where the record should be), never by a faked verdict. The stdlib
    ``Distribution.read_text()`` would suppress those failures into the same
    ``None`` as absence, which is exactly the collapse these tests guard
    against. Carries the true installed version so ``build_version_provenance``
    still emits a complete payload. Returns the record's path so a test can
    restore permissions.
    """
    from importlib.metadata import PathDistribution

    info = tmp_path / "gda_fixture-0.0.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.3\nName: gda-fixture\n"
        f"Version: {installed_version('gda')}\n",
        encoding="utf-8",
    )
    target = info / "direct_url.json"
    if as_directory:
        target.mkdir()
    elif record is not None:
        target.write_text(record, encoding="utf-8")
        if mode is not None:
            target.chmod(mode)
    dist = PathDistribution(info)
    monkeypatch.setattr(provenance.Distribution, "from_name", lambda name: dist)
    return target


def fake_editable_install(monkeypatch, root: Path) -> None:
    """Make gda look like an editable install rooted at ``root`` (PEP 610)."""
    record = {"url": root.as_uri(), "dir_info": {"editable": True}}
    fake_direct_url(monkeypatch, json.dumps(record))


def fake_wheel_install(monkeypatch) -> None:
    """Make gda look like an ordinary built install: no PEP 610 record at all."""
    fake_direct_url(monkeypatch, None)


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
    assert payload["install_kind"] in {"wheel", "editable", "unknown"}
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


def test_dirty_ignores_the_repositorys_untracked_files_config(monkeypatch, tmp_path):
    # `status.showUntrackedFiles=no` is a real setting people put in a repo or their
    # global config. With the status call left to it, an untracked module sitting in
    # the checkout — importable by the editable install, so code that can run —
    # reported `dirty: false`, contradicting this module's stated contract. The
    # verdict must be a property of the TREE, not of someone's git config.
    checkout = tmp_path / "src-checkout"
    make_git_checkout(checkout)
    _git(checkout, "config", "status.showUntrackedFiles", "no")
    (checkout / "runtime_shadow.py").write_text("# untracked\n", encoding="utf-8")
    fake_editable_install(monkeypatch, checkout)

    payload = build_version_provenance()

    # The config really is in force — this is what gda would have believed.
    assert _git(checkout, "status", "--porcelain").strip() == ""
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
    fake_direct_url(
        monkeypatch,
        json.dumps(
            {
                "url": "https://example.invalid/gda.tar.gz",
                "dir_info": {"editable": True},
            }
        ),
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
    fake_direct_url(
        monkeypatch,
        json.dumps(
            {
                "url": (tmp_path / "gda-0.0.0-py3-none-any.whl").as_uri(),
                "archive_info": {},
            }
        ),
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None


def test_a_non_editable_directory_install_is_a_wheel(monkeypatch, tmp_path):
    # `pip install .` records `dir_info` with `editable` absent/false; it builds a
    # wheel, so the checkout it was built from is not what runs.
    fake_direct_url(monkeypatch, json.dumps({"url": tmp_path.as_uri(), "dir_info": {}}))

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None


def test_an_explicit_non_editable_dir_info_is_a_wheel(monkeypatch, tmp_path):
    # PEP 610 types `editable` as a boolean and defaults an absent one to false;
    # an explicit `false` must reach the same verdict as the absent one above.
    fake_direct_url(
        monkeypatch,
        json.dumps({"url": tmp_path.as_uri(), "dir_info": {"editable": False}}),
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.WHEEL
    assert payload.source is None


def test_the_wheel_payload_reaches_the_cli(monkeypatch):
    fake_wheel_install(monkeypatch)

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["install_kind"] == "wheel"
    assert payload["source"] is None


# --- unreadable metadata is `unknown`, never a confident `wheel` --------------


def test_malformed_metadata_is_unknown_not_wheel(monkeypatch):
    # The dangerous collapse: "no record" and "a record I cannot read" both used to
    # become `wheel` + `source: null`, so a DAMAGED editable install was reported as
    # an immutable copy — the exact false provenance this surface exists to prevent.
    fake_direct_url(monkeypatch, "{not json")

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.UNKNOWN
    assert payload.source is None


def test_a_non_object_record_is_unknown(monkeypatch):
    fake_direct_url(monkeypatch, '"just a string"')

    assert build_version_provenance().install_kind is InstallKind.UNKNOWN


def test_a_non_object_dir_info_is_unknown(monkeypatch):
    fake_direct_url(monkeypatch, json.dumps({"url": "file:///x", "dir_info": "yes"}))

    assert build_version_provenance().install_kind is InstallKind.UNKNOWN


def test_a_non_boolean_editable_is_unknown_not_truthiness(monkeypatch, tmp_path):
    # PEP 610 types `editable` as a boolean. Reading `"false"` or `1` by truthiness
    # is how a mutable checkout gets called immutable (or the reverse), so anything
    # off-spec refuses to answer rather than guessing.
    for off_spec in ("false", "true", 1, 0, None, [], {}):
        fake_direct_url(
            monkeypatch,
            json.dumps({"url": tmp_path.as_uri(), "dir_info": {"editable": off_spec}}),
        )

        payload = build_version_provenance()

        assert payload.install_kind is InstallKind.UNKNOWN, off_spec
        assert payload.source is None, off_spec


def test_unknown_never_claims_a_checkout(monkeypatch, tmp_path):
    # Even when the damaged record names a perfectly good local checkout, an
    # unresolved kind must not vouch for it.
    checkout = tmp_path / "src-checkout"
    make_git_checkout(checkout)
    fake_direct_url(
        monkeypatch,
        json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": "yes"}}),
    )

    payload = build_version_provenance()

    assert payload.install_kind is InstallKind.UNKNOWN
    assert payload.source is None


def test_malformed_metadata_reaches_the_cli_as_unknown(monkeypatch):
    fake_direct_url(monkeypatch, "{not json")

    result = CliRunner().invoke(app, ["--version", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["install_kind"] == "unknown"
    assert payload["source"] is None
    # …and the rest of the payload still answers what it CAN answer.
    assert payload["gda_version"] and payload["package_path"]


def test_classify_install_is_pure_and_total():
    # The classifier is the whole decision, so it is exercised directly too: every
    # read arm to its verdict, with no installer and no filesystem. Only ABSENT
    # reaches `wheel`; both non-answers reach `unknown`.
    absent = DirectUrlRecord(RecordState.ABSENT)
    unreadable = DirectUrlRecord(RecordState.UNREADABLE)
    editable = DirectUrlRecord(
        RecordState.PRESENT, '{"url":"file:///x","dir_info":{"editable":true}}'
    )

    assert classify_install(absent).kind is InstallKind.WHEEL
    assert classify_install(unreadable).kind is InstallKind.UNKNOWN
    assert classify_install(editable).kind is InstallKind.EDITABLE
    assert classify_install(DirectUrlRecord(RecordState.PRESENT, "")).kind is (
        InstallKind.UNKNOWN
    )
    assert classify_install(DirectUrlRecord(RecordState.PRESENT, "  \n")).kind is (
        InstallKind.UNKNOWN
    )


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


# --- the read seam has THREE arms, and flattens none of them -------------------
#
# The first round of this slice split "malformed" out of "absent" but left two arms
# still collapsing back: a whitespace-only record and a reader that raised both
# became "absent", hence a confident `wheel`. These pin all three arms at the
# reader, and the two once-collapsed ones end to end as well.


def test_a_missing_record_is_absent(monkeypatch, tmp_path):
    # The one arm that legitimately implies a wheel: the entry genuinely does not
    # exist on disk — positive missing-file evidence, not an ambiguous None.
    real_metadata_dist(monkeypatch, tmp_path)

    assert read_direct_url_record() == DirectUrlRecord(RecordState.ABSENT)


def test_a_malformed_record_is_present_and_handed_over_verbatim(monkeypatch, tmp_path):
    # The seam does not judge: it returns the bytes and the classifier decides.
    real_metadata_dist(monkeypatch, tmp_path, record="{not json")

    assert read_direct_url_record() == DirectUrlRecord(RecordState.PRESENT, "{not json")


def test_a_whitespace_only_record_is_present_not_absent(monkeypatch, tmp_path):
    # Was pinned the WRONG way: the seam blanked "   \n" to None, so a record that
    # exists but says nothing became "absent" and the payload claimed `wheel`. A
    # record that exists but says nothing is off-spec, not absent.
    real_metadata_dist(monkeypatch, tmp_path, record="   \n")

    assert read_direct_url_record() == DirectUrlRecord(RecordState.PRESENT, "   \n")


def test_an_unreadable_record_is_unreadable_not_absent(monkeypatch, tmp_path):
    # The stdlib Distribution.read_text() SUPPRESSES PermissionError and returns
    # None — indistinguishable from absence. The seam must read through the located
    # entry so a real mode-000 record stays distinct from a missing one.
    target = real_metadata_dist(monkeypatch, tmp_path, record="{}", mode=0o000)
    try:
        record = read_direct_url_record()
    finally:
        target.chmod(0o644)

    assert record == DirectUrlRecord(RecordState.UNREADABLE)


def test_a_directory_shaped_record_is_unreadable_not_absent(monkeypatch, tmp_path):
    # IsADirectoryError is another failure the stdlib reader flattens to None: a
    # directory sitting at direct_url.json is corrupt metadata, not a missing file.
    real_metadata_dist(monkeypatch, tmp_path, as_directory=True)

    assert read_direct_url_record() == DirectUrlRecord(RecordState.UNREADABLE)


def test_a_pathless_distribution_raising_reader_is_unreadable(monkeypatch):
    # A custom Distribution need not expose PathDistribution's private _path; its
    # abstract read_text() can RAISE while accessing metadata. That failure must
    # land in the same UNREADABLE boundary as the path-backed branch's failures —
    # not escape as a traceback (third-recheck regression).
    class _PathlessDist:
        version = installed_version("gda")

        def read_text(self, name: str):
            raise PermissionError("injected: metadata unreadable")

    monkeypatch.setattr(
        provenance.Distribution, "from_name", lambda name: _PathlessDist()
    )

    assert read_direct_url_record() == DirectUrlRecord(RecordState.UNREADABLE)


def test_a_pathless_raising_reader_reaches_the_cli_as_unknown(monkeypatch):
    class _PathlessDist:
        version = installed_version("gda")

        def read_text(self, name: str):
            raise PermissionError("injected: metadata unreadable")

    monkeypatch.setattr(
        provenance.Distribution, "from_name", lambda name: _PathlessDist()
    )

    result = CliRunner().invoke(app, ["--version", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["install_kind"] == "unknown"
    assert payload["source"] is None
    assert payload["gda_version"] and payload["package_path"] and payload["godot"]


def test_an_uninstalled_distribution_is_unreadable_not_absent():
    # gda did not learn that no record exists; it failed to look. Degrades rather
    # than raising, so a preflight never dies on missing metadata.
    record = read_direct_url_record("definitely-not-an-installed-distribution")

    assert record == DirectUrlRecord(RecordState.UNREADABLE)


def test_a_whitespace_only_record_reaches_the_cli_as_unknown(monkeypatch, tmp_path):
    real_metadata_dist(monkeypatch, tmp_path, record="   \n")

    result = CliRunner().invoke(app, ["--version", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["install_kind"] == "unknown"
    assert payload["source"] is None
    # …and the payload is still emitted in full: degrade, never die.
    assert payload["gda_version"] and payload["package_path"] and payload["godot"]


def test_an_unreadable_record_reaches_the_cli_as_unknown(monkeypatch, tmp_path):
    # A REAL mode-000 record through the real CLI: the stdlib reader would flatten
    # this to None/absent; the located-entry read keeps it distinct, and the
    # preflight degrades to `unknown` with a complete payload instead of dying.
    target = real_metadata_dist(monkeypatch, tmp_path, record="{}", mode=0o000)

    try:
        result = CliRunner().invoke(app, ["--version", "--json"])
    finally:
        target.chmod(0o644)

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["install_kind"] == "unknown"
    assert payload["source"] is None
    assert payload["gda_version"] and payload["package_path"] and payload["godot"]


def test_a_missing_record_reaches_the_cli_as_wheel(monkeypatch, tmp_path):
    # The control for the two arms above: only a genuinely absent record earns the
    # confident `wheel`, so the tests prove a distinction rather than a constant.
    real_metadata_dist(monkeypatch, tmp_path)

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["install_kind"] == "wheel"
    assert payload["source"] is None


# --- the engine side is resolved WITHOUT a launch -----------------------------


def test_godot_version_key_is_omitted_with_a_stated_reason(monkeypatch):
    # #659's contract is "the engine version appears only when obtainable without a
    # launch, otherwise OMITTED with a stated reason". A `null` would claim gda
    # looked and found nothing; the key's ABSENCE plus the reason says it declined
    # to look — the same omitted-never-null convention gda uses elsewhere. So this
    # asserts absence, not nullness.
    monkeypatch.setenv("GDA_GODOT", "/definitely/missing/Godot")

    payload = json.loads(CliRunner().invoke(app, ["--version", "--json"]).stdout)

    assert payload["godot"]["binary"] == "/definitely/missing/Godot"
    assert "version" not in payload["godot"]
    assert payload["godot"]["version_unavailable_reason"]
    assert set(payload["godot"]) == {"binary", "version_unavailable_reason"}


def test_a_resolved_godot_version_would_omit_the_reason_instead():
    # The mirror of the rule: exactly one of the pair is ever present, so a future
    # spawn-free version source cannot leave a stale null reason beside it.
    resolved = provenance.GodotProvenance(binary="/x/Godot", version="4.6.3-stable")

    serialized = json.loads(resolved.model_dump_json())

    assert serialized == {"binary": "/x/Godot", "version": "4.6.3-stable"}


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
