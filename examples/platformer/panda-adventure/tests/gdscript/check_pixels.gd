extends SceneTree

## Generic pixel-counting probe for the Visual-smoke seam (gADR-0007) — the
## generalization of S6a's check_hud_pixels.gd. It knows NOTHING about the
## game: the Python side derives every region, color, and threshold from the
## authoritative JSON configs and passes a spec file; this script only decodes
## the capture PNGs with the engine's own Image API (the repo's
## no-image-decode-dependency convention) and counts matching pixels.
##
## Run via `gda script run` with the PIXEL_CHECKS_SPEC environment variable
## holding the absolute path of a spec JSON:
##
##   {"images": {"<name>": "/abs/path.png", ...},
##    "checks": [{"name": ..., "mode": ..., "image": ..., "rect": [x,y,w,h],
##                ...mode params...}, ...]}
##
## Modes (all count pixels inside `rect`, clamped to the image bounds):
## - "background_delta": pixels whose max channel delta from the pixel at
##   `reference` [x,y] (same image) exceeds `min_delta` — "this region
##   differs from the scene background".
## - "color_match": pixels within per-channel `tolerance` of `color` [r,g,b]
##   — "this opaque blockout color appears here".
## - "blend_match": pixels within `tolerance` of `color` [r,g,b,a]
##   alpha-blended over the SAME pixel of `base_image` — "this translucent
##   blockout renders here over whatever was underneath before".
## - "image_delta": pixels whose max channel delta from the same pixel of
##   `base_image` exceeds `min_delta` — "this region changed between
##   captures".
##
## Emits ONE parseable line and quits 0:
##
##   PIXEL_CHECKS: {"results": [{"name": N, "counted": C, "sampled": S}, ...]}
##
## `counted` is the matching-pixel count, `sampled` the in-bounds pixels
## examined; pass/fail thresholds live on the Python side, next to the config
## derivation. Any environment/spec/load failure quits 1 with a CHECK_FAIL
## line.


func _init() -> void:
	var spec_path := OS.get_environment("PIXEL_CHECKS_SPEC")
	if spec_path.is_empty():
		print("CHECK_FAIL: PIXEL_CHECKS_SPEC not set")
		quit(1)
		return
	var text := FileAccess.get_file_as_string(spec_path)
	if text.is_empty():
		print("CHECK_FAIL: could not read ", spec_path)
		quit(1)
		return
	var spec: Variant = JSON.parse_string(text)
	if spec == null or not (spec is Dictionary):
		print("CHECK_FAIL: spec is not a JSON object: ", spec_path)
		quit(1)
		return

	var images := {}
	for image_name: String in spec["images"]:
		var image := Image.load_from_file(spec["images"][image_name])
		if image == null:
			print("CHECK_FAIL: could not load image '", image_name, "': ", spec["images"][image_name])
			quit(1)
			return
		images[image_name] = image

	var results := []
	for check: Dictionary in spec["checks"]:
		var counted := _run_check(check, images)
		if counted.is_empty():
			print("CHECK_FAIL: bad check spec: ", JSON.stringify(check))
			quit(1)
			return
		results.append({
			"name": check["name"],
			"counted": counted[0],
			"sampled": counted[1],
		})

	print("PIXEL_CHECKS: ", JSON.stringify({"results": results}))
	quit(0)


const MODES := ["background_delta", "color_match", "blend_match", "image_delta"]


## Run one check; returns [counted, sampled], or [] on a bad spec (unknown
## mode / missing image). Pure counting — no thresholds here.
func _run_check(check: Dictionary, images: Dictionary) -> Array:
	var mode: String = check["mode"]
	if not MODES.has(mode) or not images.has(check["image"]):
		return []
	var image: Image = images[check["image"]]
	var base: Image = null
	if mode == "blend_match" or mode == "image_delta":
		if not images.has(check.get("base_image")):
			return []
		base = images[check["base_image"]]

	var rect: Array = check["rect"]
	var x0 := maxi(int(rect[0]), 0)
	var y0 := maxi(int(rect[1]), 0)
	var x1 := mini(int(rect[0]) + int(rect[2]), image.get_width())
	var y1 := mini(int(rect[1]) + int(rect[3]), image.get_height())

	var reference := Color.BLACK
	if mode == "background_delta":
		var ref: Array = check["reference"]
		reference = image.get_pixel(
			clampi(int(ref[0]), 0, image.get_width() - 1),
			clampi(int(ref[1]), 0, image.get_height() - 1)
		)

	var counted := 0
	var sampled := 0
	for y in range(y0, y1):
		for x in range(x0, x1):
			sampled += 1
			var c := image.get_pixel(x, y)
			match mode:
				"background_delta":
					if _max_channel_delta(c, reference) > float(check["min_delta"]):
						counted += 1
				"color_match":
					var want: Array = check["color"]
					var target := Color(want[0], want[1], want[2])
					if _max_channel_delta(c, target) <= float(check["tolerance"]):
						counted += 1
				"blend_match":
					# Expected: the spec'd RGBA alpha-blended (canvas "mix")
					# over what this exact pixel showed in the base capture.
					var over: Array = check["color"]
					var alpha := float(over[3])
					var under := base.get_pixel(x, y)
					var expected := Color(
						float(over[0]) * alpha + under.r * (1.0 - alpha),
						float(over[1]) * alpha + under.g * (1.0 - alpha),
						float(over[2]) * alpha + under.b * (1.0 - alpha)
					)
					if _max_channel_delta(c, expected) <= float(check["tolerance"]):
						counted += 1
				"image_delta":
					if _max_channel_delta(c, base.get_pixel(x, y)) > float(check["min_delta"]):
						counted += 1
	return [counted, sampled]


static func _max_channel_delta(a: Color, b: Color) -> float:
	return maxf(
		absf(a.r - b.r),
		maxf(absf(a.g - b.g), absf(a.b - b.b))
	)
