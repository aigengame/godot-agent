extends Node

# The gda harness (ADR-0017, ADR-0018). Installed as a project [autoload] by
# `gda daemon`. It is INERT unless gda-daemon launched this run: at startup it
# looks for the daemon's launch marker in the user args (after `--`); absent it,
# it returns early — opening no connection, starting no server — and stays
# resident. It must NOT free()/queue_free() itself: Godot crashes if an autoload
# is freed at runtime, so a resident do-nothing node is the safe inert form. Thus
# it does nothing in a human editor run, a plain `godot --path` run, and a
# shipped/exported build.
#
# This is the inert gate only (#7 Step 3). The daemon<->harness connection
# (StreamPeerUDS, available since Godot 4.6) and the live-operation dispatch land
# in a later slice (#7 Step 6).

const LAUNCH_MARKER := "gda-daemon"


func _ready() -> void:
	var user_args := OS.get_cmdline_user_args()
	if not user_args.has(LAUNCH_MARKER):
		# Not launched by gda-daemon — stay resident and do nothing.
		return
	# Launched by gda-daemon: the live connection is wired in a later slice. Until
	# then this is intentionally a no-op so the installed autoload is safe to ship.
	pass
