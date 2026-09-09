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
for argv in [['--help'], ['--version'], ['asset-pipeline', 'run', '--schema'], ['asset-pipeline', 'check', '--schema']]:
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 0, (argv, outcome.output, outcome.exception)
assert 'gda_assets.adapters.blender' not in sys.modules
assert 'gda_assets.adapters._blender_worker' not in sys.modules
"""
    outcome = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert outcome.returncode == 0, outcome.stderr


def test_core_commands_do_not_build_unused_asset_models(tmp_path):
    # A fresh process observes startup work before other tests request schemas.
    # Pydantic's completion state proves construction was deferred without a
    # machine-dependent timing threshold.
    probe = """
from pydantic import BaseModel
from typer.testing import CliRunner
from gda.cli import app
from gda.commands import asset_pipeline

runner = CliRunner()
for argv in [['--help'], ['game', 'get', '--schema']]:
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 0, (argv, outcome.output, outcome.exception)
models = [
    value for name, value in vars(asset_pipeline).items()
    if not name.startswith('_') and isinstance(value, type)
    and issubclass(value, BaseModel)
    and value.__module__ == asset_pipeline.__name__
]
assert models
built = [model.__name__ for model in models if model.__pydantic_complete__]
assert not built, 'unused asset models compiled: ' + repr(built)

# The first actual asset schema request must still build its models.
outcome = runner.invoke(app, ['asset-pipeline', 'concept-prepare', '--schema'])
assert outcome.exit_code == 0, (outcome.output, outcome.exception)
assert asset_pipeline.ConceptPrepareParams.__pydantic_complete__
assert asset_pipeline.ConceptPreparationResult.__pydantic_complete__
"""
    outcome = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert outcome.returncode == 0, outcome.stderr
