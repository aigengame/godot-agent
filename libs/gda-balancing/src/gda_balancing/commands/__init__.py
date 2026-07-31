"""The registered command surface.

``REGISTRY`` is the one registry every projection reads (bADR-0011): dispatch,
``--schema``, and the conformance harness. Import order is acyclic — command
modules import :mod:`gda_balancing.descriptors`; only this package assembles
the tuple.
"""

from gda_balancing.commands.manifest import MANIFEST
from gda_balancing.commands.experiment import EXPERIMENT_CHECK, EXPERIMENT_RUN
from gda_balancing.commands.model import (
    MODEL_BUILD,
    MODEL_CHECK,
    MODEL_INSPECT,
    MODEL_MIGRATE,
)
from gda_balancing.commands.package import PACKAGE_GET, PACKAGE_LIST
from gda_balancing.commands.schema import SCHEMA_GET
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    TEMPLATE_LIST,
)
from gda_balancing.commands.version import VERSION
from gda_balancing.descriptors import CommandDescriptor, build_registry

REGISTRY: tuple[CommandDescriptor, ...] = build_registry(
    VERSION,
    SCHEMA_GET,
    MANIFEST,
    EXPERIMENT_CHECK,
    EXPERIMENT_RUN,
    MODEL_CHECK,
    MODEL_BUILD,
    MODEL_INSPECT,
    MODEL_MIGRATE,
    TEMPLATE_LIST,
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    PACKAGE_LIST,
    PACKAGE_GET,
)
