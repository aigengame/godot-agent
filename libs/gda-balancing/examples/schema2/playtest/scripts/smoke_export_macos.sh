#!/usr/bin/env bash

set -euo pipefail

APP_PATH="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build/RewardRun.app}"
BINARY="$APP_PATH/Contents/MacOS/Reward Run"

if [[ ! -x "$BINARY" ]]; then
	echo "error: exported Reward Run binary not found at $BINARY" >&2
	exit 1
fi

OUTPUT="$("$BINARY" --headless --quit-after 3 2>&1)"
if [[ "$OUTPUT" != *'"event":"playtest_started"'* ]]; then
	echo "error: exported Reward Run did not reach the player-facing path" >&2
	echo "$OUTPUT" >&2
	exit 1
fi

echo '{"artifact":"RewardRun.app","status":"launched"}'
