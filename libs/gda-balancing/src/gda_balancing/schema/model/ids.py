"""Identifier vocabulary (bADR-0002).

Every id matches ``^[a-z][a-z0-9_]*$``. Ids are the map keys of their
declaring collection — the map key is the single id authority, so uniqueness
is structural (duplicate JSON keys are a preflight refusal, bADR-0004). The
same id may legally appear in different namespaces; references are typed
(bADR-0003).
"""

from typing import Annotated

from pydantic import StringConstraints

ID_PATTERN = r"^[a-z][a-z0-9_]*$"

IdStr = Annotated[str, StringConstraints(pattern=ID_PATTERN)]
