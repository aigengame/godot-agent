# gda-balancing

Game numeric design & balancing toolkit — design a game's numbers before development
(Standard Schema attribute/build/growth/economy templates for the RPG and Roguelike
families), validate and tune balance quantitatively during it (Monte-Carlo + system-dynamics
simulation, metrics and weighted scoring), and emit the result as structured,
Standard Schema JSON.

A standalone, engine- and game-agnostic sibling product of `gda` — it neither depends on nor
extends `gda`; its CLI follows the family's interface conventions.

- Requirements: [PRD #501](https://github.com/aigengame/godot-agent/issues/501)
- Milestones: [Phase 1 — Schema 2.0 language & model foundation](https://github.com/aigengame/godot-agent/milestone/8) ·
  [Phase 2 — runtime, evidence & genre closure](https://github.com/aigengame/godot-agent/milestone/9)
- Status: Phase 1's permanent Schema 2.0 surface includes the Kernel/LDB authority, command
  discovery, one typed-Quantity Model build, and one minimal Template release. Phase 2 includes a bounded deterministic
  multi-Event Experiment Runtime and RPG and Roguelike product-feedback examples; evidence and
  complete RPG/Roguelike Template closure remain ahead. The package is **not published to PyPI
  yet**.

The [current-language refactor](docs/refactor/current-language/PLAN.md) removes internal release
history, version selection and unnecessary execution bindings while retaining the typed language,
compiler and deterministic Runtime. Internal definitions may be changed or withdrawn; formal
compatibility will be considered no earlier than toolkit v1.0. The commands below describe the
current implementation. The Schema 1 converter, `model migrate` command and `tooling.migration`
package are retired; use current Model Source directly. The [retirement record](docs/refactor/current-language/RETIREMENT.md)
documents source disposition and validation boundaries. See [bADR-0028](docs/badr/0028-current-language-refactor-and-pre-1.0-retirement.md)
for the accepted direction and its distinction from completed implementation.

## Commands

```bash
gda-balancing schema get language-bundle   # admitted Kernel/LDB authority pair
gda-balancing schema get wire-schema       # exact generated wire-schema projection
gda-balancing schema get diagnostic-catalog # exact generated Diagnostic projection
gda-balancing formula parse <source>       # parse notation into a canonical Formula pair
gda-balancing formula render <source>      # render a structured body as canonical notation
gda-balancing model check <source>         # admit a Schema 2.0 Model Source
gda-balancing model build <source> [...]   # build and atomically publish a Model
gda-balancing model inspect <receipt> [...] # render a stored Model explanation
gda-balancing experiment check <source>    # admit an exact Experiment without running it
gda-balancing experiment run <source> [...] # run and atomically publish evaluation artifacts
gda-balancing template list                # list admitted Template releases
gda-balancing template get [...]           # retrieve an exact Template release
gda-balancing template instantiate [...]   # publish a new editable Model Source
gda-balancing serve [--host 127.0.0.1] [--port 0] # run the local HTTP execution service
gda-balancing manifest                     # live Schema 2.0 command surface
gda-balancing version                      # toolkit version + supported Schema line
```

Every command emits one JSON document: the typed result on stdout at exit 0, or an error
envelope — `refusal` (exit 2, on stdout), `usage` (exit 3) or `internal` (exit 4). Add
`--schema` to any command for its closed input/result/error contract, or `--out <path>` to an
artifact-emitting command to write the artifact to a file and get a receipt on stdout. Every
Schema 2.0 command also accepts `--params-json <json | ->`; `-` reads the same descriptor-owned
input object from stdin, and structured input is mutually exclusive with individual argv fields.
There is no Schema 1 input entrypoint or compatibility adapter. Author or deliberately rewrite
source as a current Model Source Package, then use normal `model check` and `model build`.

Unlike the one-shot commands, `serve` stays in the foreground. It binds only to a numeric loopback
address. It prints one readiness document with its local URL and process capability, and then keeps
stdout silent. The owning local application uses the capability on every `/v1/*` request. It calls
the authenticated shutdown route when it finishes. See
[bADR-0026](docs/badr/0026-local-http-execution-service.md) for the execution-session protocol and
its authority boundaries.

## Examples

- [Reciprocal RPG combat](examples/schema2/rpg-combat-cast/README.md) — two same-time directional
  roots, committed-Snapshot visibility, explicit cancellation and Formula tuning.
- [Periodic RPG Effect](examples/schema2/rpg-periodic-effect/README.md) — snapshot/live Formula
  timing, scheduled tick/tick/expire Events, same-time combat ordering and Formula rebinding.
- [Progression-derived periodic Effect](examples/schema2/progression-periodic-effect/README.md) —
  a progression Formula supplies the periodic threshold through the ordinary Model/Experiment path.
- [Seeded Roguelike reward and build tuning](examples/schema2/roguelike-reward-build/README.md) —
  ordered reward selection, a Named random stream, one-value tuning, atomic replacement, and
  Discriminated gameplay outcomes.

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
The admitted-authority fixture boundary, logical inventory gate, CI shards, and full-suite
latency guidance are documented in
[`docs/agents/testing.md`](docs/agents/testing.md).

Design decisions live in [`docs/badr/`](docs/badr) (balancing ADRs) and the domain glossary
in [`BALANCING-CONTEXT.md`](BALANCING-CONTEXT.md).
