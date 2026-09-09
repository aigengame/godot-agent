"""Prompt file admission refuses non-regular inputs before opening them."""

import os

import pytest

from tests.support import Gda


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes require POSIX")
@pytest.mark.parametrize("operation", ["prepare", "register"])
def test_named_pipe_input_is_refused_without_waiting_for_a_writer(tmp_path, operation):
    pipe = tmp_path / "input.png"
    os.mkfifo(pipe)
    record = tmp_path / "attempt"
    gda = Gda(None, godot=None, json_output=True, timeout=3)
    if operation == "prepare":
        args = ("prompt-prepare", "--record", str(record), "--template", str(pipe))
    else:
        gda.json(
            "asset-pipeline",
            "prompt-prepare",
            "--record",
            str(record),
            "--text",
            "A robot.",
        )
        args = (
            "prompt-register-output",
            "--record",
            str(record),
            "--output",
            str(pipe),
            "--name",
            "image.png",
        )

    error = gda.error("asset-pipeline", *args, code="invalid_params")

    assert "regular file" in error["message"]
    if operation == "prepare":
        assert not record.exists()
    else:
        result = gda.json("asset-pipeline", "prompt-inspect", "--record", str(record))
        assert result["preparation"]["record"]["outputs"] == []
