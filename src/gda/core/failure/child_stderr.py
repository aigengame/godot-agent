"""The producer half of ADR-0002's #803 child-stderr rule (ADR-0045 §2).

Split out of the headless descriptor module, below the import-pass step that was
its one upward edge: :func:`forward_child_stderr`, and the unbound type variable
``T`` that only its signature uses.
"""

import sys
from typing import TypeVar

from gda.core.engine.launch import RunResult
from gda.core.failure.catalog import Failure

T = TypeVar("T")


def forward_child_stderr(result: RunResult, outcome: T | Failure) -> T | Failure:
    """Forward a classified run's stderr under ADR-0002's #803 rule, and return it.

    The producer half of the child-stderr rule, in ONE place shared by the
    following producers: :meth:`gda.headless.HeadlessCommand.execute`, the live exchange
    (:func:`gda.dispatch.run_live_exchange`, #1013), `project scan`'s class read
    (#1073) and the import-pass step (:func:`gda.import_pass.run_import_pass`,
    #1079). The rule is recorded in ADR-0002's #803 outcome note.

    A failure CARRIES the stderr on ``child_stderr`` and this prints nothing: whether
    printing it would repeat the bytes ``diagnostics`` is about to carry depends on the
    caller's channel, which only :func:`gda.headless.emit_failure` knows (#798 review).
    A success has no diagnostics to duplicate, so its stderr is teed now.

    The success is whatever the producer hands on: a typed result model, or the
    import-pass step's raw run (#1079), which its callers read for their own
    data. So ``T`` is unbound, unlike the ``M`` of :mod:`gda.headless`.
    """
    if isinstance(outcome, Failure):
        outcome.child_stderr = result.stderr
    elif result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return outcome
