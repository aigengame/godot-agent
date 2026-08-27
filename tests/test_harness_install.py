"""gda harness install (#7, #225, ADR-0018): idempotent project.godot autoload write.

Pure filesystem: materialize the bundled harness under ``res://addons/`` and add
its ``[autoload]`` entry to ``project.godot`` — a one-time, install-time write
(never a per-launch mutation), idempotent and order-preserving. #225 adds the
version self-sync (a leading ``# gda-harness-version: <N>`` header on the
materialized file, riding the existing content-compare so re-materialize happens
only on a version mismatch) and the paired uninstall (autoload entry removed
first, then the files — crash-safe ordering, ADR-0018).

#654 completes the reversal: uninstall also removes the engine-generated ``.uid``
sidecar and a now-empty ``[autoload]`` section, so install → uninstall leaves
``project.godot`` byte-identical (line endings included) and no
``addons/gda_harness/`` residue — ``addons/`` itself is deliberately left in place.
Both halves RETURN the exact path/section set they touched.
"""

from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_RES_PATH,
    HARNESS_UID_FILE,
    HARNESS_UID_RES_PATH,
    HARNESS_VERSION,
    HarnessSnapshot,
    harness_artifacts,
    harness_directories,
    install_harness,
    installed_harness_version,
    uninstall_harness,
)

_NO_AUTOLOAD = 'config_version=5\n\n[application]\n\nconfig/name="t"\n'


def _autoload_line() -> str:
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def _harness_file(project):
    return project / HARNESS_RES_DIR / HARNESS_FILE


def _harness_uid(project):
    """The ``.uid`` sidecar the ENGINE writes next to an imported script (#654)."""
    return project / HARNESS_RES_DIR / HARNESS_UID_FILE


def _write_engine_uid_sidecar(project):
    """Stand in for the engine's import pass, which writes the ``.uid`` sidecar.

    The real sidecar comes from a Godot import (covered end-to-end by
    ``tests/test_e2e_daemon.py``); here only its PRESENCE matters, so the fast tests
    plant one with the shape the engine writes.
    """
    _harness_uid(project).write_text("uid://bxxxxxxxxxxxxx\n", encoding="utf-8")


def test_install_materializes_harness_and_writes_autoload_entry(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    result = install_harness(tmp_path)

    assert result.changed is True
    assert result.synced is False  # a first install is NOT a resync (#247 review)
    assert result.version == HARNESS_VERSION
    gd = tmp_path / "addons" / "gda_harness" / "gda_harness.gd"
    assert gd.exists()
    assert "extends Node" in gd.read_text(encoding="utf-8")

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert "[autoload]" in text
    # enabled-singleton form: the res:// path prefixed with "*".
    assert _autoload_line() in text


def test_installed_harness_carries_the_daemon_launched_predicate(tmp_path):
    # #362: the public `is_daemon_launched()` predicate must travel into the INSTALLED
    # copy — install copies the bundled source verbatim, so the change is not confined
    # to the in-repo file. Game code gates its logging on this predicate, so a project
    # that installed the harness must carry it.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    install_harness(tmp_path)

    body = _harness_file(tmp_path).read_text(encoding="utf-8")
    assert "func is_daemon_launched() -> bool:" in body


def test_install_is_idempotent(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    assert install_harness(tmp_path).changed is True  # first install changes it
    assert install_harness(tmp_path).changed is False  # second is a no-op

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert text.count(_autoload_line()) == 1  # not duplicated


def test_install_preserves_existing_autoloads(tmp_path):
    existing = _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n'
    (tmp_path / "project.godot").write_text(existing, encoding="utf-8")

    assert install_harness(tmp_path).changed is True

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert 'Other="*res://other.gd"' in text  # sibling autoload preserved
    assert _autoload_line() in text  # harness added
    assert text.count("[autoload]") == 1  # no duplicate section


# --- Version self-sync (#225, D1) ---------------------------------------------


def test_materialized_harness_carries_the_version_header(tmp_path):
    # _materialize prepends a `# gda-harness-version: <N>` comment header so the
    # installed copy declares its version on disk; installed_harness_version reads
    # it back. The header is sourced from HARNESS_VERSION, NOT the package version.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    install_harness(tmp_path)

    head = _harness_file(tmp_path).read_text(encoding="utf-8").splitlines()[0]
    assert head == f"# gda-harness-version: {HARNESS_VERSION}"
    assert installed_harness_version(tmp_path) == HARNESS_VERSION


def test_installed_harness_version_is_none_when_absent(tmp_path):
    # No installed harness file -> no installed version (a clean project).
    assert installed_harness_version(tmp_path) is None


def test_version_mismatch_re_materializes(tmp_path, monkeypatch):
    # The installed copy declares an OLD version: install must re-materialize so the
    # version header (and body) self-sync to the running HARNESS_VERSION, and report
    # the change. The mismatch falls out of the existing content-compare, not a
    # separate branch.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    assert install_harness(tmp_path).changed is True  # first install
    assert install_harness(tmp_path).changed is False  # idempotent same version

    # Simulate a previously-installed copy at an older version by rewriting only
    # the header to a stale value (the on-disk version no longer matches).
    gd = _harness_file(tmp_path)
    lines = gd.read_text(encoding="utf-8").splitlines()
    lines[0] = "# gda-harness-version: stale-old"
    gd.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert installed_harness_version(tmp_path) == "stale-old"

    resynced = install_harness(tmp_path)  # version mismatch -> re-materialize
    assert resynced.changed is True
    assert resynced.synced is True  # the re-materialize is a real sync
    assert installed_harness_version(tmp_path) == HARNESS_VERSION  # synced
    assert install_harness(tmp_path).changed is False  # idempotent again


def test_matched_version_does_not_rewrite_the_file(tmp_path):
    # When the installed version matches, _materialize must NOT touch the file —
    # an unconditional overwrite would bump its mtime and trip the concurrent-editor
    # prompt (ADR-0018). Assert the file's mtime is unchanged across a no-op install.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    gd = _harness_file(tmp_path)
    before = gd.stat().st_mtime_ns

    result = install_harness(tmp_path)
    assert result.changed is False
    assert result.synced is False  # nothing re-materialized
    assert gd.stat().st_mtime_ns == before  # not rewritten


def test_install_is_not_fooled_by_the_exact_line_outside_autoload(tmp_path):
    # PR #247 review (round 2): the "already present" check is scoped to [autoload].
    # The EXACT GdaHarness line sitting in another section must NOT make install
    # think the entry exists (the old global early return did) — it still adds a
    # real entry under [autoload].
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        f"config_version=5\n\n[decoy]\n\n{_autoload_line()}\n", encoding="utf-8"
    )

    result = install_harness(tmp_path)

    assert result.changed is True
    text = project_godot.read_text(encoding="utf-8")
    assert "[autoload]" in text  # a real [autoload] section was added
    # The line now appears twice: the untouched decoy + the real [autoload] entry.
    assert text.count(_autoload_line()) == 2


# --- Paired uninstall (#225, D2) ----------------------------------------------


def test_uninstall_removes_both_autoload_and_files(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    assert _harness_file(tmp_path).exists()

    result = uninstall_harness(tmp_path)

    assert result.removed is True
    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert _autoload_line() not in text  # autoload entry stripped
    assert HARNESS_AUTOLOAD_NAME not in text  # no dangling GdaHarness= line
    assert not _harness_file(tmp_path).exists()  # files deleted
    assert not (tmp_path / HARNESS_RES_DIR).exists()  # the addon dir too


def test_uninstall_scopes_removal_to_the_autoload_section(tmp_path):
    # PR #247 review: uninstall must strip the GdaHarness row from [autoload] ONLY,
    # never a same-named key in another section of project.godot.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)  # writes the real autoload entry into [autoload]
    # Inject a same-named decoy key in an unrelated section.
    project_godot.write_text(
        '[some_plugin]\n\nGdaHarness="keep-me"\n\n'
        + project_godot.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    uninstall_harness(tmp_path)

    text = project_godot.read_text(encoding="utf-8")
    assert 'GdaHarness="keep-me"' in text  # the unrelated section key is untouched
    assert _autoload_line() not in text  # the [autoload] entry is gone


def test_uninstall_removes_autoload_before_files(tmp_path, monkeypatch):
    # Crash-safe ordering (ADR-0018, D2): the [autoload] entry must be stripped
    # FIRST, then the files — so a mid-failure leaves only a harmless stray inert
    # .gd, never a dangling autoload pointing at a missing script (which makes an
    # exported game log ERR_CONTINUE and skip it at startup — error spam, not a hard
    # crash; ADR-0028). Force the file-delete step to blow up and assert the autoload
    # was already gone.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)

    import gda.harness.install as install_mod

    def boom(_project):
        raise RuntimeError("file deletion failed mid-uninstall")

    monkeypatch.setattr(install_mod, "_remove_files", boom)

    try:
        uninstall_harness(tmp_path)
    except RuntimeError:
        pass  # the file-delete step failed, as injected

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert _autoload_line() not in text  # autoload removed BEFORE the files


def test_uninstall_preserves_sibling_autoloads(tmp_path):
    existing = _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n'
    (tmp_path / "project.godot").write_text(existing, encoding="utf-8")
    install_harness(tmp_path)

    uninstall_harness(tmp_path)

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert _autoload_line() not in text  # harness entry gone
    assert 'Other="*res://other.gd"' in text  # sibling preserved


def test_uninstall_is_idempotent_when_not_installed(tmp_path):
    # Uninstall when nothing is installed is a no-op success (mirrors daemon stop).
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    assert uninstall_harness(tmp_path).removed is False  # nothing to remove

    # And a second uninstall after a real one is also a no-op.
    install_harness(tmp_path)
    assert uninstall_harness(tmp_path).removed is True
    assert uninstall_harness(tmp_path).removed is False


# --- Full reversal + mutation receipt (#654) ----------------------------------


def test_uninstall_removes_the_engine_generated_uid_sidecar(tmp_path):
    # GDA-DF-009: `daemon uninstall` reported {"removed": true} yet left
    # gda_harness.gd.uid behind — and because that file kept the directory
    # non-empty, the existing empty-directory removal never fired either.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    _write_engine_uid_sidecar(tmp_path)

    result = uninstall_harness(tmp_path)

    assert result.removed is True
    assert not _harness_uid(tmp_path).exists()  # the sidecar goes with the script
    assert not (tmp_path / HARNESS_RES_DIR).exists()  # so the dir can go too
    assert HARNESS_UID_RES_PATH in result.removed_paths


def test_uninstall_removes_the_generated_empty_autoload_section(tmp_path):
    # GDA-DF-020 (10 recurrences): the harness entry left, but the generated
    # [autoload] header stayed, so every live-QA session left project.godot
    # modified in git. Removing the last key must remove the section too.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    assert "[autoload]" in project_godot.read_text(encoding="utf-8")

    result = uninstall_harness(tmp_path)

    assert "[autoload]" not in project_godot.read_text(encoding="utf-8")
    assert result.removed_sections == ("[autoload]",)


def test_install_then_uninstall_leaves_project_godot_byte_identical(tmp_path):
    # The #654 acceptance criterion: on a project with NO pre-existing autoload
    # section, a full round trip must leave project.godot at its exact pre-install
    # bytes (not merely "no GdaHarness line") and no addons/gda_harness residue.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(_NO_AUTOLOAD, encoding="utf-8")
    before = project_godot.read_bytes()
    install_harness(tmp_path)
    _write_engine_uid_sidecar(tmp_path)
    assert project_godot.read_bytes() != before  # the install really did write

    uninstall_harness(tmp_path)

    assert project_godot.read_bytes() == before
    assert not (tmp_path / HARNESS_RES_DIR).exists()


def test_round_trip_leaves_a_pre_existing_user_autoload_section_unchanged(tmp_path):
    # The paired criterion: a USER [autoload] section is not gda's to remove, so the
    # section (and its sibling entry) survive the round trip byte-identically.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n', encoding="utf-8"
    )
    before = project_godot.read_bytes()
    install = install_harness(tmp_path)
    assert install.created_sections == ()  # gda joined a section, it did not make one

    result = uninstall_harness(tmp_path)

    assert project_godot.read_bytes() == before
    assert result.removed_sections == ()  # a user section is never dropped


def test_round_trip_preserves_crlf_line_endings(tmp_path):
    # #654: the config edit must not silently rewrite a CRLF project.godot to LF —
    # Python's default text mode would, turning a one-line autoload edit into a
    # whole-file diff. Byte-identity is asserted on the CRLF bytes themselves.
    project_godot = tmp_path / "project.godot"
    before = _NO_AUTOLOAD.replace("\n", "\r\n").encode("utf-8")
    project_godot.write_bytes(before)

    install_harness(tmp_path)

    installed = project_godot.read_bytes()
    assert b"\r\n[autoload]\r\n" in installed  # the appended section is CRLF too
    assert b"\n" not in installed.replace(b"\r\n", b"")  # no stray LF anywhere

    uninstall_harness(tmp_path)

    assert project_godot.read_bytes() == before


def test_uninstall_keeps_an_autoload_section_that_still_has_keys(tmp_path):
    # The section is dropped ONLY when the harness entry was its last key; a sibling
    # user autoload keeps the header (and everything around it) in place.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n', encoding="utf-8"
    )
    install_harness(tmp_path)

    uninstall_harness(tmp_path)

    text = project_godot.read_text(encoding="utf-8")
    assert "[autoload]" in text
    assert 'Other="*res://other.gd"' in text


def test_uninstall_drops_a_mid_file_empty_autoload_section_without_merging_neighbours(
    tmp_path,
):
    # An [autoload] section that is NOT at EOF keeps the blank line in front of it:
    # that separator still divides the two surviving sections, so dropping it would
    # glue [application] onto the preceding key.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        'config_version=5\n\n[autoload]\n\nGdaHarness="*'
        + HARNESS_RES_PATH
        + '"\n\n[application]\n\nconfig/name="t"\n',
        encoding="utf-8",
    )

    uninstall_harness(tmp_path)

    assert (
        project_godot.read_text(encoding="utf-8")
        == 'config_version=5\n\n[application]\n\nconfig/name="t"\n'
    )


def test_install_reports_the_paths_and_sections_it_created(tmp_path):
    # The install half of the #654 receipt: an agent (or a reviewer) can see exactly
    # what a `daemon start` wrote into a tracked project, outermost dir first.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    result = install_harness(tmp_path)

    assert result.created_paths == (
        "res://addons",
        "res://addons/gda_harness",
        HARNESS_RES_PATH,
    )
    assert result.created_sections == ("[autoload]",)

    # An idempotent repeat start creates nothing, so it reports nothing.
    again = install_harness(tmp_path)
    assert again.changed is False
    assert again.created_paths == ()
    assert again.created_sections == ()


def test_install_does_not_claim_an_addons_dir_the_project_already_had(tmp_path):
    # The receipt must be the paths THIS call created — a project that already keeps
    # other addons contributes res://addons itself, so gda must not claim it.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    (tmp_path / "addons").mkdir()

    result = install_harness(tmp_path)

    assert result.created_paths == ("res://addons/gda_harness", HARNESS_RES_PATH)


def test_uninstall_reports_every_path_and_section_it_removed(tmp_path):
    # The removal half of the #654 receipt, in removal order: the script, its .uid
    # sidecar, then the emptied addon directory — plus the generated section.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    _write_engine_uid_sidecar(tmp_path)

    result = uninstall_harness(tmp_path)

    assert result.removed_paths == (
        HARNESS_RES_PATH,
        HARNESS_UID_RES_PATH,
        "res://addons/gda_harness",
    )
    assert result.removed_sections == ("[autoload]",)
    # res://addons stays: an empty directory is invisible to git (so it causes none
    # of the churn this removal is for), and another addon may be about to fill it.
    assert (tmp_path / "addons").is_dir()
    assert "res://addons" not in result.removed_paths


def test_uninstall_of_a_dangling_entry_takes_the_section_with_it(tmp_path):
    # A project.godot that kept the entry after the files went (an interrupted
    # uninstall): there are no paths to remove, but the entry was the section's only
    # key, so the section goes and the receipt reports it.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD + f'\n[autoload]\n\nGdaHarness="*{HARNESS_RES_PATH}"\n',
        encoding="utf-8",
    )

    result = uninstall_harness(tmp_path)

    assert result.removed is True
    assert result.removed_paths == ()
    assert result.removed_sections == ("[autoload]",)


def test_uninstall_reports_an_empty_receipt_when_only_the_entry_remained(tmp_path):
    # The ONE combination that yields `removed` True with BOTH receipt lists empty,
    # as the HarnessUninstall docstring documents: the harness files are already gone
    # (nothing to delete) AND a sibling autoload keeps the section alive (nothing to
    # drop), so the [autoload] ENTRY is all that is left to remove.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD
        + f'\n[autoload]\n\nGdaHarness="*{HARNESS_RES_PATH}"\nOther="*res://other.gd"\n',
        encoding="utf-8",
    )

    result = uninstall_harness(tmp_path)

    assert result.removed is True
    assert result.removed_paths == ()
    assert result.removed_sections == ()
    text = project_godot.read_text(encoding="utf-8")
    assert _autoload_line() not in text  # the entry went
    assert "[autoload]" in text  # the section stayed, held up by the sibling
    assert 'Other="*res://other.gd"' in text


def test_uninstall_leaves_an_unrelated_pre_existing_empty_autoload_section(tmp_path):
    # PR #680 review, claim 5. Section removal must be scoped to the section the
    # harness entry was actually removed FROM. A project carrying its own (degenerate
    # but pre-existing) empty [autoload] section elsewhere had it silently deleted
    # too, which contradicts this module's own "a pre-existing empty section is not
    # gda's to remove" scoping.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        "config_version=5\n\n"
        "[autoload]\n\n"  # unrelated, pre-existing, already empty
        "[application]\n\n"
        'config/name="t"\n\n'
        f'[autoload]\n\nGdaHarness="*{HARNESS_RES_PATH}"\n',
        encoding="utf-8",
    )

    result = uninstall_harness(tmp_path)

    text = project_godot.read_text(encoding="utf-8")
    # The harness's own section went; the unrelated empty one survived untouched.
    assert text == (
        'config_version=5\n\n[autoload]\n\n[application]\n\nconfig/name="t"\n'
    )
    assert result.removed_sections == ("[autoload]",)  # exactly one, not two


def test_uninstall_removal_is_driven_by_the_harness_artifacts_authority(
    tmp_path, monkeypatch
):
    # PR #680 review, claim 3. `harness_artifacts` claims to be the single list of
    # what the install owns, but removal used to carry its own copy — so the claim
    # was only true of the export snapshot. Extending the authority must now extend
    # deletion AND the receipt, which is the whole point of having one list.
    import gda.harness.install as install_mod

    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)
    extra = tmp_path / HARNESS_RES_DIR / "gda_harness.gd.extra"
    extra.write_text("a future artifact\n", encoding="utf-8")

    real = install_mod.harness_artifacts
    monkeypatch.setattr(
        install_mod, "harness_artifacts", lambda project: (*real(project), extra)
    )

    result = uninstall_harness(tmp_path)

    assert not extra.exists()  # deletion followed the authority
    assert f"res://{HARNESS_RES_DIR}/gda_harness.gd.extra" in result.removed_paths
    assert not (tmp_path / HARNESS_RES_DIR).exists()  # nothing left to hold the dir


def test_harness_artifacts_names_the_script_and_its_uid_sidecar(tmp_path):
    # The single enumeration `gda export run`'s transactional snapshot reads, so its
    # strip and restore stay in step with what uninstall deletes (#654). A file
    # uninstall removes but the snapshot never captured would never come back.
    assert harness_artifacts(tmp_path) == (
        _harness_file(tmp_path),
        _harness_uid(tmp_path),
    )


# --- Snapshot-exact restoration of a failed install (#680 rechecks) -----------
# A `daemon start` installs the harness BEFORE the daemon exists, so a start that
# never comes ready must hand the project back untouched. The restore is the
# snapshot's own job and takes NOTHING from the install receipt: an install that
# rewrites a stale body or re-points an existing entry CREATES nothing (so a receipt
# has no prior bytes to put back), and an install that fails part way through
# produces no receipt at all. The snapshot therefore records absent FILES and absent
# DIRECTORIES, which is the whole reversal.


def test_snapshot_records_the_directories_the_install_would_create(tmp_path):
    # The receipt-independence hinges on this: the snapshot must know which of the
    # install's directories it created, so the restore can remove those and keep the
    # ones the project already had.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    fresh = HarnessSnapshot.capture(tmp_path)
    assert fresh.absent_directories == harness_directories(tmp_path)

    (tmp_path / "addons").mkdir()
    partial = HarnessSnapshot.capture(tmp_path)
    assert partial.absent_directories == (tmp_path / HARNESS_RES_DIR,)


def test_restore_undoes_a_fresh_install_completely(tmp_path):
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(_NO_AUTOLOAD, encoding="utf-8")
    before = project_godot.read_bytes()

    snapshot = HarnessSnapshot.capture(tmp_path)
    install_harness(tmp_path)
    undone = snapshot.restore()

    assert project_godot.read_bytes() == before
    assert not (tmp_path / "addons").exists()  # incl. the addons dir gda created
    assert undone == (
        "restored project.godot",
        f"removed {HARNESS_RES_PATH}",
        "removed res://addons/gda_harness",
        "removed res://addons",
    )


def test_restore_puts_a_stale_harness_body_back_unchanged(tmp_path):
    # PR #680 recheck, the reproduced residue. A project with a CORRECT pre-existing
    # autoload entry and a STALE harness body: install re-materializes the body and
    # creates nothing, so `changed=True` with an EMPTY receipt. The receipt-driven
    # rollback therefore did nothing and the rewrite silently stood — a failed start
    # changing tracked content with no footprint report at all. The snapshot restores
    # the stale bytes exactly, leaving them stale.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD + f'\n[autoload]\n\nGdaHarness="*{HARNESS_RES_PATH}"\n',
        encoding="utf-8",
    )
    harness = _harness_file(tmp_path)
    harness.parent.mkdir(parents=True)
    stale = b"# gda-harness-version: stale-old\nextends Node\n# my own edits\n"
    harness.write_bytes(stale)
    godot_before = project_godot.read_bytes()

    snapshot = HarnessSnapshot.capture(tmp_path)
    install = install_harness(tmp_path)
    # Precondition: this is the shape a receipt cannot express.
    assert install.changed is True and install.synced is True
    assert install.created_paths == ()
    assert harness.read_bytes() != stale  # the install really did rewrite it

    undone = snapshot.restore()

    assert harness.read_bytes() == stale  # the user's stale body is back, verbatim
    assert project_godot.read_bytes() == godot_before
    assert undone == (f"restored {HARNESS_RES_PATH}",)


def test_restore_puts_a_re_pointed_autoload_entry_back(tmp_path):
    # The other half of the same residue: an entry pointing somewhere else is
    # RE-POINTED by install, which again creates nothing. The receipt-driven rollback
    # removed the entry outright; the snapshot restores its original target.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        'config_version=5\n\n[autoload]\n\nGdaHarness="*res://legacy/old.gd"\n',
        encoding="utf-8",
    )
    before = project_godot.read_bytes()

    snapshot = HarnessSnapshot.capture(tmp_path)
    install_harness(tmp_path)
    assert 'GdaHarness="*res://legacy/old.gd"' not in project_godot.read_text(
        encoding="utf-8"
    )  # the install really did re-point it

    snapshot.restore()

    assert project_godot.read_bytes() == before  # original target restored, not dropped


def test_restore_of_an_unchanged_install_does_nothing(tmp_path):
    # The harness was already there and current, so this install wrote nothing and
    # the restore must not touch a pre-existing installation.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(_NO_AUTOLOAD, encoding="utf-8")
    install_harness(tmp_path)  # the real install
    installed_bytes = project_godot.read_bytes()

    snapshot = HarnessSnapshot.capture(tmp_path)
    repeat = install_harness(tmp_path)  # idempotent no-op
    assert repeat.changed is False
    undone = snapshot.restore()

    assert undone == ()
    assert project_godot.read_bytes() == installed_bytes
    assert _harness_file(tmp_path).exists()  # the pre-existing install survives


def test_restore_keeps_an_addons_dir_the_project_already_had(tmp_path):
    # `res://addons` is removed only because the receipt says THIS install created
    # it — a project that already had one keeps it.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    (tmp_path / "addons").mkdir()

    snapshot = HarnessSnapshot.capture(tmp_path)
    install_harness(tmp_path)
    snapshot.restore()

    assert (tmp_path / "addons").is_dir()
    assert not (tmp_path / HARNESS_RES_DIR).exists()


def test_restore_keeps_a_created_dir_that_meanwhile_gained_content(tmp_path):
    # Only NOW-EMPTY directories go: something else landing in addons/gda_harness
    # between install and restore must not be swept away with it.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    snapshot = HarnessSnapshot.capture(tmp_path)
    install_harness(tmp_path)
    bystander = tmp_path / HARNESS_RES_DIR / "notes.md"
    bystander.write_text("someone else's file\n", encoding="utf-8")

    snapshot.restore()

    assert bystander.exists()  # kept, and so is the directory holding it
    assert not _harness_file(tmp_path).exists()  # the harness itself still went


def test_restore_preserves_a_sibling_autoload_and_its_section(tmp_path):
    # The entry gda added comes off; a section that was NOT gda's to create (a
    # sibling autoload holds it up) stays, so the restore is byte-exact here too.
    project_godot = tmp_path / "project.godot"
    project_godot.write_text(
        _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n', encoding="utf-8"
    )
    before = project_godot.read_bytes()

    snapshot = HarnessSnapshot.capture(tmp_path)
    install = install_harness(tmp_path)
    assert install.created_sections == ()  # gda joined a section, it did not make one
    snapshot.restore()

    assert project_godot.read_bytes() == before


def test_snapshot_pending_names_what_a_failed_restore_leaves_behind(tmp_path):
    # When the restore itself fails, the caller reports the REAL residual delta —
    # measured against the snapshot, not predicted from the receipt — so the user is
    # told exactly which paths still differ from their pre-start state: changed
    # files first, then created directories that still exist (a restore can fail
    # after the files are already back, leaving directory-only residue; PR #680
    # recheck 3).
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    snapshot = HarnessSnapshot.capture(tmp_path)
    assert snapshot.pending() == ()  # nothing has changed yet

    install_harness(tmp_path)

    assert snapshot.pending() == (
        "project.godot",
        HARNESS_RES_PATH,
        "res://addons",
        f"res://{HARNESS_RES_DIR}",
    )


def test_snapshot_pending_marks_an_unreadable_path_instead_of_raising(tmp_path):
    # PR #688 recheck: pending() runs on error-reporting paths, where a thrown
    # measurement would displace the original failure. A path that cannot be read
    # cannot be confirmed restored — it is reported as unmeasurable residue while
    # every other path stays individually measured.
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")
    snapshot = HarnessSnapshot.capture(tmp_path)
    install_harness(tmp_path)

    project_godot = tmp_path / "project.godot"
    project_godot.chmod(0o000)
    try:
        residue = snapshot.pending()
    finally:
        project_godot.chmod(0o644)

    assert residue[0].startswith("project.godot (state unmeasurable: ")
    assert residue[1:] == (
        HARNESS_RES_PATH,
        "res://addons",
        f"res://{HARNESS_RES_DIR}",
    )


def test_ready_gates_on_template_feature_as_its_first_statement():
    # ADR-0028 defence in depth: an EXPORTED build must self-disable the harness,
    # "regardless of launch args". That holds iff `if OS.has_feature("template"):
    # return` is the FIRST executable statement of `_ready()` — it must run BEFORE
    # any launch-marker / socket handling, so an exported template build (where the
    # `template` feature is true) returns immediately.
    #
    # The behavioural proof needs a real exported template binary (the editor binary
    # has `template` == false), which requires installed export templates and the
    # Godot e2e job — skipped on PRs. This STATIC guard runs in the default PR gate
    # instead, so the property is checked on every PR rather than assumed.
    from pathlib import Path

    import gda.harness.install as install_mod

    bundled = Path(install_mod.__file__).parent / HARNESS_FILE
    lines = bundled.read_text(encoding="utf-8").splitlines()
    ready_at = next(
        i for i, line in enumerate(lines) if line.strip().startswith("func _ready(")
    )
    # The first two non-blank, non-comment body lines of _ready().
    body: list[str] = []
    for line in lines[ready_at + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        body.append(stripped)
        if len(body) == 2:
            break
    assert body[0] == 'if OS.has_feature("template"):', body
    assert body[1] == "return", body


# The bundled harness bytes, PINNED to the version that declares them (#736
# review follow-up). This current-snapshot guard makes an accidental body edit
# loud in the unit tier. The cross-revision invariant — changed body bytes MUST
# increase HARNESS_VERSION — is enforced mechanically by
# scripts/harness_version_guard.py in the required Python CI job. Updating the
# harness is therefore three deliberate edits:
#   1. edit gda_harness.gd;
#   2. bump HARNESS_VERSION in src/gda/harness/install.py;
#   3. update the current pins below (the failure carries the new hash).
PINNED_HARNESS_VERSION = "13"
PINNED_HARNESS_SHA256 = (
    "9ae73eef6375999deab1de87ec88d4a182a1791140ccff26b72477cd213d98f0"
)


def test_bundled_harness_bytes_are_pinned_to_the_declared_version():
    # Two failure directions, each with its own instruction:
    # - the harness bytes changed but HARNESS_VERSION did not -> the hash
    #   mismatches: bump the version AND re-pin;
    # - HARNESS_VERSION was bumped but this pin was not -> the version
    #   mismatches: re-pin to the new (version, hash) pair.
    import hashlib
    from pathlib import Path

    from gda.harness import install

    bundled = Path(install.__file__).parent / HARNESS_FILE
    digest = hashlib.sha256(bundled.read_bytes()).hexdigest()

    assert HARNESS_VERSION == PINNED_HARNESS_VERSION, (
        f"HARNESS_VERSION is {HARNESS_VERSION!r} but this pin says "
        f"{PINNED_HARNESS_VERSION!r}: update PINNED_HARNESS_VERSION and "
        f"PINNED_HARNESS_SHA256 (current bytes: {digest})."
    )
    assert digest == PINNED_HARNESS_SHA256, (
        f"the bundled gda_harness.gd changed (sha256 {digest}) without a "
        "version bump: bump HARNESS_VERSION in src/gda/harness/install.py and "
        "update PINNED_HARNESS_VERSION / PINNED_HARNESS_SHA256 in this file."
    )
