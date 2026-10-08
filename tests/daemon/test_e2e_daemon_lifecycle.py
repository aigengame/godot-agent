"""Public daemon lifecycle, independently of engine-session availability (#1117)."""

import json
import os
import signal
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from typer.testing import CliRunner

from tests.support import Gda, runnable_project
from gda.cli import app
from gda.daemon.discovery import daemon_paths
from gda.daemon.protocol import write_message


@pytest.fixture
def lifecycle_project(tmp_path, daemon_runtime_dir):
    return runnable_project(tmp_path / "project")


@pytest.mark.e2e
def test_a_daemon_remains_available_after_start_and_protects_its_harness(
    lifecycle_project,
):
    run = Gda(lifecycle_project, json_output=True)
    try:
        started = run.json("daemon", "start")
        assert started["already_running"] is False
        status = run.json("daemon", "status")
        assert status["running"] is True
        assert status["pid"] == started["pid"]
        assert status["session_id"] is None
        assert status["startup_diagnostics"] is None
        assert status["clean_start"] is None
        again = run.json("daemon", "start")
        assert again["already_running"] is True
        assert again["pid"] == started["pid"]
        refused = run("daemon", "uninstall")
        assert refused.returncode == 6, refused.stdout + refused.stderr
        assert json.loads(refused.stdout)["error"]["code"] == "daemon_running"
    finally:
        run("daemon", "stop")
    assert run.json("daemon", "status")["running"] is False
    assert run.json("daemon", "stop")["stopped"] is False
    assert run.json("daemon", "uninstall")["removed"] is True
    assert run.json("daemon", "uninstall")["removed"] is False


@pytest.mark.e2e
def test_concurrent_starts_keep_one_owner_and_another_project_is_independent(
    lifecycle_project,
):
    run = Gda(lifecycle_project, json_output=True)
    other = Gda(
        runnable_project(lifecycle_project.parent / "another"), json_output=True
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            starts = list(pool.map(lambda _: run.json("daemon", "start"), range(2)))
        assert starts[0]["pid"] == starts[1]["pid"]
        independent = other.json("daemon", "start")
        assert independent["pid"] != starts[0]["pid"]
        assert other.json("daemon", "stop")["stopped"] is True
        assert run.json("daemon", "status")["pid"] == starts[0]["pid"]
        assert run.json("daemon", "status")["windowed"] is False
    finally:
        run("daemon", "stop")
        other("daemon", "stop")


@pytest.mark.e2e
def test_a_crashed_owner_is_not_live_and_can_be_replaced(lifecycle_project):
    run = Gda(lifecycle_project, json_output=True)
    try:
        owner = run.json("daemon", "start")["pid"]
        os.kill(owner, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while run.json("daemon", "status")["running"]:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        replacement = run.json("daemon", "start")
        assert replacement["already_running"] is False
        assert replacement["pid"] != owner
        assert run.json("daemon", "status")["pid"] == replacement["pid"]
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@pytest.mark.skipif(os.name != "nt", reason="Windows TCP authentication boundary")
def test_wrong_absent_and_malformed_peers_cannot_stop_the_owner(lifecycle_project):
    run = Gda(lifecycle_project, json_output=True)
    try:
        started = run.json("daemon", "start")
        assert started["socket_path"] is None
        assert started["endpoint"]["transport"] == "tcp"
        host, port = started["endpoint"]["address"].rsplit(":", 1)
        assert host == "127.0.0.1"
        metadata = json.loads(
            daemon_paths(lifecycle_project)
            .pidfile.with_suffix(".json")
            .read_text(encoding="utf-8")
        )
        token = metadata["token"]
        assert metadata["cli_port"] != metadata["harness_port"]
        for prefix, payload in (
            (bytes(32), {"op": "__stop__"}),
            (b"", {"op": "__stop__"}),
            (bytes.fromhex(token), None),
        ):
            with socket.create_connection((host, int(port)), timeout=4) as peer:
                peer.sendall(prefix)
                if payload is None:
                    peer.sendall(struct.pack(">I", 1) + b"!")
                else:
                    write_message(peer, payload)
                try:
                    assert peer.recv(1) == b""
                except (ConnectionResetError, ConnectionAbortedError):
                    pass
            status = run("daemon", "status")
            assert token not in status.stdout + status.stderr
            assert json.loads(status.stdout)["windowed"] is False
        # Even an authenticated direct peer cannot open the unimplemented session.
        for op in (
            "daemon-wait-ready",
            "daemon-start",
            "daemon-install",
            "daemon-status",
            "daemon-stop",
            "daemon-uninstall",
        ):
            with socket.create_connection((host, int(port)), timeout=4) as peer:
                peer.sendall(bytes.fromhex(token))
                write_message(peer, {"op": op, "params": {}})
                from gda.daemon.protocol import read_message

                reply = read_message(peer)
            assert reply is not None
            assert "live_unsupported_platform" in reply["stdout"]
        assert run.json("daemon", "status")["session_id"] is None
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@pytest.mark.skipif(os.name != "nt", reason="Windows TCP authentication boundary")
@pytest.mark.parametrize("authenticated", [False, True])
def test_a_trickling_peer_cannot_renew_the_control_deadline(
    lifecycle_project, authenticated
):
    run = Gda(lifecycle_project, json_output=True)
    try:
        address = run.json("daemon", "start")["endpoint"]["address"]
        host, port = address.rsplit(":", 1)
        started = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=4) as peer:
            if authenticated:
                metadata = json.loads(
                    daemon_paths(lifecycle_project)
                    .pidfile.with_suffix(".json")
                    .read_text(encoding="utf-8")
                )
                peer.sendall(bytes.fromhex(metadata["token"]) + struct.pack(">I", 64))
            for _ in range(40):
                try:
                    peer.sendall(b"x")
                except OSError:
                    break
                time.sleep(0.1)
            try:
                assert peer.recv(1) == b""
            except (ConnectionResetError, ConnectionAbortedError):
                pass
        assert time.monotonic() - started < 3.5
        assert run.json("daemon", "status")["windowed"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.e2e
@pytest.mark.skipif(os.name != "nt", reason="Windows private-directory ACL boundary")
def test_an_existing_shared_runtime_is_refused_before_install(lifecycle_project):
    paths = daemon_paths(lifecycle_project)
    paths.runtime_dir.mkdir(mode=0o700, parents=True)
    granted = subprocess.run(
        ["icacls", str(paths.runtime_dir), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
        capture_output=True,
        timeout=10,
    )
    assert granted.returncode == 0, granted.stdout + granted.stderr
    original = (lifecycle_project / "project.godot").read_bytes()
    run = Gda(lifecycle_project, json_output=True)
    refused = run("daemon", "start")
    assert refused.returncode == 6, refused.stdout + refused.stderr
    assert json.loads(refused.stdout)["error"]["code"] == "daemon_not_running"
    assert (lifecycle_project / "project.godot").read_bytes() == original
    assert not (lifecycle_project / "addons" / "gda_harness").exists()


@pytest.mark.e2e
@pytest.mark.skipif(os.name != "nt", reason="Windows failed-start ownership boundary")
def test_a_failed_concurrent_start_does_not_remove_the_winners_install(
    lifecycle_project,
    monkeypatch,
):
    run = Gda(lifecycle_project, json_output=True)
    native_spawn = subprocess.Popen
    winner_config = []

    def refused_spawn(args, *positional, **options):
        if isinstance(args, list) and args[1:3] == ["-m", "gda.daemon"]:
            # An actual owner starts between this caller's installation and its
            # refused OS spawn. Inject only that external process failure.
            run.json("daemon", "start")
            winner_config.append((lifecycle_project / "project.godot").read_bytes())
            raise PermissionError("controlled native spawn refusal")
        return native_spawn(args, *positional, **options)

    monkeypatch.setattr(subprocess, "Popen", refused_spawn)
    try:
        failed = CliRunner().invoke(
            app, ["daemon", "start", "--project", str(lifecycle_project), "--json"]
        )
        assert failed.exit_code == 6, failed.stdout + failed.stderr
        assert json.loads(failed.stdout)["error"]["code"] == "daemon_not_running"
        assert run.json("daemon", "status")["running"] is True
        assert (lifecycle_project / "project.godot").read_bytes() == winner_config[0]
        assert (
            lifecycle_project / "addons" / "gda_harness" / "gda_harness.gd"
        ).exists()
    finally:
        run("daemon", "stop")
