extends SceneTree

## Logic seam for the Player animation state machine (PlayerAnimator, P2-S5 #443):
## exercise the view driver headless against a SYNTHETIC controller (a bare object
## carrying the view-integration hook signals) and a real AnimatedSprite2D, and pin
## the state machine — the one place a controller emit becomes an animation state.
##
## Run via gda (ADR-0031):
##   gda script run res://tests/gdscript/test_player_animator_logic.gd
##
## Covers: the locomotion base plays at init; each verb hook plays its one-shot
## (fired->fire, hurt->hurt, consumed->consume, leveled_up->level_up); a one-shot
## resumes the CURRENT locomotion base on animation_finished; a locomotion change
## re-bases; and death latches (death_started plays "death" and every later verb /
## locomotion change / finish is ignored). preload() the driver (a headless runtime
## has no global_script_class_cache). Prints "ANIMATOR_SEAM: PASS" + quit(0) on
## success, else push_error + quit(1).

const PlayerAnimatorScript := preload("res://src/view/player_animator.gd")

# The animation states the fixture SpriteFrames ships; loop the locomotion base,
# one-shot the verbs (the PlayerAnimator contract).
const LOOPING := [&"idle", &"run"]
const ONESHOT := [&"fire", &"hurt", &"consume", &"level_up", &"death"]


## A synthetic controller: only the view-integration hook signals the animator
## connects to (untyped owner, so no dependency on the real PlayerController).
class FakeController:
	extends RefCounted
	signal locomotion_changed(state: StringName)
	signal fired(weapon: StringName)
	signal hurt
	signal consumed(item: StringName)
	signal leveled_up
	signal death_started


func _fail(msg: String) -> void:
	push_error("ANIMATOR_SEAM: " + msg)
	quit(1)


func _make_frames() -> SpriteFrames:
	var sf := SpriteFrames.new()
	var img := Image.create(1, 1, false, Image.FORMAT_RGBA8)
	var tex := ImageTexture.create_from_image(img)
	for anim in LOOPING + ONESHOT:
		if not sf.has_animation(anim):
			sf.add_animation(anim)
		sf.add_frame(anim, tex)
		sf.set_animation_loop(anim, anim in LOOPING)
	return sf


func _expect(sprite: AnimatedSprite2D, want: StringName, ctx: String) -> bool:
	if sprite.animation != want:
		_fail("%s: animation is %s, expected %s" % [ctx, sprite.animation, want])
		return false
	return true


func _init() -> void:
	var c := FakeController.new()
	var sprite := AnimatedSprite2D.new()
	sprite.sprite_frames = _make_frames()
	var _animator := PlayerAnimatorScript.new(c, sprite)

	# Init plays the locomotion base.
	if not _expect(sprite, &"idle", "init"):
		return

	# Each verb hook plays its one-shot; animation_finished resumes locomotion.
	var verbs := {
		"fired": &"fire", "hurt": &"hurt", "consumed": &"consume", "leveled_up": &"level_up"
	}
	for signal_name in verbs:
		match signal_name:
			"fired":
				c.fired.emit(&"laser_gun")
			"hurt":
				c.hurt.emit()
			"consumed":
				c.consumed.emit(&"bun")
			"leveled_up":
				c.leveled_up.emit()
		if not _expect(sprite, verbs[signal_name], "verb %s" % signal_name):
			return
		sprite.emit_signal(&"animation_finished")
		if not _expect(sprite, &"idle", "resume after %s" % signal_name):
			return

	# A locomotion change re-bases; a one-shot then resumes THAT base.
	c.locomotion_changed.emit(&"run")
	if not _expect(sprite, &"run", "locomotion->run"):
		return
	c.fired.emit(&"laser_gun")
	if not _expect(sprite, &"fire", "fire over run"):
		return
	sprite.emit_signal(&"animation_finished")
	if not _expect(sprite, &"run", "resume run after fire"):
		return

	# Death latches: plays "death" and ignores every later hook.
	c.death_started.emit()
	if not _expect(sprite, &"death", "death latch"):
		return
	c.fired.emit(&"laser_gun")
	if not _expect(sprite, &"death", "verb ignored after death"):
		return
	sprite.emit_signal(&"animation_finished")
	if not _expect(sprite, &"death", "finish ignored after death"):
		return
	c.locomotion_changed.emit(&"idle")
	if not _expect(sprite, &"death", "locomotion ignored after death"):
		return

	sprite.free()
	print("ANIMATOR_SEAM: PASS")
	quit(0)
