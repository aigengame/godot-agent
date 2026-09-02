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


# The two branches of that traversal, and the predicate each must ask (#760).
DESCEND_PREDICATE = "_should_descend"
COLLECT_PREDICATE = "_should_collect"

# The single owner of the engine-cache exclusion both predicates route through,
# and the constant only it and the descent predicate's lexical fast path may name.
CACHE_OWNER = "_is_in_engine_cache"
CACHE_CONSTANT = "ENGINE_CACHE_DIR"


def _enclosing_function(source: str, line_index: int) -> str | None:
    """The name of the top-level ``func`` whose body holds ``line_index``."""
    lines = source.splitlines()
    for i in range(line_index, -1, -1):
        line = lines[i]
        if line.startswith("func "):
            return line[len("func ") :].split("(")[0]
        if line and not line.startswith(("\t", " ", "#")):
            return None  # a top-level statement that is not a func: outside one
    return None


def test_the_symlink_policy_is_asked_on_both_branches_of_the_traversal():
    # AC2 (#760): the aliasing rule has TWO touch points. `_should_descend` gates
    # DIRECTORY descent only, so a symlinked FILE — `res://alias.gd` pointing at a
    # file inside the engine cache — reaches the acceptance test without ever
    # passing it, and re-admits by itself the content the descent rule keeps out.
    # The traversal must therefore ask both, and this is the guard against a later
    # change fixing only the half that is easy to see.
    source = _source()
    traversal = "\n".join(_function_body(source, TRAVERSAL))

    for predicate in (DESCEND_PREDICATE, COLLECT_PREDICATE):
        assert f"{predicate}(" in traversal, (
            f"{TRAVERSAL} must ask {predicate}; the symlink policy covers both the "
            f"directory branch and the file branch"
        )
        assert f"func {predicate}(" in source, f"{predicate} is asked but not defined"


def test_the_engine_cache_exclusion_has_one_owner():
    # The exclusion is one decision (#712) and stays one now that answering it
    # means resolving filesystem identity (#760): both walk-side predicates route
    # the question to `_is_in_engine_cache`, and nothing else compares against the
    # cache path. A second comparison site is how the four collectors drifted the
    # first time.
    source = _source()

    for predicate in (DESCEND_PREDICATE, COLLECT_PREDICATE):
        body = "\n".join(_function_body(source, predicate))
        assert f"{CACHE_OWNER}(" in body, (
            f"{predicate} must ask {CACHE_OWNER} rather than test the cache itself"
        )

    users = set()
    for index, line in enumerate(source.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#") or CACHE_CONSTANT not in stripped:
            continue
        if stripped.startswith(f"const {CACHE_CONSTANT}"):
            continue  # the value's own declaration
        enclosing = _enclosing_function(source, index)
        assert enclosing is not None, f"{CACHE_CONSTANT} used outside any function"
        users.add(enclosing)

    assert users == {DESCEND_PREDICATE, CACHE_OWNER}, (
        f"{CACHE_CONSTANT} must be compared only in {DESCEND_PREDICATE}'s lexical "
        f"fast path and in {CACHE_OWNER}; found it in {sorted(users)}"
    )
