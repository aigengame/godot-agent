# Test standards

Read this document before you write or change a test.

A test is useful when two things are true: it fails when its claim is false, and no other
test at the same layer holds the same claim. Each section below names a defect that breaks
one of these, says why, and gives a check that finds it.

Other sources own other facts. This document does not copy them:

- [CONTEXT.md](../CONTEXT.md) defines the project terms, for example `Headless
  operation`, `Live operation`, `Engine session` and `Error envelope`.
- The Development section of the [README](../README.md) gives the commands that run each
  tier.
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) sets which tier each CI job
  runs, and where.
- `RULES.md`, when your checkout has one, gives the general test rules. It is a local file
  that Git ignores, so this document does not link it.

## Where a test goes

**The tier.** The `e2e` marker means that the test spawns a real Godot process (the
`markers` list in [`pyproject.toml`](../pyproject.toml)). A test that starts no engine has
no marker. The pull request job runs only the tests that have no `e2e` marker, and only
on Linux. When you move a test between tiers, read the passed and skipped counts of that job:
a test that skips on Linux gives no evidence there.

**The invocation module.** A fast test that stages a canned engine run or a canned live
runner reply runs the command through [`tests/support.py`](../tests/support.py):
`invoke_cli` for a Headless command and `invoke_live` for a Live command. A test can call
the low-level `inject_live_runner` only when it drives a recipe directly or serves several
invocations from one fake, and a comment must say which. A test of a command that starts its
engine through a shared step patches that step's `launch` and invokes the CLI directly,
because `invoke_cli` replaces only the sentinel runner. A test whose claim needs the real
live runner and daemon discovery, or a separate `gda` process, stages no reply and does
not use these helpers.

**A rule that a set of commands shares.** One test holds the rule for the whole set, as a
table with one row per command and a guard that keeps the table equal to the set. For a
new command, add a row; do not write a per-command test of the rule. A row covers only the
code path that its argv takes, so keep a per-command test for a path that the row does not
take. The tables:

- Live rules: `LIVE_LEAVES` in
  [`tests/live/test_live_rules.py`](../tests/live/test_live_rules.py). The guard fails until
  each Live command has a row.
- Daemon-served log operations: `LOG_OPS` in
  [`tests/daemon/test_daemon_log_ops.py`](../tests/daemon/test_daemon_log_ops.py).
- The edit-mode refusals of `script set` and `shader set`: the set-mode table in
  [`tests/script/test_script_commands.py`](../tests/script/test_script_commands.py).

**A platform-bound mechanism.** The daemon reaches its platform-bound operations, such
as the slot, the endpoints and the session process, through the platform seam, with one
adapter per platform. A test of the daemon's platform-neutral behaviour reaches those
operations through the same seam: it connects, binds, and fakes a session spawn or a
serving daemon with the seam helpers in [`tests/support.py`](../tests/support.py), so
the test runs on each platform the seam serves. A test whose subject is one adapter's
mechanism, an authentication boundary or the raw protocol keeps its direct access to
the primitive, and gets no support helper that bypasses the seam for it. A platform gate
gives the mechanism that the test needs as its reason, not the platform, and sits on the
smallest scope that needs it: on the test, or on the module when each test in the module
is about one adapter, as in
[`tests/daemon/test_daemon_unix_adapter.py`](../tests/daemon/test_daemon_unix_adapter.py)
and the Windows daemon modules. After you add a gate, read the skip count of the
platform job: a gate wider than its mechanism hides tests that could run there.

## A test must be able to fail

### The expected value comes from the code under test

The test builds its expected value from the constants or functions that it tests. A change
to the code changes the expected value too, so the test passes by construction. A round
trip through a writer and a reader that change together cannot fail either.

**Check:** Write the expected value as a literal, or take it from a source that is
independent of the code, such as the specification or a measured engine output. A mutant
of the constant or the function must fail the test.

### The assertion is weaker than the claim

The assertion accepts a result that the claim excludes: a substring that a longer word
also contains, a prefix of the expected line, a non-zero exit, or exit 2 that an unknown
option also gives. A wrong result near the correct one passes.

**Check:** Assert the exact value: the whole word, the exact line, the error code and the
message. Give the test a near miss; it must fail.

### The input does not have the shape that the test names

The test name or comment names an input shape, but the input that the test gives does not
have that shape. The test exercises another input, so a regression for the named shape
passes.

**Check:** Read the value that reaches the subject. A mutant that handles the named shape
incorrectly must fail the test.

### The test passes when its subject did not run

The assertions do not depend on what the engine or the script did. An expected failure
can also coincide with an unrelated failure, for example an exit 1 from a process that did
nothing.

**Check:** The stand-in engine run below. Assert a fact that only a real run gives, such
as an exit status of 0, a line that the script prints, or the error code that the engine
returns.

### A fault injection cannot trip

The test injects a function that fails the test when a forbidden action occurs, but the
code never calls that function: the code keeps a reference that it took earlier, or a
precondition stops the action before the call.

**Check:** Inject the function through the seam that the code reads. A mutant that does
the forbidden action must fail the test, and the `E` line must be the message of the
injected function.

## Each claim has one test

### A test restates a claim that another test at the same layer holds

The second test cannot fail unless the first one fails too. It adds run time and one more
place to change.

**Check:** Before you add a test, search for a test that asserts the same claim at the
same layer. Before you delete a test, compare the assertions one by one: another test must
assert each of them, with an input that takes the same code path. A test that holds the
claim at a different layer is not a duplicate.

### Each command restates a shared rule

Each command of a set has its own test of a rule that the whole set follows. A command
with no such test can break the rule, and no test fails.

**Check:** When the expected answer does not depend on the command, hold the rule in one
table with a guard (see "Where a test goes").

### The test copies the invocation steps

The test stages a reply and runs the CLI itself, or through a private helper, instead of
through the invocation module. Each copy is one more place that must stage what the runner
really returns, and a private helper can hide assertions from the reader.

**Check:** Use `invoke_cli` or `invoke_live`. A helper that builds an argv or reads a
result can stay; a helper that stages a reply and runs a command goes.

### A docstring or a comment states what the tests do not do

A module docstring, a package docstring or a comment names a test, a count or an input that
is not there. A reader trusts the text to find coverage.

**Check:** When you move, delete or change a test, change the text that describes it in
the same change. Do not write a count of tests or calls in a docstring.

## Checks

The commands are for a POSIX shell on macOS or Linux.

### Mutant check

A mutant is the code under test, made wrong on purpose. A test that passes against it
cannot find that defect.

1. Find the line in `src/` that the claim of the test depends on.
2. Change only that line to the wrong behaviour that the test must find. If the file has
   changes that are not committed, save a copy of it first.
3. Remove the bytecode cache:

   ```sh
   find src tests -name __pycache__ -prune -exec rm -rf {} +
   ```

   CPython uses a cached `.pyc` file when the source has the same size and the same
   modification time in whole seconds. A mutant of the same length that you make in the
   same second then does not run.
4. Run the test. It must fail.
5. Read the `E` line of the failure. It must be the assertion of the claim. A failure on
   another assertion, an import error or a crash does not show that the test finds the
   defect.
6. Restore the file, from Git or from your copy, and remove the cache again. Make sure
   that `src` is as it was before step 2: `git diff -- src` shows no change, or only the
   changes that you had before.
7. Record the mutant and the failed assertion in the pull request description.

### Stand-in engine run

The stand-in is an executable that records the test that called it and then exits 1. Run
the e2e tier against it to find e2e tests whose result does not depend on the engine.

1. Make the stand-in:

   ```sh
   D=$(mktemp -d)
   cat > "$D/godot" <<EOS
   #!/bin/sh
   printf '%s\n' "\$PYTEST_CURRENT_TEST" >> "$D/calls.log"
   exit 1
   EOS
   chmod +x "$D/godot"
   ```

2. Run the e2e tier against it, with a summary line for each passed case:

   ```sh
   GDA_GODOT="$D/godot" uv run pytest -m e2e -rp > "$D/run.txt"
   ```

3. Compare the passed cases with the cases that called the stand-in:

   ```sh
   sed -n 's/^PASSED //p' "$D/run.txt" | LC_ALL=C sort -u > "$D/passed.txt"
   sed 's/ ([a-z]*)$//' "$D/calls.log" | LC_ALL=C sort -u > "$D/called.txt"
   LC_ALL=C comm -23 "$D/passed.txt" "$D/called.txt"  # passed, no engine call
   LC_ALL=C comm -12 "$D/passed.txt" "$D/called.txt"  # passed, engine called
   ```

4. Examine each listed case:
   - Passed with no engine call: the test starts no engine. Delete it when a fast test
     holds its claim; otherwise remove its marker. A parametrized function whose other
     cases call the engine stays in the e2e tier.
   - Passed with an engine call: the test does not check what the engine did. Assert a
     fact that only a real run gives. A control that asserts that the engine does not
     complete passes here correctly.

## Cases

The wiki page
[Case Study: Tests That Could Not Fail or Added Nothing](https://github.com/aigengame/godot-agent/wiki/Case-Study:-Tests-That-Could-Not-Fail-or-Added-Nothing-(gda-Test-Architecture-Refactor))
shows each defect as it was found in this repository, with the mutants and the results.
