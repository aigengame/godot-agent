"""The style-config schema home — the pipeline's whole per-game surface.

One JSON document (the **style config**) wires a game into the pipeline without
touching the package: the framework parses it here into its own model types and
plain config values, and every other module consumes those — never the raw file.
Its schema:

- ``game_root``    — the game project root, resolved relative to the style
  config file's own directory (so a style config is relocatable with its game).
  Every other configured path resolves against this root.
- ``assets_root``  — where produced assets land and the manifest lives,
  relative to the game root (default ``assets``).
- ``scale_spec``   — the game's size-authority JSON, relative to the game root
  (default ``data/json/scale_spec.json``): the single home of every target
  dimension the pipeline composes into an asset spec.
- ``style``        — the shared :class:`~assets.model.StyleDescriptor` input:
  ``keywords``, ``prompt_fragment``, the bounded ``palette``, and optional
  ``category_hints``.
- ``constraints``  — ``formats``, the global download-license allowlist
  ``allowed_licenses``, the ``chroma_key`` background color, and optional
  per-category ``category_licenses`` extensions.
- ``sources``      — the configurable open-asset sources (each a
  :class:`~assets.model.Source`: name, kind, base_url, default_license,
  license_url); never hardcoded in the framework.
- ``generation``   — optional: the generation backends' wiring (the ``mcp``
  channels and the ``builtin`` command/fallback).
- ``lifecycle``    — optional: ``lfs_size_threshold_bytes``, the size-gate
  threshold.
- ``assets``       — the per-asset acquire recipes, keyed by manifest id:
  ``category``, an optional ``scale_key`` (a dotted path into the size spec),
  optional ``subject``/``category_hint`` prompt overrides, and the ``acquire``
  recipe (mode, source/url or backend/model, license overrides).

Any ``_``-prefixed keys are the game's own documentation; the pipeline ignores
what it does not know. A missing or wrong-typed field — at the root or nested —
is a structured :class:`ConfigError` refusal at load time, never a stray
``KeyError``/``TypeError`` later in the pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backends import BuiltinBackend, GenerationBackend, McpBackend
from .model import Source, StyleDescriptor


class ConfigError(Exception):
    """A refused or invalid per-game input (style config, size spec, or CLI
    path), carrying a stable machine-readable ``code`` alongside the human
    ``detail``."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# The message names of the typed accessor's JSON kinds. ``float`` means "any
# number" (bool excluded), matching JSON's single number type.
_KIND_NAMES = {
    str: "a string",
    int: "an integer",
    float: "a number",
    bool: "a boolean",
    list: "an array",
    dict: "an object",
}

# The acquire modes a recipe may name (the manifest ``acquire_mode`` values).
_ACQUIRE_MODES = ("search_download", "generation")


def _invalid(path: Path, detail: str) -> ConfigError:
    return ConfigError("config_invalid", f"style config {path}: {detail}")


def _is_kind(value: Any, kind: type) -> bool:
    if kind is float:  # any JSON number; bool is not a number
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is bool:
        return isinstance(value, bool)
    return isinstance(value, kind)


def _typed(
    path: Path, mapping: dict[str, Any], key: str, kind: type, where: str = ""
) -> Any:
    """The schema boundary's typed accessor: a missing key or a wrong-typed
    value (null included) refuses with ``config_invalid`` at LOAD time —
    never a TypeError later during path resolution or an acquire."""
    label = f"{where}{key}"
    if key not in mapping:
        raise _invalid(path, f"missing the '{label}' key")
    value = mapping[key]
    if not _is_kind(value, kind):
        raise _invalid(
            path,
            f"'{label}' must be {_KIND_NAMES[kind]}, got {type(value).__name__}",
        )
    return value


def _typed_opt(
    path: Path,
    mapping: dict[str, Any],
    key: str,
    kind: type,
    default: Any,
    where: str = "",
) -> Any:
    """The optional-key variant of :func:`_typed`: absent OR an explicit JSON
    ``null`` -> ``default`` (an optional key set to null is "not set", the
    committed configs' own idiom), present-but-wrong-typed -> the same
    structured refusal. A REQUIRED key still refuses null via :func:`_typed`."""
    if key not in mapping or mapping[key] is None:
        return default
    return _typed(path, mapping, key, kind, where)


def resolve_against(base_dir: Path, value: str) -> Path:
    """Resolve a configured path value: absolute passes through, relative
    resolves against ``base_dir``. A string the OS cannot treat as a path (an
    embedded NUL, an overlong component) is the same bad input as a
    wrong-typed field — every configured path value funnels through here, so
    the whole class refuses structured."""
    try:
        p = Path(value)
        return p.resolve() if p.is_absolute() else (base_dir / p).resolve()
    except (ValueError, OSError) as exc:
        raise ConfigError("config_invalid", f"invalid path value {value!r}: {exc}")


@dataclass(frozen=True)
class StyleConfig:
    """One style config parsed: the whole per-game asset configuration."""

    path: Path
    game_root: Path
    style: StyleDescriptor
    sources: dict[str, Source]
    assets: dict[str, dict[str, Any]]
    assets_root: str
    scale_spec_rel: str
    generation: dict[str, Any]
    lfs_size_threshold_bytes: int
    # Per-category download-license extensions on top of the global allowlist
    # (``style.allowed_licenses``): e.g. ``{"fonts": ("OFL",)}`` allows a downloaded
    # OFL font for the fonts category only. Empty for a category with no extension.
    category_licenses: dict[str, tuple[str, ...]]

    def download_licenses_for(self, category: str) -> tuple[str, ...]:
        """The DOWNLOAD-license allowlist for one asset category.

        The global ``allowed_licenses`` (the game's sourcing rule) plus any
        category-scoped extension — so a license acceptable for one category
        (a permissively-licensed downloaded font, say) stays out of the global
        rule that governs every other category.
        """
        return tuple(self.style.allowed_licenses) + self.category_licenses.get(
            category, ()
        )


def _read_config_doc(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(
            "config_unreadable", f"cannot read style config {path}: {exc}"
        )
    except ValueError as exc:
        raise ConfigError(
            "config_invalid", f"style config {path} is not valid JSON: {exc}"
        )
    if not isinstance(doc, dict):
        raise ConfigError(
            "config_invalid",
            f"style config {path} must be a JSON object at the root, "
            f"got {type(doc).__name__}",
        )
    return doc


def _parse_style(path: Path, doc: dict[str, Any]) -> StyleDescriptor:
    style_doc = _typed(path, doc, "style", dict)
    constraints = _typed(path, doc, "constraints", dict)
    return StyleDescriptor(
        keywords=tuple(_typed(path, style_doc, "keywords", list, "style.")),
        prompt_fragment=_typed(path, style_doc, "prompt_fragment", str, "style."),
        palette=tuple(_typed(path, style_doc, "palette", list, "style.")),
        category_hints=dict(
            _typed_opt(path, style_doc, "category_hints", dict, {}, "style.")
        ),
        formats=tuple(_typed(path, constraints, "formats", list, "constraints.")),
        allowed_licenses=tuple(
            _typed(path, constraints, "allowed_licenses", list, "constraints.")
        ),
        chroma_key=_typed(path, constraints, "chroma_key", str, "constraints."),
    )


def _parse_sources(path: Path, doc: dict[str, Any]) -> dict[str, Source]:
    sources: dict[str, Source] = {}
    for i, src in enumerate(_typed(path, doc, "sources", list)):
        if not isinstance(src, dict):
            raise _invalid(
                path, f"'sources[{i}]' must be an object, got {type(src).__name__}"
            )
        where = f"sources[{i}]."
        source = Source(
            name=_typed(path, src, "name", str, where),
            kind=_typed(path, src, "kind", str, where),
            base_url=_typed(path, src, "base_url", str, where),
            default_license=_typed(path, src, "default_license", str, where),
            license_url=_typed(path, src, "license_url", str, where),
        )
        sources[source.name] = source
    return sources


def _parse_assets(path: Path, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate each per-asset recipe's shape at the load boundary, so the
    pipeline's later reads (category, scale_key, the acquire recipe fields)
    can never hit a wrong-typed value."""
    assets: dict[str, dict[str, Any]] = {}
    for asset_id, request in _typed(path, doc, "assets", dict).items():
        where = f"assets.{asset_id}."
        if not isinstance(request, dict):
            raise _invalid(
                path,
                f"'assets.{asset_id}' must be an object, got {type(request).__name__}",
            )
        _typed(path, request, "category", str, where)
        for key in ("scale_key", "subject", "category_hint"):
            _typed_opt(path, request, key, str, None, where)
        recipe = _typed(path, request, "acquire", dict, where)
        for key in (
            "mode",
            "source",
            "url",
            "license",
            "license_url",
            "attribution",
            "backend",
            "model",
        ):
            _typed_opt(path, recipe, key, str, None, f"{where}acquire.")
        mode = recipe.get("mode")
        if mode is not None and mode not in _ACQUIRE_MODES:
            raise _invalid(
                path,
                f"'{where}acquire.mode' must be one of {list(_ACQUIRE_MODES)}, "
                f"got {mode!r}",
            )
        assets[asset_id] = dict(request)
    return assets


def load_style_config(path: Path) -> StyleConfig:
    """Parse a style config file (the per-game configuration) into a
    :class:`StyleConfig`.

    Every field is read through the typed accessor, so ANY malformed field —
    missing, null, or the wrong JSON type, at the root or nested — is a
    ``config_invalid`` refusal here at the schema boundary. ``game_root``
    resolves against the style config file's own directory.
    """
    path = path.resolve()
    doc = _read_config_doc(path)
    lifecycle = _typed_opt(path, doc, "lifecycle", dict, {})
    return StyleConfig(
        path=path,
        game_root=resolve_against(path.parent, _typed(path, doc, "game_root", str)),
        style=_parse_style(path, doc),
        sources=_parse_sources(path, doc),
        assets=_parse_assets(path, doc),
        assets_root=_typed_opt(path, doc, "assets_root", str, "assets"),
        scale_spec_rel=_typed_opt(
            path, doc, "scale_spec", str, "data/json/scale_spec.json"
        ),
        generation=dict(_typed_opt(path, doc, "generation", dict, {})),
        lfs_size_threshold_bytes=_typed_opt(
            path, lifecycle, "lfs_size_threshold_bytes", int, 1_048_576, "lifecycle."
        ),
        # Skip the ``_``-prefixed documentation keys (the config's _readme/_note
        # convention), so only real category names carry license extensions.
        category_licenses={
            category: tuple(licenses)
            for category, licenses in _typed_opt(
                path,
                _typed(path, doc, "constraints", dict),
                "category_licenses",
                dict,
                {},
                "constraints.",
            ).items()
            if not category.startswith("_")
        },
    )


def _effective_root(config: StyleConfig, game_root: Path | None) -> Path:
    """The game root an operation runs against: the explicit override (a test's
    isolated root, the CLI's ``--game-root``) wins, else the config's own."""
    return game_root if game_root is not None else config.game_root


def _read_scale_spec(config: StyleConfig, game_root: Path | None) -> dict[str, Any]:
    spec_path = _effective_root(config, game_root) / config.scale_spec_rel
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(
            "scale_spec_invalid", f"cannot read the size spec {spec_path}: {exc}"
        )
    except ValueError as exc:
        raise ConfigError(
            "scale_spec_invalid", f"size spec {spec_path} is not valid JSON: {exc}"
        )
    if not isinstance(spec, dict):
        raise ConfigError(
            "scale_spec_invalid",
            f"size spec {spec_path} must be a JSON object at the root, "
            f"got {type(spec).__name__}",
        )
    return spec


def target_dims(
    config: StyleConfig, scale_key: str, game_root: Path | None = None
) -> tuple[int, int]:
    """The asset's exact pixel dimensions from the configured size spec.

    ``scale_key`` is a dotted path so an asset can point at a nested
    dimension, not just a top-level one (a single segment still resolves a
    top-level box). One authored size home, addressed by path — the pipeline
    never hardcodes a dimension the size spec owns.
    """
    node: Any = _read_scale_spec(config, game_root)
    for part in scale_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(
                "scale_key_unknown",
                f"scale key {scale_key!r} is not in {config.scale_spec_rel} "
                "(the configured size spec is the single size authority)",
            )
        node = node[part]
    if (
        not isinstance(node, list)
        or len(node) != 2
        or not all(_is_kind(v, float) for v in node)
    ):
        raise ConfigError(
            "scale_spec_invalid",
            f"scale key {scale_key!r} in {config.scale_spec_rel} must be a "
            "two-number array (a width/height box)",
        )
    return (int(node[0]), int(node[1]))


def scale_value(config: StyleConfig, key: str, game_root: Path | None = None) -> float:
    """A SCALAR dimension from the configured size spec.

    The scalar analogue of :func:`target_dims` (which returns a 2-tuple box):
    reads one numeric key straight from the size spec so a consumer never
    hardcodes a dimension the spec owns — retuning the authored value
    regenerates the consumer's artifact at the new size instead of scaling a
    stale one.
    """
    spec = _read_scale_spec(config, game_root)
    if key not in spec:
        raise ConfigError(
            "scale_key_unknown",
            f"scale key {key!r} is not in {config.scale_spec_rel} "
            "(the configured size spec is the single size authority)",
        )
    if not _is_kind(spec[key], float):
        raise ConfigError(
            "scale_spec_invalid",
            f"scale key {key!r} in {config.scale_spec_rel} must be a number, "
            f"got {type(spec[key]).__name__}",
        )
    return float(spec[key])


def asset_resource_path(config: StyleConfig, category: str, asset_id: str) -> str:
    """The ``res://`` path the produced asset lands at and the manifest records."""
    return f"res://{config.assets_root}/{category}/{asset_id}.png"


def asset_output_path(
    config: StyleConfig, category: str, asset_id: str, game_root: Path | None = None
) -> Path:
    """The on-disk path :func:`asset_resource_path` resolves to."""
    return (
        _effective_root(config, game_root)
        / config.assets_root
        / category
        / f"{asset_id}.png"
    )


# The image model applied when a generation recipe names none. Per-ASSET, never a
# shared-channel argument: the channel is reused across assets, so a model on the
# channel would silently regenerate every asset with one asset's model and break
# the retained per-recipe provenance contract. An asset whose recipe omits `model`
# regenerates on this default rather than on a sibling's model.
_DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"


def make_mcp_backend(
    config: StyleConfig,
    channel: str,
    game_root: Path | None = None,
    *,
    model: str | None = None,
) -> McpBackend:
    """Build the MCP generation backend for a configured channel.

    ``model`` is the per-asset image model from the acquire recipe; it wins, and
    absent one the pipeline default (:data:`_DEFAULT_IMAGE_MODEL`) applies — the
    channel's shared arguments never decide the model (that would regress a
    sibling asset). The resolved model is merged into the tool arguments.
    """
    import sys

    channels = _typed_opt(
        config.path,
        _typed_opt(config.path, config.generation, "mcp", dict, {}, "generation."),
        "channels",
        dict,
        {},
        "generation.mcp.",
    )
    if channel not in channels:
        raise ConfigError(
            "channel_unknown",
            f"no MCP generation channel {channel!r} in the style config {config.path}",
        )
    where = f"generation.mcp.channels.{channel}."
    spec = channels[channel]
    if not isinstance(spec, dict):
        raise _invalid(
            config.path,
            f"'generation.mcp.channels.{channel}' must be an object, "
            f"got {type(spec).__name__}",
        )
    root = _effective_root(config, game_root)
    command = [
        str(part).replace("{python}", sys.executable).replace("{game_root}", str(root))
        for part in _typed(config.path, spec, "command", list, where)
    ]
    arguments = dict(_typed_opt(config.path, spec, "arguments", dict, {}, where))
    arguments["model"] = model or _DEFAULT_IMAGE_MODEL
    return McpBackend(
        channel=channel,
        command=command,
        tool=_typed_opt(config.path, spec, "tool", str, "generate_image", where),
        arguments=arguments,
    )


def make_builtin_backend(
    config: StyleConfig, game_root: Path | None = None
) -> BuiltinBackend:
    """Build the BuiltinBackend, wiring its configured fallback if any."""
    spec = _typed_opt(
        config.path, config.generation, "builtin", dict, {}, "generation."
    )
    command = spec.get("command")
    fallback: GenerationBackend | None = None
    fallback_channel = _typed_opt(
        config.path, spec, "fallback", str, None, "generation.builtin."
    )
    if fallback_channel:
        fallback = make_mcp_backend(config, fallback_channel, game_root)
    return BuiltinBackend(command=command, fallback=fallback)
