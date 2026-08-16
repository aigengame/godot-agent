class_name GdaExecutionClient
extends Node

const PROTOCOL := "v1"
const STARTUP_TIMEOUT_MSEC := 15000
const SHUTDOWN_TIMEOUT_MSEC := 5000

var _base_url := ""
var _capability_token := ""
var _pid := -1
var _stdio: FileAccess
var _stderr: FileAccess


func start(executable_path: String = "") -> Dictionary:
	if _pid > 0:
		return _failure("already_started", "the local service is already running")
	if executable_path.is_empty() or not FileAccess.file_exists(executable_path):
		return _failure("executable_not_found", executable_path)

	var process := OS.execute_with_pipe(
		executable_path,
		PackedStringArray(["serve", "--host", "127.0.0.1", "--port", "0"]),
		false,
	)
	if process.is_empty():
		return _failure("startup_failed", executable_path)

	_pid = int(process["pid"])
	_stdio = process["stdio"]
	_stderr = process["stderr"]
	var readiness := await _read_readiness()
	if not readiness.get("ok", false):
		_force_stop()
		return readiness

	var value: Dictionary = readiness["value"]
	if (
		value.get("status") != "ready"
		or value.get("protocol") != PROTOCOL
		or not value.get("base_url") is String
		or not value.get("capability_token") is String
	):
		_force_stop()
		return _failure("incompatible_readiness", JSON.stringify(value))
	_base_url = value["base_url"]
	_capability_token = value["capability_token"]

	var status := await _request_json("GET", "/v1/status")
	if (
		not status.get("ok", false)
		or status.get("value", {}).get("protocol") != PROTOCOL
		or status.get("value", {}).get("toolkit_version")
		!= value.get("toolkit_version")
	):
		await shutdown()
		return _failure("incompatible_service", JSON.stringify(status))
	return {"ok": true, "value": value}


func create_session(model_source: Dictionary, experiment: Dictionary) -> Dictionary:
	var response := await _request_json(
		"POST",
		"/v1/execution-sessions",
		{
			"model_source": model_source,
			"experiment_specification": experiment,
		},
	)
	if not response.get("ok", false):
		return response
	var value: Dictionary = response["value"]
	if value.get("outcome") != "success":
		return _failure("execution_refused", JSON.stringify(value), value)
	return {
		"ok": true,
		"session": value["session_id"],
		"revision": value["revision_id"],
		"value": value,
	}


func admit_revision(session: String, experiment: Dictionary) -> Dictionary:
	var response := await _request_json(
		"POST",
		"/v1/execution-sessions/%s/experiment-revisions" % session,
		{"experiment_specification": experiment},
	)
	if not response.get("ok", false):
		return response
	var value: Dictionary = response["value"]
	if value.get("outcome") != "success":
		return _failure("execution_refused", JSON.stringify(value), value)
	return {"ok": true, "revision": value["revision_id"], "value": value}


func run_revision(session: String, revision: String) -> Dictionary:
	var response := await _request_json(
		"POST",
		"/v1/execution-sessions/%s/runs" % session,
		{"revision_id": revision},
	)
	if not response.get("ok", false):
		return response
	var value: Dictionary = response["value"]
	if value.get("outcome") not in ["success", "verdict"]:
		return _failure("execution_refused", JSON.stringify(value), value)
	return {"ok": true, "value": value}


func delete_session(session: String) -> Dictionary:
	return await _request_json(
		"DELETE",
		"/v1/execution-sessions/%s" % session,
	)


func shutdown() -> Dictionary:
	if _pid <= 0:
		return {"ok": true}
	var response := await _request_json("POST", "/v1/shutdown")
	var deadline := Time.get_ticks_msec() + SHUTDOWN_TIMEOUT_MSEC
	while OS.is_process_running(_pid) and Time.get_ticks_msec() < deadline:
		await get_tree().process_frame
	if OS.is_process_running(_pid):
		_force_stop()
		return _failure("shutdown_timeout", "the local service did not exit")
	_clear_process()
	return response


func _read_readiness() -> Dictionary:
	var deadline := Time.get_ticks_msec() + STARTUP_TIMEOUT_MSEC
	var pending := ""
	while Time.get_ticks_msec() < deadline:
		if not OS.is_process_running(_pid):
			return _failure("process_exited", _read_stderr())
		var fragment := _stdio.get_line()
		if not fragment.is_empty():
			pending += fragment
			var value = JSON.parse_string(pending)
			if value is Dictionary:
				return {"ok": true, "value": value}
		await get_tree().process_frame
	return _failure("startup_timeout", _read_stderr())


func _request_json(
	method_name: String,
	path: String,
	body_value = null,
) -> Dictionary:
	if _base_url.is_empty() or _capability_token.is_empty():
		return _failure("service_not_ready", "the local service is not ready")
	if _pid <= 0 or not OS.is_process_running(_pid):
		return _failure("process_exited", _read_stderr())

	var request := HTTPRequest.new()
	request.timeout = 30.0
	add_child(request)
	var headers := PackedStringArray([
		"Accept: application/json",
		"Authorization: Bearer %s" % _capability_token,
	])
	var request_body := ""
	if body_value != null:
		var canonical := _canonical_transport_value(body_value)
		if not canonical.get("ok", false):
			request.queue_free()
			return canonical
		headers.append("Content-Type: application/json")
		request_body = JSON.stringify(canonical["value"])
	var method := HTTPClient.METHOD_GET
	match method_name:
		"DELETE":
			method = HTTPClient.METHOD_DELETE
		"POST":
			method = HTTPClient.METHOD_POST
	var error := request.request(_base_url + path, headers, method, request_body)
	if error != OK:
		request.queue_free()
		return _failure("transport_failed", error_string(error))
	var completed: Array = await request.request_completed
	request.queue_free()
	var result := int(completed[0])
	var response_code := int(completed[1])
	var response_body: PackedByteArray = completed[3]
	if result != HTTPRequest.RESULT_SUCCESS:
		return _failure("transport_failed", str(result))
	var decoded = JSON.parse_string(response_body.get_string_from_utf8())
	if not decoded is Dictionary:
		return _failure("invalid_response", response_body.get_string_from_utf8())
	if response_code < 200 or response_code >= 300:
		return _failure("service_error", JSON.stringify(decoded), decoded)
	return {"ok": true, "value": decoded}


func _canonical_transport_value(value) -> Dictionary:
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING:
			return {"ok": true, "value": value}
		TYPE_FLOAT:
			var integer := int(value)
			if not is_finite(value) or float(integer) != value:
				return _failure(
					"invalid_canonical_value",
					"non-integer JSON number",
				)
			return {"ok": true, "value": integer}
		TYPE_ARRAY:
			var normalized: Array = []
			for item in value:
				var child := _canonical_transport_value(item)
				if not child.get("ok", false):
					return child
				normalized.append(child["value"])
			return {"ok": true, "value": normalized}
		TYPE_DICTIONARY:
			var normalized: Dictionary = {}
			for key in value:
				if not key is String:
					return _failure(
						"invalid_canonical_value",
						"JSON object key is not a string",
					)
				var child := _canonical_transport_value(value[key])
				if not child.get("ok", false):
					return child
				normalized[key] = child["value"]
			return {"ok": true, "value": normalized}
	return _failure("invalid_canonical_value", type_string(typeof(value)))


func _read_stderr() -> String:
	if _stderr == null:
		return ""
	var content := ""
	while true:
		var line := _stderr.get_line()
		if line.is_empty():
			break
		content += line + "\n"
	return content.strip_edges()


func _failure(kind: String, detail: String, value: Dictionary = {}) -> Dictionary:
	return {"ok": false, "kind": kind, "detail": detail, "value": value}


func _force_stop() -> void:
	if _pid > 0 and OS.is_process_running(_pid):
		OS.kill(_pid)
	_clear_process()


func _clear_process() -> void:
	_pid = -1
	_base_url = ""
	_capability_token = ""
	_stdio = null
	_stderr = null


func _exit_tree() -> void:
	_force_stop()
