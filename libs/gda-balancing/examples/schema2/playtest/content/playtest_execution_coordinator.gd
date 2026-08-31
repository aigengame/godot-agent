class_name PlaytestExecutionCoordinator
extends RefCounted

var _client
var _executable_path := ""
var _session := ""
var _initial_revision := ""
var _service_started := false
var _busy := false


func configure(client, executable_path: String) -> void:
	_client = client
	_executable_path = executable_path


func start(model_source: Dictionary, experiment: Dictionary) -> Dictionary:
	if _busy:
		return _local_failure(
			"operation_in_flight",
			"an Execution lifecycle operation is already in flight",
			"startup",
		)
	if _service_started or not _session.is_empty():
		return _local_failure(
			"already_started",
			"the playtest Execution session is already started",
			"startup",
		)
	_busy = true
	var result := await _start_session(model_source, experiment)
	_busy = false
	return result


func admit_and_run(experiment: Dictionary) -> Dictionary:
	var unavailable := _operation_unavailable("revision_admission")
	if not unavailable.is_empty():
		return unavailable
	_busy = true
	var admitted: Dictionary = await _client.admit_revision(_session, experiment)
	if not admitted.get("ok", false):
		_busy = false
		return _stage_failure("revision_admission", admitted)
	var revision := str(admitted.get("revision", ""))
	if revision.is_empty():
		_busy = false
		return _local_failure(
			"invalid_revision_response",
			"revision admission returned no exact revision",
			"revision_admission",
		)
	var result := await _run_exact_revision(revision)
	_busy = false
	return result


func run_initial_revision() -> Dictionary:
	var unavailable := _operation_unavailable("execution")
	if not unavailable.is_empty():
		return unavailable
	if _initial_revision.is_empty():
		return _local_failure(
			"initial_revision_unavailable",
			"the Execution session returned no initial revision",
			"execution",
		)
	_busy = true
	var result := await _run_exact_revision(_initial_revision)
	_busy = false
	return result


func retry(model_source: Dictionary, experiment: Dictionary) -> Dictionary:
	if _busy:
		return _local_failure(
			"operation_in_flight",
			"an Execution lifecycle operation is already in flight",
			"retry_cleanup",
		)
	_busy = true
	var cleaned := await _cleanup()
	if not cleaned.get("ok", false):
		_busy = false
		return cleaned
	var result := await _start_session(model_source, experiment)
	_busy = false
	return result


func shutdown() -> Dictionary:
	if _busy:
		return _local_failure(
			"operation_in_flight",
			"an Execution lifecycle operation is already in flight",
			"shutdown",
		)
	_busy = true
	var result := await _cleanup()
	_busy = false
	return result


func _start_session(model_source: Dictionary, experiment: Dictionary) -> Dictionary:
	if _client == null:
		return _local_failure(
			"not_configured",
			"the playtest Execution coordinator is not configured",
			"startup",
		)
	var started: Dictionary = await _client.start(_executable_path)
	if not started.get("ok", false):
		return _stage_failure("startup", started)
	_service_started = true
	var created: Dictionary = await _client.create_session(model_source, experiment)
	if not created.get("ok", false):
		var failed := _stage_failure("session_creation", created)
		return _with_cleanup(failed, await _cleanup())
	_session = str(created.get("session", ""))
	_initial_revision = str(created.get("revision", ""))
	if _session.is_empty() or _initial_revision.is_empty():
		var failed := _local_failure(
			"invalid_session_response",
			"session creation returned no session or initial revision",
			"session_creation",
		)
		return _with_cleanup(failed, await _cleanup())
	return {"ok": true, "revision": _initial_revision}


func _run_exact_revision(revision: String) -> Dictionary:
	var run: Dictionary = await _client.run_revision(_session, revision)
	if not run.get("ok", false):
		return _stage_failure("execution", run)
	return {
		"ok": true,
		"revision": revision,
		"value": run.get("value", {}),
	}


func _operation_unavailable(stage: String) -> Dictionary:
	if _busy:
		return _local_failure(
			"operation_in_flight",
			"an Execution lifecycle operation is already in flight",
			stage,
		)
	if not _service_started or _session.is_empty():
		return _local_failure(
			"session_not_ready",
			"the playtest Execution session is not ready",
			stage,
		)
	return {}


func _cleanup() -> Dictionary:
	var primary_failure: Dictionary = {}
	if not _session.is_empty():
		var deleted: Dictionary = await _client.delete_session(_session)
		if not deleted.get("ok", false):
			primary_failure = _stage_failure("session_deletion", deleted)
	_session = ""
	_initial_revision = ""
	if _service_started:
		var stopped: Dictionary = await _client.shutdown()
		if not stopped.get("ok", false):
			var shutdown_failure := _stage_failure("shutdown", stopped)
			if primary_failure.is_empty():
				primary_failure = shutdown_failure
			else:
				primary_failure["cleanup_failures"] = [shutdown_failure]
	_service_started = false
	return {"ok": true} if primary_failure.is_empty() else primary_failure


func _with_cleanup(primary: Dictionary, cleanup: Dictionary) -> Dictionary:
	if cleanup.get("ok", false):
		return primary
	var result := primary.duplicate(true)
	result["cleanup_failures"] = [cleanup.duplicate(true)]
	return result


func _stage_failure(stage: String, failure: Dictionary) -> Dictionary:
	var result := failure.duplicate(true)
	result["ok"] = false
	result["stage"] = stage
	return result


func _local_failure(kind: String, detail: String, stage: String) -> Dictionary:
	return {
		"ok": false,
		"kind": kind,
		"detail": detail,
		"stage": stage,
		"value": {},
	}
