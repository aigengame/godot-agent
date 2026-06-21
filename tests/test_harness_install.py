"""gda harness install (#7, ADR-0018): idempotent project.godot autoload write.

Pure filesystem: materialize the bundled harness under ``res://addons/`` and add
its ``[autoload]`` entry to ``project.godot`` — a one-time, install-time write
(never a per-launch mutation), idempotent and order-preserving.
"""

from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_RES_PATH,
    install_harness,
)

_NO_AUTOLOAD = 'config_version=5\n\n[application]\n\nconfig/name="t"\n'


def _autoload_line() -> str:
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def test_install_materializes_harness_and_writes_autoload_entry(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    changed = install_harness(tmp_path)

    assert changed is True
    gd = tmp_path / "addons" / "gda_harness" / "gda_harness.gd"
    assert gd.exists()
    assert "extends Node" in gd.read_text(encoding="utf-8")

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert "[autoload]" in text
    # enabled-singleton form: the res:// path prefixed with "*".
    assert _autoload_line() in text


def test_install_is_idempotent(tmp_path):
    (tmp_path / "project.godot").write_text(_NO_AUTOLOAD, encoding="utf-8")

    assert install_harness(tmp_path) is True  # first install changes the project
    assert install_harness(tmp_path) is False  # second is a no-op

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert text.count(_autoload_line()) == 1  # not duplicated


def test_install_preserves_existing_autoloads(tmp_path):
    existing = _NO_AUTOLOAD + '\n[autoload]\n\nOther="*res://other.gd"\n'
    (tmp_path / "project.godot").write_text(existing, encoding="utf-8")

    assert install_harness(tmp_path) is True

    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert 'Other="*res://other.gd"' in text  # sibling autoload preserved
    assert _autoload_line() in text  # harness added
    assert text.count("[autoload]") == 1  # no duplicate section
