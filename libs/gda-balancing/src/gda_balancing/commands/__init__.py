"""The registered command surface.

``REGISTRY`` is the one registry every projection reads (bADR-0011): dispatch,
``--schema``, and the conformance harness. Import order is acyclic — command
modules import :mod:`gda_balancing.descriptors`; only this package assembles
the tuple.
"""

from gda_balancing.commands.design import DESIGN_FORMAT, DESIGN_VALIDATE
from gda_balancing.commands.manifest import MANIFEST
from gda_balancing.commands.schema import SCHEMA_GET
from gda_balancing.commands.version import VERSION
from gda_balancing.descriptors import CommandDescriptor, build_registry

REGISTRY: tuple[CommandDescriptor, ...] = build_registry(
    VERSION, DESIGN_VALIDATE, DESIGN_FORMAT, SCHEMA_GET, MANIFEST
)
