"""S1 (e2e): `gda game` live commands through the real `gda` CLI (`python -m gda`, #7).

This slice's real path is the attach-or-fail: a real ``gda game tree`` with no
running daemon must emit the typed ``daemon_not_running`` envelope and exit
``EXIT_LIVE`` — exercised through the out-of-process `gda` CLI and the real
``DaemonRunner`` + discovery (no fake at the seam). The connected path (a live
tree from a real engine session) lands with the daemon, a later slice. Per
RULES.md DoD the fake-runner command tests do not count toward this gate.
"""

import json
import os
import subprocess
import time

import pytest

from gda.exit_codes import EXIT_LIVE

from tests.support import GDA_CMD


def _gda_runner(project, timeout: int = 90):
    """One project/Godot-aware `gda` invoker for this module's live e2es (#749 review).

    The protocol arguments, environment and timeout were repeated per test and
    could drift; this is the single place they live.
    """
    from gda.binary import resolve_godot_binary

    godot = resolve_godot_binary()

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(godot),
                "--json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ},
            timeout=timeout,
        )

    return run


@pytest.mark.e2e
def test_game_tree_without_a_daemon_reports_daemon_not_running(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    # An empty runtime dir so discovery finds no daemon for this fresh project.
    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path / "run")}
    proc = subprocess.run(
        [*GDA_CMD, "game", "tree", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == EXIT_LIVE, proc.stdout + proc.stderr
    error = json.loads(proc.stdout)["error"]
    assert error["code"] == "daemon_not_running"
    assert error["category"] == "live"
    assert "gda daemon start" in error["message"]


# A Player that builds PATH-LESS ImageTextures at runtime (#666): two with
# different content and a third repeating the first's, so the digest opt-in can
# prove distinguishability AND stability. Deliberately path-less — the exact
# GDA-DF-011 shape the string fallback could not identify.
TEXTURE_PLAYER_GD = (
    "extends Node2D\n"
    "@export var tex_a: Texture2D\n"
    "@export var tex_b: Texture2D\n"
    "@export var tex_a2: Texture2D\n"
    "func _ready() -> void:\n"
    "\ttex_a = _make(Color.RED)\n"
    "\ttex_b = _make(Color.BLUE)\n"
    "\ttex_a2 = _make(Color.RED)\n"
    "func _make(c: Color) -> ImageTexture:\n"
    "\tvar img := Image.create(2, 3, false, Image.FORMAT_RGBA8)\n"
    "\timg.fill(c)\n"
    "\treturn ImageTexture.create_from_image(img)\n"
)
TEXTURE_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://player.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_game_get_projects_a_path_less_texture_with_optional_digest(
    tmp_path, daemon_runtime_dir
):
    # The #666 DoD (GDA-DF-011): a live `game get` on a path-less ImageTexture
    # returns the TextureProjection — type + dimensions, the old str() form
    # under object_string, NO resource_path key — with digest null by default;
    # with --texture-digest, two same-class textures with different content
    # get different digests and same-content textures the same one.
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(TEXTURE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TEXTURE_PLAYER_GD, encoding="utf-8")

    from gda.binary import resolve_godot_binary

    godot = resolve_godot_binary()
    env = {**os.environ}

    def run(*args):
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(tmp_path),
                "--godot",
                str(godot),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )

    def texture_value(prop, *extra):
        got = run("game", "get", "/root/Main/Player", "--property", prop, *extra)
        assert got.returncode == 0, got.stdout + got.stderr
        return next(
            p for p in json.loads(got.stdout)["properties"] if p["name"] == prop
        )["value"]

    try:
        assert run("daemon", "start").returncode == 0

        # Without the opt-in: the projection names the texture, digest stays
        # null, and the readback is never paid.
        plain = texture_value("tex_a")
        assert plain["type"] == "ImageTexture"
        assert plain["width"] == 2
        assert plain["height"] == 3
        assert "ImageTexture" in plain["object_string"]
        assert plain["digest"] is None
        assert "resource_path" not in plain

        # With the opt-in: different content, different digest; same content,
        # the same digest — the identity GDA-DF-011 could not establish.
        tex_a = texture_value("tex_a", "--texture-digest")
        tex_b = texture_value("tex_b", "--texture-digest")
        tex_a2 = texture_value("tex_a2", "--texture-digest")
        assert tex_a["digest"].startswith("sha256:")
        assert tex_b["digest"].startswith("sha256:")
        assert tex_a["digest"] != tex_b["digest"]
        assert tex_a2["digest"] == tex_a["digest"]
    finally:
        run("daemon", "stop")


# --- game call: the declared read-only method surface (#673, ADR-0041) --------
# The dogfooding shape (GDA-DF-033): a debug/state contract exposed as a METHOD.
# `main.gd` declares its own callable set; `child.gd` declares none and inherits
# the base's, proving the base-chain merge. Both classes also carry a method they
# never declared, so the default-deny path is real rather than hypothetical.

CALL_BASE_GD = (
    "extends Node2D\n\n"
    'const GDA_CALLABLE := ["base_declared"]\n\n'
    "func base_declared() -> String:\n"
    '\treturn "from base"\n'
)
CALL_CHILD_GD = (
    'extends "res://call_base.gd"\n\n'
    "func child_extra() -> String:\n"
    '\treturn "never reachable"\n'
)
CALL_MAIN_GD = (
    "extends Node2D\n\n"
    "const GDA_CALLABLE := [\n"
    '\t"qa_current_state_contract", "with_args", "returns_nothing",\n'
    '\t"typed", "untyped", "typed_array", "with_node", "takes_float",\n'
    "]\n\n"
    "var _phase := 3\n\n"
    "func qa_current_state_contract() -> Dictionary:\n"
    '\treturn {"phase": _phase, "ready": true, "labels": ["a", "b"], "at": Vector2(1, 2)}\n\n'
    'func with_args(scale: int, tag: String = "idle") -> Dictionary:\n'
    '\treturn {"scaled": _phase * scale, "tag": tag}\n\n'
    "func returns_nothing() -> void:\n"
    "\tpass\n\n"
    "func undeclared_secret() -> String:\n"
    '\treturn "never reachable"\n\n'
    # The typed-parameter shapes the #749 review's false-success finding needs.
    "func typed(value: int) -> int:\n"
    "\treturn value * 2\n\n"
    "func untyped(value) -> String:\n"
    "\treturn str(value)\n\n"
    "func typed_array(items: Array[int]) -> int:\n"
    "\treturn items.size()\n\n"
    "func with_node(n: Node2D) -> String:\n"
    '\treturn "got " + str(n)\n\n'
    "func takes_float(v: float) -> float:\n"
    "\treturn v * 2.0\n"
)
CALL_MAIN_TSCN = (
    "[gd_scene load_steps=3 format=3]\n\n"
    '[ext_resource type="Script" path="res://call_main.gd" id="1"]\n'
    '[ext_resource type="Script" path="res://call_child.gd" id="2"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n\n'
    '[node name="Inherited" type="Node2D" parent="."]\n'
    'script = ExtResource("2")\n'
)


@pytest.mark.e2e
def test_game_call_serves_declared_methods_and_refuses_the_rest(
    tmp_path, daemon_runtime_dir
):
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = _gda_runner(tmp_path)

    def call(node, method, *extra):
        return run("game", "call", node, "--method", method, *extra)

    try:
        assert run("daemon", "start").returncode == 0

        # AC2: a declared method is invoked and its return is PROJECTED — the
        # Dictionary arrives structured, with the nested Array and Vector2 in
        # the same shapes every gda read uses (ADR-0035).
        ok = call("/root/Main", "qa_current_state_contract")
        assert ok.returncode == 0, ok.stdout + ok.stderr
        doc = json.loads(ok.stdout)
        assert doc["path"] == "/root/Main"
        assert doc["method"] == "qa_current_state_contract"
        assert doc["value"] == {
            "phase": 3,
            "ready": True,
            "labels": ["a", "b"],
            "at": [1.0, 2.0],
        }

        # Arguments ride as values, and a declared default fills the rest.
        one = call("/root/Main", "with_args", "--args", "[2]")
        assert one.returncode == 0, one.stdout + one.stderr
        assert json.loads(one.stdout)["value"] == {"scaled": 6, "tag": "idle"}
        both = call("/root/Main", "with_args", "--args", '[2, "peak"]')
        assert json.loads(both.stdout)["value"] == {"scaled": 6, "tag": "peak"}

        # A method returning nothing projects as null, not as an error.
        void = call("/root/Main", "returns_nothing")
        assert void.returncode == 0, void.stdout + void.stderr
        assert json.loads(void.stdout)["value"] is None

        # The declaration is inherited: the subclass node declares nothing of
        # its own and the base's set still authorizes the call.
        inherited = call("/root/Main/Inherited", "base_declared")
        assert inherited.returncode == 0, inherited.stdout + inherited.stderr
        assert json.loads(inherited.stdout)["value"] == "from base"

        # AC3, refusal 1: a method the node HAS but never declared. The message
        # names the declared set, so discovery rides the failure.
        undeclared = call("/root/Main", "undeclared_secret")
        assert undeclared.returncode == EXIT_LIVE
        error = json.loads(undeclared.stdout)["error"]
        assert error["code"] == "live_method_not_allowlisted"
        assert "qa_current_state_contract" in error["message"]
        assert "GDA_CALLABLE" in error["message"]

        # ...including a subclass method the BASE's declaration does not name.
        assert (
            json.loads(call("/root/Main/Inherited", "child_extra").stdout)["error"][
                "code"
            ]
            == "live_method_not_allowlisted"
        )

        # AC3, refusal 2: a method the node does not have at all — a DISTINCT
        # code from the undeclared one.
        missing = call("/root/Main", "nope")
        assert missing.returncode == EXIT_LIVE
        assert json.loads(missing.stdout)["error"]["code"] == "live_unknown_method"

        # Refusal 3: an argument count outside the method's range, refused
        # BEFORE the call (callv would push an engine error and return null).
        too_few = call("/root/Main", "with_args", "--args", "[]")
        assert json.loads(too_few.stdout)["error"]["code"] == "live_invalid_call_args"
        too_many = call("/root/Main", "with_args", "--args", '[1, "a", 9]')
        assert json.loads(too_many.stdout)["error"]["code"] == "live_invalid_call_args"

        # None of the refusals ran project code that polluted the engine's error
        # stream: the whole matrix above leaves diag errors empty.
        errors = run("diag", "errors")
        assert errors.returncode == 0, errors.stdout + errors.stderr
        assert json.loads(errors.stdout)["errors"] == []
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_declaring_gda_callable_in_both_base_and_subclass_is_an_engine_parse_error(
    tmp_path, daemon_runtime_dir
):
    # ADR-0041's known limitation, pinned against the ENGINE rather than prose:
    # GDScript forbids redeclaring a base class's constant, so exactly one class
    # per inheritance chain declares. The failure is loud — the script does not
    # load — never a silently wrong allowlist.
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(
        'extends "res://call_base.gd"\n\n'
        'const GDA_CALLABLE := ["also_declared"]\n\n'
        "func also_declared() -> String:\n"
        '\treturn "shadowed"\n',
        encoding="utf-8",
    )
    (tmp_path / "main.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://call_main.gd" id="1"]\n\n'
        '[node name="Main" type="Node2D"]\n'
        'script = ExtResource("1")\n',
        encoding="utf-8",
    )

    run = _gda_runner(tmp_path)

    try:
        assert run("daemon", "start").returncode == 0
        # `diag errors` never launches a session itself (ADR-0022), so establish
        # one explicitly first — the documented bounded wait (#657).
        ready = run("daemon", "wait-ready")
        assert ready.returncode == 0, ready.stdout + ready.stderr
        # The engine refuses the script itself; the parse error names the member.
        errors = run("diag", "errors")
        assert errors.returncode == 0, errors.stdout + errors.stderr
        messages = " ".join(
            entry["message"] for entry in json.loads(errors.stdout)["errors"]
        )
        assert "GDA_CALLABLE" in messages
        assert "already exists in parent class" in messages
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_game_call_refuses_arguments_the_engine_would_not_convert(
    tmp_path, daemon_runtime_dir
):
    # #749 review P1: only arity was checked, so `callv` was reached with values
    # the engine could not convert — it pushed an error, returned null, and gda
    # reported a SUCCESSFUL read of `null`, indistinguishable from a void return
    # (and polluting the Session log). Every refusal below was a false success at
    # the reviewed head; every acceptance below is a conversion the engine really
    # performs, so the gate mirrors the engine rather than over-refusing.
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = _gda_runner(tmp_path)

    def call(method, args):
        return run("game", "call", "/root/Main", "--method", method, "--args", args)

    try:
        assert run("daemon", "start").returncode == 0

        for method, args, needle in (
            ("typed", '["bad"]', "String value cannot convert to int"),
            ("typed", "[null]", "Nil value cannot convert to int"),
            ("with_node", '[{"a": 1}]', "Dictionary value cannot convert to Object"),
            ("typed_array", "[[1, 2]]", "typed Array"),
        ):
            refused = call(method, args)
            assert refused.returncode == EXIT_LIVE, refused.stdout
            error = json.loads(refused.stdout)["error"]
            assert error["code"] == "live_invalid_call_args", error
            assert needle in error["message"], error["message"]

        # The conversions the engine DOES perform still go through, so the gate
        # mirrors `Variant::can_convert_strict` instead of refusing broadly.
        for method, args, expected in (
            ("typed", "[21]", 42),
            ("typed", "[true]", 2),
            ("typed", "[3.7]", 6),
            ("takes_float", "[3]", 6.0),
            ("with_node", "[null]", "got <null>"),
            ("untyped", '[{"a": 1}]', '{ "a": 1.0 }'),
        ):
            ok = call(method, args)
            assert ok.returncode == 0, ok.stdout + ok.stderr
            assert json.loads(ok.stdout)["value"] == expected, (method, args)

        # No refusal reached callv, so the engine's error stream stayed clean —
        # the log pollution the false successes caused is gone too.
        errors = run("diag", "errors")
        assert errors.returncode == 0, errors.stdout + errors.stderr
        assert json.loads(errors.stdout)["errors"] == []
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_game_call_non_finite_args_never_reach_the_session(
    tmp_path, daemon_runtime_dir
):
    # #749 review P1: `--args '[NaN]'` produced a frame the harness could not
    # parse, so the caller waited out the 30 s relay bound, got live_timeout, and
    # the daemon retired the channel — the NEXT call relaunched the session and
    # its runtime state was gone. The refusal now happens in the params model,
    # before the wire: fast, typed, and the session identity is untouched.
    from .conftest import project_godot

    (tmp_path / "project.godot").write_text(
        project_godot(extra='run/main_scene="res://main.tscn"'), encoding="utf-8"
    )
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = _gda_runner(tmp_path)

    try:
        assert run("daemon", "start").returncode == 0
        # Establish the session and record its identity (#660).
        assert (
            run(
                "game", "call", "/root/Main", "--method", "typed", "--args", "[1]"
            ).returncode
            == 0
        )
        before = json.loads(run("daemon", "status").stdout)["session_id"]

        started = time.monotonic()
        refused = run(
            "game", "call", "/root/Main", "--method", "typed", "--args", "[NaN]"
        )
        elapsed = time.monotonic() - started

        assert refused.returncode != 0
        # Refused at the input boundary, not by the 30 s relay bound.
        assert elapsed < 10, elapsed
        assert "live_timeout" not in refused.stdout

        # The session is the SAME one — nothing was retired, no state was lost.
        assert json.loads(run("daemon", "status").stdout)["session_id"] == before
        after = run("game", "call", "/root/Main", "--method", "typed", "--args", "[2]")
        assert after.returncode == 0, after.stdout + after.stderr
        assert json.loads(run("daemon", "status").stdout)["session_id"] == before
    finally:
        run("daemon", "stop")
