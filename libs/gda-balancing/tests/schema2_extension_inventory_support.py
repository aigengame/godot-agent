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
    _consumer_b_definition_is_closed,
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
    projection: str = ""


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


def _occurrence_value(
    graph: Any, occurrence: TokenOccurrence, formula_projections: Mapping[str, Any]
) -> Any:
    if occurrence.location == "formula":
        return _pointer_value(
            formula_projections[occurrence.pointer], occurrence.projection
        )
    if occurrence.projection:
        raise InventoryRefusal("only Formula occurrences may have an AST projection")
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


def _attached_language(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    language: dict[str, Any] = {"packages": graph["packages"]}
    for projection in kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]:
        path = projection["authority_path"].split(".")
        if path[0] != "language":
            continue
        target = language
        for segment in path[1:-1]:
            target = target.setdefault(segment, {})
        target[path[-1]] = [
            definition
            for package in graph["packages"]
            for closure in package["semantic_closure"]
            if closure["authority_path"] == projection["authority_path"]
            for definition in closure["definitions"]
        ]
    return {"language": language}


def _formula_projections(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, Any]:
    from schema2_formula_conformance_support import parse_canonical, render_body

    source = graph.get("source")
    if not source:
        return {}
    language = _attached_language(kernel, graph)
    projections = {}
    for mi, module in enumerate(source["modules"]):
        for fi, formula in enumerate(module.get("formulas", [])):
            expression = formula.get("expression")
            if expression is None:
                continue
            request = {
                "schema_version": source["schema_version"],
                "package_requirements": source["package_requirements"],
                "module": module,
                "modules": source["modules"],
                "formula": formula,
            }
            try:
                parsed = parse_canonical(
                    expression, request, language, kernel=dict(kernel)
                )
                if render_body(formula["body"], request, language) != expression:
                    raise InventoryRefusal("Formula body and expression disagree")
                if render_body(parsed, request, language) != expression:
                    raise InventoryRefusal("Formula expression is not canonical")
            except (KeyError, TypeError, ValueError) as error:
                raise InventoryRefusal(
                    "Formula expression does not close independently"
                ) from error
            projections[f"/source/modules/{mi}/formulas/{fi}/expression"] = parsed
    return projections


def _walk_member_path(value: Any, pointer: str, members: Sequence[str]):
    """Follow the Kernel path language, retaining each authored array position."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk_member_path(item, _child(pointer, i), members)
    elif not members:
        yield value, pointer
    elif isinstance(value, dict) and members[0] in value:
        yield from _walk_member_path(
            value[members[0]], _child(pointer, members[0]), members[1:]
        )


def _authority_path_rows(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], path: str
):
    if path.startswith("kernel."):
        yield from (
            (None, value, pointer)
            for value, pointer in _walk_member_path(kernel, "", path.split(".")[1:])
        )
        return
    if not path.startswith("language_bundle."):
        raise InventoryRefusal("unknown authority path root")
    tail = path.removeprefix("language_bundle.")
    if tail == "language.packages" or tail.startswith("language.packages."):
        suffix = (
            tail.removeprefix("language.packages").lstrip(".").split(".")
            if tail != "language.packages"
            else []
        )
        for pi, package in enumerate(graph["packages"]):
            yield from (
                (package["id"], value, pointer)
                for value, pointer in _walk_member_path(
                    package, f"/packages/{pi}", suffix
                )
            )
        return
    if tail == "vectors" or tail.startswith("vectors."):
        suffix = (
            tail.removeprefix("vectors").lstrip(".").split(".")
            if tail != "vectors"
            else []
        )
        for vi, vector_set in enumerate(graph.get("vector_sets", [])):
            yield from (
                (vector_set["package_id"], value, pointer)
                for value, pointer in _walk_member_path(
                    vector_set["vector_definitions"],
                    f"/vector_sets/{vi}/vector_definitions",
                    suffix,
                )
            )
        return
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    matching = [
        row
        for row in projections
        if tail == row["authority_path"] or tail.startswith(row["authority_path"] + ".")
    ]
    if len(matching) != 1:
        raise InventoryRefusal("authority path has no unique authored projection")
    role = matching[0]["authority_path"]
    suffix = tail.removeprefix(role).lstrip(".").split(".") if tail != role else []
    for pi, package in enumerate(graph["packages"]):
        for ci, closure in enumerate(package["semantic_closure"]):
            if closure["authority_path"] == role:
                yield from (
                    (package["id"], value, pointer)
                    for value, pointer in _walk_member_path(
                        closure["definitions"],
                        f"/packages/{pi}/semantic_closure/{ci}/definitions",
                        suffix,
                    )
                )


def _declared_target_role(kernel: Mapping[str, Any], path: str) -> tuple[str, bool]:
    if path.startswith("kernel."):
        return path, False
    if path == "language_bundle.language.packages.id":
        return "namespace", False
    if path == "language_bundle.language.packages.exports.types.id":
        return "type", True
    if path == "language_bundle.vectors.id":
        return "vectors", False
    scoped = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.identifiers.unique"
    )["arguments"]["collections"]
    for projection in kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]:
        role = projection["authority_path"]
        target = (
            "language_bundle."
            + role
            + ("." + projection["key_member"] if projection["key_member"] else "")
        )
        if path == target:
            if role == "language.nominal_types":
                return "type", True
            return role, any(
                row["path"] == "language_bundle." + role
                and row.get("scope") == "package"
                for row in scoped
            )
    raise InventoryRefusal("reference target is not an authored identity inventory")


def _declared_metadata_links(kernel: Mapping[str, Any], graph: Mapping[str, Any]):
    """Interpret existing reference and equality laws, without scanning spellings."""
    li, law = next(
        (i, row)
        for i, row in enumerate(kernel["admission"]["laws"])
        if row["id"] == "kernel.vectors.closed"
    )
    arguments = law["arguments"]
    for ri, reference in enumerate(arguments["references"]):
        for owner, value, pointer in _authority_path_rows(
            kernel, graph, reference["owners"]
        ):
            for member_path, target in reference["targets"].items():
                for name, occurrence in _walk_member_path(
                    value, pointer, member_path.split(".")
                ):
                    yield (
                        owner,
                        name,
                        occurrence,
                        target,
                        f"/admission/laws/{li}/arguments/references/{ri}",
                    )
    for ei, equality in enumerate(arguments["equalities"]):
        target = equality["left"]
        paths = []
        if "right" in equality:
            paths.append(equality["right"])
        else:
            profile = equality["profile"]
            candidates = list(_authority_path_rows(kernel, graph, profile["profiles"]))
            for _, owner, _ in _authority_path_rows(kernel, graph, profile["owners"]):
                selected = [
                    value
                    for _, value, _ in candidates
                    if value[profile["profile_key_member"]]
                    == owner[profile["owner_profile_member"]]
                ]
                if len(selected) != 1:
                    raise InventoryRefusal(
                        "schema equality profile does not resolve uniquely"
                    )
                segments = [
                    selected[0][part["profile_member"]]
                    if isinstance(part, dict)
                    else part
                    for part in equality["right_template"]
                ]
                paths.append(".".join(segments))
        for path in sorted(set(paths)):
            for owner, name, pointer in _authority_path_rows(kernel, graph, path):
                yield (
                    owner,
                    name,
                    pointer,
                    target,
                    f"/admission/laws/{li}/arguments/equalities/{ei}",
                )


def _source_format_role(kernel: Mapping[str, Any], graph: Mapping[str, Any]) -> str:
    """Keep Source protocol format parameters distinct from nominal identities."""
    role = "language.model_source_schema_versions"
    left = "language_bundle." + role
    right = (
        "language_bundle.language.wire_schemas.schema.properties.schema_version.const"
    )
    law = next(
        row
        for row in kernel["admission"]["laws"]
        if row["id"] == "kernel.vectors.closed"
    )
    if not any(
        row.get("left") == left and row.get("right") == right
        for row in law["arguments"]["equalities"]
    ):
        raise InventoryRefusal("Source format parameter has no declared wire equality")
    actual = {value for _, value, _ in _authority_path_rows(kernel, graph, left)}
    expected = {value for _, value, _ in _authority_path_rows(kernel, graph, right)}
    if actual != expected:
        raise InventoryRefusal(
            "Source format parameter does not match its wire contract"
        )
    return role


def _constructor_member_selectors(constructor: Mapping[str, Any]):
    for selector, name in constructor["value_rule"].items():
        if selector.endswith("_member"):
            area = (
                "record-field"
                if selector in {"field_name_member", "field_type_member"}
                else "definition"
            )
            yield selector, name, area


class _Reader:
    def __init__(self, kernel: Mapping[str, Any], graph: Mapping[str, Any]):
        self.kernel = kernel
        self.graph = graph
        self.meta = kernel["meta_format"]
        self.source_format_role = _source_format_role(kernel, graph)
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
        self.occurrence_positions: set[tuple[AuthorityToken, str, str, str, str]] = (
            set()
        )
        self.uncovered: set[UncoveredRole] = set()
        self.reserved: set[AuthorityToken] = set()
        self.definitions: dict[tuple[str, str, str], tuple[Any, str]] = {}
        self.types: dict[tuple[str, str], dict[str, Any]] = {}
        self.nodes = {row["id"]: row for row in self.meta["runtime_program"]["nodes"]}
        self.node_laws = {
            row["id"]: f"/meta_format/runtime_program/nodes/{i}"
            for i, row in enumerate(self.meta["runtime_program"]["nodes"])
        }
        self.formula_projections: dict[str, Any] = {}
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
        projection: str = "",
    ) -> None:
        if not isinstance(token.name, str) or not token.name:
            raise InventoryRefusal(f"invalid token at {pointer}")
        occurrence = TokenOccurrence(token, pointer, use, law, location, projection)
        if (
            _occurrence_value(self.graph, occurrence, self.formula_projections)
            != token.name
        ):
            raise InventoryRefusal(
                f"token occurrence does not match bytes at {pointer}"
            )
        self.tokens.add(token)
        position = (token, pointer, use, location, projection)
        if position in self.occurrence_positions:
            return
        self.occurrence_positions.add(position)
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
                    if role == self.source_format_role:
                        continue
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
                    if role == self.source_format_role:
                        continue
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
            root_contract = self.meta["language_bundle"]
            if not _consumer_b_definition_is_closed(
                root,
                {
                    "required_members": root_contract["required_members"],
                    "field_types": root_contract["member_types"],
                },
                {},
            ) or not _consumer_b_definition_is_closed(
                root["resources"], root_contract["resources"], {}
            ):
                raise InventoryRefusal(
                    "LDB root does not close its Kernel member contracts"
                )
            if root["kernel_identity"] != self.kernel["content_identity"]:
                raise InventoryRefusal("LDB root does not bind the supplied Kernel")
            descriptors = root["package_descriptors"]
            if not all(
                _consumer_b_definition_is_closed(
                    row, root_contract["package_descriptor"], {}
                )
                for row in descriptors
            ):
                raise InventoryRefusal(
                    "LDB package descriptor does not close its Kernel contract"
                )
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
            # All remaining root fields are Kernel format/resource parameters or
            # generated identity/byte framing. Renaming's existing seal consumer
            # rederives that framing; it is not an authored nominal token.
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
        language = _attached_language(self.kernel, self.graph)
        closed: dict[tuple[str, str], tuple[set[str], set[str], int]] = {}
        subjects = _consumer_b_operation_composition_subjects(
            dict(self.kernel),
            language,
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
        if set(definition) != {"kind", *constructor["parameters"]}:
            raise InventoryRefusal(
                f"structured definition has undeclared members at {pointer}"
            )
        rule = constructor["value_rule"]
        law = cp + "/value_rule"
        for member in constructor["parameters"]:
            self.occurrence(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "definition"), member
                ),
                _child(pointer, member),
                "reference",
                law,
                location="key",
            )
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
                if set(field) != {rule["field_name_member"], rule["field_type_member"]}:
                    raise InventoryRefusal(
                        f"Record field has undeclared members at {fp}"
                    )
                for selector in ("field_name_member", "field_type_member"):
                    member = rule[selector]
                    self.occurrence(
                        AuthorityToken(
                            "constructor-member",
                            (constructor["id"], "record-field"),
                            member,
                        ),
                        _child(fp, member),
                        "reference",
                        law,
                        location="key",
                    )
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
        elif rule["operator"] == "canonical-ref-key":
            if set(value) != set(rule["value_members"]):
                raise InventoryRefusal(
                    "Ref value does not close its declared member addresses"
                )
            for member in rule["value_members"]:
                self.occurrence(
                    AuthorityToken(
                        "constructor-member", (constructor["id"], "ref-value"), member
                    ),
                    _child(pointer, member),
                    "reference",
                    law,
                    location="key",
                )
        else:
            raise InventoryRefusal(f"unknown typed value law at {pointer}")
        # A canonical Ref key is authored instance data; its target Type was
        # traversed above. Equal spelling does not make the key an Enum label.

    def type_identity_edges(self) -> None:
        """Follow authored Type-id selectors without inventing a nominal owner."""
        self.type_edge_occurrences: set[str] = set()
        for (_, role, _), (lowering, pointer) in self.definitions.items():
            if role != "language.model_lowerings":
                continue
            projection = lowering["runtime_projection"]
            collections = {row["id"]: row for row in projection["collections"]}
            for ei, edge in enumerate(projection["edges"]):
                source = collections[edge["source_collection"]]["source"]
                target = collections[edge["target_collection"]]["source"]
                if (
                    source["kind"] != "namespace-member"
                    or source["member"] != "types"
                    or edge["source_path"] != ["id"]
                ):
                    continue
                if target["kind"] != "semantic-closure" or edge["operator"] != "equal":
                    raise InventoryRefusal(
                        "Type identity edge has an unsupported target law"
                    )
                for (owner, target_role, _), (
                    definition,
                    dp,
                ) in self.definitions.items():
                    if target_role != target["authority_path"]:
                        continue
                    for name, occurrence in _walk_member_path(
                        definition, dp, edge["target_path"]
                    ):
                        matches = [
                            coordinate
                            for coordinate in self.types
                            if coordinate[1] == name
                            and (not edge["same_package"] or coordinate[0] == owner)
                        ]
                        if not matches:
                            if edge.get("missing_target") != "not-applicable":
                                raise InventoryRefusal(
                                    "Type identity selector has no provider"
                                )
                            self.gap(
                                occurrence,
                                pointer + "/runtime_projection/edges/" + str(ei),
                                "Type identity selector has no declared matching owner",
                            )
                        for coordinate in matches:
                            self.occurrence(
                                AuthorityToken("type", coordinate[:1], coordinate[1]),
                                occurrence,
                                "reference",
                                pointer + "/runtime_projection/edges/" + str(ei),
                            )
                            self.type_edge_occurrences.add(occurrence)

    def metadata_links(self) -> None:
        for owner, name, pointer, target, law in _declared_metadata_links(
            self.kernel, self.graph
        ):
            role, scoped = _declared_target_role(self.kernel, target)
            if role == self.source_format_role:
                continue
            token = AuthorityToken(
                role, (owner,) if scoped and owner is not None else (), name
            )
            if target.startswith("kernel."):
                declared = {
                    value
                    for _, value, _ in _authority_path_rows(
                        self.kernel, self.graph, target
                    )
                }
                if name not in declared:
                    raise InventoryRefusal(
                        "reference does not name a declared Kernel primitive"
                    )
                self.reserved.add(token)
            elif token not in self.tokens:
                raise InventoryRefusal(
                    f"unresolved declared metadata reference at {pointer}"
                )
            self.occurrence(token, pointer, "reference", law)

    def metadata_definition(
        self, role: str, value: dict[str, Any], pointer: str
    ) -> bool:
        """Close simple declared contracts; unknown nested DSLs remain explicit."""
        if role == "language.rules":
            self.rule(value, pointer)
            return True
        if role in {
            "language.quantity.units",
            "language.components",
            "language.constructors",
            "language.conversions",
            "language.structured_operations",
        }:
            contracts = self.meta["language_definitions"]
            if role.startswith("language.quantity."):
                contracts = contracts["quantity"]
            contract = contracts["collections"][role.rsplit(".", 1)[1]]
            if not _consumer_b_definition_is_closed(
                value, contract, _attached_language(self.kernel, self.graph)
            ):
                raise InventoryRefusal(
                    "typed metadata does not close its declared Kernel shape"
                )
            if role == "language.quantity.units":
                self.occurrence(
                    AuthorityToken("unit-dimension", (), value["dimension"]),
                    pointer + "/dimension",
                    "declaration",
                    "/meta_format/language_definitions/quantity/collections/units",
                )
            elif role == "language.components":
                self.reference(
                    "language.constructors",
                    value["constructor"],
                    pointer + "/constructor",
                    "/meta_format/language_definitions/collections/components",
                )
                fact_members = {
                    name
                    for fields in self.meta["fact"]["field_contracts"].values()
                    for name in fields
                }
                if not set(value["fields"]) <= fact_members:
                    raise InventoryRefusal(
                        "component field does not address a declared fact member"
                    )
            elif role == "language.constructors":
                rule = value.get("value_rule")
                if not isinstance(rule, dict):
                    raise InventoryRefusal("constructor has no declared value rule")
                if "definition_kind" in rule:
                    for selector, member, area in _constructor_member_selectors(value):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member", (value["id"], area), member
                            ),
                            pointer + "/value_rule/" + selector,
                            "declaration",
                            pointer + "/value_rule",
                        )
                    for i, member in enumerate(value["parameters"]):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member",
                                (value["id"], "definition"),
                                member,
                            ),
                            f"{pointer}/parameters/{i}",
                            "reference",
                            pointer + "/value_rule",
                        )
                    for i, member in enumerate(rule.get("value_members", [])):
                        self.occurrence(
                            AuthorityToken(
                                "constructor-member", (value["id"], "ref-value"), member
                            ),
                            f"{pointer}/value_rule/value_members/{i}",
                            "declaration",
                            pointer + "/value_rule",
                        )
                    nested = {"field_name_member", "field_type_member"}
                    members = {
                        item
                        for name, item in rule.items()
                        if name.endswith("_member") and name not in nested
                    }
                    if set(value["parameters"]) != members:
                        raise InventoryRefusal(
                            "constructor parameters do not close its definition member selectors"
                        )
                elif rule["operator"] == "exact-integer":
                    fields = {
                        name
                        for row in self.meta["fact"]["field_contracts"].values()
                        for name in row
                    }
                    if not set(value["parameters"]) <= fields:
                        raise InventoryRefusal(
                            "scalar constructor parameter has no declared fact field"
                        )
                else:
                    raise InventoryRefusal("constructor primitive rule is unclassified")
            elif role == "language.structured_operations":
                self.reference(
                    "language.constructors",
                    value["owner_constructor"],
                    pointer + "/owner_constructor",
                    "/meta_format/language_definitions/collections/structured_operations",
                )
                if "refusal_signal" in value["law"]:
                    signal = value["law"]["refusal_signal"]
                    token = AuthorityToken("diagnostic-signal", ("runtime",), signal)
                    self.occurrence(
                        token,
                        pointer + "/law/refusal_signal",
                        "reference",
                        "/meta_format/runtime_program/nodes",
                    )
                    if any(
                        signal in node.get("refusals", [])
                        for node in self.nodes.values()
                    ):
                        self.reserved.add(token)
            return True
        if role == "diagnostics":
            contract = self.meta["admitted_language_index"]["diagnostic"]
            if (
                set(value) != set(contract["required_members"])
                or value["stage"] not in self.kernel["admission"]["refusal_stages"]
            ):
                raise InventoryRefusal(
                    "diagnostic definition does not match Kernel contract"
                )
            return True
        if role in {
            "language.capabilities",
            "language.model_checks",
            "language.quantity.numeric_policies",
        }:
            parts = role.split(".")
            root = self.meta["language_definitions"]
            if len(parts) == 3:
                root = root[parts[1]]
            contract = root["collections"][parts[-1]]
            required, optional = (
                set(contract["required_members"]),
                set(contract.get("optional_members", [])),
            )
            if not required <= set(value) <= required | optional:
                raise InventoryRefusal("metadata definition has unknown members")
            for name, field in contract["field_types"].items():
                if name in value and (
                    ("const" in field and value[name] != field["const"])
                    or ("enum" in field and value[name] not in field["enum"])
                ):
                    raise InventoryRefusal(
                        "metadata primitive marker does not match Kernel contract"
                    )
            if value.get("extensions"):
                self.gap(
                    pointer + "/extensions",
                    "/meta_format/language_definitions",
                    "metadata extension roles are not yet complete",
                )
            return True
        if role == "language.reasons":
            contract = self.meta["diagnostic_reason"]
            required, optional = (
                set(contract["required_members"]),
                set(contract["optional_members"]),
            )
            if not required <= set(value) <= required | optional:
                raise InventoryRefusal("reason has unknown members")
            self.reference(
                "diagnostics",
                value["diagnostic"],
                pointer + "/diagnostic",
                "/meta_format/diagnostic_reason",
            )
            if value["stage"] not in contract["member_types"]["stage"]["enum"]:
                raise InventoryRefusal("reason has unknown stage")
            predicate = value["predicate"]
            rules = [
                row
                for row in contract["predicate_schemas"]
                if row["operation"] == predicate.get("operation")
            ]
            if len(rules) != 1:
                raise InventoryRefusal("reason predicate has unknown operator")
            rule = rules[0]
            if (
                not set(rule["required_members"])
                <= set(predicate)
                <= set(rule["required_members"]) | set(rule["optional_members"])
            ):
                raise InventoryRefusal("reason predicate has unknown members")
            if "inventory_path" in predicate:
                projection = next(
                    (
                        row
                        for row in self.projections
                        if row["authority_path"] == predicate["inventory_path"]
                    ),
                    None,
                )
                if (
                    projection is None
                    or predicate.get("member_field") != projection["key_member"]
                ):
                    raise InventoryRefusal(
                        "reason predicate does not address a declared inventory key"
                    )
            if "limit_path" in predicate:
                member = predicate["limit_path"].removeprefix("resources.")
                if (
                    not predicate["limit_path"].startswith("resources.")
                    or member not in self.graph["ldb_root"]["resources"]
                ):
                    raise InventoryRefusal(
                        "reason predicate limit is not a declared resource"
                    )
            if "signal" in value:
                token = AuthorityToken(
                    "diagnostic-signal", (value["stage"],), value["signal"]
                )
                self.occurrence(
                    token,
                    pointer + "/signal",
                    "declaration",
                    "/meta_format/diagnostic_reason",
                )
                primitive_signals = {
                    ("runtime", signal)
                    for node in self.meta["runtime_program"]["nodes"]
                    for signal in node.get("refusals", [])
                } | {
                    (root["stage"], root["signal"])
                    for root in self.meta["runtime_projection"]["execution_closure"][
                        "reasons"
                    ]["roots"]
                    if "stage" in root and "signal" in root
                }
                if (value["stage"], value["signal"]) in primitive_signals:
                    self.reserved.add(token)
            return True
        if role == "language.literal_typing_profiles":
            if value.get("source_kind") == "typed-envelope":
                law = self.meta["literal_typing"]["typed_envelope_profile"]
                if (
                    set(value) != {"admission", "id", "source_kind", "value_kind"}
                    or value["admission"] != law["admission"]
                    or value["value_kind"] != law["value_kind"]
                ):
                    raise InventoryRefusal(
                        "typed profile does not match its primitive contract"
                    )
            elif value.get("source_kind") == "integer":
                allowed = {
                    "id",
                    "type",
                    "minimum",
                    "maximum",
                    "representation",
                    "kind",
                    "unit",
                    "domain",
                    "numeric_policy",
                    "source_kind",
                }
                if set(value) != allowed:
                    raise InventoryRefusal("integer profile has unclassified members")
                self.value_contract(value, pointer)
            else:
                raise InventoryRefusal("literal profile source kind is unclassified")
            return True
        if role == "language.runtime_profiles":
            for i, name in enumerate(value["effects"]):
                self.occurrence(
                    AuthorityToken("runtime-effect", (), name),
                    f"{pointer}/effects/{i}",
                    "declaration",
                    "/meta_format/runtime_profile_definition",
                )
            contract = self.meta["runtime_profile_definition"]["active_runtime"]
            if value["evaluation"] == self.meta["runtime_program"]["version"]:
                required, optional = (
                    set(contract["required_members"]),
                    set(contract["optional_members"]),
                )
                if not required <= set(value) <= required | optional:
                    raise InventoryRefusal(
                        "active Runtime profile has unclassified members"
                    )
            elif value["evaluation"] != "declaration-only" or set(value) != {
                "id",
                "numeric_policy",
                "effects",
                "evaluation",
                "resource_bounds",
            }:
                raise InventoryRefusal("Runtime profile evaluation law is unclassified")
            if value.get("extensions"):
                self.gap(
                    pointer + "/extensions",
                    "/meta_format/runtime_profile_definition",
                    "Runtime profile extension roles are not yet complete",
                )
            return True
        return False

    def rule(self, value: dict[str, Any], pointer: str) -> None:
        """Interpret the existing premise-binding and conclusion-term grammar."""
        contract = self.meta["rule"]
        if (
            set(value) != set(contract["required_members"])
            or value["phase"] not in contract["phases"]
        ):
            raise InventoryRefusal("Language rule has an unknown shape or phase")
        law = "/meta_format/binding_substitution"
        self.occurrence(
            AuthorityToken("rule-judgment", (), value["judgment"]),
            pointer + "/judgment",
            "declaration",
            "/meta_format/rule_selection",
        )
        schemas = {
            row["kind"]: self.meta["fact"]["field_contracts"][row["field_contract"]]
            for row in self.meta["fact"]["schemas"]
        }
        bindings: set[str] = set()
        for pi, premise in enumerate(value["premises"]):
            pp = f"{pointer}/premises/{pi}"
            if set(premise) != set(contract["premise_required_members"]):
                raise InventoryRefusal("Language rule premise has unknown members")
            fields = schemas.get(premise["fact_kind"])
            if fields is None or any(
                name not in fields for name in premise["bind"].values()
            ):
                raise InventoryRefusal(
                    "Language rule premise does not address a Kernel fact"
                )
            for name in premise["bind"]:
                bindings.add(name)
                self.occurrence(
                    AuthorityToken("rule-variable", (value["id"],), name),
                    _child(pp + "/bind", name),
                    "declaration",
                    law,
                    location="key",
                )
        conclusion = value["conclusion"]
        if set(conclusion) != set(contract["conclusion_required_members"]):
            raise InventoryRefusal("Language rule conclusion has unknown members")
        fields = schemas.get(conclusion["fact_kind"])
        if fields is None or set(conclusion["fields"]) != set(fields):
            raise InventoryRefusal(
                "Language rule conclusion does not close its Kernel fact"
            )
        constructors = {row["tag"]: row for row in self.meta["term"]["constructors"]}
        for field, term in conclusion["fields"].items():
            tp = _child(pointer + "/conclusion/fields", field)
            shape = constructors.get(term.get("tag"))
            if shape is None or set(term) != set(shape["required_members"]):
                raise InventoryRefusal("Language rule conclusion has an unknown term")
            if term["tag"] == "variable":
                if term["name"] not in bindings:
                    raise InventoryRefusal("Language rule term has an unbound variable")
                self.occurrence(
                    AuthorityToken("rule-variable", (value["id"],), term["name"]),
                    tp + "/name",
                    "reference",
                    law,
                )
            elif term["tag"] == "literal":
                field_contract = fields[field]
                if field_contract.get("type") == "inventory-member":
                    role, scoped = _declared_target_role(
                        self.kernel, "language_bundle." + field_contract["path"]
                    )
                    if scoped:
                        raise InventoryRefusal("unqualified scoped fact literal")
                    self.reference(role, term["value"], tp + "/value", law)
                else:
                    self.gap(
                        tp + "/value",
                        law,
                        "non-inventory fact literal requires its typed role traversal",
                    )

    def rule_chain_links(self) -> None:
        for (_, role, _), (value, pointer) in self.definitions.items():
            if role != "language.model_lowerings":
                continue
            for member in ("rule_chain", "structured_rule_chain"):
                for i, step in enumerate(value[member]):
                    self.occurrence(
                        AuthorityToken("rule-judgment", (), step["judgment"]),
                        f"{pointer}/{member}/{i}/judgment",
                        "reference",
                        "/meta_format/rule_selection",
                    )

    def assignment_policies(self) -> None:
        for (_, role, _), (lowering, pointer) in self.definitions.items():
            if role != "language.model_lowerings":
                continue
            policy = lowering["assignment_policy"]
            pp = pointer + "/assignment_policy"
            scope = (lowering["id"],)
            self.occurrence(
                AuthorityToken("assignment-policy", scope, policy["id"]),
                pp + "/id",
                "declaration",
                "/meta_format/language_definitions/collections/model_lowerings/field_types/assignment_policy",
            )
            for ri, row in enumerate(policy["roles"]):
                rp = f"{pp}/roles/{ri}"
                self.reference(
                    "language.quantity.symbol_roles", row["role"], rp + "/role", pp
                )
                names = [mode["id"] for mode in row["modes"]]
                if len(names) != len(set(names)):
                    raise InventoryRefusal(
                        "duplicate assignment mode within a Symbol role"
                    )
                for mi, mode in enumerate(row["modes"]):
                    self.occurrence(
                        AuthorityToken(
                            "assignment-mode",
                            (*scope, policy["id"], row["role"]),
                            mode["id"],
                        ),
                        f"{rp}/modes/{mi}/id",
                        "declaration",
                        pp,
                    )

    def source_assignment_policy(self) -> tuple[dict[str, Any], str, str]:
        profiles = [
            definition
            for (_, role, _), (definition, _) in self.definitions.items()
            if role == "language.resolution_profiles"
            and definition.get("default") is True
        ]
        if len(profiles) != 1:
            raise InventoryRefusal("Source has no unique default resolution profile")
        owners = [
            (definition, pointer)
            for (_, role, name), (definition, pointer) in self.definitions.items()
            if role == "language.model_lowerings"
            and name == profiles[0]["model_lowering"]
        ]
        if len(owners) != 1:
            raise InventoryRefusal(
                "Source assignment policy has no unique lowering owner"
            )
        lowering, pointer = owners[0]
        return (
            lowering["assignment_policy"],
            pointer + "/assignment_policy",
            lowering["id"],
        )

    def source_value_policy(
        self, symbol: dict[str, Any], pointer: str, type_reference: dict[str, str]
    ) -> None:
        policy, law, lowering = self.source_assignment_policy()
        roles = [row for row in policy["roles"] if row["role"] == symbol["role"]]
        if len(roles) != 1:
            raise InventoryRefusal(
                "Source Symbol role does not select one assignment contract"
            )
        value = symbol["value_policy"]
        modes = [mode for mode in roles[0]["modes"] if mode["id"] == value["mode"]]
        if len(modes) != 1:
            raise InventoryRefusal("Source value policy does not select one mode")
        expected = {"mode"} | (
            {"value"} if modes[0]["value_member"] == "required" else set()
        )
        if set(value) != expected:
            raise InventoryRefusal(
                "Source value policy does not match its mode's closed members"
            )
        self.occurrence(
            AuthorityToken(
                "assignment-mode",
                (lowering, policy["id"], symbol["role"]),
                value["mode"],
            ),
            pointer + "/value_policy/mode",
            "reference",
            law,
        )
        if "value" in value:
            literal = value["value"]
            if isinstance(literal, dict) and set(literal) == {"type", "value"}:
                self.typed_literal(literal, pointer + "/value_policy/value")
            else:
                self.typed_value(
                    type_reference, literal, pointer + "/value_policy/value"
                )

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
            if role == self.source_format_role:
                continue
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
            elif isinstance(definition, dict) and self.metadata_definition(
                role, definition, pointer
            ):
                continue
            elif isinstance(definition, dict):
                self.gap(
                    pointer,
                    "/meta_format/language_definitions",
                    f"nested {role} roles are not yet traversed",
                )
            else:
                scalar_contracts = self.meta["language_definitions"]["quantity"][
                    "collections"
                ]
                member = role.removeprefix("language.quantity.")
                if (
                    member not in scalar_contracts
                    or scalar_contracts[member].get("item_type") != "non-empty-string"
                ):
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
        for i, effect in enumerate(operation.get("effects", [])):
            self.reference(
                "runtime-effect",
                effect,
                f"{pointer}/effects/{i}",
                "/meta_format/runtime_profile_definition",
            )
        self.operation_formula_extensions(operation, pointer, scope, bindings)
        for member in ("owner_type",):
            if (
                member == "owner_type"
                and pointer + "/owner_type" in self.type_edge_occurrences
            ):
                continue
            if member in operation and operation[member]:
                self.gap(
                    pointer + "/" + member,
                    "/meta_format/language_definitions/collections/operations",
                    f"Operation {member} links are not yet complete",
                )

    def operation_formula_extensions(
        self,
        operation: dict[str, Any],
        pointer: str,
        scope: tuple[str, str],
        bindings: dict[str, AuthorityToken],
    ) -> None:
        for key, extension in operation.get("extensions", {}).items():
            ep = _child(pointer + "/extensions", key)
            if key == "standard.formula-notation":
                if extension["kind"] == "function":
                    if set(extension) != {"kind", "name", "ordered_ports"}:
                        raise InventoryRefusal(
                            "Formula function notation has unknown members"
                        )
                    self.occurrence(
                        AuthorityToken("operation-notation", scope, extension["name"]),
                        ep + "/name",
                        "declaration",
                        ep,
                    )
                elif extension["kind"] == "infix":
                    if set(extension) != {
                        "kind",
                        "token",
                        "ordered_ports",
                        "precedence",
                        "associativity",
                    }:
                        raise InventoryRefusal(
                            "Formula infix notation has unknown members"
                        )
                    self.occurrence(
                        AuthorityToken("operation-notation", scope, extension["token"]),
                        ep + "/token",
                        "declaration",
                        ep,
                    )
                else:
                    raise InventoryRefusal("Formula notation kind is unknown")
                for i, port in enumerate(extension["ordered_ports"]):
                    self.occurrence(
                        AuthorityToken("operation-port", scope, port),
                        f"{ep}/ordered_ports/{i}",
                        "reference",
                        ep,
                    )
            elif key == "standard.formula-slots":
                if not isinstance(extension, list):
                    raise InventoryRefusal("Formula slots are not a list")
                for i, slot in enumerate(extension):
                    sp = f"{ep}/{i}"
                    if set(slot) != {
                        "id",
                        "context",
                        "parameters",
                        "permitted_refusals",
                        "placeholder_index",
                        "placeholder_length",
                        "resource_bounds",
                        "result",
                        "target",
                        "termination_measure",
                    }:
                        raise InventoryRefusal("Formula slot has unknown members")
                    slot_scope = (*scope, slot["id"])
                    self.occurrence(
                        AuthorityToken("operation-slot", scope, slot["id"]),
                        sp + "/id",
                        "declaration",
                        ep,
                    )
                    self.operand(slot["target"], sp + "/target", scope, bindings, ep)
                    self.value_contract(slot["result"], sp + "/result")
                    for pi, parameter in enumerate(slot["parameters"]):
                        pp = f"{sp}/parameters/{pi}"
                        self.occurrence(
                            AuthorityToken(
                                "operation-slot-parameter", slot_scope, parameter["id"]
                            ),
                            pp + "/id",
                            "declaration",
                            ep,
                        )
                        self.value_contract(parameter, pp)
                        source = parameter["source"]
                        if source["kind"] not in {"port", "local"}:
                            raise InventoryRefusal(
                                "unknown Formula slot parameter source"
                            )
                        self.operand(
                            source["name"], pp + "/source/name", scope, bindings, ep
                        )
                    for ri, reason in enumerate(slot["permitted_refusals"]):
                        self.reference(
                            "language.reasons",
                            reason,
                            f"{sp}/permitted_refusals/{ri}",
                            ep,
                        )
            else:
                self.gap(
                    ep,
                    "/meta_format/language_definitions/collections/operations",
                    "Operation extension roles are not yet complete",
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
            if operator == "collection-is-empty":
                members.add("value")
            elif operator == "bounded-list-append":
                members.add("item")
            elif operator == "typed-require":
                member = node["semantics"]["refusal_reference"]["instruction_member"]
                self.reference(
                    "language.reasons", instruction[member], _child(ip, member), law
                )
                consumed.update({member, "expected"})
            elif operator == "gameplay-precondition":
                self.occurrence(
                    AuthorityToken("operation-outcome", scope, instruction["outcome"]),
                    ip + "/outcome",
                    "reference",
                    law,
                )
                consumed.add("outcome")
            elif operator == "named-integer-draw":
                self.occurrence(
                    AuthorityToken("named-stream", (), instruction["stream"]),
                    ip + "/stream",
                    "declaration",
                    "/meta_format/runtime_program/named_rng/stream_derivation",
                )
                consumed.add("stream")
            elif operator == "cancel-event":
                self.occurrence(
                    AuthorityToken("operation-site", scope, instruction["site"]),
                    ip + "/site",
                    "declaration",
                    law,
                )
                self.operand(instruction["event"], ip + "/event", scope, bindings, law)
                consumed.update({"event", "site"})
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
            if operator in {
                "bounded-pure-fold",
                "invoke-operation",
                "schedule-operation",
            }:
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
                    consumed.add("result")
                    if operator == "schedule-operation":
                        members.update({"logical_time", "priority"})
                    else:
                        consumed.add("outcomes")
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
                    for oi, outcome in enumerate(instruction.get("outcomes", [])):
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
        self.formula_projections = _formula_projections(self.kernel, self.graph)
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
            alias_types = {}
            for ii, import_ in enumerate(module["imports"]):
                ip = f"{mp}/imports/{ii}"
                alias = AuthorityToken(
                    "source-type-alias", module_scope, import_["alias"]
                )
                aliases[import_["alias"]] = alias
                alias_types[import_["alias"]] = {
                    "package": import_["package"],
                    "id": import_["symbol"],
                }
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
                self.source_value_policy(symbol, sp, alias_types[symbol["type"]])
            if module.get("formulas"):
                self.formulas(source, module, mp, aliases)
        self.formula_bindings(source)
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

    def source_contract(
        self, value: dict[str, Any], pointer: str, aliases: Mapping[str, AuthorityToken]
    ) -> None:
        if "type" in value:
            name = value["type"]
            alias = aliases.get(name)
            if alias is None:
                policy, _, profile = self.formula_policy()
                fixed = {row["alias"] for row in policy["fixed_value_type_aliases"]}
                if name not in fixed:
                    raise InventoryRefusal(f"unknown Formula Type alias at {pointer}")
                alias = AuthorityToken("formula-fixed-alias", (profile,), name)
            self.occurrence(
                alias,
                pointer + "/type",
                "reference",
                "/meta_format/resolution_judgment",
            )
        self.value_contract(
            {key: val for key, val in value.items() if key != "type"}, pointer
        )

    def formulas(
        self,
        source: dict[str, Any],
        module: dict[str, Any],
        pointer: str,
        aliases: Mapping[str, AuthorityToken],
    ) -> None:
        policy, law, _ = self.formula_policy()
        model = source["manifest"]["id"]
        module_scope = (model, module["id"])
        for fi, formula in enumerate(module.get(policy["module_formulas_member"], [])):
            fp = f"{pointer}/{policy['module_formulas_member']}/{fi}"
            name = formula[policy["formula_id_member"]]
            scope = (*module_scope, name)
            self.occurrence(
                AuthorityToken("source-formula", module_scope, name),
                fp + "/" + policy["formula_id_member"],
                "declaration",
                law,
            )
            parameters = {}
            for pi, parameter in enumerate(
                formula[policy["formula_parameters_member"]]
            ):
                pp = f"{fp}/{policy['formula_parameters_member']}/{pi}"
                token = AuthorityToken(
                    "source-formula-parameter",
                    scope,
                    parameter[policy["parameter_id_member"]],
                )
                if token.name in parameters:
                    raise InventoryRefusal("duplicate Formula parameter")
                parameters[token.name] = token
                self.occurrence(
                    token, pp + "/" + policy["parameter_id_member"], "declaration", law
                )
                self.source_contract(parameter, pp, aliases)
            self.source_contract(
                formula[policy["formula_result_member"]],
                fp + "/" + policy["formula_result_member"],
                aliases,
            )
            body = formula[policy["formula_body_member"]]
            self.formula_body(
                body,
                fp + "/" + policy["formula_body_member"],
                scope,
                aliases,
                parameters,
                policy,
                law,
            )
            ep = fp + "/expression"
            if ep in self.formula_projections:
                self.formula_body(
                    self.formula_projections[ep],
                    ep,
                    scope,
                    aliases,
                    parameters,
                    policy,
                    law,
                    projected=True,
                )

    def formula_body(
        self,
        body: dict[str, Any],
        pointer: str,
        scope: tuple[str, str, str],
        aliases: Mapping[str, AuthorityToken],
        parameters: Mapping[str, AuthorityToken],
        policy: Mapping[str, Any],
        law: str,
        *,
        projected: bool = False,
    ) -> None:
        locals_: dict[str, AuthorityToken] = {}

        def emit(token: AuthorityToken, path: str, use: str = "reference") -> None:
            self.occurrence(
                token,
                pointer if projected else pointer + path,
                use,
                law,
                location="formula" if projected else "value",
                projection=path if projected else "",
            )

        def contract(value: dict[str, Any], path: str) -> None:
            alias = aliases.get(value["type"])
            if alias is None:
                raise InventoryRefusal("unknown Formula result Type alias")
            emit(alias, path + "/type")
            # These are identity joins declared by the selected runtime projection,
            # not another Formula type inference algorithm.
            for seed, _, collection in self.seeds:
                member_path = seed["declaration_path"]
                if len(member_path) != 1 or member_path[0] not in value:
                    continue
                source = collection["source"]
                if source["kind"] != "semantic-closure":
                    continue
                role = source["authority_path"]
                projection = next(
                    row for row in self.projections if row["authority_path"] == role
                )
                if seed["target_path"] != (
                    []
                    if projection["key_member"] is None
                    else [projection["key_member"]]
                ):
                    continue
                emit(
                    self.declared(role, "", value[member_path[0]]),
                    path + "/" + member_path[0],
                )

        def operand(value: dict[str, Any], path: str) -> None:
            kind = value.get("kind")
            if kind not in policy["allowed_operand_kinds"]:
                raise InventoryRefusal("unknown Formula operand kind")
            if kind == "parameter":
                token = parameters.get(value["parameter"])
                if token is None:
                    raise InventoryRefusal("unknown Formula parameter reference")
                emit(token, path + "/parameter")
            elif kind == "local":
                token = locals_.get(value["local"])
                if token is None:
                    raise InventoryRefusal("unknown Formula local reference")
                emit(token, path + "/local")
            elif kind == "symbol":
                emit(
                    AuthorityToken("source-module", scope[:1], value["module"]),
                    path + "/module",
                )
                emit(
                    AuthorityToken(
                        "source-symbol", (scope[0], value["module"]), value["symbol"]
                    ),
                    path + "/symbol",
                )
            elif type(value["value"]) is not int:
                raise InventoryRefusal("unknown Formula literal payload")

        normalizations = policy["inline_body_normalizations"]
        inline = next(
            (row for row in normalizations if body.get("node") == row["node"]), None
        )
        if inline is not None:
            token = parameters.get(body[inline["parameter_member"]])
            if token is None:
                raise InventoryRefusal("unknown inline Formula parameter")
            emit(token, "/" + inline["parameter_member"])
            return
        for ni, node in enumerate(body[policy["body_nodes_member"]]):
            np = f"/{policy['body_nodes_member']}/{ni}"
            kind = node["node"]
            if kind not in policy["allowed_body_nodes"]:
                raise InventoryRefusal("unknown Formula body node")
            if kind == "operation-call":
                coordinate = node["operation"]
                emit(
                    AuthorityToken("namespace", (), coordinate["package"]),
                    np + "/operation/package",
                )
                emit(
                    AuthorityToken(
                        "language.operations",
                        (coordinate["package"],),
                        coordinate["id"],
                    ),
                    np + "/operation/id",
                )
                for ai, argument in enumerate(node["arguments"]):
                    ap = f"{np}/arguments/{ai}"
                    emit(
                        AuthorityToken(
                            "operation-port",
                            (coordinate["package"], coordinate["id"]),
                            argument["port"],
                        ),
                        ap + "/port",
                    )
                    operand(argument["operand"], ap + "/operand")
            elif kind == "formula-call":
                coordinate = node["formula"]
                emit(
                    AuthorityToken("source-module", scope[:1], coordinate["module"]),
                    np + "/formula/module",
                )
                emit(
                    AuthorityToken(
                        "source-formula",
                        (scope[0], coordinate["module"]),
                        coordinate["id"],
                    ),
                    np + "/formula/id",
                )
                for ai, argument in enumerate(node["arguments"]):
                    ap = f"{np}/arguments/{ai}"
                    emit(
                        AuthorityToken(
                            "source-formula-parameter",
                            (scope[0], coordinate["module"], coordinate["id"]),
                            argument["parameter"],
                        ),
                        ap + "/parameter",
                    )
                    operand(argument["operand"], ap + "/operand")
            elif kind == "conditional":
                for member in ("condition", "when_true", "when_false"):
                    operand(node[member], np + "/" + member)
            contract(node["result"], np + "/result")
            name = node[policy["node_id_member"]]
            token = AuthorityToken("source-formula-local", scope, name)
            if name in locals_ or name in parameters:
                raise InventoryRefusal("duplicate or capturing Formula local")
            emit(token, np + "/" + policy["node_id_member"], "declaration")
            locals_[name] = token
        operand(body[policy["body_result_member"]], "/" + policy["body_result_member"])

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

    def formula_policy(self) -> tuple[dict[str, Any], str, str]:
        policies = [
            (value, _child(pp + "/extensions", key), definition["id"])
            for (_, role, _), (definition, pp) in self.definitions.items()
            if role == "language.resolution_profiles"
            and definition.get("default") is True
            for key, value in definition.get("extensions", {}).items()
            if isinstance(value, dict) and "formula_id_member" in value
        ]
        if len(policies) != 1:
            raise InventoryRefusal("Formula policy does not have one admitted owner")
        return policies[0]

    def formula_aliases(self) -> None:
        policy, pointer, profile = self.formula_policy()
        for i, alias in enumerate(policy["fixed_value_type_aliases"]):
            if (
                set(alias) != {"alias", "contract"}
                or alias["contract"]
                not in self.meta["runtime_program"]["fixed_value_contracts"]
            ):
                raise InventoryRefusal(
                    "Formula fixed alias does not address a Kernel contract"
                )
            self.occurrence(
                AuthorityToken("formula-fixed-alias", (profile,), alias["alias"]),
                f"{pointer}/fixed_value_type_aliases/{i}/alias",
                "declaration",
                pointer,
            )

    def formula_bindings(self, source: dict[str, Any]) -> None:
        policy, law, _ = self.formula_policy()
        model = source["manifest"]["id"]
        for i, binding in enumerate(source.get(policy["bindings_member"], [])):
            bp = f"/source/{policy['bindings_member']}/{i}"
            site = binding[policy["binding_site_member"]]
            sp = _child(bp, policy["binding_site_member"])
            slot_scope = None
            if site["kind"] == "operation-slot":
                scope = self.callee(site["operation"], sp + "/operation", law)
                slot_scope = (*scope, site["slot"])
                self.occurrence(
                    AuthorityToken("operation-slot", scope, site["slot"]),
                    sp + "/slot",
                    "reference",
                    law,
                )
            elif site["kind"] == "derived-symbol":
                self.source_operand(
                    {
                        "kind": "symbol",
                        "module": site["module"],
                        "symbol": site["symbol"],
                    },
                    sp,
                    model,
                    law,
                )
            else:
                raise InventoryRefusal("unknown Formula binding site")
            formula = binding[policy["binding_formula_member"]]
            fp = _child(bp, policy["binding_formula_member"])
            self.occurrence(
                AuthorityToken("source-module", (model,), formula["module"]),
                fp + "/module",
                "reference",
                law,
            )
            self.occurrence(
                AuthorityToken(
                    "source-formula", (model, formula["module"]), formula["id"]
                ),
                fp + "/id",
                "reference",
                law,
            )
            for ai, argument in enumerate(binding[policy["binding_arguments_member"]]):
                ap = f"{bp}/{policy['binding_arguments_member']}/{ai}"
                self.occurrence(
                    AuthorityToken(
                        "source-formula-parameter",
                        (model, formula["module"], formula["id"]),
                        argument[policy["binding_parameter_member"]],
                    ),
                    _child(ap, policy["binding_parameter_member"]),
                    "reference",
                    law,
                )
                operand = argument[policy["binding_operand_member"]]
                op = _child(ap, policy["binding_operand_member"])
                if operand["kind"] == "slot-parameter":
                    if slot_scope is None:
                        raise InventoryRefusal(
                            "slot parameter used outside Operation slot"
                        )
                    self.occurrence(
                        AuthorityToken(
                            "operation-slot-parameter", slot_scope, operand["parameter"]
                        ),
                        op + "/parameter",
                        "reference",
                        law,
                    )
                else:
                    self.source_operand(operand, op, model, law)

    def finish(self) -> ExtensionInventory:
        self.index()
        self.operation_operand_projection()
        self.metadata_links()
        self.type_identity_edges()
        self.packages()
        self.rule_chain_links()
        self.assignment_policies()
        self.formula_aliases()
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
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Independently check exact bytes and uniqueness of a supplied occurrence set."""
    projections = _formula_projections(kernel, graph)
    positions = {
        (row.token, row.pointer, row.use, row.location, row.projection)
        for row in inventory.occurrences
    }
    if len(inventory.occurrences) != len(positions):
        raise InventoryRefusal("duplicate token occurrence")
    for occurrence in inventory.occurrences:
        try:
            value = _occurrence_value(graph, occurrence, projections)
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
    shared_positions: dict[tuple[str, str, str], set[str]] = {}
    for occurrence in inventory.occurrences:
        target = correspondence.get(occurrence.token, occurrence.token)
        position = (occurrence.pointer, occurrence.location, occurrence.projection)
        shared_positions.setdefault(position, set()).add(target.name)
    if any(len(names) != 1 for names in shared_positions.values()):
        raise InventoryRefusal(
            "bijection splits one shared authored reference occurrence"
        )
    inventory.require_complete()


def _verify_constructor_address_coverage(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Reverse-check constructor declarations and addressed keys; no type inference."""
    expected = set()
    constructors = {}

    def required(
        token: AuthorityToken,
        pointer: str,
        use: str = "reference",
        location: str = "value",
    ) -> None:
        expected.add((token, pointer, use, location))

    for _, constructor, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.constructors"
    ):
        rule = constructor.get("value_rule", {})
        if "definition_kind" not in rule:
            continue
        constructors[rule["definition_kind"]] = constructor
        for selector, member, area in _constructor_member_selectors(constructor):
            required(
                AuthorityToken("constructor-member", (constructor["id"], area), member),
                pointer + "/value_rule/" + selector,
                "declaration",
            )
        for i, member in enumerate(constructor["parameters"]):
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "definition"), member
                ),
                f"{pointer}/parameters/{i}",
            )
        for i, member in enumerate(rule.get("value_members", [])):
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "ref-value"), member
                ),
                f"{pointer}/value_rule/value_members/{i}",
                "declaration",
            )

    def definition(
        value: dict[str, Any], pointer: str, owner: tuple[str, str] | None
    ) -> None:
        if "package" in value:
            required(
                AuthorityToken("namespace", (), value["package"]), pointer + "/package"
            )
            required(
                AuthorityToken("type", (value["package"],), value["id"]),
                pointer + "/id",
            )
            return
        constructor = constructors[value["kind"]]
        rule = constructor["value_rule"]
        for member in constructor["parameters"]:
            required(
                AuthorityToken(
                    "constructor-member", (constructor["id"], "definition"), member
                ),
                _child(pointer, member),
                location="key",
            )
        if rule["operator"] == "enum-member" and owner is not None:
            for i, member in enumerate(value[rule["members_member"]]):
                required(
                    AuthorityToken("enum-member", owner, member),
                    f"{pointer}/{rule['members_member']}/{i}",
                    "declaration",
                )
        elif rule["operator"] == "bounded-list":
            definition(
                value[rule["element_member"]],
                _child(pointer, rule["element_member"]),
                None,
            )
        elif rule["operator"] == "canonical-ref-key":
            definition(
                value[rule["target_member"]],
                _child(pointer, rule["target_member"]),
                None,
            )
        elif rule["operator"] == "closed-record":
            for i, field in enumerate(value[rule["fields_member"]]):
                fp = f"{pointer}/{rule['fields_member']}/{i}"
                for selector in ("field_name_member", "field_type_member"):
                    required(
                        AuthorityToken(
                            "constructor-member",
                            (constructor["id"], "record-field"),
                            rule[selector],
                        ),
                        _child(fp, rule[selector]),
                        location="key",
                    )
                if owner is not None:
                    required(
                        AuthorityToken(
                            "record-field", owner, field[rule["field_name_member"]]
                        ),
                        _child(fp, rule["field_name_member"]),
                        "declaration",
                    )
                definition(
                    field[rule["field_type_member"]],
                    _child(fp, rule["field_type_member"]),
                    None,
                )

    for namespace, nominal, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.nominal_types"
    ):
        if not isinstance(namespace, str):
            raise InventoryRefusal("nominal definition has no attached owner")
        definition(
            nominal["definition"], pointer + "/definition", (namespace, nominal["id"])
        )
    actual = {(o.token, o.pointer, o.use, o.location) for o in inventory.occurrences}
    if not expected <= actual:
        raise InventoryRefusal(
            "constructor address or nominal member coverage is incomplete"
        )
    positions = {row[1:] for row in expected}
    if any(row[1:] in positions and row not in expected for row in actual):
        raise InventoryRefusal(
            "constructor address or nominal member has the wrong owner"
        )


def _verify_formula_coverage(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    found = {
        (o.token, o.pointer, o.use, o.location, o.projection)
        for o in inventory.occurrences
    }
    expected: set[tuple[AuthorityToken, str, str, str, str]] = set()

    def field(token: AuthorityToken, pointer: str, use: str = "reference") -> None:
        expected.add((token, pointer, use, "value", ""))

    for owner, operation, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.operations"
    ):
        if not isinstance(owner, str):
            raise InventoryRefusal(
                "Formula Operation declaration has no attached owner"
            )
        scope = (owner, operation["id"])
        extensions = operation.get("extensions", {})
        notation = extensions.get("standard.formula-notation")
        if notation is not None:
            np = pointer + "/extensions/standard.formula-notation"
            member = "name" if notation["kind"] == "function" else "token"
            field(
                AuthorityToken("operation-notation", scope, notation[member]),
                np + "/" + member,
                "declaration",
            )
            for i, port in enumerate(notation["ordered_ports"]):
                field(
                    AuthorityToken("operation-port", scope, port),
                    f"{np}/ordered_ports/{i}",
                )
        for i, slot in enumerate(extensions.get("standard.formula-slots", [])):
            sp = f"{pointer}/extensions/standard.formula-slots/{i}"
            field(
                AuthorityToken("operation-slot", scope, slot["id"]),
                sp + "/id",
                "declaration",
            )
            field(
                AuthorityToken("operation-local", scope, slot["target"]), sp + "/target"
            )
            for pi, parameter in enumerate(slot["parameters"]):
                pp = f"{sp}/parameters/{pi}"
                field(
                    AuthorityToken(
                        "operation-slot-parameter",
                        (*scope, slot["id"]),
                        parameter["id"],
                    ),
                    pp + "/id",
                    "declaration",
                )
                source = parameter["source"]
                field(
                    AuthorityToken(
                        "operation-" + source["kind"], scope, source["name"]
                    ),
                    pp + "/source/name",
                )
    for _, profile, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.resolution_profiles"
    ):
        for key, policy in profile.get("extensions", {}).items():
            if isinstance(policy, dict) and "formula_id_member" in policy:
                for i, alias in enumerate(policy["fixed_value_type_aliases"]):
                    field(
                        AuthorityToken(
                            "formula-fixed-alias", (profile["id"],), alias["alias"]
                        ),
                        f"{_child(pointer + '/extensions', key)}/fixed_value_type_aliases/{i}/alias",
                        "declaration",
                    )
    source = graph.get("source")
    if not source:
        if not expected <= found:
            raise InventoryRefusal(
                "Formula declaration or reference coverage is incomplete or misowned"
            )
        return
    projections = _formula_projections(kernel, graph)
    model = source["manifest"]["id"]
    for i, binding in enumerate(source.get("formula_bindings", [])):
        bp = f"/source/formula_bindings/{i}"
        formula = binding["formula"]
        fs = (model, formula["module"], formula["id"])
        field(
            AuthorityToken("source-module", (model,), formula["module"]),
            bp + "/formula/module",
        )
        field(
            AuthorityToken("source-formula", fs[:2], formula["id"]), bp + "/formula/id"
        )
        site = binding["site"]
        if site["kind"] == "operation-slot":
            ref = site["operation"]
            scope = (ref["package"], ref["id"])
            field(
                AuthorityToken("namespace", (), ref["package"]),
                bp + "/site/operation/package",
            )
            field(
                AuthorityToken("language.operations", scope[:1], ref["id"]),
                bp + "/site/operation/id",
            )
            field(
                AuthorityToken("operation-slot", scope, site["slot"]), bp + "/site/slot"
            )
        elif site["kind"] == "derived-symbol":
            field(
                AuthorityToken("source-module", (model,), site["module"]),
                bp + "/site/module",
            )
            field(
                AuthorityToken(
                    "source-symbol", (model, site["module"]), site["symbol"]
                ),
                bp + "/site/symbol",
            )
        for ai, argument in enumerate(binding["arguments"]):
            ap = f"{bp}/arguments/{ai}"
            field(
                AuthorityToken("source-formula-parameter", fs, argument["parameter"]),
                ap + "/parameter",
            )
            operand = argument["operand"]
            if operand["kind"] == "slot-parameter":
                field(
                    AuthorityToken(
                        "operation-slot-parameter",
                        (
                            site["operation"]["package"],
                            site["operation"]["id"],
                            site["slot"],
                        ),
                        operand["parameter"],
                    ),
                    ap + "/operand/parameter",
                )
            elif operand["kind"] == "symbol":
                field(
                    AuthorityToken("source-module", (model,), operand["module"]),
                    ap + "/operand/module",
                )
                field(
                    AuthorityToken(
                        "source-symbol", (model, operand["module"]), operand["symbol"]
                    ),
                    ap + "/operand/symbol",
                )
    for mi, module in enumerate(source["modules"]):
        ms = (model, module["id"])
        for fi, formula in enumerate(module.get("formulas", [])):
            fp = f"/source/modules/{mi}/formulas/{fi}"
            fs = (*ms, formula["id"])
            expected.add(
                (
                    AuthorityToken("source-formula", ms, formula["id"]),
                    fp + "/id",
                    "declaration",
                    "value",
                    "",
                )
            )
            for pi, parameter in enumerate(formula["parameters"]):
                expected.add(
                    (
                        AuthorityToken("source-formula-parameter", fs, parameter["id"]),
                        f"{fp}/parameters/{pi}/id",
                        "declaration",
                        "value",
                        "",
                    )
                )
            bodies = [(formula["body"], fp + "/body", "value")]
            if fp + "/expression" in projections:
                bodies.append(
                    (projections[fp + "/expression"], fp + "/expression", "formula")
                )
            for body, base, location in bodies:

                def needed(
                    token: AuthorityToken, path: str, use: str = "reference"
                ) -> None:
                    expected.add(
                        (
                            token,
                            base + path if location == "value" else base,
                            use,
                            location,
                            path if location == "formula" else "",
                        )
                    )

                if body.get("node") == "parameter":
                    needed(
                        AuthorityToken(
                            "source-formula-parameter", fs, body["parameter"]
                        ),
                        "/parameter",
                    )
                    continue
                references = [(body["result"], "/result")]
                for ni, node in enumerate(body["nodes"]):
                    np = f"/nodes/{ni}"
                    needed(
                        AuthorityToken("source-formula-local", fs, node["id"]),
                        np + "/id",
                        "declaration",
                    )
                    if node["node"] == "operation-call":
                        ref = node["operation"]
                        needed(
                            AuthorityToken("namespace", (), ref["package"]),
                            np + "/operation/package",
                        )
                        needed(
                            AuthorityToken(
                                "language.operations", (ref["package"],), ref["id"]
                            ),
                            np + "/operation/id",
                        )
                        for ai, argument in enumerate(node["arguments"]):
                            ap = f"{np}/arguments/{ai}"
                            needed(
                                AuthorityToken(
                                    "operation-port",
                                    (ref["package"], ref["id"]),
                                    argument["port"],
                                ),
                                ap + "/port",
                            )
                            references.append((argument["operand"], ap + "/operand"))
                    elif node["node"] == "formula-call":
                        ref = node["formula"]
                        needed(
                            AuthorityToken("source-module", (model,), ref["module"]),
                            np + "/formula/module",
                        )
                        needed(
                            AuthorityToken(
                                "source-formula", (model, ref["module"]), ref["id"]
                            ),
                            np + "/formula/id",
                        )
                        for ai, argument in enumerate(node["arguments"]):
                            ap = f"{np}/arguments/{ai}"
                            needed(
                                AuthorityToken(
                                    "source-formula-parameter",
                                    (model, ref["module"], ref["id"]),
                                    argument["parameter"],
                                ),
                                ap + "/parameter",
                            )
                            references.append((argument["operand"], ap + "/operand"))
                    elif node["node"] == "conditional":
                        references.extend(
                            (node[member], np + "/" + member)
                            for member in ("condition", "when_true", "when_false")
                        )
                    else:
                        raise InventoryRefusal("unclassified Formula AST node")
                for operand, path in references:
                    if operand["kind"] == "parameter":
                        needed(
                            AuthorityToken(
                                "source-formula-parameter", fs, operand["parameter"]
                            ),
                            path + "/parameter",
                        )
                    elif operand["kind"] == "local":
                        needed(
                            AuthorityToken(
                                "source-formula-local", fs, operand["local"]
                            ),
                            path + "/local",
                        )
                    elif operand["kind"] == "symbol":
                        needed(
                            AuthorityToken(
                                "source-module", (model,), operand["module"]
                            ),
                            path + "/module",
                        )
                        needed(
                            AuthorityToken(
                                "source-symbol",
                                (model, operand["module"]),
                                operand["symbol"],
                            ),
                            path + "/symbol",
                        )
                    elif operand["kind"] != "literal":
                        raise InventoryRefusal("unclassified Formula AST operand")
    if not expected <= found:
        raise InventoryRefusal(
            "Formula declaration or reference coverage is incomplete or misowned"
        )
    owned_paths = {(row[1], row[2], row[3], row[4]) for row in expected}
    if any(row[1:] in owned_paths and row not in expected for row in found):
        raise InventoryRefusal("extra incorrectly owned Formula occurrence")


def validate_extension_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: ExtensionInventory
) -> None:
    """Reverse-check authored owners and declaration coverage independently.

    This verifier does not call the reader. Nested reference coverage remains an
    explicit unfinished obligation until the corresponding consuming-law pass
    is implemented; require_complete still refuses that inventory.
    """
    validate_inventory_occurrences(kernel, graph, inventory)
    _verify_constructor_address_coverage(kernel, graph, inventory)
    source_format_role = _source_format_role(kernel, graph)
    _verify_formula_coverage(kernel, graph, inventory)
    rule_required = set()
    for _, rule, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.rules"
    ):
        rule_required.add(
            (
                AuthorityToken("rule-judgment", (), rule["judgment"]),
                pointer + "/judgment",
                "declaration",
                "value",
            )
        )
        for pi, premise in enumerate(rule["premises"]):
            for variable in premise["bind"]:
                rule_required.add(
                    (
                        AuthorityToken("rule-variable", (rule["id"],), variable),
                        _child(f"{pointer}/premises/{pi}/bind", variable),
                        "declaration",
                        "key",
                    )
                )
        for field, term in rule["conclusion"]["fields"].items():
            if term["tag"] == "variable":
                rule_required.add(
                    (
                        AuthorityToken("rule-variable", (rule["id"],), term["name"]),
                        _child(pointer + "/conclusion/fields", field) + "/name",
                        "reference",
                        "value",
                    )
                )
    for _, lowering, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.model_lowerings"
    ):
        for member in ("rule_chain", "structured_rule_chain"):
            for i, step in enumerate(lowering[member]):
                rule_required.add(
                    (
                        AuthorityToken("rule-judgment", (), step["judgment"]),
                        f"{pointer}/{member}/{i}/judgment",
                        "reference",
                        "value",
                    )
                )
    rule_actual = {
        (o.token, o.pointer, o.use, o.location) for o in inventory.occurrences
    }
    if not rule_required <= rule_actual:
        raise InventoryRefusal(
            "Language rule binding or selection coverage is incomplete"
        )
    rule_positions = {
        (pointer, use, location) for _, pointer, use, location in rule_required
    }
    if any(
        row[1:] in rule_positions and row not in rule_required for row in rule_actual
    ):
        raise InventoryRefusal(
            "Language rule occurrence has an incorrect role or owner"
        )
    meta = kernel["meta_format"]
    if "ldb_root" in graph:
        root, shape = graph["ldb_root"], meta["language_bundle"]
        if (
            not _consumer_b_definition_is_closed(
                root,
                {
                    "required_members": shape["required_members"],
                    "field_types": shape["member_types"],
                },
                {},
            )
            or not _consumer_b_definition_is_closed(
                root["resources"], shape["resources"], {}
            )
            or root["kernel_identity"] != kernel["content_identity"]
            or not all(
                _consumer_b_definition_is_closed(row, shape["package_descriptor"], {})
                for row in root["package_descriptors"]
            )
        ):
            raise InventoryRefusal(
                "LDB root or descriptor has an unclassified member or binding"
            )
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
    lowering_rows = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_lowerings")
    )
    for _, lowering, pointer in lowering_rows:
        policy = lowering["assignment_policy"]
        pp = pointer + "/assignment_policy"
        required.add(
            (
                AuthorityToken("assignment-policy", (lowering["id"],), policy["id"]),
                pp + "/id",
                "declaration",
            )
        )
        for ri, row in enumerate(policy["roles"]):
            rp = f"{pp}/roles/{ri}"
            required.add(
                (
                    AuthorityToken("language.quantity.symbol_roles", (), row["role"]),
                    rp + "/role",
                    "reference",
                )
            )
            for mi, mode in enumerate(row["modes"]):
                required.add(
                    (
                        AuthorityToken(
                            "assignment-mode",
                            (lowering["id"], policy["id"], row["role"]),
                            mode["id"],
                        ),
                        f"{rp}/modes/{mi}/id",
                        "declaration",
                    )
                )
    if graph.get("source"):
        default_profiles = [
            profile
            for _, profile, _ in _authority_path_rows(
                kernel, graph, "language_bundle.language.resolution_profiles"
            )
            if profile.get("default") is True
        ]
        if len(default_profiles) != 1:
            raise InventoryRefusal("Source has no unique default profile")
        selected = [
            row
            for _, row, _ in lowering_rows
            if row["id"] == default_profiles[0]["model_lowering"]
        ]
        if len(selected) != 1:
            raise InventoryRefusal("Source has no unique assignment policy")
        lowering = selected[0]
        for mi, module in enumerate(graph["source"]["modules"]):
            for si, symbol in enumerate(module["symbols"]):
                required.add(
                    (
                        AuthorityToken(
                            "assignment-mode",
                            (
                                lowering["id"],
                                lowering["assignment_policy"]["id"],
                                symbol["role"],
                            ),
                            symbol["value_policy"]["mode"],
                        ),
                        f"/source/modules/{mi}/symbols/{si}/value_policy/mode",
                        "reference",
                    )
                )
    for _, unit, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.quantity.units"
    ):
        required.add(
            (
                AuthorityToken("unit-dimension", (), unit["dimension"]),
                pointer + "/dimension",
                "declaration",
            )
        )
    for _, definition, pointer in _authority_path_rows(
        kernel, graph, "language_bundle.language.structured_operations"
    ):
        required.add(
            (
                AuthorityToken(
                    "language.constructors", (), definition["owner_constructor"]
                ),
                pointer + "/owner_constructor",
                "reference",
            )
        )
        if "refusal_signal" in definition["law"]:
            required.add(
                (
                    AuthorityToken(
                        "diagnostic-signal",
                        ("runtime",),
                        definition["law"]["refusal_signal"],
                    ),
                    pointer + "/law/refusal_signal",
                    "reference",
                )
            )
    for owner, name, pointer, target, _ in _declared_metadata_links(kernel, graph):
        role, scoped = _declared_target_role(kernel, target)
        if role == source_format_role:
            continue
        token = AuthorityToken(
            role, (owner,) if scoped and owner is not None else (), name
        )
        required.add((token, pointer, "reference"))
        if target.startswith("kernel.") and token not in inventory.reserved:
            raise InventoryRefusal("declared Kernel primitive was made renameable")
    exported_types = [
        (package["id"], exported["id"])
        for package in graph["packages"]
        for exported in package["exports"]["types"]
    ]
    for _, lowering, lp in _authority_path_rows(
        kernel, graph, "language_bundle.language.model_lowerings"
    ):
        projection = lowering["runtime_projection"]
        collections = {row["id"]: row["source"] for row in projection["collections"]}
        for edge in projection["edges"]:
            origin, destination = (
                collections[edge["source_collection"]],
                collections[edge["target_collection"]],
            )
            if (
                origin["kind"] != "namespace-member"
                or origin["member"] != "types"
                or edge["source_path"] != ["id"]
            ):
                continue
            if destination["kind"] != "semantic-closure":
                raise InventoryRefusal("unclassified Type identity edge destination")
            for package, definition, dp in _authority_path_rows(
                kernel, graph, "language_bundle." + destination["authority_path"]
            ):
                for name, pointer in _walk_member_path(
                    definition, dp, edge["target_path"]
                ):
                    for namespace, type_id in exported_types:
                        if name == type_id and (
                            not edge["same_package"] or namespace == package
                        ):
                            required.add(
                                (
                                    AuthorityToken("type", (namespace,), type_id),
                                    pointer,
                                    "reference",
                                )
                            )
    for pi, package in enumerate(graph["packages"]):
        owner, pp = package["id"], f"/packages/{pi}"
        required.add(
            (AuthorityToken("namespace", (), owner), pp + "/id", "declaration")
        )
        for projection in projections:
            if projection["authority_path"] == source_format_role:
                continue
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
                                "schedule-operation",
                                "cancel-event",
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
                            if node["result"]["kind"] in {
                                "composition",
                                "scheduled-event",
                            }:
                                result = instruction["result"]
                                if result["kind"] == "local":
                                    required.add(
                                        (
                                            AuthorityToken(
                                                "operation-local",
                                                op_scope,
                                                result["name"],
                                            ),
                                            ip + "/result/name",
                                            "declaration",
                                        )
                                    )
                            if node["semantics"]["operator"] == "named-integer-draw":
                                required.add(
                                    (
                                        AuthorityToken(
                                            "named-stream", (), instruction["stream"]
                                        ),
                                        ip + "/stream",
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
    if token.role == "rule-variable":
        return (name(AuthorityToken("language.rules", (), token.owner[0])),)
    if token.role == "constructor-member":
        return (
            name(AuthorityToken("language.constructors", (), token.owner[0])),
            token.owner[1],
        )
    if token.role == "formula-fixed-alias":
        return (
            name(AuthorityToken("language.resolution_profiles", (), token.owner[0])),
        )
    if token.role == "assignment-policy":
        return (name(AuthorityToken("language.model_lowerings", (), token.owner[0])),)
    if token.role == "assignment-mode":
        return (
            name(AuthorityToken("language.model_lowerings", (), token.owner[0])),
            name(AuthorityToken("assignment-policy", token.owner[:1], token.owner[1])),
            name(AuthorityToken("language.quantity.symbol_roles", (), token.owner[2])),
        )
    if token.role == "diagnostic-signal":
        return token.owner  # Stage is the Kernel refusal-stage enum, not a namespace.
    if token.role.startswith("source-"):
        model = name(AuthorityToken("source-model", (), token.owner[0]))
        if len(token.owner) == 1:
            return (model,)
        module = name(AuthorityToken("source-module", token.owner[:1], token.owner[1]))
        if len(token.owner) == 2:
            return (model, module)
        if len(token.owner) == 3 and token.role.startswith("source-formula-"):
            formula = name(
                AuthorityToken("source-formula", token.owner[:2], token.owner[2])
            )
            return (model, module, formula)
        raise InventoryRefusal("unknown Source token owner")
    namespace = name(AuthorityToken("namespace", (), token.owner[0]))
    if len(token.owner) == 1:
        return (namespace,)
    if token.role in {"enum-member", "record-field"}:
        return (
            namespace,
            name(AuthorityToken("type", token.owner[:1], token.owner[1])),
        )
    if token.role.startswith("operation-"):
        owner = (
            namespace,
            name(
                AuthorityToken("language.operations", token.owner[:1], token.owner[1])
            ),
        )
        if token.role == "operation-slot-parameter":
            return (
                *owner,
                name(AuthorityToken("operation-slot", token.owner[:2], token.owner[2])),
            )
        return owner
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
