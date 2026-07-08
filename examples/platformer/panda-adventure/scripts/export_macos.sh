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

# Git-LFS gate (gADR-0015): the shipped .app must carry the REAL bytes of any
# LFS-tracked asset, not pointer files. No-op while the repo has no LFS assets;
# once it does, a missing git-lfs OR a failed pull FAILS the export rather than
# silently shipping pointer files (set -e is on; no `|| true` swallowing).
if command -v git-lfs >/dev/null 2>&1; then
	git -C "$GAME_DIR" lfs install --local >/dev/null
	if [[ -n "$(git -C "$GAME_DIR" lfs ls-files)" ]]; then
		git -C "$GAME_DIR" lfs pull
	fi
elif [[ -n "$(git -C "$GAME_DIR" ls-files -- ':(attr:filter=lfs)assets' 2>/dev/null)" ]]; then
	echo "error: LFS-tracked assets are present but git-lfs is not installed." >&2
	echo "       Install git-lfs so the shipped .app carries real bytes, not pointers." >&2
	exit 1
fi

gda export run \
	--preset macOS \
	--mode release \
	--project "$GAME_DIR" \
	--output "$OUTPUT" \
	--json

echo "exported: $OUTPUT"
