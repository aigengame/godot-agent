"""S3: the shared ``ConfigFile``-text reader behind every ``project.godot`` read (#843).

``gda.project_file`` is the ONE reader three callers share — the #829 main-scene
precondition, the harness installer's ``[autoload]`` edit, and the bounded project
write. These tests pin the format rules it owns: comments, sections, section-less
keys, multi-line values, escaped key spellings, and the byte-faithful round trip an
edit relies on.
"""

import pytest

from gda.project_file import (
    SECTIONLESS,
    ConfigText,
    ProjectFileRestoreError,
    ProjectWriteMutation,
    bound_project_write,
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


# --- bound_project_write: the restore and what it reports (#843, PR #898) -----


def _write(tmp_path, before: str, after: str, *, addressed: str | None = None):
    """Apply ``after`` as the engine's save over ``before``, then bound the write."""
    path = tmp_path / "project.godot"
    path.write_text(before, encoding="utf-8")
    config = read_config(path)
    path.write_text(after, encoding="utf-8")
    return bound_project_write(path, config, addressed=addressed), path


def test_a_section_the_save_emptied_away_is_re_opened_and_the_reorder_reported(
    tmp_path,
):
    # The section's ONLY key is default-equal, so the engine drops the section
    # with it and the restore has to re-open it — the missing-section branch. The
    # file gda leaves therefore has `[debug]` LAST where it was first, which is
    # what `sections_reordered` must be measured against: the engine's
    # intermediate file no longer holds the section at all, so comparing to that
    # would report no reorder for a file whose order plainly changed.
    before = (
        "[debug]\n\nfile_logging/enable_file_logging=false\n"
        '\n[application]\n\nconfig/name="fixture"\n'
    )
    after = '[application]\n\nconfig/name="renamed"\n'

    mutation, path = _write(
        tmp_path, before, after, addressed="application/config/name"
    )

    assert mutation.restored == ("debug/file_logging/enable_file_logging",)
    assert mutation.sections_reordered is True
    text = path.read_text(encoding="utf-8")
    assert "[debug]" in text and "file_logging/enable_file_logging=false" in text
    assert text.index("[application]") < text.index("[debug]")
    # The re-opened section is a section, not a stray key: it reads back as one.
    assert (
        read_config_text(text)
        .settings()["debug/file_logging/enable_file_logging"]
        .section
        == "debug"
    )


def test_a_section_only_one_file_holds_is_not_a_reorder(tmp_path):
    # The shared-section rule: `[audio]` exists only after the save, so it cannot
    # be out of order with respect to anything. Counting it would make every write
    # that adds a section report a reorder.
    before = '[application]\n\nconfig/name="fixture"\n\n[debug]\n\nsettings/x=1\n'
    after = (
        '[application]\n\nconfig/name="renamed"\n'
        "\n[audio]\n\nbuses/x=1\n"
        "\n[debug]\n\nsettings/x=1\n"
    )

    mutation, _ = _write(tmp_path, before, after, addressed="application/config/name")

    assert mutation.added == ("audio/buses/x",)
    assert mutation.sections_reordered is False


def test_a_reordering_the_save_made_is_reported(tmp_path):
    before = '[zsection]\n\nmy/custom=42\n\n[application]\n\nconfig/name="fixture"\n'
    after = '[application]\n\nconfig/name="renamed"\n\n[zsection]\n\nmy/custom=42\n'

    mutation, _ = _write(tmp_path, before, after, addressed="application/config/name")

    assert mutation.sections_reordered is True
    assert mutation.restored == ()


def test_a_leading_byte_order_mark_is_not_part_of_the_first_key(tmp_path):
    # Godot's ConfigFile reader does not strip a BOM, so the engine reads the
    # marked key as its own setting and writes that mangled name back BESIDE the
    # `config_version` its writer always emits. Reading the mark as part of the
    # key would make gda believe `config_version` was dropped and "restore" a
    # second one (PR #898 review).
    before = "﻿config_version=5\n\n[debug]\n\nfile_logging/enable_file_logging=false\n"
    after = (
        "config_version=5\n"
        '"ï»¿config_version"=5\n'
        '\n[application]\n\nconfig/name="renamed"\n'
    )

    mutation, path = _write(
        tmp_path, before, after, addressed="application/config/name"
    )

    assert mutation.restored == ("debug/file_logging/enable_file_logging",)
    text = path.read_text(encoding="utf-8")
    # One real declaration, the engine's own — gda added no second one.
    assert text.count("config_version=5") == 1
    # The key the engine mangled is its doing and is reported as such, not hidden.
    assert "ï»¿config_version" in mutation.added


def test_a_restore_that_cannot_be_written_is_raised_as_a_typed_error(tmp_path):
    before = '[application]\n\nconfig/name="fixture"\n\n[debug]\n\nsettings/x=1\n'
    after = '[application]\n\nconfig/name="renamed"\n'
    path = tmp_path / "project.godot"
    path.write_text(before, encoding="utf-8")
    config = read_config(path)
    path.write_text(after, encoding="utf-8")
    path.chmod(0o444)
    tmp_path.chmod(0o555)  # and the directory, so a replace cannot work around it

    try:
        with pytest.raises(ProjectFileRestoreError) as raised:
            bound_project_write(path, config, addressed="application/config/name")
    finally:
        tmp_path.chmod(0o755)
        path.chmod(0o644)

    # The message names the file and what is now missing from it, so the failure
    # the CLI mints from this is actionable by hand.
    assert raised.value.settings == ("debug/settings/x",)
    assert "debug/settings/x" in str(raised.value)
    assert str(path) in str(raised.value)


def test_an_unreadable_file_on_either_side_measures_nothing(tmp_path):
    path = tmp_path / "project.godot"
    path.write_text('[application]\n\nconfig/name="x"\n', encoding="utf-8")
    config = read_config(path)
    path.write_bytes(b"\xff\xfe\x00binary")

    assert bound_project_write(path, config, addressed=None) == ProjectWriteMutation()
    assert bound_project_write(path, None, addressed=None) == ProjectWriteMutation()
    # And nothing was written over the file it could not read.
    assert path.read_bytes() == b"\xff\xfe\x00binary"
