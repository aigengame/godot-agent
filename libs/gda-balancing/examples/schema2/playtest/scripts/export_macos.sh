#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT="$PROJECT_DIR/build/RewardRun.app"

mkdir -p "$PROJECT_DIR/build"

gda export run \
	--preset macOS \
	--mode debug \
	--project "$PROJECT_DIR" \
	--output "$OUTPUT" \
	--json

"$SCRIPT_DIR/smoke_export_macos.sh" "$OUTPUT"
