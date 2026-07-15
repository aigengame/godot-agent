# gda-balancing

The shared language of gda-balancing: a standalone, engine- and game-agnostic toolkit for
designing a game's numerics before development and validating balance quantitatively during
it, with structured output suitable for programmatic consumption. (Requirements: PRD #501.)

## Language

### Product

**gda-balancing**:
The toolkit itself. The `gda-` prefix is the **product-family brand** — this is a sibling
product of `gda`, not a `gda` component (contrast `gda-mcp` / `gda-daemon`, which are gda's
own components). It neither depends on nor extends `gda`; its CLI *interface style* follows
gda's conventions (PRD #501 addendum).
_Avoid_: gda balancing module, balancing plugin

**Standard Schema**:
The machine-readable schema for game numeric systems (character attributes, combat, builds,
encounters, growth, economy) that is the toolkit's **sole spec and single authority source**.
The pipeline designs and configures numbers before game development; a game is then developed
consuming the pipeline's Schema-standard output. Non-standard game configs are not adapted or
imported.
_Avoid_: config format, data model, descriptor

**Genre template**:
A genre's numeric design baseline — default values plus formulas-as-data — shipped as an
*instance of the Standard Schema*, never as code paths. First families: RPG (CRPG/JRPG/ARPG)
and Roguelike (metroidvania-like, survivors-like, deckbuilder-like).
_Avoid_: preset, profile

**Reference fixture**:
A paper-game config per supported genre, living in the test suite as an executable consumer
and golden example — exercising template superset paths no live game exercises yet.
_Avoid_: sample project, demo config

### Simulation

**Evaluation method**:
A method that *estimates* balance metrics from a config — Monte-Carlo encounter estimation
and system-dynamics (first-order nonlinear ODE) long-horizon prediction. Distinct from a
`Tuning method`; Monte-Carlo is an estimation method, never an "exact algorithm".
_Avoid_: exact algorithm, precise algorithm

**Tuning method**:
A method that *searches* config space toward balance targets — parameter sensitivity
analysis first, then simple (greedy) search; stronger optimizers later. Delivery ordering is
simple-to-hard.
_Avoid_: approximation algorithm, auto-balancer

**Metrics schema**:
The one shape shared by simulated results and (future) observed playtest results, so the
playtest feedback loop can be wired later without schema rework — round-trip capable by
design; ingestion wiring is deferred until playtests produce real feedback.
_Avoid_: report format (as a separate shape)
