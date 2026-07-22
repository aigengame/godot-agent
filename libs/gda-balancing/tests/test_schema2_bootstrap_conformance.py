"""Independent bootstrap and mutation conformance for the permanent authority.

Consumer B below intentionally imports no production bootstrap or canonical
code.  Agreement is over public artifact bytes and observable inventories,
not shared helper behavior.
"""

import hashlib
import json
from copy import deepcopy
from typing import Any

from gda_balancing.schema2.authority import authority_set
from gda_balancing.schema2.bootstrap import admit_authorities


def _identity(domain: str, artifact: dict[str, Any]) -> str:
    body = {key: value for key, value in artifact.items() if key != "content_identity"}
    encoded = _encoded(body)
    return (
        "sha256:"
        + hashlib.sha256(f"gda-balancing:{domain}:".encode() + encoded).hexdigest()
    )


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _shape(value: Any) -> tuple[int, int]:
    depth = 0
    members = 0
    stack = [(value, 0)]
    while stack:
        current, current_depth = stack.pop()
        depth = max(depth, current_depth)
        if isinstance(current, dict):
            members = max(members, len(current))
            stack.extend((item, current_depth + 1) for item in current.values())
        elif isinstance(current, list):
            members = max(members, len(current))
            stack.extend((item, current_depth + 1) for item in current)
    return depth, members


def _consumer_b(kernel: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    """A separate, deliberately compact Kernel interpreter for cross-checking."""
    diagnostics: set[tuple[str, str, str]] = set()
    cap = kernel.get("resources", {}).get("max_diagnostics", 128)
    if not isinstance(cap, int) or cap < 1:
        cap = 128

    def refuse(code: str, stage: str, subject: str) -> None:
        diagnostics.add((stage, code, subject))

    if kernel.get("content_identity") != _identity("schema-major-kernel-v2", kernel):
        refuse("kernel.identity_mismatch", "ingress", "kernel")
    if ldb.get("content_identity") != _identity("language-definition-bundle-v2", ldb):
        refuse("kernel.identity_mismatch", "ingress", "language-bundle")
    if ldb.get("kernel_identity") != kernel.get("content_identity"):
        refuse("kernel.binding_mismatch", "ingress", "language-bundle.kernel_identity")

    kernel_members = {
        "admission",
        "artifact_kind",
        "artifact_version",
        "canonical_encoding",
        "content_identity",
        "diagnostics",
        "meta_format",
        "resources",
        "schema_major",
        "vectors",
    }
    if set(kernel) != kernel_members:
        refuse("kernel.member_set_mismatch", "ingress", "kernel")

    expected_members = set(kernel["admission"]["required_ldb_members"])
    if set(ldb) != expected_members:
        refuse("kernel.member_set_mismatch", "ingress", "language-bundle")

    limits = kernel["resources"]
    for subject, artifact in (("kernel", kernel), ("language-bundle", ldb)):
        depth, members = _shape(artifact)
        if (
            depth > limits["max_nesting_depth"]
            or members > limits["max_members"]
            or len(_encoded(artifact)) > limits["max_authority_bytes"]
        ):
            refuse("kernel.resource_exhausted", "ingress", subject)

    if diagnostics:
        ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
        truncated = len(ordered) > cap
        return {
            "admitted": False,
            "kernel_identity": kernel.get("content_identity"),
            "language_bundle_identity": ldb.get("content_identity"),
            "law_ids": [],
            "law_projections": [],
            "rule_ids": [],
            "rule_projections": [],
            "diagnostic_projections": [],
            "diagnostics": ordered[:cap],
            "truncated": truncated,
        }

    laws = kernel["admission"]["laws"]
    allowed_operations = {
        "verify-content-identity",
        "require-equal",
        "require-exact-members",
        "require-unique-identifiers",
        "require-known-operations",
        "require-vector-closure",
        "require-diagnostic-closure",
        "enforce-resource-limits",
    }
    law_ids = [law["id"] for law in laws]
    if len(law_ids) != len(set(law_ids)):
        refuse("kernel.duplicate_identifier", "static", "kernel.admission.laws")
    for law in laws:
        if law["operation"] not in allowed_operations:
            refuse("kernel.unknown_operation", "static", law["id"])
    law_projections = sorted(
        (law["id"], _identity("kernel-law-projection-v2", law)) for law in laws
    )

    kernel_vectors = kernel["vectors"]
    referenced_laws = {vector["law"] for vector in kernel_vectors}
    if set(law_ids) != referenced_laws:
        refuse("kernel.vector_mismatch", "static", "kernel.vectors")
    kernel_codes = [item["code"] for item in kernel["diagnostics"]]
    if len(kernel_codes) != len(set(kernel_codes)):
        refuse("kernel.duplicate_identifier", "static", "kernel.diagnostics")
    kernel_catalog = {(item["code"], item["stage"]) for item in kernel["diagnostics"]}
    kernel_vector_catalog = {
        (item["diagnostic"], item["stage"])
        for item in kernel_vectors
        if "diagnostic" in item
    }
    if kernel_catalog != kernel_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "kernel.diagnostics")

    rules = ldb["language"]["rules"]
    rule_ids = [rule["id"] for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        refuse("kernel.duplicate_identifier", "static", "language.rules")
    closed_rules = all(
        set(rule) == {"id", "judgment", "premises", "conclusion"}
        and all(set(item) == {"bind", "fact_kind"} for item in rule["premises"])
        and set(rule["conclusion"]) == {"fact_kind", "fields"}
        and all(
            (term.get("tag") == "literal" and set(term) == {"tag", "value"})
            or (term.get("tag") == "variable" and set(term) == {"tag", "name"})
            for term in rule["conclusion"]["fields"].values()
        )
        for rule in rules
    )
    if not closed_rules:
        refuse("kernel.vector_mismatch", "static", "language.rules")
    rule_vectors = [item for item in ldb["vectors"] if "rule" in item]
    if set(rule_ids) != {item["rule"] for item in rule_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.vectors")
    projections = []
    for vector in rule_vectors:
        invocation = vector["input"]
        facts = invocation["facts"]
        candidates = [
            rule
            for rule in sorted(rules, key=lambda item: item["id"])
            if rule["judgment"] == invocation["judgment"]
            and len(rule["premises"]) == len(facts)
            and all(
                premise["fact_kind"] == fact["kind"]
                for premise, fact in zip(rule["premises"], facts, strict=True)
            )
        ]
        output = None
        if len(candidates) == 1 and candidates[0]["id"] == vector["rule"]:
            selected = candidates[0]
            bindings = {}
            valid = True
            for premise, fact in zip(selected["premises"], facts, strict=True):
                for variable, field_name in premise["bind"].items():
                    if field_name not in fact["fields"]:
                        valid = False
                        break
                    bindings[variable] = fact["fields"][field_name]
            fields = {}
            for name, term in selected["conclusion"]["fields"].items():
                if term["tag"] == "literal" and set(term) == {"tag", "value"}:
                    fields[name] = term["value"]
                elif term["tag"] == "variable" and term.get("name") in bindings:
                    fields[name] = bindings[term["name"]]
                else:
                    valid = False
            if valid:
                output = {"kind": selected["conclusion"]["fact_kind"], "fields": fields}
        if output != vector["expect"]:
            refuse("kernel.vector_mismatch", "static", vector["id"])
        else:
            assert isinstance(output, dict)
            projections.append(
                (vector["id"], _identity("rule-vector-projection-v2", output))
            )

    ldb_codes = [item["code"] for item in ldb["diagnostics"]]
    if len(ldb_codes) != len(set(ldb_codes)):
        refuse("kernel.duplicate_identifier", "static", "language-bundle.diagnostics")
    ldb_catalog = {(item["code"], item["stage"]) for item in ldb["diagnostics"]}
    ldb_vector_catalog = {
        (item["diagnostic"], item["stage"])
        for item in ldb["vectors"]
        if "diagnostic" in item
    }
    if ldb_catalog != ldb_vector_catalog:
        refuse("kernel.diagnostic_closure", "static", "language-bundle.diagnostics")

    def resolve(path: str) -> Any:
        value: Any = ldb
        for part in path.split("."):
            value = value[part]
        return value

    reasons = {item["id"]: item for item in ldb["language"]["reasons"]}
    diagnostic_projections = []
    diagnostic_vectors = [item for item in ldb["vectors"] if "diagnostic" in item]
    if set(reasons) != {item["reason"] for item in diagnostic_vectors}:
        refuse("kernel.vector_mismatch", "static", "language-bundle.reasons")
    for vector in diagnostic_vectors:
        reason = reasons.get(vector["reason"])
        matched = False
        if reason is not None:
            predicate = reason["predicate"]
            operation = predicate["operation"]
            if operation == "not-member":
                inventory = resolve(predicate["inventory_path"])
                if "member_field" in predicate:
                    inventory = [item[predicate["member_field"]] for item in inventory]
                matched = vector["input"]["value"] not in inventory
            elif operation == "has-duplicate":
                values = vector["input"]["values"]
                matched = len(values) != len(set(values))
            elif operation == "greater-than":
                matched = vector["input"]["value"] > resolve(predicate["limit_path"])
        output = (
            {"code": reason["diagnostic"], "stage": reason["stage"]}
            if matched and reason is not None
            else None
        )
        expected = {"code": vector["diagnostic"], "stage": vector["stage"]}
        if output != expected:
            refuse("kernel.vector_mismatch", "static", vector["id"])
        else:
            assert isinstance(output, dict)
            diagnostic_projections.append(
                (
                    vector["id"],
                    vector["diagnostic"],
                    _identity("diagnostic-vector-projection-v2", output),
                )
            )

    ordered = sorted(diagnostics, key=lambda item: (item[0], item[2], item[1]))
    truncated = len(ordered) > cap
    return {
        "admitted": not ordered,
        "kernel_identity": kernel.get("content_identity"),
        "language_bundle_identity": ldb.get("content_identity"),
        "law_ids": sorted(law_ids),
        "law_projections": law_projections,
        "rule_ids": sorted(rule_ids),
        "rule_projections": sorted(projections),
        "diagnostic_projections": sorted(diagnostic_projections),
        "diagnostics": ordered[:cap],
        "truncated": truncated,
    }


def _consumer_a(kernel: dict[str, Any], ldb: dict[str, Any]) -> dict[str, Any]:
    result = admit_authorities(kernel, ldb)
    return {
        "admitted": result.admitted,
        "kernel_identity": result.kernel_identity,
        "language_bundle_identity": result.language_bundle_identity,
        "law_ids": list(result.law_ids),
        "law_projections": list(result.law_projections),
        "rule_ids": list(result.rule_ids),
        "rule_projections": list(result.rule_projections),
        "diagnostic_projections": list(result.diagnostic_projections),
        "diagnostics": [
            (item.stage, item.code, item.subject) for item in result.diagnostics
        ],
        "truncated": result.truncated,
    }


def _reidentify(kernel: dict[str, Any], ldb: dict[str, Any]) -> None:
    kernel["content_identity"] = _identity("schema-major-kernel-v2", kernel)
    ldb["kernel_identity"] = kernel["content_identity"]
    ldb["content_identity"] = _identity("language-definition-bundle-v2", ldb)


def test_two_independent_consumers_admit_the_exact_authority_and_inventories():
    authority = authority_set()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is True
    assert first["law_ids"]
    assert first["rule_ids"] == ["quantity.declare", "quantity.lower"]


def test_kernel_meta_format_and_ldb_rules_are_structured_for_independent_execution():
    authority = authority_set()
    meta_format = authority["kernel"]["meta_format"]

    assert set(meta_format) == {
        "fact",
        "term",
        "rule",
        "rule_selection",
        "binding_substitution",
        "diagnostic_reason",
    }
    assert {item["tag"] for item in meta_format["term"]["constructors"]} == {
        "literal",
        "variable",
    }
    for rule in authority["language_bundle"]["language"]["rules"]:
        assert set(rule) == {"id", "judgment", "premises", "conclusion"}
        assert rule["premises"]
        assert set(rule["conclusion"]) == {"fact_kind", "fields"}


def test_bootstrap_executes_every_rule_vector_into_a_stable_projection():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    assert admission.admitted is True
    assert dict(admission.rule_projections).keys() == {
        "quantity.declare.valid",
        "quantity.lower.valid",
    }
    assert all(
        identity.startswith("sha256:") for _, identity in admission.rule_projections
    )


def test_bootstrap_projects_every_kernel_law_without_a_host_fallback_table():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    law_ids = {item["id"] for item in authority["kernel"]["admission"]["laws"]}
    assert {law_id for law_id, _ in admission.law_projections} == law_ids
    assert all(
        identity.startswith("sha256:") for _, identity in admission.law_projections
    )


def test_bootstrap_behavior_covers_every_ldb_diagnostic_reason():
    authority = authority_set()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    catalog_codes = {
        item["code"] for item in authority["language_bundle"]["diagnostics"]
    }
    projection_codes = {code for _, code, _ in admission.diagnostic_projections}
    assert admission.admitted is True
    assert projection_codes == catalog_codes
    assert all(
        identity.startswith("sha256:")
        for _, _, identity in admission.diagnostic_projections
    )


def test_reidentified_deletion_of_every_law_and_rule_is_refused_by_both_consumers():
    baseline = authority_set()
    kernel_laws = baseline["kernel"]["admission"]["laws"]
    ldb_rules = baseline["language_bundle"]["language"]["rules"]

    for index in range(len(kernel_laws)):
        authority = deepcopy(baseline)
        del authority["kernel"]["admission"]["laws"][index]
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(ldb_rules)):
        authority = deepcopy(baseline)
        del authority["language_bundle"]["language"]["rules"][index]
        authority["language_bundle"]["content_identity"] = _identity(
            "language-definition-bundle-v2", authority["language_bundle"]
        )
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )


def test_reidentified_duplicate_diagnostic_is_not_hidden_by_set_projection():
    authority = authority_set()
    authority["language_bundle"]["diagnostics"].append(
        deepcopy(authority["language_bundle"]["diagnostics"][0])
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.duplicate_identifier",
        "language-bundle.diagnostics",
    ) in first["diagnostics"]


def test_old_identity_tamper_and_reidentified_behavior_or_token_mutations_refuse():
    baseline = authority_set()

    old_identity = deepcopy(baseline)
    old_identity["language_bundle"]["language"]["rules"][0]["conclusion"][
        "fact_kind"
    ] = "changed"
    first = _consumer_a(old_identity["kernel"], old_identity["language_bundle"])
    second = _consumer_b(old_identity["kernel"], old_identity["language_bundle"])
    assert first == second
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )

    for index in range(len(baseline["kernel"]["admission"]["laws"])):
        authority = deepcopy(baseline)
        authority["kernel"]["admission"]["laws"][index]["operation"] += ".renamed"
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert any(
            code == "kernel.unknown_operation" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(baseline["language_bundle"]["language"]["rules"])):
        authority = deepcopy(baseline)
        authority["language_bundle"]["language"]["rules"][index]["conclusion"][
            "fact_kind"
        ] += ".changed"
        authority["language_bundle"]["content_identity"] = _identity(
            "language-definition-bundle-v2", authority["language_bundle"]
        )
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )

    for owner, path in (
        ("kernel", ("admission", "laws")),
        ("language_bundle", ("language", "rules")),
    ):
        authority = deepcopy(baseline)
        collection = authority[owner]
        for part in path:
            collection = collection[part]
        collection[0]["id"] += ".renamed"
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )


def test_diagnostic_catalog_missing_extra_and_stage_drift_are_refused():
    baseline = authority_set()
    mutations = []

    missing = deepcopy(baseline)
    missing["language_bundle"]["diagnostics"].pop()
    mutations.append(missing)

    extra = deepcopy(baseline)
    extra["language_bundle"]["diagnostics"].append(
        {"code": "language.unreachable", "stage": "static"}
    )
    mutations.append(extra)

    drift = deepcopy(baseline)
    drift["language_bundle"]["diagnostics"][0]["stage"] = "resolution"
    mutations.append(drift)

    for authority in mutations:
        authority["language_bundle"]["content_identity"] = _identity(
            "language-definition-bundle-v2", authority["language_bundle"]
        )
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert (
            "static",
            "kernel.diagnostic_closure",
            "language-bundle.diagnostics",
        ) in first["diagnostics"]


def test_reidentified_deletion_and_behavior_mutation_of_every_reason_refuse():
    baseline = authority_set()
    reasons = baseline["language_bundle"]["language"]["reasons"]

    for index in range(len(reasons)):
        for mutation in ("delete", "operation"):
            authority = deepcopy(baseline)
            target = authority["language_bundle"]["language"]["reasons"]
            if mutation == "delete":
                del target[index]
            else:
                target[index]["predicate"]["operation"] += ".changed"
            authority["language_bundle"]["content_identity"] = _identity(
                "language-definition-bundle-v2", authority["language_bundle"]
            )
            first = _consumer_a(authority["kernel"], authority["language_bundle"])
            second = _consumer_b(authority["kernel"], authority["language_bundle"])
            assert first == second
            assert first["admitted"] is False
            assert any(
                code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
            )


def test_reidentified_extra_members_cannot_extend_kernel_ldb_or_rule_shapes():
    baseline = authority_set()
    mutations = []

    kernel_extra = deepcopy(baseline)
    kernel_extra["kernel"]["host_extension"] = True
    _reidentify(kernel_extra["kernel"], kernel_extra["language_bundle"])
    mutations.append(kernel_extra)

    ldb_extra = deepcopy(baseline)
    ldb_extra["language_bundle"]["host_extension"] = True
    ldb_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", ldb_extra["language_bundle"]
    )
    mutations.append(ldb_extra)

    rule_extra = deepcopy(baseline)
    rule_extra["language_bundle"]["language"]["rules"][0]["host_hook"] = "run"
    rule_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", rule_extra["language_bundle"]
    )
    mutations.append(rule_extra)

    for authority in mutations:
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False


def test_two_consumers_agree_on_report_all_cap_and_truncation():
    authority = authority_set()
    authority["kernel"]["resources"]["max_diagnostics"] = 3
    for index in range(8):
        authority["kernel"]["admission"]["laws"].append(
            {"id": f"mutant.{index}", "operation": f"unknown.{index}"}
        )
    _reidentify(authority["kernel"], authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["truncated"] is True
    assert len(first["diagnostics"]) == 3


def test_two_consumers_refuse_the_same_nesting_resource_exhaustion():
    authority = authority_set()
    nested: object = "leaf"
    for _ in range(authority["kernel"]["resources"]["max_nesting_depth"] + 1):
        nested = [nested]
    authority["language_bundle"]["vectors"][0]["unused_host_payload"] = nested
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["diagnostics"] == [
        ("ingress", "kernel.resource_exhausted", "language-bundle")
    ]
