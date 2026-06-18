"""Enable ``python -m gda`` (and thus ``sys.executable -m gda``).

gda-mcp invokes the CLI as ``[sys.executable, "-m", "gda", …]`` for a
deterministic, same-environment binary (ADR-0011, Design decision 3): it runs
the *exact* gda paired with the running gda-mcp, never a wrong global ``gda`` a
PATH lookup might resolve. This module is the ``-m gda`` entry point that makes
that invocation work; it shares the one Typer ``app`` with the ``gda`` console
script, so both entry points behave identically.
"""

from gda.cli import app

if __name__ == "__main__":
    app()
