"""Domain tests for structural RIR program reachability."""

from typing import Any

import gda_balancing.domain.program_reachability as program_reachability_module


def test_projects_nested_operation_only_structure():
    rir = {
        "selected_semantics": {
            "packages": [{"id": "example.program"}],
            "operations": [
                {
                    "package": "example.program",
                    "definition": {
                        "id": "root",
                        "body": [
                            {
                                "node": "invoke",
                                "operation": {
                                    "package": "example.program",
                                    "id": "invoked",
                                },
                            },
                            {
                                "node": "schedule",
                                "operation": {
                                    "package": "example.program",
                                    "id": "scheduled",
                                },
                            },
                        ],
                    },
                },
                {
                    "package": "example.program",
                    "definition": {"id": "invoked", "body": [{"node": "add"}]},
                },
                {
                    "package": "example.program",
                    "definition": {
                        "id": "scheduled",
                        "body": [{"node": "subtract"}],
                    },
                },
            ],
        },
        "initialization_programs": [],
    }
    entrypoint = {
        "operation": {
            "package": "example.program",
            "id": "root",
        },
        "arguments": [],
    }

    projected = program_reachability_module.project_reachable_program_structure(
        rir, [entrypoint]
    )

    assert projected.operation_coordinates == {
        ("example.program", "root"),
        ("example.program", "invoked"),
        ("example.program", "scheduled"),
    }
    assert projected.runtime_node_ids == {"add", "invoke", "schedule", "subtract"}
    assert all(
        projected.formula_programs.for_phase(phase) == ()
        for phase in program_reachability_module.LIFECYCLE_PHASES
    )


def test_groups_formula_programs_by_lifecycle_phase():
    target = {"model": "example", "module": "main", "name": "derived"}

    def formula_program(phase: str, node: str) -> dict[str, Any]:
        return {
            "site": {"context": {"phase": phase}},
            "target": target,
            "inputs": [],
            "body": [{"instruction": {"node": node}}],
        }

    rir = {
        "selected_semantics": {
            "packages": [{"id": "example.program"}],
            "operations": [
                {
                    "package": "example.program",
                    "definition": {"id": "root", "body": [{"node": "copy"}]},
                }
            ],
        },
        "initialization_programs": [
            formula_program("initialization", "add"),
            formula_program("event", "multiply"),
            formula_program("observation", "subtract"),
        ],
    }
    entrypoint = {
        "operation": {
            "package": "example.program",
            "id": "root",
        },
        "arguments": [{"operand": {"kind": "symbol", "symbol": target}}],
    }

    projected = program_reachability_module.project_reachable_program_structure(
        rir, [entrypoint]
    )

    assert projected.runtime_node_ids == {"add", "copy", "multiply", "subtract"}
    for phase, node in (
        ("initialization", "add"),
        ("event", "multiply"),
        ("observation", "subtract"),
    ):
        programs = projected.formula_programs.for_phase(phase)
        assert len(programs) == 1
        assert programs[0]["body"][0]["instruction"]["node"] == node
