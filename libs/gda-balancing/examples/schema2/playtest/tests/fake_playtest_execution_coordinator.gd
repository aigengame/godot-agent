extends RefCounted

var sessions_created := 0
var return_invalid_artifacts := false


func start(_model_source: Dictionary, _experiment: Dictionary) -> Dictionary:
	sessions_created += 1
	return {"ok": true, "revision": "baseline-%d" % sessions_created}


func admit_and_run(_experiment: Dictionary) -> Dictionary:
	return _run_result("candidate")


func run_initial_revision() -> Dictionary:
	return _run_result("baseline-%d" % sessions_created)


func retry(_model_source: Dictionary, _experiment: Dictionary) -> Dictionary:
	sessions_created += 1
	return {"ok": true, "revision": "baseline-%d" % sessions_created}


func shutdown() -> Dictionary:
	return {"ok": true}


func _run_result(revision: String) -> Dictionary:
	if return_invalid_artifacts:
		return {
			"ok": true,
			"revision": revision,
			"value": {"artifacts": {}},
		}
	return {
		"ok": false,
		"kind": "execution_refused",
		"detail": "sentinel",
		"stage": "execution",
		"value": {"outcome": "refusal"},
	}
