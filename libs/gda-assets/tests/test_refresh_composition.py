"""Composition boundaries between disk observations and runtime refresh."""

import json
import os
import struct

import pytest

from gda_assets.api import (
    AssetFile,
    AssetRecipe,
    CollectionRequest,
    ImportAssetFacts,
    ImportedContent,
    ImportOutcome,
    LoadObservation,
    ModelContent,
    PortFailure,
    ProductionOutput,
    ProductionRequest,
    RefreshRequest,
    ReadyObservation,
    SessionState,
    StartObservation,
    StopObservation,
    run_pipeline,
)


CONTENT = ModelContent(
    "godot-static-model-content-v3", "4.6.3.stable.official", True, "a" * 64
)


def _glb_bytes() -> bytes:
    document = json.dumps({"asset": {"version": "2.0"}}).encode()
    document += b" " * (-len(document) % 4)
    return (
        struct.pack("<4sIII4s", b"glTF", 2, 20 + len(document), len(document), b"JSON")
        + document
    )


def _handoff(tmp_path):
    source = tmp_path / "source.glb"
    source.write_bytes(_glb_bytes())
    project = tmp_path / "project"
    project.mkdir()
    (project / "model.glb.import").write_bytes(b"configuration")
    (project / "model.scn").write_bytes(b"artifact")
    return project, AssetRecipe((AssetFile(str(source), "res://model.glb"),))


class Port:
    def __init__(self, project, *, collection_failure=None, ready_failure=False):
        self.project = project
        self.collection_failure = collection_failure
        self.ready_failure = ready_failure
        self.runtime_calls = []
        self.session = "old"

    def observe_import(self, paths):
        return [
            ImportAssetFacts(
                paths[0],
                "cached",
                "res://model.glb.import",
                ("res://model.scn",),
                "scene",
                paths[0],
            )
        ]

    def import_assets(self, paths):
        if self.collection_failure == "changed":
            (self.project / "model.glb").write_bytes(_glb_bytes() + b"changed")
        if self.collection_failure == "incomplete":
            (self.project / "model.scn").unlink()
        return ImportOutcome({"engine_pass": True})

    def check_load(self, path):
        return LoadObservation(path, "PackedScene", engine={"string": "4.6.3"})

    def inspect_content(self, path, **limits):
        self.runtime_calls.append("inspect")
        return ImportedContent(path, CONTENT)

    def status(self):
        self.runtime_calls.append("status")
        return SessionState(True, 7, True, self.session)

    def stop(self):
        self.runtime_calls.append("stop")
        return StopObservation(True, 7)

    def start(self, scene, *, windowed):
        self.runtime_calls.append("start")
        self.session = "new"
        return StartObservation(False, False, "1", (), (), 8, windowed, False)

    def wait_ready(self, timeout):
        self.runtime_calls.append("ready")
        if self.ready_failure:
            raise PortFailure("engine_session_not_running", "readiness failed")
        return ReadyObservation(8, True)

    def observe_content(self, node, **limits):
        raise AssertionError("not reached by these failure scenarios")

    def capture(self, output):
        raise AssertionError("no capture requested")


def _refresh() -> RefreshRequest:
    return RefreshRequest(
        "res://model.glb", "res://test.tscn", "/root/Test/Model", True
    )


def test_saved_disk_facts_survive_a_later_runtime_readiness_failure(tmp_path):
    project, recipe = _handoff(tmp_path)
    saved = tmp_path / "observations.json"
    port = Port(project, ready_failure=True)

    result = run_pipeline(
        recipe,
        source_root=None,
        project_root=project,
        godot=port,
        collection=CollectionRequest(save_to=saved),
        import_observer=port,
        refresh=_refresh(),
        runtime=port,
    )

    assert result.failure is not None
    assert result.failure.stage == "refresh.ready"
    assert result.content_observations is not None
    assert result.content_observations.status == "stable"
    assert result.content_observations.saved_to == str(saved)
    assert json.loads(saved.read_text())["status"] == "stable"
    assert "observe" in result.completed
    assert port.runtime_calls[:5] == ["inspect", "status", "stop", "start", "ready"]


@pytest.mark.parametrize(
    ("collection_failure", "status", "code"),
    [
        ("incomplete", "incomplete", "observation_incomplete"),
        ("changed", "changed", "observation_changed"),
    ],
)
def test_unstable_disk_collection_prevents_any_runtime_reset(
    tmp_path, collection_failure, status, code
):
    project, recipe = _handoff(tmp_path)
    port = Port(project, collection_failure=collection_failure)

    result = run_pipeline(
        recipe,
        source_root=None,
        project_root=project,
        godot=port,
        collection=CollectionRequest(),
        import_observer=port,
        refresh=_refresh(),
        runtime=port,
    )

    assert result.failure is not None
    assert result.failure.code == code
    assert result.content_observations is not None
    assert result.content_observations.status == status
    assert result.refresh is None
    assert port.runtime_calls == []


def test_completed_production_is_not_replayed_after_runtime_readiness_failure(
    tmp_path,
):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source.blend"
    source.write_bytes(b"BLENDER-v300")
    calls = tmp_path / "producer-calls"
    executable = tmp_path / "fake-blender"
    payload = _glb_bytes().hex()
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "calls.write_text(calls.read_text() + 'x' if calls.exists() else 'x')\n"
        "request = json.loads(pathlib.Path(sys.argv[-1]).read_text())\n"
        f"pathlib.Path(request['output']).write_bytes(bytes.fromhex({payload!r}))\n"
        "pathlib.Path(request['result']).write_text(json.dumps({"
        "'completed':['inspect','prepare','export']}))\n"
    )
    os.chmod(executable, 0o755)
    port = Port(project, ready_failure=True)

    result = run_pipeline(
        AssetRecipe(()),
        source_root=None,
        project_root=project,
        godot=port,
        production=ProductionRequest(
            "blender_saved",
            (ProductionOutput("model", "res://model.glb"),),
            {
                "source": str(source),
                "scene": "Scene",
                "root": "Model",
                "executable": str(executable),
            },
        ),
        refresh=_refresh(),
        runtime=port,
    )

    assert result.failure is not None
    assert result.failure.stage == "refresh.ready"
    assert calls.read_text() == "x"
    assert result.completed.count("produce") == 1
    assert result.production is not None
    assert result.production["source_preserved"] is True
    assert (project / "model.glb").is_file()
