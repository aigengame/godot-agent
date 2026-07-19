"""Module invocation entry (`python -m gda_balancing`, bADR-0007).

Registered alongside the console script by #502; shares the same dispatch, so
the two invocation forms are byte-identical in behavior.
"""

from gda_balancing.cli import main

if __name__ == "__main__":
    main()
