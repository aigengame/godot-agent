"""The dependency rules of the headless payload (ADR-0043 §3).

The payload under ``src/gda/ops`` is an entry (``operations.gd``), the op base
(``op_base.gd``), one file per command group (``groups/``) and the concept
modules (``lib/``). A group depends on the op base and on concept modules, never
on another group; a concept module never depends on a group or on the entry; and
the concept modules form no cycle. The engine loads a cycle (ADR-0043 probe 7),
so the rules hold only through this test: it reads the ``preload("…")`` and
``extends "…"`` targets of every payload file and fails on each forbidden edge.
"""

import re
from pathlib import Path

from tests.support import PAYLOAD_DIR, payload_files

PRELOAD = re.compile(r'preload\("([^"]+)"\)')
EXTENDS = re.compile(r'^extends "([^"]+)"$')

ENTRY = "entry"
SEAM = "seam"
GROUP = "group"
CONCEPT = "concept"


def _tier(path: Path) -> str:
    relative = path.relative_to(PAYLOAD_DIR)
    if relative == Path("operations.gd"):
        return ENTRY
    if relative == Path("op_base.gd"):
        return SEAM
    if relative.parts[0] == "groups":
        return GROUP
    if relative.parts[0] == "lib":
        return CONCEPT
    raise AssertionError(f"{relative} is in no tier of the ADR-0043 module map")


def _targets(path: Path) -> set[Path]:
    """The payload files ``path`` preloads or extends, by resolved path.

    Comment lines are skipped: the payload documents ``preload("…")`` forms it
    scans for in user scripts. A target that is not a payload file fails here, so
    a mistyped relative path is RED in this tier and not only on the engine.
    """
    targets: set[Path] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        code = line.strip()
        if code.startswith("#"):
            continue
        for reference in [*PRELOAD.findall(code), *EXTENDS.findall(code)]:
            target = (path.parent / reference).resolve()
            assert target.is_file() and target.is_relative_to(PAYLOAD_DIR.resolve()), (
                f"{path.relative_to(PAYLOAD_DIR)} names {reference}, "
                f"which is not a payload file"
            )
            targets.add(target)
    return targets


def _edges() -> dict[Path, set[Path]]:
    edges = {path.resolve(): _targets(path) for path in payload_files()}
    assert any(edges.values()), "no preload or extends edge found in the payload"
    return edges


def _name(path: Path) -> str:
    return str(path.relative_to(PAYLOAD_DIR.resolve()))


def test_every_payload_file_is_in_a_tier_of_the_module_map():
    for path in payload_files():
        assert _tier(path) in {ENTRY, SEAM, GROUP, CONCEPT}


def test_no_group_depends_on_another_group():
    for source, targets in _edges().items():
        if _tier(source) != GROUP:
            continue
        forbidden = sorted(
            _name(target) for target in targets if _tier(target) == GROUP
        )
        assert not forbidden, f"{_name(source)} depends on a group: {forbidden}"


def test_no_concept_module_depends_on_a_group_or_the_entry():
    for source, targets in _edges().items():
        if _tier(source) != CONCEPT:
            continue
        forbidden = sorted(
            _name(target) for target in targets if _tier(target) in {GROUP, ENTRY}
        )
        assert not forbidden, (
            f"{_name(source)} depends on a group or the entry: {forbidden}"
        )


def test_concept_modules_form_no_cycle():
    edges = _edges()
    concepts = {path for path in edges if _tier(path) == CONCEPT}
    finished: set[Path] = set()

    def visit(path: Path, trail: list[Path]) -> None:
        if path in trail:
            cycle = [*trail[trail.index(path) :], path]
            raise AssertionError(
                "concept modules form a cycle: " + " -> ".join(map(_name, cycle))
            )
        if path in finished:
            return
        for target in sorted(edges[path]):
            if target in concepts:
                visit(target, [*trail, path])
        finished.add(path)

    for path in sorted(concepts):
        visit(path, [])
