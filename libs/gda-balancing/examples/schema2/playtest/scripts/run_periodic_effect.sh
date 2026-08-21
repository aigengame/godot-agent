#!/usr/bin/env bash
set -euo pipefail

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$script_directory/run_playtest.sh" "res://apps/periodic_effect/main.tscn"
