"""Conformance-only semantic-token inventory derived from admitted machine laws.

The reader is intentionally separate from production resolution and evaluation.
An incomplete inventory is useful evidence, but cannot authorize a rename.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

from schema2_bootstrap_conformance_support import (
    _consumer_b_operation_composition_subjects,
)


class InventoryRefusal(ValueError):
    """The graph, coverage proof, or rename map does not close."""


@dataclass(frozen=True, order=True)
class AuthorityToken:
    role: str
    owner: tuple[str, ...]
    name: str


@dataclass(frozen=True, order=True)
class TokenOccurrence:
    token: AuthorityToken
    pointer: str
    use: str
    law: str
    location: str = "value"


@dataclass(frozen=True, order=True)
class UncoveredRole:
    pointer: str
    law: str
    reason: str


@dataclass(frozen=True)
class ExtensionInventory:
    tokens: frozenset[AuthorityToken]
    occurrences: tuple[TokenOccurrence, ...]
    reserved: frozenset[AuthorityToken]
    uncovered: tuple[UncoveredRole, ...]

    def require_complete(self) -> None:
        if self.uncovered:
            first = self.uncovered[0]
            raise InventoryRefusal(
                f"uncovered semantic role at {first.pointer}: {first.reason}"
            )


def _child(pointer: str, key: str | int) -> str:
    return pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _at(value: Any, path: Sequence[str]) -> Any:
    for part in path:
        value = value[part]
    return value


def _pointer_value(graph: Any, pointer: str) -> Any:
    value = graph
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _occurrence_value(graph: Any, occurrence: TokenOccurrence) -> Any:
    if occurrence.location == "value":
        return _pointer_value(graph, occurrence.pointer)
    if occurrence.location == "key":
        parent, _, encoded = occurrence.pointer.rpartition("/")
        key = encoded.replace("~1", "/").replace("~0", "~")
        container = _pointer_value(graph, parent)
        if not isinstance(container, dict) or key not in container:
            raise InventoryRefusal("key occurrence does not identify an object member")
        return key
    raise InventoryRefusal("unknown occurrence location")


class _Reader:
    def __init__(self, kernel: Mapping[str, Any], graph: Mapping[str, Any]):
        self.kernel = kernel
        self.graph = graph
        self.meta = kernel["meta_format"]
        self.projections = self.meta["package_release"]["semantic_closure"][
            "projections"
        ]
        uniqueness = next(
            law
            for law in kernel["admission"]["laws"]
            if law["id"] == "kernel.identifiers.unique"
        )
        self.scoped = {
            row["path"].removeprefix("language_bundle.")
            for row in uniqueness["arguments"]["collections"]
            if row.get("scope") == "package"
        }
        self.tokens: set[AuthorityToken] = set()
        self.occurrences: set[TokenOccurrence] = set()
        self.uncovered: set[UncoveredRole] = set()
        self.reserved: set[AuthorityToken] = set()
        self.definitions: dict[tuple[str, str, str], tuple[Any, str]] = {}
        self.types: dict[tuple[str, str], dict[str, Any]] = {}
        self.nodes = {row["id"]: row for row in self.meta["runtime_program"]["nodes"]}
        self.node_laws = {
            row["id"]: f"/meta_format/runtime_program/nodes/{i}"
            for i, row in enumerate(self.meta["runtime_program"]["nodes"])
        }
        self.seeds: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        self.operand_contracts: dict[
            tuple[tuple[str, str], tuple[int, ...], str], tuple[dict[str, Any], ...]
        ] = {}

    def gap(self, pointer: str, law: str, reason: str) -> None:
        self.uncovered.add(UncoveredRole(pointer, law, reason))

    def occurrence(
        self,
        token: AuthorityToken,
        pointer: str,
        use: str,
        law: str,
        *,
        location: str = "value",
    ) -> None:
        if not isinstance(token.name, str) or not token.name:
            raise InventoryRefusal(f"invalid token at {pointer}")
        occurrence = TokenOccurrence(token, pointer, use, law, location)
        if _occurrence_value(self.graph, occurrence) != token.name:
            raise InventoryRefusal(
                f"token occurrence does not match bytes at {pointer}"
            )
        self.tokens.add(token)
        self.occurrences.add(occurrence)

    def declared(self, role: str, namespace: str, name: str) -> AuthorityToken:
        if role == "language.nominal_types":
            return AuthorityToken("type", (namespace,), name)
        return AuthorityToken(role, (namespace,) if role in self.scoped else (), name)

    def reference(
        self, role: str, name: str, pointer: str, law: str, namespace: str = ""
    ) -> None:
        token = self.declared(role, namespace, name)
        if token not in self.tokens and token not in self.reserved:
            raise InventoryRefusal(f"unresolved {role} reference at {pointer}: {name}")
        self.occurrence(token, pointer, "reference", law)

    def namespace(self, name: str, pointer: str, use: str, law: str) -> None:
        token = AuthorityToken("namespace", (), name)
        if (
            use == "reference"
            and token not in self.tokens
            and token not in self.reserved
        ):
            raise InventoryRefusal(f"unresolved namespace at {pointer}")
        self.occurrence(token, pointer, use, law)

    def index(self) -> None:
        allowed = {
            "packages",
            "ldb_root",
            "vector_sets",
            "source",
            "experiment",
            "artifacts",
            "results",
        }
        if set(self.graph) - allowed or "packages" not in self.graph:
            raise InventoryRefusal("unknown or missing witness graph surface")
        package_ids = [p["id"] for p in self.graph["packages"]]
        if len(package_ids) != len(set(package_ids)):
            raise InventoryRefusal("duplicate namespace")
        for pi, package in enumerate(self.graph["packages"]):
            pp = f"/packages/{pi}"
            self.namespace(
                package["id"], pp + "/id", "declaration", "/meta_format/package_release"
            )
            if len(package["semantic_closure"]) != len(self.projections):
                raise InventoryRefusal("semantic closure projection count changed")
            for ci, (entry, projection) in enumerate(
                zip(package["semantic_closure"], self.projections, strict=True)
            ):
                if entry["authority_path"] != projection["authority_path"]:
                    raise InventoryRefusal("semantic closure projection order changed")
                role = projection["authority_path"]
                law = f"/meta_format/package_release/semantic_closure/projections/{ci}"
                owners = _at(package, projection["owners_path"].split("."))
                definition_names = []
                for di, definition in enumerate(entry["definitions"]):
                    name = (
                        definition
                        if projection["key_member"] is None
                        else definition[projection["key_member"]]
                    )
                    definition_names.append(name)
                    coordinate = (package["id"], role, name)
                    if coordinate in self.definitions:
                        raise InventoryRefusal("duplicate owned definition")
                    dp = f"{pp}/semantic_closure/{ci}/definitions/{di}"
                    self.definitions[coordinate] = (definition, dp)
                    kp = (
                        dp
                        if projection["key_member"] is None
                        else _child(dp, projection["key_member"])
                    )
                    token = self.declared(role, package["id"], name)
                    if token in self.tokens:
                        raise InventoryRefusal("duplicate semantic token owner")
                    self.occurrence(token, kp, "declaration", law)
                if sorted(definition_names) != sorted(owners) or len(owners) != len(
                    set(owners)
                ):
                    raise InventoryRefusal("export/definition set mismatch")
                for oi, name in enumerate(owners):
                    self.occurrence(
                        self.declared(role, package["id"], name),
                        pp
                        + "/"
                        + projection["owners_path"].replace(".", "/")
                        + f"/{oi}",
                        "reference",
                        law,
                    )
            for ti, exported in enumerate(package["exports"]["types"]):
                coordinate = (package["id"], exported["id"])
                if coordinate in self.types:
                    raise InventoryRefusal("duplicate exported Type")
                self.types[coordinate] = exported
                self.occurrence(
                    AuthorityToken("type", coordinate[:1], coordinate[1]),
                    f"{pp}/exports/types/{ti}/id",
                    "declaration",
                    "/meta_format/package_release/type_export",
                )
        if "ldb_root" in self.graph:
            root = self.graph["ldb_root"]
            descriptors = root["package_descriptors"]
            if sorted(row["id"] for row in descriptors) != sorted(package_ids):
                raise InventoryRefusal(
                    "LDB descriptor graph does not exactly cover packages"
                )
            for i, descriptor in enumerate(descriptors):
                self.namespace(
                    descriptor["id"],
                    f"/ldb_root/package_descriptors/{i}/id",
                    "reference",
                    "/meta_format/language_bundle/package_descriptor",
                )
            self.gap(
                "/ldb_root",
                "/meta_format/language_bundle",
                "generated content/byte-size framing must be rederived on rename",
            )
        else:
            self.gap(
                "/ldb_root",
                "/meta_format/language_bundle",
                "exact reachable root descriptor graph was not supplied",
            )
        for vi, vectors in enumerate(self.graph.get("vector_sets", [])):
            vp = f"/vector_sets/{vi}"
            self.namespace(
                vectors["package_id"],
                vp + "/package_id",
                "reference",
                "/meta_format/package_conformance_vector_set",
            )
            definitions = vectors["vector_definitions"]
            if sorted(row["id"] for row in definitions) != sorted(vectors["vectors"]):
                raise InventoryRefusal("vector owner list does not close definitions")
            for di, definition in enumerate(definitions):
                token = self.declared(
                    "vectors", vectors["package_id"], definition["id"]
                )
                if token in self.tokens:
                    raise InventoryRefusal("duplicate vector identity")
                self.occurrence(
                    token,
                    f"{vp}/vector_definitions/{di}/id",
                    "declaration",
                    "/meta_format/package_conformance_vector_set",
                )
            for ri, name in enumerate(vectors["vectors"]):
                self.reference(
                    "vectors",
                    name,
                    f"{vp}/vectors/{ri}",
                    "/meta_format/package_conformance_vector_set",
                )
        for contract in self.meta["runtime_program"]["fixed_value_contracts"].values():
            ref = contract["type"]
            self.reserved.add(AuthorityToken("type", (ref["package"],), ref["id"]))
            self.reserved.add(AuthorityToken("namespace", (), ref["package"]))
        for (owner, role, name), (definition, pointer) in self.definitions.items():
            if role == "language.nominal_types":
                if (owner, name) not in self.types:
                    raise InventoryRefusal("nominal declaration has no exported Type")
                self.types[(owner, name)] = definition
            if role == "language.model_lowerings":
                projection = definition["runtime_projection"]
                collections = {row["id"]: row for row in projection["collections"]}
                for i, seed in enumerate(projection["seeds"]):
                    collection = collections[seed["collection"]]
                    self.seeds.append(
                        (seed, f"{pointer}/runtime_projection/seeds/{i}", collection)
                    )

    def operation_operand_projection(self) -> None:
        language: dict[str, Any] = {"packages": self.graph["packages"]}
        for projection in self.projections:
            path = projection["authority_path"].split(".")
            if path[0] != "language":
                continue
            target = language
            for segment in path[1:-1]:
                target = target.setdefault(segment, {})
            target[path[-1]] = [
                definition
                for (_, role, _), (definition, _) in self.definitions.items()
                if role == projection["authority_path"]
            ]
        closed: dict[tuple[str, str], tuple[set[str], set[str], int]] = {}
        subjects = _consumer_b_operation_composition_subjects(
            dict(self.kernel),
            {"language": language},
            closed_operations=closed,
            operand_contracts=self.operand_contracts,
        )
        expected = {
            (owner, name)
            for owner, role, name in self.definitions
            if role == "language.operations"
        }
        if subjects or set(closed) != expected:
            raise InventoryRefusal("independent Operation composition did not close")

    def type_reference(self, value: Any, pointer: str) -> None:
        law = "/meta_format/literal_typing/typed_envelope_profile/admission/nominal_type_reference"
        if not isinstance(value, dict):
            raise InventoryRefusal(f"Type reference is not an object at {pointer}")
        if "package" in value or "id" in value:
            if set(value) not in ({"package", "id"}, {"package", "id", "kind"}):
                raise InventoryRefusal(f"unknown Type reference shape at {pointer}")
            token = AuthorityToken("type", (value["package"],), value["id"])
            if token not in self.tokens and token not in self.reserved:
                raise InventoryRefusal(f"unresolved Type reference at {pointer}")
            self.namespace(value["package"], pointer + "/package", "reference", law)
            self.occurrence(token, pointer + "/id", "reference", law)
            return
        self.structured_definition(value, pointer, None)

    def structured_definition(
        self, definition: dict[str, Any], pointer: str, owner: tuple[str, str] | None
    ) -> None:
        constructors = [
            (value, dp)
            for (_, role, _), (value, dp) in self.definitions.items()
            if role == "language.constructors"
            and value.get("value_rule", {}).get("definition_kind")
            == definition.get("kind")
        ]
        if len(constructors) != 1:
            raise InventoryRefusal(f"unknown structured constructor at {pointer}")
        constructor, cp = constructors[0]
        rule = constructor["value_rule"]
        law = cp + "/value_rule"
        operator = rule["operator"]
        if operator == "enum-member":
            member = rule["members_member"]
            if owner is None:
                self.gap(pointer, law, "anonymous Enum scope is not yet represented")
                return
            for i, name in enumerate(definition[member]):
                self.occurrence(
                    AuthorityToken("enum-member", owner, name),
                    f"{pointer}/{member}/{i}",
                    "declaration",
                    law,
                )
        elif operator == "bounded-list":
            self.type_reference(
                definition[rule["element_member"]],
                _child(pointer, rule["element_member"]),
            )
        elif operator == "closed-record":
            for i, field in enumerate(definition[rule["fields_member"]]):
                fp = f"{pointer}/{rule['fields_member']}/{i}"
                if owner is None:
                    self.gap(fp, law, "anonymous Record scope is not yet represented")
                else:
                    self.occurrence(
                        AuthorityToken(
                            "record-field", owner, field[rule["field_name_member"]]
                        ),
                        _child(fp, rule["field_name_member"]),
                        "declaration",
                        law,
                    )
                self.type_reference(
                    field[rule["field_type_member"]],
                    _child(fp, rule["field_type_member"]),
                )
        elif operator == "canonical-ref-key":
            self.type_reference(
                definition[rule["target_member"]],
                _child(pointer, rule["target_member"]),
            )
        else:
            raise InventoryRefusal(
                f"unimplemented constructor law {operator} at {pointer}"
            )

    def value_contract(self, value: dict[str, Any], pointer: str) -> None:
        if "type" in value:
            self.type_reference(value["type"], pointer + "/type")
        if "type" in value and any(
            value["type"] == contract["type"]
            for contract in self.meta["runtime_program"][
                "fixed_value_contracts"
            ].values()
        ):
            return
        for seed, law, collection in self.seeds:
            path = seed["declaration_path"]
            if len(path) != 1 or path[0] not in value:
                continue
            source = collection["source"]
            if source["kind"] != "semantic-closure":
                continue
            role = source["authority_path"]
            projection = next(
                p for p in self.projections if p["authority_path"] == role
            )
            target = (
                [] if projection["key_member"] is None else [projection["key_member"]]
            )
            if seed["target_path"] != target:
                continue  # This join selects on a value contract, not on an identity.
            self.reference(role, value[path[0]], _child(pointer, path[0]), law)

    def typed_literal(self, value: Any, pointer: str) -> None:
        if not isinstance(value, dict):
            return
        profile = self.meta["literal_typing"]["typed_envelope_profile"]
        tm, vm = profile["type_member"], profile["value_member"]
        if set(value) != {tm, vm}:
            raise InventoryRefusal(f"unknown typed literal shape at {pointer}")
        self.type_reference(value[tm], _child(pointer, tm))
        self.typed_value(value[tm], value[vm], _child(pointer, vm))

    def typed_value(self, reference: dict[str, Any], value: Any, pointer: str) -> None:
        if "package" in reference:
            definition = self.types.get((reference["package"], reference["id"]))
            if definition is None or "definition" not in definition:
                return  # Scalar or Kernel value has no authored nested labels.
            owner = (reference["package"], reference["id"])
            definition = definition["definition"]
        else:
            definition, owner = reference, None
        constructors = [
            (row, dp)
            for (_, role, _), (row, dp) in self.definitions.items()
            if role == "language.constructors"
            and row.get("value_rule", {}).get("definition_kind")
            == definition.get("kind")
        ]
        if len(constructors) != 1:
            raise InventoryRefusal(f"unknown typed value constructor at {pointer}")
        constructor, cp = constructors[0]
        rule, law = constructor["value_rule"], cp + "/value_rule"
        if rule["operator"] == "enum-member":
            if owner is None:
                self.gap(pointer, law, "anonymous Enum value scope is unresolved")
            else:
                token = AuthorityToken("enum-member", owner, value)
                if token not in self.tokens:
                    raise InventoryRefusal(f"unknown Enum member at {pointer}")
                self.occurrence(token, pointer, "reference", law)
        elif rule["operator"] == "bounded-list":
            for i, item in enumerate(value):
                self.typed_value(
                    definition[rule["element_member"]], item, _child(pointer, i)
                )
        elif rule["operator"] == "closed-record":
            for field in definition[rule["fields_member"]]:
                field_name = field[rule["field_name_member"]]
                if owner is None:
                    self.gap(pointer, law, "anonymous Record value scope is unresolved")
                else:
                    self.occurrence(
                        AuthorityToken("record-field", owner, field_name),
                        _child(pointer, field_name),
                        "reference",
                        law,
                        location="key",
                    )
                self.typed_value(
                    field[rule["field_type_member"]],
                    value[field[rule["field_name_member"]]],
                    _child(pointer, field[rule["field_name_member"]]),
                )
        elif rule["operator"] != "canonical-ref-key":
            raise InventoryRefusal(f"unknown typed value law at {pointer}")
        # A canonical Ref key is authored instance data; its target Type was
        # traversed above. Equal spelling does not make the key an Enum label.

    def packages(self) -> None:
        for pi, package in enumerate(self.graph["packages"]):
            pp = f"/packages/{pi}"
            for member in self.meta["package_release"]["nested_members"][
                "dependencies"
            ]:
                for i, name in enumerate(package["dependencies"][member]):
                    self.namespace(
                        name,
                        f"{pp}/dependencies/{member}/{i}",
                        "reference",
                        "/meta_format/package_release/nested_members/dependencies",
                    )
            for i, name in enumerate(package["capabilities"]["required"]):
                self.reference(
                    "language.capabilities",
                    name,
                    f"{pp}/capabilities/required/{i}",
                    "/meta_format/package_release/nested_members/capabilities",
                )
            for ti, exported in enumerate(package["exports"]["types"]):
                self.reference(
                    "language.constructors",
                    exported["constructor"],
                    f"{pp}/exports/types/{ti}/constructor",
                    "/meta_format/package_release/type_export",
                )
        for (owner, role, name), (definition, pointer) in self.definitions.items():
            if role == "language.nominal_types":
                self.occurrence(
                    AuthorityToken("type", (owner,), name),
                    pointer + "/id",
                    "reference",
                    "/meta_format/runtime_projection/type_reference_closure",
                )
                self.reference(
                    "language.constructors",
                    definition["constructor"],
                    pointer + "/constructor",
                    "/meta_format/runtime_projection/type_reference_closure",
                )
                self.structured_definition(
                    definition["definition"], pointer + "/definition", (owner, name)
                )
            elif role == "language.operations":
                continue
            elif isinstance(definition, dict):
                self.gap(
                    pointer,
                    "/meta_format/language_definitions",
                    f"nested {role} roles are not yet traversed",
                )
            else:
                self.gap(
                    pointer,
                    "/meta_format/language_definitions",
                    "Kernel-fixed versus renameable scalar declaration is not yet classified",
                )
        for (owner, role, _), (definition, pointer) in self.definitions.items():
            if role == "language.operations":
                self.operation(owner, definition, pointer)
        for surface in ("vector_sets", "experiment", "artifacts", "results"):
            if self.graph.get(surface):
                self.gap(
                    "/" + surface,
                    "/meta_format",
                    f"{surface} traversal is not yet complete",
                )

    def operand(
        self,
        value: Any,
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
        law: str,
    ) -> None:
        if isinstance(value, str):
            token = bindings.get(value)
            if token is None:
                raise InventoryRefusal(
                    f"unresolved lexical operand at {pointer}: {value}"
                )
            self.occurrence(token, pointer, "reference", law)
        elif isinstance(value, dict):
            kind = value.get("kind")
            if kind in {"port", "local"}:
                member = kind
                self.operand(
                    value[member], _child(pointer, member), scope, bindings, law
                )
            elif kind == "literal":
                self.typed_literal(value["value"], pointer + "/value")
            else:
                self.gap(
                    pointer, law, "expression operand traversal is not yet complete"
                )
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise InventoryRefusal(f"unknown lexical operand shape at {pointer}")

    def operation(self, owner: str, operation: dict[str, Any], pointer: str) -> None:
        scope = (owner, operation["id"])
        law = "/meta_format/runtime_program/invocation_contract"
        bindings: dict[str, AuthorityToken] = {}
        for i, port in enumerate(operation["inputs"]):
            token = AuthorityToken("operation-port", scope, port["id"])
            if port["id"] in bindings:
                raise InventoryRefusal("duplicate Operation port")
            bindings[port["id"]] = token
            self.occurrence(token, f"{pointer}/inputs/{i}/id", "declaration", law)
            self.value_contract(port, f"{pointer}/inputs/{i}")
        if isinstance(operation.get("result"), dict):
            result = operation["result"]
            self.occurrence(
                AuthorityToken("operation-result", scope, result["id"]),
                pointer + "/result/id",
                "declaration",
                law,
            )
            self.value_contract(result, pointer + "/result")
        for i, outcome in enumerate(operation.get("outcomes", [])):
            self.occurrence(
                AuthorityToken("operation-outcome", scope, outcome["id"]),
                f"{pointer}/outcomes/{i}/id",
                "declaration",
                "/meta_format/runtime_program/outcome_contract",
            )
        self.body(operation["body"], pointer + "/body", scope, bindings)
        result = operation.get("result", {})
        source = result.get("source")
        if isinstance(source, dict):
            if source["kind"] in {"port", "local"}:
                self.operand(
                    source["name"],
                    pointer + "/result/source/name",
                    scope,
                    bindings,
                    law,
                )
            elif source["kind"] == "operation-result":
                self.occurrence(
                    AuthorityToken("operation-site", scope, source["site"]),
                    pointer + "/result/source/site",
                    "reference",
                    law,
                )
            elif source["kind"] != "unit":
                raise InventoryRefusal("unknown Operation result source")
        if "default_outcome" in operation:
            self.occurrence(
                AuthorityToken(
                    "operation-outcome", scope, operation["default_outcome"]
                ),
                pointer + "/default_outcome",
                "reference",
                "/meta_format/runtime_program/outcome_contract",
            )
        for member, role in (
            ("rule", "language.rules"),
            ("runtime_profile", "language.runtime_profiles"),
            ("numeric_policy", "language.quantity.numeric_policies"),
        ):
            if member in operation:
                self.reference(
                    role,
                    operation[member],
                    pointer + "/" + member,
                    "/meta_format/language_definitions/collections/operations",
                )
        for i, reason in enumerate(operation.get("refusals", [])):
            self.reference(
                "language.reasons",
                reason,
                f"{pointer}/refusals/{i}",
                "/meta_format/language_definitions/collections/operations",
            )
        if self.graph.get("vector_sets"):
            for i, name in enumerate(operation.get("vectors", [])):
                self.reference(
                    "vectors",
                    name,
                    f"{pointer}/vectors/{i}",
                    "/meta_format/package_vector",
                )
        for gi, group in enumerate(
            operation.get("alias_policy", {}).get("writable_groups", [])
        ):
            for pi, name in enumerate(group["ports"]):
                self.occurrence(
                    AuthorityToken("operation-port", scope, name),
                    f"{pointer}/alias_policy/writable_groups/{gi}/ports/{pi}",
                    "reference",
                    law,
                )
        for member in (
            "owner_type",
            "effects",
            "extensions",
        ):
            if member in operation and operation[member]:
                self.gap(
                    pointer + "/" + member,
                    "/meta_format/language_definitions/collections/operations",
                    f"Operation {member} links are not yet complete",
                )

    def callee(
        self, reference: dict[str, Any], pointer: str, law: str
    ) -> tuple[str, str]:
        self.namespace(reference["package"], pointer + "/package", "reference", law)
        self.reference(
            "language.operations",
            reference["id"],
            pointer + "/id",
            law,
            reference["package"],
        )
        return reference["package"], reference["id"]

    def body(
        self,
        body: list[dict[str, Any]],
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
        body_path: tuple[int, ...] = (),
    ) -> None:
        for i, instruction in enumerate(body):
            ip = _child(pointer, i)
            node = self.nodes.get(instruction.get("node"))
            if node is None:
                raise InventoryRefusal(f"unknown runtime node at {ip}")
            law = self.node_laws[node["id"]]
            if set(instruction) != set(node["required_members"]):
                raise InventoryRefusal(f"unknown runtime node members at {ip}")
            operator = node["semantics"]["operator"]
            members = {
                member
                for constraint in node["operand_constraints"]
                for member in constraint.get("members", [])
            }
            members.update(node["result"].get("typing", {}).get("members", []))
            consumed = {"node", "target"}
            if operator == "typed-literal":
                self.typed_literal(instruction["literal"], ip + "/literal")
                consumed.add("literal")
                members.discard("literal")
            if operator == "bounded-lookup":
                members.discard("key")
                consumed.add("key")
                candidates = self.operand_contracts.get(
                    (scope, (*body_path, i), "value")
                )
                if not candidates:
                    raise InventoryRefusal("lookup has no closed operand judgment")
                roles = set()
                for contract in candidates:
                    reference = contract["type"]
                    owner = (
                        (reference["package"], reference["id"])
                        if "package" in reference
                        else None
                    )
                    nominal = self.types[owner] if owner is not None else None
                    constructor, cp = next(
                        (definition, dp)
                        for (_, role, name), (
                            definition,
                            dp,
                        ) in self.definitions.items()
                        if role == "language.constructors"
                        and (
                            name == nominal["constructor"]
                            if nominal is not None
                            else definition.get("value_rule", {}).get("definition_kind")
                            == reference.get("kind")
                        )
                    )
                    kind = constructor["value_rule"]["operator"]
                    roles.add(kind)
                    if kind == "closed-record":
                        if owner is None:
                            self.gap(
                                ip + "/key",
                                law,
                                "anonymous Record lookup field scope is unresolved",
                            )
                            continue
                        self.occurrence(
                            AuthorityToken("record-field", owner, instruction["key"]),
                            ip + "/key",
                            "reference",
                            cp + "/value_rule",
                        )
                    elif kind == "bounded-list":
                        self.operand(
                            instruction["key"], ip + "/key", scope, bindings, law
                        )
                    else:
                        raise InventoryRefusal(
                            "lookup operand has an unknown consuming law"
                        )
                if len(roles) > 1:
                    raise InventoryRefusal("lookup key has conflicting semantic roles")
            if operator in {"bounded-pure-fold", "invoke-operation"}:
                consumed.update({"site", "operation", "arguments"})
                site = AuthorityToken("operation-site", scope, instruction["site"])
                self.occurrence(site, ip + "/site", "declaration", law)
                target_scope = self.callee(
                    instruction["operation"], ip + "/operation", law
                )
                for ai, argument in enumerate(instruction["arguments"]):
                    ap = f"{ip}/arguments/{ai}"
                    self.occurrence(
                        AuthorityToken(
                            "operation-port", target_scope, argument["port"]
                        ),
                        ap + "/port",
                        "reference",
                        law,
                    )
                    self.operand(
                        argument["operand"], ap + "/operand", scope, bindings, law
                    )
                if operator == "bounded-pure-fold":
                    members.update({"value", "initial"})
                    consumed.update({"accumulator_port", "item_port"})
                    for member in ("accumulator_port", "item_port"):
                        self.occurrence(
                            AuthorityToken(
                                "operation-port", target_scope, instruction[member]
                            ),
                            ip + "/" + member,
                            "reference",
                            law,
                        )
                else:
                    consumed.update({"result", "outcomes"})
                    result = instruction["result"]
                    if result["kind"] == "local":
                        token = AuthorityToken("operation-local", scope, result["name"])
                        self.occurrence(token, ip + "/result/name", "declaration", law)
                        bindings[result["name"]] = token
                    elif (
                        result["kind"]
                        not in self.meta["runtime_program"]["invocation_contract"][
                            "result_binding_kinds"
                        ]
                    ):
                        raise InventoryRefusal("unknown invocation result binding")
                    for oi, outcome in enumerate(instruction["outcomes"]):
                        op = f"{ip}/outcomes/{oi}"
                        self.occurrence(
                            AuthorityToken(
                                "operation-outcome", target_scope, outcome["outcome"]
                            ),
                            op + "/outcome",
                            "reference",
                            law,
                        )
                        if outcome["action"]["kind"] == "propagate":
                            self.occurrence(
                                AuthorityToken(
                                    "operation-outcome",
                                    scope,
                                    outcome["action"]["outcome"],
                                ),
                                op + "/action/outcome",
                                "reference",
                                law,
                            )
            elif operator == "guarded-outcome-block":
                consumed.update({"body", "outcome"})
                self.body(
                    instruction["body"], ip + "/body", scope, bindings, (*body_path, i)
                )
                self.occurrence(
                    AuthorityToken("operation-outcome", scope, instruction["outcome"]),
                    ip + "/outcome",
                    "reference",
                    law,
                )
            for member in members:
                if member in instruction:
                    self.operand(
                        instruction[member], _child(ip, member), scope, bindings, law
                    )
                    consumed.add(member)
            if "target" in instruction and node["result"]["kind"] in {"local", "draw"}:
                token = AuthorityToken("operation-local", scope, instruction["target"])
                self.occurrence(token, ip + "/target", "declaration", law)
                bindings[instruction["target"]] = token
            remaining = set(instruction) - consumed
            if remaining:
                self.gap(
                    ip,
                    law,
                    "node roles not yet covered: " + ",".join(sorted(remaining)),
                )

    def source(self) -> None:
        source = self.graph.get("source")
        if not source:
            return
        schemas = [
            value["schema"]
            for (_, role, _), (value, _) in self.definitions.items()
            if role == "language.wire_schemas"
            and value["artifact_kind"] == "model-source-package"
        ]
        if len(schemas) != 1 or not jsonschema.Draft202012Validator(
            schemas[0]
        ).is_valid(source):
            raise InventoryRefusal(
                "Source does not match its admitted closed wire schema"
            )
        law = "/meta_format/resolution_judgment"
        model = source["manifest"]["id"]
        self.occurrence(
            AuthorityToken("source-model", (), model),
            "/source/manifest/id",
            "declaration",
            law,
        )
        for i, name in enumerate(source["package_requirements"]):
            self.namespace(name, f"/source/package_requirements/{i}", "reference", law)
        for mi, module in enumerate(source["modules"]):
            mp = f"/source/modules/{mi}"
            module_scope = (model, module["id"])
            self.occurrence(
                AuthorityToken("source-module", (model,), module["id"]),
                mp + "/id",
                "declaration",
                law,
            )
            aliases = {}
            for ii, import_ in enumerate(module["imports"]):
                ip = f"{mp}/imports/{ii}"
                alias = AuthorityToken(
                    "source-type-alias", module_scope, import_["alias"]
                )
                aliases[import_["alias"]] = alias
                self.occurrence(alias, ip + "/alias", "declaration", law)
                self.namespace(import_["package"], ip + "/package", "reference", law)
                self.occurrence(
                    AuthorityToken("type", (import_["package"],), import_["symbol"]),
                    ip + "/symbol",
                    "reference",
                    law,
                )
            for si, symbol in enumerate(module["symbols"]):
                sp = f"{mp}/symbols/{si}"
                self.occurrence(
                    AuthorityToken("source-symbol", module_scope, symbol["symbol"]),
                    sp + "/symbol",
                    "declaration",
                    law,
                )
                alias = aliases.get(symbol["type"])
                if alias is None:
                    raise InventoryRefusal(f"unresolved Source Type alias at {sp}")
                self.occurrence(alias, sp + "/type", "reference", law)
                self.value_contract(
                    {k: v for k, v in symbol.items() if k != "type"}, sp
                )
                if symbol["value_policy"]["mode"] not in {
                    "experiment-required",
                    "none",
                }:
                    self.gap(
                        sp + "/value_policy",
                        law,
                        "Source initializer roles are not yet complete",
                    )
            if module.get("formulas"):
                self.gap(
                    mp + "/formulas",
                    law,
                    "Formula text and binding spans are not yet complete",
                )
        entry = AuthorityToken(
            "source-module", (model,), source["manifest"]["entry_module"]
        )
        self.occurrence(entry, "/source/manifest/entry_module", "reference", law)
        for ei, entrypoint in enumerate(source.get("entrypoints", [])):
            ep = f"/source/entrypoints/{ei}"
            self.occurrence(
                AuthorityToken("source-entrypoint", (model,), entrypoint["id"]),
                ep + "/id",
                "declaration",
                law,
            )
            target_scope = self.callee(entrypoint["operation"], ep + "/operation", law)
            for ai, argument in enumerate(entrypoint["arguments"]):
                ap = f"{ep}/arguments/{ai}"
                self.occurrence(
                    AuthorityToken("operation-port", target_scope, argument["port"]),
                    ap + "/port",
                    "reference",
                    law,
                )
                self.source_operand(argument["operand"], ap + "/operand", model, law)
            self.source_operand(entrypoint["result"], ep + "/result", model, law)

    def source_operand(
        self, operand: dict[str, Any], pointer: str, model: str, law: str
    ) -> None:
        if operand["kind"] == "symbol":
            self.occurrence(
                AuthorityToken("source-module", (model,), operand["module"]),
                pointer + "/module",
                "reference",
                law,
            )
            self.occurrence(
                AuthorityToken(
                    "source-symbol", (model, operand["module"]), operand["symbol"]
                ),
                pointer + "/symbol",
                "reference",
                law,
            )
        elif operand["kind"] == "literal":
            self.typed_literal(operand["value"], pointer + "/value")
        elif operand["kind"] != "discard":
            self.gap(pointer, law, "Source operand form is not yet traversed")

    def finish(self) -> ExtensionInventory:
        self.index()
        self.operation_operand_projection()
        self.packages()
        self.source()
        declarations = {o.token for o in self.occurrences if o.use == "declaration"}
        unresolved = self.tokens - declarations - self.reserved
        if unresolved:
            # A not-yet-traversed provider is visible evidence, never a successful
            # lookup created simply by seeing a reference spelling.
            for token in unresolved:
                occurrence = next(o for o in self.occurrences if o.token == token)
                self.gap(
                    occurrence.pointer,
                    occurrence.law,
                    "reference has no traversed declaration",
                )
        return ExtensionInventory(
            frozenset(self.tokens),
            tuple(sorted(self.occurrences)),
            frozenset(self.reserved),
            tuple(sorted(self.uncovered)),
        )


def read_extension_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> ExtensionInventory:
    return _Reader(kernel, graph).finish()


def validate_inventory_occurrences(
    graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Independently check exact bytes and uniqueness of a supplied occurrence set."""
    if len(inventory.occurrences) != len(set(inventory.occurrences)):
        raise InventoryRefusal("duplicate token occurrence")
    for occurrence in inventory.occurrences:
        try:
            value = _occurrence_value(graph, occurrence)
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise InventoryRefusal("invalid token occurrence pointer") from error
        if occurrence.token not in inventory.tokens or value != occurrence.token.name:
            raise InventoryRefusal("token occurrence does not match graph")
    if {o.token for o in inventory.occurrences} != set(inventory.tokens):
        raise InventoryRefusal("inventory member has no occurrence")


def validate_token_bijection(
    inventory: ExtensionInventory,
    pairs: Sequence[tuple[AuthorityToken, AuthorityToken]],
) -> None:
    """Check exact token-domain and owner-role preservation; never waive coverage."""
    sources, targets = [p[0] for p in pairs], [p[1] for p in pairs]
    if len(sources) != len(set(sources)) or len(targets) != len(set(targets)):
        raise InventoryRefusal("duplicate source or target in token bijection")
    if any(token in inventory.reserved for token in sources + targets):
        raise InventoryRefusal("Kernel-reserved token in bijection")
    if set(sources) != set(inventory.tokens - inventory.reserved):
        raise InventoryRefusal("bijection domain is not the complete inventory")
    correspondence = dict(pairs)
    if any(
        source.role != target.role
        or target.owner != _renamed_owner(source, correspondence)
        or not target.name
        for source, target in pairs
    ):
        raise InventoryRefusal("token role or owner changed inconsistently")
    inventory.require_complete()


def validate_extension_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Reverse-check authored owners and declaration coverage independently.

    This verifier does not call the reader. Nested reference coverage remains an
    explicit unfinished obligation until the corresponding consuming-law pass
    is implemented; require_complete still refuses that inventory.
    """
    validate_inventory_occurrences(graph, inventory)
    meta = kernel["meta_format"]
    projections = meta["package_release"]["semantic_closure"]["projections"]
    unique = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.identifiers.unique"
    )
    scopes = {
        row["path"].removeprefix("language_bundle."): row.get("scope")
        for row in unique["arguments"]["collections"]
    }
    actual = {
        (o.token, o.pointer, o.use)
        for o in inventory.occurrences
        if o.location == "value"
    }
    required: set[tuple[AuthorityToken, str, str]] = set()
    for pi, package in enumerate(graph["packages"]):
        owner, pp = package["id"], f"/packages/{pi}"
        required.add(
            (AuthorityToken("namespace", (), owner), pp + "/id", "declaration")
        )
        for projection in projections:
            ci, entry = next(
                (i, e)
                for i, e in enumerate(package["semantic_closure"])
                if e["authority_path"] == projection["authority_path"]
            )
            root, member = projection["owners_path"].split(".")
            for ei, exported in enumerate(package[root][member]):
                di, definition = next(
                    (i, d)
                    for i, d in enumerate(entry["definitions"])
                    if (
                        d
                        if projection["key_member"] is None
                        else d[projection["key_member"]]
                    )
                    == exported
                )
                role = projection["authority_path"]
                scope = (owner,) if scopes.get(role) == "package" else ()
                if role == "language.nominal_types":
                    role, scope = "type", (owner,)
                token = AuthorityToken(role, scope, exported)
                dp = f"{pp}/semantic_closure/{ci}/definitions/{di}"
                if projection["key_member"] is not None:
                    dp += "/" + projection["key_member"]
                required.add((token, dp, "declaration"))
                required.add((token, f"{pp}/{root}/{member}/{ei}", "reference"))
                if projection["authority_path"] == "language.operations":
                    op = definition
                    op_scope, op_path = (owner, op["id"]), dp.rsplit("/", 1)[0]
                    for i, port in enumerate(op["inputs"]):
                        required.add(
                            (
                                AuthorityToken("operation-port", op_scope, port["id"]),
                                f"{op_path}/inputs/{i}/id",
                                "declaration",
                            )
                        )
                    if isinstance(op.get("result"), dict):
                        required.add(
                            (
                                AuthorityToken(
                                    "operation-result", op_scope, op["result"]["id"]
                                ),
                                op_path + "/result/id",
                                "declaration",
                            )
                        )
                    for i, outcome in enumerate(op.get("outcomes", [])):
                        required.add(
                            (
                                AuthorityToken(
                                    "operation-outcome", op_scope, outcome["id"]
                                ),
                                f"{op_path}/outcomes/{i}/id",
                                "declaration",
                            )
                        )
                    nodes = {
                        node["id"]: node for node in meta["runtime_program"]["nodes"]
                    }
                    pending = [(op["body"], op_path + "/body")]
                    while pending:
                        body, body_path = pending.pop()
                        for i, instruction in enumerate(body):
                            node, ip = nodes[instruction["node"]], f"{body_path}/{i}"
                            if node["result"]["kind"] in {"local", "draw"}:
                                required.add(
                                    (
                                        AuthorityToken(
                                            "operation-local",
                                            op_scope,
                                            instruction["target"],
                                        ),
                                        ip + "/target",
                                        "declaration",
                                    )
                                )
                            if node["semantics"]["operator"] in {
                                "bounded-pure-fold",
                                "invoke-operation",
                            }:
                                required.add(
                                    (
                                        AuthorityToken(
                                            "operation-site",
                                            op_scope,
                                            instruction["site"],
                                        ),
                                        ip + "/site",
                                        "declaration",
                                    )
                                )
                            if node["semantics"]["operator"] == "guarded-outcome-block":
                                pending.append((instruction["body"], ip + "/body"))
        for i, exported in enumerate(package["exports"]["types"]):
            required.add(
                (
                    AuthorityToken("type", (owner,), exported["id"]),
                    f"{pp}/exports/types/{i}/id",
                    "declaration",
                )
            )
    for i, descriptor in enumerate(
        graph.get("ldb_root", {}).get("package_descriptors", [])
    ):
        required.add(
            (
                AuthorityToken("namespace", (), descriptor["id"]),
                f"/ldb_root/package_descriptors/{i}/id",
                "reference",
            )
        )
    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        vp = f"/vector_sets/{vi}"
        required.add(
            (
                AuthorityToken("namespace", (), vector_set["package_id"]),
                vp + "/package_id",
                "reference",
            )
        )
        for member, use in (
            ("vector_definitions", "declaration"),
            ("vectors", "reference"),
        ):
            for i, row in enumerate(vector_set[member]):
                name = row["id"] if use == "declaration" else row
                path = f"{vp}/{member}/{i}" + ("/id" if use == "declaration" else "")
                owner = (
                    (vector_set["package_id"],)
                    if scopes.get("vectors") == "package"
                    else ()
                )
                required.add((AuthorityToken("vectors", owner, name), path, use))
    source = graph.get("source")
    if source:
        model = source["manifest"]["id"]
        required.add(
            (
                AuthorityToken("source-model", (), model),
                "/source/manifest/id",
                "declaration",
            )
        )
        required.add(
            (
                AuthorityToken(
                    "source-module", (model,), source["manifest"]["entry_module"]
                ),
                "/source/manifest/entry_module",
                "reference",
            )
        )
        for i, namespace in enumerate(source["package_requirements"]):
            required.add(
                (
                    AuthorityToken("namespace", (), namespace),
                    f"/source/package_requirements/{i}",
                    "reference",
                )
            )
        for mi, module in enumerate(source["modules"]):
            scope, mp = (model, module["id"]), f"/source/modules/{mi}"
            required.add(
                (
                    AuthorityToken("source-module", (model,), module["id"]),
                    mp + "/id",
                    "declaration",
                )
            )
            for ii, row in enumerate(module["imports"]):
                ip = f"{mp}/imports/{ii}"
                required.add(
                    (
                        AuthorityToken("source-type-alias", scope, row["alias"]),
                        ip + "/alias",
                        "declaration",
                    )
                )
                required.add(
                    (
                        AuthorityToken("namespace", (), row["package"]),
                        ip + "/package",
                        "reference",
                    )
                )
                required.add(
                    (
                        AuthorityToken("type", (row["package"],), row["symbol"]),
                        ip + "/symbol",
                        "reference",
                    )
                )
            for si, row in enumerate(module["symbols"]):
                sp = f"{mp}/symbols/{si}"
                required.add(
                    (
                        AuthorityToken("source-symbol", scope, row["symbol"]),
                        sp + "/symbol",
                        "declaration",
                    )
                )
                required.add(
                    (
                        AuthorityToken("source-type-alias", scope, row["type"]),
                        sp + "/type",
                        "reference",
                    )
                )
        for ei, entry in enumerate(source.get("entrypoints", [])):
            ep = f"/source/entrypoints/{ei}"
            operation = entry["operation"]
            callee = (operation["package"], operation["id"])
            required.add(
                (
                    AuthorityToken("source-entrypoint", (model,), entry["id"]),
                    ep + "/id",
                    "declaration",
                )
            )
            required.add(
                (
                    AuthorityToken("namespace", (), callee[0]),
                    ep + "/operation/package",
                    "reference",
                )
            )
            required.add(
                (
                    AuthorityToken("language.operations", (), callee[1])
                    if scopes.get("language.operations") != "package"
                    else AuthorityToken("language.operations", callee[:1], callee[1]),
                    ep + "/operation/id",
                    "reference",
                )
            )
            operands = [(entry["result"], ep + "/result")]
            for ai, argument in enumerate(entry["arguments"]):
                ap = f"{ep}/arguments/{ai}"
                required.add(
                    (
                        AuthorityToken("operation-port", callee, argument["port"]),
                        ap + "/port",
                        "reference",
                    )
                )
                operands.append((argument["operand"], ap + "/operand"))
            for operand, op in operands:
                if operand["kind"] == "symbol":
                    required.add(
                        (
                            AuthorityToken(
                                "source-module", (model,), operand["module"]
                            ),
                            op + "/module",
                            "reference",
                        )
                    )
                    required.add(
                        (
                            AuthorityToken(
                                "source-symbol",
                                (model, operand["module"]),
                                operand["symbol"],
                            ),
                            op + "/symbol",
                            "reference",
                        )
                    )
    if not required <= actual:
        first = sorted(required - actual, key=lambda row: row[1])[0]
        raise InventoryRefusal(
            f"missing or incorrectly owned declaration/export occurrence at {first[1]}"
        )
    required_paths = {(pointer, use) for _, pointer, use in required}
    for token, pointer, use in actual:
        if (pointer, use) in required_paths and (token, pointer, use) not in required:
            raise InventoryRefusal(f"wrong role or owner at {pointer}")


def _renamed_owner(
    token: AuthorityToken, correspondence: Mapping[AuthorityToken, AuthorityToken]
) -> tuple[str, ...]:
    def name(owner_token: AuthorityToken) -> str:
        target = correspondence.get(owner_token)
        return owner_token.name if target is None else target.name

    if not token.owner:
        return ()
    if token.role.startswith("source-"):
        model = name(AuthorityToken("source-model", (), token.owner[0]))
        if len(token.owner) == 1:
            return (model,)
        module = name(AuthorityToken("source-module", token.owner[:1], token.owner[1]))
        return (model, module)
    namespace = name(AuthorityToken("namespace", (), token.owner[0]))
    if len(token.owner) == 1:
        return (namespace,)
    if token.role in {"enum-member", "record-field"}:
        return (
            namespace,
            name(AuthorityToken("type", token.owner[:1], token.owner[1])),
        )
    if token.role.startswith("operation-"):
        return (
            namespace,
            name(
                AuthorityToken("language.operations", token.owner[:1], token.owner[1])
            ),
        )
    raise InventoryRefusal("unknown token ownership role")


def token_bijection_from_names(
    inventory: ExtensionInventory, names: Mapping[AuthorityToken, str]
) -> tuple[tuple[AuthorityToken, AuthorityToken], ...]:
    """Transport owner coordinates through a caller-provided name permutation.

    This constructs a candidate map; validation and complete coverage remain
    mandatory before a graph can be renamed.
    """
    provisional = {
        source: AuthorityToken(source.role, source.owner, name)
        for source, name in names.items()
    }
    return tuple(
        (
            source,
            AuthorityToken(
                source.role, _renamed_owner(source, provisional), target.name
            ),
        )
        for source, target in provisional.items()
    )
