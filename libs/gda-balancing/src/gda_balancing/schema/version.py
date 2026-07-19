"""Standard Schema version authorities (bADR-0001).

The Standard Schema is semver-versioned independently of the toolkit package
(the two are distinct authorities, bADR-0007). A validator supporting line
``X.Y`` accepts a document declaring major ``X`` and minor ``<= Y``; the
declared patch component is ignored for acceptance and resolution. Version
dispatch itself belongs to the funnel's preflight phase (bADR-0004).
"""

import re

# The Standard Schema version this toolkit implements, and its line.
SCHEMA_VERSION = "1.0.0"
SUPPORTED_LINE = "1.0"

# Every line this validator can dispatch to (v1: the single 1.0 line). A
# validator supporting X.Y ships every minor X.0..X.Y in its own artifact set
# (bADR-0005); each entry here is one such shipped definition.
SUPPORTED_LINES = frozenset({SUPPORTED_LINE})

# The structural schema's `$id` embeds the Standard Schema version
# (bADR-0005). It is an identifier, not a dereferenceable location — no
# hosted publication exists until a future bADR adds one (bADR-0009).
STRUCTURAL_SCHEMA_ID = f"urn:gda-balancing:standard-schema:{SCHEMA_VERSION}"

# Full-semver numeric triple (OpenAPI-style, bADR-0001 e.g. "1.1.0");
# pre-release/build suffixes are not part of the document contract.
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_line(version: str) -> str | None:
    """Return the ``major.minor`` line of a full-semver string, or ``None``
    when the string is not well-formed full semver."""
    match = _SEMVER.match(version)
    if match is None:
        return None
    return f"{match.group(1)}.{match.group(2)}"
