# Test standards

Read this document before you write or change a test. It tells you how to write a test
that fails when its subject is wrong, and how to check that it does.

Each rule comes from a defect that the test architecture refactor (#1212, #1213) found
and changed. A rule names the defect, says why a test with the defect cannot fail or
adds nothing, gives a check that finds the defect, and cites the cases.

Other sources own other facts. This document does not copy them:

- [CONTEXT.md](../CONTEXT.md) defines the project terms, for example `Headless
  operation`, `Live operation`, `Engine session` and `Error envelope`.
- The Development section of the [README](../README.md) gives the commands that run each
  tier.
- [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) sets which tier each CI job
  runs, and where.
- `RULES.md`, when your checkout has one, gives the general test rules, for example that
  a fake is not the only evidence of real integration behaviour. It is a local file that
  Git ignores, so this document does not link it.

## Where a test goes

### The tier

The `e2e` marker means that the test spawns a real Godot process (the `markers` list in
[`pyproject.toml`](../pyproject.toml)). A test that starts no engine has no marker. The
pull request job runs only the tests that have no `e2e` marker, so an `e2e` marker on a
test that starts no engine keeps that test out of each pull request run.

Case: 29 e2e functions started no engine. #1222 deleted the 6 that a fast test already
held, and moved the other 23 to the fast tier.

When you move a test to the fast tier, read the passed and skipped counts of the pull
request job. That job runs on Linux, and a test that skips itself on Linux gives no
evidence there. Case: #1222 moved
`test_a_root_whose_derived_data_path_is_blocked_is_refused`. It skips on Linux, where the
derived user-data path is the root, so the job reported one more skip and one fewer pass
than the 36 moved cases. For the same reason, #1222 deleted the absent-artifact smoke test
instead of moving it: its module skips every platform except macOS and Windows.

### The invocation module

A fast test runs a command through the shared module in
[`tests/support.py`](../tests/support.py): `invoke_cli` for a Headless command and
`invoke_live` for a Live command. Their docstrings say what each one stages. Rule 8 tells
when a test can use the low-level seam.

### A rule that a set of commands shares

When the subject follows a rule that a set of commands shares, one test holds the rule
for the whole set. Add a row to that test. Do not write a per-command test of the rule
(rule 7).

- A new Live command: add its smallest argv to `LIVE_LEAVES` in
  [`tests/live/test_live_rules.py`](../tests/live/test_live_rules.py). The guard
  `test_the_table_names_each_live_leaf_once_and_nothing_else` fails until the row exists.
  The module docstring says what stays in a per-command test.
- A new daemon-served log operation: add it to `LOG_OPS` in
  [`tests/daemon/test_daemon_log_ops.py`](../tests/daemon/test_daemon_log_ops.py).
- A new refusal of the edit-mode rule of `script set` and `shader set`: add a row to
  `test_set_mode_refusal_names_its_rule_on_both_commands` in
  [`tests/script/test_script_commands.py`](../tests/script/test_script_commands.py).

## Rules

### 1. The expected value comes from the code under test

- **Defect:** The test builds its expected value from the constants or functions of the
  code that it tests.
- **Why it cannot fail:** A change to the code changes the expected value too, so the test
  passes by construction. A round-trip test cannot fail when the writer and the reader
  change together.
- **Check:** Make a mutant that changes the constant or the function. The test must fail.
  Write the expected value as a literal, or take it from a source that is independent of
  the code, such as the specification or a measured engine output.
- **Case:** `test_build_result_wraps_payload_in_the_sentinel_with_trailing_newline` built
  its expected text from the sentinel constants. With the mutant
  `RESULT_END = "<<<GDA:FIN>>>"`, it and the round-trip test passed. It now compares with
  a literal text (#1221).

### 2. The assertion is weaker than the claim

- **Defect:** The assertion accepts a result that the claim excludes.
- **Why it cannot fail:** A wrong result that is near the correct one passes.
- **Check:** Give the test a near miss: a word that contains the expected word, another
  line with the same start, an unknown option, or another error. The test must fail.
  Assert the exact value: the whole word, the exact line, the error code and the message.
- **Cases:**
  - `"_input" in flat` was true when the help contained only `_gui_input`. The input help
    test now matches `_input` as a whole word (#1221).
  - `test_bare_version_stays_the_human_one_liner` asserted a prefix. A test that asserts
    the exact line holds the claim, so #1221 deleted it.
  - Nine argv tests of `script set` and `shader set` asserted only exit 2 and no engine
    call. An unknown option gives the same result. One `--params-json` table now asserts
    `invalid_params`, the exact message and no engine call for each refusal on both
    commands. `test_argv_and_params_json_report_the_identical_sentence` holds that the argv
    channel reports the same sentence (#1220).
  - Three Live tests of a missing project asserted only a non-zero exit. The rule table
    asserts exit 4 and `project_not_found` (#1216).

### 3. The input does not have the shape that the test names

- **Defect:** The test name or comment names an input shape, but the input that the test
  gives does not have that shape.
- **Why it cannot fail:** The test exercises another input, so a regression for the named
  shape passes.
- **Check:** Read the input value that reaches the subject. Make a mutant that handles the
  named shape incorrectly. The test must fail.
- **Case:** Two fast tests said that a filesystem path that contains `://` is not
  engine-virtual, but their input was `outside:/deck.gd`. Both passed a mutant that makes
  every path that contains `://` engine-virtual. The input is now `outside://deck.gd`, and
  both fail that mutant (#1222).

### 4. The test passes when its subject did not run

- **Defect:** The test passes when the engine or the script that it is about did nothing.
- **Why it cannot fail:** The assertions do not depend on the output of the subject.
- **Check:** The stand-in engine run (below). A passed e2e case that did not call the
  stand-in starts no engine: delete it when a fast test holds its claim, or remove its
  marker. A passed case that called the stand-in does not check what the engine did:
  assert a fact that only a real run gives. The stand-in exits 1, so a test that expects
  exit 1 for another reason also passes on it.
- **Cases:**
  - The 29 engine-free e2e functions of the tier section (#1222).
  - `test_script_run_reports_the_engine_data_path_of_a_default_run` passed on the
    stand-in. It now asserts that `exit_status` is 0 (#1221).
  - Two strict `script run` tests expected a failure, and the stand-in exits 1 as the
    script's `quit(1)` does. They now assert the line that the script prints in
    `diagnostics` (#1221).
  - `test_malformed_param_fails_promptly_not_as_timeout` passed with the
    `operation_failed` that the stand-in gives. It now asserts `invalid_path`, which
    Godot 4.6.3 gives (#1221).

### 5. A fault injection cannot trip

- **Defect:** The test injects a function that fails the test when a forbidden action
  occurs, but the code never calls that function.
- **Why it cannot fail:** The forbidden action can occur, and the test does not see it.
- **Check:** Make a mutant that does the forbidden action. The test must fail, and the `E`
  line must be the message of the injected function.
- **Case:** The diag test of the no-launch behaviour patched the module's launch function
  after it built the daemon server. The server keeps the launch function that it gets at
  construction, so the patch had no effect. The log-operation table gives the server a
  launch function through its `launch` parameter. The server also stops a launch before
  it calls that function when it has no harness listener, so the row also gives it one.
  The launching mutant then fails with `Failed: logger-tail launched an Engine session`
  (#1216).

### 6. The test restates a claim that another test at the same layer holds

- **Defect:** Two tests at one layer assert the same claim.
- **Why it adds nothing:** The second test cannot fail unless the first one fails too. It
  adds run time and one more place to change.
- **Check:** Before you add a test, search for a test that asserts the same claim at the
  same layer. Before you delete a test, compare the assertions one by one: the other test
  must assert each of them, with an input that takes the same code path. Keep both tests
  when each one holds the claim at a different layer.
- **Cases:**
  - #1221 deleted `test_params_json_validation_error_is_also_rendered_clean`,
    `test_render_engine_version_renders_the_one_line_version_string`, two export tree
    mutation tests that the `Project tree inventory` tests hold, and
    `test_info_tracer_real_chain`. It replaced two loops over three equal envelopes with
    one check of the one envelope.
  - A deleted `logger tail` test also asserted `level == "error"`. #1216 deleted it after it
    found that `test_logger_tail_reads_structured_records_from_the_log` holds that
    assertion.
  - Kept at two layers: the Live number scan tests beside the model tests that refuse the
    same values, and the MCP project resolution tests at the server and at the tool
    (#1213).
  - Not deleted: three `script validate` e2e tests had fast twins with other inputs, so
    they moved to the fast tier (#1222).

### 7. Each command restates a shared rule

- **Defect:** Each command of a set has its own test of a rule that the whole set follows.
- **Why it cannot fail:** A command with no such test can break the rule, and no test
  fails.
- **Check:** When the expected answer does not depend on the command, write one test that
  is parametrized over the set, and a guard that keeps the table equal to the set. A row
  covers only the code path that its argv takes, so keep a per-command test of a path
  that the row does not take.
- **Case:** The five rules that every Live command shares. No per-command test found that
  `logger tail` reported an empty result, with exit 0, for a Live error whose code is not
  registered. The table over all 19 Live leaves found it, and #1216 fixed the result
  model and deleted 42 per-command tests.
- **Kept:** The `perf monitors` row has no `--frames`, so it takes only the snapshot path.
  The no-daemon test of the window path stays, because that path makes its own exchange
  with the daemon (#1219).

### 8. The test copies the invocation steps

- **Defect:** The test stages a reply and invokes the CLI itself, or through a private
  helper, instead of through the shared invocation module.
- **Why it adds nothing:** Each copy is one more place that must stage what the runner
  really returns, and a private helper can hide assertions from the reader.
- **Check:** A command test that calls `inject_live_runner` directly needs a comment that
  says that it drives a recipe directly or serves several invocations from one fake. Any
  other test uses `invoke_cli` or `invoke_live`.
- **Cases:**
  - #1212 deleted or folded in eight private Live helpers.
  - `_input_json` and `_input_text` staged a reply, ran the CLI and asserted exit 0. That
    assertion now stands at each call site (#1218).

### 9. A docstring or a comment states what the tests do not do

- **Defect:** A module docstring, a package docstring or a comment names a test, a count or
  an input that is not there.
- **Why it adds nothing:** A reader trusts the text to find coverage, and does not add a
  test that the text says exists.
- **Check:** When you move, delete or change a test, search the module docstring, the
  package docstring and the comments for its claim. Do not write a count of tests or calls
  in a docstring.
- **Cases:**
  - After #1216 moved the no-daemon tests into the rule table, six module docstrings still
    said that the module ran the real `DaemonRunner` with no daemon, and the `tests/live`
    package docstring counted 149 direct calls (#1217, #1218, #1219).
  - The export tree mutations docstring said "These ten stay HERE" (#1221).
  - Module docstrings and comments said that the tests moved to the fast tier need a real
    engine (#1222).

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
   defect (rule 5).
6. Restore the file, from Git or from your copy. Remove the cache again, and make sure
   that `git diff -- src` shows no change.
7. Write the mutant and the failed assertion in the pull request description, as #1216,
   #1220 and #1221 do.

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

4. Examine each case in the two lists with rule 4. Some cases are correct:
   - One case of a parametrized function can make no engine call while its other cases
     do. The function stays e2e. Example: four cases of two `res://` containment
     functions.
   - A control that asserts that the engine does not complete also passes on the
     stand-in. Example: `test_control_unprotected_launch_really_does_die_on_the_restriction`.
