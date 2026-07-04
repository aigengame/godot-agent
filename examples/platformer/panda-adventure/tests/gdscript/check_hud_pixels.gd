extends SceneTree

## Visual-presence checker for the HUD (S6a): loads a viewport capture PNG and
## counts pixels in the HUD's screen region that differ from the scene
## background — proof the HUD actually RENDERS, not just that its Label.text
## holds the right data (the "data right, pixels absent" blind spot a playtest
## caught). Run via `gda script run` with the capture's absolute path in the
## HUD_CHECK_PNG environment variable; emits one parseable line:
##
##   HUD_PIXELS: {"differing": N, "probe": [x, y, w, h], "background": [r, g, b]}
##
## and quits 0. Any environment/load failure quits 1 with a CHECK_FAIL line.
## No image library on the Python side (the repo's no-image-decode-dependency
## convention) — the engine's own Image API does the decoding.

const HudConfigScript := preload("res://src/resources/hud_config.gd")
const HUD_CONFIG_PATH := "res://data/generated/hud_config.tres"

# The probe box (relative to the config margin) generously covering the five
# Label lines of the HUD column, and the per-channel difference that counts a
# pixel as "not background". Structural test constants, not game balance.
const PROBE_SIZE := Vector2i(280, 160)
const CHANNEL_DELTA := 0.15


func _init() -> void:
	var png_path := OS.get_environment("HUD_CHECK_PNG")
	if png_path.is_empty():
		print("CHECK_FAIL: HUD_CHECK_PNG not set")
		quit(1)
		return
	var image := Image.load_from_file(png_path)
	if image == null:
		print("CHECK_FAIL: could not load ", png_path)
		quit(1)
		return
	var config: HudConfigScript = load(HUD_CONFIG_PATH)
	if config == null:
		print("CHECK_FAIL: could not load ", HUD_CONFIG_PATH)
		quit(1)
		return
	# Background reference: the top-RIGHT corner inset — the HUD column sits at
	# the top-LEFT margin, so this samples plain scene background at boot.
	var background := image.get_pixel(image.get_width() - 8, 8)
	var origin := Vector2i(int(config.margin.x), int(config.margin.y))
	var differing := 0
	for dy in range(PROBE_SIZE.y):
		for dx in range(PROBE_SIZE.x):
			var x := origin.x + dx
			var y := origin.y + dy
			if x >= image.get_width() or y >= image.get_height():
				continue
			var c := image.get_pixel(x, y)
			var delta := maxf(
				absf(c.r - background.r),
				maxf(absf(c.g - background.g), absf(c.b - background.b))
			)
			if delta > CHANNEL_DELTA:
				differing += 1
	print(
		"HUD_PIXELS: ",
		JSON.stringify({
			"differing": differing,
			"probe": [origin.x, origin.y, PROBE_SIZE.x, PROBE_SIZE.y],
			"background": [background.r, background.g, background.b],
		})
	)
	quit(0)
