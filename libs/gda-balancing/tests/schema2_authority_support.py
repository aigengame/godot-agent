"""Shared authority inputs and owner-preserving mutable test projections."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()


def refresh_package_semantic_closures(
    language_bundle: LanguageBundleIndex, kernel: dict[str, Any]
) -> None:
    """Apply unambiguous flat fixture edits without inventing definition ownership.

    A flat index has no owner for an Operation or Component. When several
    namespaces export the same local key, only unchanged attached definitions
    can be matched safely. Edit their attached closures and reidentify the graph
    directly when a test needs to change a colliding definition.
    """
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    unique_law = next(
        law
        for law in kernel["admission"]["laws"]
        if law["id"] == "kernel.identifiers.unique"
    )
    scoped = {
        contract["path"].removeprefix("language_bundle.")
        for contract in unique_law["arguments"]["collections"]
        if contract.get("scope") == "package"
    }

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    packages = language_bundle["language"]["packages"]
    updates: list[tuple[dict[str, Any], list[Any]]] = []
    for projection in projections:
        path = projection["authority_path"]
        key_member = projection["key_member"]

        def key(definition: Any) -> Any:
            return definition if key_member is None else definition[key_member]

        definitions = path_values(language_bundle, path)
        for package in packages:
            entry = next(
                item
                for item in package["semantic_closure"]
                if item["authority_path"] == path
            )
            owned = path_values(package, projection["owners_path"])
            selected = []
            for definition in definitions:
                local_key = key(definition)
                if local_key not in owned:
                    continue
                owners = [
                    candidate
                    for candidate in packages
                    if local_key in path_values(candidate, projection["owners_path"])
                ]
                if path in scoped and len(owners) > 1:
                    if isinstance(definition, dict) and "package" in definition:
                        if definition["package"] != package["id"]:
                            continue
                    elif definition not in entry["definitions"]:
                        if not any(
                            definition in candidate_entry["definitions"]
                            for owner in owners
                            for candidate_entry in owner["semantic_closure"]
                            if candidate_entry["authority_path"] == path
                        ):
                            raise AssertionError(
                                f"ambiguous flat mutation at {path}:{local_key}; "
                                "mutate the owning package closure directly"
                            )
                        continue
                selected.append(deepcopy(definition))
            updates.append((entry, selected))
    for entry, definitions in updates:
        entry["definitions"] = definitions
