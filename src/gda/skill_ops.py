"""The ``gda skill`` operation: emit or install the bundled Agent Skill (ADR-0024).

``gda skill`` is a pure emitter meta command — no Godot is spawned. The canonical
``SKILL.md`` ships *inside* the ``gda`` package (under ``skill/``), resolved by a
package-relative path the same way the GDScript payload is (``gda.runner``), so the
guidance is shipped in the wheel and stays version-locked to the installed CLI: the
``version`` is read from ``importlib.metadata`` so the manifest and the commands it
describes are one distribution and cannot skew (ADR-0024, mirroring ADR-0013).
"""

from importlib.metadata import version as package_version
from pathlib import Path

from gda.models import SkillResult

# The bundled Skill manifest, resolved package-relative (NOT importlib.resources)
# so it works the same in a source checkout and an installed wheel — the same
# pattern ``gda.runner.OPERATIONS_GD`` uses for the GDScript payload.
SKILL_MD = Path(__file__).parent / "skill" / "SKILL.md"

# The default skills directory a ``--install`` writes into. Agent-specific (Claude
# Code's layout); the manifest content itself stays agent-neutral (ADR-0024).
DEFAULT_INSTALL_DIR = Path("~/.claude/skills/gda")


def read_skill_text() -> str:
    """Return the bundled ``SKILL.md`` text."""
    return SKILL_MD.read_text(encoding="utf-8")


def build_skill_result(
    *, install: bool = False, install_dir: str | None = None
) -> SkillResult:
    """Build the ``gda skill`` result, optionally installing the manifest.

    The plain (non-install) result carries the manifest identity — ``name``, the
    installed ``gda`` ``version`` (so the guidance is version-locked, ADR-0024), and
    the full ``content``. On ``install`` the bundled ``SKILL.md`` is written to
    ``<install_dir>/SKILL.md`` (parents created, overwrite is fine), and the written
    path is reported on ``installed_path``; ``install_dir`` defaults to
    ``~/.claude/skills/gda``. ``~`` is expanded so a tilde path resolves.
    """
    content = read_skill_text()
    result = SkillResult(
        name="gda",
        version=package_version("gda"),
        content=content,
    )
    if not install:
        return result
    target_dir = Path(install_dir).expanduser() if install_dir else DEFAULT_INSTALL_DIR.expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    target.write_text(content, encoding="utf-8")
    return result.model_copy(update={"installed_path": target})
