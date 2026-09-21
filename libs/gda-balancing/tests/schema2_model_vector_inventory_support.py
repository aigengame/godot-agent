"""Bound Model-vector observations through the existing independent consumers."""

from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import jsonschema
from gda_balancing.domain.authority.source_projection import SourceProjection

from schema2_bootstrap_conformance_support import (
    _consumer_b_model_program_vector_is_closed,
)
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    TokenOccurrence,
    _Reader,
    _attached_language,
    _child,
    _formula_projections,
    _json_pointer_segments,
    _invalid_source_paths,
    _inventory_dependency_key,
    _package_semantic_dependencies,
    _protocol_schema,
    _repair_invalid_source,
    _source_address_links,
    _source_projection,
    _template_inventory,
    _validate_ldb_root_contract,
)
from test_schema2_model_lowerer_conformance import (
    ModelSourceContext,
    _lock_oracle,
    _reference_check_source,
    _reference_materialize_vector_source,
    _reference_namespace_selection,
    _reference_package_lock,
)

_LAW = "/meta_format/model_program_vector"
_MODEL_VECTOR_INVENTORY_CACHE: OrderedDict[
    bytes,
    tuple[
        frozenset[TokenOccurrence],
        frozenset[str],
        dict[str, Any],
        frozenset[AuthorityToken],
    ],
] = OrderedDict()
_MODEL_VECTOR_INVENTORY_CACHE_LIMIT = 16


def _model_vector_dependencies(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Return exactly the authored surfaces consumed by Model vector inventory."""
    vector_membership = []
    model_vectors = []
    for set_index, vector_set in enumerate(graph.get("vector_sets", [])):
        definitions = vector_set["vector_definitions"]
        vector_membership.append(
            {
                "package_id": vector_set["package_id"],
                "ids": [vector["id"] for vector in definitions],
                "vectors": vector_set["vectors"],
            }
        )
        model_vectors.extend(
            {
                "set_index": set_index,
                "vector_index": vector_index,
                "definition": vector,
            }
            for vector_index, vector in enumerate(definitions)
            if "source_fixture" in vector
        )
    root = {
        key: value
        for key, value in graph.get("ldb_root", {}).items()
        if key != "content_identity"
    }
    return {
        "root": root,
        "vector_membership": vector_membership,
        "model_vectors": model_vectors,
    }


def _base_reader(kernel, graph):
    reader = _Reader(kernel, graph)
    reader.index()
    reader.operation_operand_projection()
    _, fixed, reader.template_roots, reader.template_schemas = _template_inventory(
        kernel, graph, reader.source_native
    )
    reader.reserved.update(fixed)
    reader.packages()
    reader.assignment_policies()
    reader.formula_aliases()
    return reader


class _SourceRoles(_Reader):
    """Reuse the Source visitor after the Model vector's actual first-fault check."""

    def __init__(self, base, source, refused, projections):
        self.__dict__ = base.__dict__.copy()
        self.graph = {**base.graph, "source": source}
        self.tokens = set(base.tokens)
        self.reserved = set(base.reserved)
        self.occurrences = set()
        self.occurrence_positions = set()
        self.uncovered = set()
        self.refused = refused
        schema = _protocol_schema(self.kernel, self.graph, "model-source-package")[
            "schema"
        ]
        validation_errors = list(
            jsonschema.Draft202012Validator(schema).iter_errors(source)
        )
        invalid_authored_paths = _invalid_source_paths(
            validation_errors, root="/source"
        )
        if invalid_authored_paths and not refused:
            raise InventoryRefusal("admitted Model vector has invalid Source grammar")
        projection_graph = (
            {
                **self.graph,
                "source": _repair_invalid_source(source, schema, validation_errors),
            }
            if validation_errors
            else self.graph
        )
        self.source_projection = _source_projection(self.kernel, projection_graph)
        if self.source_projection is None:
            raise InventoryRefusal("negative Model Source projection is unavailable")
        authored_to_stable = {
            "/source" + authored: "/source" + stable
            for stable, authored in self.source_projection.authored_paths.items()
        }

        def stable_pointer(authored: str) -> str:
            for prefix in sorted(authored_to_stable, key=len, reverse=True):
                if authored == prefix or authored.startswith(prefix + "/"):
                    return authored_to_stable[prefix] + authored.removeprefix(prefix)
            return authored

        self.invalid_authored_paths = invalid_authored_paths
        self.invalid_paths = {
            stable_pointer(pointer) for pointer in invalid_authored_paths
        }
        self.formula_projections = projections

    def source_alias(self, name, aliases, scope, pointer):
        if name not in aliases and self.refused:
            return AuthorityToken("source-type-alias", scope, name)
        return super().source_alias(name, aliases, scope, pointer)

    def reference(self, role, name, pointer, law, namespace=""):
        token = self.declared(role, namespace, name)
        if token not in self.tokens | self.reserved and self.refused:
            self.occurrence(token, pointer, "unresolved-reference", law)
        else:
            super().reference(role, name, pointer, law, namespace)

    def namespace(self, name, pointer, use, law):
        token = AuthorityToken("namespace", (), name)
        if (
            use == "reference"
            and token not in self.tokens | self.reserved
            and self.refused
        ):
            self.occurrence(token, pointer, "unresolved-reference", law)
        else:
            super().namespace(name, pointer, use, law)

    def formula_body(self, body, pointer, *args, **kwargs):
        if pointer in self.invalid_paths:
            return  # This malformed grammar has no interpreted body or AST.
        super().formula_body(body, pointer, *args, **kwargs)

    def record_occurrence(self, occurrence):
        if occurrence.location != "key" and any(
            occurrence.pointer == invalid
            or occurrence.pointer.startswith(invalid + "/")
            for invalid in self.invalid_authored_paths
        ):
            return
        super().record_occurrence(occurrence)


def _model_vector_inventory_uncached(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
):
    # Model vectors are authored in ``vector_sets``. The caller's primary
    # Source is a separate inventory surface and cannot change their fixtures,
    # first-fault observations, or projections.
    vector_graph = {key: value for key, value in graph.items() if key != "source"}
    base = _base_reader(kernel, vector_graph)
    parsed = _formula_projections(kernel, vector_graph)
    ldb = {**graph["ldb_root"], **_attached_language(kernel, graph)}
    ldb["diagnostics"] = [
        row
        for package in graph["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
        for row in entry["definitions"]
    ]
    ldb["vectors"] = [
        row for vs in graph["vector_sets"] for row in vs["vector_definitions"]
    ]
    stages = {row["code"]: row["stage"] for row in ldb["diagnostics"]}
    rows = set()
    roots = set()
    projections = {}
    reserved = set()

    def emit(token, pointer, use="reference", location="value", projection=""):
        rows.add(TokenOccurrence(token, pointer, use, _LAW, location, projection))

    def reference(role, name, pointer, owner=""):
        token = base.declared(role, owner, name)
        if token not in base.tokens | base.reserved:
            raise InventoryRefusal(f"Model oracle has no selected owner at {pointer}")
        emit(token, pointer)

    for vi, vector_set in enumerate(graph.get("vector_sets", [])):
        for di, vector in enumerate(vector_set["vector_definitions"]):
            if "source_fixture" not in vector:
                continue
            vp = f"/vector_sets/{vi}/vector_definitions/{di}"
            if not _consumer_b_model_program_vector_is_closed(
                vector, dict(kernel["meta_format"]), ldb
            ):
                raise InventoryRefusal(
                    "Model vector does not close its Kernel contract"
                )
            roots.add(vp)
            fixture, expected = vector["source_fixture"], vector["expect"]
            source = _reference_materialize_vector_source(vector, ldb)
            refused = expected["outcome"] == "refused"
            if refused:
                checked = _reference_check_source(source, dict(kernel), ldb)
                if not isinstance(checked, tuple):
                    raise InventoryRefusal(
                        "negative Model vector does not reproduce its first fault"
                    )
                diagnostics = [
                    {"code": code, "stage": stages[code], "pointer": path}
                    for code, path in checked
                ]
                if diagnostics != expected["diagnostics"]:
                    raise InventoryRefusal(
                        "Model vector first-fault observation differs: "
                        + vector["id"]
                        + f"; observed={diagnostics!r}; expected={expected['diagnostics']!r}"
                    )
            visitor = _SourceRoles(
                base,
                source,
                refused,
                {
                    "/source"
                    + pointer.removeprefix(vp + "/source_fixture/source"): body
                    for pointer, body in parsed.items()
                    if pointer.startswith(vp + "/source_fixture/source/")
                },
            )
            if visitor.source_projection is not None:
                visitor.source_structure(visitor.source_projection.value)
            if visitor.uncovered:
                raise InventoryRefusal(
                    "Model Source has an unclassified interpreted role"
                )
            for token, pointer, use, location, projection, law in _source_address_links(
                kernel, visitor.graph
            ):
                if pointer.startswith("/source/"):
                    visitor.record_occurrence(
                        TokenOccurrence(token, pointer, use, law, location, projection)
                    )
            declared = (
                base.tokens
                | base.reserved
                | {row.token for row in visitor.occurrences if row.use == "declaration"}
            )
            collection = fixture.get("collection_path")
            collection_pointer = (
                "/source" + "".join(_child("", part) for part in collection)
                if collection
                else None
            )

            def physical(pointer, location="value"):
                if collection_pointer and pointer.startswith(collection_pointer + "/"):
                    tail = pointer[len(collection_pointer) + 1 :].split("/", 1)
                    if len(tail) == 2:
                        member = _json_pointer_segments("/" + tail[1])[0]
                        if (
                            member == fixture["index_member"]
                            and "/" not in tail[1]
                            and location == "value"
                        ):
                            return None  # The generator overwrites this template value.
                        return vp + "/source_fixture/template/" + tail[1]
                    return None
                return vp + "/source_fixture/source" + pointer.removeprefix("/source")

            for row in visitor.occurrences:
                pointer = physical(row.pointer, row.location)
                if pointer is None:
                    continue
                token, use = row.token, row.use
                if (
                    use == "reference"
                    and token not in declared
                    and token.role != "source-field"
                ):
                    if not refused:
                        raise InventoryRefusal(
                            "Model Source reference has no declaration"
                        )
                    use = "unresolved-reference"
                if token.role.startswith("source-") and token.role != "source-field":
                    token = AuthorityToken(
                        "model-vector-" + token.role,
                        (vector["id"], *token.owner),
                        token.name,
                    )
                emit(token, pointer, use, row.location, row.projection)
                if row.token in visitor.reserved:
                    reserved.add(token)
            if collection_pointer:
                # The generator selects actual Source fields; generated indices
                # and the overwritten template name are recipe data.
                keys = {
                    row.pointer: row.token
                    for row in visitor.occurrences
                    if row.location == "key"
                }
                for i, segment in enumerate(collection):
                    if segment.isdecimal():
                        continue
                    pointer = "/source" + "".join(
                        _child("", part) for part in collection[: i + 1]
                    )
                    token = keys.get(pointer)
                    if token is None:
                        raise InventoryRefusal(
                            "Model materialization path has no actual Source field"
                        )
                    emit(token, f"{vp}/source_fixture/collection_path/{i}")
                    if token in visitor.reserved:
                        reserved.add(token)
                index_token = keys[
                    _child(collection_pointer + "/0", fixture["index_member"])
                ]
                emit(index_token, vp + "/source_fixture/index_member")
                if index_token in visitor.reserved:
                    reserved.add(index_token)
            for pointer, body in visitor.formula_projections.items():
                destination = physical(pointer)
                if destination is not None:
                    projections[destination] = body
            ep = vp + "/expect"
            for i, diagnostic in enumerate(expected["diagnostics"]):
                reference(
                    "diagnostics", diagnostic["code"], f"{ep}/diagnostics/{i}/code"
                )
                segments = _json_pointer_segments(diagnostic["pointer"])
                path = "/source"
                keys = {
                    row.pointer: row.token
                    for row in visitor.occurrences
                    if row.location == "key"
                }
                for index, segment in enumerate(segments):
                    path = _child(path, segment)
                    if path in keys:
                        emit(
                            keys[path],
                            f"{ep}/diagnostics/{i}/pointer",
                            location="json-pointer",
                            projection=str(index),
                        )
            relation = expected["relation"]
            if relation["reference"] is not None:
                reference("vectors", relation["reference"], ep + "/relation/reference")
            if refused:
                continue
            projection = visitor.source_projection
            if projection is None:
                raise InventoryRefusal("admitted Model vector has no Source projection")
            context = ModelSourceContext(
                source=source,
                source_identity="unserialized-inventory-view",
                kernel=dict(kernel),
                language_bundle=ldb,
                namespace_selection=_reference_namespace_selection(
                    projection.value, kernel, ldb
                ),
                source_projection=SourceProjection(
                    value=projection.value,
                    authored_paths=projection.authored_paths,
                    authored_source=source,
                ),
            )
            lock = _reference_package_lock(context)
            if _lock_oracle(lock) != expected["lock_oracle"]:
                raise InventoryRefusal(
                    "Model Lock oracle disagrees with its selected package owners: "
                    + vector["id"]
                )
            lp = ep + "/lock_oracle"
            reference(
                "language.resolution_profiles",
                lock["resolution_profile"]["id"],
                lp + "/resolution_profile",
            )
            for i, name in enumerate(lock["root_requirements"]):
                reference("namespace", name, f"{lp}/root_requirements/{i}")
            for i, row in enumerate(lock["packages"]):
                reference("namespace", row["id"], f"{lp}/packages/{i}/id")
            for i, row in enumerate(lock["dependency_edges"]):
                for member in ("from_package", "to_package"):
                    reference(
                        "namespace", row[member], f"{lp}/dependency_edges/{i}/{member}"
                    )
            for i, row in enumerate(lock["capability_bindings"]):
                reference(
                    "namespace",
                    row["provider_package"],
                    f"{lp}/capability_bindings/{i}/provider_package",
                )
                reference(
                    "language.capabilities",
                    row["capability"],
                    f"{lp}/capability_bindings/{i}/capability",
                )
            for i, row in enumerate(lock["types"]):
                reference("namespace", row["package"], f"{lp}/types/{i}/package")
                emit(
                    AuthorityToken("type", (row["package"],), row["id"]),
                    f"{lp}/types/{i}/id",
                )
                reference(
                    "language.constructors",
                    row["constructor"],
                    f"{lp}/types/{i}/constructor",
                )
            for collection in ("components", "conversions", "operations"):
                for i, row in enumerate(lock[collection]):
                    reference(
                        "language." + collection,
                        row["definition"]["id"],
                        f"{lp}/{collection}/{i}",
                        row["package"],
                    )
            for collection, role in (
                ("numeric_profiles", "language.quantity.numeric_policies"),
                ("runtime_profiles", "language.runtime_profiles"),
                ("diagnostic_reasons", "language.reasons"),
            ):
                for i, row in enumerate(lock[collection]):
                    reference(role, row["id"], f"{lp}/{collection}/{i}")
            for collection, role in (
                ("diagnostics", "diagnostics"),
                ("language_rules", "language.rules"),
            ):
                for i, name in enumerate(lock[collection]):
                    reference(role, name, f"{lp}/{collection}/{i}")
    reserved.update(row.token for row in rows if row.token in base.reserved)
    return rows, roots, projections, reserved


def model_vector_inventory(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
    *,
    include_source_fields: bool = True,
):
    if "ldb_root" in graph:
        _validate_ldb_root_contract(kernel, graph["ldb_root"])
    key = _inventory_dependency_key(
        kernel=kernel,
        packages=_package_semantic_dependencies(graph["packages"]),
        model_vector_dependencies=_model_vector_dependencies(graph),
        surfaces=sorted(set(graph) - {"source"}),
    )
    cached = _MODEL_VECTOR_INVENTORY_CACHE.get(key)
    if cached is None:
        rows, roots, projections, reserved = _model_vector_inventory_uncached(
            kernel, graph
        )
        cached = (
            frozenset(rows),
            frozenset(roots),
            deepcopy(projections),
            frozenset(reserved),
        )
        _MODEL_VECTOR_INVENTORY_CACHE[key] = cached
        _MODEL_VECTOR_INVENTORY_CACHE.move_to_end(key)
        while len(_MODEL_VECTOR_INVENTORY_CACHE) > _MODEL_VECTOR_INVENTORY_CACHE_LIMIT:
            _MODEL_VECTOR_INVENTORY_CACHE.popitem(last=False)
    else:
        _MODEL_VECTOR_INVENTORY_CACHE.move_to_end(key)
    rows, roots, projections, reserved = cached
    selected_rows = {
        row for row in rows if include_source_fields or row.token.role != "source-field"
    }
    selected_reserved = {
        token
        for token in reserved
        if include_source_fields or token.role != "source-field"
    }
    return selected_rows, set(roots), deepcopy(projections), selected_reserved
