from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gda_assets.adapters.observations import LocalObservationFiles
from gda_assets.application.ports import PortFailure
from gda_assets.domain.observations import ContentObservations


def test_digest_rejects_malformed_and_escaping_resource_paths_without_reading_outside(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read")
    (project / "escape").symlink_to(tmp_path, target_is_directory=True)
    files = LocalObservationFiles(project)

    for resource in (
        str(outside),
        "user://secret.txt",
        "res://",
        "res:///secret.txt",
        "res://../secret.txt",
        "res://escape/secret.txt",
        "res://folder\\secret.txt",
        "res://folder:secret.txt",
    ):
        result = files.digest(resource)
        assert result.path == resource
        assert result.state == "unavailable"
        assert result.sha256 is None
        assert result.reason and "resource path" in result.reason.lower()


def test_digest_observes_project_and_host_published_cache_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    cache = project / ".godot" / "imported" / "model.glb-deadbeef.scn"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"abc")

    result = LocalObservationFiles(project).digest(
        "res://.godot/imported/model.glb-deadbeef.scn"
    )

    assert result.state == "observed"
    assert result.size == 3
    assert result.sha256 == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert result.reason is None


def test_digest_reports_missing_non_file_and_per_file_limit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "folder").mkdir()
    large = project / "large.bin"
    with large.open("wb") as stream:
        stream.truncate(256 * 1024 * 1024 + 1)
    files = LocalObservationFiles(project)

    missing = files.digest("res://missing.bin")
    directory = files.digest("res://folder")
    oversized = files.digest("res://large.bin")

    assert missing.state == "missing" and missing.reason
    assert directory.state == "unavailable" and directory.reason
    assert oversized.state == "unavailable" and oversized.reason
    assert "268435456" in oversized.reason
    assert all(item.sha256 is None for item in (missing, directory, oversized))


def test_digest_refuses_a_fifo_without_blocking_on_open(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    os.mkfifo(project / "engine.pipe")
    probe = (
        "from pathlib import Path; "
        "from gda_assets.adapters.observations import LocalObservationFiles; "
        f"result=LocalObservationFiles(Path({str(project)!r})).digest('res://engine.pipe'); "
        "assert result.state == 'unavailable' and result.reason"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=2
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_digest_limits_distinct_paths_and_total_streamed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = LocalObservationFiles(project)
    for index in range(128):
        assert files.digest(f"res://missing-{index}.bin").state == "missing"
    distinct = files.digest("res://one-too-many.bin")
    assert distinct.state == "unavailable"
    assert distinct.reason
    assert "128 distinct" in distinct.reason

    import gda_assets.adapters.observations as module

    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 5)
    (project / "first.bin").write_bytes(b"abc")
    (project / "second.bin").write_bytes(b"def")
    bounded = LocalObservationFiles(project)
    assert bounded.digest("res://first.bin").state == "observed"
    total = bounded.digest("res://second.bin")
    assert total.state == "unavailable"
    assert total.reason
    assert "5 byte total" in total.reason
    assert total.sha256 is None


def test_digest_discards_hash_when_path_moves_during_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    path = project / "moving.bin"
    replacement = project / "replacement.bin"
    path.write_bytes(b"before")
    replacement.write_bytes(b"after!")
    real_open = Path.open

    class MovingStream:
        def __init__(self, stream):
            self.stream = stream
            self.moved = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            chunk = self.stream.read(size)
            if chunk and not self.moved:
                self.moved = True
                os.replace(replacement, path)
            return chunk

    def moving_open(self, *args, **kwargs):
        stream = real_open(self, *args, **kwargs)
        return MovingStream(stream) if self == path else stream

    monkeypatch.setattr(Path, "open", moving_open)

    result = LocalObservationFiles(project).digest("res://moving.bin")

    assert result.state == "changed"
    assert result.sha256 is None
    assert result.size is None
    assert result.reason and "changed" in result.reason
    assert "inode" not in result.reason and "mtime" not in result.reason


def test_digest_detects_resource_symlink_retargeting_during_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    first = project / "first.bin"
    second = project / "second.bin"
    selected = project / "selected.bin"
    first.write_bytes(b"first!")
    second.write_bytes(b"second")
    selected.symlink_to(first)
    real_open = Path.open

    class RetargetingStream:
        def __init__(self, stream):
            self.stream = stream
            self.retargeted = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            chunk = self.stream.read(size)
            if chunk and not self.retargeted:
                self.retargeted = True
                selected.unlink()
                selected.symlink_to(second)
            return chunk

    def retargeting_open(self, *args, **kwargs):
        stream = real_open(self, *args, **kwargs)
        return RetargetingStream(stream) if self == first else stream

    monkeypatch.setattr(Path, "open", retargeting_open)

    result = LocalObservationFiles(project).digest("res://selected.bin")

    assert result.state == "changed"
    assert result.sha256 is None
    assert result.size is None


def test_validate_output_refuses_existing_and_broken_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = LocalObservationFiles(project)
    existing = tmp_path / "report.json"
    existing.write_text("keep")
    broken = tmp_path / "broken.json"
    broken.symlink_to(tmp_path / "absent.json")

    for path in (existing, broken):
        with pytest.raises(PortFailure) as caught:
            files.validate_output(path)
        assert caught.value.code == "invalid_collection"
    assert existing.read_text() == "keep"
    assert broken.is_symlink()


def test_save_creates_exclusively_and_file_matches_returned_observations(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    files = LocalObservationFiles(project)
    observations = ContentObservations(
        status="stable",
        declared_output_sha256={"res://icon.png": "00ff"},
        issues=["caller value preserved"],
    )
    output = tmp_path / "observations.json"

    files.validate_output(output)
    files.save(observations, output)

    assert observations.saved_to == str(output.resolve())
    returned_json = json.loads(json.dumps(asdict(observations)))
    assert json.loads(output.read_text()) == returned_json
    assert '": "' not in output.read_text()
    with pytest.raises(PortFailure):
        files.save(observations, output)
    assert json.loads(output.read_text()) == returned_json
