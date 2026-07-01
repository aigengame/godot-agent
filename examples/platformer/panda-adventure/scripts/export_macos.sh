#!/usr/bin/env bash
#
# Reproducible macOS export smoke-test for Panda Adventure.
#
# Produces a launchable, ad-hoc-signed universal .app from a CLEAN checkout using
# only `gda` and a Godot binary ($GDA_GODOT or --godot). It encodes the two things
# a raw `gda export run` needs but does not do itself:
#   1. `mkdir -p build/` — Godot writes the artifact via FileAccess and will NOT
#      create the parent dir; an absent build/ is the `export_failed` review hit.
#   2. an ABSOLUTE --project — `gda export run` mis-resolves a RELATIVE --project
#      (it sets cwd=<project> AND passes --path <project>, applying the relative
#      path twice; gda issue #344), so we always pass the absolute path.
#
# Config: relies on the COMMITTED data/generated/player_config.tres (a tracked,
# derived artifact, so a clean checkout boots/exports with no build step). If you
# change data/json/player_config.json, regenerate it with
# `python3 scripts/build_config.py` — the CI freshness gate enforces they match.
#
# Usage:
#   export GDA_GODOT=/path/to/Godot
#   scripts/export_macos.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GAME_DIR="$(dirname "$SCRIPT_DIR")"
TRES="$GAME_DIR/data/generated/player_config.tres"
OUTPUT="$GAME_DIR/build/PandaAdventure.app"

if [[ ! -f "$TRES" ]]; then
	echo "error: missing derived config $TRES" >&2
	echo "       run: python3 $SCRIPT_DIR/build_config.py" >&2
	exit 1
fi

mkdir -p "$GAME_DIR/build"

gda export run \
	--preset macOS \
	--mode release \
	--project "$GAME_DIR" \
	--output "$OUTPUT" \
	--json

echo "exported: $OUTPUT"
