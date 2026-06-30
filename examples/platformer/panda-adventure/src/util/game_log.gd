class_name GameLog
extends RefCounted

## Game-owned structured logging that degrades gracefully without the gda daemon.
##
## The GdaHarness autoload (which carries gda_log) is installed into the project
## only by `gda daemon start`; it is absent in a plain run, a headless run, and a
## shipped build. Referencing the static `GdaHarness` global in game code would
## therefore fail to COMPILE when the autoload is absent — so we look the harness
## up DYNAMICALLY at /root/GdaHarness instead. Under the daemon the rich
## <<<GDA:LOG>>> line materializes; otherwise the print() fallback is still
## captured as a passive `info` record by the daemon's log parser.


static func emit(level: String, message: String, fields: Dictionary = {}) -> void:
	var loop := Engine.get_main_loop()
	if loop is SceneTree:
		var harness := (loop as SceneTree).root.get_node_or_null("GdaHarness")
		if harness != null:
			harness.gda_log(level, message, fields)
			return
	print("[%s] %s %s" % [level, message, JSON.stringify(fields)])
