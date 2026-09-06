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
the line primitives (:func:`split_config`, :func:`strip_comment`,
:func:`section_name`, …) plus the entry scan (:func:`read_config_text`) that
turns a text into its ``section``/``key``/``value`` assignments — each carrying
the RAW lines it spans, so a caller can put an entry back exactly as it was
written.

It is a READER of the format, not a parser of Godot values: an entry's ``value``
is the literal text, never a decoded Variant. Decoding is the engine's job and
gda has no business re-implementing ``VariantParser``; every consumer here either
compares value TEXT or hands the line back verbatim.

**Multi-line values.** ``ConfigFile`` values may span lines — an ``input/<action>``
entry is a ``Dictionary`` the engine writes across several. The scan tracks
bracket depth outside quotes, so such an entry is ONE entry rather than a key
followed by fragments that look like nothing at all.

**Undecodable keys.** A key may be quoted and escaped
(``String::property_name_encode``). :func:`config_key` decodes the escapes it
knows and returns ``None`` for anything else, and an entry gda cannot name is
excluded from every comparison — a key wrongly believed to be two different keys
is how a "restore" would write a second, duplicate line for a setting that is
already there.
"""

from dataclasses import dataclass
from pathlib import Path

# The engine's comment character, and the file's own bracket pairs. A ``;``
# outside quotes starts a comment (Godot's ``VariantParser`` tokenizer); the
# brackets are what makes a value span lines.
_COMMENT = ";"
_OPENING = "([{"
_CLOSING = ")]}"

# The escapes ``String::c_escape_multiline`` emits, decoded back. ``\\uXXXX`` is
# handled separately (it carries digits); anything not listed here makes a key
# undecodable rather than silently mis-decoded.
_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "'": "'",
    '"': '"',
    "\\": "\\",
    "/": "/",
}

# The name of the file's leading, SECTION-LESS keys (``config_version``). Godot
# writes them before the first ``[section]`` header and addresses them by their
# bare name, so gda names them the same way.
SECTIONLESS = ""


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


def strip_comment(line: str) -> str:
    """``line`` up to a ``;`` comment outside double quotes (Godot's comment char)."""
    quoted = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == _COMMENT and not quoted:
            return line[:index]
    return line


def is_section_header(stripped: str) -> bool:
    """Whether a stripped config line is an INI section header (``[name]``)."""
    return stripped.startswith("[") and stripped.endswith("]")


def section_name(line: str) -> str | None:
    """The section a ``[name]`` line opens, or ``None`` for any other line."""
    if is_section_header(line):
        return line[1:-1].strip()
    return None


def section_of(stripped: str, current: str) -> str:
    """The active section after a stripped line, or ``current`` if unchanged."""
    opened = section_name(stripped)
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
    every other key bare. This decodes the quoted form back so the two spellings
    of one key compare equal, and refuses — ``None`` — a token it cannot decode
    with certainty rather than guessing at a name.
    """
    token = token.strip()
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        return _unescape(token[1:-1])
    if '"' in token or "\\" in token:
        return None
    return token


def _unescape(body: str) -> str | None:
    """``body`` with its C escapes decoded, or ``None`` on one gda does not know."""
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(body):
            return None
        marker = body[index]
        index += 1
        if marker in _ESCAPES:
            out.append(_ESCAPES[marker])
            continue
        if marker in ("u", "U"):
            width = 4 if marker == "u" else 8
            digits = body[index : index + width]
            if len(digits) != width:
                return None
            try:
                out.append(chr(int(digits, 16)))
            except ValueError:
                return None
            index += width
            continue
        return None
    return "".join(out)


def _assignment(stripped: str) -> tuple[str, str] | None:
    """``stripped`` split at its assignment ``=``, or ``None`` when it has none.

    The first ``=`` OUTSIDE quotes separates key from value, so a quoted key that
    itself holds one (``"a=b"=1``) is not cut in half.
    """
    quoted = False
    escaped = False
    for index, char in enumerate(stripped):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "=" and not quoted:
            return stripped[:index], stripped[index + 1 :]
    return None


def _depth(text: str) -> int:
    """The net bracket depth ``text`` opens (positive) or closes (negative)."""
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif char in _OPENING:
            depth += 1
        elif char in _CLOSING:
            depth -= 1
    return depth


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
    order: the entry as it was WRITTEN, which is what a restore puts back.
    ``value`` is the value text with comments stripped and the lines of a
    multi-line value joined, for comparing two spellings of the same assignment
    — never a decoded Variant (this module parses no Godot values).
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
    it did not touch. ``sections`` names the sections in FILE order (the
    section-less head is not one of them), and ``entries`` the assignments in
    file order.
    """

    lines: tuple[str, ...]
    eol: str
    trailing: str
    sections: tuple[str, ...]
    entries: tuple[ConfigEntry, ...]

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
    """Scan a ``ConfigFile`` text into its sections and assignments."""
    lines, eol, trailing = split_config(text)
    sections: list[str] = []
    entries: list[ConfigEntry] = []
    section = SECTIONLESS
    index = 0
    while index < len(lines):
        stripped = strip_comment(lines[index]).strip()
        opened = section_name(stripped)
        if opened is not None:
            section = opened
            if section not in sections:
                sections.append(section)
            index += 1
            continue
        assignment = _assignment(stripped) if stripped else None
        if assignment is None:
            index += 1
            continue
        key_token, head = assignment
        start = index
        value = [head.strip()]
        depth = _depth(head)
        while depth > 0 and index + 1 < len(lines):
            index += 1
            part = strip_comment(lines[index])
            value.append(part.strip())
            depth += _depth(part)
        key = config_key(key_token)
        entries.append(
            ConfigEntry(
                section=section,
                name=None
                if key is None
                else (key if section == SECTIONLESS else f"{section}/{key}"),
                key_token=key_token.strip(),
                lines=tuple(lines[start : index + 1]),
                value="".join(value),
            )
        )
        index += 1
    return ConfigText(
        lines=tuple(lines),
        eol=eol,
        trailing=trailing,
        sections=tuple(sections),
        entries=tuple(entries),
    )


def read_config(path: Path) -> ConfigText | None:
    """Read and scan a config file, or ``None`` when it cannot be read.

    Newline translation is OFF so a CRLF file stays CRLF (#654). A file gda
    cannot read or decode yields ``None``: that is not a verdict about its
    contents, and every caller here treats it as "gda has nothing to say".
    """
    try:
        return read_config_text(path.read_text(encoding="utf-8", newline=""))
    except (OSError, UnicodeDecodeError):
        return None


# --- Bounding what a ``ProjectSettings.save()`` did to the file (#843) ---------


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
    if dropped:
        text = _restored(after, [entry for _, entry in dropped])
        path.write_text(text, encoding="utf-8", newline="")
    return ProjectWriteMutation(
        added=added,
        rewritten=rewritten,
        restored=tuple(name for name, _ in dropped),
        sections_reordered=_reordered(before.sections, after.sections),
    )


def _reordered(before: tuple[str, ...], after: tuple[str, ...]) -> bool:
    """Whether the sections BOTH files hold appear in a different order.

    Restricted to the shared sections on purpose: a section the save added (or
    one it emptied away) is a different fact from the file's order changing, and
    conflating them would report a reorder for every write that adds one.
    """
    shared = set(before) & set(after)
    return [name for name in before if name in shared] != [
        name for name in after if name in shared
    ]


def _restored(after: ConfigText, dropped: list[ConfigEntry]) -> str:
    """``after``'s text with each dropped entry written back into its section."""
    lines = list(after.lines)
    for entry in dropped:
        lines = _insert(lines, entry)
    return after.eol.join(lines) + after.trailing


def _insert(lines: list[str], entry: ConfigEntry) -> list[str]:
    """``lines`` with ``entry`` restored at the end of the section it came from.

    A section the engine no longer writes is re-opened at the end of the file,
    with the blank separator its own writer puts between two sections. The
    section-less head always exists (it is the file's beginning), so only a named
    section can be missing.
    """
    span = _section_span(lines, entry.section)
    if span is None:
        separator = [] if not lines or not lines[-1].strip() else [""]
        return [*lines, *separator, f"[{entry.section}]", "", *entry.lines]
    start, end = span
    while end > start and not lines[end - 1].strip():
        end -= 1
    return [*lines[:end], *entry.lines, *lines[end:]]


def _section_span(lines: list[str], section: str) -> tuple[int, int] | None:
    """The ``[start, end)`` line range of ``section``, or ``None`` when absent.

    The range covers the section's keys, not its header: for the section-less
    head it starts at line 0 and ends at the first header, so it is always found.
    """
    start: int | None = 0 if section == SECTIONLESS else None
    for index, raw in enumerate(lines):
        opened = section_name(strip_comment(raw).strip())
        if opened is None:
            continue
        if start is not None:
            return start, index
        if opened == section:
            start = index + 1
    return None if start is None else (start, len(lines))
