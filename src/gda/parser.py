"""Result parser for the ADR-0002 sentinel contract.

A headless Godot process interleaves its banner, warnings and stray ``print()``
output into stdout. The GDScript operation emits exactly one result payload
wrapped in unique sentinels::

    <<<GDA:RESULT>>>{...json...}<<<GDA:END>>>

``parse_result`` extracts the bytes between the sentinels and parses them as
JSON, ignoring everything else on stdout.
"""

import json
from typing import Any

RESULT_BEGIN = "<<<GDA:RESULT>>>"
RESULT_END = "<<<GDA:END>>>"


def parse_result(stdout: str) -> Any:
    """Extract and parse the sentinel-delimited JSON result from ``stdout``."""
    start = stdout.find(RESULT_BEGIN)
    if start == -1:
        raise ValueError("no GDA result sentinel found in stdout")
    payload_start = start + len(RESULT_BEGIN)
    end = stdout.find(RESULT_END, payload_start)
    if end == -1:
        raise ValueError("unterminated GDA result sentinel in stdout")
    return json.loads(stdout[payload_start:end])
