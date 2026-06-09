---
status: accepted
---

# CLI command taxonomy: grouped by Godot domain object

`gda` will grow to many commands. We need a command structure that stays navigable
at that scale, is intuitive to anyone who knows Godot, and maps cleanly onto
`gda-mcp`'s tool surface.

## Decision

Commands are **grouped**: `gda <group> <command> [options]`. Groups are **Godot
domain objects** — `scene`, `node`, `script`, `project`, `resource`, `export`, etc. —
and each command is an action on that object (e.g. `gda scene create`,
`gda node add`, `gda project info`). This mirrors both Godot's own conceptual model
and the taxonomy proven by `godot-mcp-pro`.

A small set of **top-level meta commands** — those about `gda` or the engine itself
rather than a Godot domain object — are exempt from grouping and sit at the top level:
`gda info`, `gda version`, `gda help`. This is the usual CLI pattern (`git --version`,
`docker info`). Everything that acts on a Godot domain object is grouped.

This enables:

- **Zero learning cost** for anyone who knows Godot — a group name *is* an engine
  concept.
- **Progressive disclosure** — `gda --help` lists groups, `gda <group> --help` lists
  that group's commands, and `gda <group> <command> --schema` (ADR-0004) gives the
  full machine-readable contract. An agent never has to load every tool definition
  upfront — the key advantage of a CLI surface over a fixed MCP tool list.
- **Deterministic `gda-mcp` naming** — `gda <group> <command>` maps mechanically to
  the MCP tool name `<group>_<command>` (e.g. `scene_create`), so the adapter is
  generated, not hand-written (ADR-0001, ADR-0004).

## Phases do not appear in the command tree

The headless/live distinction (Phase 1 / Phase 2) is a *delivery* dimension and must
not leak into the user-facing command structure. A headless command and a live
command on the same object (e.g. `gda scene create` vs a future live scene-inspect)
are siblings under the same `scene` group; the phase/operation kind is expressed in
each command's `--schema` metadata, not by splitting the tree.

## The command surface is delivered incrementally, not enumerated up front

The surface grows **one vertical slice at a time** (ADR-0000), not as a pre-declared
closed set. The full territory each group will eventually hold is tracked as a
**non-binding roadmap** in [`docs/command-catalog.md`](../command-catalog.md), seeded
from the `godot-mcp-pro` taxonomy and refined as we go. The catalog is a *map, not a
commitment*: a command becomes a commitment only when its slice is picked up as an
issue. This keeps the territory visible (for prioritisation and for agents) without
forcing big-design-up-front. Every command that ships does so self-describing
(`--schema`, ADR-0004) — a hard gate, no exceptions.

## Considered options

- **Grouped by domain object** (chosen) — navigable, intuitive, extensible, clean MCP
  mapping.
- **Flat `gda <verb-noun>`** (like `godot-mcp`, e.g. `gda create-scene`) — rejected;
  with many commands it becomes an unstructured, hard-to-discover, hard-to-extend
  list with no hierarchy.
- **Grouped by capability phase** (headless group / live group) — rejected; leaks the
  delivery dimension into the user surface and separates commands users think of as
  siblings.

## Naming conventions

**Casing.** All tokens — group names, command names, and multi-word flags — use
**kebab-case** (`gda input-map add`, `gda node add-child`, `--node-type`). The
deterministic CLI→MCP mapping is `<group> <command>` → `<group>_<command>` with
dashes converted to underscores (`gda input-map add` → MCP tool `input_map_add`),
since MCP tool names conventionally use underscores.

**Verb vocabulary.** A small, orthogonal set of verbs, used with the *same meaning in
every group* so an agent learns each once:

| Verb              | Meaning                                                    |
| ----------------- | --------------------------------------------------------- |
| `create`          | Make a new standalone entity (scene, script, resource)    |
| `delete`          | Delete a standalone entity                                 |
| `add`             | Add a child/sub-entity into a container (node→scene, track→animation) |
| `remove`          | Remove a sub-entity from a container                       |
| `get`             | Read a single entity's structured data                     |
| `list`            | Enumerate multiple entities                                |
| `set`             | Mutate a property                                          |
| domain verbs      | `play` / `stop` / `run` / `export` / `import`, etc. — non-CRUD actions kept with their natural meaning |

Two binding rules:

1. **`create`/`delete` operate on standalone entities; `add`/`remove` operate on
   sub-entities within a container.** This is a deliberate distinction, not redundant
   synonyms — it removes the create-vs-add and delete-vs-remove ambiguity seen in the
   reference implementations.
2. **A verb's meaning is constant across groups** — `get` always returns one entity's
   data, `list` always enumerates. Synonyms are avoided: `read` (use `get`), `update`
   / `edit` as a property verb (use `set`).

