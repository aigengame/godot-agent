"""The single registry of ``gda`` process exit codes (issue #3).

These are the public CLI ABI an agent or shell keys on to tell failure
categories apart *without* parsing the JSON error. Kept in one leaf module — not
split across ``runner`` and ``errors`` — so the whole contract is reviewable at a
glance and new codes cannot silently collide.

- ``EXIT_NOT_FOUND`` / ``EXIT_TIMEOUT`` follow shell conventions (127 = command
  not found, 124 = timed out) and are also what the runner *synthesizes* when it
  cannot get a result from the engine; the CLI maps both to ``environment``.
- ``EXIT_VERSION`` / ``EXIT_OPERATION`` / ``EXIT_PARSE`` are distinct small codes
  the CLI assigns to failures the engine signalled differently or not at all.
"""

EXIT_NOT_FOUND = 127
EXIT_TIMEOUT = 124
EXIT_VERSION = 3
EXIT_OPERATION = 4
EXIT_PARSE = 5
