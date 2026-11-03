"""Verify this finite historical evidence portfolio, not future test inventory."""

import gzip
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
xml_receipts = 0
for entry in manifest["entries"]:
    data = (root / entry["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["tracked_sha256"], entry["path"]
    if Path(entry["path"]).suffix == ".xml":
        ET.fromstring(data)
        xml_receipts += 1
    if entry["kind"] == "gzip-verbatim-original":
        assert (
            hashlib.sha256(gzip.decompress(data)).hexdigest()
            == entry["original_sha256"]
        )
    if entry["kind"] == "verbatim-original":
        assert entry["tracked_sha256"] == entry["original_sha256"]
baseline = gzip.decompress(
    (root / "retirement/baseline-observations.json.gz").read_bytes()
)
candidate = gzip.decompress(
    (root / "retirement/candidate-observations.json.gz").read_bytes()
)
assert baseline == candidate
observations = json.loads(baseline)["observations"]
receipt = json.loads((root / "retirement/sink-probe-result.json").read_text())
assert len(observations) == receipt["observation_count"]
assert hashlib.sha256(baseline).hexdigest() == receipt["observation_sha256"]
print(
    f"Verified {len(manifest['entries'])} recorded files, "
    f"{xml_receipts} readable XML receipts and {len(observations)} paired CLI observations."
)
