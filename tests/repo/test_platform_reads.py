"""The ``sys.platform`` and ``os.name`` reads under ``src/gda``, on one allow-list.

The daemon selects its platform implementation in one place,
``gda.daemon.host`` (#1189). A new ``sys.platform`` or ``os.name`` read beside
the seam would make a second selection, which nothing keeps in step with the
first. The reads are found statically with ``ast``, so a read is caught whether
or not a test imports its module. The counter sees an attribute read on the
module or on an ``import ... as`` alias of it, and counts a ``from`` import of
either name once, at the import. It does not follow an assignment alias
(``host = sys``) or ``getattr(sys, "platform")``. Each file that may read the
host platform is named below with the number of reads it holds and the reason
for them; a read in another file, or a changed count, fails the test until this
list states why.
"""

import ast
from pathlib import Path

GDA = Path(__file__).resolve().parents[2] / "src" / "gda"
READS = {("sys", "platform"), ("os", "name")}

ALLOWED = {
    "daemon/host.py": (
        1,
        "the one selection: host_platform() picks the daemon's platform adapter",
    ),
    "daemon/windows_discovery.py": (
        4,
        "the Windows adapter's guards",
    ),
    "daemon/windows_process.py": (
        2,
        "the Windows adapter's guards: a Windows-only primitive refuses another host",
    ),
    "daemon/display.py": (
        8,
        "the windowed-session display probe, which asks each host its own question",
    ),
    "core/engine/execution.py": (
        1,
        "the Live support guard: it looks up this host in the published platform set",
    ),
    "core/engine/user_data.py": (
        3,
        "the engine's user-data path and editor directories, which each host takes "
        "from its own variables",
    ),
    "core/failure/classify.py": (
        1,
        "the exit-status decode: a Windows exit status is an unsigned 32-bit value",
    ),
    "mcp/runner.py": (
        1,
        "the $GDA_BIN command line, which Windows keeps as text and Unix splits",
    ),
}


def _reads(tree: ast.AST) -> int:
    """The ``sys.platform`` and ``os.name`` reads in one module, as counted above."""
    modules = {"sys": "sys", "os": "os"}
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules and alias.asname:
                    modules[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"sys", "os"}:
            count += sum((node.module, alias.name) in READS for alias in node.names)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (modules.get(node.value.id), node.attr) in READS
        ):
            count += 1
    return count


def _platform_reads() -> dict[str, int]:
    found = {}
    for path in sorted(GDA.rglob("*.py")):
        count = _reads(ast.parse(path.read_text(encoding="utf-8")))
        if count:
            found[path.relative_to(GDA).as_posix()] = count
    return found


def test_every_platform_read_is_on_the_allow_list():
    allowed = {name: count for name, (count, _) in ALLOWED.items()}

    assert _platform_reads() == allowed, (
        "a sys.platform or os.name read changed under src/gda: select through "
        "gda.daemon.platform, or state the read's reason in ALLOWED"
    )


def test_the_read_counter_counts_the_named_forms():
    source = (
        "import sys\nimport os as _os\nfrom sys import platform\n"
        "a = sys.platform\nb = _os.name\nc = sys.argv\n"
    )

    assert _reads(ast.parse(source)) == 3
