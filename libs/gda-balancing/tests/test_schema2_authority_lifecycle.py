"""Performance and isolation contracts for the packaged Schema 2.0 authority."""

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.domain.authority.context as authority_module
import gda_balancing.domain.authority.admission as bootstrap_module
import gda_balancing.domain.authority.contract_validation as contract_validation
import schema2_bootstrap_conformance_support as consumer_support
from gda_balancing.interfaces.cli.registry import REGISTRY
from gda_balancing.interfaces.cli.model_check import (
    ModelCheckInput,
    ModelCheckResult,
    run_model_check,
)
from gda_balancing.domain.authority.graph import LanguageBundleIndex


_PACKAGE_ROOT = Path(__file__).parents[1]
_SOURCE_ROOT = _PACKAGE_ROOT / "src" / "gda_balancing"
_RPG_MODEL_SOURCE = (
    _PACKAGE_ROOT / "examples" / "schema2" / "rpg-combat-cast" / "model-source.json"
)
_AUTHORITY_COMMANDS = tuple(
    descriptor
    for descriptor in REGISTRY
    if (descriptor.group, descriptor.command)
    in {
        (None, "version"),
        ("schema", "get"),
        ("experiment", "check"),
        ("experiment", "run"),
        ("model", "check"),
        ("model", "build"),
        ("model", "migrate"),
        ("template", "list"),
        ("template", "get"),
        ("template", "instantiate"),
        ("package", "list"),
        ("package", "get"),
    }
)


@pytest.fixture(autouse=True)
def _reset_packaged_authority_context_after_test():
    """Keep deliberate lifecycle mutations inside this module."""
    yield
    authority_module.reset_packaged_authority_context_for_tests()


def test_packaged_context_initialization_is_single_flight(monkeypatch):
    authority_module.reset_packaged_authority_context_for_tests()
    original = authority_module._load_packaged_authority_context_uncached
    calls = 0

    def observed():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        authority_module, "_load_packaged_authority_context_uncached", observed
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        contexts = list(
            executor.map(
                lambda _index: authority_module.packaged_authority_context(),
                range(16),
            )
        )

    assert calls == 1
    assert all(context is contexts[0] for context in contexts)
    assert authority_module.authority_lifecycle_metrics() == {
        "packaged_admission_attempts": 1,
        "packaged_context_published": 1,
        "packaged_refusal_published": 0,
    }


def test_concurrent_packaged_refusal_is_single_flight_and_deterministic(monkeypatch):
    authority_module.reset_packaged_authority_context_for_tests()
    calls = 0

    def refusing():
        nonlocal calls
        calls += 1
        raise authority_module.AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="kernel",
            message="deterministic test refusal",
        )

    monkeypatch.setattr(
        authority_module, "_load_packaged_authority_context_uncached", refusing
    )

    def observe(_index):
        try:
            authority_module.packaged_authority_context()
        except authority_module.AuthorityLoadError as err:
            return err.code, err.subject, err.message
        raise AssertionError("refusing packaged context unexpectedly succeeded")

    with ThreadPoolExecutor(max_workers=8) as executor:
        refusals = list(executor.map(observe, range(16)))

    assert calls == 1
    assert len(set(refusals)) == 1
    assert authority_module.authority_lifecycle_metrics() == {
        "packaged_admission_attempts": 1,
        "packaged_context_published": 0,
        "packaged_refusal_published": 1,
    }


def test_mutating_first_refusal_cannot_poison_cached_failure(monkeypatch):
    authority_module.reset_packaged_authority_context_for_tests()

    def refusing():
        raise authority_module.AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="kernel",
            message="deterministic test refusal",
        )

    monkeypatch.setattr(
        authority_module, "_load_packaged_authority_context_uncached", refusing
    )

    with pytest.raises(authority_module.AuthorityLoadError) as first:
        authority_module.packaged_authority_context()
    first.value.code = "poisoned"
    first.value.subject = "poisoned"
    first.value.message = "poisoned"

    with pytest.raises(authority_module.AuthorityLoadError) as later:
        authority_module.packaged_authority_context()

    assert later.value is not first.value
    assert (
        later.value.code,
        later.value.subject,
        later.value.message,
    ) == (
        "kernel.member_set_mismatch",
        "kernel",
        "deterministic test refusal",
    )


def test_packaged_context_exposes_no_nested_mutation_alias():
    authority_module.reset_packaged_authority_context_for_tests()
    context = authority_module.packaged_authority_context()
    assert isinstance(context.language_bundle, LanguageBundleIndex)
    kernel_identity = context.kernel["content_identity"]
    package_count = len(context.language_bundle["language"]["packages"])

    with pytest.raises(TypeError, match="immutable"):
        context.kernel["content_identity"] = "sha256:" + "0" * 64
    with pytest.raises(TypeError, match="immutable"):
        context.kernel["admission"]["laws"][0]["id"] = "changed"
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle["language"]["packages"].append({})
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle.root["content_identity"] = "sha256:" + "0" * 64
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle.package_releases[0]["id"] = "changed"
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle.package_conformance_vector_sets[0][
            "vector_definitions"
        ].append({})
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle.root = {}
    with pytest.raises(TypeError, match="immutable"):
        context.language_bundle.package_releases = []

    mutable_kernel, mutable_ldb = context.mutable_pair()
    mutable_kernel["content_identity"] = "sha256:" + "0" * 64
    mutable_ldb["language"]["packages"].clear()

    assert context.kernel["content_identity"] == kernel_identity
    assert len(context.language_bundle["language"]["packages"]) == package_count


def test_packaged_context_derives_immutable_replay_comparison_policy_index():
    context = authority_module.packaged_authority_context()

    assert context.replay_comparison_policy_index == {
        "exact-replay-v1": {
            "owner": {
                "package": "standard.experiment",
                "package_version": "1.1.0",
            },
            "policy": {
                "checks": [
                    "evaluation-outcome-status",
                    "event-trace-identity",
                    "snapshot-series-identity",
                    "metric-dataset-identity",
                ],
                "comparator": "canonical-equal",
                "id": "exact-replay-v1",
                "version": "1.0.0",
            },
        }
    }
    with pytest.raises(TypeError):
        cast(dict[str, Any], context.replay_comparison_policy_index)["other"] = {}
    with pytest.raises(TypeError, match="immutable"):
        context.replay_comparison_policy_index["exact-replay-v1"]["policy"][
            "version"
        ] = "2.0.0"
    with pytest.raises(TypeError, match="init=False"):
        replace(context, replay_comparison_policy_index={})


def test_mutable_builtin_descriptors_cannot_bypass_authority_freeze():
    authority_module.reset_packaged_authority_context_for_tests()
    context = authority_module.packaged_authority_context()
    language_bundle = cast(LanguageBundleIndex, context.language_bundle)
    before = (
        context.canonical_kernel_bytes,
        context.canonical_language_bundle_bytes,
        context.kernel["content_identity"],
        language_bundle["content_identity"],
    )

    with pytest.raises(TypeError):
        dict.__setitem__(context.kernel, "content_identity", "poisoned")
    with pytest.raises(TypeError):
        dict.__setitem__(context.kernel["admission"], "laws", [])
    with pytest.raises(TypeError):
        list.append(context.kernel["admission"]["laws"], {"id": "poisoned"})
    with pytest.raises(TypeError):
        dict.__setitem__(language_bundle, "content_identity", "poisoned")
    with pytest.raises(TypeError):
        dict.__setitem__(language_bundle.root, "content_identity", "poisoned")
    with pytest.raises(TypeError):
        list.append(language_bundle.package_releases, {})
    with pytest.raises(TypeError):
        list.append(
            language_bundle.package_conformance_vector_sets,
            {},
        )
    with pytest.raises(TypeError):
        list.append(language_bundle["language"]["packages"], {})

    later = authority_module.packaged_authority_context()
    assert later is context
    assert (
        later.canonical_kernel_bytes,
        later.canonical_language_bundle_bytes,
        later.kernel["content_identity"],
        later.language_bundle["content_identity"],
    ) == before


def test_refused_injected_context_cannot_poison_packaged_observations():
    authority_module.reset_packaged_authority_context_for_tests()
    baseline = authority_module.packaged_authority_context()
    before = (
        baseline.canonical_kernel_bytes,
        baseline.canonical_language_bundle_bytes,
        baseline.admission,
    )
    kernel, language_bundle = baseline.mutable_pair()
    kernel["content_identity"] = "sha256:" + "0" * 64

    refusal = authority_module.admit_authority_context(kernel, language_bundle)

    assert not isinstance(refusal, authority_module.AdmittedAuthorityContext)
    later = authority_module.packaged_authority_context()
    assert later is baseline
    assert (
        later.canonical_kernel_bytes,
        later.canonical_language_bundle_bytes,
        later.admission,
    ) == before


def test_production_schema_meta_validation_cache_binds_actual_bytes_and_profile(
    monkeypatch,
):
    contract_validation.reset_schema_meta_validation_cache_for_tests()
    production_check_schema = (
        bootstrap_module.jsonschema.Draft202012Validator.check_schema
    )
    calls: list[dict[str, Any]] = []

    def observed(schema):
        calls.append(schema)
        return production_check_schema(schema)

    monkeypatch.setattr(
        bootstrap_module.jsonschema.Draft202012Validator,
        "check_schema",
        observed,
    )
    kernel, language_bundle = authority_module.load_authorities()

    first = bootstrap_module.admit_authorities(kernel, language_bundle)
    second = bootstrap_module.admit_authorities(kernel, language_bundle)

    assert first.admitted is True
    assert second == first
    assert calls
    assert len(calls) == len(
        {bootstrap_module.canonical_bytes(schema) for schema in calls}
    )
    info = contract_validation.schema_meta_validation_cache_info()
    assert info.hits >= len(calls)
    assert info.misses == len(calls)


def test_schema_meta_validation_cache_misses_for_changed_bytes_or_profile():
    contract_validation.reset_schema_meta_validation_cache_for_tests()
    first_schema = bootstrap_module.canonical_bytes(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "string",
        }
    )
    changed_schema = bootstrap_module.canonical_bytes(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "minLength": 1,
            "type": "string",
        }
    )
    first_profile = bootstrap_module.canonical_bytes({"profile": "one"})
    changed_profile = bootstrap_module.canonical_bytes({"profile": "two"})

    assert bootstrap_module._meta_validate_json_schema(first_schema, first_profile)
    assert bootstrap_module._meta_validate_json_schema(first_schema, first_profile)
    assert bootstrap_module._meta_validate_json_schema(changed_schema, first_profile)
    assert bootstrap_module._meta_validate_json_schema(first_schema, changed_profile)

    info = contract_validation.schema_meta_validation_cache_info()
    assert (info.hits, info.misses) == (1, 3)


def test_consumer_b_owns_an_independent_meta_validation_cache_domain():
    contract_validation.reset_schema_meta_validation_cache_for_tests()
    consumer_support._consumer_b_meta_validate_schema.cache_clear()
    schema = consumer_support._encoded(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "integer",
        }
    )
    profile = consumer_support._encoded({"profile": "consumer-b"})

    assert consumer_support._consumer_b_meta_validate_schema(schema, profile)
    assert consumer_support._consumer_b_meta_validate_schema(schema, profile)

    assert consumer_support._consumer_b_meta_validate_schema.cache_info().hits == 1
    assert contract_validation.schema_meta_validation_cache_info().currsize == 0


def test_cold_model_check_performs_one_packaged_graph_admission(monkeypatch):
    authority_module.reset_packaged_authority_context_for_tests()
    production_admit = authority_module.admit_authorities
    calls = 0

    def observed(kernel, graph):
        nonlocal calls
        calls += 1
        return production_admit(kernel, graph)

    monkeypatch.setattr(authority_module, "admit_authorities", observed)
    result = run_model_check(ModelCheckInput(source=str(_RPG_MODEL_SOURCE)))

    assert isinstance(result, ModelCheckResult)
    assert calls == 1


@pytest.mark.parametrize(
    "descriptor",
    _AUTHORITY_COMMANDS,
    ids=lambda descriptor: " ".join(
        part for part in (descriptor.group, descriptor.command) if part
    ),
)
def test_each_cold_public_authority_command_performs_one_packaged_admission(
    descriptor,
    invocation,
    run_cli,
    monkeypatch,
):
    argv = invocation(descriptor)
    authority_module.reset_packaged_authority_context_for_tests()
    original = authority_module._load_packaged_authority_context_uncached
    calls = 0

    def observed():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        authority_module, "_load_packaged_authority_context_uncached", observed
    )

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stderr) == (0, ""), stdout
    assert calls == 1
    assert (
        authority_module.authority_lifecycle_metrics()["packaged_admission_attempts"]
        == 1
    )


def test_authority_lifecycle_module_is_the_only_packaged_production_owner():
    forbidden_calls = {"load_authorities", "load_descriptor_authorities"}
    forbidden_admission = {"admit_authorities"}
    violations: list[str] = []

    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(_SOURCE_ROOT)
        if relative.as_posix() in {
            "domain/authority/admission.py",
            "domain/authority/context.py",
        }:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                leaked = names & (forbidden_calls | forbidden_admission)
                if leaked:
                    violations.append(
                        f"{relative}:{node.lineno}: imports {sorted(leaked)}"
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls | forbidden_admission
            ):
                violations.append(f"{relative}:{node.lineno}: calls {node.func.id}")

    assert violations == []


def test_consumer_b_functions_do_not_call_production_admission_or_cache():
    path = Path(consumer_support.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {
            "gda_balancing.domain.authority.context",
            "gda_balancing.domain.authority.admission",
        }:
            violations.append(f"module:{node.lineno}:{node.module}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {
                    "gda_balancing.domain.authority.context",
                    "gda_balancing.domain.authority.admission",
                }:
                    violations.append(f"module:{node.lineno}:{alias.name}")

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_consumer_b"):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in {
                "admit_authorities",
                "production_bootstrap",
                "_meta_validate_json_schema",
            }:
                violations.append(f"{node.name}:{child.lineno}:{child.id}")

    assert violations == []
