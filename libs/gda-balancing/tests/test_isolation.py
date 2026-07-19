"""The game/engine-agnosticism isolation gate (#502, hardened standard).

The toolkit names no game identity and imports no game, engine, or `gda`
code; this gate is the single owner of that constraint, at the hardened
standard: recursive file collection and AST-level import walking (syntax-
aware, so lazy in-function imports and both `import X` / `from X import Y`
spellings are covered), a word-boundary vocabulary scan, and a stray
per-game-config scan.

This module is the package's sole sanctioned appearance of the forbidden
terms (adjudicated on #502): a denylist must name what it bans, and the gate
is where the constraint lives — so the vocabulary scan exempts exactly this
file and nothing else.
"""

import ast
import re
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PACKAGE_ROOT / "src" / "gda_balancing"
_TESTS_DIR = _PACKAGE_ROOT / "tests"
_GATE_FILE = Path(__file__).resolve()

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

# Engine identity, the engine's scripting language, the example game's
# identity, and its decision-record prefix. Deliberately NOT a bare `gda`
# word: it is a substring of this package's own name (`gda-balancing`), and
# the import gate above already owns the import axis.
_FORBIDDEN_VOCABULARY = re.compile(r"\b(godot|gdscript|panda|gadr)\b", re.IGNORECASE)


def _python_sources() -> list[Path]:
    files = [
        path
        for base in (_SRC_DIR, _TESTS_DIR)
        for path in sorted(base.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    assert files, f"isolation gate found no sources under {_PACKAGE_ROOT}"
    return files


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
    for path in _python_sources():
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
    stray = [
        str(path.relative_to(_PACKAGE_ROOT))
        for path in sorted(_SRC_DIR.rglob("*.json"))
    ]
    assert not stray, "per-game config files inside the toolkit:\n" + "\n".join(stray)
