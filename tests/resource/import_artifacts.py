"""Import-cache artifacts, built the way the engine writes them.

Both halves of ``resource import``'s coverage stand on the same trees: the
adapter tests read them through ``gda.import_evidence``, the command tests drive
them through the CLI. The builders live here rather than in either module so the
two cannot drift apart on what a ``cached`` or ``stale`` tree looks like — the
shape a receipt or a sidecar has is the fixture, not the assertion (#741).
"""

import hashlib
from pathlib import Path

from tests.support import minimal_project


def icon_project(tmp_path: Path) -> Path:
    """The shared minimum, plus the one asset the import pass has to see."""
    project = minimal_project(tmp_path)
    (project / "icon.png").write_bytes(b"\x89PNG fake bytes")
    return project


def sidecar(
    project: Path,
    asset: str,
    dest_rel: str | None,
    valid: bool = True,
    importer: str = "texture",
    uid: bool = True,
    source_file: str | None = None,
) -> None:
    """A sidecar shaped like the engine writes it (uid + source_file included:
    the reimport-test adapter reads both, #738 review)."""
    lines = [f'[remap]\n\nimporter="{importer}"\n']
    if not valid:
        lines.append("valid=false\n")
    if uid:
        lines.append('uid="uid://test"\n')
    lines.append("\n[deps]\n\n")
    source = source_file if source_file is not None else f"res://{asset}"
    lines.append(f'source_file="{source}"\n')
    if dest_rel is not None:
        lines.append(f'dest_files=["res://{dest_rel}"]\n')
    (project / f"{asset}.import").write_text("".join(lines), encoding="utf-8")


def receipt_path(project: Path, asset: str) -> Path:
    """The engine's per-asset receipt, at the PATH-derived import base:
    .godot/imported/<filename>-<md5 of the res:// path>.md5 — how
    ResourceFormatImporter::get_import_base_path derives it."""
    digest = hashlib.md5(f"res://{asset}".encode()).hexdigest()
    return project / ".godot" / "imported" / f"{Path(asset).name}-{digest}.md5"


def md5_companion(project: Path, dest_rel: str, source_rel: str) -> None:
    """The engine's freshness receipt for ``source_rel``, recording source_md5."""
    digest = hashlib.md5((project / source_rel).read_bytes()).hexdigest()
    receipt = receipt_path(project, source_rel)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(f'source_md5="{digest}"\n', encoding="utf-8")


def cached_asset(project: Path, asset: str, dest_rel: str) -> None:
    """A fully intact cache: sidecar + dest + the engine's md5 receipt."""
    (project / dest_rel).parent.mkdir(parents=True, exist_ok=True)
    (project / dest_rel).write_bytes(b"ctex")
    sidecar(project, asset, dest_rel)
    md5_companion(project, dest_rel, asset)
