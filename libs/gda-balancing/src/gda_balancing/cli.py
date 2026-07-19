"""Console-script entry point (`gda-balancing`, bADR-0007).

The equivalent module invocation lives in ``__main__.py``; both call the same
:func:`gda_balancing.dispatch.dispatch`, guaranteeing identical behavior.
Only this function calls ``sys.exit`` — dispatch returns exit codes as data.
"""

import sys

from gda_balancing.dispatch import dispatch


def main() -> None:
    sys.exit(dispatch(sys.argv[1:], sys.stdout, sys.stderr))
