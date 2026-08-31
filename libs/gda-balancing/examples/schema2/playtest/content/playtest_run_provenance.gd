class_name PlaytestRunProvenance
extends RefCounted


static func project(run_result: Dictionary) -> Dictionary:
	var artifacts_value = run_result.get("artifacts")
	if not artifacts_value is Dictionary:
		return {}
	var artifacts: Dictionary = artifacts_value
	var primary_names: Array[String] = []
	for name in ["evaluation-run", "experiment-verdict"]:
		var candidate = artifacts.get(name)
		if candidate is Dictionary and candidate.get("artifact_kind") == name:
			primary_names.append(name)
	if primary_names.size() != 1:
		return {}

	var primary_name := primary_names[0]
	var primary: Dictionary = artifacts[primary_name]
	var primary_identity := str(primary.get("content_identity", ""))
	var experiment_identity := str(primary.get("experiment_identity", ""))
	if primary_identity.is_empty() or experiment_identity.is_empty():
		return {}

	var artifact_bindings := {
		"event-trace": "event_trace_identity",
		"snapshot-series": "snapshot_series_identity",
		"metric-dataset": "metric_dataset_identity",
		"reproduction-receipt": "reproduction_receipt_identity",
	}
	var projected := {
		"primary_artifact_kind": primary_name,
		"primary_artifact_identity": primary_identity,
		"experiment_identity": experiment_identity,
	}
	for artifact_name in artifact_bindings:
		var artifact_value = artifacts.get(artifact_name)
		if not artifact_value is Dictionary:
			return {}
		var artifact: Dictionary = artifact_value
		var identity := str(artifact.get("content_identity", ""))
		var binding_member: String = artifact_bindings[artifact_name]
		if (
			artifact.get("artifact_kind") != artifact_name
			or identity.is_empty()
			or primary.get(binding_member) != identity
		):
			return {}
		if artifact.get("experiment_identity") != experiment_identity:
			return {}
		projected[binding_member] = identity
	return projected
