"""The ``project.godot`` TEXT: one reader for Godot's ``ConfigFile`` format (#843).

``ProjectSettings`` answers what a project *means*; this module answers what its
file *says* — which sections and keys are written there, on which lines, spelled
how. gda needs that second answer wherever it must act on the declarations a
human or a tool wrote rather than on the engine's merged view of them:

- the main-scene precondition for a live session launch (:mod:`gda.project`,
  #829) reads two settings out of the file before any engine exists;
- the harness installer (:mod:`gda.harness.install`) edits the ``[autoload]``
  section as TEXT, so an install/uninstall pair leaves the file byte-identical;
- a project write (``gda project set`` and its four siblings) compares the file
  before and after ``ProjectSettings.save()``, because that save reserializes the
  whole file: it DROPS every explicit line whose value equals the engine's
  initial value (``ProjectSettings::save_custom``: ``if (v->variant ==
  v->initial) continue;``), adds or rewrites ``application/config/features``, and
  writes the sections in its own (alphabetical) order.

Those three grew three partial readers. This module is the one they share (#843):
the line primitives (:func:`split_config`, :func:`config_line`,
:func:`section_name`, …) plus the entry scan (:func:`read_config_text`) that
turns a text into its ``section``/``key``/``value`` assignments — each carrying
the RAW lines it spans, so a caller can put an entry back exactly as it was
written.

It is a READER of the format, not a parser of Godot values: an entry's ``value``
is the literal text, never a decoded Variant. Decoding is the engine's job and
gda has no business re-implementing ``VariantParser``; every consumer here either
compares value TEXT or hands the line back verbatim.

**One lexical scan owns every boundary.** ``ConfigFile`` values may span lines: an
``input/<action>`` entry is a ``Dictionary`` the engine writes across several, and
a quoted string may hold a LITERAL newline (``VariantParser::get_token`` just
counts the line and reads on). :func:`_scan_line` carries the quote, escape and
bracket state from one line to the next, so a value continues while a string is
open or a bracket is unclosed, and a ``[looks_like_a_header]`` line INSIDE a
quoted value is not a section. :func:`read_config_text` records what that one scan
found — every section header's line index (:class:`ConfigHeader`) and every
entry's lines — and the restore below consumes those recordings rather than
rescanning the raw text. A SECOND recognizer without the same state is the defect
this replaces: a ``[debug]`` inside a description made the restore write a dropped
line into the wrong section, and a successful ``project set`` then read back its
OLD value (PR #898 review, round 3).

**Key spellings.** :func:`config_key` mirrors the engine on both forms a key can
take. Quoted (``String::property_name_encode``), it is decoded exactly as
``VariantParser``'s string tokenizer decodes it — ``\\uXXXX`` four hex digits,
``\\UXXXXXX`` SIX, every other escape standing for the character it precedes.
Bare, every character of code 32 or less is DROPPED, because
``parse_tag_assign_eof`` accumulates only ``c > 32``: the engine reads
``foo bar=1`` as the key ``foobar``. gda still returns ``None`` for a spelling it
cannot decode with certainty, and an entry gda cannot name is excluded from every
comparison — a key wrongly believed to be two different keys is how a "restore"
writes a second, duplicate line for a setting that is already there.
"""

import os
from dataclasses import dataclass, replace
from pathlib import Path

# The engine's comment character, and the file's own bracket pairs. A ``;``
# outside quotes starts a comment (Godot's ``VariantParser`` tokenizer); the
# brackets, and an open quoted string, are what makes a value span lines.
_COMMENT = ";"
_OPENING = "([{"
_CLOSING = ")]}"

# The escapes ``VariantParser::get_token`` gives a meaning of their own inside a
# quoted string. Everything else — ``\\'``, ``\\"``, ``\\\\``, ``\\/`` and any
# unknown letter — falls to the engine's ``default: res = next``, which is the
# character itself; ``\\u`` and ``\\U`` are handled separately (they carry digits).
# Note what is NOT here: the engine's tokenizer knows no ``\\a`` or ``\\v``, so
# those two mean a literal ``a`` and ``v`` (``String::c_unescape`` does know them,
# but ``ConfigFile`` does not go through it).
_ESCAPES = {
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "f": "\f",
    "r": "\r",
}

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

# The name of the file's leading, SECTION-LESS keys (``config_version``). Godot
# writes them before the first ``[section]`` header and addresses them by their
# bare name, so gda names them the same way.
SECTIONLESS = ""

# A byte-order mark on the first line. Godot's `ConfigFile` reader does not strip
# it, so the engine reads the file's first key WITH the mark glued to its name and
# writes that mangled key back beside the real one. gda drops it instead, so it
# agrees with the engine about the key the file DECLARES (`config_version`, not a
# marked spelling of it) and never "restores" a line that is already there
# (PR #898 review). The mark is dropped from the scanned text, so a `ConfigText`
# of a marked file does not rebuild it — see :meth:`ConfigText.text`.
_BOM = "\ufeff"


def line_ending(text: str) -> str:
    """The terminator the text's FIRST line uses (``\\r\\n`` or ``\\n``).

    Rejoining with it keeps a CRLF ``project.godot`` CRLF (#654). A file with
    mixed terminators normalizes to its first one — the documented limit of the
    harness installer's byte-identity guarantee.
    """
    index = text.find("\n")
    if index > 0 and text[index - 1] == "\r":
        return "\r\n"
    return "\n"


def split_config(text: str) -> tuple[list[str], str, str]:
    """A config text as (terminator-free lines, line ending, trailing terminator)."""
    eol = line_ending(text)
    return text.splitlines(), eol, eol if text.endswith(("\n", "\r")) else ""


@dataclass(frozen=True)
class _Scan:
    """The lexical state one config line hands to the next.

    ``quoted`` is a double-quoted string still open at the end of the line — the
    engine reads the newline as part of it — and ``depth`` the brackets still
    unclosed. Either one means the value is not finished. ``escaped`` never
    survives a line: a trailing backslash escapes the line's own terminator, so
    :func:`_scan_line` always returns it cleared.
    """

    quoted: bool = False
    escaped: bool = False
    depth: int = 0

    @property
    def open(self) -> bool:
        """Whether a value started on this line continues onto the next."""
        return self.quoted or self.depth > 0


@dataclass(frozen=True)
class _Lexed:
    """What one pass over a config line found: its content, its state, its ``=``.

    ``content`` is the line up to a ``;`` comment (the whole line when it has
    none), ``state`` what a following line inherits, and ``assign`` the index —
    into the line, not into ``content`` — of the first assignment ``=`` outside
    quotes, or ``None`` when the line makes no assignment.
    """

    content: str
    state: _Scan
    assign: int | None


def _scan_line(line: str, state: _Scan) -> _Lexed:
    """Read one config line as Godot's tokenizer would, continuing ``state``.

    The ONE character-level recognizer in this module: comments, quoted strings,
    escapes, brackets and the assignment ``=`` are all decided here, so nothing
    else has to keep (or forget) the same state. A ``;`` inside an open string is
    not a comment, a ``"`` inside a comment is never reached, and a bracket inside
    a string does not count.
    """
    quoted, escaped, depth = state.quoted, state.escaped, state.depth
    assign: int | None = None
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif char == _COMMENT:
            return _Lexed(line[:index], _Scan(False, False, depth), assign)
        elif char == "=" and assign is None:
            assign = index
        elif char in _OPENING:
            depth += 1
        elif char in _CLOSING:
            depth -= 1
    return _Lexed(line, _Scan(quoted, False, depth), assign)


def strip_comment(line: str) -> str:
    """``line`` up to a ``;`` comment outside double quotes (Godot's comment char)."""
    return _scan_line(line, _Scan()).content


def config_line(raw: str) -> str:
    """A RAW config line reduced to what Godot's parser reads on it.

    The comment gone and the surrounding whitespace trimmed. This is the one
    reduction every recognizer applies — here and in the harness installer, which
    consumes it per line — so a header written ``[autoload] ; note`` is the
    autoload section to all of them. Two reducers, one of which skipped the
    comment, is how an install appended a SECOND ``[autoload]`` section next to a
    commented one (PR #898 review, round 3).
    """
    return strip_comment(raw).strip()


def is_section_header(line: str) -> bool:
    """Whether a config line is an INI section header (``[name]``)."""
    reduced = config_line(line)
    return reduced.startswith("[") and reduced.endswith("]")


def section_name(line: str) -> str | None:
    """The section a ``[name]`` line opens, or ``None`` for any other line."""
    reduced = config_line(line)
    if is_section_header(reduced):
        return reduced[1:-1].strip()
    return None


def section_of(line: str, current: str) -> str:
    """The active section after a config line, or ``current`` if unchanged."""
    opened = section_name(line)
    return current if opened is None else opened


def unquote(token: str) -> str:
    """Strip surrounding quotes; this is not a ``ConfigFile`` escape decoder."""
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1].replace('\\"', '"')
    return token


def config_key(token: str) -> str | None:
    """The key ``token`` names, or ``None`` when gda cannot decode it.

    ``String::property_name_encode`` quotes and escapes a key holding ``=``,
    ``"``, ``;``, brackets or any non-printable/non-ASCII character, and leaves
    every other key bare. Both spellings are read the way the engine reads them,
    so the two spellings of one key compare equal:

    * quoted, the body is decoded by :func:`_unescape`, which mirrors
      ``VariantParser::get_token``;
    * bare, every character of code 32 or less is dropped, because
      ``parse_tag_assign_eof`` only appends ``c > 32`` to the key it is
      accumulating — ``foo bar`` IS ``foobar`` to the engine, and reading it as a
      different key made a restore re-declare the setting a ``project set`` had
      just written (PR #898 review, round 3).

    A token gda cannot decode with certainty is refused — ``None`` — rather than
    guessed at.
    """
    trimmed = token.strip()
    if len(trimmed) >= 2 and trimmed.startswith('"') and trimmed.endswith('"'):
        return _unescape(trimmed[1:-1])
    if '"' in token or "\\" in token:
        return None
    return "".join(char for char in token if ord(char) > 32)


def _unescape(body: str) -> str | None:
    """``body`` decoded as ``VariantParser::get_token`` decodes a quoted string.

    ``None`` where the engine's tokenizer would REFUSE the file — a truncated or
    non-hex ``\\u``/``\\U`` sequence, an unpaired UTF-16 surrogate, a code point
    outside Unicode — because a key gda cannot name with certainty is better left
    unnamed than guessed at.
    """
    out: list[str] = []
    pending = 0  # a lead surrogate waiting for its trail, as the engine's `prev`
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            if pending:
                return None
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(body):
            return None
        marker = body[index]
        index += 1
        if marker in ("u", "U"):
            # The engine reads FOUR hex digits after \u and SIX after \U
            # (`hex_len = (next == 'U') ? 6 : 4`); demanding eight made a valid
            # declaration unnameable, and the save then dropped it in silence
            # (PR #898 review, round 3).
            width = 4 if marker == "u" else 6
            digits = body[index : index + width]
            if len(digits) != width or not all(d in _HEX_DIGITS for d in digits):
                return None
            index += width
            code = int(digits, 16)
        else:
            code = ord(_ESCAPES.get(marker, marker))
        if 0xD800 <= code <= 0xDBFF:
            if pending:
                return None
            pending = code
            continue
        if 0xDC00 <= code <= 0xDFFF:
            if not pending:
                return None
            code = ((pending - 0xD800) << 10) + (code - 0xDC00) + 0x10000
            pending = 0
        elif pending:
            return None
        try:
            out.append(chr(code))
        except ValueError:
            return None
    if pending:
        return None
    return "".join(out)


@dataclass(frozen=True)
class ConfigHeader:
    """One ``[name]`` section header, and the line it was found on.

    Recorded by the single scan in :func:`read_config_text` so the restore can ask
    where a section starts and ends without looking at the raw lines again — the
    raw lines cannot answer that question, because a header spelling inside a
    multi-line quoted value is not a header.
    """

    index: int
    name: str


@dataclass(frozen=True)
class ConfigEntry:
    """One ``key=value`` assignment in a ``ConfigFile`` text.

    ``section`` is the section that holds it (:data:`SECTIONLESS` for a key
    written before the first header) and ``name`` the full setting name gda
    reports it by — ``section/key``, or the bare key when section-less — or
    ``None`` when :func:`config_key` could not decode the spelling.
    ``key_token`` is that spelling, RAW, for a caller whose own rule reads it
    (the main-scene reader defers to the engine on any escaped key).

    ``lines`` are the raw lines the entry spans, terminator-free and in file
    order — the span the scan recorded, which is the entry as it was WRITTEN and
    what a restore puts back. ``value`` is the value text with comments stripped
    and the lines of a multi-line value joined, for comparing two spellings of the
    same assignment — never a decoded Variant (this module parses no Godot
    values). A line the value crossed while a quoted string was open keeps its
    newline and its spaces, because both are inside the string.
    """

    section: str
    name: str | None
    key_token: str
    lines: tuple[str, ...]
    value: str


@dataclass(frozen=True)
class ConfigText:
    """A ``ConfigFile`` text as gda reads it: its lines, its layout, its entries.

    ``lines`` / ``eol`` / ``trailing`` rebuild the exact input
    (``eol.join(lines) + trailing``), so an edit stays byte-faithful to the parts
    it did not touch — with one exception, a leading byte-order mark, which
    :data:`_BOM` explains and which no writer here can reintroduce (the only text
    this module writes back is the engine's own, which never carries one).
    ``headers`` are the section headers the scan found, with the line each sits
    on; ``sections`` names them in FILE order (the section-less head is not one of
    them), and ``entries`` holds the assignments in file order.

    ``token`` is the change token of the file this was read FROM — ``st_mtime_ns``
    and ``st_size``, taken from the same open handle — or ``None`` for a text that
    came from no file. It is what an optimistic write compares against before it
    replaces that file (ADR-0018 Decision 4).
    """

    lines: tuple[str, ...]
    eol: str
    trailing: str
    headers: tuple[ConfigHeader, ...]
    entries: tuple[ConfigEntry, ...]
    token: tuple[int, int] | None = None

    @property
    def sections(self) -> tuple[str, ...]:
        """The section names in file order, each once.

        Derived from :attr:`headers` rather than recorded beside it: one scan
        found them, and one list is what says where they are.
        """
        return tuple(dict.fromkeys(header.name for header in self.headers))

    def settings(self) -> dict[str, ConfigEntry]:
        """The named entries by setting name; a repeated key keeps the LAST one.

        ``ConfigFile`` lets the last assignment win, so a reader that kept the
        first would disagree with the engine about what the file says. Entries
        gda cannot name are left out entirely.
        """
        named: dict[str, ConfigEntry] = {}
        for entry in self.entries:
            if entry.name is not None:
                named[entry.name] = entry
        return named

    def text(self) -> str:
        """The text these lines spell."""
        return self.eol.join(self.lines) + self.trailing


def read_config_text(text: str) -> ConfigText:
    """Scan a ``ConfigFile`` text into its sections and assignments.

    ONE pass with ONE state (:func:`_scan_line`). A line is a section header, an
    assignment, or neither only while no value is open; once a line opens a quoted
    string or a bracket, the following lines belong to that value however they are
    spelled. An unterminated string therefore swallows the rest of the file into
    its entry — which is what the engine does too (it refuses to load the file at
    all), so gda has nothing truthful to say about such a text either.
    """
    lines, eol, trailing = split_config(text.removeprefix(_BOM))
    headers: list[ConfigHeader] = []
    entries: list[ConfigEntry] = []
    section = SECTIONLESS
    index = 0
    while index < len(lines):
        lexed = _scan_line(lines[index], _Scan())
        opened = section_name(lexed.content)
        if opened is not None:
            section = opened
            headers.append(ConfigHeader(index=index, name=opened))
            index += 1
            continue
        if lexed.assign is None:
            index += 1
            continue
        start = index
        key_token = lexed.content[: lexed.assign]
        head = lexed.content[lexed.assign + 1 :]
        state = _scan_line(head, _Scan()).state
        parts = [head.lstrip() if state.quoted else head.strip()]
        while state.open and index + 1 < len(lines):
            index += 1
            inside = state.quoted
            continued = _scan_line(lines[index], state)
            state = continued.state
            parts.append(_continuation(continued.content, inside, state.quoted))
        key = config_key(key_token)
        entries.append(
            ConfigEntry(
                section=section,
                name=None
                if key is None
                else (key if section == SECTIONLESS else f"{section}/{key}"),
                key_token=key_token.strip(),
                lines=tuple(lines[start : index + 1]),
                value="".join(parts),
            )
        )
        index += 1
    return ConfigText(
        lines=tuple(lines),
        eol=eol,
        trailing=trailing,
        headers=tuple(headers),
        entries=tuple(entries),
    )


def _continuation(content: str, inside: bool, still_inside: bool) -> str:
    """One continuation line's contribution to a multi-line value's text.

    Whitespace between the tokens of a ``Dictionary`` written across lines is
    insignificant and goes; whitespace INSIDE an open quoted string is part of the
    string and stays, newline included.
    """
    if inside:
        return "\n" + (content if still_inside else content.rstrip())
    return content.lstrip() if still_inside else content.strip()


def read_config(path: Path) -> ConfigText | None:
    """Read and scan a config file, or ``None`` when it cannot be read.

    Newline translation is OFF so a CRLF file stays CRLF (#654). The change token
    is taken from the SAME open handle the text came from, so it describes exactly
    the bytes that were scanned. A file gda cannot read or decode yields ``None``:
    that is not a verdict about its contents, and every caller here treats it as
    "gda has nothing to say".
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()
            info = os.fstat(handle.fileno())
    except (OSError, UnicodeDecodeError):
        return None
    return replace(read_config_text(text), token=(info.st_mtime_ns, info.st_size))


# --- Bounding what a ``ProjectSettings.save()`` did to the file (#843) ---------


class ProjectFileRestoreError(Exception):
    """The restored text could not be written back to ``project.godot`` (#843).

    Raised instead of letting the ``OSError`` escape as a traceback: the engine
    has already reserialized the file, so the caller must be able to turn this
    into a typed failure naming the declarations that are now gone. It carries no
    error taxonomy of its own — this module sits below ``gda.errors`` — only the
    facts the envelope is built from.
    """

    def __init__(self, path: Path, settings: tuple[str, ...], error: OSError) -> None:
        super().__init__(
            f"the engine reserialized {path} but gda could not write the "
            f"declarations it dropped back into it ({error}); "
            f"restore them by hand: {', '.join(settings)}"
        )
        self.path = path
        self.settings = settings
        self.error = error


class ProjectFileChangedError(Exception):
    """``project.godot`` moved under gda between the engine's save and the restore.

    The restore is a read-modify-write of the engine's own output, so it takes
    ADR-0018 Decision 4's optimistic check: the file is re-stat'd against the
    token recorded when that output was read, and a difference refuses the write
    instead of clobbering whatever landed there. The engine's write STANDS — it is
    already on disk and cannot be taken back — so the message says so and names
    the declarations that were not put back. Like its sibling above it carries no
    error taxonomy; ``gda.commands.project`` maps it to
    :term:`Gda error code` ``file_changed_externally``.
    """

    def __init__(self, path: Path, settings: tuple[str, ...]) -> None:
        super().__init__(
            f"the engine's write to {path} stands, but gda refused to restore the "
            f"declarations that save dropped: the file changed on disk after the "
            f"engine wrote it (a concurrent editor may have edited it). "
            f"NOT restored: {', '.join(settings)}"
        )
        self.path = path
        self.settings = settings


@dataclass(frozen=True)
class ProjectWriteMutation:
    """What the engine's save did to ``project.godot`` beyond the request (#843).

    ``added`` / ``rewritten`` are the settings the engine wrote that the caller
    never asked about (``application/config/features``, and ``config_version`` on
    a file that lacked it); ``restored`` the explicit lines it dropped —
    default-equal declarations — that gda put back verbatim.
    ``sections_reordered`` says the engine's own layout moved the sections the two
    files share. The addressed setting is in none of them: it is the request, not
    a residual mutation.
    """

    added: tuple[str, ...] = ()
    rewritten: tuple[str, ...] = ()
    restored: tuple[str, ...] = ()
    sections_reordered: bool = False


def bound_project_write(
    path: Path, before: ConfigText | None, *, addressed: str | None
) -> ProjectWriteMutation:
    """Restore what the save dropped, and report what it changed besides (#843).

    ``before`` is the file as it was read BEFORE the operation ran; this reads it
    again and compares. A dropped explicit line is the caller's own declaration —
    ``ProjectSettings.save()`` deletes it whenever its value equals the engine's
    initial value — so gda writes it back with the exact bytes it had, into the
    section it came from. Nothing else is put back: the engine owns the layout,
    and gda reports the reordering instead of fighting it.

    ``addressed`` names the setting the operation itself was about, and is
    excluded from every category — its appearance, disappearance or new value IS
    the request. It stays excluded when it is ``None`` (an operation that
    addresses no single setting).

    A file gda could not read on either side leaves the mutation empty and the
    file untouched: with nothing to compare against, a "restore" would be a guess.
    Raises :class:`ProjectFileRestoreError` when the restored text cannot be
    written and :class:`ProjectFileChangedError` when the file changed under gda
    since the engine wrote it — the one IO here that can fail after the engine has
    already changed the file.
    """
    after = read_config(path)
    if before is None or after is None:
        return ProjectWriteMutation()
    old = before.settings()
    new = after.settings()
    dropped = [
        (name, entry)
        for name, entry in old.items()
        if name != addressed and name not in new
    ]
    added = tuple(name for name in new if name != addressed and name not in old)
    rewritten = tuple(
        name
        for name, entry in new.items()
        if name != addressed and name in old and old[name].value != entry.value
    )
    restored = tuple(name for name, _ in dropped)
    # The order is asked of the file gda LEAVES, not of the engine's intermediate:
    # a section the save emptied away is re-opened by the restore, and only the
    # final text says where it ended up (PR #898 review).
    sections = after.sections
    if dropped:
        text = _restored(after, [entry for _, entry in dropped])
        sections = read_config_text(text).sections
        _replace_file(path, text, after.token, restored)
    return ProjectWriteMutation(
        added=added,
        rewritten=rewritten,
        restored=restored,
        sections_reordered=_reordered(before.sections, sections),
    )


def _reordered(before: tuple[str, ...], after: tuple[str, ...]) -> bool:
    """Whether the sections BOTH files hold appear in a different order.

    ``after`` is the FINAL file — the engine's output with the restore already
    applied — because that is the file the caller will read; measuring the
    engine's intermediate would report "not reordered" for a section the save
    emptied away and the restore then re-opened somewhere else (PR #898 review).

    Restricted to the shared sections on purpose: a section only one side has
    cannot be out of order with respect to the other, and counting it would
    report a reorder for every write that merely adds one
    (``application/config/features`` pulling in a section of its own, say).
    """
    shared = set(before) & set(after)
    return [name for name in before if name in shared] != [
        name for name in after if name in shared
    ]


def _restored(after: ConfigText, dropped: list[ConfigEntry]) -> str:
    """``after``'s text with each dropped entry written back into its section.

    Every position comes from the boundaries the scan RECORDED for ``after``
    (:attr:`ConfigText.headers`), computed before a single line moves, so the
    insertions cannot shift each other's targets and no line is read as a header
    twice. Entries whose section the save emptied away share one re-opened section
    at the end of the file.
    """
    inserted: dict[int, list[str]] = {}
    reopened: dict[str, list[str]] = {}
    for entry in dropped:
        end = _section_end(after, entry.section)
        if end is None:
            reopened.setdefault(entry.section, []).extend(entry.lines)
        else:
            inserted.setdefault(end, []).extend(entry.lines)
    lines: list[str] = []
    for index, raw in enumerate(after.lines):
        lines.extend(inserted.get(index, ()))
        lines.append(raw)
    lines.extend(inserted.get(len(after.lines), ()))
    for section, body in reopened.items():
        # The blank separator the engine's own writer puts between two sections.
        separator = [] if not lines or not lines[-1].strip() else [""]
        lines.extend([*separator, f"[{section}]", "", *body])
    return after.eol.join(lines) + after.trailing


def _section_end(config: ConfigText, section: str) -> int | None:
    """The line index a restored entry of ``section`` is inserted BEFORE.

    The end of the section's keys, with its trailing blank lines left below the
    restored entry. ``None`` says the text has no such section, and the caller
    re-opens one. The section-less head always exists (it is the file's
    beginning), so only a named section can be missing.
    """
    headers = config.headers
    if section == SECTIONLESS:
        start = 0
        end = headers[0].index if headers else len(config.lines)
    else:
        found = next(
            (at for at, header in enumerate(headers) if header.name == section), None
        )
        if found is None:
            return None
        start = headers[found].index + 1
        end = (
            headers[found + 1].index if found + 1 < len(headers) else len(config.lines)
        )
    while end > start and not config.lines[end - 1].strip():
        end -= 1
    return end


def _replace_file(
    path: Path, text: str, token: tuple[int, int] | None, settings: tuple[str, ...]
) -> None:
    """Put ``text`` in place of ``path`` atomically, refusing a file that moved.

    ADR-0018 Decision 4 on the CLI side of a headless write, the same guarantee
    ``operations.gd`` gives its own read-modify-write ops: the new text is staged
    in a sibling temporary file, the target is re-stat'd against ``token`` — the
    ``st_mtime_ns`` and ``st_size`` recorded when the engine's output was read —
    and only a match is committed, with a single ``os.replace``. A reader
    therefore sees the old file or the new one, never a truncated
    ``project.godot``, and a file some other writer touched in the meantime is
    left exactly as that writer left it. A text gda holds no token for is refused
    too: the restore goes onto the file it measured or onto none.
    """
    temp = path.with_name(f"{path.name}.gda-restore.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8", newline="")
        os.chmod(temp, os.stat(path).st_mode & 0o777)
    except OSError as error:
        _discard(temp)
        raise ProjectFileRestoreError(path, settings, error) from error
    if token is None or _change_token(path) != token:
        _discard(temp)
        raise ProjectFileChangedError(path, settings)
    try:
        os.replace(temp, path)
    except OSError as error:
        _discard(temp)
        raise ProjectFileRestoreError(path, settings, error) from error


def _change_token(path: Path) -> tuple[int, int] | None:
    """``path``'s (mtime, size) change token, or ``None`` when it cannot be read.

    The pair, not the mtime alone: a coarse filesystem clock can hide a same-tick
    edit that the size still shows — the reasoning ``operations.gd``'s own
    staleness guard is built on.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


def _discard(temp: Path) -> None:
    """Remove a staged file, leaving no residue beside ``project.godot``."""
    try:
        temp.unlink(missing_ok=True)
    except OSError:
        pass
