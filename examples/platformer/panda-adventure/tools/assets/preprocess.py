"""Preprocess — compose the Style descriptor + size spec into a per-asset spec.

The head of the pipeline: it builds ONE :class:`AssetSpec` from the
shared Style descriptor and the size spec's target dimensions for an asset, then
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
    *,
    subject: str | None = None,
    hint: str | None = None,
) -> AssetSpec:
    """Compose the style descriptor with an asset's target dimensions.

    ``subject``/``hint`` are the optional per-asset recipe overrides (a namespaced
    id needs a human subject; an off-category asset supplies its own style hint)."""
    return AssetSpec(
        id=asset_id,
        category=category,
        target_dims=target_dims,
        style=style,
        subject=subject,
        hint=hint,
    )


def _subject_terms(spec: AssetSpec) -> str:
    """The concrete thing the query/prompt is about (the recipe subject override,
    else the humanized id) — delegated to the spec so both renderers agree."""
    return spec.subject_terms


def render_search_query(spec: AssetSpec) -> str:
    """The search-download query: the subject, the style keywords, the category
    hint — the terms an open-asset search matches against."""
    parts = [_subject_terms(spec), *spec.style.keywords]
    if spec.category_hint:
        parts.append(spec.category_hint)
    return " ".join(p for p in parts if p)


def render_generation_prompt(spec: AssetSpec) -> str:
    """The generation prompt: the style prompt fragment, the subject, the category
    hint, an explicit solid-background instruction (so postprocess can key it out),
    and a single-centered-subject framing."""
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
