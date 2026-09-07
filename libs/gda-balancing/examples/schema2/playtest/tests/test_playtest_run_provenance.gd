extends "res://tests/playtest_test_case.gd"

const PlaytestRunProvenance = preload(
	"res://content/playtest_run_provenance.gd"
)


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	for primary_kind in ["evaluation-run", "experiment-verdict"]:
		var projected := PlaytestRunProvenance.project(_provenance_run(primary_kind))
		_expect(
			projected.get("primary_artifact_kind") == primary_kind,
			"%s is retained as the primary artifact" % primary_kind,
		)
		for member in [
			"primary_artifact_identity",
			"experiment_identity",
			"event_trace_identity",
			"snapshot_series_identity",
			"metric_dataset_identity",
		]:
			_expect(
				not str(projected.get(member, "")).is_empty(),
				"%s provenance includes %s" % [primary_kind, member],
			)
	for artifact_name in ["event-trace", "snapshot-series", "metric-dataset"]:
		for member in ["content_identity", "experiment_identity"]:
			var mismatched := _provenance_run("evaluation-run")
			mismatched["artifacts"][artifact_name][member] = "other-identity"
			_expect(
				PlaytestRunProvenance.project(mismatched).is_empty(),
				"%s retains its exact %s binding" % [artifact_name, member],
			)
	var incomplete := _provenance_run("evaluation-run")
	incomplete["artifacts"].erase("metric-dataset")
	_expect(
		PlaytestRunProvenance.project(incomplete).is_empty(),
		"incomplete provenance is refused",
	)
	_finish()


func _provenance_run(primary_kind: String) -> Dictionary:
	var artifacts := {
		"event-trace": {
			"artifact_kind": "event-trace",
			"content_identity": "trace-id",
			"experiment_identity": "experiment-id",
		},
		"snapshot-series": {
			"artifact_kind": "snapshot-series",
			"content_identity": "snapshots-id",
			"experiment_identity": "experiment-id",
		},
		"metric-dataset": {
			"artifact_kind": "metric-dataset",
			"content_identity": "metrics-id",
			"experiment_identity": "experiment-id",
		},
	}
	artifacts[primary_kind] = {
		"artifact_kind": primary_kind,
		"content_identity": "primary-id",
		"experiment_identity": "experiment-id",
		"event_trace_identity": "trace-id",
		"snapshot_series_identity": "snapshots-id",
		"metric_dataset_identity": "metrics-id",
	}
	return {"artifacts": artifacts}
