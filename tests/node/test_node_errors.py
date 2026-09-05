"""S3: gda node failure modes map to structured JSON errors + stable exit codes.

Issue #53's acceptance: node-command failures (scene not found, bad parent
path, invalid type, name collision) surface as structured ``GdaError``s with
registered operation codes (ADR-0002) — exit 4 for the operation category,
finer stable codes so an agent can branch on the mode without parsing prose.
"""

from tests.support import assert_operation_error, operation_error_invoker

_node_add = operation_error_invoker(
    ["node", "add", "/x/main.tscn", "--type", "Sprite2D", "--json"], "node-add"
)


def test_node_add_bad_parent_maps_to_stable_parent_not_found_code(monkeypatch):
    # The scene exists but the requested parent node path resolves to nothing —
    # a new node-group code, distinct from the file-level path_not_found, so an
    # agent knows to fix the node path, not the scene path.
    result = _node_add(
        monkeypatch, "parent_not_found", "parent node not found in scene: Bogus/Path"
    )

    # The raw stderr still rides along as diagnostics (ADR-0002).
    assert_operation_error(
        result,
        "parent_not_found",
        "Bogus/Path",
        diagnostics="gda: running operation: node-add\n",
    )


def test_node_add_non_canonical_parent_maps_to_stable_parent_not_found_code(
    monkeypatch,
):
    # Issue #66: a non-canonical parent path ("A/..", "A/", "./A", …) is
    # rejected by the operation rather than silently resolved to a node the
    # literal string never named. The refusal reuses the registered
    # parent_not_found code — under strict addressing the path resolves to
    # nothing — with a message naming the canonical form. Mapping pin: the
    # envelope rides through the same parent_not_found path as a missing
    # canonical parent.
    result = _node_add(
        monkeypatch,
        "parent_not_found",
        "non-canonical parent path: A/.. — address the parent exactly as "
        "node list reports it: '.' for the root, 'A/B' for a descendant",
    )

    err = assert_operation_error(result, "parent_not_found", "A/..")
    assert "non-canonical" in err["message"]


def test_node_add_unknown_type_maps_to_stable_invalid_node_type_code(monkeypatch):
    result = _node_add(
        monkeypatch,
        "invalid_node_type",
        "not an instantiable Node class or registered class_name: Foo",
    )

    assert_operation_error(result, "invalid_node_type", "Foo")


def test_node_add_name_collision_maps_to_stable_duplicate_node_name_code(monkeypatch):
    result = _node_add(
        monkeypatch, "duplicate_node_name", "parent already has a child named: Hero"
    )

    assert_operation_error(result, "duplicate_node_name", "Hero")


def test_node_add_bad_name_maps_to_stable_invalid_node_name_code(monkeypatch):
    result = _node_add(monkeypatch, "invalid_node_name", "invalid name: Bad%Name")

    assert_operation_error(result, "invalid_node_name", "Bad%Name")


def test_node_add_vanished_instance_maps_to_stable_missing_dependency_code(monkeypatch):
    # Issue #64: a scene whose instanced sub-scene cannot be resolved on load
    # would lose the whole instance on re-save; the refusal surfaces as the
    # registered missing_dependency code so an agent knows to fix the scene's
    # dependencies or its project context rather than retry the add.
    result = _node_add(
        monkeypatch,
        "missing_dependency",
        "scene nodes vanished on load (unresolvable instanced sub-scene?): "
        "ChildInstance — re-saving would silently drop them",
    )

    assert_operation_error(result, "missing_dependency", "ChildInstance")


def test_node_add_substituted_class_maps_to_stable_missing_dependency_code(monkeypatch):
    # Issue #64's degraded mode: a declared class unavailable in this engine
    # run materializes as a substitute node, so a re-save would rewrite its
    # type. The refusal reuses missing_dependency — an unavailable class IS a
    # missing dependency (extension/module), the same agent fix applies.
    result = _node_add(
        monkeypatch,
        "missing_dependency",
        "scene nodes vanished or degraded on load: "
        "Widget (declared TotallyMissingClass, materialized Node) — "
        "re-saving would silently drop or downgrade them",
    )

    assert_operation_error(
        result, "missing_dependency", "declared TotallyMissingClass, materialized Node"
    )


def test_node_add_broken_class_name_maps_to_stable_uninstantiable_script_code(
    monkeypatch,
):
    # Issue #65: a class_name still present in the global class list but whose
    # script broke after registration is a script problem, not an unknown type.
    # The refusal surfaces as the registered uninstantiable_script code so an
    # agent knows to repair the script rather than the type name.
    result = _node_add(
        monkeypatch,
        "uninstantiable_script",
        "registered class_name Hero script cannot be instantiated: "
        "res://hero.gd — it no longer compiles; see diagnostics",
    )

    assert_operation_error(result, "uninstantiable_script", "res://hero.gd")


def test_node_add_missing_scene_reuses_stable_path_not_found_code(monkeypatch):
    # The scene-file-level failure reuses the registered scene code: the
    # node group introduces no parallel code for the same mode.
    result = _node_add(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert_operation_error(result, "path_not_found", "/x/main.tscn")


_node_get = operation_error_invoker(
    ["node", "get", "/x/main.tscn", "--node", "Bogus", "--json"], "node-get"
)


_node_set = operation_error_invoker(
    [
        "node",
        "set",
        "/x/main.tscn",
        "--node",
        "Hero",
        "--property",
        "position",
        "--value",
        "3,4",
        "--json",
    ],
    "node-set",
)


def test_node_get_missing_node_maps_to_stable_node_not_found_code(monkeypatch):
    # issue #55: a node path that resolves to nothing is node_not_found —
    # distinct from the file-level path_not_found and from node add's
    # parent_not_found, so an agent knows the node, not the file or parent, is
    # the thing that's missing.
    result = _node_get(monkeypatch, "node_not_found", "node not found in scene: Bogus")

    assert_operation_error(result, "node_not_found", "Bogus")


def test_node_set_missing_node_maps_to_stable_node_not_found_code(monkeypatch):
    result = _node_set(monkeypatch, "node_not_found", "node not found in scene: Hero")

    assert_operation_error(result, "node_not_found", "Hero")


def test_node_set_unknown_property_maps_to_stable_unknown_property_code(monkeypatch):
    # issue #55: setting a property the node does not declare is a clean
    # unknown_property error, so an agent can branch on a typo'd or absent
    # property name rather than parsing prose.
    result = _node_set(
        monkeypatch,
        "unknown_property",
        "node Hero has no settable property: positon",
    )

    assert_operation_error(result, "unknown_property", "positon")


def test_node_set_uncoercible_value_maps_to_stable_uncoercible_value_code(monkeypatch):
    # issue #55's type-coercion contract: a value that cannot be coerced to the
    # property's declared Godot type is a clean uncoercible_value error naming
    # the value, the target type, and the property — never a silent wrong value.
    result = _node_set(
        monkeypatch,
        "uncoercible_value",
        'cannot coerce value "nope" to Vector2 for property position on node Hero',
    )

    assert_operation_error(result, "uncoercible_value", "Vector2")


def test_node_set_missing_dependency_maps_to_stable_missing_dependency_code(
    monkeypatch,
):
    # node set is a mutating op, so it honors the mutation-integrity boundary
    # (issue #64) via the shared mutate-entry: a scene whose instance vanishes
    # on load is refused with missing_dependency, the same as node add, leaving
    # the file untouched rather than dropping the instance on re-save.
    result = _node_set(
        monkeypatch,
        "missing_dependency",
        "scene nodes vanished or degraded on load: ChildInstance (vanished) — "
        "re-saving would silently drop or downgrade them",
    )

    assert_operation_error(result, "missing_dependency", "ChildInstance")


def test_node_get_missing_scene_reuses_stable_path_not_found_code(monkeypatch):
    result = _node_get(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert_operation_error(result, "path_not_found", "/x/main.tscn")


_node_remove = operation_error_invoker(
    lambda node="Hero": ["node", "remove", "/x/main.tscn", "--node", node, "--json"],
    "node-remove",
)


def test_node_remove_missing_node_maps_to_stable_node_not_found_code(monkeypatch):
    # issue #56: removing a node path that resolves to nothing reuses the
    # node-group's node_not_found code — the same mode node get / node set
    # report, so an agent branches on a missing node without a parallel code.
    result = _node_remove(
        monkeypatch, "node_not_found", "node not found in scene: Bogus", node="Bogus"
    )

    assert_operation_error(result, "node_not_found", "Bogus")


def test_node_remove_root_maps_to_stable_cannot_target_root_code(monkeypatch):
    # issue #56: removing the scene root is refused with the new structural-edit
    # code cannot_target_root — the root has no parent to be removed from, so
    # the agent learns to delete the scene file rather than retry the removal.
    result = _node_remove(
        monkeypatch,
        "cannot_target_root",
        "cannot remove the scene root: . — the root has no parent to be removed from",
        node=".",
    )

    assert_operation_error(result, "cannot_target_root", "root")


_node_duplicate = operation_error_invoker(
    lambda node="Hero": ["node", "duplicate", "/x/main.tscn", "--node", node, "--json"],
    "node-duplicate",
)


def test_node_duplicate_missing_node_maps_to_stable_node_not_found_code(monkeypatch):
    # issue #56: duplicating a node path that resolves to nothing reuses the
    # node-group's node_not_found code.
    result = _node_duplicate(
        monkeypatch, "node_not_found", "node not found in scene: Bogus", node="Bogus"
    )

    assert_operation_error(result, "node_not_found", "Bogus")


def test_node_duplicate_root_maps_to_stable_cannot_target_root_code(monkeypatch):
    # issue #56: the scene root has no parent to host a sibling copy, so
    # duplicating '.' reuses the shared cannot_target_root code.
    result = _node_duplicate(
        monkeypatch,
        "cannot_target_root",
        "cannot duplicate the scene root: . — the root has no parent to host a sibling copy",
        node=".",
    )

    assert_operation_error(result, "cannot_target_root", "root")


_node_move = operation_error_invoker(
    lambda node="Hero", to="Enemies": [
        "node",
        "move",
        "/x/main.tscn",
        "--node",
        node,
        "--to",
        to,
        "--json",
    ],
    "node-move",
)


def test_node_move_cyclic_target_maps_to_stable_cyclic_target_code(monkeypatch):
    # issue #56: moving a node under its own descendant would detach the subtree
    # from the scene. The refusal surfaces as the new cyclic_target code so an
    # agent branches on the cyclic mistake rather than parsing prose.
    result = _node_move(
        monkeypatch,
        "cyclic_target",
        "cyclic move target: A/B is the moved node A or one of its descendants",
        node="A",
        to="A/B",
    )

    assert_operation_error(result, "cyclic_target", "A/B")


def test_node_move_missing_target_maps_to_stable_parent_not_found_code(monkeypatch):
    # An invalid move target reuses the node group's parent_not_found code (the
    # same code node add reports for a bad --parent).
    result = _node_move(
        monkeypatch,
        "parent_not_found",
        "target parent node not found in scene: Bogus",
        to="Bogus",
    )

    assert_operation_error(result, "parent_not_found", "Bogus")


def test_node_move_name_collision_maps_to_stable_duplicate_node_name_code(monkeypatch):
    # A name collision at the destination reuses duplicate_node_name.
    result = _node_move(
        monkeypatch,
        "duplicate_node_name",
        "target Enemies already has a child named: Hero",
    )

    assert_operation_error(result, "duplicate_node_name", "Hero")


def test_node_move_missing_node_maps_to_stable_node_not_found_code(monkeypatch):
    result = _node_move(
        monkeypatch, "node_not_found", "node not found in scene: Bogus", node="Bogus"
    )

    assert_operation_error(result, "node_not_found", "Bogus")


def test_node_move_root_maps_to_stable_cannot_target_root_code(monkeypatch):
    # Moving the scene root is refused with cannot_target_root — the root has no
    # parent to be reparented out of.
    result = _node_move(
        monkeypatch,
        "cannot_target_root",
        "cannot move the scene root: . — the root has no parent to be reparented out of",
        node=".",
    )

    assert_operation_error(result, "cannot_target_root", "root")


# --- node connect-signal / disconnect-signal (issue #57) ---


_connect_signal = operation_error_invoker(
    [
        "node",
        "connect-signal",
        "/x/main.tscn",
        "--from",
        "Emitter",
        "--signal",
        "timeout",
        "--to",
        "Receiver",
        "--method",
        "on_timeout",
        "--json",
    ],
    "node-connect-signal",
)


_disconnect_signal = operation_error_invoker(
    [
        "node",
        "disconnect-signal",
        "/x/main.tscn",
        "--from",
        "Emitter",
        "--signal",
        "timeout",
        "--to",
        "Receiver",
        "--method",
        "on_timeout",
        "--json",
    ],
    "node-disconnect-signal",
)


def test_connect_signal_missing_signal_maps_to_stable_signal_not_found_code(
    monkeypatch,
):
    # issue #57's design decision: the signal MUST exist on the source node — a
    # typo or wrong node is a clean signal_not_found error, so an agent branches
    # on a bad signal name rather than parsing prose.
    result = _connect_signal(
        monkeypatch, "signal_not_found", "source node Emitter has no signal: timoeut"
    )

    assert_operation_error(result, "signal_not_found", "timoeut")


def test_connect_signal_missing_source_node_reuses_node_not_found_code(monkeypatch):
    # The source node path resolving to nothing reuses the node group's
    # node_not_found code (issue #55) — the node group introduces no parallel
    # code for the same mode.
    result = _connect_signal(
        monkeypatch, "node_not_found", "source node not found in scene: Emitter"
    )

    assert_operation_error(result, "node_not_found", "Emitter")


def test_connect_signal_missing_target_node_reuses_node_not_found_code(monkeypatch):
    result = _connect_signal(
        monkeypatch, "node_not_found", "target node not found in scene: Receiver"
    )

    assert_operation_error(result, "node_not_found", "Receiver")


def test_connect_signal_already_connected_maps_to_stable_already_connected_code(
    monkeypatch,
):
    # Connecting a signal->method that is already wired is a clean
    # already_connected error rather than a silent no-op or a noisy engine
    # ERR_INVALID_PARAMETER — so an agent can tell "already there" apart from
    # "newly wired".
    result = _connect_signal(
        monkeypatch,
        "already_connected",
        "Emitter.timeout is already connected to Receiver.on_timeout",
    )

    assert_operation_error(result, "already_connected", "on_timeout")


def test_disconnect_signal_absent_connection_maps_to_connection_not_found_code(
    monkeypatch,
):
    # issue #57's acceptance: disconnecting a connection that does not exist is a
    # clean connection_not_found error, not a silent success — so an agent knows
    # the unwiring had nothing to remove.
    result = _disconnect_signal(
        monkeypatch,
        "connection_not_found",
        "no such connection: Emitter.timeout -> Receiver.on_timeout",
    )

    assert_operation_error(result, "connection_not_found", "Emitter.timeout")


def test_disconnect_signal_missing_signal_maps_to_signal_not_found_code(monkeypatch):
    # A missing source signal on disconnect is signal_not_found, symmetric with
    # connect-signal and the documented contract (issue #57 review) — it is not
    # collapsed into connection_not_found.
    result = _disconnect_signal(
        monkeypatch,
        "signal_not_found",
        "source node Emitter has no signal: timoeut",
    )

    assert_operation_error(result, "signal_not_found", "timoeut")


def test_disconnect_signal_missing_node_reuses_node_not_found_code(monkeypatch):
    result = _disconnect_signal(
        monkeypatch, "node_not_found", "source node not found in scene: Emitter"
    )

    assert_operation_error(result, "node_not_found", "Emitter")


def test_connect_signal_missing_scene_reuses_path_not_found_code(monkeypatch):
    result = _connect_signal(
        monkeypatch, "path_not_found", "scene file does not exist: /x/main.tscn"
    )

    assert_operation_error(result, "path_not_found", "/x/main.tscn")
