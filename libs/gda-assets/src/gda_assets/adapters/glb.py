"""Bounded GLB container admission and explicit external-file references.

This is not a scene inspector or a full glTF validator. Godot owns engine loading.
Container layout: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#glb-file-format-specification
"""

import json
from pathlib import Path
import struct
from urllib.parse import unquote, urlsplit

from gda_assets.application.ports import PortFailure


def external_uris(source: Path) -> list[str]:
    try:
        with source.open("rb") as stream:
            magic, version, size, json_size, kind = struct.unpack(
                "<4sIIII", stream.read(20)
            )
            if (
                magic != b"glTF"
                or version != 2
                or size != source.stat().st_size
                or kind != 0x4E4F534A
            ):
                raise ValueError("Expected a GLB 2.0 container")
            if json_size > min(size - 20, 16 * 1024 * 1024) or json_size % 4:
                raise ValueError("Invalid or oversized GLB JSON chunk")
            document = json.loads(stream.read(json_size))
            if not isinstance(document, dict):
                raise ValueError("Expected a glTF object")
            asset = document.get("asset")
            if not isinstance(asset, dict) or asset.get("version") != "2.0":
                raise ValueError("Expected glTF asset version 2.0")
            # Validate chunk boundaries without reading the mesh payload into memory.
            while stream.tell() < size:
                length, chunk_type = struct.unpack("<II", stream.read(8))
                if (
                    length % 4
                    or stream.tell() + length > size
                    or chunk_type == 0x4E4F534A
                ):
                    raise ValueError("Invalid GLB chunk boundary")
                stream.seek(length, 1)
        references = []
        for section in ("images", "buffers"):
            entries = document.get(section, [])
            if not isinstance(entries, list):
                raise ValueError(f"Expected a glTF {section} array")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError(f"Expected a glTF {section} object")
                uri = entry.get("uri")
                if uri is None:
                    continue
                if not isinstance(uri, str) or not uri:
                    raise ValueError("Expected a nonempty glTF URI")
                if uri.startswith("data:"):
                    continue
                parsed = urlsplit(uri)
                path = unquote(parsed.path, errors="strict")
                if (
                    parsed.scheme
                    or parsed.netloc
                    or parsed.query
                    or parsed.fragment
                    or path.startswith("/")
                    or "\\" in path
                    or ":" in path
                    or "\x00" in path
                ):
                    raise ValueError(
                        f"Only local relative GLB references are supported: {uri!r}"
                    )
                references.append(path)
        return references
    except (ValueError, struct.error) as exc:
        raise PortFailure("invalid_asset", f"Invalid GLB {source}: {exc}") from exc
