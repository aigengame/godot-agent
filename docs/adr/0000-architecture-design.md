---
status: accepted
---

# Architecture: an agent-facing Godot toolchain, built bottom-up

## Context

Agents need a Godot operations interface with structured output suitable for
programmatic consumption — both a CLI and an MCP server.

Godot ships a `godot --headless` command line, but it is not agent-facing and emits
no structured output. The existing Godot MCP repositories (see the "reference repos"
section of `RULES.md`) implement an MCP server but provide no CLI, and fall short on
completeness, performance, and state consistency.

## Decision

godot-agent (`gda`) implements an agent-facing Godot CLI and MCP that aim to be
complete, performant, and state-consistent. The system is built **bottom-up, from
simpler to more complex**, in this component order:

- **`gda`** — the CLI. Covers the full set of Godot operations and emits structured
  output (`--json`, `--schema`). It is standalone, depends on no service, and is the
  bottom layer and the entry point for automation.
- **`gda-mcp`** — a thin protocol adapter that wraps `gda` to expose its capabilities
  as an MCP server.
- **`gda-daemon`** — because `gda` and `gda-mcp` calls are stateless, a long-lived
  `gda-daemon` provides a persistent, state-consistent `gda` for both performance and
  capability reasons.

> Refined by ADR-0001: the daemon's role is reframed there from an optional
> performance layer into the necessary carrier of all live-engine capabilities, and
> delivery is split into Phase 1 (headless) and Phase 2 (live).

## Development conventions

- Incremental development driven by **vertical slices** and **TDD**:
  - A vertical slice is the smallest demoable, runnable unit that cuts through all
    layers.
  - TDD proceeds through Red → Green → Refactor iterations.
- Every issue (requirement, feature, bug) closes the loop through the issue tracker.

## Technical constraints

- Python (3.13) stack.
