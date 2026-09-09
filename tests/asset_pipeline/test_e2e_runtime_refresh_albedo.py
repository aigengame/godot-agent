"""Imported embedded-image changes remain visible across selected live instances."""

import json
import os

import pytest

from tests.albedo_support import write_albedo_glb
from tests.conftest import project_godot
from tests.support import Gda, assert_windowed_ok

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.xdist_group("windowed"),
]

MODEL = "res://model.glb"
NODE = "/root/Test/Model"


def _digest(sample):
    content = sample["content"]
    assert content["complete"] is True, content
    assert content["measurement"] == "godot-static-model-content-v3"
    assert content["unsupported"] == []
    assert content["omitted"] == []
    assert len(content["digest"]) == 64
    return content["digest"]


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_embedded_image_change_preserves_summaries_but_rejects_stale_content(
    tmp_path, monkeypatch
):
    project, source = tmp_path / "project", tmp_path / "source"
    project.mkdir()
    source.mkdir()
    (project / "project.godot").write_text(
        project_godot(
            name="gda-albedo-refresh-e2e",
            extra=(
                'run/main_scene="res://test.tscn"\n\n'
                '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
            ),
        )
    )
    (project / "test.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n"
        '[ext_resource type="Script" path="res://startup.gd" id="1"]\n'
        '[node name="Test" type="Node3D"]\nscript = ExtResource("1")\n'
        '[node name="Camera3D" type="Camera3D" parent="."]\nposition = Vector3(0,0,4)\n'
    )
    (project / "startup.gd").write_text(
        "extends Node3D\nfunc _ready():\n"
        '\tvar model = (load("res://model.glb") as PackedScene).instantiate()\n'
        '\tmodel.name = "Model"\n\tadd_child(model)\n'
    )
    write_albedo_glb(source / "a.glb", color=(255, 32, 16, 255))
    write_albedo_glb(source / "b.glb", color=(16, 32, 255, 255))
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)

    def handoff(filename, *, refresh=False):
        args = [
            "asset-pipeline",
            "run",
            "--source-root",
            str(source),
            "--files",
            json.dumps([{"source": filename, "target": MODEL}]),
            "--overwrite",
        ]
        if refresh:
            args += [
                "--refresh",
                json.dumps(
                    {
                        "path": MODEL,
                        "scene": "res://test.tscn",
                        "node": NODE,
                        "windowed": True,
                    }
                ),
            ]
        return run.json(*args)

    try:
        handoff("a.glb")
        imported_a = run.json("resource", "inspect-model-content", "--path", MODEL)
        report_a = run.json("resource", "inspect-model", MODEL)
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        run.json("daemon", "wait-ready", "--timeout", "25")
        live_a = run.json("game", "inspect-model-content", "--node", NODE)
        assert _digest(live_a) == _digest(imported_a)

        handoff("b.glb")
        imported_b = run.json("resource", "inspect-model-content", "--path", MODEL)
        report_b = run.json("resource", "inspect-model", MODEL)
        stale = run.json("game", "inspect-model-content", "--node", NODE)
        for field in ("path", "summary", "bounds", "nodes"):
            assert report_a[field] == report_b[field]
        assert _digest(imported_a) != _digest(imported_b)
        assert _digest(stale) == _digest(imported_a)
        assert stale["session_id"] == live_a["session_id"]

        result = handoff("b.glb", refresh=True)
        refresh = result["pipeline"]["refresh"]
        assert refresh["status"] == "verified"
        assert refresh["comparison"] == {"status": "match", "reasons": []}
        assert refresh["ready_session"]["session_id"] != live_a["session_id"]
        assert _digest(refresh["imported"]) == _digest(imported_b)
        assert _digest(refresh["instance"]) == _digest(imported_b)
    finally:
        stopped = run("daemon", "stop")
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
