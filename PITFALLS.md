# PITFALLS — godot-agent

_Project-scoped operational guidance for agents. These entries are not universal
constraints. Apply an entry only when its **Applies when** condition matches the current
environment. Check the current harness first when that check is practical; another
harness can have different capabilities._

## Writable `uv` and `uvx` paths in a managed sandbox

- **Applies when:** A managed harness denies writes to the default user cache or tool
  directory, or `uv` fails before it runs the requested command.
- **Symptom:** `uv` reports that it failed to initialize its cache, or `uvx` fails while
  it prepares a tool environment.
- **Cause:** The default cache or tool directory is outside the harness's writable
  paths.
- **Prevention:** Consider a task-scoped writable cache such as
  `UV_CACHE_DIR=/tmp/<task>-uv-cache`. An `uvx` command that installs a tool may also need
  `UV_TOOL_DIR=/tmp/<task>-uv-tools`. Serial commands can reuse one task cache. Concurrent
  commands should use separate cache directories.
- **Recovery:** Rerun once with writable, task-scoped paths. If the rerun reaches the
  requested command, treat the first failure as environment evidence rather than a
  product or test failure.
- **Last verified:** 2026-08-24 in a managed Codex desktop harness.

## Writable GitHub CLI cache for run evidence

- **Applies when:** A `gh run` command cannot read run logs or other CI evidence because
  the default local cache is not writable.
- **Symptom:** The command fails with an `operation not permitted` or similar local cache
  error before it returns the requested GitHub data.
- **Cause:** The GitHub CLI is trying to use a cache path outside the harness's writable
  paths.
- **Prevention:** For the affected command, consider a task-scoped cache such as
  `XDG_CACHE_HOME=/tmp/<task>-xdg-cache`.
- **Recovery:** Retry the read with the writable cache. Distinguish a repeated GitHub or
  network error from the original local-cache failure.
- **Last verified:** 2026-08-21 in a managed Codex review harness.

## Restricted Git metadata during isolated review

- **Applies when:** A review harness can read a checkout but cannot update its Git
  metadata.
- **Symptom:** `git fetch` cannot write `FETCH_HEAD`, or a linked-worktree command cannot
  update metadata even though the source files are readable.
- **Cause:** The harness protects `.git` or linked-worktree metadata outside its writable
  scope.
- **Prevention:** Check the available permission scope before planning a Git mutation.
  For read-only work, an existing exact commit object or an immutable GitHub snapshot may
  provide sufficient evidence.
- **Recovery:** For an authorized mutation, request the narrow permission that the Git
  operation needs. For read-only review, use a writable temporary clone or snapshot and
  record the exact commit that was inspected.
- **Last verified:** 2026-08 in managed review harnesses; recheck the current harness.

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

## Rendered Godot validation in a restricted harness

- **Applies when:** A sandbox or remote harness does not provide the window, display,
  input, or application-data permissions needed by a rendered Godot run.
- **Symptom:** Headless checks pass, while a rendered or interactive run cannot start or
  cannot complete its user path.
- **Cause:** The harness lacks a runtime capability that the rendered check needs. This
  does not by itself identify a product defect.
- **Prevention:** Separate headless evidence from rendered or human-in-the-loop evidence
  in the validation plan.
- **Recovery:** Run the rendered check in a capable local harness when possible. Report
  the passing headless evidence and the remaining rendered-validation gap separately.
- **Last verified:** 2026-08 in managed Godot review harnesses.
