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
  ``parse`` (exit ``5``) spans more than one ``GdaError.code``: both a genuine
  ``contract_violation`` and a deep-but-valid ``tree_too_deep`` (issue #37) — the
  envelope ``code`` distinguishes them, exactly as the many ``operation`` codes
  share exit ``4``. Exit codes stay at category granularity; finer detail is the
  ``code`` field's job (ADR-0002, ADR-0004).
- ``EXIT_LIVE`` (exit ``6``) is the Phase-2 ``live`` category: a live operation
  failed against ``gda-daemon`` / the engine session — no running daemon, a lost
  session, or a live timeout (ADR-0017, ADR-0021). Like ``operation`` and
  ``parse`` it spans several ``GdaError.code``s that the ``code`` field tells
  apart.
- ``EXIT_USAGE`` (exit ``2``) is the ``usage`` category: gda could not resolve
  what was asked for — an unrecognized command or option (#670). It is the ONE
  value here gda did not choose: ``2`` is the exit every CLI parser (click's
  included) already uses for a usage error, and gda's structured refusal is the
  same failure reported better, not a different one. Registering it therefore
  changes no observable exit code; it makes an exit gda already produced part of
  the registry so the envelope's ``exit_code`` and the process's agree.
"""

EXIT_USAGE = 2
EXIT_NOT_FOUND = 127
EXIT_TIMEOUT = 124
EXIT_VERSION = 3
EXIT_OPERATION = 4
EXIT_PARSE = 5
EXIT_LIVE = 6
