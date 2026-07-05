extends SceneTree

## Synthetic PNG fixtures for the generic pixel probe's headless coverage
## (gADR-0007, test_visual_smoke_probe.py). Authored with the engine's own
## Image API (the no-image-decode-dependency convention) so the probe's four
## matching modes can be pinned with EXACT expected counts, no display and no
## game scene involved. Geometry/colors here are mirrored by the Python test —
## change them together.
##
## Writes into the directory named by the PIXEL_FIXTURES_DIR environment
## variable:
##
## - base.png: a 100x100 flat 0.3-gray field with a pure-red 20x20 square at
##   (40, 40) — feeds background_delta and color_match.
## - next.png: base plus a white 10x10 square at (70, 70) (feeds image_delta)
##   and, at (10, 10), a 20x20 patch of the probe's blend color
##   (0.35, 0.65, 1.0) alpha-0.35 mixed over the gray — the exact canvas
##   "mix" result blend_match must recognize against base.png.
##
## Prints FIXTURES_DONE and quits 0; any environment/save failure quits 1
## with a FIXTURE_FAIL line.

const SIZE := 100
const BACKGROUND := Color(0.3, 0.3, 0.3)
const RED_RECT := Rect2i(40, 40, 20, 20)
const RED := Color(1.0, 0.0, 0.0)
const DELTA_RECT := Rect2i(70, 70, 10, 10)
const DELTA_COLOR := Color(1.0, 1.0, 1.0)
const BLEND_RECT := Rect2i(10, 10, 20, 20)
const BLEND_RGB := Color(0.35, 0.65, 1.0)
const BLEND_ALPHA := 0.35


func _init() -> void:
	var out_dir := OS.get_environment("PIXEL_FIXTURES_DIR")
	if out_dir.is_empty():
		print("FIXTURE_FAIL: PIXEL_FIXTURES_DIR not set")
		quit(1)
		return

	var base := Image.create(SIZE, SIZE, false, Image.FORMAT_RGB8)
	base.fill(BACKGROUND)
	base.fill_rect(RED_RECT, RED)

	var next := base.duplicate() as Image
	next.fill_rect(DELTA_RECT, DELTA_COLOR)
	var mixed := Color(
		BLEND_RGB.r * BLEND_ALPHA + BACKGROUND.r * (1.0 - BLEND_ALPHA),
		BLEND_RGB.g * BLEND_ALPHA + BACKGROUND.g * (1.0 - BLEND_ALPHA),
		BLEND_RGB.b * BLEND_ALPHA + BACKGROUND.b * (1.0 - BLEND_ALPHA)
	)
	next.fill_rect(BLEND_RECT, mixed)

	if base.save_png(out_dir + "/base.png") != OK:
		print("FIXTURE_FAIL: could not save base.png to ", out_dir)
		quit(1)
		return
	if next.save_png(out_dir + "/next.png") != OK:
		print("FIXTURE_FAIL: could not save next.png to ", out_dir)
		quit(1)
		return
	print("FIXTURES_DONE")
	quit(0)
