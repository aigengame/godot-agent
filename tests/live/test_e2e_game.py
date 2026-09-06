"""S1 (e2e): `gda game` live commands through the real `gda` CLI (`python -m gda`, #7).

This slice's real path is the attach-or-fail: a real ``gda game tree`` with no
running daemon must emit the typed ``daemon_not_running`` envelope and exit
``EXIT_LIVE`` — exercised through the out-of-process `gda` CLI and the real
``DaemonRunner`` + discovery (no fake at the seam). The connected path (a live
tree from a real engine session) lands with the daemon, a later slice. Per
RULES.md DoD the fake-runner command tests do not count toward this gate.
"""

import json
import time

import pytest

from gda.exit_codes import EXIT_LIVE
from tests.support import Gda

from tests.conftest import LIVE_PROJECT_GODOT


@pytest.mark.e2e
def test_game_tree_without_a_daemon_reports_daemon_not_running(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    # An empty runtime dir so discovery finds no daemon for this fresh project.
    proc = Gda(tmp_path, godot=None)(
        "game", "tree", "--json", extra_env={"XDG_RUNTIME_DIR": str(tmp_path / "run")}
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
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(TEXTURE_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "player.gd").write_text(TEXTURE_PLAYER_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

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
# `main.gd` owns its chain's callable declaration; `child.gd` declares none and
# inherits the base's, proving base-chain resolution. Both classes also carry a method they
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
    '\t"typed", "untyped", "typed_array", "with_node", "takes_bool", "takes_float",\n'
    '\t"takes_color", "takes_node_path", "takes_string_name",\n'
    '\t"takes_packed_byte", "takes_packed_int", "takes_packed_int64",\n'
    '\t"takes_packed_float32", "takes_packed_float64", "takes_packed_string",\n'
    '\t"takes_packed_color", "takes_packed_vector2", "takes_packed_vector3",\n'
    '\t"takes_packed_vector4", "takes_vector2", "takes_dict", "argument_type",\n'
    '\t"float_argument_preserved",\n'
    '\t"probe_direct",\n'
    "]\n\n"
    "var _phase := 3\n"
    "var _hit := false\n\n"
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
    "\t_hit = true\n"
    "\treturn value * 2\n\n"
    "func untyped(value) -> String:\n"
    "\t_hit = true\n"
    "\treturn str(value)\n\n"
    "func typed_array(items: Array[int]) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func with_node(n: Node2D) -> String:\n"
    "\t_hit = true\n"
    '\treturn "got " + str(n)\n\n'
    "func takes_bool(v: bool) -> bool:\n"
    "\t_hit = true\n"
    "\treturn v\n\n"
    "func takes_float(v: float) -> float:\n"
    "\t_hit = true\n"
    "\treturn v * 2.0\n\n"
    # The conversion matrix's parameter shapes, plus the ORACLE: `probe_direct`
    # performs the call itself and reports whether the body RAN, so the engine —
    # not a second copy of gda's table — decides what is convertible (#749
    # re-review).
    "func takes_color(c: Color) -> String:\n"
    "\t_hit = true\n"
    "\treturn str(c)\n\n"
    "func takes_node_path(p: NodePath) -> String:\n"
    "\t_hit = true\n"
    "\treturn String(p)\n\n"
    "func takes_string_name(s: StringName) -> String:\n"
    "\t_hit = true\n"
    "\treturn String(s)\n\n"
    "func takes_packed_byte(items: PackedByteArray) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_int(items: PackedInt32Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_int64(items: PackedInt64Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_float32(items: PackedFloat32Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_float64(items: PackedFloat64Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_string(items: PackedStringArray) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_color(items: PackedColorArray) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_vector2(items: PackedVector2Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_vector3(items: PackedVector3Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_packed_vector4(items: PackedVector4Array) -> int:\n"
    "\t_hit = true\n"
    "\treturn items.size()\n\n"
    "func takes_vector2(v: Vector2) -> String:\n"
    "\t_hit = true\n"
    "\treturn str(v)\n\n"
    "func takes_dict(d: Dictionary) -> int:\n"
    "\t_hit = true\n"
    "\treturn d.size()\n\n"
    "func argument_type(value) -> String:\n"
    "\treturn type_string(typeof(value))\n\n"
    "func float_argument_preserved(value: float, expected: String) -> bool:\n"
    "\tmatch expected:\n"
    '\t\t"1e17": return value == 1e17\n'
    '\t\t"2.5e17": return value == 2.5e17\n'
    '\t\t"1e300": return value == 1e300\n'
    "\treturn false\n\n"
    "func probe_direct(method: String, call_args: Array) -> bool:\n"
    "\t_hit = false\n"
    "\tcallv(method, call_args)\n"
    "\treturn _hit\n"
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
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

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
    # GDScript forbids redeclaring a base class's constant, so an opted-in chain
    # has at most one declaration owner. The failure is loud — the script does
    # not load — never a silently wrong allowlist.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
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

    run = Gda(tmp_path, json_output=True)

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
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

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
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

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

        invocations = [
            (
                "argv",
                ("game", "call", "/root/Main", "--method", "typed", "--args", "[NaN]"),
            ),
            (
                "params-json",
                (
                    "game",
                    "call",
                    "--params-json",
                    '{"node": "/root/Main", "method": "untyped", '
                    '"args": [{"deep": [Infinity]}]}',
                ),
            ),
        ]
        for label, invocation in invocations:
            started = time.monotonic()
            refused = run(*invocation)
            elapsed = time.monotonic() - started

            assert refused.returncode != 0, (label, refused.stdout)
            # Refused at the input boundary, not by the 30 s relay bound.
            assert elapsed < 10, (label, elapsed)
            assert "live_timeout" not in refused.stdout
            if label == "params-json":
                assert json.loads(refused.stdout)["error"]["code"] == "invalid_params"
            # The session is the SAME one — nothing was retired, no state was lost.
            assert json.loads(run("daemon", "status").stdout)["session_id"] == before

        after = run("game", "call", "/root/Main", "--method", "typed", "--args", "[2]")
        assert after.returncode == 0, after.stdout + after.stderr
        assert json.loads(run("daemon", "status").stdout)["session_id"] == before
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_game_call_argument_gate_agrees_with_the_engine(tmp_path, daemon_runtime_dir):
    # #749 re-review P1: the first hand-transcribed conversion table REJECTED
    # calls Godot accepts (a String into `Color`, a JSON array into
    # `PackedInt32Array`). The table is now transcribed from the engine's own
    # `Variant::can_convert_strict` closure over the SIX Variant types the live
    # JSON parser produces — and pinned by THIS matrix, whose
    # oracle is the engine itself: `probe_direct` performs the call inside the
    # game and reports whether the method body RAN. gda must call exactly when
    # the engine would, so the table can never drift silently again.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    # (method, JSON arguments) pairs spanning every retained live source-to-target
    # conversion edge, plus identity and refusal boundaries. Empty Arrays isolate
    # the container conversion itself from element-conversion policy.
    matrix = [
        ("typed", "[7]"),
        ("typed", '["bad"]'),
        ("typed", "[null]"),
        ("typed", "[true]"),
        ("typed", "[3.7]"),
        ("takes_float", "[3]"),
        ("takes_float", "[true]"),
        ("takes_bool", "[1]"),
        ("takes_color", '["red"]'),
        ("takes_color", "[16711680]"),
        ("takes_color", "[[1, 0, 0]]"),
        ("takes_node_path", '["root/player"]'),
        ("takes_packed_byte", "[[]]"),
        ("takes_packed_int", "[[1, 2, 3]]"),
        ("takes_packed_int64", "[[]]"),
        ("takes_packed_float32", "[[]]"),
        ("takes_packed_float64", "[[]]"),
        ("takes_packed_int", '["nope"]'),
        ("takes_packed_string", '[["a", "b"]]'),
        ("takes_packed_color", "[[]]"),
        ("takes_packed_vector2", "[[]]"),
        ("takes_packed_vector3", "[[]]"),
        ("takes_packed_vector4", "[[]]"),
        ("takes_vector2", "[[1, 2]]"),
        ("takes_string_name", '["x"]'),
        ("takes_string_name", "[7]"),
        ("takes_dict", '[{"a": 1}]'),
        ("takes_dict", "[[1]]"),
        ("with_node", "[null]"),
        ("with_node", '[{"a": 1}]'),
        ("untyped", '[{"a": 1}]'),
        ("typed_array", "[[1, 2]]"),
    ]

    try:
        assert run("daemon", "start").returncode == 0

        # Godot's live JSON parser materializes every number as float, even when
        # the source literal has no fractional part. This pins the source domain
        # before the conversion oracle: there is no reachable TYPE_INT row.
        for literal in ("16711680", "16711680.0"):
            observed = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "argument_type",
                "--args",
                f"[{literal}]",
            )
            assert observed.returncode == 0, observed.stdout + observed.stderr
            assert json.loads(observed.stdout)["value"] == "float"

        disagreements = []
        for method, args in matrix:
            gda = run("game", "call", "/root/Main", "--method", method, "--args", args)
            gda_calls = gda.returncode == 0
            if not gda_calls:
                assert (
                    json.loads(gda.stdout)["error"]["code"] == "live_invalid_call_args"
                ), gda.stdout

            probe = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "probe_direct",
                "--args",
                f'["{method}", {args}]',
            )
            assert probe.returncode == 0, probe.stdout + probe.stderr
            engine_calls = json.loads(probe.stdout)["value"]

            if gda_calls != engine_calls:
                disagreements.append((method, args, gda_calls, engine_calls))

        assert not disagreements, disagreements
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_game_call_refuses_integers_the_wire_cannot_carry(tmp_path, daemon_runtime_dir):
    # #749 re-review P1: the live wire's JSON parser reads every number as a
    # double, so an integer past the exact-integer range arrived CHANGED and the
    # call succeeded on a value the caller never sent (9007199254740993 doubled
    # to …984 instead of …986; 1.2e29 arrived as -2). The bound is now refused at
    # the input boundary; the largest exact value still goes through unchanged.
    from gda.commands.game import MAX_EXACT_JSON_INT

    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0
        assert run("daemon", "wait-ready").returncode == 0
        before = json.loads(run("daemon", "status").stdout)["session_id"]

        # Both boundary values round-trip exactly: doubled, they are still exact.
        for boundary in (MAX_EXACT_JSON_INT, -MAX_EXACT_JSON_INT):
            ok = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "typed",
                "--args",
                f"[{boundary}]",
            )
            assert ok.returncode == 0, ok.stdout + ok.stderr
            assert json.loads(ok.stdout)["value"] == boundary * 2

        # Past it — both signs, and a value far outside int64 — the call is
        # refused rather than silently altered.
        for value in (
            MAX_EXACT_JSON_INT + 2,
            -(MAX_EXACT_JSON_INT + 2),
            123456789012345678901234567890,
        ):
            refused = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "typed",
                "--args",
                f"[{value}]",
            )
            assert refused.returncode != 0, refused.stdout
            assert "live_timeout" not in refused.stdout

        # A pure --params-json request (no individual node/method arguments)
        # reaches the integer validator. Mixing the two forms only tests the
        # mutual-exclusion usage error and gave the old regression a false pass.
        nested = run(
            "game",
            "call",
            "--params-json",
            json.dumps(
                {
                    "node": "/root/Main",
                    "method": "untyped",
                    "args": [{"deep": [MAX_EXACT_JSON_INT + 2]}],
                }
            ),
        )
        assert nested.returncode != 0, nested.stdout
        nested_error = json.loads(nested.stdout)["error"]
        assert nested_error["code"] == "invalid_params"
        assert str(MAX_EXACT_JSON_INT) in nested_error["message"]
        assert json.loads(run("daemon", "status").stdout)["session_id"] == before
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
def test_game_call_preserves_large_finite_float_arguments(tmp_path, daemon_runtime_dir):
    """The live wire preserves high-range finite binary64 arguments."""
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(CALL_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "call_base.gd").write_text(CALL_BASE_GD, encoding="utf-8")
    (tmp_path / "call_child.gd").write_text(CALL_CHILD_GD, encoding="utf-8")
    (tmp_path / "call_main.gd").write_text(CALL_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0
        for literal in ("1e17", "2.5e17", "1e300"):
            result = run(
                "game",
                "call",
                "/root/Main",
                "--method",
                "float_argument_preserved",
                "--args",
                f'[{literal}, "{literal}"]',
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert json.loads(result.stdout)["value"] is True, literal
    finally:
        run("daemon", "stop")


# --- game tree: the bounded read (#849, GDA-DF-052) ---------------------------
# The dogfooding shape: an unfiltered tree of a production UI exceeded the
# client's budget and was truncated by it, which a caller cannot distinguish from
# a complete read. The fixture is the acceptance shape — a HUD with three direct
# children, one of which has two of its own.

TREE_MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="HUD" type="Control" parent="."]\n\n'
    '[node name="Panel" type="Control" parent="HUD"]\n\n'
    '[node name="Title" type="Label" parent="HUD/Panel"]\n\n'
    '[node name="Value" type="Label" parent="HUD/Panel"]\n\n'
    '[node name="Score" type="Label" parent="HUD"]\n\n'
    '[node name="Timer" type="Label" parent="HUD"]\n'
)


@pytest.mark.e2e
def test_game_tree_bounds_the_read_and_counts_what_it_left_out(
    tmp_path, daemon_runtime_dir
):
    # The three acceptance cases of #849 against a real engine session: a
    # subtree root, a depth bound with both counters, and the unbounded read
    # that must stay what it was apart from the two totals.
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(TREE_MAIN_TSCN, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    def names(node):
        return [child["name"] for child in node["children"]]

    try:
        assert run("daemon", "start").returncode == 0

        # AC1: the subtree root plus one level. The node whose children were not
        # walked reports how many; the result totals every unserialized node.
        bounded = run("game", "tree", "--root", "/root/Main/HUD", "--max-depth", "1")
        assert bounded.returncode == 0, bounded.stdout + bounded.stderr
        doc = json.loads(bounded.stdout)
        assert doc["root"]["path"] == "/root/Main/HUD"
        assert names(doc["root"]) == ["Panel", "Score", "Timer"]
        panel, score, timer = doc["root"]["children"]
        assert panel["children_omitted"] == 2
        assert panel["children"] == []
        assert "children_omitted" not in score
        assert "children_omitted" not in timer
        assert "children_omitted" not in doc["root"]
        assert doc["omitted_nodes"] == 2
        assert doc["truncated"] is True

        # AC2: depth 0 is the root alone — three direct children omitted, and
        # five nodes in total, since the count reaches every depth.
        root_only = run("game", "tree", "--root", "/root/Main/HUD", "--max-depth", "0")
        assert root_only.returncode == 0, root_only.stdout + root_only.stderr
        alone = json.loads(root_only.stdout)
        assert alone["root"]["path"] == "/root/Main/HUD"
        assert alone["root"]["children"] == []
        assert alone["root"]["children_omitted"] == 3
        assert alone["omitted_nodes"] == 5
        assert alone["truncated"] is True

        # AC3: with no options the whole current scene is serialized as before,
        # and the addition is exactly the two totals — no node grows a key.
        whole = run("game", "tree")
        assert whole.returncode == 0, whole.stdout + whole.stderr
        full = json.loads(whole.stdout)
        assert full["root"]["path"] == "/root/Main"
        assert full["omitted_nodes"] == 0
        assert full["truncated"] is False
        assert "children_omitted" not in json.dumps(full)
        hud = full["root"]["children"][0]
        assert names(hud) == ["Panel", "Score", "Timer"]
        assert names(hud["children"][0]) == ["Title", "Value"]

        # An unknown --root is the existing typed refusal, not an empty tree.
        missing = run("game", "tree", "--root", "/root/Main/Nope")
        assert missing.returncode == EXIT_LIVE, missing.stdout + missing.stderr
        assert json.loads(missing.stdout)["error"]["code"] == "live_node_not_found"
    finally:
        run("daemon", "stop")


# A chain deeper than GDScript's call stack (1024 frames by default), built by the
# main scene's script so the fixture stays small. The count-only pass over an
# omitted subtree recursed at first: at this depth it overflowed, returned a partial
# total, and the op published that as a successful read — the exact-count promise
# of #849 broken on a finite, valid tree.
DEEP_CHAIN_DEPTH = 2200
DEEP_CHAIN_MAIN_GD = (
    "extends Node2D\n"
    "func _ready() -> void:\n"
    "\tvar current: Node = self\n"
    f"\tfor index in range({DEEP_CHAIN_DEPTH}):\n"
    "\t\tvar child := Node.new()\n"
    "\t\tchild.name = str(index)\n"
    "\t\tcurrent.add_child(child)\n"
    "\t\tcurrent = child\n"
)
DEEP_CHAIN_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


@pytest.mark.e2e
def test_game_tree_counts_an_omitted_subtree_deeper_than_the_call_stack(
    tmp_path, daemon_runtime_dir
):
    (tmp_path / "project.godot").write_text(LIVE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(DEEP_CHAIN_MAIN_TSCN, encoding="utf-8")
    (tmp_path / "main.gd").write_text(DEEP_CHAIN_MAIN_GD, encoding="utf-8")

    run = Gda(tmp_path, json_output=True)

    try:
        assert run("daemon", "start").returncode == 0

        # Depth 0 on the current scene omits the whole chain: ONE direct child,
        # and every chain node in the total — exact, at a depth the recursive
        # count could not reach.
        root_only = run("game", "tree", "--max-depth", "0")
        assert root_only.returncode == 0, root_only.stdout + root_only.stderr
        alone = json.loads(root_only.stdout)
        assert alone["root"]["path"] == "/root/Main"
        assert alone["root"]["children"] == []
        assert alone["root"]["children_omitted"] == 1
        assert alone["omitted_nodes"] == DEEP_CHAIN_DEPTH
        assert alone["truncated"] is True

        # The same chain counted from one level higher: /root's children are
        # serialized, everything below them is omitted, and the total is still
        # exactly the chain — the engine session's own nodes have no children.
        from_root = run("game", "tree", "--root", "/root", "--max-depth", "1")
        assert from_root.returncode == 0, from_root.stdout + from_root.stderr
        top = json.loads(from_root.stdout)
        main = next(
            child for child in top["root"]["children"] if child["name"] == "Main"
        )
        assert main["children_omitted"] == 1
        assert top["omitted_nodes"] == DEEP_CHAIN_DEPTH

        # And the count left no engine error behind: the overflow surfaced here
        # as "Stack overflow" while the op still reported success.
        errors = run("diag", "errors")
        assert errors.returncode == 0, errors.stdout + errors.stderr
        assert json.loads(errors.stdout)["errors"] == []
    finally:
        run("daemon", "stop")
