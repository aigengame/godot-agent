"""The payload's enums and a project global of the same name (#1205).

A ``--project`` operation compiles the headless payload inside the user's
project (ADR-0043 §5), so the payload's names share the project's global
namespace: a ``class_name`` in the class index, or an autoload. In a type hint,
Godot resolves such a global before the script's own enum, so a payload enum
used as a type stops the payload from compiling in a project that has a global
of the same name. The payload therefore names an enum only before a ``.``, to
read a value (``Write.SET``), and a parameter that takes one is ``int``.
"""

import re
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.support import PAYLOAD_DIR, Gda

# Every GDScript file gda compiles inside a project: the payload and the harness.
GDA_DIR = PAYLOAD_DIR.parent
# A comment or a string, matched in source order, so that a `#` in a string or a
# quote in a comment does not start the other.
NOT_CODE = re.compile(
    r"#.*"
    r'|"""[\s\S]*?"""'
    r"|'''[\s\S]*?'''"
    r'|"(?:\\.|[^"\\\n])*"'
    r"|'(?:\\.|[^'\\\n])*'"
)
ENUM = re.compile(r"^\s*enum\s+(\w+)")
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'


@pytest.mark.e2e
def test_project_classes_named_like_payload_enums_break_no_scene_node_or_script_command(
    tmp_path,
):
    project = tmp_path / "p"
    project.mkdir()
    (project / "project.godot").write_text(
        project_godot(name="gda-enum-names"), encoding="utf-8"
    )
    (project / "write.gd").write_text(
        "class_name Write extends Node\n", encoding="utf-8"
    )
    (project / "role.gd").write_text("class_name Role extends Node\n", encoding="utf-8")
    (project / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    gda = Gda(project, json_output=True, timeout=300)

    # Without a scan the class index is empty and the names clash with nothing.
    scanned = gda.json("project", "scan")
    assert {"Write", "Role"} <= {entry["name"] for entry in scanned["classes"]}

    added = gda.json(
        "node", "add", "res://main.tscn", "--type", "Node", "--name", "Child"
    )
    assert added["path"] == "Child"
    written = gda.json(
        "node",
        "set",
        "res://main.tscn",
        "--node",
        "Child",
        "--property",
        "process_priority",
        "--value",
        "3",
    )
    assert written["value"] == 3
    scene = gda.json("scene", "get", "res://main.tscn")
    assert [child["name"] for child in scene["root"]["children"]] == ["Child"]
    assert gda.json("script", "validate", "res://write.gd")["valid"] is True


def _code(path: Path) -> list[tuple[int, str]]:
    """Each line of ``path`` with its comments and strings removed."""
    text = path.read_text(encoding="utf-8")
    code = NOT_CODE.sub(lambda m: "\n" * m[0].count("\n"), text)
    return list(enumerate(code.splitlines(), 1))


def test_the_payload_names_an_enum_only_before_a_dot():
    files = {path: _code(path) for path in sorted(GDA_DIR.rglob("*.gd"))}
    enums = {
        m[1] for code in files.values() for _, line in code if (m := ENUM.match(line))
    }
    assert enums, f"no enum declared under {GDA_DIR}"
    other_use = re.compile(rf"(?<!\w)({'|'.join(sorted(enums))})(?!\w)(?!\s*\.)")
    found = [
        f"{path.relative_to(GDA_DIR)}:{n}: {line.strip()}"
        for path, code in files.items()
        for n, line in code
        if other_use.search(line[m.end() :] if (m := ENUM.match(line)) else line)
    ]
    assert not found, (
        "a payload enum is used other than before a `.`; type the value int (#1205):\n"
        + "\n".join(found)
    )
