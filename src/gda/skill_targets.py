"""Known per-agent skills directories for ``gda skill --install --provider`` (ADR-0027).

ADR-0024 kept agent-specific install paths *out of core*: a plain ``gda skill`` and a
bare ``--install`` carry no default location, and ``--dir`` is the neutral escape hatch.
ADR-0027 **extends** that with an explicit opt-in — when the caller NAMES a ``--provider``,
``gda`` resolves a known skills directory for it. The default (no provider) still has no
built-in path, the ``SKILL.md`` content stays agent-neutral, and ``--dir`` remains the
general override, so ADR-0024's "the default is neutral" principle is preserved while the
named-provider path is merely a convenience.

This module is the single home of that vendor knowledge: which agents are known and where
each loads skills, by scope. The directories follow each agent's documented convention —
Claude Code's ``.claude/skills/``, and the cross-agent Agent Skills namespace
``.agents/skills/`` that Codex (per OpenAI's Codex docs) and other agents scan. The leaf
``gda/`` is the skill's own directory (``<base>/gda/SKILL.md``), the layout
``docs/gda-skill.md`` documents. The table is best-effort and may lag an agent's upstream
change; ``--dir`` is always the fallback when a path is wrong or an agent is not listed here.
"""

from enum import Enum


class SkillProvider(str, Enum):
    """A known agent whose skills directory ``gda skill --install`` can target (ADR-0027).

    A closed set, so an unknown ``--provider`` is a usage error rather than a guess; an
    agent not listed here is still served by the neutral ``--dir`` path (ADR-0024).
    """

    CLAUDE = "claude"
    CODEX = "codex"


class SkillScope(str, Enum):
    """Where a skill is installed: per-project (committed) or per-user (all projects).

    Agent-neutral — it only chooses between an agent's project-local skills directory
    (resolved against the current directory) and its user-level one (under ``$HOME``).
    """

    PROJECT = "project"
    USER = "user"


# The known per-agent skills directories, by scope. Each value is the install BASE dir
# with the skill's own ``gda/`` leaf already appended, so the written file is
# ``<value>/SKILL.md`` (the layout docs/gda-skill.md documents). Project paths are
# relative (resolved against the CWD); user paths use ``~`` (expanded by the install).
# Vendor-specific by design and kept to this one module (ADR-0027) so core logic and the
# SKILL.md content stay agent-neutral. Codex follows the cross-agent ``.agents/skills``
# namespace per OpenAI's Codex docs, NOT ``.codex/skills``.
PROVIDER_SKILL_DIRS: dict[SkillProvider, dict[SkillScope, str]] = {
    SkillProvider.CLAUDE: {
        SkillScope.PROJECT: ".claude/skills/gda",
        SkillScope.USER: "~/.claude/skills/gda",
    },
    SkillProvider.CODEX: {
        SkillScope.PROJECT: ".agents/skills/gda",
        SkillScope.USER: "~/.agents/skills/gda",
    },
}


def resolve_skill_dir(provider: SkillProvider, scope: SkillScope) -> str:
    """Return the known install directory for ``provider`` at ``scope`` (ADR-0027).

    The returned path is the install BASE (with the ``gda/`` leaf), suitable as
    ``SkillParams.install_dir``; the existing install path expands ``~`` and writes
    ``<dir>/SKILL.md``. Every ``SkillProvider`` × ``SkillScope`` pair is present, so this
    never raises for a valid enum pair.
    """
    return PROVIDER_SKILL_DIRS[provider][scope]
