---
status: accepted
---

# gda-authored scenes and resources reference by `res://` path, not `uid://` (read-uid / write-path asymmetry)

gda authors `.tscn`/`.tres` files by driving Godot's own `ResourceSaver` inside a
`godot --headless` process — a [Headless operation](../../CONTEXT.md) on an
editor-never-opened [Trusted project](../../CONTEXT.md). Godot 4's **Resource UID**
system (`uid://…`) exists to *"maintain references between resources, even when files
are renamed or moved"*: a stable id mapped to a `res://` path through the
editor-generated, machine-local `.godot/uid_cache.bin`. The Godot editor writes a
`uid="uid://…"` onto every `[gd_scene]`/`[gd_resource]` header and every
`ext_resource` line, and regenerates the local `1_…` ids from its live UID registry.

gda-authored files carry **none of this**: bare `[gd_scene format=3]` headers,
`ext_resource` referenced by `path` + a local `id`, no `uid://` anywhere. This was an
**unstated, emergent property** — never a recorded decision — and the question surfaced
dogfooding Panda Adventure (the human-GUI-coexistence question raised during the v0.8.0
`game set --verified` verification session): should gda "align" its output to the
editor's uid-ized form?

Two facts settle it:

- **UID assignment is editor-only.** Per Godot's `ResourceSaver.save` contract: *"When
  the project is running, any generated UID associated with the resource will not be
  saved as the required code is only executed in editor mode."* A headless gda process
  has no live UID registry, so its `ResourceSaver` emits path-only references **by
  construction**. Emitting editor-equivalent uids would require gda to reimplement the
  editor's UID allocator headlessly — and the synthesized values still would not match
  any given machine's editor-generated ones. This is the same editor-only-state gap
  [ADR-0032](0032-project-local-class-name-resolution-static-fallback.md) hit with
  `.godot/global_script_class_cache.cfg` (also `.godot/`, also editor-scan-only): gda's
  target has no `.godot/`, so it cannot and should not depend on it.
- **`uid://` is optional for loading; the path always resolves.** Godot's text loader
  loads every `ext_resource` **by path**, and when a `uid` is absent, invalid, or
  unregistered it falls back to the text path (with, at most, a `WARN_PRINT` for a
  *stale* uid — never for a *missing* one). A uid-free file therefore loads, runs, and
  exports identically and with **zero warnings**.

## Decision

Ratify path-based emission as the intentional authoring contract, structured as a
deliberate **read-uid / write-path asymmetry**:

- **Write side — reference by `res://` path, never `uid://`.** gda-authored scenes and
  resources reference their dependencies by `res://` path plus a local `id`, and carry
  no `uid` on their headers. This extends the same "name an external resource by its
  `res://` path" principle already chosen on the write side for Object-typed property
  values in [ADR-0033](0033-object-typed-property-assignment-via-resource-reference.md).
- **Read side — accept and resolve `uid://` as a first-class input.** Consuming a uid is
  not the same as emitting one, and gda stays a full uid *consumer*: it validates
  `uid://` inputs (`invalid_uid` / `unknown_uid` / `no_uid_assigned`,
  [ADR-0002](0002-headless-structured-output-contract.md)), resolves `uid://` as an
  engine virtual-path scheme ([ADR-0006](0006-project-context-and-path-resolution.md)),
  and takes `--scene <path|UID>` ([ADR-0017](0017-gda-daemon-live-execution-mechanism.md)).
  gda relies on 4.4+ UID *management* being present
  ([ADR-0003](0003-target-godot-version.md)) — it just does not *author* uids.

Rationale: the path-only form keeps the **committed text self-contained** (everything
needed to resolve a reference is in the file — no dependency on the gitignored,
machine-local `uid_cache.bin`) and **byte-deterministic** (identical headless output
every run → clean semantic diffs, working freshness gates, and the byte-for-byte
export restore of [ADR-0028](0028-harness-export-cleanliness.md)). Determinism and a
single self-contained source are core to gda's positioning as structured,
machine-reproducible authoring; a cache-backed, editor-only indirection layer would
trade exactly that away.

## Non-goals

- **We do not synthesize editor-equivalent uids headlessly.** They would not match any
  machine's GUI-generated values and would reintroduce non-determinism and a cache
  dependency — defeating the reason path-only was chosen.
- **We do not forbid or guard against a human opening the project in the Godot GUI.**
  Opening the project in the editor — to view, run, or verify agent output — is the
  user's autonomous choice, and a GUI *save* legitimately re-serializes to Godot's
  canonical uid-ized form. That coexistence is handled by **awareness and recovery, not
  enforcement**, consistent with the sole-driver stance of the parent trust model
  (ADR-0018 / the *Concurrent external editor* term in CONTEXT.md): a concurrent
  external editor's writes are *undefended*, not *prohibited*.

## Consequences

- **Interoperates fully.** Path-only files load, run, and export identically to uid-ized
  ones — the engine resolves `ext_resource` by path regardless — so there is no
  correctness or runtime cost, and no reason to "align" for functionality.
- **Trade-off: no editor rename/move-reference tracking** on gda-emitted files (the one
  thing `uid://` buys). In a gda workflow a rename is performed by a gda operation that
  rewrites the referring paths, or by hand — not by dragging in the editor's FileSystem
  dock — so this cost is largely moot.
- **Coexistence boundary.** If a human opens *and saves* a gda-authored scene in the
  Godot GUI, Godot adds `uid` headers and reshuffles the `ext_resource` ids, diverging
  from gda's deterministic form. This is **not a breakage** (the file still loads) but it
  creates diff churn and means gda's byte-determinism / freshness assumptions no longer
  hold for that file until it is re-authored. The operational handling — passive
  view/run touches only gitignored caches (`.godot/`, `*.uid`); recover an unwanted uid
  churn with `git checkout`; the gda-authored form is the source of truth — is documented
  where the exposure lives, in the Panda Adventure `AGENTS.md` "Development conventions".
- **Forward-looking.** Godot keeps investing in uid (4.4's `.gd.uid` script sidecars;
  ADR-0003 pins 4.4 as the UID-management floor). Path-only remains a first-class,
  fully-supported load path in 4.6 (`ResourceLoader.get_dependencies` still returns a
  uid **and** a fallback path; `ext_resource` still loads by path). Should a future Godot
  degrade path-only support, revisit — most likely via **deterministic, path-derived
  uids** (Godot already seeds sub-resource ids from `path.hash()` for reproducible
  saves), which would preserve reproducibility without a cache. No action today; watch
  the trajectory.
