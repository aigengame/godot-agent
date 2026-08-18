"""S1 (e2e): the installed gda harness loads inert in a real engine (#7, #225, #301, ADR-0018, ADR-0028).

Per RULES.md DoD the fast install tests do not count toward this gate: these boot
a REAL Godot on a project with the harness installed and assert the autoload is
valid GDScript and stays inert — no daemon launch marker, so it opens no
connection and the engine boots clean. The exact failures ADR-0018 guards (a
dangling autoload spamming startup errors, or the harness opening a connection in a
plain run / shipped build) must NOT occur.

Two boots: a plain ``--path`` run (#7, strengthened by #225), and an EXPORTED PCK
run (#225) — the harness packed into a templateless ``.pck`` and run with no
``gda-daemon`` marker, the shipped-build path ADR-0018 point 2 calls out.

The PCK boot packs via a RAW ``godot --export-pack`` (NOT ``gda export run``): since
ADR-0018's export-strip, ``gda export run`` removes the harness from its artifacts
(verified in ``tests/test_e2e_export_run.py``), so to exercise the DEFENSE-IN-DEPTH
property here — that a harness which *did* reach a shipped build stays inert — the
pack must come from a route that does not strip it, and the harness's presence in
the pack is asserted so "inert" is never trivially true.

NOTE on what the PCK boot proves: it runs the pack with the EDITOR (tools) binary via
``--main-pack``, where ``OS.has_feature("template")`` is FALSE — so it exercises the
**no-marker** inert path (ADR-0018 point 2), not ADR-0028's ``template`` gate. That
gate's BEHAVIOURAL proof — exporting a real TEMPLATE binary (where the feature is
true) and asserting the harness never connects despite a marker + live socket — is
``test_template_feature_gates_the_harness_only_in_exported_builds`` below (#301; it
needs installed export templates, so it skips loudly where they are absent). Its
CI-runnable static counterpart — that the gate is the first statement of ``_ready()``
— lives in ``tests/test_harness_install.py``.
"""

import json
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import NamedTuple

import pytest

from gda.binary import resolve_godot_binary
from gda.daemon.protocol import read_frame
from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_FILE,
    HARNESS_RES_PATH,
    install_harness,
)

from tests.support import GDA_CMD, templates_installed

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A trivial main scene so a normal (non-`--script`) boot runs the autoload's
# `_ready`; file logging stays disabled via project_godot (issue #180).
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

# The harness only connects when a `gda-daemon` marker is present in the user args
# (StreamPeerUDS.connect_to_host). An inert boot opens nothing, so none of these
# connection/socket diagnostics may appear in the engine output.
_CONNECTION_NOISE = ("StreamPeerUDS", "connect_to_host", "harness_socket", ".sock")


def _assert_inert_boot(out: str, returncode: int) -> None:
    assert "SCRIPT ERROR" not in out, out
    assert "Parse Error" not in out, out
    # Strengthened (#225): the autoload must not have opened a connection — no
    # daemon marker, so it returns early and touches no socket.
    for needle in _CONNECTION_NOISE:
        assert needle not in out, (
            f"unexpected harness connection activity: {needle}\n{out}"
        )
    assert returncode == 0, out


@pytest.mark.e2e
def test_installed_harness_boots_inert_in_a_real_engine(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    result = install_harness(tmp_path)

    assert result.changed is True
    assert (tmp_path / "addons" / "gda_harness" / "gda_harness.gd").exists()
    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"' in text

    # Boot the real engine. The installed autoload must load (valid GDScript) and
    # stay inert — no `gda-daemon` marker in the args, so it returns early and
    # opens nothing, and the engine boots without a script/parse error.
    proc = subprocess.run(
        [str(GODOT), "--headless", "--path", str(tmp_path), "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    _assert_inert_boot(proc.stdout + proc.stderr, proc.returncode)


@pytest.mark.e2e
def test_exported_pck_with_harness_runs_inert(tmp_path):
    # #225 / ADR-0018 point 2 (defense in depth): a harness that DID reach a SHIPPED
    # build must stay inert. `gda export run` now strips the harness from its
    # artifacts (see tests/test_e2e_export_run.py), so to exercise the residual case
    # we pack via a RAW `godot --export-pack` (which does NOT strip), assert the
    # harness is genuinely IN the pack, then RUN that .pck with no `gda-daemon`
    # marker — the packed GdaHarness autoload must boot clean and open nothing (the
    # exact failure ADR-0018 guards: a dangling/active autoload in an exported game).
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    install_harness(tmp_path)

    # A minimal Linux preset so `--export-pack` has a preset to pack from (pack
    # produces project data only; platform is immaterial, no templates used).
    (tmp_path / "export_presets.cfg").write_text(
        "[preset.0]\n\n"
        'name="Pack"\n'
        'platform="Linux/X11"\n'
        "runnable=true\n"
        'export_filter="all_resources"\n'
        'include_filter=""\n'
        'exclude_filter=""\n'
        'export_path="build/game.x86_64"\n\n'
        "[preset.0.options]\n\n"
        "binary_format/embed_pck=false\n",
        encoding="utf-8",
    )
    pck = tmp_path / "dist" / "game.pck"
    pck.parent.mkdir(parents=True, exist_ok=True)

    # RAW engine export (bypasses gda's strip on purpose) so the harness is packed.
    packed = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--path",
            str(tmp_path),
            "--export-pack",
            "Pack",
            str(pck),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert pck.exists(), (
        f"expected packed .pck at {pck}\n{packed.stdout}{packed.stderr}"
    )
    # Non-trivial precondition: the harness path really is inside the pack (the pck
    # file table stores res:// paths as plaintext), so "inert" below is meaningful.
    assert b"gda_harness.gd" in pck.read_bytes(), "the harness was not packed"

    # Run the engine against the packed .pck (the shipped-build path): the packed
    # GdaHarness autoload must boot inert — no marker, so it opens nothing.
    proc = subprocess.run(
        [str(GODOT), "--headless", "--main-pack", str(pck), "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    _assert_inert_boot(proc.stdout + proc.stderr, proc.returncode)


# --- ADR-0028 template-gate behavioural proof (#301) ------------------------------
#
# The two boots above run on the EDITOR binary, where `OS.has_feature("template")` is
# false. The proof below needs a real exported TEMPLATE binary (feature true), so it
# exports one for the HOST platform and runs it. The helpers are host-parameterized;
# only the Linux/X11 (CI) and macOS (dev) export paths are wired — other hosts skip.

# The proof's project. A macOS arm64/universal export refuses to build unless ETC2
# ASTC VRAM import is enabled (Godot validates it regardless of whether the project
# has textures); it is harmless for the Linux/X11 export, so the project enables it
# on both hosts.
_GATE_PROJECT_GODOT = project_godot(
    extra=(
        'run/main_scene="res://main.tscn"\n\n'
        "[rendering]\n\n"
        "textures/vram_compression/import_etc2_astc=true"
    )
)

_LINUX_PRESETS = (
    "[preset.0]\n\n"
    'name="Linux/X11"\n'
    'platform="Linux/X11"\n'
    "runnable=true\n"
    'export_filter="all_resources"\n'
    'include_filter=""\n'
    'exclude_filter=""\n'
    'export_path="export/game.x86_64"\n\n'
    "[preset.0.options]\n\n"
    "binary_format/embed_pck=false\n"  # a sidecar game.pck we can grep for the harness
)

# The macOS export template (macos.zip) ships a single UNIVERSAL binary
# (godot_macos_debug.universal), so the preset must request "universal" — a per-arch
# value errors with "template binary not found". The .app runs natively on any host.
# The options section must also be non-empty or Godot errors reading its keys.
_MACOS_PRESETS = (
    "[preset.0]\n\n"
    'name="macOS"\n'
    'platform="macOS"\n'
    "runnable=true\n"
    'export_filter="all_resources"\n'
    'include_filter=""\n'
    'exclude_filter=""\n'
    'export_path="export/game.app"\n\n'
    "[preset.0.options]\n\n"
    'binary_format/architecture="universal"\n'
    # macOS export requires a bundle identifier; ad-hoc codesigning (the default,
    # Gatekeeper-blocked) is fine for a locally-built binary we run ourselves.
    'application/bundle_identifier="org.godotagent.gatetest"\n'
)


class _ExportTarget(NamedTuple):
    preset: str  # export_presets.cfg preset name (== platform here)
    export_path: str  # the preset's export_path, also the raw --export-debug out
    presets_cfg: str  # the full export_presets.cfg for this host


def _host_export_target() -> "_ExportTarget | None":
    """The host's template-export preset, or None on an unsupported host (skip).

    Only the platforms this test can run on are wired: Linux/X11 (CI) and macOS (the
    dev machine). The exported artifact must run on THIS host, so the preset is the
    host platform.
    """
    if sys.platform.startswith("linux"):
        return _ExportTarget("Linux/X11", "export/game.x86_64", _LINUX_PRESETS)
    if sys.platform == "darwin":
        return _ExportTarget("macOS", "export/game.app", _MACOS_PRESETS)
    return None


def _locate_exe(project, target: _ExportTarget):
    """The runnable executable the host export produced, or None if it failed.

    ``--export-debug`` exits 0 even when the export fails (leaving only a partial
    artifact), so a missing executable is how this test detects a failed export.
    """
    artifact = project / target.export_path
    if sys.platform == "darwin":
        # A macOS export is a .app bundle; the executable is the lone real file under
        # Contents/MacOS/ (named from the preset, so glob rather than guess it). Skip
        # dotfiles (e.g. a stray .DS_Store) that would sort ahead of the binary.
        macos_dir = artifact / "Contents" / "MacOS"
        exes = (
            sorted(
                p
                for p in macos_dir.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            if macos_dir.is_dir()
            else []
        )
        return exes[0] if exes else None
    return artifact if artifact.exists() else None  # Linux: export_path IS the exe


def _exported_tree_has_harness(export_dir) -> bool:
    """Whether the harness script is packed into the exported artifact's pck.

    The ``res://`` path is stored as plaintext in the project pack — a sidecar
    ``game.pck`` on Linux, ``Contents/Resources/<name>.pck`` inside the .app on macOS
    — so scanning the pck(s) finds it WITHOUT reading the multi-hundred-MB template
    binary, and keeps the negative "no connection" result non-vacuous (the harness
    really shipped in the template build).
    """
    return any(
        HARNESS_FILE.encode() in p.read_bytes() for p in export_dir.rglob("*.pck")
    )


class _SocketProbe:
    """A listening AF_UNIX socket that records the harness's first connection.

    Plays the daemon's role for the harness's connect attempt: accept once, read the
    first length-prefixed frame (the harness sends the auth token first — see
    ``gda_harness.gd`` ``_send_frame``), and record both that a connection arrived and
    the token bytes. A daemon thread polls ``accept()`` on a short timeout so
    ``stop()`` unwinds deterministically (closing the listening fd from another thread
    does not reliably wake a blocked ``accept()``).
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self.connected = threading.Event()
        self.token: bytes | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        self._sock.settimeout(0.25)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2.0)
                    self.token = read_frame(conn)
                except OSError:
                    pass
                # Signal AFTER the token is read so a waiter gated on `connected` sees
                # a populated `token` — no read-before-write race in the positive
                # control (the harness sends the token as its first frame).
                self.connected.set()
            return

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


@contextmanager
def _socket_probe(path):
    """A live listening UDS at ``path``; bind under daemon_runtime_dir (sun_path limit)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(1)  # the backlog holds a connect that beats accept() — no startup race
    probe = _SocketProbe(sock)
    try:
        yield probe
    finally:
        probe.stop()
        sock.close()
        path.unlink(missing_ok=True)


@pytest.mark.e2e
def test_template_feature_gates_the_harness_only_in_exported_builds(
    tmp_path, daemon_runtime_dir
):
    # ADR-0028 BEHAVIOURAL proof (#301), replacing the test_e2e_export_run tripwire
    # and completing this file's story. It isolates `OS.has_feature("template")` as
    # the ONLY variable: the SAME project + `gda-daemon` marker + live socket CONNECTS
    # under the EDITOR binary (template=false) and stays SILENT under an EXPORTED
    # TEMPLATE binary (template=true), where the gate short-circuits `_ready()` before
    # any marker/socket handling.
    #
    # Skips LOUDLY when the host is unsupported or export templates for the running
    # engine version are absent (the static first-statement proof in
    # tests/test_harness_install.py still guards the gate everywhere). Residual,
    # documented limitation: the positive control cannot rule out a template build
    # dropping `--` user args — academic, since feeding user args to exported games is
    # the documented purpose of OS.get_cmdline_user_args() and gda only ever launches
    # the editor binary in production (the gate is pure defence-in-depth).
    target = _host_export_target()
    if target is None:
        pytest.skip(
            f"no template-export path is wired for {sys.platform!r}; the behavioural "
            "template-gate proof (#301) exports a host template binary. Covered "
            "statically by test_ready_gates_on_template_feature_as_its_first_statement."
        )

    (tmp_path / "project.godot").write_text(_GATE_PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    (tmp_path / "export_presets.cfg").write_text(target.presets_cfg, encoding="utf-8")
    install_harness(tmp_path)

    def gda(*args):  # bound `gda export get` for the templates-presence gate
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(tmp_path)],
            capture_output=True,
            text=True,
        )

    if not templates_installed(gda, preset=target.preset):
        pytest.skip(
            f"export templates for the running engine + {target.preset!r} are not "
            "installed; the template-gate BEHAVIOURAL proof cannot export a template "
            "binary here (covered statically by "
            "test_ready_gates_on_template_feature_as_its_first_statement). Install "
            "matching templates (the install-godot CI action does) to run it. (#301)"
        )

    # Positive control: the EDITOR binary (template=false) DOES connect — proving the
    # socket/marker/token rig genuinely drives a harness connection, so the template
    # binary's later silence is attributable to the gate, not a dead rig.
    editor_sock = daemon_runtime_dir / "editor.sock"
    editor_token = "tok-editor"
    with _socket_probe(editor_sock) as probe:
        subprocess.run(
            [
                str(GODOT),
                "--headless",
                "--path",
                str(tmp_path),
                "--quit",
                "--",
                "gda-daemon",
                str(editor_sock),
                editor_token,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert probe.connected.wait(5), (
            "editor binary never connected — the rig is broken"
        )
        assert probe.token == editor_token.encode(), probe.token

    # Export a real DEBUG TEMPLATE binary that CONTAINS the harness. RAW `--export-debug`
    # (NOT `gda export run`, which strips the harness per ADR-0018) so the harness
    # genuinely SHIPS in the template build — the gate, not the strip, must silence it.
    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    artifact = tmp_path / target.export_path
    exported = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--path",
            str(tmp_path),
            "--export-debug",
            target.preset,
            str(artifact),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    exe = _locate_exe(tmp_path, target)
    assert exe is not None, (
        "--export-debug produced no runnable binary — the export failed (it exits 0 "
        f"even on failure)\n{exported.stdout}{exported.stderr}"
    )
    assert _exported_tree_has_harness(export_dir), (
        "the harness was not packed into the template build — the proof would be vacuous"
    )
    exe.chmod(0o755)

    # Negative: the TEMPLATE binary (template=true) stays SILENT despite the marker.
    tmpl_sock = daemon_runtime_dir / "tmpl.sock"
    tmpl_token = "tok-template"
    with _socket_probe(tmpl_sock) as probe:
        ran = subprocess.run(
            [
                str(exe),
                "--headless",
                "--quit",
                "--",
                "gda-daemon",
                str(tmpl_sock),
                tmpl_token,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out_text = ran.stdout + ran.stderr
        # The binary booted and ran `_ready` (so the gate executed) and exited clean —
        # otherwise "no connection" could be a crash before `_ready`, not the gate.
        assert "SCRIPT ERROR" not in out_text, out_text
        assert "Parse Error" not in out_text, out_text
        assert ran.returncode == 0, out_text
        # The harness never connected: the `template` gate fired before marker handling.
        # The binary has already exited, so a 0.5s grace (2 probe accept-poll cycles)
        # is enough to catch any late backlog connection without padding every run.
        assert not probe.connected.wait(0.5), (
            "the exported TEMPLATE binary connected — the `template` gate did NOT fire "
            "before marker/socket handling\n" + out_text
        )


@pytest.mark.e2e
def test_daemon_install_leaves_a_project_a_real_engine_boots_inert(tmp_path):
    # #670: the CLI command, end to end. `gda daemon install` performs the same
    # install `daemon start` folds in, so the project it leaves behind must boot the
    # same way the fast install tests' does — the autoload loads, and stays inert with
    # no daemon marker. Driven through a REAL `gda` subprocess (no daemon involved),
    # so the recipe, the JSON receipt and the engine's verdict are all exercised.
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    installed = subprocess.run(
        [*GDA_CMD, "daemon", "install", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert installed.returncode == 0, installed.stdout + installed.stderr
    receipt = json.loads(installed.stdout)
    assert receipt["installed_harness"] is True
    assert HARNESS_RES_PATH in receipt["created_paths"]
    assert receipt["created_sections"] == ["[autoload]"]
    assert (tmp_path / "addons" / "gda_harness" / HARNESS_FILE).exists()
    assert f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"' in (
        tmp_path / "project.godot"
    ).read_text(encoding="utf-8")

    proc = subprocess.run(
        [str(GODOT), "--headless", "--path", str(tmp_path), "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    _assert_inert_boot(proc.stdout + proc.stderr, proc.returncode)

    # And `gda daemon uninstall` reverses it, so the pair is symmetric end to end.
    removed = subprocess.run(
        [*GDA_CMD, "daemon", "uninstall", "--project", str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert json.loads(removed.stdout)["removed"] is True
    assert not (tmp_path / "addons" / "gda_harness").exists()
