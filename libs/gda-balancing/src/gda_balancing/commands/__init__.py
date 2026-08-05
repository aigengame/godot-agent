"""The registered command surface.

``REGISTRY`` is the one registry every projection reads (bADR-0011): dispatch,
``--schema``, and the conformance harness. Import order is acyclic — command
modules import :mod:`gda_balancing.descriptors`; only this package assembles
the tuple.
"""

from gda_balancing.commands.experiment import EXPERIMENT_CHECK, EXPERIMENT_RUN
from gda_balancing.commands.model import (
    MODEL_INSPECT,
    MODEL_MIGRATE,
)
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    TEMPLATE_LIST,
)
from gda_balancing.descriptors import CommandDescriptor, build_registry
from gda_balancing.interfaces.cli.package_list import PACKAGE_LIST
from gda_balancing.interfaces.cli.package import PACKAGE_GET
from gda_balancing.interfaces.cli.manifest import manifest_descriptor
from gda_balancing.interfaces.cli.model_check import MODEL_CHECK
from gda_balancing.interfaces.cli.model_build import MODEL_BUILD
from gda_balancing.interfaces.cli.formula import FORMULA_PARSE, FORMULA_RENDER
from gda_balancing.interfaces.cli.schema import SCHEMA_GET
from gda_balancing.interfaces.cli.version import VERSION


def _live_registry() -> tuple[CommandDescriptor, ...]:
    return REGISTRY


MANIFEST = manifest_descriptor(_live_registry)

REGISTRY: tuple[CommandDescriptor, ...] = build_registry(
    VERSION,
    SCHEMA_GET,
    MANIFEST,
    EXPERIMENT_CHECK,
    EXPERIMENT_RUN,
    FORMULA_PARSE,
    FORMULA_RENDER,
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
