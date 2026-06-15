"""The single registry of ``gda`` process exit codes (issue #3).

These are the public CLI ABI an agent or shell keys on to tell failure
categories apart *without* parsing the JSON error. Kept in one leaf module — not
split across ``runner`` and ``errors`` — so the whole contract is reviewable at a
glance and new codes cannot silently collide.

- ``EXIT_NOT_FOUND`` / ``EXIT_TIMEOUT`` follow shell conventions (127 = command
  not found, 124 = timed out) and are what the runner *synthesizes* when it
  cannot get a result from the engine. The CLI maps those synthesized cases to
  ``environment`` — keyed on the runner's typed ``RunResult.launch_failure``, not
  the exit code, so an engine that genuinely returns 124/127 is an ``operation``
  failure, not mislabelled environment (issue #15).
- ``EXIT_VERSION`` / ``EXIT_OPERATION`` / ``EXIT_PARSE`` are distinct small codes
  the CLI assigns to failures the engine signalled differently or not at all.
- ``EXIT_TREE_TOO_DEEP`` is a wrapper-side limit, not a contract violation
  (issue #37): the engine emitted a valid, contract-conformant result tree, but
  it nests past pydantic-core's recursion ceiling so ``gda`` cannot materialize
  it. A distinct exit code keeps a shell consumer from conflating it with the
  ``EXIT_PARSE`` "the engine violated the contract" case.
"""

EXIT_NOT_FOUND = 127
EXIT_TIMEOUT = 124
EXIT_VERSION = 3
EXIT_OPERATION = 4
EXIT_PARSE = 5
EXIT_TREE_TOO_DEEP = 6
