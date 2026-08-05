class_name GameLog
extends RefCounted

## Game-owned structured logging that degrades gracefully to print().
##
## The GdaHarness autoload carries gda_log(). This project COMMITS the harness, so
## it is present in every run — but its gda_log() only emits when gda-daemon
## launched the run; on a plain run, a headless run, or the editor it is DORMANT
## and gda_log() is a silent no-op. So we route to the harness only when it reports
## is_daemon_launched() (the public predicate, gda #362); otherwise we print(),
## which the daemon's log parser also captures as a passive `info` record and which
## a human sees on the console. (The harness is still looked up DYNAMICALLY at
## /root/GdaHarness — a bare `GdaHarness` global would not compile in the exported
## build, where `gda export run` strips the harness entirely.)


static func emit(level: String, message: String, fields: Dictionary = {}) -> void:
	var loop := Engine.get_main_loop()
	if loop is SceneTree:
		var harness := (loop as SceneTree).root.get_node_or_null("GdaHarness")
		# Route to the harness ONLY when the daemon launched this run; a committed-
		# but-dormant harness would otherwise swallow the log (its gda_log no-ops).
		if harness != null and harness.is_daemon_launched():
			harness.gda_log(level, message, fields)
			return
	print("[%s] %s %s" % [level, message, JSON.stringify(fields)])
