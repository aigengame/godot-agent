"""Phase 1 — structural: the document against the published structural schema.

The second funnel phase (bADR-0004). It runs the Design document through the
generated JSON Schema 2020-12 artifact (:mod:`gda_balancing.schema.artifacts`)
with ``jsonschema`` and projects each validation error into the toolkit's
element-level refusal shape: a stable :data:`STRUCTURAL_VIOLATION` code (the one
structural code family, bADR-0004), the instance path as an RFC 6901 pointer,
and the violated keyword in the detail.

**Element precision (bADR-0004: "never just the enclosing collection").** Two
JSON Schema keywords report at the *enclosing object*, not the offending member;
each is drilled to the member so an agent gets the exact pointer:

* ``additionalProperties`` — jsonschema reports one error at the object with the
  object as its instance. The offending keys are recomputed (instance keys not
  in ``properties`` and matching no ``patternProperties`` pattern under
  ``re.search``, mirroring jsonschema's own semantics) → **one refusal per
  offending key** at ``…/<key>``.
* ``propertyNames`` — jsonschema *descends* into the ``propertyNames`` subschema
  and surfaces the inner keyword failure (e.g. ``not``) with ``absolute_path``
  at the object and ``instance`` set to the offending **key string**; it already
  yields one such error per failing key. These are detected by ``propertyNames``
  appearing in the error's ``schema_path`` (the prompt's ``validator ==
  "propertyNames"`` never matches — jsonschema reports the nested keyword), and
  projected to **one refusal per failing key** at ``…/<key>``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import jsonschema

from gda_balancing.schema.refusal import Refusal
from gda_balancing.schema import pointer

if TYPE_CHECKING:
    from gda_balancing.schema.bundle import VersionBundle

# The single stable structural refusal code (bADR-0004): structural refusals
# share one code family, with the violated JSON Schema keyword in the detail.
STRUCTURAL_VIOLATION = "structural_violation"

# One Draft 2020-12 validator per resolved line, keyed on `bundle.line`. Each
# line has its own structural schema (bADR-0001/0005), so a document is checked
# against the definition of the version it declares — never a single global
# validator that would silently apply a newer minor's shape to an older document.
_validators: dict[str, jsonschema.Draft202012Validator] = {}


def _validator_for(bundle: VersionBundle) -> jsonschema.Draft202012Validator:
    """The lazily-built, cached validator over ``bundle``'s structural schema.
    Built once per line — schema generation is deterministic."""
    validator = _validators.get(bundle.line)
    if validator is None:
        validator = jsonschema.Draft202012Validator(bundle.structural_schema())
        _validators[bundle.line] = validator
    return validator


def structural(parsed: object, bundle: VersionBundle | None = None) -> list[Refusal]:
    """Validate ``parsed`` against ``bundle``'s structural schema; return the
    refusals.

    An empty list means the document is structurally well-formed (the semantic
    phase runs next). Refusals are returned raw, in jsonschema's discovery order
    — dedup/order/truncate is :mod:`report`'s job. ``bundle`` defaults to the
    newest line (:func:`~gda_balancing.schema.bundle.current_bundle`) for
    line-agnostic callers; the funnel passes the *resolved* bundle so the
    document is validated under the version it declared.
    """
    if bundle is None:
        # Lazy import keeps the funnel free of a load-time `bundle` dependency
        # (the bundle imports this package's rules — see schema/bundle.py).
        from gda_balancing.schema.bundle import current_bundle

        bundle = current_bundle()
    # `parsed` is JSON the funnel already decoded; widen to Any at the
    # jsonschema boundary, whose stub types the instance as a JSON-value union.
    instance: Any = parsed
    refusals: list[Refusal] = []
    for error in _validator_for(bundle).iter_errors(instance):
        refusals.extend(_project(error))
    return refusals


def _project(error: jsonschema.ValidationError) -> list[Refusal]:
    if error.validator == "additionalProperties":
        return _additional_property_refusals(error)
    if "propertyNames" in error.schema_path:
        return _property_name_refusals(error)
    return [
        Refusal(
            code=STRUCTURAL_VIOLATION,
            path=pointer.build(*error.absolute_path),
            detail=f"{error.validator}: {error.message}",
        )
    ]


def _additional_property_refusals(
    error: jsonschema.ValidationError,
) -> list[Refusal]:
    """One refusal per key the closed subschema does not permit — recomputed so
    the pointer reaches the key, not the enclosing object."""
    schema = error.schema if isinstance(error.schema, dict) else {}
    declared: set[str] = set(schema.get("properties", {}))
    patterns: list[str] = list(schema.get("patternProperties", {}))
    instance: Any = error.instance
    keys = instance.keys() if isinstance(instance, dict) else ()
    return [
        Refusal(
            code=STRUCTURAL_VIOLATION,
            path=pointer.build(*error.absolute_path, key),
            detail=f"additionalProperties: {key!r} is not a permitted property",
        )
        for key in keys
        if key not in declared
        and not any(re.search(pattern, key) for pattern in patterns)
    ]


def _property_name_refusals(error: jsonschema.ValidationError) -> list[Refusal]:
    """One refusal for the offending key of a ``propertyNames`` failure —
    jsonschema descends and sets ``instance`` to the failing key string, and
    yields one such error per failing key."""
    key = str(error.instance)
    return [
        Refusal(
            code=STRUCTURAL_VIOLATION,
            path=pointer.build(*error.absolute_path, key),
            detail=f"propertyNames: key {key!r} is not a valid identifier",
        )
    ]
