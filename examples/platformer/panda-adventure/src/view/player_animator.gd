class_name PlayerAnimator
extends RefCounted

## The Player's animation state machine (P2-S5, #443) — the view-layer driver that
## turns the PlayerController's view-integration hook SIGNALS into AnimatedSprite2D
## animation state, replacing the S1–S7 property-tween placeholders (landing squash,
## hit/level-up/consume flashes) with real sprite animation.
##
## It is the FIRST consumer of the phase-wide view-integration hook surface (the
## controller EMITS; presenters LISTEN — the controller holds no reference to any
## presenter, so animation/audio/VFX stay out of the controller and the pure Systems,
## gADR-0000). The state model:
##
##   - a LOCOMOTION base state (idle / run / jump / fall) driven by `locomotion_changed`
##     — looping, always the animation to return to;
##   - one-shot VERB overlays (fire / hurt / consume / level_up) from the discrete
##     verb signals — non-looping, playing over the locomotion then returning to it
##     on `animation_finished`;
##   - DEATH as a terminal latch (`death_started`) — once dead, nothing else plays.
##
## Every play() is guarded by `has_animation`, so a partial SpriteFrames (a set that
## ships fewer states) still drives whatever it has and ignores the rest.
##
## A stateful view driver (the EnemyWarpDriver / GameFlowDirector idiom): a RefCounted
## owned by the controller (untyped `controller`, so no cyclic class dependency),
## holding the live animation state across frames. It touches only the view layer (an
## AnimatedSprite2D) — never gameplay or the pure Systems (the Phase-2 closed
## logic-change list: view-integration hooks only). Siblings #444 (SFX) / #448 (VFX)
## connect to the SAME controller signals; this module is the animation consumer.

var _sprite: AnimatedSprite2D
var _locomotion: StringName = &"idle"
var _oneshot := false
var _dead := false


## Wire the animator to a controller's hooks. `controller` is untyped so the
## controller can preload this script without a cyclic class reference (the
## established controller-helper idiom); it must expose the view-integration hook
## signals. Starts on the locomotion base animation.
func _init(controller: Object, sprite: AnimatedSprite2D) -> void:
	_sprite = sprite
	controller.locomotion_changed.connect(_on_locomotion_changed)
	controller.fired.connect(_on_fired)
	controller.hurt.connect(_on_hurt)
	controller.consumed.connect(_on_consumed)
	controller.leveled_up.connect(_on_leveled_up)
	controller.death_started.connect(_on_death_started)
	if _sprite != null:
		_sprite.animation_finished.connect(_on_animation_finished)
	_play_locomotion()


func _on_locomotion_changed(state: StringName) -> void:
	_locomotion = state
	# A one-shot verb (or death) owns the sprite until it finishes; the new base
	# state is remembered and resumed then.
	if not _dead and not _oneshot:
		_play_locomotion()


func _on_fired(_weapon: StringName) -> void:
	_play_oneshot(&"fire")


func _on_hurt() -> void:
	_play_oneshot(&"hurt")


func _on_consumed(_item: StringName) -> void:
	_play_oneshot(&"consume")


func _on_leveled_up() -> void:
	_play_oneshot(&"level_up")


## Death is terminal: latch, drop any one-shot, and hold the death animation.
func _on_death_started() -> void:
	_dead = true
	_oneshot = false
	_play(&"death")


## A non-looping one-shot ended → resume the current locomotion base state.
func _on_animation_finished() -> void:
	if _dead:
		return
	_oneshot = false
	_play_locomotion()


func _play_locomotion() -> void:
	_play(_locomotion)


func _play_oneshot(anim: StringName) -> void:
	if _dead:
		return
	if _play(anim):
		_oneshot = true


## Play `anim` if the SpriteFrames carries it; report whether it did. The single
## has_animation guard keeps a partial sprite set safe.
func _play(anim: StringName) -> bool:
	if _sprite == null or _sprite.sprite_frames == null:
		return false
	if not _sprite.sprite_frames.has_animation(anim):
		return false
	_sprite.play(anim)
	return true
