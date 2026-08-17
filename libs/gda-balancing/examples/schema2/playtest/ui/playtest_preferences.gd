extends RefCounted

const ENGLISH_TRANSLATION = preload("res://ui/localization/playtest.en.tres")
const CHINESE_TRANSLATION = preload("res://ui/localization/playtest.zh_CN.tres")
const DEFAULT_RESOLUTION_ID := "2k"
const DEFAULT_LOCALE_ID := "en"

const RESOLUTIONS: Array[Dictionary] = [
	{"id": "1080p", "label": "1080p", "size": Vector2i(1920, 1080)},
	{"id": "2k", "label": "2K", "size": Vector2i(2560, 1440)},
	{"id": "4k", "label": "4K", "size": Vector2i(3840, 2160)},
]

const LOCALES: Array[Dictionary] = [
	{"id": "en", "label": "English"},
	{"id": "zh_CN", "label": "中文"},
]


func resolution_options() -> Array[Dictionary]:
	return RESOLUTIONS.duplicate(true)


func locale_options() -> Array[Dictionary]:
	return LOCALES.duplicate(true)


func default_resolution_id() -> String:
	return DEFAULT_RESOLUTION_ID


func default_locale() -> String:
	return DEFAULT_LOCALE_ID


func install_translations() -> void:
	TranslationServer.add_translation(ENGLISH_TRANSLATION)
	TranslationServer.add_translation(CHINESE_TRANSLATION)


func resolution_size(resolution_id: String) -> Vector2i:
	for option in RESOLUTIONS:
		if option["id"] == resolution_id:
			return option["size"]
	return Vector2i.ZERO


func supports_locale(locale_id: String) -> bool:
	return LOCALES.any(func(option): return option["id"] == locale_id)


func apply_resolution(window: Window, resolution_id: String) -> bool:
	var size := resolution_size(resolution_id)
	if size == Vector2i.ZERO:
		return false
	window.size = size
	return true


func apply_locale(locale_id: String) -> bool:
	if not supports_locale(locale_id):
		return false
	TranslationServer.set_locale(locale_id)
	return true
