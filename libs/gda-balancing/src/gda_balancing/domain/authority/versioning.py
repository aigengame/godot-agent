"""Version information derived from admitted language authority."""

from typing import Any, cast

from gda_balancing.domain.authority.context import AdmittedAuthorityContext


def supported_schema_line(context: AdmittedAuthorityContext) -> str:
    """Return the newest supported Model Source major/minor line."""
    language_bundle = context.language_bundle
    versions = cast(
        list[str],
        cast(dict[str, Any], language_bundle["language"])[
            "model_source_schema_versions"
        ],
    )
    parsed = [tuple(int(part) for part in version.split(".")) for version in versions]
    if not parsed or any(len(version) != 3 for version in parsed):
        raise ValueError("LDB model source version inventory is not semantic versioned")
    newest = max(parsed)
    return f"{newest[0]}.{newest[1]}"
