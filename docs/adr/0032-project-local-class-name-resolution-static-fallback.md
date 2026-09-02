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
> cache, whose scripts then enter the index too. The comparison being lexical, it did not resolve
> filesystem targets: an alias that leads to `res://.godot` was walked and the cache's own scripts
> were indexed through it. Symlink policy for the `res://` walk was undecided and tracked in #760.

> **Amendment (2026-08-31, #760) — the boundary is the cache's filesystem IDENTITY, not its
> spelling.** #760 decided the symlink policy the amendment above left open, for the whole `res://`
> walk and therefore for this index. The walk follows a link as the engine does, but identifies what
> it reaches with the engine's own `DirAccess.is_equivalent`, so the cache is excluded however it is
> aliased — a directory link at it, a directory link into one of its subdirectories, or a file link
> at a file inside it — and a link that leads back up the descent chain is not re-entered, so a
> symlink cycle no longer floods the index with paths that name one script many times. For this ADR
> the boundary is now: a `class_name` declared in a script inside the ROOT engine cache does not
> resolve, whatever path reaches it (the #760 repro resolved `RootCacheThing` through an alias); a
> `class_name` under a NESTED `.godot`, or in a vendored checkout reached through a link, still
> resolves — for ENUMERATION and this index. Whether that same file may be NAMED as an operation's
> target is a different question, owned by ADR-0006's addressing gate rather than by this ADR: the
> walk decides what the project can address by filesystem identity, the gate decides what a caller
> may operate on from the caller's own spelling. A file link at an authored script is indexed under
> both its paths, so a `class_name` it declares is `ambiguous_class_name` — the same report this ADR
> already gives a name declared in two files. The full rule and its rationale live with the walk, in
> `docs/command-catalog.md`'s exclusion passage.

> **Amendment (2026-09-02, #804) — the walk skips what the ENGINE's scan skips, which
> REVERSES the vendored-tree trade above.** #804 aligned the shared `res://` walk with
> `EditorFileSystem::_should_skip_directory` (`editor/file_system/editor_file_system.cpp`,
> 4.6.3-stable): besides the project data path, the engine skips a directory holding a
> `project.godot` — another project inside this one — and a directory holding a
> `.gdignore`. Its trigger was `script validate --all` compiling a nested project's
> scripts against the OUTER root (ADR-0006's closed gap), but the change is the walk's, so
> this index changes with it. **For this ADR the boundary is now:** a `class_name` declared
> under a nested `project.godot` or under a `.gdignore`d directory **does not resolve** at
> any of the three call sites, and a name that was `ambiguous_class_name` **only** because
> a vendored sub-project declared it a second time is now unambiguous and resolves to the
> outer project's declaration.
>
> That is a **deliberate reversal**, not a side effect. The two amendments above accepted
> a vendored tree's scripts into the index — #712 chose to walk a nested `.godot` because
> it is usually authored content, and #760 kept a checkout reached through a link
> enumerable — on the reasoning that gda cannot tell a vendored sample tree from a real
> sub-project. A `project.godot` **is** that missing distinction: the sub-project declares
> itself, and its scripts' own `res://` references mean ITS root, so resolving one of its
> `class_name`s here would instantiate a script against the wrong root — the same wrong
> answer ADR-0006's ownership gate refuses when such a file is NAMED. A `.gdignore` is the
> project's own instruction not to scan. The narrower trade the earlier amendments made is
> therefore superseded exactly where a marker is present, and nowhere else: a vendored tree
> WITHOUT either marker, including one reached through a symlink, is still walked and still
> indexed, as #712 and #760 decided.
>
> **A second, unplanned reversal: the nested CACHE (recorded 2026-09-02, #808 review).**
> #712 accepted one named cost — a vendored sub-project's own engine cache counting in
> `project statistics`, becoming a `find-unused-resources` candidate, and its scripts
> entering this index — because nothing in the PATH tells an engine cache from authored
> content. The CONTENT does, and #804's `.gdignore` clause reads it: every engine that
> creates a project data directory writes a `.gdignore` INTO it (`EditorPaths::create`,
> `editor/file_system/editor_paths.cpp:268-277`; `EditorNode` does the same, and gda's own
> `resource import` pass reports `res://.godot/.gdignore` in `created`). So a nested cache
> that any engine produced — the case #712 named, "opened once in an editor" — now carries
> the marker and is skipped, and #712's accepted cost is retired with it. The same
> mechanism reaches the Android `build/` directory an export template installs
> (`editor/export/export_template_manager.cpp:848-849`), which the engine marks the same
> way, so that tree leaves `project statistics` too. What #712's
> rule was actually FOR is unchanged: a `.godot` no engine wrote — an addon vendoring a
> sample tree, a fixture tree — holds no `.gdignore` and is still walked and still indexed.
> Measured both ways on a real engine and pinned by
> `test_an_engine_written_nested_cache_is_skipped_where_an_authored_one_is_walked`.
>
> **Residuals, stated not chased.** The exclusion of the project data path is still the
> hardcoded `res://.godot`, while the engine reads
> `application/config/project_data_dir_name` from `ProjectSettings`; a project that renames
> its data directory has gda index the renamed cache's scripts and skip a `res://.godot`
> that is ordinary content. And the two marker clauses cost two `FileAccess.file_exists`
> per child DIRECTORY — the same two probes the engine's own scan pays, on the same
> directories, not per file.

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
- **Scan boundary (amended 2026-08-28 #712, 2026-08-31 #760, 2026-09-02 #804).** What the scan
  skips is the root cache **identity** — not every directory named `.godot`, and not the path as
  written — plus the two directories the engine's own scan skips: a nested `project.godot` and a
  `.gdignore`. See the Decision amendments for the boundary, the symlink policy, and the two
  reversals #804 makes to the earlier vendored-tree trade — the declared sub-project, and the
  nested cache the engine marks with a `.gdignore` of its own.
- **Cost.** A never-opened-project miss walks the whole `res://` tree and parses every `.gd`; this is
  acceptable for one-shot ops and is **not** backed by a persistent gda-owned cache — a gda-owned
  cache would re-introduce the very ".godot ownership" complexity the editor-scan option was rejected
  for.
