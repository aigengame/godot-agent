"""Emitters — the pluggable output side of the pipeline (gADR-0014).

The Tool Script framework carries pluggable output emitters (JSON/XML/Resource/…)
so the core is reusable beyond this demo; the asset pipeline's default emitter
writes the acquired+postprocessed asset's record into the Asset manifest as JSON.
An emitter is the WRITE side of :mod:`manifest`: given a :class:`ManifestEntry`,
it persists it deterministically (sorted ids, stable field order) so the committed
fragment diffs cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from . import manifest
from .model import ManifestEntry


class Emitter(Protocol):
    """The output contract: record one produced asset. Other emitters (XML,
    Resource, …) implement the same shape for reuse beyond this game."""

    def emit(self, entry: ManifestEntry) -> None: ...


class JsonManifestEmitter:
    """Write manifest entries into the per-category JSON fragments (the default).

    Merges each emitted entry into its category fragment (upserting by id) and
    rewrites the fragment with sorted ids and stable field order, so re-running
    the pipeline for one asset leaves every other record byte-identical.
    """

    def __init__(self, root: Path, assets_root: str) -> None:
        self._root = root
        self._assets_root = assets_root

    def emit(self, entry: ManifestEntry) -> None:
        path = manifest.fragment_path(self._root, self._assets_root, entry.category)
        current = manifest.load_fragment(path)
        current[entry.id] = entry
        records = {
            asset_id: manifest.entry_to_dict(current[asset_id])
            for asset_id in sorted(current)
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
