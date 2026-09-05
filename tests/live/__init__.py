"""Tests whose subject is the live channel, not one live command's domain object.

Every module here exercises the same seam: a command goes through Typer, into
``classify_live``, out as JSON, against an injected daemon runner rather than a
real engine -- plus the e2e half that drives the same path against a real
daemon. ``inject_live_runner`` appears 149 times across seven of this package's
modules; outside it, only its own helper in ``tests.support`` and the daemon
package's wait-ready module use it at all. The seam, not the addressed object,
is what makes these modules change together.

That is why ``game``, ``input``, ``logger``, ``diag``, ``perf`` and ``screen``
sit here rather than in six packages named after their command groups. ADR-0019
places those groups by domain object in the COMMAND SURFACE, where a user reads
the tree; it does not speak about the test tree, and the reason to change is not
the same on the two sides. A change to one command's own semantics still edits
one module here, found by its file name.

The suite's packages are drawn by reason to change. A package is named after a
domain object where the object drives the change (``scene``, ``node``,
``project``, ...) and after the mechanism otherwise (``cli``, ``runtime``,
``mcp``, ``harness``, ``repo``, this one).
"""
