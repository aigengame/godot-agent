"""The Asset manifest — read/merge the per-category fragments (gADR-0014).

The manifest is the single record-of-source registry for produced assets, split
per category (``<assets_root>/manifest/<category>.json``) so parallel pipeline
slices never contend on one file. It is a RECORD source (its provenance/license
are not derivable), so the pipeline authors it and it is integrity-checked, never
freshness-gated. This module owns the read side and the record model; the write
side is :mod:`emitter`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import FrameLayout, ManifestEntry

# The per-category fragment lives under this directory of the assets root.
MANIFEST_DIRNAME = "manifest"

# The seven core manifest fields (gADR-0014), in a deterministic write order;
# optional provenance detail follows.
_CORE_FIELDS = (
    "path",
    "category",
    "acquire_mode",
    "source",
    "license",
    "license_url",
    "target_dims",
)
_OPTIONAL_FIELDS = ("source_url", "attribution", "prompt", "backend", "model")


def manifest_dir(root: Path, assets_root: str) -> Path:
    """The directory holding the per-category manifest fragments."""
    return root / assets_root / MANIFEST_DIRNAME


def fragment_path(root: Path, assets_root: str, category: str) -> Path:
    """The manifest fragment file for one asset category."""
    return manifest_dir(root, assets_root) / f"{category}.json"


def entry_to_dict(entry: ManifestEntry) -> dict[str, Any]:
    """Serialize an entry to its fragment JSON value (core fields, then optional)."""
    data: dict[str, Any] = {
        "path": entry.path,
        "category": entry.category,
        "acquire_mode": entry.acquire_mode,
        "source": entry.source,
        "license": entry.license,
        "license_url": entry.license_url,
        "target_dims": list(entry.target_dims),
    }
    for name in _OPTIONAL_FIELDS:
        value = getattr(entry, name)
        if value is not None:
            data[name] = value
    if entry.frame_layout is not None:
        layout = entry.frame_layout
        data["frame_layout"] = {
            "frame_dims": list(layout.frame_dims),
            "columns": layout.columns,
            "rows": layout.rows,
            "count": layout.count,
        }
    return data


def dict_to_entry(asset_id: str, data: dict[str, Any]) -> ManifestEntry:
    """Parse one fragment record back into a :class:`ManifestEntry`."""
    dims = data["target_dims"]
    return ManifestEntry(
        id=asset_id,
        path=data["path"],
        category=data["category"],
        acquire_mode=data["acquire_mode"],
        source=data["source"],
        license=data["license"],
        license_url=data["license_url"],
        target_dims=(int(dims[0]), int(dims[1])),
        source_url=data.get("source_url"),
        attribution=data.get("attribution"),
        prompt=data.get("prompt"),
        backend=data.get("backend"),
        model=data.get("model"),
        frame_layout=_frame_layout_from_dict(data.get("frame_layout")),
    )


def _frame_layout_from_dict(data: dict[str, Any] | None) -> FrameLayout | None:
    """Parse a sprite-set record's ``frame_layout`` sub-object (``None`` if absent)."""
    if data is None:
        return None
    dims = data["frame_dims"]
    return FrameLayout(
        frame_dims=(int(dims[0]), int(dims[1])),
        columns=int(data["columns"]),
        rows=int(data["rows"]),
        count=int(data["count"]),
    )


def load_fragment(path: Path) -> dict[str, ManifestEntry]:
    """Load one manifest fragment into ``id -> ManifestEntry`` (``{}`` if absent)."""
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {asset_id: dict_to_entry(asset_id, rec) for asset_id, rec in doc.items()}


def load_manifest(root: Path, assets_root: str) -> dict[str, ManifestEntry]:
    """Merge every category fragment into one ``id -> ManifestEntry`` map.

    Returns ``{}`` when the manifest directory is absent (a project with no
    acquired assets yet). Raises on a duplicate id across fragments — the id is
    the manifest's primary key.
    """
    directory = manifest_dir(root, assets_root)
    if not directory.exists():
        return {}
    merged: dict[str, ManifestEntry] = {}
    for fragment in sorted(directory.glob("*.json")):
        for asset_id, entry in load_fragment(fragment).items():
            if asset_id in merged:
                raise ValueError(
                    f"duplicate manifest id {asset_id!r} across fragments "
                    f"(second in {fragment.name}) — the id is the primary key"
                )
            merged[asset_id] = entry
    return merged
