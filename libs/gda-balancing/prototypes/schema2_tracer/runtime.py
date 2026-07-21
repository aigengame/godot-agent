from __future__ import annotations

import copy
import hashlib
import heapq
from dataclasses import dataclass, field
from typing import Any

from bundle import LanguageBundle
from canonical import content_identity, identified
from refusals import Refusal, runtime_location


_PHASE_INDEX = {"input": 0, "transition": 1, "observation": 2}
_EXPERIMENT_FIELDS = {
    "artifact_kind",
    "effective_seed",
    "external_inputs",
    "metrics",
    "partition",
    "replication_id",
    "resolved_model_identity",
    "runtime_profile",
}


@dataclass(order=True)
class Event:
    sort_key: tuple[int, int, int, int]
    event_id: str = field(compare=False)
    time: int = field(compare=False)
    phase: str = field(compare=False)
    priority: int = field(compare=False)
    sequence: int = field(compare=False)
    operation: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False)
    zero_time_depth: int = field(compare=False)

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        time: int,
        phase: str,
        priority: int,
        sequence: int,
        operation: str,
        payload: dict[str, Any],
        zero_time_depth: int,
    ) -> Event:
        return cls(
            (time, _PHASE_INDEX[phase], -priority, sequence),
            event_id,
            time,
            phase,
            priority,
            sequence,
            operation,
            payload,
            zero_time_depth,
        )


@dataclass(frozen=True)
class RuntimeArtifacts:
    trace: dict[str, Any]
    final_snapshot: dict[str, Any]
    metric_dataset: dict[str, Any]
    evaluation_run: dict[str, Any]
    evidence_assertions: tuple[dict[str, Any], ...]


def _experiment_refusal(
    experiment: dict[str, Any], code: str, message: str, pointer: str
) -> Refusal:
    return Refusal(
        "evaluation",
        code,
        message,
        {
            "artifact_identity": content_identity(
                {"artifact_kind": "experiment-specification", "content": experiment}
            ),
            "kind": "artifact",
            "pointer": pointer,
        },
    )


def validate_experiment_envelope(experiment: dict[str, Any]) -> None:
    if set(experiment) != _EXPERIMENT_FIELDS:
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.experiment-shape",
            "Experiment Specification does not match the closed tracer shape",
            "",
        )
    if not isinstance(experiment["resolved_model_identity"], str):
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.experiment-field-type",
            "resolved_model_identity must be a string",
            "/resolved_model_identity",
        )


def validate_experiment(
    experiment: dict[str, Any], rir: dict[str, Any], bundle: LanguageBundle
) -> None:
    validate_experiment_envelope(experiment)
    if (
        not isinstance(experiment["effective_seed"], int)
        or isinstance(experiment["effective_seed"], bool)
        or experiment["effective_seed"] < 0
        or not isinstance(experiment["partition"], str)
        or not isinstance(experiment["replication_id"], str)
        or not isinstance(experiment["runtime_profile"], str)
    ):
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.experiment-field-type",
            "Experiment Specification scalar fields have invalid types",
            "",
        )
    if experiment["resolved_model_identity"] != rir.get("identity"):
        raise _experiment_refusal(
            experiment,
            "schema2.experiment.model-identity-mismatch",
            "Experiment Specification does not bind the supplied Resolved Model",
            "/resolved_model_identity",
        )

    external_inputs = experiment["external_inputs"]
    if not isinstance(external_inputs, list) or not external_inputs:
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.external-input-shape",
            "external_inputs must be a non-empty list",
            "/external_inputs",
        )
    input_fields = {"payload", "priority", "source_id", "source_sequence", "time"}
    payload_fields = {"actor", "handler", "transition_priority"}
    for index, input_record in enumerate(external_inputs):
        valid_shape = (
            isinstance(input_record, dict) and set(input_record) == input_fields
        )
        payload = (
            input_record.get("payload") if isinstance(input_record, dict) else None
        )
        valid_payload = isinstance(payload, dict) and set(payload) == payload_fields
        scalar_types_valid = valid_shape and all(
            isinstance(input_record[name], int)
            and not isinstance(input_record[name], bool)
            for name in ("priority", "source_sequence", "time")
        )
        payload_types_valid = (
            isinstance(payload, dict)
            and all(isinstance(payload[name], str) for name in ("actor", "handler"))
            and isinstance(payload["transition_priority"], int)
        )
        if not (
            valid_shape and valid_payload and scalar_types_valid and payload_types_valid
        ):
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.external-input-shape",
                "external input does not match the closed tracer shape",
                f"/external_inputs/{index}",
            )

    entities = {
        entity["entity_id"]: entity for entity in rir["content"].get("entities", [])
    }
    type_units = bundle.document["semantic_kernel"].get("type_units")
    if not isinstance(type_units, dict):
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.unit-registry-missing",
            "Language Definition Bundle has no explicit type-to-unit registry",
            "/metrics",
        )
    metrics = experiment["metrics"]
    if not isinstance(metrics, list) or not metrics:
        raise _experiment_refusal(
            experiment,
            "schema2.evaluation.metric-shape",
            "metrics must be a non-empty list",
            "/metrics",
        )
    metric_fields = {
        "aggregation",
        "dimensions",
        "entity",
        "field",
        "id",
        "missing",
        "type",
        "unit",
        "window",
    }
    seen_metric_ids: set[str] = set()
    for index, metric in enumerate(metrics):
        pointer = f"/metrics/{index}"
        if not isinstance(metric, dict) or set(metric) != metric_fields:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-shape",
                "Metric definition does not match the closed tracer shape",
                pointer,
            )
        if not all(
            isinstance(metric[name], str)
            for name in (
                "aggregation",
                "entity",
                "field",
                "id",
                "missing",
                "type",
                "unit",
                "window",
            )
        ):
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-field-type",
                "Metric scalar fields must be strings",
                pointer,
            )
        if metric["id"] in seen_metric_ids:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-id-duplicate",
                f"duplicate Metric id {metric['id']}",
                f"{pointer}/id",
            )
        seen_metric_ids.add(metric["id"])
        if metric["dimensions"] != ["entity"]:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-dimensions",
                "tracer Metric dimensions must be exactly [entity]",
                f"{pointer}/dimensions",
            )
        entity = entities.get(metric["entity"])
        field = entity.get("fields", {}).get(metric["field"]) if entity else None
        if field is None:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-source-missing",
                "Metric entity/field does not exist in RIR",
                pointer,
            )
        if metric["type"] != field["type"]:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-type-mismatch",
                f"Metric type {metric['type']} does not match slot type {field['type']}",
                f"{pointer}/type",
            )
        expected_unit = type_units.get(metric["type"])
        if expected_unit is None or metric["unit"] != expected_unit:
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-unit-mismatch",
                f"Metric unit {metric['unit']} does not match LDB unit {expected_unit}",
                f"{pointer}/unit",
            )
        if (
            metric["aggregation"] != "last"
            or metric["missing"] != "refuse"
            or metric["window"] != "encounter-end"
        ):
            raise _experiment_refusal(
                experiment,
                "schema2.evaluation.metric-policy",
                "tracer supports only aggregation=last, missing=refuse, and "
                "window=encounter-end",
                pointer,
            )


class Transaction:
    def __init__(self, runtime: Runtime, event: Event) -> None:
        self.runtime = runtime
        self.event = event
        self.snapshot = runtime.state
        self.writes: dict[tuple[str, str], dict[str, Any]] = {}
        self.children: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self.reads: list[str] = []
        self.locals: dict[str, Any] = {}
        self.signal_payload: dict[str, Any] | None = None
        self.rng_counters = dict(runtime.rng_counters)
        self.rng_draws: list[dict[str, Any]] = []
        self.metric_samples: list[dict[str, Any]] = []

    def read_field(self, entity_id: str, field_name: str) -> dict[str, Any]:
        try:
            value = self.snapshot["entities"][entity_id]["fields"][field_name]
        except KeyError as exc:
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.missing-state",
                f"missing state slot {entity_id}.{field_name}",
            ) from exc
        self.reads.append(f"{entity_id}.{field_name}")
        return value

    def write_field(
        self, entity_id: str, field_name: str, typed_value: dict[str, Any]
    ) -> None:
        key = (entity_id, field_name)
        if key in self.writes:
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.multiple-final-writes",
                f"multiple final writes to {entity_id}.{field_name}",
            )
        self.writes[key] = typed_value

    def schedule(
        self,
        *,
        time: int,
        phase: str,
        priority: int,
        operation: str,
        payload: dict[str, Any],
    ) -> None:
        if phase not in _PHASE_INDEX:
            raise self.runtime.runtime_refusal(
                self.event, "schema2.runtime.unknown-phase", f"unknown phase {phase}"
            )
        if phase == "input":
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.model-input-schedule",
                "model operations cannot schedule input events",
            )
        candidate_prefix = (time, _PHASE_INDEX[phase], -priority)
        active_prefix = self.event.sort_key[:3]
        if candidate_prefix < active_prefix or (
            candidate_prefix == active_prefix and priority > self.event.priority
        ):
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.cursor-backward",
                "child event ordering key would sort before the active cursor",
            )
        if (
            time == self.event.time
            and phase == self.event.phase
            and priority > self.event.priority
        ):
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.cursor-backward",
                "same-phase child priority exceeds the active event priority",
            )
        if self.event.phase == "observation" and time == self.event.time:
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.observation-schedule",
                "observation cannot schedule at the same logical time",
            )
        self.children.append(
            {
                "operation": operation,
                "payload": payload,
                "phase": phase,
                "priority": priority,
                "time": time,
                "zero_time_depth": (
                    self.event.zero_time_depth + 1 if time == self.event.time else 0
                ),
            }
        )

    def draw_percent(self, stream: str) -> int:
        if stream not in self.runtime.admitted_streams:
            raise self.runtime.runtime_refusal(
                self.event,
                "schema2.runtime.stream-not-admitted",
                f"Named random stream is not admitted by the Runtime profile: {stream}",
            )
        counter = self.rng_counters.get(stream, 0)
        material = f"sha256-counter-v1\x00{self.runtime.seed}\x00{stream}\x00{counter}".encode()
        raw = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        value = raw % 100
        self.rng_counters[stream] = counter + 1
        self.rng_draws.append(
            {
                "algorithm": "sha256-counter-v1",
                "counter": counter,
                "mapping": "uint64-be-mod-100",
                "stream": stream,
                "value": value,
            }
        )
        return value

    def emit_signal(self, signal_id: str, payload: dict[str, Any]) -> None:
        self.signals.append({"payload": payload, "signal": signal_id})
        subscribers = sorted(
            subscription["handler"]
            for subscription in self.runtime.rir["content"]["subscriptions"]
            if subscription["signal"] == signal_id
        )
        for subscriber in subscribers:
            previous = self.signal_payload
            self.signal_payload = payload
            self.runtime.execute_handler(subscriber, self)
            self.signal_payload = previous


class Runtime:
    def __init__(
        self,
        *,
        rir: dict[str, Any],
        bundle: LanguageBundle,
        experiment: dict[str, Any],
        seed: int,
    ) -> None:
        self.rir = rir
        self.bundle = bundle
        self.experiment = experiment
        self.seed = seed
        self.handlers = {
            handler["id"]: handler for handler in rir["content"]["handlers"]
        }
        self.declaration_values = self._evaluate_declarations()
        self.state = {
            "declarations": copy.deepcopy(self.declaration_values),
            "entities": {
                entity["entity_id"]: {
                    "entity_type": entity["entity_type"],
                    "fields": copy.deepcopy(entity["fields"]),
                }
                for entity in rir["content"]["entities"]
            },
        }
        self.queue: list[Event] = []
        self.sequence = 0
        self.rng_counters: dict[str, int] = {}
        self.trace_entries: list[dict[str, Any]] = []
        self.metric_samples: list[dict[str, Any]] = []
        self.evaluator_identity = content_identity(
            {"evaluator": "schema2-tracer-reference", "version": 1}
        )
        self.tool_identity = content_identity(
            {"tool": "gda-balancing-schema2-tracer", "version": 1}
        )
        self.runtime_profile = self._runtime_profile()
        profile_content = self.runtime_profile["content"]
        self.budgets = profile_content["budgets"]
        self.admitted_streams = frozenset(profile_content["named_streams"])
        self.events_dispatched = 0
        experiment_identity = content_identity(
            {"artifact_kind": "experiment-specification", "content": experiment}
        )
        self.run_id = content_identity(
            {
                "experiment_identity": experiment_identity,
                "resolved_model_identity": rir["identity"],
                "runtime_profile_identity": self.runtime_profile["identity"],
                "seed": seed,
            }
        )

    def _runtime_profile(self) -> dict[str, Any]:
        profile_id = self.experiment["runtime_profile"]
        profiles = {
            profile["id"]: profile
            for profile in self.bundle.document["runtime_profiles"]
        }
        if profile_id not in profiles:
            raise Refusal(
                "evaluation",
                "schema2.experiment.unknown-runtime-profile",
                f"unknown Runtime profile {profile_id}",
                {"kind": "invocation"},
            )
        return identified(
            "runtime-profile",
            {
                **profiles[profile_id],
                "bundle_identity": self.bundle.identity,
                "evaluator_identity": self.evaluator_identity,
            },
        )

    def _evaluate_declarations(self) -> dict[str, dict[str, Any]]:
        pending = {item["id"]: item for item in self.rir["content"]["declarations"]}
        values: dict[str, dict[str, Any]] = {}
        while pending:
            progressed = False
            for symbol_id in sorted(tuple(pending)):
                declaration = pending[symbol_id]
                if "value" in declaration:
                    values[symbol_id] = {
                        "type": declaration["type"],
                        "value": declaration["value"],
                    }
                else:
                    try:
                        value = self._eval_static_expression(
                            declaration["expression"], values
                        )
                    except KeyError:
                        continue
                    values[symbol_id] = {"type": declaration["type"], "value": value}
                del pending[symbol_id]
                progressed = True
            if not progressed:
                raise Refusal(
                    "resolution",
                    "schema2.lowering.declaration-cycle",
                    "declaration graph is cyclic after lowering",
                    {
                        "kind": "artifact",
                        "artifact_identity": self.rir["identity"],
                        "pointer": "/content/declarations",
                    },
                )
        return values

    def _eval_static_expression(
        self, expression: dict[str, Any], values: dict[str, dict[str, Any]]
    ) -> Any:
        if "read_symbol" in expression:
            return values[expression["read_symbol"]]["value"]
        if "literal" in expression:
            return expression["literal"]
        if expression.get("kernel") == "exact.add":
            return sum(
                self._eval_static_expression(argument, values)
                for argument in expression["args"]
            )
        raise KeyError("unresolved static expression")

    def snapshot(self) -> dict[str, Any]:
        queue_projection = [
            {
                "event_id": event.event_id,
                "operation": event.operation,
                "phase": event.phase,
                "priority": event.priority,
                "sequence": event.sequence,
                "time": event.time,
                "zero_time_depth": event.zero_time_depth,
            }
            for event in sorted(self.queue)
        ]
        return identified(
            "runtime-snapshot",
            {
                "queue": queue_projection,
                "rng_counters": dict(sorted(self.rng_counters.items())),
                "state": self.state,
            },
        )

    def runtime_refusal(self, event: Event, code: str, message: str) -> Refusal:
        snapshot = self.snapshot()
        return Refusal(
            "runtime",
            code,
            message,
            runtime_location(self.run_id, event.event_id, snapshot["identity"]),
        )

    def enqueue(
        self,
        *,
        time: int,
        phase: str,
        priority: int,
        operation: str,
        payload: dict[str, Any],
        zero_time_depth: int = 0,
    ) -> Event:
        if len(self.queue) >= self.budgets["max_queue"]:
            raise Refusal(
                "runtime",
                "schema2.runtime.queue-budget",
                "Runtime profile queue budget exhausted",
                {"kind": "invocation"},
            )
        if zero_time_depth > self.budgets["max_zero_time_depth"]:
            raise Refusal(
                "runtime",
                "schema2.runtime.zero-time-depth-budget",
                "Runtime profile zero-time derivation depth exhausted",
                {"kind": "invocation"},
            )
        sequence = self.sequence
        self.sequence += 1
        event_id = content_identity(
            {
                "operation": operation,
                "payload": payload,
                "phase": phase,
                "priority": priority,
                "run_id": self.run_id,
                "sequence": sequence,
                "time": time,
                "zero_time_depth": zero_time_depth,
            }
        )
        event = Event.create(
            event_id=event_id,
            time=time,
            phase=phase,
            priority=priority,
            sequence=sequence,
            operation=operation,
            payload=payload,
            zero_time_depth=zero_time_depth,
        )
        heapq.heappush(self.queue, event)
        return event

    def _initialize_inputs(self) -> None:
        previous_by_source: dict[str, int] = {}
        for input_record in sorted(
            self.experiment["external_inputs"],
            key=lambda item: (item["source_id"], item["source_sequence"]),
        ):
            source_id = input_record["source_id"]
            source_sequence = input_record["source_sequence"]
            previous = previous_by_source.get(source_id)
            if previous is not None and source_sequence != previous + 1:
                raise Refusal(
                    "runtime",
                    "schema2.runtime.input-sequence",
                    "external input sequence must be contiguous per source",
                    {"kind": "invocation"},
                )
            previous_by_source[source_id] = source_sequence
            self.enqueue(
                time=input_record["time"],
                phase="input",
                priority=input_record["priority"],
                operation="core.input.admit@1",
                payload=input_record["payload"],
            )

    def _eval_argument(self, expression: dict[str, Any], tx: Transaction) -> Any:
        if "literal" in expression:
            return expression["literal"]
        if "read_symbol" in expression:
            return self.declaration_values[expression["read_symbol"]]["value"]
        if "event_field" in expression:
            return tx.event.payload[expression["event_field"]]
        if "signal_field" in expression:
            if tx.signal_payload is None:
                raise self.runtime_refusal(
                    tx.event,
                    "schema2.runtime.missing-signal-context",
                    "signal argument used outside Signal delivery",
                )
            return tx.signal_payload[expression["signal_field"]]
        if "local" in expression:
            return tx.locals[expression["local"]]
        if expression.get("kernel") == "exact.add":
            return sum(
                self._eval_argument(argument, tx) for argument in expression["args"]
            )
        raise self.runtime_refusal(
            tx.event,
            "schema2.runtime.unknown-expression",
            "RIR contains an unknown expression",
        )

    def execute_handler(self, handler_id: str, tx: Transaction) -> None:
        try:
            handler = self.handlers[handler_id]
        except KeyError as exc:
            raise self.runtime_refusal(
                tx.event,
                "schema2.runtime.unknown-handler",
                f"unknown RIR handler {handler_id}",
            ) from exc
        for call in handler["calls"]:
            arguments = {
                name: self._eval_argument(expression, tx)
                for name, expression in call["arguments"].items()
            }
            result = self.execute_primitive(call["primitive"], arguments, tx)
            if call["bind"] is not None:
                tx.locals[call["bind"]] = result

    def execute_primitive(
        self, primitive: str, arguments: dict[str, Any], tx: Transaction
    ) -> Any:
        if primitive == "query.select-target":
            actor = arguments["actor"]
            target_team = arguments["target_team"]
            candidates: list[str] = []
            for entity_id in sorted(tx.snapshot["entities"]):
                if entity_id == actor:
                    continue
                team = tx.read_field(entity_id, "team")["value"]
                active = tx.read_field(entity_id, "active")["value"]
                if team == target_team and active:
                    candidates.append(entity_id)
            if not candidates:
                raise self.runtime_refusal(
                    tx.event,
                    "game.query.empty-target",
                    "target query produced no entity",
                )
            return candidates[0]

        if primitive == "resource.reserve":
            actor = arguments["actor"]
            slot = arguments["slot"]
            amount = arguments["amount"]
            current = tx.read_field(actor, slot)["value"]
            return {
                "actor": actor,
                "amount": amount,
                "before": current,
                "slot": slot,
                "status": "reserved" if current >= amount else "insufficient",
            }

        if primitive == "check.named-percent":
            hit_draw = tx.draw_percent(arguments["hit_stream"])
            critical_draw = tx.draw_percent(arguments["critical_stream"])
            return {
                "critical": critical_draw < arguments["critical_threshold"],
                "critical_draw": critical_draw,
                "hit": hit_draw < arguments["hit_threshold"],
                "hit_draw": hit_draw,
            }

        if primitive == "combat.staged-damage":
            target = arguments["target"]
            check = arguments["check"]
            power = arguments["power"]
            raw = power if check["hit"] else 0
            critical = raw * 2 if check["critical"] else raw
            mitigation = tx.read_field(target, "mitigation")["value"]
            after_mitigation = max(0, critical - mitigation)
            shield_before = tx.read_field(target, "shield")["value"]
            absorbed = min(shield_before, after_mitigation)
            shield_after = shield_before - absorbed
            health_damage = after_mitigation - absorbed
            health_before = tx.read_field(target, "health")["value"]
            health_after = max(0, health_before - health_damage)
            defeated = health_after == 0
            tx.write_field(
                target, "shield", {"type": "Quantity:health", "value": shield_after}
            )
            tx.write_field(
                target, "health", {"type": "Quantity:health", "value": health_after}
            )
            tx.write_field(target, "defeated", {"type": "Bool", "value": defeated})
            tx.emit_signal(
                "game.combat.damage-resolved@1",
                {"amount": health_damage, "defeated": defeated, "target": target},
            )
            return {
                "after_mitigation": after_mitigation,
                "critical": critical,
                "defeated": defeated,
                "health_after": health_after,
                "health_before": health_before,
                "health_damage": health_damage,
                "raw": raw,
                "shield_absorbed": absorbed,
            }

        if primitive == "resource.commit":
            reservation = arguments["reservation"]
            if reservation["status"] != "reserved":
                return {"status": "insufficient"}
            tx.write_field(
                reservation["actor"],
                reservation["slot"],
                {
                    "type": "Quantity:mana",
                    "value": reservation["before"] - reservation["amount"],
                },
            )
            return None

        if primitive == "effect.apply-marker":
            target = arguments["target"]
            tx.read_field(target, "marked")
            tx.write_field(target, "marked", {"type": "Bool", "value": True})
            return None

        if primitive == "runtime.schedule-observation":
            tx.schedule(
                time=tx.event.time,
                phase="observation",
                priority=arguments["priority"],
                operation="experiment.balance.observe@1",
                payload={"target": arguments["target"]},
            )
            return None

        if primitive == "runtime.schedule-transition":
            authored = arguments["handler"]
            try:
                resolved = self.rir["content"]["exports"][authored]
            except KeyError as exc:
                raise self.runtime_refusal(
                    tx.event,
                    "schema2.runtime.unknown-handler",
                    f"unknown exported handler {authored}",
                ) from exc
            tx.schedule(
                time=tx.event.time,
                phase="transition",
                priority=arguments["priority"],
                operation="core.handler.dispatch@1",
                payload={"actor": tx.event.payload["actor"], "handler": resolved},
            )
            return None

        if primitive == "experiment.observe":
            for definition in sorted(
                self.experiment["metrics"], key=lambda item: item["id"]
            ):
                entity = definition["entity"]
                field_name = definition["field"]
                typed_value = tx.read_field(entity, field_name)
                tx.metric_samples.append(
                    {
                        "definition_id": definition["id"],
                        "dimensions": {"entity": entity},
                        "logical_time": tx.event.time,
                        "provenance": {
                            "evaluator_identity": self.evaluator_identity,
                            "event_id": tx.event.event_id,
                            "resolved_model_identity": self.rir["identity"],
                            "tool_identity": self.tool_identity,
                        },
                        "replication_id": self.experiment["replication_id"],
                        "source_kind": "simulated",
                        "value": typed_value,
                        "window": definition["window"],
                    }
                )
            return None

        if primitive == "core.noop":
            return None

        raise self.runtime_refusal(
            tx.event,
            "schema2.runtime.unknown-primitive",
            f"RIR primitive is not implemented by the reference tracer: {primitive}",
        )

    def _dispatch(self, event: Event, tx: Transaction) -> None:
        if event.phase == "input":
            authored = event.payload["handler"]
            try:
                handler = self.rir["content"]["exports"][authored]
            except KeyError as exc:
                raise self.runtime_refusal(
                    event,
                    "schema2.runtime.unknown-handler",
                    f"unknown exported handler {authored}",
                ) from exc
            tx.schedule(
                time=event.time,
                phase="transition",
                priority=event.payload["transition_priority"],
                operation="core.handler.dispatch@1",
                payload={"actor": event.payload["actor"], "handler": handler},
            )
            return
        if event.operation == "core.handler.dispatch@1":
            self.execute_handler(event.payload["handler"], tx)
            return
        operation = self.bundle.operations.get(event.operation)
        if operation is None:
            raise self.runtime_refusal(
                event,
                "schema2.runtime.unknown-operation",
                f"unknown event operation {event.operation}",
            )
        self.execute_primitive(operation["primitive"], event.payload, tx)

    def _commit(self, event: Event, tx: Transaction, before: dict[str, Any]) -> None:
        if len(self.queue) + len(tx.children) > self.budgets["max_queue"]:
            raise self.runtime_refusal(
                event,
                "schema2.runtime.queue-budget",
                "Runtime profile queue budget exhausted",
            )
        if any(
            child["zero_time_depth"] > self.budgets["max_zero_time_depth"]
            for child in tx.children
        ):
            raise self.runtime_refusal(
                event,
                "schema2.runtime.zero-time-depth-budget",
                "Runtime profile zero-time derivation depth exhausted",
            )
        next_state = copy.deepcopy(self.state)
        for (entity_id, field_name), typed_value in sorted(tx.writes.items()):
            next_state["entities"][entity_id]["fields"][field_name] = typed_value
        self.state = next_state
        self.rng_counters = tx.rng_counters
        admitted_children: list[str] = []
        for child in tx.children:
            admitted = self.enqueue(**child)
            admitted_children.append(admitted.event_id)
        self.metric_samples.extend(tx.metric_samples)
        after = self.snapshot()
        self.trace_entries.append(
            {
                "children": admitted_children,
                "event_id": event.event_id,
                "operation": event.operation,
                "ordering": {
                    "phase": event.phase,
                    "priority": event.priority,
                    "sequence": event.sequence,
                    "time": event.time,
                },
                "reads": sorted(set(tx.reads)),
                "rng_draws": tx.rng_draws,
                "signals": tx.signals,
                "snapshot_after": after["identity"],
                "snapshot_before": before["identity"],
                "status": "committed",
                "writes": [
                    {"entity": entity_id, "field": field_name, "value": value}
                    for (entity_id, field_name), value in sorted(tx.writes.items())
                ],
            }
        )

    def _terminal_receipt(self, event: Event, tx: Transaction) -> dict[str, Any]:
        snapshot = self.snapshot()
        trace = identified(
            "ordered-runtime-trace",
            {
                "entries": self.trace_entries,
                "run_id": self.run_id,
                "terminal": "refused",
            },
        )
        return {
            "discarded_child_count": len(tx.children),
            "discarded_rng_draws": tx.rng_draws,
            "discarded_write_slots": [
                f"{entity_id}.{field_name}"
                for entity_id, field_name in sorted(tx.writes)
            ],
            "last_committed_snapshot_identity": snapshot["identity"],
            "last_committed_state_identity": content_identity(self.state),
            "pre_event_state_identity": content_identity(tx.snapshot),
            "refusing_event_id": event.event_id,
            "rng_counters_after_rollback": dict(sorted(self.rng_counters.items())),
            "runtime_profile_identity": self.runtime_profile["identity"],
            "trace_identity": trace["identity"],
        }

    def execute(self) -> RuntimeArtifacts:
        self._initialize_inputs()
        while self.queue:
            event = heapq.heappop(self.queue)
            before = self.snapshot()
            tx = Transaction(self, event)
            try:
                if self.events_dispatched >= self.budgets["max_events"]:
                    raise self.runtime_refusal(
                        event,
                        "schema2.runtime.event-budget",
                        "Runtime profile event budget exhausted",
                    )
                self._dispatch(event, tx)
                self._commit(event, tx, before)
                self.events_dispatched += 1
            except Refusal as refusal:
                terminal = self._terminal_receipt(event, tx)
                raise Refusal(
                    refusal.stage,
                    refusal.code,
                    refusal.message,
                    refusal.location,
                    terminal,
                ) from refusal

        final_snapshot = self.snapshot()
        trace = identified(
            "ordered-runtime-trace",
            {
                "entries": self.trace_entries,
                "run_id": self.run_id,
                "terminal": "completed",
            },
        )
        experiment_identity = content_identity(
            {"artifact_kind": "experiment-specification", "content": self.experiment}
        )
        metric_dataset = identified(
            "metric-dataset",
            {
                "definitions": self.experiment["metrics"],
                "experiment_identity": experiment_identity,
                "ordering": "definition-id/entity/logical-time",
                "partition": self.experiment["partition"],
                "samples": sorted(
                    self.metric_samples,
                    key=lambda item: (
                        item["definition_id"],
                        item["dimensions"]["entity"],
                        item["logical_time"],
                    ),
                ),
            },
        )
        evaluation_run = identified(
            "evaluation-run",
            {
                "effective_seed": self.seed,
                "evaluator_identity": self.evaluator_identity,
                "experiment_identity": experiment_identity,
                "external_input_identity": content_identity(
                    self.experiment["external_inputs"]
                ),
                "final_snapshot_identity": final_snapshot["identity"],
                "metric_dataset_identity": metric_dataset["identity"],
                "named_streams": dict(sorted(self.rng_counters.items())),
                "resolved_model_identity": self.rir["identity"],
                "run_id": self.run_id,
                "runtime_profile_identity": self.runtime_profile["identity"],
                "terminal_status": "completed",
                "tool_identity": self.tool_identity,
                "trace_identity": trace["identity"],
            },
        )
        well_typed = identified(
            "evidence-assertion",
            {
                "assertion": "well_typed",
                "evaluator_identity": self.evaluator_identity,
                "policy_identity": self.bundle.identity,
                "prerequisites": [],
                "subject_identity": self.rir["identity"],
                "tool_identity": self.tool_identity,
            },
        )
        resolved = identified(
            "evidence-assertion",
            {
                "assertion": "resolved",
                "evaluator_identity": self.evaluator_identity,
                "policy_identity": self.bundle.identity,
                "prerequisites": [well_typed["identity"]],
                "subject_identity": self.rir["identity"],
                "tool_identity": self.tool_identity,
            },
        )
        evaluable = identified(
            "evidence-assertion",
            {
                "assertion": "evaluable",
                "evaluator_identity": self.evaluator_identity,
                "policy_identity": experiment_identity,
                "prerequisites": [resolved["identity"]],
                "subject_identity": evaluation_run["identity"],
                "tool_identity": self.tool_identity,
            },
        )
        return RuntimeArtifacts(
            trace=trace,
            final_snapshot=final_snapshot,
            metric_dataset=metric_dataset,
            evaluation_run=evaluation_run,
            evidence_assertions=(well_typed, resolved, evaluable),
        )


def run_experiment(
    *,
    rir: dict[str, Any],
    bundle: LanguageBundle,
    experiment: dict[str, Any],
    seed: int,
) -> RuntimeArtifacts:
    validate_experiment(experiment, rir, bundle)
    return Runtime(rir=rir, bundle=bundle, experiment=experiment, seed=seed).execute()
