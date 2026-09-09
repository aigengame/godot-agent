from dataclasses import asdict
import json
from pathlib import Path

import pytest

from gda_assets.adapters.preview_baseline import read_preview_baseline
from gda_assets.application.ports import PortFailure
from test_preview_comparison import _result


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, default=str))


def test_reads_explicit_public_preview_envelope(tmp_path):
    path = tmp_path / "baseline.json"
    _write(path, {"preview": asdict(_result())})

    baseline = read_preview_baseline(path)

    assert baseline.source_sha256 == "a" * 64
    assert baseline.views[0].state is not None
    assert baseline.performance is not None
    assert baseline.views[0].state.camera.name == "front"
    assert baseline.performance.stats["fps"].count == 3


@pytest.mark.parametrize(
    "value", [{}, {"preview": {}}, {"preview": asdict(_result()), "extra": 1}]
)
def test_rejects_malformed_or_non_public_envelopes(tmp_path, value):
    path = tmp_path / "baseline.json"
    _write(path, value)

    with pytest.raises(PortFailure) as failure:
        read_preview_baseline(path)

    assert failure.value.code == "invalid_preview_baseline"


def test_rejects_oversized_baseline_before_parsing(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))

    with pytest.raises(PortFailure) as failure:
        read_preview_baseline(path)

    assert failure.value.code == "invalid_preview_baseline"


def test_rejects_non_regular_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.mkdir()

    with pytest.raises(PortFailure) as failure:
        read_preview_baseline(path)

    assert failure.value.code == "invalid_preview_baseline"


def test_invalid_baseline_diagnostic_does_not_embed_input_or_vendor_dump(tmp_path):
    path = tmp_path / "baseline.json"
    _write(path, {"preview": {"request": "untrusted-input-marker"}})

    with pytest.raises(PortFailure) as failure:
        read_preview_baseline(path)

    assert "untrusted-input-marker" not in str(failure.value)
    assert "pydantic.dev" not in str(failure.value)
    assert "request" in str(failure.value)


def test_pre_warmup_baseline_retains_zero_default(tmp_path):
    payload = asdict(_result())
    del payload["request"]["warmup_seconds"]
    path = tmp_path / "old.json"
    _write(path, {"preview": payload})
    assert read_preview_baseline(path).request.warmup_seconds == 0
