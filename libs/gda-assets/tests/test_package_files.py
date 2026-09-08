from dataclasses import replace
import hashlib

import pytest

from gda_assets.adapters import file_copy
from gda_assets.adapters import package_files
from gda_assets.adapters.file_copy import copy_with_sha256
from gda_assets.adapters.package_files import PackageFiles
from gda_assets.application.ports import PortFailure


def test_snapshot_copies_same_bytes_with_digest_and_removes_owned_root(tmp_path):
    source = tmp_path / "game.pck"
    source.write_bytes(b"Godot package bytes")
    files = PackageFiles()

    snapshot = files.snapshot(source)

    assert snapshot.source == str(source.resolve())
    assert snapshot.path.is_absolute()
    assert snapshot.root.is_absolute()
    assert snapshot.path.read_bytes() == source.read_bytes()
    assert snapshot.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert snapshot.size_bytes == source.stat().st_size
    files.remove(snapshot)
    assert not snapshot.root.exists()


@pytest.mark.parametrize("kind", ["suffix", "directory"])
def test_snapshot_rejects_invalid_source(tmp_path, kind):
    source = tmp_path / ("game.zip" if kind == "suffix" else "game.pck")
    if kind == "suffix":
        source.write_bytes(b"package")
    else:
        source.mkdir()

    with pytest.raises(PortFailure) as failure:
        PackageFiles().snapshot(source)

    assert failure.value.code == "invalid_package"


def test_snapshot_rejects_size_over_limit(tmp_path, monkeypatch):
    source = tmp_path / "game.pck"
    source.write_bytes(b"12345")
    monkeypatch.setattr(package_files, "MAX_PACKAGE_BYTES", 4)

    with pytest.raises(PortFailure) as failure:
        PackageFiles().snapshot(source)

    assert failure.value.code == "invalid_package"


def test_remove_rejects_forged_snapshot_and_preserves_unrelated_paths(tmp_path):
    source = tmp_path / "game.pck"
    source.write_bytes(b"package")
    files = PackageFiles()
    snapshot = files.snapshot(source)
    unrelated = tmp_path / "keep"
    unrelated.mkdir()
    (unrelated / "data").write_text("keep")

    with pytest.raises(PortFailure) as failure:
        files.remove(replace(snapshot, root=unrelated, path=unrelated / "package.pck"))

    assert failure.value.code == "package_cleanup_failed"
    assert (unrelated / "data").read_text() == "keep"
    assert snapshot.path.exists()
    files.remove(snapshot)


def test_snapshot_cleans_partial_directory_when_copy_fails(tmp_path, monkeypatch):
    source = tmp_path / "game.pck"
    source.write_bytes(b"package")
    created = tmp_path / "created"

    def make_directory(**_):
        created.mkdir()
        return str(created)

    monkeypatch.setattr(package_files.tempfile, "mkdtemp", make_directory)
    monkeypatch.setattr(
        package_files,
        "copy_with_sha256",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )

    with pytest.raises(PortFailure) as failure:
        PackageFiles().snapshot(source)

    assert failure.value.code == "package_stage_failed"
    assert not created.exists()


def test_snapshot_reports_cleanup_failure_with_stage_context(tmp_path, monkeypatch):
    source = tmp_path / "game.pck"
    source.write_bytes(b"package")
    created = tmp_path / "created"

    def make_directory(**_):
        created.mkdir()
        return str(created)

    monkeypatch.setattr(package_files.tempfile, "mkdtemp", make_directory)
    monkeypatch.setattr(
        package_files,
        "copy_with_sha256",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )
    monkeypatch.setattr(
        package_files.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(PortFailure) as failure:
        PackageFiles().snapshot(source)

    assert failure.value.code == "package_cleanup_failed"
    assert failure.value.cause == {
        "stage_error": "copy failed",
        "retained_root": str(created),
    }


@pytest.mark.parametrize(
    ("max_bytes", "message"),
    [(None, "changed while copying"), (8, "grew beyond")],
)
def test_copy_rejects_source_changed_during_stream(
    tmp_path, monkeypatch, max_bytes, message
):
    source = tmp_path / "game.pck"
    destination = tmp_path / "copy.pck"
    source.write_bytes(b"package")
    original_open = type(source).open

    class ChangingReader:
        def __init__(self, stream):
            self.stream = stream
            self.changed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            chunk = self.stream.read(size)
            if chunk and not self.changed:
                self.changed = True
                with original_open(source, "ab") as writer:
                    writer.write(b"changed")
            return chunk

    def changing_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == source and args and args[0] == "rb":
            return ChangingReader(stream)
        return stream

    monkeypatch.setattr(file_copy, "_READ_SIZE", 1)
    monkeypatch.setattr(type(source), "open", changing_open)

    with pytest.raises(OSError, match=message):
        copy_with_sha256(source, destination, max_bytes=max_bytes)

    if max_bytes is None:
        assert not destination.exists()


def test_remove_rejects_replaced_owned_directory(tmp_path):
    source = tmp_path / "game.pck"
    source.write_bytes(b"package")
    files = PackageFiles()
    snapshot = files.snapshot(source)
    moved = tmp_path / "original-staging"
    snapshot.root.rename(moved)
    snapshot.root.mkdir()
    keep = snapshot.root / "keep"
    keep.write_text("unrelated")

    with pytest.raises(PortFailure) as failure:
        files.remove(snapshot)

    assert failure.value.code == "package_cleanup_failed"
    assert keep.read_text() == "unrelated"
    assert (moved / "package.pck").read_bytes() == b"package"
