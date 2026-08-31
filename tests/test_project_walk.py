"""The ``res://`` walk contract: one traversal, four collectors (#764).

``operations.gd`` walks the project's ``res://`` tree for four purposes —
``scene list``, ``script list``, the extension-filtered static-analysis scan,
and the unfiltered count behind ``project statistics``. The ``DirAccess``
scaffolding around that walk used to be copied once per purpose, and the copies
drifted twice: first on the directory-exclusion decision (#712), then on the
file-acceptance test, where the scene walk alone compared the extension
case-sensitively.

These are the source-level guards for the consolidation. The BEHAVIOUR they
protect — the case rule and the two surviving file universes — is pinned against
a real engine in ``test_e2e_project_walk.py``.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS_GD = ROOT / "src" / "gda" / "ops" / "operations.gd"

# The four collectors, each of which must be a single delegation to the traversal.
COLLECTORS = (
    "_collect_resource_paths",
    "_collect_all_file_paths",
    "_collect_scene_paths",
    "_collect_script_paths",
)

# The traversal they share, and the DirAccess call only it may make.
TRAVERSAL = "_collect_paths"
LISTING_CALL = "list_dir_begin()"

# The section note that documents the two static scans over the one traversal.
SECTION_HEADER = "# --- project static-analysis reads (issue #116) ---"

# A gda helper named in prose: a ``_``-prefixed identifier that is not the tail of
# a longer word, so ``ext_resource`` does not read as a mention of ``_resource``.
HELPER_MENTION = re.compile(r"(?<![A-Za-z0-9_])_[a-z][A-Za-z0-9_]*")


def _source() -> str:
    return OPERATIONS_GD.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> list[str]:
    """The statement lines of top-level ``func name(...)`` — comments dropped."""
    lines = source.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith(f"func {name}(")), None
    )
    assert start is not None, f"expected function {name} in operations.gd"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break  # back at column 0: the function ended
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            body.append(stripped)
    return body


def _comment_block(source: str, header: str) -> list[str]:
    """The run of comment lines starting at the line that opens with ``header``."""
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(header)), None)
    assert start is not None, f"expected the comment block opening with {header!r}"
    block: list[str] = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(line)
    return block


def test_the_four_res_collectors_share_one_traversal():
    # AC1 (#764): ONE traversal implementation. The DirAccess scaffolding exists
    # exactly once in the payload, inside the shared walker; each collector is a
    # single delegation to it and differs only in the acceptance test it passes.
    source = _source()

    copies = source.count(LISTING_CALL)
    assert copies == 1, (
        f"the res:// listing scaffolding must live only in {TRAVERSAL}; "
        f"found {copies} copies of {LISTING_CALL}"
    )
    assert LISTING_CALL in "\n".join(_function_body(source, TRAVERSAL)), (
        f"{TRAVERSAL} must be the function that holds the listing scaffolding"
    )

    accepts: dict[str, str] = {}
    for name in COLLECTORS:
        body = _function_body(source, name)
        assert len(body) == 1, f"{name} must be one delegating line, got {body}"
        call = re.fullmatch(
            rf"{TRAVERSAL}\(\w+, (?P<accept>_[A-Za-z0-9_]+), \w+\)", body[0]
        )
        assert call, f"{name} must delegate to {TRAVERSAL}, got {body[0]!r}"
        accepts[name] = call.group("accept")

    # The acceptance test is the one thing they vary — four distinct predicates,
    # each a function this file defines.
    assert len(set(accepts.values())) == len(COLLECTORS), (
        f"each collector must pass its own acceptance test, got {accepts}"
    )
    for name, accept in accepts.items():
        assert f"func {accept}(" in source, f"{name} passes undefined {accept}"


def test_the_static_analysis_note_names_only_helpers_that_exist():
    # AC5 (#764): the section note used to claim a SINGLE static project scan
    # performed by a helper named `_scan_project` — a function this file has
    # never defined. It now describes the two scans and the traversal they share,
    # and every gda helper it names must be a function that actually exists, so
    # the correction cannot rot back into a phantom.
    source = _source()
    defined = set(re.findall(r"^func (_[A-Za-z0-9_]+)\(", source, re.MULTILINE))

    assert "_scan_project" not in source, (
        "operations.gd names _scan_project, which no function defines"
    )

    note = _comment_block(source, SECTION_HEADER)
    mentioned = {token for line in note for token in HELPER_MENTION.findall(line)}
    assert mentioned, "the section note must name the helpers it describes"
    undefined = sorted(mentioned - defined)
    assert not undefined, f"the section note names undefined helpers: {undefined}"

    # The corrected fact itself: two scans over different universes, one traversal.
    assert {
        "_collect_resource_paths",
        "_collect_all_file_paths",
        TRAVERSAL,
    } <= mentioned
