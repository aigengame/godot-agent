#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
playtest_dir="$(cd "$script_dir/.." && pwd)"
package_dir="$(cd "$playtest_dir/../../.." && pwd)"

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
if [[ -z "$gda_balancing_executable" && -x "$package_dir/.venv/bin/gda-balancing" ]]; then
  gda_balancing_executable="$package_dir/.venv/bin/gda-balancing"
fi

arguments=(--path "$playtest_dir")
if [[ -n "$gda_balancing_executable" ]]; then
  executable_dir="$(cd "$(dirname "$gda_balancing_executable")" && pwd)"
  gda_balancing_executable="$executable_dir/$(basename "$gda_balancing_executable")"
  arguments+=(-- "--gda-balancing-executable=$gda_balancing_executable")
fi

exec "$godot_executable" "${arguments[@]}"
