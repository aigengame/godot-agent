from pathlib import Path

from PIL import Image
import pytest


class NoGodotCalls:
    def import_assets(self, paths):
        raise AssertionError("invalid input must not reach import")

    def check_load(self, path):
        raise AssertionError("invalid input must not reach load")


def test_handoff_installs_before_import_and_returns_the_loaded_observation(tmp_path):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        ImportOutcome,
        LoadObservation,
        run_pipeline,
    )

    source = tmp_path / "source"
    source.mkdir()
    Image.new("RGBA", (12, 8), "red").save(source / "icon.png")
    project = tmp_path / "consumer"
    project.mkdir()
    original = (source / "icon.png").read_bytes()

    class Godot:
        def import_assets(self, paths):
            assert paths == ["res://art/icon.png"]
            assert (project / "art/icon.png").read_bytes() == original
            return ImportOutcome(facts={"engine_pass": True})

        def check_load(self, path):
            return LoadObservation(path, "Texture2D", texture_size=(12, 8))

    result = run_pipeline(
        AssetRecipe(files=(AssetFile("icon.png", "res://art/icon.png"),)),
        source_root=source,
        project_root=project,
        godot=Godot(),
    )

    assert result.failure is None
    assert result.completed == ["validate", "stage", "install", "import", "load"]
    assert result.outputs[0].state == "installed"
    assert result.observations == [
        LoadObservation("res://art/icon.png", "Texture2D", texture_size=(12, 8))
    ]
    assert (source / "icon.png").read_bytes() == original


def test_destination_conflict_leaves_all_targets_untouched(tmp_path):
    from gda_assets.api import AssetFile, AssetRecipe, run_pipeline

    source = tmp_path / "source"
    source.mkdir()
    Image.new("RGB", (2, 2), "red").save(source / "icon.png")
    project = tmp_path / "project"
    project.mkdir()
    (project / "second.png").write_bytes(b"existing authored content")

    result = run_pipeline(
        AssetRecipe(
            files=(
                AssetFile("icon.png", "res://first.png"),
                AssetFile("icon.png", "res://second.png"),
            )
        ),
        source_root=source,
        project_root=project,
        godot=NoGodotCalls(),
    )

    assert result.failure is not None
    assert result.failure.stage == "validate"
    assert result.failure.code == "destination_conflict"
    assert result.outputs == []
    assert not (project / "first.png").exists()
    assert (project / "second.png").read_bytes() == b"existing authored content"


@pytest.mark.parametrize(
    "case",
    [
        "escape",
        "cache",
        "symlink",
        "missing",
        "duplicate",
        "bad_png",
        "bad_glb",
        "empty",
    ],
)
def test_invalid_handoff_is_refused_before_any_install(tmp_path, case):
    from gda_assets.api import AssetFile, AssetRecipe, run_pipeline

    source = tmp_path / "source"
    source.mkdir()
    Image.new("RGB", (2, 2), "red").save(source / "icon.png")
    project = tmp_path / "project"
    project.mkdir()
    inputs = [AssetFile("icon.png", "res://icon.png")]
    if case == "escape":
        inputs = [AssetFile("icon.png", "res://../escape.png")]
    elif case == "cache":
        inputs = [AssetFile("icon.png", "res://.godot/icon.png")]
    elif case == "symlink":
        (project / "outside").symlink_to(source, target_is_directory=True)
        inputs = [AssetFile("icon.png", "res://outside/escape.png")]
    elif case == "missing":
        inputs = [AssetFile("missing.png", "res://icon.png")]
    elif case == "duplicate":
        inputs *= 2
    elif case == "bad_png":
        (source / "icon.png").write_bytes(b"not a png")
    elif case == "bad_glb":
        (source / "broken.glb").write_bytes(b"not a glb")
        inputs = [AssetFile("broken.glb", "res://model.glb")]
    elif case == "empty":
        inputs = []

    before = sorted(
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    )
    result = run_pipeline(
        AssetRecipe(tuple(inputs)),
        source_root=source,
        project_root=project,
        godot=NoGodotCalls(),
    )
    assert result.failure is not None
    assert result.failure.stage == "validate"
    assert result.outputs == []
    assert (
        sorted(
            p.relative_to(tmp_path).as_posix()
            for p in tmp_path.rglob("*")
            if p.is_file()
        )
        == before
    )


def test_resize_preserves_source_and_a_repeat_reports_unchanged(tmp_path):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        ImportOutcome,
        LoadObservation,
        Resize,
        run_pipeline,
    )

    source = tmp_path / "original.png"
    Image.new("RGBA", (12, 8), (255, 0, 0, 128)).save(source)
    original = source.read_bytes()
    project = tmp_path / "project"
    project.mkdir()

    class Godot:
        def import_assets(self, paths):
            return ImportOutcome(facts={"engine_pass": False})

        def check_load(self, path):
            with Image.open(project / "icon.png") as image:
                return LoadObservation(path, "Texture2D", texture_size=image.size)

    recipe = AssetRecipe(
        (AssetFile(str(source), "res://icon.png", resize=Resize(6, 4, "nearest")),)
    )
    first = run_pipeline(
        recipe, source_root=tmp_path, project_root=project, godot=Godot()
    )
    assert first.failure is None
    assert first.observations[0].texture_size == (6, 4)
    assert first.outputs[0].resize == Resize(6, 4, "nearest")
    stamp = (project / "icon.png").stat().st_mtime_ns
    second = run_pipeline(
        recipe, source_root=tmp_path, project_root=project, godot=Godot()
    )
    assert second.failure is None
    assert second.outputs[0].state == "unchanged"
    assert (project / "icon.png").stat().st_mtime_ns == stamp
    assert source.read_bytes() == original


def test_failed_file_write_preserves_that_target_and_reports_previous_install(
    tmp_path, monkeypatch
):
    import shutil
    from gda_assets.api import AssetFile, AssetRecipe, run_pipeline

    source = tmp_path / "source.png"
    Image.new("RGBA", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()
    old_second = b"authored old file"
    (project / "second.png").write_bytes(old_second)
    original_copy = shutil.copyfile
    writes = []

    def fail_second_project_write(src, dst, *args, **kwargs):
        if Path(dst).parent == project:
            writes.append(dst)
            if len(writes) == 2:
                Path(dst).write_bytes(b"partial")
                raise OSError("simulated disk write failure")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copyfile", fail_second_project_write)
    result = run_pipeline(
        AssetRecipe(
            (
                AssetFile(str(source), "res://first.png"),
                AssetFile(str(source), "res://second.png"),
            ),
            overwrite=True,
        ),
        source_root=tmp_path,
        project_root=project,
        godot=NoGodotCalls(),
    )
    assert result.failure is not None
    assert result.failure.stage == "install"
    assert result.completed == ["validate", "stage"]
    assert [(f.target, f.state) for f in result.outputs] == [
        ("res://first.png", "installed")
    ]
    assert (project / "first.png").read_bytes() == source.read_bytes()
    assert (project / "second.png").read_bytes() == old_second
    assert sorted(p.name for p in project.iterdir()) == ["first.png", "second.png"]


@pytest.mark.parametrize(
    "mapping", ["complete", "missing_member", "undeclared", "wrong_placement"]
)
def test_glb_reference_requires_explicit_membership_and_matching_placement(
    tmp_path, mapping
):
    import json
    import struct
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        ImportOutcome,
        LoadObservation,
        run_pipeline,
    )

    document = json.dumps(
        {"asset": {"version": "2.0"}, "images": [{"uri": "icon.png"}]}
    ).encode()
    document += b" " * (-len(document) % 4)
    (tmp_path / "model.glb").write_bytes(
        struct.pack(
            "<4sIIII", b"glTF", 2, 20 + len(document), len(document), 0x4E4F534A
        )
        + document
    )
    Image.new("RGB", (2, 2), "red").save(tmp_path / "icon.png")
    project = tmp_path / "project"
    project.mkdir()
    target = (
        "res://art/icon.png"
        if mapping != "wrong_placement"
        else "res://elsewhere/icon.png"
    )
    references = (target,) if mapping != "undeclared" else ()
    selected = [AssetFile("model.glb", "res://art/model.glb", references=references)]
    if mapping != "missing_member":
        selected.append(AssetFile("icon.png", target))

    class Godot:
        def import_assets(self, paths):
            assert paths == ["res://art/model.glb", "res://art/icon.png"]
            return ImportOutcome({})

        def check_load(self, path):
            return LoadObservation(
                path, "PackedScene" if path.endswith(".glb") else "Texture2D"
            )

    result = run_pipeline(
        AssetRecipe(tuple(selected)),
        source_root=tmp_path,
        project_root=project,
        godot=Godot() if mapping == "complete" else NoGodotCalls(),
    )
    if mapping == "complete":
        assert result.failure is None
        assert len(result.outputs) == 2
        assert len(result.observations) == 2
    else:
        assert result.failure is not None
        assert result.failure.stage == "validate"
        assert result.outputs == []
        assert list(project.iterdir()) == []


@pytest.mark.parametrize(
    "case", ["parent_file", "aliased_targets", "source_overlap", "metadata_alias"]
)
def test_conflicting_filesystem_mapping_is_refused_before_any_write(tmp_path, case):
    from gda_assets.api import AssetFile, AssetRecipe, run_pipeline

    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()
    inputs = [AssetFile(str(source), "res://first.png")]
    if case == "parent_file":
        (project / "blocked").write_bytes(b"file")
        inputs.append(AssetFile(str(source), "res://blocked/icon.png"))
    elif case == "aliased_targets":
        (project / "alias").symlink_to(project, target_is_directory=True)
        inputs.append(AssetFile(str(source), "res://alias/first.png"))
    elif case == "metadata_alias":
        (project / ".godot").mkdir()
        (project / "alias").symlink_to(project / ".godot", target_is_directory=True)
        inputs.append(AssetFile(str(source), "res://alias/icon.png"))
    else:
        Image.new("RGB", (2, 2), "blue").save(project / "original.png")
        inputs.extend(
            [
                AssetFile(str(source), "res://original.png"),
                AssetFile(str(project / "original.png"), "res://copy.png"),
            ]
        )
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    result = run_pipeline(
        AssetRecipe(tuple(inputs), overwrite=True),
        source_root=tmp_path,
        project_root=project,
        godot=NoGodotCalls(),
    )
    assert result.failure is not None
    assert result.failure.stage == "validate"
    assert result.outputs == []
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


def test_generated_file_import_failure_keeps_outputs_and_declared_metadata(tmp_path):
    from gda_assets.api import AssetFile, AssetRecipe, PortFailure, run_pipeline

    source = tmp_path / "generated.png"
    Image.new("RGB", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()
    cause = {
        "category": "engine",
        "code": "launch_failed",
        "diagnostics": "engine stderr",
    }

    class BrokenGodot(NoGodotCalls):
        def import_assets(self, paths):
            raise PortFailure("launch_failed", "Import could not start", cause=cause)

    result = run_pipeline(
        AssetRecipe(
            (AssetFile(str(source), "res://icon.png"),),
            source_mode="imagegen",
            provenance={"model": "caller-selected-model"},
        ),
        source_root=tmp_path,
        project_root=project,
        godot=BrokenGodot(),
    )
    assert result.failure is not None
    assert result.failure.stage == "import"
    assert result.failure.cause == cause
    assert result.completed == ["validate", "stage", "install"]
    assert result.source_mode == "imagegen"
    assert result.caller_declared_provenance == {"model": "caller-selected-model"}
    assert result.observations == []
    assert result.outputs[0].state == "installed"
    assert (project / "icon.png").read_bytes() == source.read_bytes()


def test_png_with_valid_chunk_checksums_but_invalid_pixels_is_refused(tmp_path):
    import struct
    import zlib
    from gda_assets.api import AssetFile, AssetRecipe, run_pipeline

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    image = b"\x89PNG\r\n\x1a\n"
    image += chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
    image += chunk(b"IDAT", b"invalid compressed pixels") + chunk(b"IEND", b"")
    (tmp_path / "broken.png").write_bytes(image)
    project = tmp_path / "project"
    project.mkdir()
    result = run_pipeline(
        AssetRecipe((AssetFile("broken.png", "res://icon.png"),)),
        source_root=tmp_path,
        project_root=project,
        godot=NoGodotCalls(),
    )
    assert result.failure is not None
    assert result.failure.stage == "validate"
    assert result.failure.code == "invalid_asset"
    assert result.outputs == []
    assert list(project.iterdir()) == []
