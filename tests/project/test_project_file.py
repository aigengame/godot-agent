"""S3: the shared ``ConfigFile``-text reader behind every ``project.godot`` read (#843).

``gda.project_file`` is the ONE reader three callers share — the #829 main-scene
precondition, the harness installer's ``[autoload]`` edit, and the bounded project
write. These tests pin the format rules it owns: comments, sections, section-less
keys, multi-line values, escaped key spellings, and the byte-faithful round trip an
edit relies on.

They exercise it through the interface its callers have — the readers, the bounded
write and what they answer with. The line primitives are private (#930), so a rule
they used to be asked about directly is asked of the text it applies to.
"""

import pytest

from gda.project_file import (
    SECTIONLESS,
    ConfigText,
    ProjectFileChangedError,
    ProjectFileRestoreError,
    ProjectWriteMutation,
    bound_project_write,
    read_config,
    read_config_text,
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


def test_a_comment_ends_a_line_only_outside_quotes():
    config = read_config_text('a="x" ; note\nb="x ; y"\n')

    settings = config.settings()
    assert settings["a"].value == '"x"'  # the comment is not part of the value
    assert settings["b"].value == '"x ; y"'  # a quoted `;` is not a comment


def test_a_header_line_opens_a_section_and_an_assignment_does_not():
    config = read_config_text("[application]\nconfig/name=1\n")

    assert [(header.index, header.name) for header in config.headers] == [
        (0, "application")
    ]
    assert [entry.name for entry in config.entries] == ["application/config/name"]


def test_an_entry_is_named_by_the_key_the_engine_reads():
    # property_name_encode() quotes and escapes a key holding '=' or non-ASCII, so
    # the two spellings of one key have to compare equal. VariantParser::get_token
    # reads SIX hex digits after \U and four after \u, and gives every other escape
    # the character it precedes (`default: res = next`) — there is no \a or \v in
    # that switch. Demanding eight digits made a valid declaration unnameable, so
    # the save dropped it and gda reported nothing (PR #898 review, round 3).
    config = read_config_text(
        "config/name=1\n"
        '"run/\\u006dain_scene"=1\n'
        '"a=b"=1\n'
        '"\\U000066ile_logging/enable_file_logging"=1\n'
        '"a\\q"=1\n'
        '"\\a\\v"=1\n'
        '"\\ud83d\\ude00"=1\n'  # a UTF-16 pair, combined as the tokenizer combines it
    )

    assert [entry.name for entry in config.entries] == [
        "config/name",
        "run/main_scene",
        "a=b",
        "file_logging/enable_file_logging",
        "aq",
        "av",
        "\U0001f600",
    ]


def test_a_bare_key_drops_what_a_bare_key_cannot_hold():
    # parse_tag_assign_eof accumulates ONLY characters of code > 32 into a bare
    # key, so `foo bar` IS `foobar` to the engine. Keeping the space made gda read
    # one declaration as a second setting, and the restore then re-declared the
    # old value under the name a `project set` had just written (PR #898 review,
    # round 3).
    config = read_config_text("foo bar=1\ndebug/foo\tbar baz=1\n")

    assert [entry.name for entry in config.entries] == ["foobar", "debug/foobarbaz"]


def test_a_commented_header_is_a_section_and_a_quoted_semicolon_is_not_a_comment():
    # The reduction every boundary is decided on: the comment goes and the
    # surrounding whitespace with it, so a header written `[autoload] ; note` IS
    # the autoload section — a second reducer that skipped the comment made the
    # harness installer miss one (PR #898 review, round 3).
    config = read_config_text('  [autoload] ; note  \na="x ; y" \n')

    assert [(header.index, header.name) for header in config.headers] == [
        (0, "autoload")
    ]
    assert config.settings()["autoload/a"].value == '"x ; y"'


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


# A description whose value is a literal multi-line string, with a line inside it
# that is spelled exactly like a section header. Godot writes it back this way —
# `String::c_escape_multiline` escapes only `\` and `"`, so the newlines stay
# literal — and its parser reads the `[debug]` as three characters of the string.
MULTILINE = """\
config_version=5

[application]

config/description="line one
[debug]
line three"
config/name="old"

[debug]

file_logging/enable_file_logging=false
"""


def test_a_header_spelling_inside_a_quoted_value_is_not_a_section():
    # The scan carries the quote state across lines, so the value continues and
    # `[debug]` inside it opens nothing. Reading it as a header put `config/name`
    # in the wrong section, and the restore then wrote the setting's OLD value
    # back UNDER a `project set` that had just changed it (PR #898 review, round
    # 3): a successful command whose value read back stale.
    config = read_config_text(MULTILINE)

    assert config.sections == ("application", "debug")
    assert [header.index for header in config.headers] == [2, 9]
    settings = config.settings()
    assert settings["application/config/name"].value == '"old"'
    assert settings["application/config/description"].lines == (
        'config/description="line one',
        "[debug]",
        'line three"',
    )
    # The string's own newlines and spacing survive into the compared text.
    assert settings["application/config/description"].value == (
        '"line one\n[debug]\nline three"'
    )


def test_a_quoted_string_carries_its_state_over_a_bracket_and_a_comment():
    # Inside an open string a `;` is not a comment and a bracket does not count;
    # outside one, both do. One scan decides all of it.
    config = read_config_text('a="; not a comment {\nstill}" ; a comment\nb=2\n')

    settings = config.settings()
    assert settings["a"].value == '"; not a comment {\nstill}"'
    assert settings["a"].lines == ('a="; not a comment {', 'still}" ; a comment')
    assert settings["b"].value == "2"


def test_an_entry_after_a_multi_line_string_is_read_in_its_real_section():
    config = read_config_text(MULTILINE)

    assert (
        config.settings()["debug/file_logging/enable_file_logging"].section == "debug"
    )
    assert "debug/config/name" not in config.settings()


def test_text_round_trips_the_input_byte_for_byte():
    # The byte-order mark included: the engine glues it to the first key, so the
    # scan keeps it out of the KEYS it names — but the bytes are the file's, and
    # every writer built on this spells them back (#930).
    for text in (PROJECT, PROJECT.replace("\n", "\r\n"), "﻿" + PROJECT, "a=1", ""):
        assert read_config_text(text).text() == text


def test_an_entry_knows_the_line_it_starts_on():
    # The span an edit replaces or removes: `lines[index : index + len(lines)]` of
    # the scanned text IS the entry as it was written, multi-line values included.
    config = read_config_text(MULTILINE)

    for entry in config.entries:
        span = config.lines[entry.index : entry.index + len(entry.lines)]
        assert span == entry.lines
    assert config.settings()["application/config/description"].index == 4


def test_sections_named_bounds_every_part_the_scan_found():
    # A name can be opened more than once, and a caller that edits the section has
    # to see all of them — the harness installer's `[autoload]` edit does.
    config = read_config_text(
        'config_version=5\n\n[autoload]\n\nOne="*res://one.gd"\n'
        "\n[application]\n\n"
        'config/description="line one\n[autoload]\nline three"\n'
        '\n[autoload]\n\nTwo="*res://two.gd"\n'
    )

    autoloads = config.sections_named("autoload")

    assert [(section.header, section.start, section.end) for section in autoloads] == [
        (2, 3, 6),
        (12, 13, 15),
    ]
    # The `[autoload]` spelled inside the description opens nothing, so the
    # section it appears to start is not one of these — and the entries are the
    # scan's, each under the header that really holds it.
    assert [[entry.name for entry in section.entries] for section in autoloads] == [
        ["autoload/One"],
        ["autoload/Two"],
    ]


def test_the_section_less_head_is_always_one_section():
    # It is the file's beginning, so it exists even when nothing is written there.
    for text, end in ((PROJECT, 3), ("[application]\n", 0), ("a=1\n", 1)):
        head = read_config_text(text).sections_named(SECTIONLESS)
        assert len(head) == 1
        assert (head[0].header, head[0].start, head[0].end) == (None, 0, end)
    assert read_config_text(PROJECT).sections_named("nowhere") == ()


def test_settings_keeps_the_last_assignment_of_a_repeated_key():
    # ConfigFile lets the last assignment win; a reader that kept the first would
    # disagree with the engine about what the file says.
    config = read_config_text('[application]\n\nconfig/name="a"\nconfig/name="b"\n')

    assert config.settings()["application/config/name"].value == '"b"'


def test_an_undecodable_key_is_scanned_but_never_named():
    # A key gda cannot name is excluded from every comparison rather than guessed
    # at — a key wrongly read as two keys is how a restore writes a duplicate line.
    # These are the spellings the engine's own tokenizer refuses the FILE for.
    config = read_config_text(
        "[application]\n\n"
        '"a\\u00"=1\n'  # truncated hex sequence
        '"a\\uzzzz"=1\n'  # not hex at all
        '"a\\ud800"=1\n'  # unpaired lead surrogate
        '"a\\udc00"=1\n'  # unpaired trail surrogate
        "a\\b=1\n"  # a backslash in a bare key
        'config/name="x"\n'
    )

    assert [entry.name for entry in config.entries] == [
        *[None] * 5,
        "application/config/name",
    ]
    assert set(config.settings()) == {"application/config/name"}


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
    # The engine's own output is still there in full: the restore stages its text
    # in a sibling file and commits with one replace, so a refused write truncates
    # nothing (PR #898 review, round 3).
    assert path.read_text(encoding="utf-8") == after
    assert list(tmp_path.iterdir()) == [path]


def test_an_unreadable_file_on_either_side_measures_nothing(tmp_path):
    path = tmp_path / "project.godot"
    path.write_text('[application]\n\nconfig/name="x"\n', encoding="utf-8")
    config = read_config(path)
    path.write_bytes(b"\xff\xfe\x00binary")

    assert bound_project_write(path, config, addressed=None) == ProjectWriteMutation()
    assert bound_project_write(path, None, addressed=None) == ProjectWriteMutation()
    # And nothing was written over the file it could not read.
    assert path.read_bytes() == b"\xff\xfe\x00binary"


def test_a_restore_lands_in_the_section_the_scan_recorded(tmp_path):
    # The engine writes a multi-line string back with its newlines literal, so its
    # own output can carry a `[debug]` line INSIDE a value. The restore asks the
    # scan where `[debug]` is, not the raw lines: rescanning found the spelling in
    # the string first and wrote the dropped declaration into the middle of the
    # description (PR #898 review, round 3).
    before = (
        "config_version=5\n\n[application]\n\n"
        'config/description="line one\n[debug]\nline three"\n'
        'config/name="old"\n'
        "\n[debug]\n\nfile_logging/enable_file_logging=false\n"
        "file_logging/enable_file_logging.pc=false\n"
    )
    after = (
        "config_version=5\n\n[application]\n\n"
        'config/description="line one\n[debug]\nline three"\n'
        'config/name="renamed"\n'
        "\n[debug]\n\nfile_logging/enable_file_logging.pc=false\n"
    )

    mutation, path = _write(
        tmp_path, before, after, addressed="application/config/name"
    )

    assert mutation.restored == ("debug/file_logging/enable_file_logging",)
    restored = read_config_text(path.read_text(encoding="utf-8"))
    settings = restored.settings()
    assert settings["debug/file_logging/enable_file_logging"].section == "debug"
    # The value the restore was not asked about is byte-identical, so nothing was
    # written into the string that only looks like a section.
    assert settings["application/config/description"].value == (
        '"line one\n[debug]\nline three"'
    )
    assert settings["application/config/name"].value == '"renamed"'


def test_a_file_that_changed_under_gda_refuses_the_restore(tmp_path, monkeypatch):
    # ADR-0018 Decision 4 on the CLI side: the engine's write has landed and the
    # restore is a read-modify-write of ITS output, so a file that moved in that
    # window is left to whoever moved it. The seam here stands in for a concurrent
    # editor — the window is sub-millisecond, so a test cannot race one into it.
    from gda import project_file

    before = '[application]\n\nconfig/name="fixture"\n\n[debug]\n\nsettings/x=1\n'
    after = '[application]\n\nconfig/name="renamed"\n'
    external = '[application]\n\nconfig/name="written by someone else"\n'
    path = tmp_path / "project.godot"
    path.write_text(before, encoding="utf-8")
    config = read_config(path)
    path.write_text(after, encoding="utf-8")

    restore_text = project_file._restored

    def land_an_external_edit(scanned, dropped):
        text = restore_text(scanned, dropped)
        path.write_text(external, encoding="utf-8")
        return text

    monkeypatch.setattr(project_file, "_restored", land_an_external_edit)

    with pytest.raises(ProjectFileChangedError) as raised:
        bound_project_write(path, config, addressed="application/config/name")

    # The external edit is intact, and the refusal names what is NOT restored.
    assert path.read_text(encoding="utf-8") == external
    assert raised.value.settings == ("debug/settings/x",)
    assert "debug/settings/x" in str(raised.value)
    assert "stands" in str(raised.value)  # the engine's write is not undone
    # And the staged text left no residue beside project.godot.
    assert list(tmp_path.iterdir()) == [path]


def test_a_restore_replaces_the_file_in_one_step(tmp_path):
    # The committed file is exactly the restored text — one os.replace, never a
    # truncate-then-write a reader could observe half of.
    before = '[application]\n\nconfig/name="fixture"\n\n[debug]\n\nsettings/x=1\n'
    after = '[application]\n\nconfig/name="renamed"\n'

    mutation, path = _write(
        tmp_path, before, after, addressed="application/config/name"
    )

    assert mutation.restored == ("debug/settings/x",)
    assert list(tmp_path.iterdir()) == [path]
    assert path.read_text(encoding="utf-8").endswith("settings/x=1\n")
