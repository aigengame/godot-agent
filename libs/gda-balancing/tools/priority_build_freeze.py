#!/usr/bin/env python3
"""Freeze independent A/B builds and run direct-wheel priority exchanges."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
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


def _snapshot(roots: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {"root": str(root.resolve()), "members": _tree(root)}
        for name, root in roots.items()
    }


def _file_snapshot(roots: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {
            "root": str(path.resolve(strict=True)),
            "members": [
                {
                    "path": path.resolve(strict=True).name,
                    "kind": "file",
                    "sha256": _sha(path.resolve(strict=True)),
                }
            ],
        }
        for name, path in roots.items()
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


def _command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path = REPOSITORY,
    timeout: int = 480,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {args}\n"
            f"stdout: {result.stdout[-4000:]}\nstderr: {result.stderr[-4000:]}"
        )
    return result.stdout


def _runtime_path(python: Path, expression: str, env: dict[str, str]) -> Path:
    return Path(
        _command([str(python), "-c", expression], env=env, cwd=python.parent).strip()
    )


def _verify_install_matches_wheel(
    wheel: Path, site_packages: Path
) -> tuple[int, list[str]]:
    with zipfile.ZipFile(wheel) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.startswith("gda_balancing/") and not name.endswith("/")
        ]
        for name in members:
            if (site_packages / name).read_bytes() != archive.read(name):
                raise FreezeViolation(f"installed package differs from wheel: {name}")
    return len(members), members


def _clean_env(base: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in base.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"}
    }


def run(proof: Path, uv: str) -> dict[str, Any]:
    if proof.exists():
        raise FileExistsError(f"proof directory already exists: {proof}")
    proof.mkdir(parents=True)
    wheel_dir = proof / "wheel"
    a_venv = proof / "a-venv"
    b_venv = proof / "b-venv"
    b_python_runtime = proof / "b-python-runtime"
    frozen = proof / "frozen"
    tests = frozen / "tests"
    harness = frozen / "harness"
    inputs = frozen / "inputs"
    output = proof / "output"
    wheel_dir.mkdir()
    harness.mkdir(parents=True)
    output.mkdir()
    uv_env = {
        **_clean_env(dict(os.environ)),
        "UV_CACHE_DIR": str(proof / "uv-cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
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
    if len(wheels) != 1:
        raise AssertionError(f"expected one wheel, got {wheels}")
    wheel = wheels[0]
    _command([uv, "venv", "--python", "3.13", str(a_venv)], env=uv_env)
    base_python = Path(
        _command([uv, "python", "find", "3.13"], env=uv_env).strip()
    ).resolve(strict=True)
    shutil.copytree(base_python.parents[1], b_python_runtime, symlinks=True)
    copied_b_python = b_python_runtime / "bin" / base_python.name
    _command([uv, "venv", "--python", str(copied_b_python), str(b_venv)], env=uv_env)
    a_python = a_venv / "bin" / "python"
    b_python = b_venv / "bin" / "python"
    _command([uv, "pip", "install", "--python", str(a_python), str(wheel)], env=uv_env)
    _command(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(b_python),
            str(wheel),
            "pytest>=9.0.3",
        ],
        env=uv_env,
    )

    a_env = _clean_env(uv_env)
    b_env = {
        **_clean_env(uv_env),
        "PYTHONPATH": os.pathsep.join((str(tests), str(harness))),
    }
    a_site_packages = _runtime_path(
        a_python,
        "import sysconfig; print(sysconfig.get_path('purelib'))",
        a_env,
    )
    b_site_packages = _runtime_path(
        b_python,
        "import sysconfig; print(sysconfig.get_path('purelib'))",
        b_env,
    )
    a_product_count, product_members = _verify_install_matches_wheel(
        wheel, a_site_packages
    )
    b_product_count, _ = _verify_install_matches_wheel(wheel, b_site_packages)
    if a_product_count != b_product_count:
        raise FreezeViolation("A and B installed different wheel member sets")

    shutil.copytree(
        PACKAGE / "tests", tests, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    for name in (
        "priority_build_freeze.py",
        "priority_build_freeze_worker.py",
        "priority_direct_wheel_driver.py",
    ):
        shutil.copy2(PACKAGE / "tools" / name, harness / name)
    worker = harness / "priority_build_freeze_worker.py"
    driver = harness / "priority_direct_wheel_driver.py"
    _command(
        [str(b_python), str(worker), "prepare", str(inputs)],
        env=b_env,
        cwd=output,
    )
    _command(
        [
            str(a_python),
            str(driver),
            "identify",
            "--output",
            str(inputs / "a-identity.json"),
        ],
        env=a_env,
        cwd=output,
    )
    _command(
        [
            str(b_python),
            str(worker),
            "identify",
            "--output",
            str(inputs / "b-identity.json"),
        ],
        env=b_env,
        cwd=output,
    )
    identities_before = {
        name: json.loads((inputs / f"{name}-identity.json").read_text())
        for name in ("a", "b")
    }
    if not Path(identities_before["a"]["package_origin"]).is_relative_to(
        a_site_packages
    ) or not Path(identities_before["b"]["package_origin"]).is_relative_to(
        b_site_packages
    ):
        raise FreezeViolation("A or B identity probe did not use its installed wheel")

    a_stdlib = _runtime_path(
        a_python,
        "import sysconfig; print(sysconfig.get_path('stdlib'))",
        a_env,
    )
    b_stdlib = _runtime_path(
        b_python,
        "import sysconfig; print(sysconfig.get_path('stdlib'))",
        b_env,
    )
    if a_python.resolve(strict=True) == b_python.resolve(
        strict=True
    ) or a_stdlib.resolve(strict=True) == b_stdlib.resolve(strict=True):
        raise FreezeViolation("B interpreter and stdlib are not independent from A")
    directory_roots = {
        "a_wheel": wheel_dir,
        "a_installed_environment": a_venv,
        "b_installed_environment": b_venv,
        "b_python_runtime": b_python_runtime,
        "b_harness_and_inputs": frozen,
        "a_python_stdlib": a_stdlib,
        "b_python_stdlib": b_stdlib,
    }
    file_roots = {
        "a_python_executable": a_python,
        "b_python_executable": b_python,
    }
    manifest = {
        **_snapshot(directory_roots),
        **_file_snapshot(file_roots),
    }
    (proof / "manifest.before.json").write_bytes(_canonical(manifest))
    verify_manifest({name: manifest[name] for name in directory_roots}, directory_roots)

    _command(
        [
            str(b_python),
            str(worker),
            "exercise",
            str(inputs),
            "--output",
            str(output),
            "--a-python",
            str(a_python),
            "--a-driver",
            str(driver),
            "--a-site-packages",
            str(a_site_packages),
            "--forbidden-source-root",
            str(PACKAGE),
        ],
        env=b_env,
        cwd=output,
        timeout=460,
    )
    after = {
        **_snapshot(directory_roots),
        **_file_snapshot(file_roots),
    }
    (proof / "manifest.after.json").write_bytes(_canonical(after))
    if after != manifest:
        raise FreezeViolation("pre/post fixed build manifests differ")

    result = json.loads((output / "result.json").read_text())
    identities_after = {
        "a": result["a_identity"],
        "b": result["b_identity"],
    }
    if identities_after != identities_before:
        raise FreezeViolation("A/B build identities changed after witness generation")
    b_allowed = (b_venv.resolve(), frozen.resolve(), b_stdlib.resolve())
    outside = [
        origin
        for origin in result["b_import_origins"]
        if not any(Path(origin).is_relative_to(root) for root in b_allowed)
    ]
    if outside:
        raise FreezeViolation(f"B imports outside frozen closure: {outside[:12]}")
    if not Path(result["b_package_origin"]).is_relative_to(b_site_packages):
        raise FreezeViolation("B did not import the installed support package")
    if not Path(result["b_harness_origin"]).is_relative_to(harness):
        raise FreezeViolation("B harness did not execute from its frozen copy")
    if result["b_executable"] != str(b_python.resolve(strict=True)):
        raise FreezeViolation("B harness used an unfrozen interpreter")
    if any(Path(path).is_relative_to(PACKAGE) for path in result["b_sys_path"]):
        raise FreezeViolation("B search path contains the source checkout")

    expected_a_invocations = 4 * sum(
        len(variants) for variants in result["matrix"].values()
    )
    if len(result["a_invocations"]) != expected_a_invocations:
        raise FreezeViolation("A did not execute all four public commands per case")
    a_package_root = (a_site_packages / "gda_balancing").resolve()
    for audit in result["a_invocations"]:
        if audit["executable"] != str(a_python.resolve(strict=True)):
            raise FreezeViolation("A invocation used an unfrozen interpreter")
        if Path(audit["package_origin"]).resolve().parent != a_package_root:
            raise FreezeViolation("A invocation did not import the installed wheel")
        if (
            not audit["module_origin_count"]
            or audit["all_module_origins_in_site_packages"] is not True
        ):
            raise FreezeViolation("an A module origin lies outside site-packages")
        if any(Path(path).is_relative_to(PACKAGE) for path in audit["sys_path"]):
            raise FreezeViolation("A search path contains the source checkout")

    tamper = proof / "tamper"
    shutil.copytree(harness, tamper)
    expected_tamper = _snapshot({"harness": tamper})
    target = tamper / "priority_direct_wheel_driver.py"
    content = target.read_bytes()
    target.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    try:
        verify_manifest(expected_tamper, {"harness": tamper})
    except FreezeViolation as error:
        tamper_refusal = str(error)
    else:
        raise AssertionError("single-byte tamper was not refused")

    install_record = next(a_venv.rglob("gda_balancing-*.dist-info/RECORD"))
    summary = {
        "scope": "direct installed-wheel priority Model and Experiment exchange",
        "a_wheel_sha256": _sha(wheel),
        "a_wheel_install_record_sha256": _sha(install_record),
        "a_wheel_product_members_verified": len(product_members),
        "a_installed_tree_sha256": hashlib.sha256(
            _canonical(manifest["a_installed_environment"])
        ).hexdigest(),
        "b_installed_tree_sha256": hashlib.sha256(
            _canonical(manifest["b_installed_environment"])
        ).hexdigest(),
        "b_executable_harness_sha256": hashlib.sha256(
            _canonical(manifest["b_harness_and_inputs"])
        ).hexdigest(),
        "a_python_stdlib_tree_sha256": hashlib.sha256(
            _canonical(manifest["a_python_stdlib"])
        ).hexdigest(),
        "b_python_stdlib_tree_sha256": hashlib.sha256(
            _canonical(manifest["b_python_stdlib"])
        ).hexdigest(),
        "a_python_executable_sha256": _sha(a_python.resolve(strict=True)),
        "b_python_executable_sha256": _sha(b_python.resolve(strict=True)),
        "build_identities": identities_before,
        "build_identities_pre_post_equal": True,
        "full_manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "pre_post_manifests_equal": True,
        "frozen_member_counts": {
            name: len(value["members"]) for name, value in manifest.items()
        },
        "single_byte_tamper_refusal": tamper_refusal,
        "matrix": result["matrix"],
        "selected_closure": result["selected_closure"],
        "a_invocations": result["a_invocations"],
        "b_import_origin_count": len(result["b_import_origins"]),
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
    print(
        json.dumps(
            run(args.proof_dir.resolve(), args.uv),
            indent=2,
            sort_keys=True,
        )
    )
