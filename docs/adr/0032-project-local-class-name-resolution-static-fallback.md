---
status: accepted
---

# Project-local `class_name` resolution: a gda-owned static scan as a cache-independent fallback

#342 gave `node add --type <class_name>` and `resource create --type <class_name>` the ability to
resolve a **project-local GDScript `class_name`**, resolving it through
`ProjectSettings.get_global_class_list()`. That list is populated **only** by the Godot editor scan,
written into `.godot/global_script_class_cache.cfg`. But gda's core target is a
[Headless operation](../../CONTEXT.md) on a headless, **editor-never-opened** [Trusted project](../../CONTEXT.md)
— which has no `.godot/`, so the global class list is **empty** and #342's support is unreachable in
exactly the workflow gda positions itself for (surfaced dogfooding Panda Adventure S1, #359/#360).
Three call sites share this single dependency: node instantiation (`_instantiate_node_type`), resource
instantiation (`_instantiate_resource_type`), and `find-references`' `class_name → script path`
resolution (#116). The one-shot editor-scan workaround (`godot --headless --editor --quit`) confirms
the mechanism but is not a workflow gda can adopt on the agent's behalf.

## Decision

gda resolves a project-local `class_name` through **one unified resolver**, shared by all three call
sites, as a **three-tier chain**:

1. a **built-in engine class** (`ClassDB.can_instantiate`, base-class-checked) — unchanged;
2. the **editor global class list** (`get_global_class_list`) — the existing cache, kept **first** so
   an editor-opened project resolves exactly as it does today;
3. a **gda-owned static scan** of the project's own `.gd` sources — invoked **only when tiers 1–2 do
   not resolve** the type.

The static scan is a **cache-independent fallback**, not a replacement (cache-first). It walks the
full `res://` tree **skipping `.godot/`** (reusing the existing recursive walker), parses each `.gd`'s
`class_name` declaration with the existing **raw-source** parser (`_parse_script_meta`, the same
never-compiled parse `script get` / `find-references` already use), and builds a `class_name → script
path` index once per process run. Resolution stays a **static text scan**; the subsequent
instantiation (and the Node-vs-Resource base-class check) remains **split per site** — only the
`class_name → path` resolution is unified.

> **Amendment (2026-08-28, #712) — the scan's boundary is the ROOT cache PATH, not the directory
> name.** "Skipping `.godot/`" above was implemented as a directory-NAME test, which also excluded
> every `.godot` deeper in the tree. #712 replaced that, in all four `res://` collectors at once,
> with a lexical comparison of the child's path against `res://.godot`, owned by a single predicate
> (`_should_descend` in `operations.gd`) so the four cannot drift apart again — three of them
> disagreed with the fourth, and one project answered two ways: `script list` named a `.gd` whose
> `class_name` this index could not resolve. For this ADR the boundary is now: the index covers a
> `.gd` under a **nested** `.godot`, so its `class_name` resolves at all three call sites, and a
> declaration there can make a name `ambiguous_class_name` that was unambiguous before. The trade
> is accepted deliberately — a nested `.godot` is usually authored content (an addon vendoring a
> sample tree), and nothing in the path distinguishes it from a vendored sub-project's own engine
> cache, whose scripts then enter the index too. The comparison being lexical, it does not resolve
> filesystem targets: an alias that leads to `res://.godot` is walked and the cache's own scripts
> are indexed through it. Symlink policy for the `res://` walk is undecided and tracked separately;
> it is not decided here.

**Explicit contract edges:**

- **Duplicate `class_name`** (declared in more than one `.gd`) is **ambiguous and rejected** with a
  new [Operation-reported error code](../../CONTEXT.md) `ambiguous_class_name` naming the conflicting
  script paths — never a nondeterministic "first file wins", which would mask a real project error
  (the editor reports the same conflict) and depend on traversal order.
- **A type that resolves through none of the three tiers** stays the existing `invalid_node_type` /
  `invalid_resource_type`, but with the message **upgraded to be actionable** — it names the
  missing-class cause (a misspelled name, or a class not declared in a `.gd`) and **no longer implies
  the missing editor cache as the root cause** (the static scan removed that precondition). This is
  the retained, defense-in-depth part of the "document + better error" option.
- **`find-references`** shares the identical resolver and the identical `ambiguous_class_name`
  semantics, so `find-references Foo` and `resource create --type Foo` agree on whether `Foo` resolves
  in a never-opened project.

**Scope:** `.gd` only. A `class_name` declared in C# (`.cs`) is **out of scope** (consistent with
gda's existing boundary); its resolution would need a different mechanism and is not admitted here.

## Considered options

- **Trigger an editor class-list scan** (`godot --headless --editor --quit`) before the lookup —
  **rejected.** It introduces an `--editor` launch shape gda does not have (breaking the
  [Headless operation](../../CONTEXT.md) / Headless-launch model of ADR-0010), **writes `.godot/`
  into the Trusted project** as a side effect (a future hazard against a Concurrent external editor,
  ADR-0018), and is slow and fragile under headless/CI (a full editor boot + import that can fail on
  missing assets).
- **Document + actionable error only** — **rejected as the sole fix.** It leaves gda's core
  positioning scenario (headless, editor-never-opened) broken. Retained only as the tier-3-miss error
  message above.
- **Make the static scan authoritative** (always scan, override the cache for freshness) —
  **rejected.** It changes behavior for editor-opened projects (regression surface) and discards the
  cache's coverage of forms a text scan may miss; a cache-first fallback is unobservable for
  editor-opened projects. The known edge — a **stale** cache that resolves a since-renamed class —
  stays consistent with today's behavior rather than introducing a new inconsistency, and is judged
  not worth the merge-and-freshness complexity.
- **First-file-wins on a duplicate `class_name`** — **rejected** (see the contract edge above).

## Consequences

- **The resolver stays a pure [Headless operation](../../CONTEXT.md)** — no pre-existing engine
  state, no editor launch, no write into the project — consistent with ADR-0010, and it **removes the
  hidden editor-cache precondition** from the three sites for the headless workflow.
- **The [Project-code execution surface](../../CONTEXT.md) (ADR-0009) is unchanged.** The static scan
  **runs no project code** (it parses raw source, exactly like `script get` / `find-references`); only
  the subsequent instantiation runs a script's `_init`, which #342 already does. No new trust axis.
- **Backward compatible.** An editor-opened project resolves via the cache exactly as before; the
  fallback is unobservable there.
- **New shared [Gda error code](../../CONTEXT.md)** `ambiguous_class_name` (Operation-reported),
  emitted uniformly by `node add`, `resource create`, and `find-references`.
- **Consistency restored** across the three sites: they now agree on `class_name` resolution in a
  never-opened project, rather than `find-references` reporting "no such class" while a repaired
  `resource create` resolves it.
- **Scan boundary (amended 2026-08-28, #712).** What the scan skips is the root cache **path**, not
  every directory named `.godot` — see the Decision amendment for the boundary, the accepted
  nested-cache trade, and the open symlink question.
- **Cost.** A never-opened-project miss walks the whole `res://` tree and parses every `.gd`; this is
  acceptable for one-shot ops and is **not** backed by a persistent gda-owned cache — a gda-owned
  cache would re-introduce the very ".godot ownership" complexity the editor-scan option was rejected
  for.
