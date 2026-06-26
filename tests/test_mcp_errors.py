"""S3 (fast): gda-mcp error channel + the can't-run / non-envelope edge (issue #193).

A failing gda call (non-zero exit) maps to ``CallToolResult(isError=True)``
carrying gda's ``GdaError`` envelope **verbatim and losslessly** as JSON content
(never flattened to prose, never folded into ``structuredContent`` /
``outputSchema``) — ADR-0011. The stable ``code`` survives for every non-zero
category: environment / version / operation / parse, including the launch codes
(``binary_not_found`` / ``launch_timeout``) and the parse-category
``contract_violation``. The edge — gda could not even run, or emitted
non-envelope output — is synthesized by gda-mcp itself.

These drive the real surface through a fake seam (no gda subprocess, no Godot)
over an in-memory MCP client.
"""

import json

import pytest

from gda.error_codes import ERROR_CODE_BY_CODE
from gda.mcp.server import build_server
from gda.models import GdaError, GdaErrorEnvelope
from tests.mcp_support import FakeGdaRunner, call_tool, gda_result, schema_then


def _gda_envelope_json(code: str) -> str:
    """The exact stdout gda emits for ``code`` — the real envelope, real shape."""
    spec = ERROR_CODE_BY_CODE[code]
    error = GdaError(
        category=spec.category,
        code=code,
        message=f"{code} happened",
        diagnostics="engine stderr noise",
    )
    return GdaErrorEnvelope(error=error).model_dump_json()


def _failing_server(code: str):
    """A server whose every dispatch fails with gda's real envelope for ``code``."""
    spec = ERROR_CODE_BY_CODE[code]
    stdout = _gda_envelope_json(code)
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(stdout, returncode=spec.exit_code))
    )
    return build_server(runner)


# One representative code per non-zero category, spanning the two launch codes
# and the parse-category contract_violation the AC calls out explicitly.
@pytest.mark.parametrize(
    "code",
    [
        "binary_not_found",  # environment (launch, exit 127)
        "launch_timeout",  # environment (launch, exit 124)
        "unsupported_version",  # version
        "operation_failed",  # operation
        "path_not_found",  # operation (an operation-reported code)
        "contract_violation",  # parse
    ],
)
def test_each_category_relays_losslessly_as_is_error(code):
    result = call_tool(
        _failing_server(code), "scene_create", {"path": "x", "root_type": "Node2D"}
    )

    # The failure channel: isError, and the error stays OUT of structuredContent.
    assert result.isError is True
    assert result.structuredContent is None
    # Lossless: the single content block parses back to gda's exact envelope —
    # all four fields, and crucially the stable code, preserved verbatim.
    assert len(result.content) == 1
    relayed = json.loads(result.content[0].text)
    assert relayed == json.loads(_gda_envelope_json(code))
    assert relayed["error"]["code"] == code
    assert relayed["error"]["category"] == ERROR_CODE_BY_CODE[code].category.value


def test_relayed_content_is_not_flattened_to_prose():
    # ADR-0011: the envelope must arrive as JSON an agent can branch on, never a
    # prose string the SDK would synthesize from a raised exception.
    result = call_tool(_failing_server("path_not_found"), "scene_create", {"path": "x"})
    text = result.content[0].text
    parsed = json.loads(text)  # must be valid JSON, not prose
    assert set(parsed["error"]) >= {"category", "code", "message", "diagnostics"}


def test_cannot_run_edge_is_synthesized_by_gda_mcp():
    # gda could not even run (e.g. `-m gda` import failure): no stdout, a traceback
    # on stderr, non-zero exit. gda-mcp synthesizes its OWN structured isError,
    # preserving gda's stderr as diagnostics rather than crashing or going silent.
    runner = FakeGdaRunner(
        schema_then(
            lambda args, stdin: gda_result(
                stdout="",
                stderr="Traceback: ModuleNotFoundError: No module named 'gda'",
                returncode=1,
            )
        )
    )
    result = call_tool(build_server(runner), "info", {})

    assert result.isError is True
    assert result.structuredContent is None
    body = json.loads(result.content[0].text)
    assert body["error"]["category"] == "adapter"  # gda-mcp's own, not a gda category
    assert "ModuleNotFoundError" in body["error"]["diagnostics"]


def test_non_envelope_output_edge_is_synthesized():
    # Non-zero exit but stdout is not a GdaError envelope (a Click usage error, a
    # bare string, JSON missing the error shape): also synthesized by gda-mcp.
    runner = FakeGdaRunner(
        schema_then(
            lambda args, stdin: gda_result(stdout='{"not":"an envelope"}', returncode=2)
        )
    )
    result = call_tool(build_server(runner), "info", {})

    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["category"] == "adapter"


def test_exit_zero_but_non_json_stdout_edge_is_synthesized():
    # The success-path edge: gda exits 0 yet stdout is not JSON (so --json could
    # not have been honored). gda-mcp treats it as an adapter error, not a crash.
    runner = FakeGdaRunner(
        schema_then(
            lambda args, stdin: gda_result(stdout="not json at all", returncode=0)
        )
    )
    result = call_tool(build_server(runner), "info", {})

    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["category"] == "adapter"
