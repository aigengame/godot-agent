"""S (e2e): `gda resource import` against the real engine (#668).

The GDA-DF-010 proof: in a clean worktree (sources + committed sidecars, no
.godot/ cache) a one-shot `script run` preload() of a PNG fails with "no
recognized resource loader"; after `resource import` it succeeds. The suite
also proves the dry run writes nothing, the pass's created files are
classified, the second run is a no-pass cache hit, and a script is the
engine-decided `not_importable`. Run e2e SERIALLY; not a fresh empty HOME.
"""

import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

CHECK_GD = (
    "extends SceneTree\n"
    "func _init() -> void:\n"
    '\tvar tex = load("res://icon.png")\n'
    '\tprint("LOADED: ", tex)\n'
    "\tquit(0 if tex != null else 1)\n"
)


def _png(path: Path, color: tuple[int, int, int]) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(color) * 2 for _ in range(2))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _project(tmp_path: Path) -> Path:
    (tmp_path / "project.godot").write_text(
        "config_version=5\n\n[application]\n\n"
        'config/name="t668"\n\n[debug]\n\n'
        "file_logging/enable_file_logging=false\n"
        "file_logging/enable_file_logging.pc=false\n",
        encoding="utf-8",
    )
    _png(tmp_path / "icon.png", (255, 0, 0))
    (tmp_path / "check.gd").write_text(CHECK_GD, encoding="utf-8")
    return tmp_path


def _gda(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            *GDA_CMD,
            *args,
            "--project",
            str(project),
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _tree(project: Path) -> set[str]:
    return {
        p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()
    }


@pytest.mark.e2e
def test_import_heals_the_clean_worktree_preload_failure(tmp_path):
    # The #668 DoD (GDA-DF-010): without the import the preload FAILS; with it,
    # it succeeds — plus the dry run's zero-write inventory, the classified
    # created files, and the idempotent second run, all on the same project.
    project = _project(tmp_path)

    # AC1, the failing half: plain `script run` triggers no import pass, and
    # the clean-worktree load dies.
    before_run = _tree(project)
    failing = _gda(project, "script", "run", "res://check.gd")
    assert failing.returncode == 0, failing.stdout + failing.stderr
    assert json.loads(failing.stdout)["exit_status"] == 1
    # `script run` added no import artifacts (the engine writes only its own
    # transient state, never the import cache).
    assert not any(
        f.startswith(".godot/imported") or f.endswith(".import")
        for f in _tree(project) - before_run
    )

    # AC3: the dry run reports the inventory and writes NOTHING.
    before_dry = _tree(project)
    dry = _gda(project, "resource", "import", "res://icon.png", "--dry-run")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    dry_doc = json.loads(dry.stdout)
    assert dry_doc["dry_run"] is True
    assert dry_doc["engine_pass"] is True
    assert dry_doc["assets"][0]["status"] == "missing"
    assert dry_doc["predicted_source_adjacent"] == ["res://icon.png.import"]
    assert _tree(project) == before_dry

    # AC2 + AC4: the real run reports per-asset verdicts, the summary, and
    # every created file classified against the cache root.
    imported = _gda(project, "resource", "import", "res://icon.png")
    assert imported.returncode == 0, imported.stdout + imported.stderr
    doc = json.loads(imported.stdout)
    assert doc["engine_pass"] is True
    assert doc["assets"][0]["status"] == "imported"
    assert doc["assets"][0]["sidecar"] == "res://icon.png.import"
    created = {f["path"]: f["classification"] for f in doc["created"]}
    assert created["res://icon.png.import"] == "source_adjacent"
    assert created["res://check.gd.uid"] == "source_adjacent"
    assert any(
        p.startswith("res://.godot/imported/icon.png-") and c == "cache_owned"
        for p, c in created.items()
    )
    assert all(
        c == "cache_owned" for p, c in created.items() if p.startswith("res://.godot/")
    )
    assert doc["summary"]["imported"] == 1
    assert doc["summary"]["requested"] == 1

    # AC1, the healed half: the same preload now succeeds.
    healed = _gda(project, "script", "run", "res://check.gd")
    assert healed.returncode == 0, healed.stdout + healed.stderr
    healed_doc = json.loads(healed.stdout)
    assert healed_doc["exit_status"] == 0
    assert "LOADED" in healed_doc["stdout"]

    # Idempotence: the second import is a cache hit and runs NO pass.
    second = _gda(project, "resource", "import", "res://icon.png")
    second_doc = json.loads(second.stdout)
    assert second_doc["engine_pass"] is False
    assert second_doc["assets"][0]["status"] == "cached"
    assert second_doc["created"] == []


@pytest.mark.e2e
def test_a_script_is_engine_decided_not_importable(tmp_path):
    project = _project(tmp_path)

    result = _gda(project, "resource", "import", "res://check.gd")

    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc["assets"][0]["status"] == "not_importable"
    assert doc["summary"]["not_importable"] == 1


@pytest.mark.e2e
def test_engine_invalid_import_is_failed_not_imported(tmp_path):
    # #738 review [P1], the real-engine reproduction: ordinary text named
    # .png — Godot writes a sidecar with valid=false and no dest_files. gda
    # must report `failed`, never a cache hit or a successful import.
    project = _project(tmp_path)
    (project / "broken.png").write_text("this is not a png", encoding="utf-8")

    result = _gda(project, "resource", "import", "res://broken.png")

    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    broken = next(a for a in doc["assets"] if a["path"] == "res://broken.png")
    assert broken["status"] == "failed"
    assert doc["summary"]["failed"] == 1
    # And the verdict is stable: a second run still refuses to call it cached.
    again = json.loads(_gda(project, "resource", "import", "res://broken.png").stdout)
    assert again["assets"][0]["status"] == "failed"


@pytest.mark.e2e
def test_stale_source_reimports_and_dry_run_lists_project_gaps(tmp_path):
    # #738 review [P1]: freshness rides the engine's own md5 receipts — after
    # the source changes, the dry run says `missing` (and would run the pass),
    # and the real run re-imports. Plus the review's own two-asset probe,
    # pinned: requesting only icon.png, the dry run's project-wide scan lists
    # other.png as something the pass would also import.
    project = _project(tmp_path)
    _png(project / "other.png", (0, 0, 255))

    first = json.loads(_gda(project, "resource", "import", "res://icon.png").stdout)
    assert first["assets"][0]["status"] == "imported"

    # Make icon.png stale (different content, same path).
    _png(project / "icon.png", (0, 255, 0))
    dry = json.loads(
        _gda(project, "resource", "import", "res://icon.png", "--dry-run").stdout
    )
    assert dry["assets"][0]["status"] == "stale"
    assert dry["engine_pass"] is True

    re_imported = json.loads(
        _gda(project, "resource", "import", "res://icon.png").stdout
    )
    assert re_imported["assets"][0]["status"] == "imported"

    # The project-gap half: strip other.png's cache, request only icon.png.
    import shutil

    other_sidecar = project / "other.png.import"
    assert other_sidecar.is_file()
    shutil.rmtree(project / ".godot")
    dry2 = json.loads(
        _gda(project, "resource", "import", "res://icon.png", "--dry-run").stdout
    )
    assert dry2["assets"][0]["status"] == "stale"
    assert "res://other.png" in dry2["pass_will_also_import"]


@pytest.mark.e2e
def test_alias_sidecar_and_invalid_skip_match_the_engine(tmp_path):
    # #738 review, both real-engine reproductions in one project:
    # - a copied source+sidecar (source_file naming the original) is STALE and
    #   a real run re-imports it into its own cache entries;
    # - an invalid sidecar is EXCLUDED from pass_will_also_import, and the
    #   pass leaves its bytes untouched (the engine skips failed imports).
    project = _project(tmp_path)
    first = json.loads(_gda(project, "resource", "import", "res://icon.png").stdout)
    assert first["assets"][0]["status"] == "imported"

    # The invalid neighbor FIRST (its first import runs a project-wide pass;
    # the alias must not exist yet or that pass would heal it prematurely).
    (project / "bad.png").write_text("not a png", encoding="utf-8")
    assert (
        json.loads(_gda(project, "resource", "import", "res://bad.png").stdout)[
            "assets"
        ][0]["status"]
        == "failed"
    )
    bad_sidecar_before = (project / "bad.png.import").read_bytes()
    # The alias: copy source + sidecar verbatim.
    (project / "alias2.png").write_bytes((project / "icon.png").read_bytes())
    (project / "alias2.png.import").write_text(
        (project / "icon.png.import").read_text(encoding="utf-8"), encoding="utf-8"
    )

    dry = json.loads(
        _gda(project, "resource", "import", "res://alias2.png", "--dry-run").stdout
    )
    assert dry["assets"][0]["status"] == "stale"
    assert "res://bad.png" not in dry["pass_will_also_import"]

    real = json.loads(_gda(project, "resource", "import", "res://alias2.png").stdout)
    assert real["assets"][0]["status"] == "imported"
    # The engine rewrote the alias's sidecar to its own source/dest paths.
    rewritten = (project / "alias2.png.import").read_text(encoding="utf-8")
    assert 'source_file="res://alias2.png"' in rewritten
    # And the invalid neighbor's sidecar is byte-identical: the pass skipped it.
    assert (project / "bad.png.import").read_bytes() == bad_sidecar_before


@pytest.mark.e2e
def test_no_destination_sidecar_matches_the_engines_current_verdict(tmp_path):
    # #738 re-review 4 [P1], the real-engine reproduction: strip only the
    # path=/dest_files= lines from a normally imported sidecar (receipts and
    # everything else intact). The engine's reimport test considers that
    # CURRENT (nothing to check, receipts pass); gda must agree — no pass
    # spent, never settled to failed, and excluded from the gap prediction.
    project = _project(tmp_path)
    first = json.loads(_gda(project, "resource", "import", "res://icon.png").stdout)
    assert first["assets"][0]["status"] == "imported"

    sidecar = project / "icon.png.import"
    kept = [
        line
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if not line.startswith("path=") and not line.startswith("dest_files=")
    ]
    sidecar.write_text("\n".join(kept) + "\n", encoding="utf-8")

    dry = json.loads(
        _gda(project, "resource", "import", "res://icon.png", "--dry-run").stdout
    )
    assert dry["assets"][0]["status"] == "cached"
    assert dry["engine_pass"] is False

    real = json.loads(_gda(project, "resource", "import", "res://icon.png").stdout)
    assert real["assets"][0]["status"] == "cached"
    assert real["engine_pass"] is False
    assert real["created"] == []

    # And a request for a NEW asset must not falsely predict this one.
    _png(project / "fresh.png", (1, 2, 3))
    gap = json.loads(
        _gda(project, "resource", "import", "res://fresh.png", "--dry-run").stdout
    )
    assert "res://icon.png" not in gap["pass_will_also_import"]
