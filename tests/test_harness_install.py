"""gda harness install (#7, #225, ADR-0018): idempotent project.godot autoload write.

Pure filesystem: materialize the bundled harness under ``res://addons/`` and add
its ``[autoload]`` entry to ``project.godot`` — a one-time, install-time write
(never a per-launch mutation), idempotent and order-preserving. #225 adds the
version self-sync (a leading ``# gda-harness-version: <N>`` header on the
materialized file, riding the existing content-compare so re-materialize happens
only on a version mismatch) and the paired uninstall (autoload entry removed
first, then the files — crash-safe ordering, ADR-0018).
"""

from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_FILE,
    HARNESS_RES_DIR,
    HARNESS_RES_PATH,
    HARNESS_VERSION,
    install_harness,
    installed_harness_version,
    uninstall_harness,
)

_NO_AUTOLOAD = 'config_version=5\n\n[application]\n\nconfig/name="t"\n'


def _autoload_line() -> str:
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def _harness_file(project):
    return project / HARNESS_RES_DIR / HARNESS_FILE


def test_install_materializes_harness_and_writes_autoload_entry(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    result = install_harness(tmp_path)

    assert result.changed is True
    assert result.synced is True  # the harness file was materialized
    assert result.version == HARNESS_VERSION
    gd = tmp_path / "addons" / "gda_harness" / "gda_harness.gd"
    assert gd.exists()
    assert "extends Node" in gd.read_text(encoding="utf-8")

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert "[autoload]" in text
    # enabled-singleton form: the res:// path prefixed with "*".
    assert _autoload_line() in text


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


def test_uninstall_removes_autoload_before_files(tmp_path, monkeypatch):
    # Crash-safe ordering (ADR-0018, D2): the [autoload] entry must be stripped
    # FIRST, then the files — so a mid-failure leaves only a harmless stray inert
    # .gd, never a dangling autoload pointing at a missing script (which crashes an
    # exported game). Force the file-delete step to blow up and assert the autoload
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
