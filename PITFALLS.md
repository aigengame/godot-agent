# PITFALLS — godot-agent

_Project-scoped operational guidance for agents. These entries are not universal
constraints. Apply an entry only when its **Applies when** condition matches the current
environment. Check the current execution environment first when that check is practical;
another environment can have different capabilities._

## Writable `uv`, `uvx`, and project environment paths in a managed sandbox

- **Applies when:** A managed environment reports that the default `uv` cache, tool
  directory, or project environment is not writable before the requested command
  starts.
- **Symptom:** `uv` reports that it failed to initialize its cache or acquire the
  project environment lock, or `uvx` fails while it prepares a tool environment.
- **Cause:** The default cache, tool directory, or project environment is outside the
  execution environment's writable paths.
- **Prevention:** Consider a task-scoped writable cache such as
  `UV_CACHE_DIR=<writable-temp-dir>/<task>-uv-cache`. An `uvx` command that installs a
  tool may also need `UV_TOOL_DIR=<writable-temp-dir>/<task>-uv-tools`. When the
  project environment is not writable, consider a unique absolute
  `UV_PROJECT_ENVIRONMENT=<writable-temp-dir>/<task>-venv`; do not share that environment
  between projects. On macOS or Linux, `/tmp/...` can be a suitable writable temporary
  location. Commands can reuse one task cache and project environment.
- **Recovery:** Rerun once with writable, task-scoped paths. For a read-only validation
  that does not need dependency synchronization, an existing environment's executable
  can be called directly after confirming that it belongs to the exact checkout. If the
  rerun reaches the requested command, treat the first failure as environment evidence
  rather than a product or test failure.
- **Last verified:** 2026-08-27 in a managed Codex desktop environment.

## Pytest cache in a read-only worktree

- **Applies when:** Pytest runs from a checkout or worktree that is readable but does
  not allow writes below its project root.
- **Symptom:** Tests can pass, but pytest reports `PytestCacheWarning` because it cannot
  write a path below `.pytest_cache`.
- **Cause:** The built-in cache provider stores node ids, failure state, and related
  data in `.pytest_cache` by default.
- **Prevention:** If the cache is not needed, consider disabling the provider with
  `-p no:cacheprovider`. This also disables pytest's stepwise plugin. If the cache or
  stepwise behavior is needed, set a task-scoped writable location with
  `-o cache_dir=<writable-temp-dir>/<task>-pytest-cache`.
- **Recovery:** Rerun with the cache disabled or redirected when a warning-free result
  is required. A cache-write warning by itself does not prove that the test failed.
- **Last verified:** 2026-08-24 with pytest in a managed read-only review worktree.

## Writable GitHub CLI cache for run evidence

- **Applies when:** A `gh run` command cannot read run logs or other CI evidence because
  the default local cache is not writable.
- **Symptom:** The command fails with an `operation not permitted` or similar local cache
  error before it returns the requested GitHub data.
- **Cause:** The GitHub CLI is trying to use a cache path outside the execution
  environment's writable paths.
- **Prevention:** For the affected command, consider a task-scoped cache such as
  `XDG_CACHE_HOME=<writable-temp-dir>/<task>-xdg-cache`. On macOS or Linux, `/tmp/...`
  can be a suitable writable temporary location.
- **Recovery:** Retry the read with the writable cache. Distinguish a repeated GitHub or
  network error from the original local-cache failure.
- **Last verified:** 2026-08-27 in a managed Codex review environment.

## Restricted Git metadata during isolated review

- **Applies when:** A review environment can read a checkout but cannot update its Git
  metadata.
- **Symptom:** `git fetch` cannot write `FETCH_HEAD`, or a linked-worktree command cannot
  update metadata even though the source files are readable.
- **Cause:** The environment protects `.git` or linked-worktree metadata outside its
  writable scope.
- **Prevention:** Check the available permission scope before planning a Git mutation.
  For read-only work, an existing exact commit object or an immutable GitHub snapshot may
  provide sufficient evidence.
- **Recovery:** For an authorized mutation, request the narrow permission that the Git
  operation needs. For read-only review, use a writable temporary clone or snapshot and
  record the exact commit that was inspected.
- **Last verified:** 2026-08 in managed review environments; recheck the current
  environment.

## GitHub connector and CLI permission differences

- **Applies when:** An authorized GitHub mutation through a connector returns
  `403 Resource not accessible by integration`.
- **Symptom:** The connector can read the target but cannot post or edit the requested
  GitHub artifact.
- **Cause:** The connector token does not have the required permission. An authenticated
  local GitHub CLI can have a different permission set.
- **Prevention:** Use the available GitHub path that has the required permission. For
  Markdown-heavy content, a body file also avoids shell interpretation.
- **Recovery:** If the mutation is already authorized, consider the authenticated `gh`
  CLI. Read the target after an ambiguous failure or retry so the operation does not
  create a duplicate.
- **Last verified:** 2026-08 in managed Codex GitHub workflows.

## Repository code versus an installed CLI

- **Applies when:** Validation runs a command name that can resolve to both the current
  checkout and a globally installed package.
- **Symptom:** The command reports stale behavior, a different version, or results that do
  not match the checked-out source.
- **Cause:** `PATH` selected an installed executable instead of the repository runtime.
- **Prevention:** Verify the executable and version before judging branch behavior.
  Prefer the repository's documented environment, such as its local virtual environment
  or supported module entry point.
- **Recovery:** Rerun with the repository runtime selected explicitly and compare the
  result before classifying the change.
- **Last verified:** 2026-08 in godot-agent review worktrees.

## Godot `user://` writes in a restricted environment

- **Applies when:** A sandbox or remote execution environment does not allow Godot to
  write to its default application-data location, and a headless or rendered validation
  launches the engine or writes files through `user://`.
- **Symptom:** Godot can fail before the test script starts because it cannot open
  `user://logs`, or a script can fail to save feedback or another `user://` file even
  after the engine log is redirected with an absolute `--log-file`.
- **Cause:** The default Godot application-data location is outside the environment's
  writable paths. `--log-file` redirects the engine log only; it does not relocate
  `user://`.
- **Prevention:** Prefer the repository's supported `gda` runner with a unique writable
  `--user-data-root <writable-temp-dir>/<task>-godot-data` for each concurrent process.
  A direct Godot run that does not use `user://` may use an absolute `--log-file`, but
  this does not make other application-data paths writable.
- **Recovery:** Rerun through `gda --user-data-root` and check the structured result and
  script `exit_status`. If that run reaches and passes the requested behavior, classify
  the first failure as environment evidence rather than a product defect.
- **Last verified:** 2026-08-27 with Godot 4.6.3 in a managed environment.

## `GDA_USER_DATA_ROOT` exported for a whole e2e run

- **Applies when:** `GDA_USER_DATA_ROOT` (or a repeated `--user-data-root`) is exported
  for a batch of e2e tests rather than set per invocation.
- **Symptom:** Unrelated suites fail — notably
  `test_e2e_export_run.py::test_templates_installed_is_true_when_host_templates_are_on_disk`,
  which reports `templates_installed=false` while the host's
  `export_templates/<version>/` directory is present and correct.
- **Cause:** The setting relocates the platform application-data variable, and Godot's
  export templates live under that same directory. Redirecting it hides templates that
  are installed in the real one.
- **Prevention:** Scope the redirect to the invocations that need a private `user://`
  or a writable data directory. Do not export it for a whole suite run.
- **Recovery:** Re-run the failing test with the variable unset before treating the
  result as a product defect.
- **Last verified:** 2026-08-31 with Godot 4.6.3 on macOS, against this repository's
  e2e suite.

## Rendered Godot validation in a restricted environment

- **Applies when:** A sandbox or remote execution environment does not provide the
  window, display, or input capabilities needed by a rendered Godot run.
- **Symptom:** Headless checks pass, while a rendered or interactive run cannot start or
  cannot complete its user path.
- **Cause:** The environment lacks a runtime capability that the rendered check needs.
  This does not by itself identify a product defect.
- **Prevention:** Separate headless evidence from rendered or human-in-the-loop evidence
  in the validation plan.
- **Recovery:** Run the rendered check in a capable local environment when possible.
  Report the passing headless evidence and the remaining rendered-validation gap
  separately.
- **Last verified:** 2026-08 in managed Godot review environments.

## Godot game-path launch with no scene on macOS blocks on a native alert

- **Applies when:** On macOS, the engine starts on the GAME path (`--path <project>` with
  no `--script`, `--scene`, `--import`, or `--export-*`) and has no scene it can run:
  `application/run/main_scene` is empty, or a `uid://` with no UID cache (a checkout
  never imported). Reached by a hand-written launch, or by a `gda` session launch that
  `gda` deferred to the engine (a main-scene feature override, a settings overlay, or an
  escaped key in `project.godot`, #829).
- **Symptom:** The engine prints `Can't run project: no main scene defined` (or `Main
  scene's path could not be resolved from UID`), shows a native ALERT even with
  `--headless`, and blocks until the dialog is dismissed or the process is killed — a
  caller waits out its full timeout.
- **Cause:** `main/main.cpp` (4.6.3) calls `OS::alert()` unconditionally on both paths;
  the macOS implementation shows an `NSAlert` regardless of display server; no flag
  suppresses it.
- **Prevention:** Name what to run (`--script`, `--scene`, `--import`, `--export-*`), or
  set `run/main_scene` and import once for a `uid://`. Since #829, `gda daemon start`
  and the daemon's launch boundary refuse the two determinable shapes before spawning
  (`live_main_scene_undefined`, `live_main_scene_unresolved`); a deferred configuration
  is not refused and can still reach the alert.
- **Recovery:** `pkill -f "Godot.*<project dir>"` closes the dialog; a `gda` launch ends
  at its timeout or readiness deadline. For a `uid://`, run `gda resource import <any
  existing res:// asset>` (or open the project in the editor) before starting again.
- **Last verified:** 2026-09-04, Godot 4.6.3 on macOS; `gda`'s refusal scope is #829's (PR #831).
