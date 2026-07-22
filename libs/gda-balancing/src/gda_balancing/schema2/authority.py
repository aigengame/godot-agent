"""Loader for the permanent, packaged Kernel/LDB authority artifacts.

The JSON resources are the language authority.  This host module only reads,
independently admits, and defensively copies them; changing Python dispatch
cannot silently add a law, rule, diagnostic, or package to the language.
"""

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from gda_balancing.schema2.bootstrap import admit_authorities

_AUTHORITY_PACKAGE = "gda_balancing.schema2.authorities"


def _load(name: str) -> dict[str, Any]:
    resource = files(_AUTHORITY_PACKAGE).joinpath(name)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"packaged authority {name} is not an object")
    return value


def load_authorities() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load fresh copies of both packaged authority artifacts."""
    return _load("kernel.json"), _load("language-bundle.json")


def authority_set() -> dict[str, Any]:
    """Return a defensive copy of the independently admitted authority pair."""
    kernel, ldb = load_authorities()
    admission = admit_authorities(kernel, ldb)
    return {
        "kernel": deepcopy(kernel),
        "language_bundle": deepcopy(ldb),
        "admission": {
            "admitted": admission.admitted,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }
