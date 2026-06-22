"""S2 (fast): gda-mcp carries zero live/phase-specific code (issue #227, ADR-0011).

The verification slice's structural invariant turned into an enforced regression
guard: gda-mcp is a *generic* CLI-subprocess client — it maps the aggregate
schema dump (ADR-0012) to tools and dispatches by exit code (ADR-0011), with no
awareness of whether a command is headless or live. So its two core modules
(``server.py``, ``runner.py``) must carry no live-phase *logic*: no branch on a
command's execution kind, no daemon channel, no live-ness in any form
(``live`` / ``daemon`` / ``kind`` / ``ExecutionKind``).

The guard scans the modules with only **comments and docstrings** stripped —
every *executable* string literal is kept. The two modules legitimately say "a
live session" in a *docstring* to mean an *active MCP session* (unrelated to the
Phase-2 live channel), so docstrings are dropped to avoid a false fire; but a real
per-phase reference — ``entry["kind"] == "live"``, an argv ``["daemon", …]``, an
``import`` of the daemon channel — lives in *executable* tokens (a dict key, a
call argument, a name), which the scan keeps visible. So it trips on exactly the
ADR-0011 violation to surface, not patch, while letting the prose stand. Stripping
*all* string literals, as a first cut did, would blind the guard to string-keyed
branching — the gap PR #246 review caught.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

import gda.mcp.runner
import gda.mcp.server

# The live-phase vocabulary gda-mcp's code must never reference: a branch on a
# command's execution kind, the daemon channel, or live-ness in any form.
_FORBIDDEN = ("live", "daemon", "kind", "ExecutionKind")


def _docstring_starts(source: str) -> set[tuple[int, int]]:
    """Start positions of every module/class/function docstring literal.

    A docstring is the first string-expression statement of a module, class, or
    function — the only string literal that is *documentation*. Every other string
    literal is executable code (a dict key like ``entry["kind"]``, an argv element
    like ``["daemon", …]``) and MUST stay visible to the scan, or the guard would
    miss the very per-phase branching it forbids (PR #246 review). Identifying
    docstrings by AST position lets us drop exactly those and keep the rest.
    """
    starts: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            const = body[0].value
            starts.add((const.lineno, const.col_offset))
    return starts


def _code_text(module) -> str:
    """The module's source with comments and docstrings removed — every
    *executable* string literal kept.

    So a real per-phase reference (``entry["kind"] == "live"``, an argv
    ``["daemon", …]``, an import naming the daemon channel) stays visible to the
    forbidden-vocabulary scan, while the modules' legitimate prose — a docstring
    saying "a live session" to mean an active MCP session — is dropped and cannot
    false-fire.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    docstrings = _docstring_starts(source)
    kept: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.start in docstrings:
            continue  # a docstring — not executable code
        kept.append(tok.string)
    return " ".join(kept)


def _phase_vocabulary_in(module) -> list[str]:
    code = _code_text(module)
    return [w for w in _FORBIDDEN if re.search(rf"\b{w}\b", code)]


def test_server_code_has_no_live_or_phase_specific_vocabulary():
    hits = _phase_vocabulary_in(gda.mcp.server)
    assert not hits, (
        f"src/gda/mcp/server.py's code references phase-specific vocabulary {hits}; "
        "gda-mcp must stay generic (ADR-0011) — surface this as a violation, "
        "do not patch the guard."
    )


def test_runner_code_has_no_live_or_phase_specific_vocabulary():
    hits = _phase_vocabulary_in(gda.mcp.runner)
    assert not hits, (
        f"src/gda/mcp/runner.py's code references phase-specific vocabulary {hits}; "
        "gda-mcp must stay generic (ADR-0011) — surface this as a violation, "
        "do not patch the guard."
    )
