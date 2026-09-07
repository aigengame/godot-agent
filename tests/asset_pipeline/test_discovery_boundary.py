"""Discovery does not initialize optional production or raster capabilities."""

import subprocess
import sys


def test_discovery_without_vendor_or_raster_imports(tmp_path):
    probe = """
import importlib.abc
import sys

class RefuseCapabilities(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PIL', 'bpy', 'mcp', 'google', 'openai'}:
            raise AssertionError('unused capability initialized: ' + fullname)

sys.meta_path.insert(0, RefuseCapabilities())
import gda_assets.api
from gda.cli import app
from typer.testing import CliRunner
runner = CliRunner()
for argv in [['--help'], ['--version'], ['asset-pipeline', 'run', '--schema']]:
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 0, (argv, outcome.output, outcome.exception)
"""
    outcome = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert outcome.returncode == 0, outcome.stderr
