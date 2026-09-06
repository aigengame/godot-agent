"""S3: the shared ``ConfigFile``-text reader behind every ``project.godot`` read (#843).

``gda.project_file`` is the ONE reader three callers share — the #829 main-scene
precondition, the harness installer's ``[autoload]`` edit, and the bounded project
write. These tests pin the format rules it owns: comments, sections, section-less
keys, multi-line values, escaped key spellings, and the byte-faithful round trip an
edit relies on.
"""

from gda.project_file import (
    SECTIONLESS,
    ConfigText,
    config_key,
    read_config,
    read_config_text,
    section_name,
    strip_comment,
    unquote,
)


PROJECT = """\
; a hand-written project
config_version=5

[application]

config/name="My Game" ; the window title
config/description="a ; semicolon inside quotes"

[input]

fire={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"keycode":74)
]
}

[debug]

file_logging/enable_file_logging=false
"""


def test_strip_comment_cuts_at_an_unquoted_semicolon_only():
    assert strip_comment('a="x" ; note').strip() == 'a="x"'
    assert strip_comment('a="x ; y"') == 'a="x ; y"'


def test_section_name_reads_a_header_and_nothing_else():
    assert section_name("[application]") == "application"
    assert section_name("config/name=1") is None


def test_config_key_decodes_the_engine_encoded_spelling():
    # property_name_encode() quotes and escapes a key holding '=' or non-ASCII, so
    # the two spellings of one key have to compare equal.
    assert config_key("config/name") == "config/name"
    assert config_key('"run/\\u006dain_scene"') == "run/main_scene"
    assert config_key('"a=b"') == "a=b"


def test_config_key_refuses_a_spelling_it_cannot_decode():
    # A key gda cannot name is excluded from every comparison rather than guessed
    # at — a key wrongly read as two keys is how a restore writes a duplicate line.
    assert config_key('"a\\q"') is None
    assert config_key("a\\b") is None


def test_entries_carry_section_name_and_raw_lines():
    config = read_config_text(PROJECT)

    entries = {entry.name: entry for entry in config.entries}
    assert config.sections == ("application", "input", "debug")
    # A key written before the first header is named by its bare key.
    assert entries["config_version"].section == SECTIONLESS
    # A key inside a section is named the way project get names it: section/key.
    assert entries["application/config/name"].section == "application"
    assert entries["application/config/name"].lines == (
        'config/name="My Game" ; the window title',
    )
    # The value is the comment-stripped text, never a decoded Variant.
    assert entries["application/config/name"].value == '"My Game"'
    assert (
        entries["application/config/description"].value
        == '"a ; semicolon inside quotes"'
    )


def test_a_multi_line_value_is_one_entry_with_all_its_lines():
    config = read_config_text(PROJECT)

    action = config.settings()["input/fire"]
    assert len(action.lines) == 5
    assert action.lines[0] == "fire={"
    assert action.lines[-1] == "}"
    # The fragments of a Dictionary value are not mistaken for keys of their own.
    assert '"deadzone": 0.5,' not in [
        line for e in config.entries for line in e.lines[:1]
    ]


def test_text_round_trips_the_input_byte_for_byte():
    for text in (PROJECT, PROJECT.replace("\n", "\r\n"), "a=1", ""):
        assert read_config_text(text).text() == text


def test_settings_keeps_the_last_assignment_of_a_repeated_key():
    # ConfigFile lets the last assignment win; a reader that kept the first would
    # disagree with the engine about what the file says.
    config = read_config_text('[application]\n\nconfig/name="a"\nconfig/name="b"\n')

    assert config.settings()["application/config/name"].value == '"b"'


def test_an_undecodable_key_is_scanned_but_never_named():
    config = read_config_text('[application]\n\n"a\\q"=1\nconfig/name="x"\n')

    assert [entry.name for entry in config.entries] == [None, "application/config/name"]
    assert set(config.settings()) == {"application/config/name"}


def test_unquote_strips_a_quoted_literal():
    assert unquote('"res://main.tscn"') == "res://main.tscn"
    assert unquote("false") == "false"


def test_read_config_reports_a_file_it_cannot_read_as_none(tmp_path):
    assert read_config(tmp_path / "absent.godot") is None
    unreadable = tmp_path / "project.godot"
    unreadable.write_bytes(b"\xff\xfe\x00binary")
    assert read_config(unreadable) is None


def test_read_config_reads_a_file_from_disk(tmp_path):
    path = tmp_path / "project.godot"
    path.write_text(PROJECT, encoding="utf-8")

    config = read_config(path)

    assert isinstance(config, ConfigText)
    assert config.settings()["debug/file_logging/enable_file_logging"].value == "false"
