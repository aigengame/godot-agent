"""The game/engine-agnosticism isolation gate (#502, hardened standard).

The toolkit names no game identity and imports no game, engine, or `gda`
code; this gate is the single owner of that constraint, at the hardened
standard: recursive file collection and AST-level import walking (syntax-
aware, so lazy in-function imports and both `import X` / `from X import Y`
spellings are covered), an identifier-aware vocabulary scan, and a stray
per-game-config scan.

This module is the package's sole sanctioned appearance of the forbidden
terms (adjudicated on #502): a denylist must name what it bans, and the gate
is where the constraint lives — so the vocabulary scan exempts exactly this
file and nothing else.
"""

import ast
import re
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PACKAGE_ROOT / "src" / "gda_balancing"
_TESTS_DIR = _PACKAGE_ROOT / "tests"
_GATE_FILE = Path(__file__).resolve()

# The shipped Genre templates (bADR-0012): genre-generic Standard Schema
# instances, deliberately NOT per-game configs — exempt from the stray-config
# scan below, but held (with the committed test fixtures) to the vocabulary
# scan, which walks their JSON alongside the Python sources.
_TEMPLATES_DIR = _SRC_DIR / "templates"

# Top-level import roots of the sibling `gda` product, engine bindings, and
# the repo's example game's plug-ins/builder.
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "gda",
        "gda_mcp",
        "godot",
        "panda_assets",
        "panda_balancing",
        "build_config",
    }
)

# Game-identity vocabulary: engine identities and scripting language, the
# example game's identity + decision-record prefix, its item/actor identity
# nouns, and the mechanic fields PRD #501 names as the prior leak class
# (warp kit, time fields). Deliberate exclusions: a bare `gda` (substring of
# this package's own name; the import gate owns the import axis) and the
# predecessor gate's genre-generic mechanics words (gravity, hud, obstacle,
# crate, pickup, boss) — genre templates may legitimately speak those;
# `unity` collides with the math term, accepted (write `1` instead).
_FORBIDDEN_TERMS = (
    "godot",
    "gdscript",
    "unity",
    "unreal",
    "panda",
    "gadr",
    "spacesuit",
    "laser",
    "bun",
    "wine",
    "warp",
    "time_field",
    "time_dilation",
)

# Identifier-aware boundaries: `\b` treats `_` as a word character, so a
# snake_case compound like `warp_charges` would slip past `\bwarp\b`. These
# lookarounds bound terms by "not a letter/digit" instead, catching the term
# bare, in snake_case, and in SCREAMING_CASE alike.
_FORBIDDEN_VOCABULARY = re.compile(
    r"(?<![a-zA-Z0-9])(" + "|".join(_FORBIDDEN_TERMS) + r")(?![a-zA-Z0-9])",
    re.IGNORECASE,
)


def _python_sources() -> list[Path]:
    files = [
        path
        for base in (_SRC_DIR, _TESTS_DIR)
        for path in sorted(base.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    assert files, f"isolation gate found no sources under {_PACKAGE_ROOT}"
    return files


def _design_document_sources() -> list[Path]:
    """The committed Design-document JSON — shipped Genre templates and test
    fixtures — which speaks domain vocabulary and so joins the vocabulary
    scan (it cannot import, so the import gate does not apply)."""
    return [
        path
        for base in (_TEMPLATES_DIR, _TESTS_DIR / "fixtures")
        for path in sorted(base.rglob("*.json"))
    ]


def test_toolkit_imports_no_game_engine_or_gda_code() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            else:
                continue
            offenders.extend(
                f"{path.relative_to(_PACKAGE_ROOT)}:{node.lineno} imports {root!r}"
                for root in roots
                if root in _FORBIDDEN_IMPORT_ROOTS
            )
    assert not offenders, "engine-/game-agnosticism violated by imports:\n" + "\n".join(
        offenders
    )


def test_toolkit_speaks_no_game_identity_vocabulary() -> None:
    offenders: list[str] = []
    for path in _python_sources() + _design_document_sources():
        if path == _GATE_FILE:
            continue  # the denylist itself — the sole sanctioned appearance
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = _FORBIDDEN_VOCABULARY.search(line)
            if match:
                offenders.append(
                    f"{path.relative_to(_PACKAGE_ROOT)}:{lineno} "
                    f"speaks {match.group(0)!r}"
                )
    assert not offenders, (
        "engine-/game-agnosticism violated by vocabulary:\n" + "\n".join(offenders)
    )


def test_toolkit_carries_no_per_game_config() -> None:
    """Genre templates under ``templates/`` are the one sanctioned JSON
    payload (bADR-0012): genre-generic baselines, not per-game configs. Any
    other JSON under ``src/`` remains a violation."""
    stray = [
        str(path.relative_to(_PACKAGE_ROOT))
        for path in sorted(_SRC_DIR.rglob("*.json"))
        if _TEMPLATES_DIR not in path.parents
    ]
    assert not stray, "per-game config files inside the toolkit:\n" + "\n".join(stray)


@pytest.mark.parametrize("term", _FORBIDDEN_TERMS)
def test_vocabulary_gate_catches_each_denylisted_term(term: str) -> None:
    """Red-proof per term: bare, SCREAMING_CASE, and snake_case-compound
    spellings must all trip the scan (the identifier-aware boundaries exist
    for the compound forms, which `\\b` would miss)."""
    for sample in (
        term,
        term.upper(),
        f"max_{term}_charges = 3",
        f"{term.upper()}_DEFENSE = 0.5",
    ):
        assert _FORBIDDEN_VOCABULARY.search(sample), sample


@pytest.mark.parametrize(
    "benign",
    [
        "gda-balancing",  # the package's own name
        "gda_balancing.dispatch",
        "unrealistic growth curves",  # `unreal` bounded by letters
        "bundle size",  # `bun` bounded by letters
        "pickup_radius = 2.5",  # genre-generic mechanics stay legal
        "boss_encounter waves",
        "gravity_scale",
        "over-time effects tick each period",  # bare `time` is not identity
    ],
)
def test_vocabulary_gate_allows_family_and_genre_generic_speech(benign: str) -> None:
    assert not _FORBIDDEN_VOCABULARY.search(benign), benign
