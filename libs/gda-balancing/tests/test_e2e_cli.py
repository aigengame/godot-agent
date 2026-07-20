"""The e2e tier — the CLI as real subprocesses.

Family convention (gda's ``test_e2e_*`` naming): end-to-end tests live in
their own module. Unlike gda's engine-backed e2e, this tier has no external
dependency and runs fast, so it stays in the standard CI job — no marker
gating.

Two claims, both unprovable in-process:

* **Packaging** — the installed console script and ``python -m`` entry agree
  and separate their streams (the claim #502 exists to prove).
* **Key user path** (RULES DoD: automated e2e on the path an agent actually
  drives) — author a document, validate it, get typed refusals, format
  canonically with an artifact sink, read the self-description; through the
  installed entry point, OS argv/streams, and real files. The in-process
  conformance rows prove the behavior; these prove the same commands survive
  the process boundary.
"""

import json
import shutil
import subprocess
import sys

import jsonschema

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA


def _console_script() -> str:
    script = shutil.which("gda-balancing")
    assert script is not None, (
        "console script `gda-balancing` not on PATH — this package is its own "
        "uv project, so run the suite from its environment: "
        "`uv run --project libs/gda-balancing pytest libs/gda-balancing/tests` "
        "(the entry point is what this e2e tier exists to prove)"
    )
    return script


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_console_script(), *argv], capture_output=True, text=True)


class TestEntryPoints:
    def test_both_entry_points_agree_on_the_valid_row(self):
        console = _run("version")
        module = subprocess.run(
            [sys.executable, "-m", "gda_balancing", "version"],
            capture_output=True,
            text=True,
        )
        assert (console.returncode, console.stderr) == (0, "")
        assert (module.returncode, module.stderr) == (0, "")
        assert console.stdout == module.stdout
        json.loads(console.stdout)

    def test_stream_separation_end_to_end(self):
        result = _run()
        assert (result.returncode, result.stdout) == (3, "")
        payload = json.loads(result.stderr)
        jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
        assert payload["error"]["category"] == "usage"
        assert payload["error"]["code"] == "missing_command"


class TestKeyUserPath:
    def test_validate_key_path(self, minimal_design_path):
        # The committed minimal-document golden, straight through the installed
        # console script and the OS file/argv boundary.
        result = _run("design", "validate", str(minimal_design_path))
        assert (result.returncode, result.stderr) == (0, "")
        assert result.stdout == '{"valid": true}\n'

    def test_refusal_key_path(self, tmp_path, minimal_design_path):
        doc = tmp_path / "doc.json"
        mutated = minimal_design_path.read_text(encoding="utf-8").replace(
            "1.0.0", "9.0.0"
        )
        doc.write_text(mutated, encoding="utf-8")
        result = _run("design", "validate", str(doc))
        assert (result.returncode, result.stderr) == (2, "")
        payload = json.loads(result.stdout)
        jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
        assert payload["error"]["category"] == "refusal"
        codes = {r["code"] for r in payload["error"]["refusals"]}
        assert codes == {"unsupported_schema_version"}

    def test_format_with_sink_key_path(self, tmp_path, minimal_design_path):
        sink = tmp_path / "canonical.json"
        bare = _run("design", "format", str(minimal_design_path))
        sunk = _run("design", "format", str(minimal_design_path), "--out", str(sink))
        assert (bare.returncode, bare.stderr) == (0, "")
        assert (sunk.returncode, sunk.stderr) == (0, "")
        # The sink holds exactly the artifact the bare invocation printed,
        # and the receipt names it (bADR-0009).
        assert sink.read_text(encoding="utf-8") == bare.stdout
        receipt = json.loads(sunk.stdout)["artifact"]
        assert receipt["path"] == str(sink.resolve())
        assert receipt["bytes"] == sink.stat().st_size

    def test_schema_get_key_path(self):
        result = _run("schema", "get", "structural")
        assert (result.returncode, result.stderr) == (0, "")
        artifact = json.loads(result.stdout)
        assert artifact["$id"].endswith("1.0.0")

    def test_template_instantiate_key_path(self, tmp_path):
        # The #505 key path: instantiate (`template get` is instantiate,
        # bADR-0012 — `--out` writes the consumer's starting document),
        # validate it, emit it canonically; then `template list` names it.
        doc = tmp_path / "my_design.json"
        got = _run("template", "get", "rpg", "--out", str(doc))
        assert (got.returncode, got.stderr) == (0, "")
        assert json.loads(got.stdout)["artifact"]["path"] == str(doc.resolve())
        validated = _run("design", "validate", str(doc))
        assert (validated.returncode, validated.stderr) == (0, "")
        assert validated.stdout == '{"valid": true}\n'
        emitted = _run("design", "format", str(doc))
        assert (emitted.returncode, emitted.stderr) == (0, "")
        assert emitted.stdout == doc.read_text(encoding="utf-8")
        listed = _run("template", "list")
        assert (listed.returncode, listed.stderr) == (0, "")
        assert any(t["id"] == "rpg" for t in json.loads(listed.stdout)["templates"])
