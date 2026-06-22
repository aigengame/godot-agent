"""S2 (fast): gda-mcp carries zero live/phase-specific code (issue #227, ADR-0011).

The verification slice's structural invariant turned into an enforced regression
guard: gda-mcp is a *generic* CLI-subprocess client — it maps the aggregate
schema dump (ADR-0012) to tools and dispatches by exit code (ADR-0011), with no
awareness of whether a command is headless or live. So its two core modules
(``server.py``, ``runner.py``) must carry no live-phase *logic*: no branch on a
command's execution kind, no daemon channel, no live-ness in any form
(``live`` / ``daemon`` / ``kind`` / ``ExecutionKind``).

The guard scans the modules' executable **code tokens only** — comments and
string literals (docstrings) are stripped first. The two modules legitimately
say "a live session" in prose to mean an *active MCP session* (unrelated to the
Phase-2 live channel); a literal text scan would false-fire on that and tempt an
edit to clean generic code. Scanning code keeps the invariant honest: it trips
on a real reference like ``cmd.kind`` or an ``import`` of the daemon channel —
which is exactly the ADR-0011 violation to surface, not patch — while letting
the prose stand.
"""

import io
import re
import tokenize
from pathlib import Path

import gda.mcp.runner
import gda.mcp.server

# The live-phase vocabulary gda-mcp's code must never reference: a branch on a
# command's execution kind, the daemon channel, or live-ness in any form.
_FORBIDDEN = ("live", "daemon", "kind", "ExecutionKind")

# Token kinds that are documentation/structure, not executable code — stripped so
# the scan sees only what the module *does*, never what it *says* about itself.
_NON_CODE_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.STRING,  # drops docstrings and every string literal
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)


def _code_text(module) -> str:
    """The module's source with comments and string literals removed.

    Leaves only identifiers/keywords/operators, so a substring match cannot
    false-fire on prose like the docstrings' "a live session".
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    readline = io.StringIO(source).readline
    return " ".join(
        tok.string
        for tok in tokenize.generate_tokens(readline)
        if tok.type not in _NON_CODE_TOKENS
    )


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
