---
status: accepted
---

# The Skills CLI installs the gda skill from a repository-root container

ADR-0024 ships the `gda skill`'s `SKILL.md` inside the `gda` package, where the `gda skill`
command emits it version-locked to the installed CLI, and makes the same file under the
package directory the drop-in that a user copies from the repository. To make the skill
easier to find, install and update, the maintainer chose the Skills CLI
(`vercel-labs/skills`, run as `npx skills add`) as the first install channel (#1126):

```bash
npx skills add aigengame/godot-agent --skill gda        # project scope
npx skills add aigengame/godot-agent --skill gda -g     # user scope
```

Skills CLI 1.5.10 finds a skill in a repository in two ways. First it searches root
containers: `skills/`, `skills/.curated/`, `.agents/skills/`, `.claude/skills/` and the
skills directory of each agent it supports. Only when no container holds a skill does it
search the whole tree. `--full-depth` and a subpath in the source change this, but the
command above uses neither. A source can also name a git ref (`<source>#<ref>`). The CLI
records that ref in its lock file, and `skills check` and `skills update` read the same ref.
A source with no ref, like the command above, installs from the default branch, and the
update checks read the default branch.

The Agent Skills specification requires the frontmatter `name` to equal the name of the
skill's directory. The package directory is `src/gda/skill/`, and the name is `gda`.

The build backend is uv_build. It packages one module, `src/gda`, and has no wheel
includes, so the wheel cannot carry a file from outside the module.

Probes on mock repositories, with Skills CLI 1.5.10 and uv 0.11.19:

| Layout | Result |
| --- | --- |
| `src/skills/gda/` only, or `src/gda/skill/` only | Each is listed, by the whole-tree search. |
| A skill in `skills/other/` at the root, plus `src/skills/gda/` | Only `other` is listed. |
| `src/skills/gda/`, plus a link to it at `src/gda/skill/SKILL.md` | One `gda` is listed, but the install copied the link's directory `src/gda/skill/`: a marker file placed there was copied, and the lock hash was the SHA-256 of empty input. |
| `skills/gda/` at the root, plus a link to it at `src/gda/skill/SKILL.md` | The CLI installed from the root directory. The lock hash was not the hash of empty input. |
| uv_build, a link in the module to a file outside it | The sdist, the wheel built from the sdist, and the wheel built from the tree each hold a regular file with the target's bytes. |

## Decision

**The authored file is `skills/gda/SKILL.md`.** It sits in the root container that the
Skills CLI searches first, and its directory name equals the frontmatter `name`. It is
the only authored copy of the skill.

**The package path is a link.** `src/gda/skill/SKILL.md` is a relative symbolic link to
`../../../skills/gda/SKILL.md`. uv_build writes the linked bytes as a regular file into
the sdist and the wheel, so an installed `gda` carries the same file as before and the
`gda skill` lookup does not change. Tests hold the link to its purpose: the bytes at the
package path, and the bytes of the wheel member, equal the authored file, and the
frontmatter `name` equals the authored file's directory name.

**Two channels, two version rules.** The documented Skills CLI source names no ref, so
it installs from the default branch and its update checks read that branch. So it tracks
`main`, as the earlier copy-from-the-repository drop-in did. `gda skill` stays the version-locked
channel of ADR-0024, and needs no Node.js. The documentation names the Skills CLI first
and `gda skill` for guidance that matches the installed `gda`.

## Considered options

- **`src/skills/gda/SKILL.md` (the first proposal).** Rejected. It is outside every root
  container, so the CLI finds it only by the whole-tree search. That search stops when any
  root container holds a skill. With the package link beside it, the probe installed the
  link's directory instead of the skill's.
- **Keep the authored file at `src/gda/skill/SKILL.md`.** Rejected. The directory name
  `skill` does not equal the name `gda`, and the CLI finds the file only by the whole-tree
  search.
- **Two copies, held equal by a test.** Rejected. A second authored copy is a sync duty
  that the link removes.
- **Package `skills/` with a build-backend include.** Rejected. uv_build has no wheel
  includes; a different backend is a larger decision than this channel.
- **Tag-pinned install sources** (`aigengame/godot-agent#vX.Y.Z`). Not documented. The
  update checks read the recorded tag, so they find no change, and a user who upgrades
  `gda` must add the skill again with the new tag. `gda skill` already gives the
  version-locked copy in one step.

## Consequences

- A checkout with `core.symlinks=false`, which `git clone` can set on Windows, writes the
  link target as text at the package path. `gda skill` from an editable install of that
  checkout prints the path, and the byte-equality test fails with a message that names
  `core.symlinks`. `PITFALLS.md` has the entry. Published artifacts are built on Linux
  runners, so a package from PyPI carries the file.
- The repository path `src/gda/skill/SKILL.md` is now a link, so the old raw URL under it
  does not serve the guidance. The documentation uses the new path.
- `gda skill --install --provider <agent>` (ADR-0027) and the Skills CLI can write the
  same agent skills directory. The last write wins; the two channels do not know of each
  other.
- `gda skill`, its `--json` result and its schema do not change. The `gda skill`
  description no longer calls the package file "canonical".
