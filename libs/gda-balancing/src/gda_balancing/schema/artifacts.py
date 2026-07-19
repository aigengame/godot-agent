"""The generated structural schema artifact (bADR-0005).

The published **structural schema** is a JSON Schema 2020-12 document whose
instances are Design documents; it is *generated* from the pydantic document
model (:class:`gda_balancing.schema.model.document.DesignDocument`), never
hand-maintained — one authority, a projection around it (bADR-0005 anti-drift).
It is emitted verbatim by ``schema get structural`` and is the schema the
funnel's structural phase runs against.

**Portability rationale — why the newline guards exist.** A published pattern
must remain ECMA-262-valid (JSON Schema's regex dialect), so ``\\Z`` may *never*
appear in the artifact — only ``^``/``$`` anchoring is portable. Under ECMA,
``$`` already anchors at true end of input, so the guards this module adds are
no-ops for ecosystem validators. Under Python's ``re`` — the engine our *own*
structural phase (``jsonschema``) runs on — ``$`` (and an unanchored ``pattern``
search) also matches *before a trailing newline*, so without a guard a key or id
like ``"ab\\n"`` would **pass** the structural phase and then **fail** pydantic's
Rust-regex construction, turning a refusable document into an exit-4 crash. Two
guards close that hole so structural-pass ⇒ model-construction-success:

* every ``patternProperties`` node gains ``additionalProperties: false`` (keys
  matching no pattern are refused) **and** ``propertyNames: {"not": {"pattern":
  "\\n"}}`` (no key may contain a newline — the case ``$``-leniency would admit);
* every id-valued ``pattern`` node (the ``^[a-z]…$`` scalar ids) gains a sibling
  ``not: {"pattern": "\\n"}``.

Precedent: :data:`gda_balancing.envelope._JSON_POINTER_SCHEMA`'s ``anyOf`` guard
— the same Python-``re`` vs Rust-regex trailing-newline divergence, fixed in the
same structural style rather than by sharing a raw pattern string.
"""

import copy
from typing import Any

from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.model.ids import ID_PATTERN
from gda_balancing.schema.version import STRUCTURAL_SCHEMA_ID

# The JSON Schema dialect the artifact declares itself in (2020-12, bADR-0005).
_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# The trailing-newline guard, shared by both fix sites (see module docstring).
_NO_NEWLINE: dict[str, Any] = {"not": {"pattern": "\\n"}}


def generate_structural_schema() -> dict[str, Any]:
    """Build the published structural schema from :class:`DesignDocument`.

    Deterministic and side-effect-free: the pydantic validation-mode schema is
    deep-copied, then post-processed in place — top-level dialect/``$id`` set,
    every ``title`` stripped (snapshot stability across pydantic versions), and
    the two newline guards applied wherever they apply.
    """
    schema = copy.deepcopy(DesignDocument.model_json_schema())
    schema["$schema"] = _DIALECT
    schema["$id"] = STRUCTURAL_SCHEMA_ID
    _harden(schema)
    return schema


def _harden(node: object) -> None:
    """Recursively strip titles and apply the newline guards, in place.

    Children are visited *before* this node's own mutations so the guard keys we
    add are never re-walked (they carry no ``title`` and the ``"\\n"`` guard
    pattern is not :data:`ID_PATTERN`, so a second pass would be a no-op anyway).
    """
    if isinstance(node, dict):
        for value in list(node.values()):
            _harden(value)
        node.pop("title", None)
        if "patternProperties" in node:
            # `additionalProperties: false` refuses keys matching no pattern;
            # `propertyNames` refuses any key carrying a newline (the case the
            # Python-`re` `$`-leniency would otherwise admit). `setdefault`
            # never clobbers an author-declared keyword — the generated schema
            # carries neither on any patternProperties node today.
            node.setdefault("additionalProperties", False)
            node.setdefault("propertyNames", copy.deepcopy(_NO_NEWLINE))
        if node.get("pattern") == ID_PATTERN:
            node.setdefault("not", copy.deepcopy(_NO_NEWLINE["not"]))
    elif isinstance(node, list):
        for item in node:
            _harden(item)
