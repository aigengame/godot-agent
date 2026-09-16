#!/usr/bin/env python3
"""Prove a fixed A wheel and executable B harness for one priority baseline.

This is a prerequisite to #878 AC2, not the complete inventory/rename proof.
The manifest covers whole installed, harness, authority, and Python file trees;
it does not infer a build identity from a short list of support modules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


PACKAGE = Path(__file__).resolve().parents[1]
REPOSITORY = PACKAGE.parents[1]


class FreezeViolation(RuntimeError):
    """A frozen file, link, or directory changed after the manifest was sealed."""


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _tree(root: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(root.rglob("*")):
        row = {"path": path.relative_to(root).as_posix()}
        if path.is_symlink():
            row.update(kind="link", target=os.readlink(path))
            resolved = path.resolve(strict=True)
            if resolved.is_file():
                row["resolved_sha256"] = _sha(resolved)
            elif resolved.is_dir():
                row["resolved_kind"] = "directory"
            else:
                raise FreezeViolation(f"unsupported link target: {path}")
        elif path.is_file():
            row.update(kind="file", sha256=_sha(path))
        elif path.is_dir():
            row["kind"] = "directory"
        else:
            raise FreezeViolation(f"unsupported member: {path}")
        rows.append(row)
    return rows


def _snapshot(roots: dict[str, Path]) -> dict:
    return {
        name: {"root": str(root.resolve()), "members": _tree(root)}
        for name, root in roots.items()
    }


def verify_manifest(expected: dict, roots: dict[str, Path]) -> None:
    observed = _snapshot(roots)
    for name, record in expected.items():
        if record != observed.get(name):
            prior = {row["path"]: row for row in record["members"]}
            current = {row["path"]: row for row in observed[name]["members"]}
            changed = sorted(
                key
                for key in prior.keys() | current.keys()
                if prior.get(key) != current.get(key)
            )
            if not changed and record["root"] != observed[name]["root"]:
                changed = ["<root>"]
            raise FreezeViolation(f"{name}: changed membership/content: {changed[:12]}")
    if set(expected) != set(observed):
        raise FreezeViolation("freeze root membership changed")


def _command(args: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=REPOSITORY,
        env=env,
        capture_output=True,
        text=True,
        timeout=480,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {args}\n"
            f"stdout: {result.stdout[-3000:]}\nstderr: {result.stderr[-3000:]}"
        )
    return result.stdout


def run(proof: Path, uv: str) -> dict:
    if proof.exists():
        raise FileExistsError(f"proof directory already exists: {proof}")
    proof.mkdir(parents=True)
    wheel_dir = proof / "wheel"
    venv = proof / "venv"
    frozen = proof / "frozen"
    tests = frozen / "tests"
    harness = frozen / "harness"
    fixture = frozen / "fixture"
    output = proof / "output"
    wheel_dir.mkdir()
    harness.mkdir(parents=True)
    fixture.mkdir()
    output.mkdir()
    uv_env = {**os.environ, "UV_CACHE_DIR": str(proof / "uv-cache")}
    _command(
        [
            uv,
            "build",
            "--project",
            str(PACKAGE),
            "--wheel",
            "--out-dir",
            str(wheel_dir),
        ],
        env=uv_env,
    )
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    wheel = wheels[0]
    _command([uv, "venv", "--python", "3.13", str(venv)], env=uv_env)
    python = venv / "bin" / "python"
    _command(
        [uv, "pip", "install", "--python", str(python), str(wheel), "pytest>=9.0.3"],
        env=uv_env,
    )
    site_packages = venv / "lib" / "python3.13" / "site-packages"
    with zipfile.ZipFile(wheel) as archive:
        product_members = [
            name
            for name in archive.namelist()
            if name.startswith("gda_balancing/") and not name.endswith("/")
        ]
        for name in product_members:
            if (site_packages / name).read_bytes() != archive.read(name):
                raise FreezeViolation(f"installed A differs from wheel member: {name}")
    shutil.copytree(
        PACKAGE / "tests", tests, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    shutil.copytree(PACKAGE / "examples", frozen / "examples")
    for name in ("priority_build_freeze.py", "priority_build_freeze_worker.py"):
        shutil.copy2(PACKAGE / "tools" / name, harness / name)
    shutil.copy2(
        PACKAGE / "tools" / "priority_freeze_sitecustomize.py",
        harness / "sitecustomize.py",
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(tests),
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_CACHE_DIR": str(proof / "uv-cache"),
    }
    installed_origin = _command(
        [str(python), "-c", "import gda_balancing; print(gda_balancing.__file__)"],
        env=env,
    ).strip()
    if not Path(installed_origin).is_relative_to(venv):
        raise AssertionError(f"A did not load installed wheel: {installed_origin}")
    _command(
        [
            str(python),
            str(harness / "priority_build_freeze_worker.py"),
            "prepare",
            str(fixture),
        ],
        env=env,
    )
    stdlib = Path(
        _command(
            [
                str(python),
                "-c",
                "import sysconfig; print(sysconfig.get_path('stdlib'))",
            ],
            env=env,
        ).strip()
    )
    interpreter = python.resolve(strict=True)
    roots = {
        "a_wheel": wheel_dir,
        "installed_dependencies_and_a": venv,
        "b_harness_and_shared_data": frozen,
        "python_stdlib": stdlib,
        "python_executable": interpreter,
    }
    # An executable is a file, unlike the four directory roots.
    manifest = _snapshot({name: root for name, root in roots.items() if root.is_dir()})
    manifest["python_executable"] = {
        "root": str(interpreter),
        "members": [
            {"path": interpreter.name, "kind": "file", "sha256": _sha(interpreter)}
        ],
    }
    (proof / "manifest.before.json").write_bytes(_canonical(manifest))

    # The same manifest is checked before and after execution; no build occurs
    # between these checks. All run outputs are outside the frozen roots.
    verify_manifest(
        {
            name: value
            for name, value in manifest.items()
            if name != "python_executable"
        },
        {name: root for name, root in roots.items() if root.is_dir()},
    )
    _command(
        [
            str(python),
            str(harness / "priority_build_freeze_worker.py"),
            "exercise",
            str(fixture),
            "--output",
            str(output),
        ],
        env=env,
    )
    after = _snapshot({name: root for name, root in roots.items() if root.is_dir()})
    after["python_executable"] = {
        "root": str(interpreter),
        "members": [
            {"path": interpreter.name, "kind": "file", "sha256": _sha(interpreter)}
        ],
    }
    (proof / "manifest.after.json").write_bytes(_canonical(after))
    if after != manifest:
        raise FreezeViolation("pre/post fixed build manifests differ")
    result = json.loads((output / "result.json").read_text())
    allowed = (venv.resolve(), frozen.resolve(), stdlib.resolve())
    outside = [
        origin
        for origin in result["b_import_origins"]
        if not any(Path(origin).is_relative_to(root) for root in allowed)
    ]
    if outside:
        raise FreezeViolation(f"B imports outside frozen closure: {outside[:12]}")
    if not Path(result["a_package_origin"]).is_relative_to(venv):
        raise FreezeViolation("B's A helper import did not resolve to installed wheel")
    if not Path(result["b_harness_origin"]).is_relative_to(harness):
        raise FreezeViolation("B harness did not execute from frozen copy")
    if result["b_executable"] != str(interpreter):
        raise FreezeViolation("B harness used an unfrozen interpreter")
    if any(Path(path).is_relative_to(PACKAGE) for path in result["b_sys_path"]):
        raise FreezeViolation("B search path shadows the frozen harness with source")
    a_audits = [
        json.loads(path.read_text())
        for path in sorted(output.rglob("a-imports-*.json"))
    ]
    if len(a_audits) != 6:
        raise FreezeViolation(
            f"expected six A public process audits, got {len(a_audits)}"
        )
    for audit in a_audits:
        if audit["executable"] != str(interpreter):
            raise FreezeViolation("A process used an unfrozen interpreter")
        if not any(
            Path(audit["package_origin"]).is_relative_to(root)
            for root in (venv, fixture / "runtime")
        ):
            raise FreezeViolation(
                "A package import resolved outside fixed wheel/code copy"
            )
        process_roots = (venv.resolve(), stdlib.resolve(), harness.resolve())
        if Path(audit["package_origin"]).is_relative_to(fixture / "runtime"):
            process_roots += ((fixture / "runtime").resolve(),)
        foreign = [
            origin
            for origin in audit["import_origins"]
            if not any(Path(origin).is_relative_to(root) for root in process_roots)
        ]
        if foreign:
            raise FreezeViolation(f"A imports outside frozen closure: {foreign[:12]}")
        if any(Path(path).is_relative_to(PACKAGE) for path in audit["sys_path"]):
            raise FreezeViolation("A search path shadows the frozen wheel with source")
    direct_audits = [
        audit
        for audit in a_audits
        if Path(audit["package_origin"]).is_relative_to(venv)
    ]
    if len(direct_audits) != 3:
        raise FreezeViolation(
            "direct wheel public build/check/run did not all import installed A"
        )

    # Mutate exactly one byte in an expendable copy and demand refusal. The
    # original frozen harness remains untouched throughout the measurement.
    tamper = proof / "tamper"
    shutil.copytree(harness, tamper)
    target = tamper / "priority_build_freeze_worker.py"
    content = target.read_bytes()
    target.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    expected_harness = {
        "harness": {"root": str(tamper.resolve()), "members": _tree(harness)}
    }
    try:
        verify_manifest(expected_harness, {"harness": tamper})
    except FreezeViolation as error:
        tamper_refusal = str(error)
    else:
        raise AssertionError("single-byte tamper was not refused")
    b_members = [
        row
        for row in manifest["b_harness_and_shared_data"]["members"]
        if row["path"].startswith(("tests/", "harness/"))
    ]
    priority_a_members = [
        row
        for row in manifest["b_harness_and_shared_data"]["members"]
        if row["path"].startswith("fixture/runtime/")
    ]
    install_record = next(venv.rglob("gda_balancing-*.dist-info/RECORD"))
    summary = {
        "scope": "fixed-build prerequisite; not complete #878 AC2",
        "a_wheel_sha256": _sha(wheel),
        "a_wheel_install_record_sha256": _sha(install_record),
        "a_wheel_product_members_verified": len(product_members),
        "a_installed_tree_sha256": hashlib.sha256(
            _canonical(manifest["installed_dependencies_and_a"]["members"])
        ).hexdigest(),
        "a_priority_fixture_runtime_sha256": hashlib.sha256(
            _canonical(priority_a_members)
        ).hexdigest(),
        "b_executable_harness_sha256": hashlib.sha256(
            _canonical(b_members)
        ).hexdigest(),
        "b_shared_data_tree_sha256": hashlib.sha256(
            _canonical(
                [
                    row
                    for row in manifest["b_harness_and_shared_data"]["members"]
                    if row not in b_members and row not in priority_a_members
                ]
            )
        ).hexdigest(),
        "python_stdlib_tree_sha256": hashlib.sha256(
            _canonical(manifest["python_stdlib"])
        ).hexdigest(),
        "python_executable_sha256": _sha(interpreter),
        "full_manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "pre_post_manifests_equal": True,
        "frozen_member_counts": {
            name: len(value["members"]) for name, value in manifest.items()
        },
        "single_byte_tamper_refusal": tamper_refusal,
        "baseline": {
            key: value for key, value in result.items() if key != "b_import_origins"
        },
        "b_import_origin_count": len(result["b_import_origins"]),
        "a_public_processes": [
            {
                "executable": audit["executable"],
                "package_origin": audit["package_origin"],
                "sys_path": audit["sys_path"],
                "import_origin_count": len(audit["import_origins"]),
            }
            for audit in a_audits
        ],
        "missing_for_ac2": [
            "complete reachable non-Kernel inventory and exhaustive bijection",
            "fixed original/renamed A and B mutual artifact/result exchange",
            "baseline plus variant causal comparison over the full graph",
        ],
    }
    (proof / "receipt.json").write_bytes(
        json.dumps(summary, indent=2, sort_keys=True).encode() + b"\n"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--uv", default=shutil.which("uv") or "uv")
    args = parser.parse_args()
    print(json.dumps(run(args.proof_dir.resolve(), args.uv), indent=2, sort_keys=True))
