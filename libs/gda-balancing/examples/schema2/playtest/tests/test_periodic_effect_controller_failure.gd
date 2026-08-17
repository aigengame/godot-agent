extends "res://tests/playtest_test_case.gd"

const PeriodicEffectController = preload(
	"res://content/periodic_effect/periodic_effect_controller.gd"
)

class RefusingClient extends Node:
	var sessions_created := 0

	func start(_executable: String) -> Dictionary:
		return {"ok": true}

	func create_session(_model: Dictionary, _experiment: Dictionary) -> Dictionary:
		sessions_created += 1
		return {
			"ok": true,
			"revision": "baseline",
			"session": "session-%d" % sessions_created,
		}

	func admit_revision(_session: String, _experiment: Dictionary) -> Dictionary:
		return {"ok": true, "revision": "later"}

	func run_revision(_session: String, _revision: String) -> Dictionary:
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
	var controller := PeriodicEffectController.new()
	get_root().add_child(controller)
	controller.configure(client, "unused")
	var started: Dictionary = await controller.start()
	_expect(started.get("ok", false), "fake Periodic Effect preparation succeeds")
	controller.primary_action()
	await process_frame
	var refused := controller.current_state()
	_expect(refused.get("phase") == "retry", "run refusal presents retry")
	_expect(not refused.has("health"), "run refusal publishes no gameplay state")
	var retried: Dictionary = await controller.retry()
	_expect(retried.get("ok", false), "explicit retry recreates the Effect session")
	_expect(client.sessions_created == 2, "retry creates a new isolated session")
	await controller.shutdown()
	controller.queue_free()
	client.queue_free()
	_finish()
