"""Built-in ``standard.quantity-minimal`` template release."""

from copy import deepcopy
from typing import cast

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.authority.graph import resolve_current_namespaces
from gda_balancing.domain.authority.source_projection import (
    author_source_value,
    project_source_value,
    source_assignment_binding,
    source_assignment_policy,
    source_native_contract_values,
    source_schema_member,
)
from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.model import model_source_identity_domain
from gda_balancing.domain.artifacts import select_protocol_artifact_contract

from ._release_semantics import (
    _member,
    _member_schema_identities,
    _template_admission_profile,
    _template_model_source_member_kind,
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
    source_schema = context.source_semantic_index.schema
    source_bindings = context.source_native_binding_index
    symbol_schema = context.source_semantic_index.role_anchors[
        source_bindings.roles["source.symbol"]
    ][0]

    def one_native_value(member: str) -> JsonValue:
        values = source_native_contract_values(
            language_bundle, symbol_schema, member
        )
        if len(values) != 1:
            raise ValueError(
                f"quantity-minimal requires one Source native {member} value"
            )
        return deepcopy(values[0])

    assignment_policy = source_assignment_policy(language_bundle)
    parameter = source_assignment_binding(
        assignment_policy,
        initialization_source="experiment",
        binding_kind="operand",
        entrypoint_result=False,
        entrypoint_operand_access=("read",),
        value_member="forbidden",
        experiment_cardinality="required",
        event_payload_cardinality="optional",
        external_fact_cardinality="forbidden",
        override=False,
    )
    derived = source_assignment_binding(
        assignment_policy,
        initialization_source="resolved-model",
        binding_kind="operand",
        entrypoint_result=False,
        entrypoint_operand_access=("read",),
        value_member="forbidden",
        experiment_cardinality="forbidden",
        event_payload_cardinality="forbidden",
        external_fact_cardinality="forbidden",
        override=False,
    )
    output = source_assignment_binding(
        assignment_policy,
        initialization_source="execution",
        binding_kind="result",
        entrypoint_result=True,
        entrypoint_operand_access=(),
        value_member="forbidden",
        experiment_cardinality="forbidden",
        event_payload_cardinality="forbidden",
        external_fact_cardinality="forbidden",
        override=False,
    )
    quantity_contract: dict[str, JsonValue] = {
        "type": "quantity",
        "representation": one_native_value("representation"),
        "kind": one_native_value("kind"),
        "unit": one_native_value("unit"),
        "domain_kind": one_native_value("domain"),
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": one_native_value("numeric_policy"),
    }
    _, schema_version_schema = source_schema_member(
        source_schema, source_bindings.members["source.root.schema_version"]
    )
    starter_semantic: dict[str, JsonValue] = {
        "schema_version": cast(str, schema_version_schema["const"]),
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
                        "role": parameter.role,
                        "value_policy": {"mode": parameter.mode},
                    },
                    {
                        "symbol": "derived_value",
                        **deepcopy(quantity_contract),
                        "role": derived.role,
                        "value_policy": {"mode": derived.mode},
                    },
                    {
                        "symbol": "output_value",
                        **deepcopy(quantity_contract),
                        "role": output.role,
                        "value_policy": {"mode": output.mode},
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
    starter = author_source_value(starter_semantic, source_schema, source_bindings)
    starter_projection = project_source_value(starter, source_schema, source_bindings)
    profile = _template_admission_profile(language_bundle)
    member_identity_domain = cast(str, profile["member_identity_domain"])
    source_identity_domain = model_source_identity_domain(language_bundle)
    release_contract = select_protocol_artifact_contract(
        language_bundle, "template-release"
    )
    source_kind = _template_model_source_member_kind(kernel, profile)
    member_kinds = {
        row["role"]: row["member_kind"]
        for row in cast(list[dict[str, str]], profile["member_roles"])
    }
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
            source_kind,
            schema_identities[source_kind],
            starter,
        ),
        build_member(
            "experiment-specification",
            member_kinds["experiment"],
            schema_identities[member_kinds["experiment"]],
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
                        "kind": deepcopy(quantity_contract["kind"]),
                        "unit": deepcopy(quantity_contract["unit"]),
                        "target": {"minimum": 0, "maximum": 100},
                    }
                ],
            },
        ),
        build_member(
            "declared-package-dependencies",
            member_kinds["dependencies"],
            schema_identities[member_kinds["dependencies"]],
            {
                "schema_version": "2.0.0",
                "packages": [package.namespace for package in selection.packages],
            },
        ),
        build_member(
            "defaults",
            member_kinds["defaults"],
            schema_identities[member_kinds["defaults"]],
            {
                "schema_version": "2.0.0",
                "symbol_values": [
                    {
                        "symbol": {
                            "model": "standard.quantity-minimal.starter",
                            "module": "main",
                            "name": "value",
                        },
                        "value": 50,
                    }
                ],
            },
        ),
        build_member(
            "compatibility",
            member_kinds["compatibility"],
            schema_identities[member_kinds["compatibility"]],
            {
                "schema_version": "2.0.0",
                "kernel_identity": kernel_identity,
                "language_bundle_identity": language_bundle_identity,
                "packages": ["core.quantity"],
            },
        ),
        build_member(
            "documentation",
            member_kinds["documentation"],
            schema_identities[member_kinds["documentation"]],
            {
                "schema_version": "2.0.0",
                "media_type": "text/markdown",
                "text": "A minimal editable Quantity Model Source Package.",
            },
        ),
        build_member(
            "coverage-matrix",
            member_kinds["coverage"],
            schema_identities[member_kinds["coverage"]],
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
            member_kinds["golden"],
            schema_identities[member_kinds["golden"]],
            {
                "schema_version": "2.0.0",
                "id": golden_id,
                "experiment": experiment_id,
                "model_source_identity": starter_identity,
                "symbol": {
                    "model": "standard.quantity-minimal.starter",
                    "module": "main",
                    "name": "value",
                },
                "value": 50,
            },
        ),
        build_member(
            "negative-vector",
            member_kinds["negative-vector"],
            schema_identities[member_kinds["negative-vector"]],
            {
                "schema_version": "2.0.0",
                "id": negative_id,
                "diagnostic": "language.invalid_domain",
                "mutation": {
                    "pointer": starter_projection.authored_pointer(
                        "/modules/0/symbols/0/domain"
                    ),
                    "value": {"minimum": 1, "maximum": 0},
                },
            },
        ),
        build_member(
            "boundary-vector",
            member_kinds["boundary-vector"],
            schema_identities[member_kinds["boundary-vector"]],
            {
                "schema_version": "2.0.0",
                "id": boundary_id,
                "pointer": starter_projection.authored_pointer(
                    "/modules/0/symbols/0/domain/maximum"
                ),
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
        "id": "standard.quantity-minimal",
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle_identity,
        "manifest": cast(JsonValue, manifest),
        "members": cast(JsonValue, members),
    }
    return release_contract.identify(body)
