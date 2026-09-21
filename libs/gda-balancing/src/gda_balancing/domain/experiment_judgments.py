"""Select the exact language judgments for authored Experiment intent."""

from collections.abc import Mapping, Sequence
from typing import Any

from gda_balancing.domain.canonical import canonical_bytes


def metric_selector(metric: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{
            name: metric[name]
            for name in ("kind", "aggregation", "replication", "missing", "censoring")
        },
        "window": {"kind": metric["window"]["kind"]},
        "observation": {"source": metric["observation"]["source"]},
    }


def select_metric_judgment(
    metric: Mapping[str, Any], language: Mapping[str, Any]
) -> dict[str, Any]:
    selector = canonical_bytes(metric_selector(metric))
    matches = [
        row
        for row in language["experiment_metric_judgments"]
        if canonical_bytes(row["selector"]) == selector
    ]
    if len(matches) != 1:
        raise ValueError("Metric intent must select exactly one language judgment")
    return matches[0]


def select_acceptance_judgment(
    policy: str, language: Mapping[str, Any]
) -> dict[str, Any]:
    matches = [
        row
        for row in language["experiment_acceptance_judgments"]
        if row["id"] == policy
    ]
    if len(matches) != 1:
        raise ValueError("Acceptance intent must select exactly one language judgment")
    return matches[0]


def acceptance_result(
    judgment: Mapping[str, Any], samples: Sequence[Mapping[str, Any]]
) -> tuple[bool, list[str]]:
    """Execute the finite all-samples judgment, never the authored policy name."""
    if judgment["operator"] != "all-metrics-within-target":
        raise ValueError("Unsupported admitted acceptance operator")
    if not samples or any(
        type(sample["within_target"]) is not bool for sample in samples
    ):
        raise ValueError("Acceptance requires complete boolean Metric samples")
    failed = [sample["metric"] for sample in samples if not sample["within_target"]]
    return not failed, failed


def acceptance_output_role(contracts: Mapping[str, Any], accepted: bool) -> str:
    """Select the existing outcome contract for the finite judgment result."""
    status = "accepted" if accepted else "rejected"
    matches = [
        role
        for role, contract in contracts.items()
        if contract.schema["properties"].get("outcome") == {"const": status}
    ]
    if len(matches) != 1:
        raise ValueError("Acceptance requires exactly one matching outcome contract")
    return matches[0]
