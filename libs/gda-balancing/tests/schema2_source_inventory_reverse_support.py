"""Independent reverse coverage for physical Model Source field owners.

The inventory reader is one observation of Source ownership.  This verifier
starts again from the selected wire schema, its semantic annotations, the
actual Source objects, and the language consumers that select those objects.
It intentionally compares physical occurrences without their diagnostic law:
outside generated execution artifacts the reader de-duplicates by the five
physical coordinates, so the retained law is only an insertion-order detail.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from schema2_extension_inventory_support import AuthorityToken, InventoryRefusal


type _Address = tuple[str | int, ...]
type _Position = tuple[AuthorityToken, str, str, str, str]

_EXECUTION_ROOTS = ("/experiment/", "/artifacts/", "/results/")


def _child(pointer: str, key: str | int) -> str:
    return pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _same_instance_schemas(
    value: Any, pointer: str
) -> list[tuple[dict[str, Any], str]]:
    if not isinstance(value, dict):
        return []
    found = [(value, pointer)]
    for applicator in ("oneOf", "anyOf", "allOf"):
        branches = value.get(applicator, [])
        if not isinstance(branches, list):
            continue
        for index, branch in enumerate(branches):
            found.extend(
                _same_instance_schemas(branch, f"{pointer}/{applicator}/{index}")
            )
    return found


def _source_schema(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> tuple[str, str, dict[str, Any], str]:
    """Bind the one authored schema selected by the Kernel's Source role."""
    try:
        notation = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["source_notation"]
        protocol_role = notation["role"]
        declared = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]
    except (KeyError, TypeError) as error:
        raise InventoryRefusal("Source reverse role binding is absent") from error
    if not isinstance(protocol_role, str) or protocol_role not in declared.get(
        "identified_artifacts", []
    ) + declared.get("standalone_inputs", []):
        raise InventoryRefusal("Source reverse role is not a declared protocol")
    matches: list[tuple[str, str, dict[str, Any], str]] = []
    for package_index, package in enumerate(graph.get("packages", [])):
        for closure_index, closure in enumerate(package.get("semantic_closure", [])):
            role = closure.get("authority_path")
            if role not in {
                "language.wire_schemas",
                "language.artifact_wire_schemas",
            }:
                continue
            for definition_index, definition in enumerate(
                closure.get("definitions", [])
            ):
                if (
                    isinstance(definition, dict)
                    and definition.get("protocol_role") == protocol_role
                    and isinstance(definition.get("artifact_kind"), str)
                    and isinstance(definition.get("schema"), dict)
                ):
                    matches.append(
                        (
                            role,
                            definition["artifact_kind"],
                            definition["schema"],
                            f"/packages/{package_index}/semantic_closure/"
                            f"{closure_index}/definitions/{definition_index}/schema",
                        )
                    )
    if len(matches) != 1:
        raise InventoryRefusal("Source reverse schema has no unique owner")
    return matches[0]


def _token(schema_role: str, schema_kind: str, address: _Address) -> AuthorityToken:
    if len(address) < 2 or address[-2] != "properties":
        raise InventoryRefusal("Source reverse address is not an object member")
    owner: tuple[str, ...] = (schema_role, schema_kind)
    index = 0
    while index < len(address) - 2:
        step = address[index]
        member = address[index + 1]
        if step == "properties" and isinstance(member, str):
            owner = (*owner, "member", member)
            index += 2
        elif step == "items":
            owner = (*owner, "items")
            index += 1
        else:
            raise InventoryRefusal("Source reverse owner has an unknown schema step")
    name = address[-1]
    if not isinstance(name, str) or not name:
        raise InventoryRefusal("Source reverse field name is malformed")
    return AuthorityToken("source-field", owner, name)


def _schema_nodes(
    schema: dict[str, Any], address: _Address
) -> list[tuple[dict[str, Any], _Address]]:
    selected: list[tuple[dict[str, Any], _Address]] = [(schema, ())]
    index = 0
    while index < len(address):
        step = address[index]
        if step == "properties" and index + 1 < len(address):
            member = address[index + 1]
            selected = [
                (candidate["properties"][member], (*path, "properties", member))
                for value, parent in selected
                for candidate, path in _same_instance_schema_addresses(value, parent)
                if isinstance(member, str)
                and member in candidate.get("properties", {})
                and isinstance(candidate["properties"][member], dict)
            ]
            index += 2
        elif step == "items":
            selected = [
                (candidate["items"], (*path, "items"))
                for value, parent in selected
                for candidate, path in _same_instance_schema_addresses(value, parent)
                if isinstance(candidate.get("items"), dict)
            ]
            index += 1
        else:
            raise InventoryRefusal("Source reverse schema address is malformed")
    return [
        (candidate, path)
        for value, parent in selected
        for candidate, path in _same_instance_schema_addresses(value, parent)
    ]


def _same_instance_schema_addresses(
    value: Any, address: _Address
) -> list[tuple[dict[str, Any], _Address]]:
    if not isinstance(value, dict):
        return []
    found = [(value, address)]
    for applicator in ("oneOf", "anyOf", "allOf"):
        branches = value.get(applicator, [])
        if not isinstance(branches, list):
            continue
        for index, branch in enumerate(branches):
            found.extend(
                _same_instance_schema_addresses(branch, (*address, applicator, index))
            )
    return found


def _schema_pointer(root: str, address: _Address) -> str:
    for part in address:
        root = _child(root, part)
    return root


def _semantic_addresses(
    schema: dict[str, Any],
) -> tuple[set[_Address], dict[tuple[str, str], set[_Address]]]:
    """Derive the role/member graph from the LDB-owned annotations alone."""
    found: dict[tuple[str, str], set[_Address]] = {}
    occurrence_members: dict[tuple[str, _Address], set[str]] = {}
    role_members: dict[str, set[str]] = {}
    roots: set[tuple[str, _Address]] = set()

    def visit(value: Any, address: _Address, inherited: str | None = None) -> None:
        if not isinstance(value, dict):
            return
        explicit = value.get("semantic_role")
        if explicit is not None and (not isinstance(explicit, str) or not explicit):
            raise InventoryRefusal(
                "Source reverse schema has a malformed semantic role"
            )
        role = explicit if isinstance(explicit, str) else inherited
        if isinstance(explicit, str):
            roots.add((explicit, address))
        properties = value.get("properties", {})
        if not isinstance(properties, dict):
            raise InventoryRefusal("Source reverse object properties are malformed")
        for authored_name, child in properties.items():
            if not isinstance(authored_name, str) or not isinstance(child, dict):
                raise InventoryRefusal("Source reverse property is malformed")
            semantic_member = child.get("semantic_member")
            child_address = (*address, "properties", authored_name)
            if semantic_member is not None:
                if (
                    not isinstance(semantic_member, str)
                    or not semantic_member
                    or role is None
                ):
                    raise InventoryRefusal(
                        "Source reverse member has no semantic role owner"
                    )
                found.setdefault((role, semantic_member), set()).add(child_address)
                occurrence_members.setdefault((role, address), set()).add(
                    semantic_member
                )
                role_members.setdefault(role, set()).add(semantic_member)
            # A property enters a child instance.  Only an explicit role on that
            # child (or on one of its same-instance branches) owns its members.
            visit(child, child_address)
        item = value.get("items")
        if item is not None:
            if not isinstance(item, dict):
                raise InventoryRefusal("Source reverse array item is malformed")
            # An array item is likewise a new instance and owner.
            visit(item, (*address, "items"))
        for applicator in ("oneOf", "anyOf", "allOf"):
            branches = value.get(applicator, [])
            if not isinstance(branches, list):
                raise InventoryRefusal("Source reverse schema branch is malformed")
            for branch in branches:
                # Applicators share the same instance and owner.  Their indexes
                # belong only to the authored schema pointer.
                visit(branch, address, role)

    visit(schema, ())
    if not roots or not found:
        raise InventoryRefusal("Source reverse semantic annotations are absent")
    for role, address in roots:
        if occurrence_members.get((role, address), set()) != role_members[role]:
            raise InventoryRefusal(
                "Source reverse semantic role occurrences disagree on members"
            )
    return set().union(*found.values()), found


def _semantic_children(
    value: dict[str, Any], address: _Address, member: str
) -> list[tuple[dict[str, Any], _Address]]:
    selected: list[tuple[dict[str, Any], _Address]] = []
    for candidate, _ in _same_instance_schemas(value, ""):
        properties = candidate.get("properties", {})
        if not isinstance(properties, dict):
            continue
        selected.extend(
            (child, (*address, "properties", authored))
            for authored, child in properties.items()
            if isinstance(child, dict) and child.get("semantic_member") == member
        )
    names = {path[-1] for _, path in selected}
    if len(names) != 1:
        raise InventoryRefusal("Source reverse selector member is absent or ambiguous")
    return selected


def _resolve_semantic_selector(
    candidates: list[tuple[dict[str, Any], _Address]], selector: Any
) -> tuple[list[tuple[dict[str, Any], _Address]], set[_Address]]:
    if not isinstance(selector, list) or not selector:
        raise InventoryRefusal("Source reverse selector is empty")
    consumed: set[_Address] = set()
    for segment in selector:
        if segment == "*":
            following = [
                (candidate["items"], (*address, "items"))
                for candidate, address in candidates
                if candidate.get("type") == "array"
                and isinstance(candidate.get("items"), dict)
            ]
            if len(following) != len(candidates):
                raise InventoryRefusal("Source reverse wildcard has no array owner")
        elif isinstance(segment, str) and segment:
            following = []
            for candidate, address in candidates:
                children = _semantic_children(candidate, address, segment)
                following.extend(children)
                consumed.update(path for _, path in children)
        else:
            raise InventoryRefusal("Source reverse selector segment is malformed")
        physical = {address for _, address in following}
        if not following or len(physical) != 1:
            raise InventoryRefusal("Source reverse selector is ambiguous")
        candidates = following
    return candidates, consumed


def _trace_model_checks(
    graph: Mapping[str, Any], schema: dict[str, Any]
) -> set[_Address]:
    consumed: set[_Address] = set()
    for package in graph.get("packages", []):
        for closure in package.get("semantic_closure", []):
            if closure.get("authority_path") != "language.model_checks":
                continue
            for check in closure.get("definitions", []):
                if not isinstance(check, dict):
                    raise InventoryRefusal("Source reverse Model check is malformed")
                roots = [(schema, ())]
                scope = check.get("semantic_scope_selector")
                if scope is not None:
                    roots, selected = _resolve_semantic_selector(roots, scope)
                    consumed.update(selected)
                _, selected = _resolve_semantic_selector(
                    roots, check.get("semantic_selector")
                )
                consumed.update(selected)
    return consumed


def _trace_path(
    candidates: list[tuple[dict[str, Any], _Address]], path: Any
) -> tuple[list[tuple[dict[str, Any], _Address]], set[_Address]]:
    if not isinstance(path, list):
        raise InventoryRefusal("Source reverse Resolution path is malformed")
    consumed: set[_Address] = set()
    for segment in path:
        if not isinstance(segment, str) or not segment:
            raise InventoryRefusal("Source reverse Resolution segment is malformed")
        following = []
        for candidate, address in candidates:
            children = _semantic_children(candidate, address, segment)
            following.extend(children)
            consumed.update(child_address for _, child_address in children)
        physical = {address for _, address in following}
        if not following or len(physical) != 1:
            raise InventoryRefusal("Source reverse Resolution path is ambiguous")
        candidates = following
    return candidates, consumed


def _trace_resolution_profiles(
    graph: Mapping[str, Any], schema: dict[str, Any]
) -> set[_Address]:
    consumed: set[_Address] = set()
    for package in graph.get("packages", []):
        for closure in package.get("semantic_closure", []):
            if closure.get("authority_path") != "language.resolution_profiles":
                continue
            for profile in closure.get("definitions", []):
                if not isinstance(profile, dict):
                    raise InventoryRefusal(
                        "Source reverse Resolution profile is malformed"
                    )
                for recipe in profile.get("relation_recipes", []):
                    bindings: dict[str, list[tuple[dict[str, Any], _Address]]] = {}

                    def select(term: Any) -> list[tuple[dict[str, Any], _Address]]:
                        if not isinstance(term, dict):
                            raise InventoryRefusal(
                                "Source reverse Resolution term is malformed"
                            )
                        root = term.get("root")
                        if root == "source":
                            candidates = [(schema, ())]
                        elif root == "binding" and term.get("binding") in bindings:
                            candidates = bindings[term["binding"]]
                        else:
                            return []
                        selected, addresses = _trace_path(candidates, term.get("path"))
                        consumed.update(addresses)
                        return selected

                    for binding in recipe.get("bindings", []):
                        selected = select(binding.get("source"))
                        if selected:
                            items = [
                                (candidate["items"], (*address, "items"))
                                for candidate, address in selected
                                if candidate.get("type") == "array"
                                and isinstance(candidate.get("items"), dict)
                            ]
                            if len(items) != len(selected):
                                raise InventoryRefusal(
                                    "Source reverse binding does not select a list"
                                )
                            bindings[binding["name"]] = items
                    for predicate in recipe.get("predicates", []):
                        select(predicate.get("left"))
                        select(predicate.get("right"))
                    for field in recipe.get("fields", []):
                        select(field.get("term"))
    return consumed


def _trace_formula_consumers(
    kernel: Mapping[str, Any],
    graph: Mapping[str, Any],
) -> set[_Address]:
    """Bind Formula notation to its actual LDB Operation owner.

    Formula field ownership comes from the Source Schema annotations.  The only
    Kernel input needed to locate Formula notation is its generic authority and
    extension reference; the LDB's definitions are the selected consumers.
    """
    try:
        owner = kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["source_notation"]["operation_source"]
        authority_path = owner["authority_path"]
        extension_member = owner["extension_member"]
    except (KeyError, TypeError) as error:
        raise InventoryRefusal("Source reverse Formula owner is absent") from error
    if not all(
        isinstance(member, str) and member
        for member in (authority_path, extension_member)
    ):
        raise InventoryRefusal("Source reverse Formula owner is malformed")
    for package in graph.get("packages", []):
        for closure in package.get("semantic_closure", []):
            if closure.get("authority_path") != authority_path:
                continue
            definitions = closure.get("definitions", [])
            if not isinstance(definitions, list):
                raise InventoryRefusal(
                    "Source reverse Formula definitions are malformed"
                )
            for definition in definitions:
                if not isinstance(definition, dict):
                    raise InventoryRefusal(
                        "Source reverse Formula definition is malformed"
                    )
                extensions = definition.get("extensions", {})
                if not isinstance(extensions, dict):
                    raise InventoryRefusal(
                        "Source reverse Formula extensions are malformed"
                    )
                selected = extensions.get(extension_member)
                if selected is not None:
                    if not isinstance(selected, dict):
                        raise InventoryRefusal(
                            "Source reverse Formula selector is malformed"
                        )
    return set()


def _field_positions(
    schema: dict[str, Any],
    schema_pointer: str,
    schema_role: str,
    schema_kind: str,
    addresses: set[_Address],
) -> set[_Position]:
    positions: set[_Position] = set()
    for address in addresses:
        token = _token(schema_role, schema_kind, address)
        parent = address[:-2]
        for candidate, path in _schema_nodes(schema, parent):
            properties = candidate.get("properties", {})
            if token.name in properties:
                positions.add(
                    (
                        token,
                        _schema_pointer(
                            schema_pointer, (*path, "properties", token.name)
                        ),
                        "declaration",
                        "key",
                        "",
                    )
                )
            required = candidate.get("required", [])
            if not isinstance(required, list):
                continue
            for index, member in enumerate(required):
                if member == token.name:
                    positions.add(
                        (
                            token,
                            _schema_pointer(schema_pointer, (*path, "required", index)),
                            "reference",
                            "value",
                            "",
                        )
                    )
    return positions


def _address_tokens(
    schema_role: str, schema_kind: str, addresses: set[_Address]
) -> dict[_Address, AuthorityToken]:
    return {address: _token(schema_role, schema_kind, address) for address in addresses}


def _walk_actual_keys(
    value: Any,
    pointer: str,
    schema_address: _Address,
    tokens: Mapping[_Address, AuthorityToken],
) -> tuple[set[_Position], dict[str, AuthorityToken]]:
    positions: set[_Position] = set()
    keys: dict[str, AuthorityToken] = {}
    if isinstance(value, dict):
        for name, child in value.items():
            child_pointer = _child(pointer, name)
            child_address = (*schema_address, "properties", name)
            token = tokens.get(child_address)
            if token is not None:
                positions.add((token, child_pointer, "reference", "key", ""))
                keys[child_pointer] = token
            child_positions, child_keys = _walk_actual_keys(
                child, child_pointer, child_address, tokens
            )
            positions.update(child_positions)
            keys.update(child_keys)
    elif isinstance(value, list):
        item_address = (*schema_address, "items")
        for index, child in enumerate(value):
            child_positions, child_keys = _walk_actual_keys(
                child, _child(pointer, index), item_address, tokens
            )
            positions.update(child_positions)
            keys.update(child_keys)
    return positions, keys


def _pointer_segments(value: Any) -> list[str]:
    if not isinstance(value, str) or (value and not value.startswith("/")):
        raise InventoryRefusal("Source reverse diagnostic pointer is malformed")
    encoded = value.split("/")[1:]
    if any("~" in part.replace("~0", "").replace("~1", "") for part in encoded):
        raise InventoryRefusal("Source reverse diagnostic pointer has a bad escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in encoded]


def _path_value(value: Any, path: Sequence[str]) -> Any:
    for part in path:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _fixture_pointer_tokens(
    fixture: Mapping[str, Any],
    tokens: Mapping[_Address, AuthorityToken],
    pointer_value: Any,
    graph: Mapping[str, Any],
) -> list[AuthorityToken | None]:
    segments = _pointer_segments(pointer_value)
    current: Any = fixture["source"]
    address: _Address = ()
    path: tuple[str, ...] = ()
    collection = tuple(fixture.get("collection_path", []))
    count = None
    if fixture.get("mode") == "indexed-repeat":
        count_path = fixture.get("count_resource_path")
        if not isinstance(count_path, str):
            raise InventoryRefusal("Source reverse repeat count path is malformed")
        count = (
            _path_value(graph["ldb_root"], count_path.split("."))
            + fixture["count_offset"]
        )
    found: list[AuthorityToken | None] = []
    for segment in segments:
        if isinstance(current, list):
            if not segment.isdecimal():
                break
            index = int(segment)
            address = (*address, "items")
            next_path = (*path, segment)
            if index < len(current):
                current = current[index]
            elif count is not None and path == collection and 0 <= index < count:
                current = deepcopy(fixture["template"])
                current[fixture["index_member"]] = "generated"
            else:
                break
            path = next_path
            found.append(None)
            continue
        if not isinstance(current, dict) or segment not in current:
            break
        address = (*address, "properties", segment)
        found.append(tokens.get(address))
        current = current[segment]
        path = (*path, segment)
    return found


def _vector_positions(
    graph: Mapping[str, Any], tokens: Mapping[_Address, AuthorityToken]
) -> set[_Position]:
    positions: set[_Position] = set()
    for vector_set_index, vector_set in enumerate(graph.get("vector_sets", [])):
        for vector_index, vector in enumerate(vector_set.get("vector_definitions", [])):
            fixture = vector.get("source_fixture")
            if not isinstance(fixture, dict):
                continue
            root = f"/vector_sets/{vector_set_index}/vector_definitions/{vector_index}"
            source_positions, _ = _walk_actual_keys(
                fixture.get("source"), root + "/source_fixture/source", (), tokens
            )
            positions.update(source_positions)
            collection = fixture.get("collection_path")
            if collection is not None:
                if not isinstance(collection, list):
                    raise InventoryRefusal(
                        "Source reverse materialization path is malformed"
                    )
                address: _Address = ()
                for index, part in enumerate(collection):
                    if not isinstance(part, str):
                        raise InventoryRefusal(
                            "Source reverse materialization segment is malformed"
                        )
                    if part.isdecimal():
                        address = (*address, "items")
                        continue
                    address = (*address, "properties", part)
                    token = tokens.get(address)
                    if token is None:
                        raise InventoryRefusal(
                            "Source reverse materialization field is unowned"
                        )
                    positions.add(
                        (
                            token,
                            f"{root}/source_fixture/collection_path/{index}",
                            "reference",
                            "value",
                            "",
                        )
                    )
                item_address = (*address, "items")
                template_positions, _ = _walk_actual_keys(
                    fixture.get("template"),
                    root + "/source_fixture/template",
                    item_address,
                    tokens,
                )
                positions.update(template_positions)
                index_member = fixture.get("index_member")
                if not isinstance(index_member, str):
                    raise InventoryRefusal(
                        "Source reverse materialization index is malformed"
                    )
                index_address = (*item_address, "properties", index_member)
                token = tokens.get(index_address)
                if token is None:
                    raise InventoryRefusal(
                        "Source reverse materialization index is unowned"
                    )
                positions.add(
                    (
                        token,
                        root + "/source_fixture/index_member",
                        "reference",
                        "value",
                        "",
                    )
                )
            expected = vector.get("expect", {})
            for diagnostic_index, diagnostic in enumerate(
                expected.get("diagnostics", [])
            ):
                pointer = f"{root}/expect/diagnostics/{diagnostic_index}/pointer"
                for projection, token in enumerate(
                    _fixture_pointer_tokens(
                        fixture, tokens, diagnostic.get("pointer"), graph
                    )
                ):
                    if token is not None:
                        positions.add(
                            (
                                token,
                                pointer,
                                "reference",
                                "json-pointer",
                                str(projection),
                            )
                        )
    return positions


def _source_context(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> tuple[
    dict[str, Any],
    dict[_Address, AuthorityToken],
    set[_Position],
]:
    schema_role, schema_kind, schema, schema_pointer = _source_schema(kernel, graph)
    annotated, _ = _semantic_addresses(schema)
    consumed = set(annotated)
    consumed.update(_trace_resolution_profiles(graph, schema))
    consumed.update(_trace_model_checks(graph, schema))
    consumed.update(_trace_formula_consumers(kernel, graph))
    tokens = _address_tokens(schema_role, schema_kind, consumed)
    schema_positions = _field_positions(
        schema, schema_pointer, schema_role, schema_kind, consumed
    )
    return schema, tokens, schema_positions


def source_key_tokens(
    kernel: Mapping[str, Any], graph: Mapping[str, Any]
) -> dict[str, AuthorityToken]:
    """Return independently owned keys in the graph's actual Model Source."""
    _, tokens, _ = _source_context(kernel, graph)
    source = graph.get("source")
    if not isinstance(source, dict):
        return {}
    _, keys = _walk_actual_keys(source, "/source", (), tokens)
    return keys


def validate_source_inventory(
    kernel: Mapping[str, Any], graph: Mapping[str, Any], inventory: Any
) -> None:
    """Require the exact non-execution Source-field occurrence projection."""
    _, tokens, expected = _source_context(kernel, graph)
    source = graph.get("source")
    if isinstance(source, dict):
        actual_positions, _ = _walk_actual_keys(source, "/source", (), tokens)
        expected.update(actual_positions)
    expected.update(_vector_positions(graph, tokens))
    actual: set[_Position] = {
        (row.token, row.pointer, row.use, row.location, row.projection)
        for row in inventory.occurrences
        if row.token.role == "source-field"
        and not row.pointer.startswith(_EXECUTION_ROOTS)
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        first = missing[0][1] if missing else extra[0][1]
        raise InventoryRefusal(
            "Source field address coverage is incomplete or misowned at "
            f"{first}: missing={len(missing)} extra={len(extra)}"
        )
    if inventory.reserved & set(tokens.values()):
        raise InventoryRefusal("Source annotated field ownership is misclassified")
