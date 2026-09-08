"""Keep the bounded imported/live static-model sampler byte-identical (#890)."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "src" / "gda" / "ops" / "operations.gd"
HARNESS = ROOT / "src" / "gda" / "harness" / "gda_harness.gd"
BLOCK = re.compile(
    r"^# --- BEGIN shared static model content sampling \(#890\) ---$\n"
    r"(?P<body>.*?)"
    r"^# --- END shared static model content sampling ---$",
    re.MULTILINE | re.DOTALL,
)


def _block(path: Path) -> str:
    matches = BLOCK.findall(path.read_text(encoding="utf-8"))
    assert len(matches) == 1, f"expected one sampler block in {path.name}"
    return matches[0]


def test_static_model_content_sampler_is_byte_identical():
    imported = _block(OPERATIONS)
    live = _block(HARNESS)

    assert imported
    assert imported == live
