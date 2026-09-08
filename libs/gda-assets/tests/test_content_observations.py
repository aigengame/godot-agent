from PIL import Image
import pytest


def test_cold_handoff_collects_selected_disk_facts_and_repeat_is_stable(tmp_path):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        CollectionRequest,
        ImportAssetFacts,
        ImportOutcome,
        LoadObservation,
        run_pipeline,
    )

    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()
    config = project / "source.png.import"
    artifact = project / "imported.bin"

    class Godot:
        def observe_import(self, paths):
            return [
                ImportAssetFacts(
                    path=paths[0],
                    cache_status="cached" if config.exists() else "missing",
                    configuration="res://source.png.import"
                    if config.exists()
                    else None,
                    artifacts=("res://imported.bin",) if config.exists() else (),
                    declared_importer="texture" if config.exists() else None,
                    declared_source_file=paths[0] if config.exists() else None,
                )
            ]

        def import_assets(self, paths):
            config.write_bytes(b"configured import bytes")
            artifact.write_bytes(b"abc")
            return ImportOutcome(facts={"engine_pass": True})

        def check_load(self, path):
            return LoadObservation(path, "Texture2D", engine={"string": "4.6.3"})

    port = Godot()
    recipe = AssetRecipe((AssetFile(str(source), "res://source.png"),))

    def run():
        return run_pipeline(
            recipe,
            source_root=None,
            project_root=project,
            godot=port,
            collection=CollectionRequest(),
            import_observer=port,
        )

    first, repeat = run(), run()
    assert first.failure is None
    content = first.content_observations
    repeat_content = repeat.content_observations
    assert content is not None
    assert repeat_content is not None
    assert content.status == "stable"
    asset = content.assets[0]
    assert asset.configuration_before is None
    assert asset.configuration_after is not None
    assert asset.source_before is not None
    assert asset.source_after is not None
    assert asset.configuration_after.sha256 is not None
    assert asset.artifacts[0].size == 3
    assert (
        asset.artifacts[0].sha256
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert asset.source_before.sha256 == asset.source_after.sha256
    assert asset.source_after == repeat_content.assets[0].source_after
    assert asset.configuration_after == repeat_content.assets[0].configuration_after
    assert asset.engine == {"string": "4.6.3"}
    assert content.limitations


@pytest.mark.parametrize("changed", ["source", "configuration", "dependency"])
def test_changed_input_during_import_refuses_mixed_observation(tmp_path, changed):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        CollectionRequest,
        ImportAssetFacts,
        ImportOutcome,
        LoadObservation,
        run_pipeline,
    )

    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "red").save(source)
    config = project / "icon.png.import"
    config.write_bytes(b"before")
    artifact = project / "imported.bin"
    artifact.write_bytes(b"abc")

    class Godot:
        def observe_import(self, paths):
            return [
                ImportAssetFacts(
                    path,
                    "cached",
                    "res://icon.png.import",
                    ("res://imported.bin",),
                    "texture",
                    path,
                )
                for path in paths
            ]

        def import_assets(self, paths):
            affected = {
                "source": project / "icon.png",
                "configuration": config,
                "dependency": project / "texture.png",
            }[changed]
            affected.write_bytes(b"changed input")
            return ImportOutcome(facts={"engine_pass": True})

        def check_load(self, path):
            return LoadObservation(path, "Texture2D")

    port = Godot()
    result = run_pipeline(
        AssetRecipe(
            (
                AssetFile(
                    str(source), "res://icon.png", references=("res://texture.png",)
                ),
                AssetFile(str(source), "res://texture.png"),
            )
        ),
        source_root=None,
        project_root=project,
        godot=port,
        collection=CollectionRequest(),
        import_observer=port,
    )
    failure = result.failure
    content = result.content_observations
    assert failure is not None
    assert content is not None
    assert failure.code == "observation_changed"
    assert content.status == "changed"
    assert content.changes
    source_before = content.assets[0].source_before
    assert source_before is not None
    assert source_before.sha256
    assert (tmp_path / "source.png").read_bytes() != b"changed input"


def test_import_failure_retains_before_and_after_facts_without_certifying_completion(
    tmp_path,
):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        CollectionRequest,
        ImportAssetFacts,
        PortFailure,
        run_pipeline,
    )

    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()

    class Godot:
        def observe_import(self, paths):
            return [ImportAssetFacts(paths[0], "missing")]

        def import_assets(self, paths):
            raise PortFailure("operation_failed", "native import refused")

        def check_load(self, path):
            raise AssertionError("failed import must not load")

    port = Godot()
    result = run_pipeline(
        AssetRecipe((AssetFile(str(source), "res://source.png"),)),
        source_root=None,
        project_root=project,
        godot=port,
        collection=CollectionRequest(),
        import_observer=port,
    )
    failure = result.failure
    observed = result.content_observations
    assert failure is not None
    assert observed is not None
    assert failure.message == "native import refused"
    assert observed.status == "incomplete"
    asset = observed.assets[0]
    assert asset.source_before is not None
    assert asset.source_after is not None
    assert asset.import_after is not None
    assert asset.source_after == asset.source_before
    assert asset.import_after.cache_status == "missing"
    assert "import" not in result.completed


@pytest.fixture
def handoff(tmp_path):
    from gda_assets.api import (
        AssetFile,
        AssetRecipe,
        ImportAssetFacts,
        ImportOutcome,
        LoadObservation,
        run_pipeline,
    )

    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "red").save(source)
    project = tmp_path / "project"
    project.mkdir()
    config = project / "source.png.import"
    config.write_bytes(b"config")
    artifact = project / "imported.bin"
    artifact.write_bytes(b"abc")

    class Godot:
        calls = []

        def observe_import(self, paths):
            self.calls.append("observe")
            return [
                ImportAssetFacts(
                    paths[0],
                    "cached",
                    "res://source.png.import",
                    ("res://imported.bin",),
                    "texture",
                    paths[0],
                )
            ]

        def import_assets(self, paths):
            self.calls.append("import")
            return ImportOutcome(facts={"engine_pass": False})

        def check_load(self, path):
            return LoadObservation(path, "Texture2D")

    port = Godot()

    def run(collection=None):
        return run_pipeline(
            AssetRecipe(
                (AssetFile(str(source), "res://source.png"),),
                provenance={"scene": "CallerScene"},
            ),
            source_root=None,
            project_root=project,
            godot=port,
            collection=collection,
            import_observer=port if collection else None,
        )

    return run, port, project


def test_missing_artifact_is_incomplete_with_source_facts_retained(handoff):
    from gda_assets.api import CollectionRequest

    run, _, project = handoff
    (project / "imported.bin").unlink()
    result = run(CollectionRequest())
    assert result.failure.code == "observation_incomplete"
    assert result.content_observations.status == "incomplete"
    assert result.content_observations.assets[0].source_after.sha256
    assert result.content_observations.assets[0].artifacts[0].state == "missing"


def test_declared_hash_mismatch_stops_before_import_with_observed_hash(handoff):
    from gda_assets.api import CollectionRequest

    run, port, _ = handoff
    result = run(
        CollectionRequest(declared_output_sha256={"res://source.png": "0" * 64})
    )
    assert result.failure.code == "declared_hash_mismatch"
    assert "import" not in port.calls
    assert result.content_observations.assets[0].source_before.sha256 != "0" * 64
    assert result.content_observations.declared_output_sha256 == {
        "res://source.png": "0" * 64
    }
    assert result.caller_declared_provenance == {"scene": "CallerScene"}


def test_change_while_other_files_are_hashed_is_detected(handoff, monkeypatch):
    from gda_assets.api import CollectionRequest
    from gda_assets.adapters.observations import LocalObservationFiles

    run, _, project = handoff
    original = LocalObservationFiles.digest
    changed = False

    def digest(self, path):
        nonlocal changed
        if path == "res://imported.bin" and not changed:
            (project / "source.png").write_bytes(b"changed while hashing artifact")
            changed = True
        return original(self, path)

    monkeypatch.setattr(LocalObservationFiles, "digest", digest)
    result = run(CollectionRequest())
    assert result.failure.code == "observation_changed"
    assert result.content_observations.status == "changed"
    assert any(
        change.before.path == "res://source.png"
        for change in result.content_observations.changes
    )


def test_explicit_save_matches_result_and_existing_output_refuses_before_import(
    handoff, tmp_path
):
    import json
    from dataclasses import asdict
    from gda_assets.api import CollectionRequest

    run, port, _ = handoff
    destination = tmp_path / "observations.json"
    first = run(CollectionRequest(save_to=destination))
    assert first.failure is None
    assert json.loads(destination.read_text()) == json.loads(
        json.dumps(asdict(first.content_observations))
    )
    before = destination.read_bytes()
    port.calls.clear()
    repeat = run(CollectionRequest(save_to=destination))
    assert repeat.failure.stage == "validate"
    assert port.calls == []
    assert destination.read_bytes() == before


@pytest.mark.parametrize(
    "declaration", [{"res://source.png": "invalid"}, {"res://other.png": "0" * 64}]
)
def test_invalid_declaration_refuses_before_install(handoff, declaration):
    from gda_assets.api import CollectionRequest

    run, port, project = handoff
    result = run(CollectionRequest(declared_output_sha256=declaration))
    assert result.failure.code == "invalid_collection"
    assert result.outputs == []
    assert not (project / "source.png").exists()
    assert port.calls == []


def test_collection_bounds_published_artifact_lists(handoff):
    from gda_assets.api import CollectionRequest, ImportAssetFacts

    run, port, _ = handoff
    port.observe_import = lambda paths: [
        ImportAssetFacts(
            paths[0],
            "cached",
            "res://source.png.import",
            tuple(f"res://cache/{i}.bin" for i in range(500)),
            "texture",
            paths[0],
        )
    ]
    result = run(CollectionRequest())
    assert result.failure.code == "observation_incomplete"
    asset = result.content_observations.assets[0]
    assert len(asset.import_before.artifacts) <= 128
    assert asset.import_before.artifacts_omitted > 0
    assert len(asset.artifacts) <= 128


def test_ordinary_handoff_does_not_collect_or_save(handoff, monkeypatch):
    from gda_assets.adapters.observations import LocalObservationFiles

    run, port, _ = handoff

    def no_digest(*args):
        raise AssertionError("ordinary handoff must not collect")

    monkeypatch.setattr(LocalObservationFiles, "digest", no_digest)
    result = run()
    assert result.failure is None
    assert result.content_observations is None
    assert port.calls == ["import"]


def test_missing_pre_import_facts_cannot_masquerade_as_cold_import(handoff):
    from gda_assets.api import CollectionRequest

    run, port, project = handoff
    original_observe = port.observe_import
    original_import = port.import_assets
    first = True

    def incomplete_before(paths):
        nonlocal first
        if first:
            first = False
            return []
        return original_observe(paths)

    def change_configuration(paths):
        (project / "source.png.import").write_bytes(b"changed during import")
        return original_import(paths)

    port.observe_import = incomplete_before
    port.import_assets = change_configuration
    result = run(CollectionRequest())
    assert result.failure is not None
    assert result.failure.code == "invalid_observation"
    assert "import" not in port.calls
    assert result.content_observations is not None
    assert result.content_observations.status == "incomplete"
    assert (project / "source.png.import").read_bytes() == b"config"


def test_save_failure_retains_collected_facts(handoff, tmp_path):
    from gda_assets.api import CollectionRequest

    run, _, _ = handoff
    result = run(CollectionRequest(save_to=tmp_path / "missing-parent" / "result.json"))
    assert result.failure.code == "observation_save_failed"
    assert result.content_observations.status == "incomplete"
    assert result.content_observations.saved_to is None
    assert result.content_observations.assets[0].source_after.sha256
