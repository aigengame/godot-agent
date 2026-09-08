"""Inspect or consume model facts, then evaluate project intent."""

from gda_assets.application.ports import ModelInspectionPort, PortFailure
from gda_assets.domain.artifacts import PipelineFailure
from gda_assets.domain.expectations import Expectation, evaluate
from gda_assets.domain.model import ModelCheckResult, ModelFacts


def check_model(
    conditions: tuple[Expectation, ...],
    *,
    path: str | None = None,
    godot: ModelInspectionPort | None = None,
    report: ModelFacts | None = None,
    subtree: str = ".",
    max_nodes: int = 256,
    max_items: int = 1024,
    baseline: ModelFacts | None = None,
) -> ModelCheckResult:
    result = ModelCheckResult(resource=path)
    stage = "validate"
    try:
        if (path is None) == (report is None):
            raise PortFailure("invalid_check", "Select exactly one of path or report")
        if report is None and godot is None:
            raise PortFailure(
                "invalid_check", "A Godot port is required for inspection"
            )
        result.completed.append("validate")
        stage = "inspect"
        if report is None:
            if path is None or godot is None:
                raise PortFailure(
                    "invalid_check",
                    "A model path and Godot port are required for inspection",
                )
            report = godot.inspect_model(
                path, subtree=subtree, max_nodes=max_nodes, max_items=max_items
            )
            result.observation_source = "godot"
            result.completed.append("inspect")
        else:
            result.observation_source = "supplied_report"
        result.resource = report.resource
        result.checks = evaluate(conditions, report)
        result.verdict = (
            "fail"
            if any(c.verdict == "fail" for c in result.checks)
            else "insufficient"
            if any(c.verdict == "insufficient" for c in result.checks)
            else "pass"
        )
        result.completed.append("evaluate")
        if baseline is not None:
            from gda_assets.domain.model_diff import compare_models

            result.comparison = compare_models(baseline, report)
            result.completed.append("compare")
    except PortFailure as exc:
        result.failure = PipelineFailure(stage, exc.code, str(exc), exc.cause)
    return result
