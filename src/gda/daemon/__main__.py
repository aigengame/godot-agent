"""``python -m gda.daemon``: the detached per-project daemon entry (ADR-0017).

``gda daemon start`` spawns this in its own session (detached from the one-shot
CLI). It derives the per-project paths the same way the CLI does — same
``GDA_PROJECT``/env, so it binds the very socket the CLI will connect to — and
runs the server loop until stopped.
"""

import argparse
from pathlib import Path

from gda.daemon.discovery import daemon_paths
from gda.daemon.server import DaemonServer


def main() -> None:
    parser = argparse.ArgumentParser(prog="gda.daemon")
    parser.add_argument("--project", required=True, help="The project root to serve.")
    parser.add_argument(
        "--godot", default="", help="The resolved Godot binary for engine sessions."
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Launch engine sessions windowed (no --headless), for `screen` capture (#222).",
    )
    args = parser.parse_args()

    paths = daemon_paths(Path(args.project))
    DaemonServer(paths, godot=args.godot, windowed=args.windowed).serve()


if __name__ == "__main__":
    main()
