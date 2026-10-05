"""The main-scene precondition for a live session launch (#829).

Split out of the path authority (:mod:`gda.core.project.paths`) by ADR-0045 §2;
it reads ``project.godot`` through :mod:`gda.core.project.project_file`.
"""

from dataclasses import dataclass
from pathlib import Path

from gda.core.project.paths import PROJECT_MARKER
from gda.core.project.project_file import read_config

MAIN_SCENE_UNDEFINED = "live_main_scene_undefined"
MAIN_SCENE_UNRESOLVED = "live_main_scene_unresolved"

_APPLICATION_SECTION = "application"
_MAIN_SCENE_KEY = "run/main_scene"
_HIDDEN_DATA_DIR_KEY = "config/use_hidden_project_data_directory"
_SETTINGS_OVERRIDE_KEY = "config/project_settings_override"
_UID_CACHE = "uid_cache.bin"
_OVERRIDE_CFG = "override.cfg"


@dataclass(frozen=True)
class MainSceneUnrunnable:
    """The refusal for a session launch whose main scene cannot be run (#829).

    ``code`` is the :term:`Gda error code` — :data:`MAIN_SCENE_UNDEFINED` when the
    project declares no main scene, :data:`MAIN_SCENE_UNRESOLVED` when it declares a
    ``uid://`` one the engine could not resolve because the project was never
    imported — and ``reason`` the caller-first sentence both refusal sites relay
    verbatim (the optional ``daemon start`` fail-fast and the daemon's
    authoritative launch boundary), so the two never disagree about what was found
    or what to do.
    """

    code: str
    reason: str


@dataclass(frozen=True)
class _MainSceneSetting:
    """What ``project.godot`` says about the main scene, as far as gda reads it.

    ``value`` is the base ``application/run/main_scene``; ``overridden`` records
    that a feature-tagged override of it (``run/main_scene.<feature>``) or a
    default/custom settings overlay exists. Either can change the effective value
    in ways only the engine decides (its features and the overlay's contents), so
    the verdict defers to the engine. ``hidden_data_dir`` is
    ``application/config/use_hidden_project_data_directory`` (``.godot/`` when
    true, ``godot/`` when false), which names the one UID cache the engine reads.
    ``None`` means the directory depends on an override or an unrecognized value;
    only the UID-cache verdict needs to defer in that case.
    """

    value: str
    overridden: bool
    hidden_data_dir: bool | None


def _unquoted_literal(token: str) -> str:
    """A Godot VALUE literal with its surrounding quotes off, or as it stands.

    The one thing this lookup needs that :mod:`gda.core.project.project_file` does not provide:
    that module reads the FORMAT and leaves every value as the text the file
    spells, because decoding a Variant is the engine's job. A main-scene path and
    an overlay path are the two literals this verdict compares, and both are
    plain quoted strings — so the quotes come off here, at the one caller, and
    nothing else in gda grows a second value decoder. It is NOT a key decoder:
    a key's spelling is the reader's (``ConfigEntry.name``).
    """
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].replace('\\"', '"')
    return token


def _read_main_scene(project: Path) -> _MainSceneSetting | None:
    """Read the main-scene setting, or ``None`` when it cannot be determined.

    Reads the ``[application]`` section through the shared ``ConfigFile`` reader
    (:mod:`gda.core.project.project_file`, #843) and takes from it only the settings this
    verdict needs and their override declarations. Each entry is addressed by the
    NAME that reader decoded for it, which is the one decoding of a key spelling in
    gda: ``"run/\\u006dain_scene"`` names the main scene, as it does to the
    engine's parser. An entry that reader could not name is left to the engine:
    this reader gives up on the whole file rather than mistake a declaration it
    cannot decode for an absent setting, so the verdict defers instead of refusing.
    A file gda cannot read or decode is ``None`` too — that is not a verdict about
    the scene, and the next step that touches the file (the harness install)
    reports the failure as its own.
    """
    config = read_config(project / PROJECT_MARKER)
    if config is None:
        return None
    value = ""
    overridden = (project / _OVERRIDE_CFG).exists()
    hidden: bool | None = True
    for entry in config.entries:
        if entry.section != _APPLICATION_SECTION:
            continue
        if entry.name is None:
            return None
        key = entry.name.removeprefix(f"{_APPLICATION_SECTION}/")
        token = entry.value
        if key == _MAIN_SCENE_KEY:
            value = _unquoted_literal(token)
        elif key.startswith(_MAIN_SCENE_KEY + "."):
            overridden = True
        elif key == _HIDDEN_DATA_DIR_KEY:
            if hidden is not None:
                hidden = {"true": True, "false": False}.get(token.strip())
        elif key.startswith(_HIDDEN_DATA_DIR_KEY + "."):
            hidden = None
        elif key == _SETTINGS_OVERRIDE_KEY and _unquoted_literal(token):
            overridden = True
        elif key.startswith(_SETTINGS_OVERRIDE_KEY + "."):
            overridden = True
    return _MainSceneSetting(value=value, overridden=overridden, hidden_data_dir=hidden)


def _uid_cache_present(project: Path, hidden_data_dir: bool) -> bool:
    """Whether the ONE UID cache the engine reads exists (``.godot/`` or ``godot/``)."""
    data_dir = ".godot" if hidden_data_dir else "godot"
    return (project / data_dir / _UID_CACHE).is_file()


def main_scene_unrunnable(
    project: Path, scene: str | None
) -> MainSceneUnrunnable | None:
    """The pre-launch verdict for a live session: ``None`` unless it certainly cannot run.

    Godot started on the GAME path with no ``--scene``/``--script`` prints
    ``Can't run project: no main scene defined`` when ``application/run/main_scene``
    is empty, and ``Main scene's path could not be resolved from UID`` when it is a
    ``uid://`` the engine has no UID cache for (``main/main.cpp``: the cache file
    under the project data directory does not exist — a fresh clone, since Godot
    4.4 writes the setting as a UID and ``.godot/`` is normally ignored). Either
    way it then calls ``OS::alert()`` unconditionally — on macOS a native modal that
    ignores ``--headless`` and blocks the process until it is dismissed or killed
    (#829). Every gda headless operation names a script, an import or an export, so
    only a session launch can reach that path: this is the one check the two launch
    sites share (the ``daemon start`` fail-fast and the daemon's authoritative
    launch boundary), decided from the project files alone.

    The verdict refuses only what it is CERTAIN of and must never refuse a project
    the engine would run: a ``--scene`` selector makes the main scene irrelevant; a
    feature-tagged override of the setting or a default/custom settings overlay
    can change the effective value in ways only the engine decides (its features
    and the overlay's contents), so their presence defers to the engine. The launch
    behaves as before this check, bounded by the readiness deadline (a native alert
    can still appear). An application key gda cannot decode defers as well. A
    feature-tagged data-directory setting defers only the UID-cache verdict.
    """
    if scene:
        return None
    setting = _read_main_scene(project)
    if setting is None or setting.overridden:
        return None
    if setting.value == "":
        return MainSceneUnrunnable(
            MAIN_SCENE_UNDEFINED,
            "the project defines no main scene to run: `application/run/main_scene` "
            f"is empty in {project / PROJECT_MARKER} and no --scene selector was "
            "given. Set it (`gda project set application/run/main_scene --value "
            "res://<scene>.tscn`) or start with `gda daemon start --scene "
            "<res://path|uid://...>` (after `gda daemon stop` if a daemon is "
            "running); Godot would otherwise refuse to run the project and, on "
            "macOS, block on a native alert even under --headless",
        )
    if (
        setting.value.startswith("uid://")
        and setting.hidden_data_dir is not None
        and not _uid_cache_present(project, setting.hidden_data_dir)
    ):
        return MainSceneUnrunnable(
            MAIN_SCENE_UNRESOLVED,
            f"the project's main scene is {setting.value!r} but the engine has no "
            "UID cache to resolve it through (no uid_cache.bin under the project "
            "data directory — the project has not been imported on this checkout). "
            "Run the import pass once (`gda resource import <any existing res:// "
            "asset>`, or open the project in the editor), or start with `gda daemon "
            "start --scene <res://path>` (after `gda daemon stop` if a daemon is "
            "running); Godot would otherwise refuse to run the project and, on "
            "macOS, block on a native alert even under --headless",
        )
    return None
