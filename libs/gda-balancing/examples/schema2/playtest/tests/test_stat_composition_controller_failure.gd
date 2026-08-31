extends "res://tests/playtest_test_case.gd"

const StatCompositionController = preload(
	"res://content/stat_composition/stat_composition_controller.gd"
)

class RefusingClient extends Node:
	var sessions_created := 0
	var return_invalid_artifacts := false

	func start(_executable: String) -> Dictionary:
		return {"ok": true}

	func create_session(_model: Dictionary, _experiment: Dictionary) -> Dictionary:
		sessions_created += 1
		return {"ok": true, "session": "session-%d" % sessions_created}

	func admit_revision(_session: String, _experiment: Dictionary) -> Dictionary:
		return {"ok": true, "revision": "later"}

	func run_revision(_session: String, _revision: String) -> Dictionary:
		if return_invalid_artifacts:
			return {"ok": true, "value": {"artifacts": {}}}
		return {"ok": false, "kind": "execution_refused", "detail": "sentinel"}

	func delete_session(_session: String) -> Dictionary:
		return {"ok": true}

	func shutdown() -> Dictionary:
		return {"ok": true}


func _init() -> void:
	super()
	call_deferred("_run")


func _run() -> void:
	var client := RefusingClient.new()
	get_root().add_child(client)
	var controller := StatCompositionController.new()
	get_root().add_child(controller)
	controller.configure(client, "unused")
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "fake Stat Composition preparation succeeds")
	var before := controller.current_state()
	controller.primary_action()
	await process_frame
	var refused := controller.current_state()
	_expect(refused.get("phase") == "retry", "run refusal presents Retry")
	_expect(refused.get("target_health") == before.get("target_health"), "run refusal applies no damage")
	_expect(refused.get("attack_count") == 0, "run refusal records no successful attack")
	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit Retry recreates the session")
	_expect(client.sessions_created == 2, "Retry creates a new isolated session")
	client.return_invalid_artifacts = true
	controller.primary_action()
	await process_frame
	_expect(controller.current_state().get("phase") == "retry", "projection failure presents Retry")
	_expect(controller.current_state().get("attack_count") == 0, "projection failure records no attack")
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()
