"""Public namespace ownership survives compilation, invocation and literal data."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

import gda_balancing
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _bind_package_vector_set,
    _encoded,
    _reidentify_package_release,
)
from schema2_bootstrap_production_support import _reidentify_graph_root


_OWNERS = ("genre.economy", "genre.rebate")
_PAYLOAD = {"id": "adjust-v1", "package": "genre.economy", "version": "1.0.0"}
_EFFECTS = ["event.commit", "metric.observe", "snapshot.commit"]


def _receipt_type(owner: str) -> dict[str, str]:
    return {"package": owner, "id": "Receipt"}


def _receipt(owner: str) -> dict[str, Any]:
    return {"type": _receipt_type(owner), "value": deepcopy(_PAYLOAD)}


def _quantity_port(name: str, access: str) -> dict[str, Any]:
    return {
        "access": access,
        "domain": {"kind": "actual"},
        "id": name,
        "kind": "scalar",
        "numeric_policy": "exact-int64",
        "representation": "Int",
        "type": {"package": "core.quantity", "id": "Quantity"},
        "unit": "1",
    }


def _operation(owner: str) -> dict[str, Any]:
    receipt_port = {
        "access": "read",
        "id": "receipt",
        "type": _receipt_type(owner),
        "value_kind": "nominal-structured",
    }
    result = {
        **receipt_port,
        "id": "result",
        "discardable": True,
        "source": {"kind": "local", "name": "receipt_result"},
    }
    inputs = [
        _quantity_port("account_balance", "read-write"),
        _quantity_port("price", "read"),
        receipt_port,
    ]
    body: list[dict[str, Any]] = [
        {"node": "subtract-state", "symbol": "account_balance", "value": "price"},
        {"node": "copy", "target": "receipt_result", "value": "receipt"},
    ]
    if owner == "genre.rebate":
        inputs.append(
            {
                **receipt_port,
                "id": "purchase_receipt",
                "type": _receipt_type("genre.economy"),
            }
        )
        body = [
            {
                "node": "invoke",
                "site": "purchase",
                "operation": {"package": "genre.economy", "id": "adjust-v1"},
                "arguments": [
                    {"port": port, "operand": {"kind": "port", "port": actual}}
                    for port, actual in (
                        ("account_balance", "account_balance"),
                        ("price", "price"),
                        ("receipt", "purchase_receipt"),
                    )
                ],
                "outcomes": [
                    {"outcome": "purchase-complete", "action": {"kind": "continue"}}
                ],
                "result": {"kind": "discard"},
            },
            {
                "node": "add",
                "target": "partial_rebate",
                "left": "account_balance",
                "right": "price",
            },
            {
                "node": "add",
                "target": "full_rebate",
                "left": "partial_rebate",
                "right": "price",
            },
            {
                "node": "write-state",
                "symbol": "account_balance",
                "value": "full_rebate",
            },
            {"node": "copy", "target": "receipt_result", "value": "receipt"},
        ]
    outcome = "purchase-complete" if owner == "genre.economy" else "rebate-complete"
    return {
        "alias_policy": {"read_only": "share", "writable_groups": []},
        "body": body,
        "default_outcome": outcome,
        "effects": deepcopy(_EFFECTS),
        "id": "adjust-v1",
        "inputs": inputs,
        "kind_rules": {"inputs": "preserve", "result": "preserve"},
        "numeric_policy": "exact-int64",
        "operation_kind": "event-program",
        "outcomes": [{"id": outcome, "kind": "success", "state_policy": "commit"}],
        "owner_type": "Receipt",
        "purity": "event",
        "refusals": ["runtime.reason.step-limit", "runtime.reason.numeric-overflow"],
        "resource_bounds": {"max_steps": 2 if owner == "genre.economy" else 7},
        "result": result,
        "rule": "structured.lower",
        "runtime_profile": "standard.exact-int64-event-v1",
        "unit_rules": {"inputs": "preserve", "result": "preserve"},
        "vectors": [
            f"{owner}.adjust.{member}"
            for member in ("body", "effects", "outcomes", "resource-bound")
        ],
    }


def _candidate(
    *, duplicate_owner: bool = False
) -> tuple[dict[str, Any], LanguageBundleIndex]:
    kernel, ldb = mutable_authorities()
    for owner in _OWNERS:
        package = deepcopy(
            next(
                row
                for row in ldb["language"]["packages"]
                if row["id"] == "standard.compiler"
            )
        )
        package["id"] = owner
        package["dependencies"] = {
            "optional": [],
            "required": sorted(
                ["core.quantity", "standard.runtime", "standard.schema"]
                + (["genre.economy"] if owner == "genre.rebate" else [])
            ),
        }
        package["capabilities"] = {
            "provided": [f"{owner}.adjust"],
            "required": ["quantity.lower", "structured.lower"],
        }
        package["exports"] = {member: [] for member in package["exports"]}
        package["exports"]["operations"] = ["adjust-v1"]
        package["exports"]["nominal_types"] = ["Token", "Receipt"]
        package["exports"]["types"] = [
            {"id": "Token", "constructor": "standard.schema.enum"},
            {"id": "Receipt", "constructor": "standard.schema.record"},
        ]
        package["profiles"] = {member: [] for member in package["profiles"]}
        package["runtime_semantic_excluded_extensions"] = []
        package["runtime_semantic_paths"] = [
            "language.capabilities",
            "language.nominal_types",
            "language.operations",
        ]
        operation = _operation(owner)
        definitions = {
            "language.capabilities": [
                {"id": f"{owner}.adjust", "rule": "structured.lower"}
            ],
            "language.nominal_types": [
                {
                    "id": "Token",
                    "package": owner,
                    "constructor": "standard.schema.enum",
                    "definition": {
                        "kind": "enum",
                        "members": ["adjust-v1", "genre.economy", "1.0.0"],
                    },
                },
                {
                    "id": "Receipt",
                    "package": owner,
                    "constructor": "standard.schema.record",
                    "definition": {
                        "kind": "record",
                        "fields": [
                            {
                                "name": name,
                                "type": {
                                    "kind": "nominal",
                                    "package": owner,
                                    "id": "Token",
                                },
                            }
                            for name in ("id", "package", "version")
                        ],
                    },
                },
            ],
            "language.operations": [operation],
        }
        if duplicate_owner and owner == "genre.economy":
            definitions["language.operations"].append(deepcopy(operation))
        for entry in package["semantic_closure"]:
            entry["definitions"] = definitions.get(entry["authority_path"], [])
        vectors = [
            {
                "category": category,
                "expect": deepcopy(
                    operation["resource_bounds"]["max_steps"]
                    if member == "resource_bounds.max_steps"
                    else operation[member]
                ),
                "id": f"{owner}.adjust.{suffix}",
                "kind": "operation-contract",
                "operation": "adjust-v1",
                "probe": {"path": member},
            }
            for category, suffix, member in (
                ("positive", "body", "body"),
                ("effects", "effects", "effects"),
                ("outcome", "outcomes", "outcomes"),
                ("resource", "resource-bound", "resource_bounds.max_steps"),
            )
        ]
        vector_set = {
            "artifact_kind": "package-conformance-vector-set",
            "package_id": owner,
            "vectors": [row["id"] for row in vectors],
            "vector_definitions": vectors,
        }
        _bind_package_vector_set(package, vector_set)
        ldb["language"]["packages"].append(package)
        ldb.package_conformance_vector_sets.append(vector_set)
    # Ownership is authored above in the attached closures. Flat recapture would
    # mix the two distinct definitions which intentionally share a local ID.
    _reidentify_graph_root(ldb)
    return kernel, ldb


def _source() -> dict[str, Any]:
    symbols = [
        {
            "symbol": name,
            "type": "quantity",
            "role": role,
            "representation": "Int",
            "kind": "scalar",
            "unit": "1",
            "domain_kind": "closed-interval",
            "domain": {"minimum": 0, "maximum": 100},
            "numeric_policy": "exact-int64",
            "value_policy": {"mode": "experiment-required"},
        }
        for name, role in (("account_balance", "state"), ("price", "parameter"))
    ]
    imports = [{"alias": "quantity", "package": "core.quantity", "symbol": "Quantity"}]
    entrypoints = []
    for owner in _OWNERS:
        label = owner.split(".")[1]
        imports.append(
            {"alias": f"{label}-receipt", "package": owner, "symbol": "Receipt"}
        )
        symbols.append(
            {
                "symbol": f"{label}_receipt",
                "type": f"{label}-receipt",
                "role": "output",
                "value_policy": {"mode": "none"},
            }
        )
        arguments = [
            {
                "port": name,
                "operand": {"kind": "symbol", "module": "main", "symbol": name},
            }
            for name in ("account_balance", "price")
        ]
        arguments.append(
            {
                "port": "receipt",
                "operand": {"kind": "literal", "value": _receipt(owner)},
            }
        )
        if owner == "genre.rebate":
            arguments.append(
                {
                    "port": "purchase_receipt",
                    "operand": {"kind": "literal", "value": _receipt("genre.economy")},
                }
            )
        entrypoints.append(
            {
                "id": label,
                "operation": {"package": owner, "id": "adjust-v1"},
                "arguments": arguments,
                "result": {
                    "kind": "symbol",
                    "module": "main",
                    "symbol": f"{label}_receipt",
                },
            }
        )
    return {
        "schema_version": "2.0.0",
        "manifest": {"id": "example.namespace-ownership", "entry_module": "main"},
        "package_requirements": ["core.quantity", *_OWNERS],
        "modules": [{"id": "main", "imports": imports, "symbols": symbols}],
        "entrypoints": entrypoints,
    }


class _PublicCandidate:
    def __init__(self, directory: Path, *, duplicate_owner: bool = False):
        self.directory = directory
        self.runtime = directory / "runtime"
        package_source = Path(gda_balancing.__file__).parent
        package_copy = self.runtime / "gda_balancing"
        shutil.copytree(
            package_source,
            package_copy,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        self.kernel, self.ldb = _candidate(duplicate_owner=duplicate_owner)
        authority = package_copy / "schema2" / "authorities"
        (authority / "kernel.json").write_bytes(_encoded(self.kernel))
        (authority / "language-bundle.json").write_bytes(_encoded(self.ldb.root))
        for package, vectors in zip(
            self.ldb.package_releases,
            self.ldb.package_conformance_vector_sets,
            strict=True,
        ):
            namespace = package["id"]
            target = authority / "packages" / namespace.replace(".", "-")
            target.mkdir(exist_ok=True)
            (target / f"{namespace}.json").write_bytes(_encoded(package))
            (target / f"{namespace}.conformance-vectors.json").write_bytes(
                _encoded(vectors)
            )
        # Assert the public subprocess receives precisely the production Python.
        for path in package_source.rglob("*.py"):
            assert (
                path.read_bytes()
                == (package_copy / path.relative_to(package_source)).read_bytes()
            )
            assert all(owner not in path.read_text() for owner in _OWNERS)
        self.env = {
            **os.environ,
            "PYTHONPATH": str(self.runtime),
            "GDA_BALANCING_STORE_DIR": str(directory / "store"),
            "GDA_BALANCING_ANCHOR_KEY": "a5" * 32,
        }
        imported = subprocess.run(
            [
                sys.executable,
                "-c",
                "import gda_balancing; print(gda_balancing.__file__)",
            ],
            env=self.env,
            cwd=directory,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        assert Path(imported.stdout.strip()) == package_copy / "__init__.py"
        self.source = directory / "model-source.json"
        self.write_source(_source())
        self.receipts: list[dict[str, Any]] = []

    def write_source(self, value: dict[str, Any]) -> None:
        self.source.write_text(json.dumps(value))

    def cli(self, *arguments: str, success: bool = True) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-m", "gda_balancing", *arguments],
            cwd=self.directory,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.receipts.append(
            {
                "arguments": arguments,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (self.directory / "cli-results.json").write_text(
            json.dumps(self.receipts, indent=2)
        )
        assert (result.returncode == 0) == success, self.receipts[-1]
        assert result.stderr == "", self.receipts[-1]
        return json.loads(result.stdout)


def _members(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        row["logical_name"]: json.loads(Path(row["locator"]).read_text())
        for row in receipt["member_locators"]
    }


def _experiment(build: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "id": "example.namespace-ownership",
        "kernel_identity": build["kernel_identity"],
        "language_bundle_identity": build["language_bundle_identity"],
        "model": {
            member: build[
                "content_identity" if member == "build_receipt_identity" else member
            ]
            for member in (
                "source_identity",
                "build_receipt_identity",
                "resolved_model_identity",
                "package_lock_identity",
                "rir_identity",
            )
        },
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-program"],
                "instruction_nodes": [
                    "add",
                    "copy",
                    "invoke",
                    "subtract-state",
                    "write-state",
                ],
                "effects": deepcopy(_EFFECTS),
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
                "runtime_profiles": ["standard.exact-int64-event-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 20260727},
        "scenarios": [
            {
                "id": "round-trip",
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": name,
                        "logical_time": index,
                        "priority": 0,
                        "entrypoint": name,
                        "payload": [],
                    }
                    for index, name in enumerate(("economy", "rebate"))
                ],
                "assignments": [
                    {
                        "target": {
                            "model": "example.namespace-ownership",
                            "module": "main",
                            "name": name,
                        },
                        "value": value,
                    }
                    for name, value in (("account_balance", 100), ("price", 25))
                ],
                "named_streams": [],
                "terminal_condition": {"kind": "event-count", "maximum": 2},
            }
        ],
        "metrics": [
            {
                "id": "terminal-balance",
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "account_balance",
                },
                "target": {"minimum": 100, "maximum": 100},
            }
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }


def test_public_namespace_owned_operations_and_literal_data(tmp_path: Path) -> None:
    candidate = _PublicCandidate(tmp_path)
    assert candidate.cli("model", "check", str(candidate.source))["checked"] is True
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "01" * 32,
    )
    artifacts = _members(receipt)
    rir = artifacts["rir-semantic-payload"]
    operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    for owner in _OWNERS:
        assert operations[(owner, "adjust-v1")] == _operation(owner)
    nominal = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in rir["selected_semantics"]["nominal_types"]
    }
    for owner in _OWNERS:
        assert [
            row["name"] for row in nominal[(owner, "Receipt")]["definition"]["fields"]
        ] == ["id", "package", "version"]
    assert {row["operation"]["package"] for row in rir["entrypoints"]} == set(_OWNERS)
    literals = [
        argument["operand"]["value"]
        for row in rir["entrypoints"]
        for argument in row["arguments"]
        if argument["operand"]["kind"] == "literal"
    ]
    assert literals == [
        _receipt("genre.economy"),
        _receipt("genre.rebate"),
        _receipt("genre.economy"),
    ]
    explanation = candidate.cli(
        "model",
        "inspect",
        str(Path(receipt["manifest_locator"]).parent / "artifact-set-receipt.json"),
    )
    structured = [
        row
        for row in explanation["declaration_explanations"]
        if row.get("value_kind") == "nominal-structured"
    ]
    assert {row["type_identity"]["package"] for row in structured} == set(_OWNERS)
    experiment_path = tmp_path / "experiment.json"
    experiment_path.write_text(json.dumps(_experiment(artifacts["build-receipt"])))
    assert candidate.cli("experiment", "check", str(experiment_path))["checked"] is True
    evaluation = _members(
        candidate.cli(
            "experiment",
            "run",
            str(experiment_path),
            "--out",
            str(tmp_path / "evaluation"),
            "--invocation-key",
            "02" * 32,
        )
    )
    events = [
        event
        for event in evaluation["event-trace"]["events"]
        if event["observation"] is None
    ]
    assert [row["outcome"] for row in events] == [
        {"id": "purchase-complete", "kind": "success"},
        {"id": "rebate-complete", "kind": "success"},
    ]
    assert [
        {row["name"]: row["value"] for row in event["state_after"]}["account_balance"]
        for event in events
    ] == [75, 100]
    for owner, event in zip(_OWNERS, events, strict=True):
        output = next(
            row
            for row in event["facts"]
            if row["name"] == f"{owner.split('.')[1]}_receipt"
        )
        assert output["kind"] == "structured"
        assert output["value"] == _receipt(owner)
    assert evaluation["metric-dataset"]["samples"][0]["value"] == 100
    assert evaluation["metric-dataset"]["samples"][0]["within_target"] is True


@pytest.mark.parametrize(
    "mutation",
    ("operation-owner", "nominal-owner", "missing-namespace", "duplicate-namespace"),
)
def test_public_namespace_binding_refusals_are_atomic(
    tmp_path: Path, mutation: str
) -> None:
    candidate = _PublicCandidate(tmp_path)
    source = _source()
    if mutation == "operation-owner":
        source["entrypoints"][0]["operation"]["package"] = "core.quantity"
    elif mutation == "nominal-owner":
        source["entrypoints"][0]["arguments"][2]["operand"]["value"]["type"][
            "package"
        ] = "genre.rebate"
    elif mutation == "missing-namespace":
        source["package_requirements"].append("genre.absent")
    else:
        source["package_requirements"].append("genre.economy")
    candidate.write_source(source)
    checked = candidate.cli("model", "check", str(candidate.source), success=False)
    built = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "refused-build"),
        "--invocation-key",
        "03" * 32,
        success=False,
    )
    error = checked["error"]
    assert error["category"] == "refusal"
    assert error["stage"] == (
        "resolution" if mutation == "missing-namespace" else "static"
    )
    assert error["diagnostics"] == built["error"]["diagnostics"]
    code, pointer = {
        "operation-owner": (
            "language.source_contract_mismatch",
            "/entrypoints/0/operation/id",
        ),
        "nominal-owner": (
            "language.source_contract_mismatch",
            "/entrypoints/0/arguments/2/operand",
        ),
        "missing-namespace": (
            "language.package_unavailable",
            "/package_requirements/3",
        ),
        "duplicate-namespace": ("language.name_ambiguity", "/package_requirements/3"),
    }[mutation]
    diagnostic = next(row for row in error["diagnostics"] if row["code"] == code)
    assert diagnostic["primary"]["pointer"] == pointer
    if mutation == "duplicate-namespace":
        assert [row["pointer"] for row in diagnostic["related"]] == [
            "/package_requirements/1"
        ]
    assert not (tmp_path / "refused-build").exists()
    assert not list((tmp_path / "store" / "anchors").rglob("*.json"))


def test_public_same_owner_duplicate_refuses_after_reidentification(
    tmp_path: Path,
) -> None:
    candidate = _PublicCandidate(tmp_path, duplicate_owner=True)
    package = next(
        row for row in candidate.ldb.package_releases if row["id"] == "genre.economy"
    )
    operations = next(
        row["definitions"]
        for row in package["semantic_closure"]
        if row["authority_path"] == "language.operations"
    )
    assert len(operations) == 2
    assert operations[0] == operations[1]
    resealed = deepcopy(package)
    _reidentify_package_release(resealed)
    assert resealed["semantic_identity"] == package["semantic_identity"]
    assert resealed["content_identity"] == package["content_identity"]
    # Duplicate keys violate the package closure before the later identifier law.
    # This existing ingress refusal must survive public CLI initialization with
    # its real stage and location; the recomputation above rules out stale bytes.
    checked = candidate.cli("model", "check", str(candidate.source), success=False)
    built = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "refused-build"),
        "--invocation-key",
        "04" * 32,
        success=False,
    )
    assert checked == built
    error = checked["error"]
    assert error["category"] == "refusal"
    assert error["stage"] == "ingress"
    assert error["truncated"] is False
    assert len(error["diagnostics"]) == 1
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "kernel.identity_mismatch"
    assert diagnostic["primary"] == {
        "kind": "artifact",
        "content_identity": candidate.ldb["content_identity"],
        "pointer": "/language-bundle/language/packages/8/semantic_identity",
    }
    assert not (tmp_path / "refused-build").exists()
    assert not list((tmp_path / "store" / "anchors").rglob("*.json"))
