#!/usr/bin/env bash
set -euo pipefail

scene_path="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
playtest_dir="$(cd "$script_dir/.." && pwd)"

godot_executable="${GDA_GODOT:-}"
if [[ -z "$godot_executable" ]]; then
  godot_executable="$(command -v godot || command -v godot4 || true)"
fi
if [[ -z "$godot_executable" ]]; then
  echo "Godot executable not found. Set GDA_GODOT or add Godot to PATH." >&2
  exit 127
fi

gda_balancing_executable="${GDA_BALANCING_EXECUTABLE:-}"
if [[ -z "$gda_balancing_executable" ]]; then
  gda_balancing_executable="$(command -v gda-balancing || true)"
fi
arguments=(--path "$playtest_dir" "$scene_path")
if [[ -n "$gda_balancing_executable" ]]; then
  if [[ "$gda_balancing_executable" != /* ]]; then
    gda_balancing_executable="$PWD/$gda_balancing_executable"
  fi
  arguments+=(-- "--gda-balancing-executable=$gda_balancing_executable")
fi

exec "$godot_executable" "${arguments[@]}"
