"""Preprocess — compose the Style descriptor + Scale spec into a per-asset spec.

The head of the pipeline (gADR-0014): it builds ONE :class:`AssetSpec` from the
shared Style descriptor and the Scale spec's target dimensions for an asset, then
renders it as either a search query (search-download) or a generation prompt
(generation). One spec, both modes, so a downloaded asset and a generated asset
target the same style and size.
"""

from __future__ import annotations

from .model import AssetSpec, StyleDescriptor


def build_asset_spec(
    asset_id: str,
    category: str,
    target_dims: tuple[int, int],
    style: StyleDescriptor,
) -> AssetSpec:
    """Compose the style descriptor with an asset's target dimensions."""
    return AssetSpec(
        id=asset_id, category=category, target_dims=target_dims, style=style
    )


def _subject_terms(spec: AssetSpec) -> str:
    """Human-readable subject words from the asset id (``obstacle_crate`` ->
    ``obstacle crate``) — the concrete thing the query/prompt is about."""
    return spec.id.replace("_", " ")


def render_search_query(spec: AssetSpec) -> str:
    """The search-download query: the subject, the style keywords, the category
    hint — the terms an open-asset search matches against (gADR-0014)."""
    parts = [_subject_terms(spec), *spec.style.keywords]
    if spec.category_hint:
        parts.append(spec.category_hint)
    return " ".join(p for p in parts if p)


def render_generation_prompt(spec: AssetSpec) -> str:
    """The generation prompt: the style prompt fragment, the subject, the category
    hint, an explicit solid-background instruction (so postprocess can key it out),
    and a single-centered-subject framing (gADR-0014)."""
    w, h = spec.target_dims
    parts = [
        spec.style.prompt_fragment,
        f"a single {_subject_terms(spec)}",
    ]
    if spec.category_hint:
        parts.append(spec.category_hint)
    parts.extend(
        [
            ", ".join(spec.style.keywords),
            f"one centered object filling the frame, "
            f"on a solid {spec.style.chroma_key} background, no text, "
            f"no shadow, no border, designed to read at {w}x{h} pixels",
        ]
    )
    return ". ".join(p for p in parts if p)
