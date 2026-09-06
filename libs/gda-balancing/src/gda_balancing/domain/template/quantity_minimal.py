"""Built-in ``standard.quantity-minimal`` template release."""

from copy import deepcopy
from typing import cast

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.authority.graph import resolve_current_namespaces
from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.model import model_source_identity_domain

from ._release_semantics import (
    _artifact_identity_domain,
    _member,
    _member_schema_identities,
    _template_admission_profile,
)


def minimal_release(context: AdmittedAuthorityContext) -> dict[str, JsonValue]:
    """Build the packaged minimal Quantity Template from one admitted context."""
    kernel = context.kernel
    language_bundle = context.language_bundle
    kernel_identity = cast(str, kernel["content_identity"])
    language_bundle_identity = cast(str, language_bundle["content_identity"])
    selection = resolve_current_namespaces(
        context.current_namespace_packages(), ["core.quantity"]
    )
    quantity_contract: dict[str, JsonValue] = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    starter: dict[str, JsonValue] = {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "standard.quantity-minimal.starter",
            "entry_module": "main",
        },
        "package_requirements": ["core.quantity"],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [
                    {
                        "symbol": "value",
                        **deepcopy(quantity_contract),
                        "role": "parameter",
                        "value_policy": {"mode": "experiment-required"},
                    },
                    {
                        "symbol": "derived_value",
                        **deepcopy(quantity_contract),
                        "role": "derived",
                        "value_policy": {"mode": "none"},
                    },
                    {
                        "symbol": "output_value",
                        **deepcopy(quantity_contract),
                        "role": "output",
                        "value_policy": {"mode": "none"},
                    },
                ],
                "formulas": [
                    {
                        "id": "derive-value",
                        "parameters": [{"id": "base", **deepcopy(quantity_contract)}],
                        "result": deepcopy(quantity_contract),
                        "body": {
                            "nodes": [
                                {
                                    "id": "value",
                                    "node": "operation-call",
                                    "operation": {
                                        "package": "core.quantity",
                                        "id": "quantity.identity",
                                    },
                                    "arguments": [
                                        {
                                            "port": "value",
                                            "operand": {
                                                "kind": "parameter",
                                                "parameter": "base",
                                            },
                                        }
                                    ],
                                    "result": deepcopy(quantity_contract),
                                }
                            ],
                            "result": {"kind": "local", "local": "value"},
                        },
                        "expression": "let value = identity(base);\nvalue",
                    }
                ],
            }
        ],
        "formula_bindings": [
            {
                "site": {
                    "kind": "derived-symbol",
                    "module": "main",
                    "symbol": "derived_value",
                },
                "formula": {"module": "main", "id": "derive-value"},
                "arguments": [
                    {
                        "parameter": "base",
                        "operand": {
                            "kind": "symbol",
                            "module": "main",
                            "symbol": "value",
                        },
                    }
                ],
            }
        ],
        "entrypoints": [
            {
                "id": "quantity.identity",
                "operation": {
                    "package": "core.quantity",
                    "id": "quantity.identity",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {
                            "kind": "symbol",
                            "module": "main",
                            "symbol": "derived_value",
                        },
                    }
                ],
                "result": {
                    "kind": "symbol",
                    "module": "main",
                    "symbol": "output_value",
                },
            }
        ],
    }
    profile = _template_admission_profile(language_bundle)
    member_identity_domain = cast(str, profile["member_identity_domain"])
    source_identity_domain = model_source_identity_domain(language_bundle)
    release_identity_domain = _artifact_identity_domain(
        language_bundle, "template-release"
    )
    starter_identity = content_identity(source_identity_domain, starter)
    experiment_id = "standard.quantity-minimal.experiment"
    golden_id = "standard.quantity-minimal.golden"
    negative_id = "standard.quantity-minimal.invalid-domain"
    boundary_id = "standard.quantity-minimal.maximum-boundary"
    schema_identities = _member_schema_identities(language_bundle)

    def build_member(
        logical_name: str,
        member_kind: str,
        member_schema_identity: str,
        payload: JsonValue,
    ) -> dict[str, JsonValue]:
        return _member(
            logical_name,
            member_kind,
            member_schema_identity,
            payload,
            identity_domain=member_identity_domain,
        )

    members = [
        build_member(
            "starter-model-source",
            "model-source-package",
            schema_identities["model-source-package"],
            starter,
        ),
        build_member(
            "experiment-specification",
            "experiment-template",
            schema_identities["experiment-template"],
            {
                "schema_version": "2.0.0",
                "id": experiment_id,
                "kernel_identity": kernel_identity,
                "language_bundle_identity": language_bundle_identity,
                "model_source_identity": starter_identity,
                "scenarios": [golden_id],
                "metrics": [
                    {
                        "id": "value",
                        "kind": "scalar",
                        "unit": "1",
                        "target": {"minimum": 0, "maximum": 100},
                    }
                ],
            },
        ),
        build_member(
            "declared-package-dependencies",
            "declared-package-dependencies",
            schema_identities["declared-package-dependencies"],
            {
                "schema_version": "2.0.0",
                "packages": [package.namespace for package in selection.packages],
            },
        ),
        build_member(
            "defaults",
            "template-defaults",
            schema_identities["template-defaults"],
            {
                "schema_version": "2.0.0",
                "symbol_values": [{"symbol": "main.value", "value": 50}],
            },
        ),
        build_member(
            "compatibility",
            "template-compatibility",
            schema_identities["template-compatibility"],
            {
                "schema_version": "2.0.0",
                "kernel_identity": kernel_identity,
                "language_bundle_identity": language_bundle_identity,
                "packages": ["core.quantity"],
            },
        ),
        build_member(
            "documentation",
            "template-documentation",
            schema_identities["template-documentation"],
            {
                "schema_version": "2.0.0",
                "media_type": "text/markdown",
                "text": "A minimal editable Quantity Model Source Package.",
            },
        ),
        build_member(
            "coverage-matrix",
            "genre-coverage-matrix",
            schema_identities["genre-coverage-matrix"],
            {
                "schema_version": "2.0.0",
                "rows": [
                    {
                        "id": "template.quantity.tracer",
                        "requirement": "An editable Quantity source builds through model build.",
                        "capabilities": ["quantity.declare", "quantity.lower"],
                        "operations": ["quantity.identity"],
                        "packages": ["core.quantity"],
                        "experiment": experiment_id,
                        "golden_scenario": golden_id,
                        "vectors": [negative_id, boundary_id],
                        "observables": ["value"],
                    }
                ],
            },
        ),
        build_member(
            "golden-scenario",
            "golden-scenario",
            schema_identities["golden-scenario"],
            {
                "schema_version": "2.0.0",
                "id": golden_id,
                "experiment": experiment_id,
                "model_source_identity": starter_identity,
                "symbol": "main.value",
                "value": 50,
            },
        ),
        build_member(
            "negative-vector",
            "negative-vector",
            schema_identities["negative-vector"],
            {
                "schema_version": "2.0.0",
                "id": negative_id,
                "diagnostic": "language.invalid_domain",
                "mutation": {
                    "pointer": "/modules/0/symbols/0/domain",
                    "value": {"minimum": 1, "maximum": 0},
                },
            },
        ),
        build_member(
            "boundary-vector",
            "boundary-vector",
            schema_identities["boundary-vector"],
            {
                "schema_version": "2.0.0",
                "id": boundary_id,
                "pointer": "/modules/0/symbols/0/domain/maximum",
                "value": 100,
                "expected": "accepted",
            },
        ),
    ]
    manifest = [
        {
            key: member[key]
            for key in (
                "logical_name",
                "member_kind",
                "member_schema_identity",
                "content_identity",
            )
        }
        for member in members
    ]
    body: dict[str, JsonValue] = {
        "artifact_kind": "template-release",
        "artifact_version": "2.0.0",
        "wire_schema_identity": schema_identities["template-release"],
        "id": "standard.quantity-minimal",
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle_identity,
        "manifest": cast(JsonValue, manifest),
        "members": cast(JsonValue, members),
    }
    return {
        **body,
        "content_identity": content_identity(release_identity_domain, body),
    }
