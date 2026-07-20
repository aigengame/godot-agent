# gda-balancing

Game numeric design & balancing toolkit — design a game's numbers before development
(Standard Schema attribute/build/growth/economy templates for the RPG and Roguelike
families), validate and tune balance quantitatively during it (Monte-Carlo + system-dynamics
simulation, metrics and weighted scoring), and emit the result as structured,
Standard Schema JSON.

A standalone, engine- and game-agnostic sibling product of `gda` — it neither depends on nor
extends `gda`; its CLI follows the family's interface conventions.

- Requirements: [PRD #501](https://github.com/aigengame/godot-agent/issues/501)
- Milestones: [Phase 1 — numeric design & config templates](https://github.com/aigengame/godot-agent/milestone/8) ·
  [Phase 2 — balance simulation](https://github.com/aigengame/godot-agent/milestone/9)
- Status: Phase 1 in progress. The Standard Schema core ships — a Design document validates
  through the boundary funnel, round-trips as canonical JSON, and the schema describes
  itself — and the first Genre template (the RPG family) ships behind `template list`/`get`.
  Further templates, evaluation, and tuning are still ahead; the package is **not
  published to PyPI yet**.

## Commands

```bash
gda-balancing design validate <document>   # validate through the boundary funnel
gda-balancing design format <document>     # emit the validated document, canonically
gda-balancing template list                # the shipped Genre templates
gda-balancing template get rpg             # emit a Genre template as a Design document
gda-balancing schema get structural        # the JSON Schema 2020-12 artifact
gda-balancing schema get catalog           # the semantic rule catalog
gda-balancing version                      # package version + supported Schema line
```

To start a game's numeric design from a template, instantiate it —
`template get rpg --out my_design.json` — then name your game in `meta`, adjust the
`parameters`, and keep `design validate` green as you iterate. The RPG template's tiers,
defaults, and formulas are documented in [`docs/templates/rpg.md`](docs/templates/rpg.md).

Every command emits one JSON document: the typed result on stdout at exit 0, or an error
envelope — `refusal` (exit 2, on stdout), `usage` (exit 3) or `internal` (exit 4). Add
`--schema` to any command for its input/output/error contract, or `--out <path>` to an
artifact-emitting command to write the artifact to a file and get a receipt on stdout.

## Development

This is an **independent uv project**, not a workspace member of the repo root
([ADR-0038](../../docs/adr/0038-gda-balancing-leaves-the-uv-workspace.md)) — it locks and
resolves on its own, so every command needs `--project` when run from the repo root:

```bash
uv sync --project libs/gda-balancing                              # set up its environment
uv run --project libs/gda-balancing pytest libs/gda-balancing/tests
uv run --project libs/gda-balancing pyright --project libs/gda-balancing
uv build --project libs/gda-balancing                             # sdist + wheel
```

From inside `libs/gda-balancing/` the `--project` flag is unnecessary (`uv sync`,
`uv run pytest`, …). Linting and formatting stay repo-wide from the root:
`uv run ruff check .` / `uv run ruff format .`.

The suite is fast and needs no game engine — the toolkit is engine- and game-agnostic, and
an isolation gate in the suite enforces that. Its e2e tier drives the installed console
script as a real subprocess, which is why the test commands above run through `--project`:
that is what puts `gda-balancing` on `PATH`.

Design decisions live in [`docs/badr/`](docs/badr) (balancing ADRs) and the domain glossary
in [`BALANCING-CONTEXT.md`](BALANCING-CONTEXT.md).
