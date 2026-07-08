"""Acquire — the two-mode interface that fulfils an :class:`AssetSpec`.

Acquire is an interface with two modes (gADR-0014):

- :func:`search_download` — fetch a candidate from a configurable open-asset
  source (CC0/CC-BY only), recording provenance and license.
- :func:`generate` — render the spec's prompt through a generation backend
  (:class:`~assets.backends.GenerationBackend`), recording the prompt and backend.

Both return an :class:`AcquireResult` naming the RAW acquired file (postprocess
conforms it next) and its record. The network / API boundary is injected — the
``fetch`` callable for search-download, the ``backend`` for generation — so the
fast CI suite mocks it while the on-demand ``acquire_live`` tests use the real
thing.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Callable

from .backends import GenerationBackend
from .model import AcquireResult, AcquireMode, AssetSpec, Source

# The acquire boundary the unit tests mock: given a URL, return the raw bytes.
Fetch = Callable[[str], bytes]

_USER_AGENT = "panda-adventure-asset-pipeline/0 (+gADR-0014; CC0/CC-BY fetch)"


class AcquireError(RuntimeError):
    """An acquire attempt failed (bad license, empty fetch, missing source)."""


def default_fetch(url: str, *, timeout: float = 60.0) -> bytes:
    """Fetch ``url`` over HTTP(S) — the real search-download boundary."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _check_license(license_name: str, allowed: tuple[str, ...]) -> None:
    if license_name not in allowed:
        raise AcquireError(
            f"license {license_name!r} is not in the allowed set {list(allowed)} "
            "— the pipeline records CC0/CC-BY only (gADR-0014)"
        )


def search_download(
    spec: AssetSpec,
    recipe: dict[str, object],
    source: Source,
    raw_dest: Path,
    *,
    allowed_licenses: tuple[str, ...],
    fetch: Fetch = default_fetch,
) -> AcquireResult:
    """Fetch the recipe's candidate URL and record its provenance + license.

    The recipe (from the per-game config) names the direct ``url`` for this asset
    within the configurable ``source``; the license defaults to the source's
    ``default_license`` unless the recipe overrides it. Rejects a non-CC0/CC-BY
    license before writing anything.

    Scope note (the tracer, #439): this resolves a **preconfigured source URL**
    from the recipe rather than driving a live search over
    ``render_search_query(spec)``. The rendered query is authored (preprocess
    composes it, and it is what a live search WOULD submit), but wiring a live
    open-asset search API is a deliberate follow-up — the tracer pins the
    end-to-end path with a fixed, license-verified candidate so the demo is
    reproducible (gADR-0014).
    """
    # Configured direct URL, not a live search hit — see the scope note above.
    url = recipe.get("url")
    if not isinstance(url, str) or not url:
        raise AcquireError(
            f"asset {spec.id!r} search-download recipe has no 'url' — the "
            "configurable source needs a candidate URL (gADR-0014)"
        )
    license_name = str(recipe.get("license", source.default_license))
    _check_license(license_name, allowed_licenses)
    data = fetch(url)
    if not data:
        raise AcquireError(f"fetch of {url} returned no bytes")
    raw_dest.parent.mkdir(parents=True, exist_ok=True)
    raw_dest.write_bytes(data)
    return AcquireResult(
        raw_path=raw_dest,
        acquire_mode=AcquireMode.SEARCH_DOWNLOAD,
        source=source.name,
        license=license_name,
        license_url=str(recipe.get("license_url", source.license_url)),
        source_url=url,
        attribution=_opt_str(recipe.get("attribution")),
    )


def generate(
    spec: AssetSpec,
    prompt: str,
    backend: GenerationBackend,
    raw_dest: Path,
    *,
    license_name: str,
    license_url: str,
) -> AcquireResult:
    """Render ``prompt`` through ``backend`` and record the prompt + backend.

    A generated asset's license is the project's own (configured) — it is authored
    by the pipeline, not sourced — and its provenance IS the prompt and the backend
    channel, recorded for reproducibility (gADR-0014).
    """
    backend.generate(prompt, raw_dest)
    if not raw_dest.exists() or raw_dest.stat().st_size == 0:
        raise AcquireError(
            f"generation backend {backend.name!r} produced no image at {raw_dest}"
        )
    return AcquireResult(
        raw_path=raw_dest,
        acquire_mode=AcquireMode.GENERATION,
        source=backend.name,
        license=license_name,
        license_url=license_url,
        prompt=prompt,
        backend=backend.name,
    )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
