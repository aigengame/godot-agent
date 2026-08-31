extends "res://tests/playtest_test_case.gd"

const PlaytestExecutionCoordinator = preload(
	"res://content/playtest_execution_coordinator.gd"
)

class RecordingClient extends RefCounted:
	var calls: Array[String] = []
	var failures: Dictionary = {}
	var sessions_created := 0

	func start(_executable: String) -> Dictionary:
		calls.append("start")
		return _result("startup")

	func create_session(_model: Dictionary, _experiment: Dictionary) -> Dictionary:
		calls.append("create_session")
		var result := _result("session_creation")
		if not result.get("ok", false):
			return result
		sessions_created += 1
		return {
			"ok": true,
			"session": "session-%d" % sessions_created,
			"revision": "baseline-%d" % sessions_created,
		}

	func admit_revision(_session: String, _experiment: Dictionary) -> Dictionary:
		calls.append("admit_revision")
		var result := _result("revision_admission")
		if not result.get("ok", false):
			return result
		return {"ok": true, "revision": "candidate-%d" % sessions_created}

	func run_revision(_session: String, revision: String) -> Dictionary:
		calls.append("run_revision:%s" % revision)
		var result := _result("execution")
		if not result.get("ok", false):
			return result
		return {"ok": true, "value": {"revision": revision}}

	func delete_session(_session: String) -> Dictionary:
		calls.append("delete_session")
		return _result("session_deletion")

	func shutdown() -> Dictionary:
		calls.append("shutdown")
		return _result("shutdown")

	func _result(stage: String) -> Dictionary:
		if failures.has(stage):
			return failures[stage].duplicate(true)
		return {"ok": true}


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	await _verify_success_and_exact_revision()
	await _verify_startup_and_creation_failures()
	await _verify_admission_and_execution_failures()
	await _verify_retry_and_cleanup_boundaries()
	_finish()


func _verify_success_and_exact_revision() -> void:
	var client := RecordingClient.new()
	var coordinator: PlaytestExecutionCoordinator = _coordinator(client)
	var started: Dictionary = await coordinator.start({}, {})
	_expect(started == {"ok": true, "revision": "baseline-1"}, "session starts once")
	var duplicate: Dictionary = await coordinator.start({}, {})
	_expect(duplicate.get("kind") == "already_started", "double start is rejected")
	var executed: Dictionary = await coordinator.admit_and_run({"trial": 1})
	_expect(executed.get("revision") == "candidate-1", "admitted revision is returned")
	_expect(
		client.calls == [
			"start",
			"create_session",
			"admit_revision",
			"run_revision:candidate-1",
		],
		"the exact admitted revision is run in order",
	)
	var stopped: Dictionary = await coordinator.shutdown()
	_expect(stopped.get("ok", false), "successful teardown completes")
	_expect(
		client.calls.slice(-2) == ["delete_session", "shutdown"],
		"teardown deletes the session before shutdown",
	)


func _verify_startup_and_creation_failures() -> void:
	var startup_client := RecordingClient.new()
	startup_client.failures["startup"] = _typed_failure("startup-sentinel")
	var startup: Dictionary = await _coordinator(startup_client).start({}, {})
	_expect(startup.get("stage") == "startup", "startup failure identifies its stage")
	_expect(
		startup.get("value", {}).get("marker") == "startup-sentinel",
		"startup failure preserves the typed payload",
	)
	_expect(startup_client.calls == ["start"], "failed startup needs no cleanup")

	var creation_client := RecordingClient.new()
	creation_client.failures["session_creation"] = _typed_failure("create-sentinel")
	var creation: Dictionary = await _coordinator(creation_client).start({}, {})
	_expect(
		creation.get("stage") == "session_creation",
		"session creation failure identifies its stage",
	)
	_expect(
		creation_client.calls == ["start", "create_session", "shutdown"],
		"partial startup still shuts down the service",
	)


func _verify_admission_and_execution_failures() -> void:
	var admission_client := RecordingClient.new()
	var admission_coordinator: PlaytestExecutionCoordinator = _coordinator(
		admission_client
	)
	await admission_coordinator.start({}, {})
	admission_client.failures["revision_admission"] = _typed_failure("admit-sentinel")
	var admission: Dictionary = await admission_coordinator.admit_and_run({})
	_expect(
		admission.get("stage") == "revision_admission",
		"admission failure identifies its stage",
	)
	_expect(
		admission.get("value", {}).get("marker") == "admit-sentinel",
		"admission failure preserves the typed payload",
	)
	await admission_coordinator.shutdown()

	var execution_client := RecordingClient.new()
	var execution_coordinator: PlaytestExecutionCoordinator = _coordinator(
		execution_client
	)
	await execution_coordinator.start({}, {})
	execution_client.failures["execution"] = _typed_failure("run-sentinel")
	var execution: Dictionary = await execution_coordinator.run_initial_revision()
	_expect(execution.get("stage") == "execution", "run failure identifies its stage")
	_expect(
		execution_client.calls.has("run_revision:baseline-1"),
		"the initial exact revision is used",
	)
	await execution_coordinator.shutdown()


func _verify_retry_and_cleanup_boundaries() -> void:
	var retry_client := RecordingClient.new()
	var retry_coordinator: PlaytestExecutionCoordinator = _coordinator(retry_client)
	await retry_coordinator.start({}, {})
	var retried: Dictionary = await retry_coordinator.retry({}, {})
	_expect(retried.get("revision") == "baseline-2", "retry creates a fresh session")
	_expect(
		retry_client.calls == [
			"start",
			"create_session",
			"delete_session",
			"shutdown",
			"start",
			"create_session",
		],
		"retry completes cleanup before starting again",
	)
	await retry_coordinator.shutdown()

	var delete_client := RecordingClient.new()
	var delete_coordinator: PlaytestExecutionCoordinator = _coordinator(delete_client)
	await delete_coordinator.start({}, {})
	delete_client.failures["session_deletion"] = _typed_failure("delete-sentinel")
	var deletion: Dictionary = await delete_coordinator.retry({}, {})
	_expect(
		deletion.get("stage") == "session_deletion",
		"session deletion is the primary cleanup failure",
	)
	_expect(delete_client.calls.has("shutdown"), "shutdown continues after delete failure")
	_expect(delete_client.calls.count("start") == 1, "failed cleanup does not restart")

	var shutdown_client := RecordingClient.new()
	var shutdown_coordinator: PlaytestExecutionCoordinator = _coordinator(
		shutdown_client
	)
	await shutdown_coordinator.start({}, {})
	shutdown_client.failures["shutdown"] = _typed_failure("shutdown-sentinel")
	var shutdown: Dictionary = await shutdown_coordinator.shutdown()
	_expect(shutdown.get("stage") == "shutdown", "shutdown failure identifies its stage")


func _coordinator(client: RecordingClient) -> PlaytestExecutionCoordinator:
	var coordinator := PlaytestExecutionCoordinator.new()
	coordinator.configure(client, "unused")
	return coordinator


func _typed_failure(marker: String) -> Dictionary:
	return {
		"ok": false,
		"kind": "execution_refused",
		"detail": marker,
		"value": {"marker": marker, "outcome": "refusal"},
	}
