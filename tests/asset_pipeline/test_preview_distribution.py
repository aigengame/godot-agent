"""Distribution boundary for the shipped isolated preview fixture (#891)."""

from pathlib import Path
import os
import subprocess
import tarfile
import zipfile


FIXTURE_FILES = {
    "gda_assets/adapters/preview_fixture/project.godot",
    "gda_assets/adapters/preview_fixture/preview.gd",
    "gda_assets/adapters/preview_fixture/preview.tscn",
}
MODULES = {
    "gda_assets/adapters/preview_files.py",
    "gda_assets/application/preview.py",
    "gda_assets/application/preview_ports.py",
    "gda_assets/domain/preview.py",
    "gda_assets/domain/preview_result.py",
}


def test_preview_fixture_and_modules_ship_in_wheel_and_sdist(tmp_path):
    root = Path(__file__).parents[2]
    process = subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
        env={**os.environ, "UV_CACHE_DIR": str(tmp_path / "uv-cache")},
    )
    assert process.returncode == 0, process.stdout + process.stderr

    wheel = next(tmp_path.glob("gda-*.whl"))
    source = next(tmp_path.glob("gda-*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = set(archive.namelist())
    assert FIXTURE_FILES | MODULES <= wheel_names

    with tarfile.open(source, "r:gz") as archive:
        source_names = {"/".join(Path(name).parts[1:]) for name in archive.getnames()}
    source_prefix = "libs/gda-assets/src/"
    assert {source_prefix + name for name in FIXTURE_FILES | MODULES} <= source_names
