"""Classify Godot's script-error stderr lines into structured diagnostics (#651).

The single home of *what Godot's error stream says about a script*. It is the
read-side companion to :mod:`gda.engine_log`, which is the single home of *how
the engine formats an error line* (the two-line ``<TYPE>: <message>`` /
``   at: <function> (<file>:<line>)`` shape of ``core/io/logger.cpp``). This
module reuses that parser verbatim and adds the two things it does not do: decide
which of the engine's known script-failure sentences a record is, and resolve
which ``res://`` resource the sentence is about.

The split matters because the engine reports a failed script run **only** on
stderr — the process still exits ``0``. A missing entry script, a parse error in
the entry script, and a parse error in one of its dependencies all leave a clean
exit status behind (verified against Godot 4.6.3), so a channel that reads only
the exit code reports a phantom success (#651, dogfooding GDA-DF-007/GDA-DF-032).
:func:`entry_load_failure` turns the stderr evidence into that missing verdict.

Consumers (the reason this is a module and not a helper inside one command):

- ``gda script run`` (:mod:`gda.commands.script`) — the verdict plus the
  ``diagnostics`` it carries on its result;
- the ``script run`` timeout path (#655) — the same diagnostics from the partial
  stderr captured before the timeout;
- the scene-startup preflight (#664) — the same script errors from a scene launch.

Everything here is a **pure function of the stderr text**: no engine, no I/O.
Recognition is deliberately closed — only the sentences below are classified, so
``diagnostics`` stays a curated high-signal list rather than a re-encoding of the
whole error stream (the verbatim stream is preserved separately by each caller).
An unrecognized error or warning is skipped and never raises.

**Resource identity is canonical, on both sides of every comparison.** Godot
canonicalizes a ``res://`` path before reporting it, so an entry script invoked as
``res://dir/../bad.gd`` comes back named ``res://bad.gd``. Comparing the engine's
spelling against the caller's raw one silently missed the match and reported a
phantom success, so every ``path`` this module produces — and every path
:func:`entry_load_failure` compares against — is put through
:func:`canonical_res_path` first. Lexical only: no filesystem access, no symlink
resolution, so it stays a pure function.

The recognized sentences, verbatim from Godot 4.6.3::

    SCRIPT ERROR: Parse Error: <message>
              at: GDScript::reload (res://entry.gd:4)
    ERROR: Failed to load script "res://entry.gd" with error "Parse error".
    ERROR: Attempt to open script 'res://gone.gd' resulted in error 'File not found'.
    ERROR: Can't load script: res://gone.gd
    ERROR: Can't load the script "res://plain.gd" as it doesn't inherit from SceneTree or MainLoop.
    ERROR: Cannot open file 'res://missing.tres'.
    ERROR: Failed loading resource: res://missing.tres.
    ERROR: Script inherits from native type 'Resource', so it can't be assigned to an object of type 'Node2D'.
    ERROR: Cannot set object script. Parameter should be null or a reference to a valid script.
"""

import posixpath
import re
from collections.abc import Sequence
from enum import Enum

from pydantic import BaseModel, Field

from gda.engine_log import parse_errors

# The res:// scheme prefix. A diagnostic's ``path`` is only ever a res:// address:
# the engine's own ``at:`` frame for an engine-side error names a C++ source file
# (``modules/gdscript/gdscript.cpp``), which is gda-irrelevant noise.
_RES_PREFIX = "res://"

# The engine's ``SCRIPT ERROR:`` records carry the compile failure as a message
# prefixed ``Parse Error:``; every other SCRIPT ERROR is a runtime failure raised
# while the script was already executing.
_PARSE_ERROR_PREFIX = "Parse Error:"

# `ERROR: Attempt to open script '<path>' resulted in error '<reason>'.` — the
# engine could not even read the file. The reason distinguishes a missing script
# (the #651 defect) from any other open failure.
_OPEN_FAILED = re.compile(
    r"^Attempt to open script '(?P<path>[^']*)' resulted in error '(?P<reason>[^']*)'"
)
_FILE_NOT_FOUND = "File not found"

# `ERROR: Failed to load script "<path>" with error "<reason>".` — the file was
# read but the script did not compile (its own parse error, or an unresolvable
# dependency: the entry script is what the engine names either way).
_LOAD_FAILED = re.compile(
    r'^Failed to load script "(?P<path>[^"]*)" with error "(?P<reason>[^"]*)"'
)

# `ERROR: Can't load script: <path>` — main.cpp's `start()` giving up on the
# `--script` entry point (`main.cpp:4271`, `"Can't load script: " + script`, Godot
# 4.6.3). The engine concatenates the raw path with NO trailing period — unlike
# `_FAILED_LOADING_RESOURCE` below, this sentence carries no format-string
# punctuation to strip, so the capture now runs to end of line unconditionally.
# A `\.?$` strip here used to silently eat a genuine trailing dot off a
# dot-terminated path (`res://..` parsed back as `res://.`, #698). `.+` rather
# than `\S+`: a project-relative path MAY contain a space (`res://missing
# file.`), and `\S+` failed to match the line AT ALL for one — a pre-existing
# phantom success (present on `main` before #698 too, not introduced by the
# dot fix), which left NO diagnostic behind rather than a corrupted one, and
# was masked whenever the path also carried a recognized extension (that
# shape additionally gets `_OPEN_FAILED`'s quoted, space-safe capture).
# `engine_log` has already split stderr into lines before this regex ever
# sees one, so `.+` cannot run past the line it belongs to.
_CANT_LOAD = re.compile(r"^Can't load script: (?P<path>.+)$")

# `ERROR: Can't load the script "<path>" as it doesn't inherit from SceneTree or
# MainLoop.` — the script compiled fine but cannot BE the one-shot entry point.
_NOT_A_MAIN_LOOP = re.compile(
    r'^Can\'t load the script "(?P<path>[^"]*)" as it doesn\'t inherit from '
    r"SceneTree or MainLoop"
)

# `ERROR: Script inherits from native type '<base>', so it can't be assigned to an
# object of type '<target>'.` — the engine refusing to BIND a compiled script to a
# node whose native class is outside the script's base (gdscript.cpp
# instance_create). Deterministic and high-signal: the node boots silently
# script-less, so its `_ready` never runs (the PR #720 review's preflight false
# positive). The sentence names no res:// path — the `at:` frame is the engine's
# own C++ file — so the diagnostic honestly carries none. Distinct from the #722
# `push_error` question: this is the engine's own refusal with a fixed shape, not
# an arbitrary project-authored message.
_INCOMPATIBLE_BINDING = re.compile(
    r"^Script inherits from native type '(?P<base>[^']*)', so it can't be "
    r"assigned to an object of type '(?P<target>[^']*)'"
)

# `ERROR: Cannot set object script. Parameter should be null or a reference to a
# valid script.` — the engine's OTHER bind-time refusal (object.cpp set_script):
# the value bound to a `script` property is not a Script at all — a plain
# Resource declared `type="Script"` in a scene (#709 review). Same family and
# same consequence as _INCOMPATIBLE_BINDING (the object boots script-less), and
# the sentence names neither a path nor a type, so the diagnostic carries only
# the message.
_NOT_A_SCRIPT_BINDING = re.compile(
    r"^Cannot set object script\. Parameter should be null or a reference to a "
    r"valid script"
)

# The two resource-load sentences (#651 review claim 4). Godot emits BOTH for one
# failed `load()`/`preload()` of a non-script resource, from different layers:
# `Cannot open file` from the format loader, `Failed loading resource` from
# ResourceLoader. A missing SCRIPT also produces the second one, beside its own
# more specific `Attempt to open script` sentence — which outranks it, so the
# verdict is unaffected (see ``_ENTRY_FAILURE_PRECEDENCE``).
_CANNOT_OPEN_FILE = re.compile(r"^Cannot open file '(?P<path>[^']*)'")

# `ERROR: Failed loading resource: <path>.` — `resource_loader.cpp:343`,
# `vformat("Failed loading resource: %s.", p_path)` (Godot 4.6.3). The format
# string ALWAYS appends exactly one trailing period, so it is sentence
# punctuation, never part of the path. Unlike `_CANT_LOAD` above, an optional
# strip here never actually mis-read a well-formed captured line, for any
# number of trailing dots: the lazy quantifier always finds the guaranteed
# period regardless of how many dots the path itself carries. The strip is
# mandatory anyway (#698) — a fail-closed hardening that rejects a line
# lacking the guaranteed period instead of silently accepting the whole
# remainder as the path, not a fix for observed corruption. `.+` rather than
# `\S+`, for the same reason as `_CANT_LOAD`: a project-relative path MAY
# contain a space, and `engine_log` has already split stderr into lines
# before this regex ever sees one, so `.+` cannot run past the line it
# belongs to. The engine's other "Failed loading resource" wording
# (`resource_loader.cpp:327`, no trailing period) reaches only
# `print_verbose`, never an `ERROR:` line `parse_errors` recognizes, so it
# cannot reach this regex.
_FAILED_LOADING_RESOURCE = re.compile(r"^Failed loading resource: (?P<path>.+)\.$")


def canonical_res_path(path: str) -> str:
    """The canonical lexical form of a ``res://`` address (#651 review claim 1).

    ONE resource identity, used on both sides of every comparison and for the argv
    gda hands the engine. Godot canonicalizes internally before it reports a path,
    so ``res://dir/../bad.gd`` comes back as ``res://bad.gd``; comparing the
    engine's spelling against the caller's raw one missed the match and let a
    failed run report success.

    Collapses ``.``/``..`` segments and duplicate slashes on the path part only
    (posixpath semantics), leaving the ``res://`` scheme intact. Purely lexical —
    no filesystem access — so it is safe on a path that does not exist, which is
    exactly the missing-entry-script case. A non-``res://`` string is returned
    unchanged: this normalizes an address, it does not validate one.
    """
    if not path.startswith(_RES_PREFIX):
        return path
    # Strip leading slashes before normpath: POSIX gives exactly two leading
    # slashes a special meaning ("//a" stays "//a"), which would leave a
    # `res:////a.gd` spelling uncanonicalized.
    remainder = path[len(_RES_PREFIX) :].lstrip("/")
    if not remainder:
        return _RES_PREFIX
    # normpath("") is ".", so the empty case is handled above rather than here.
    return _RES_PREFIX + posixpath.normpath(remainder)


class ScriptErrorKind(str, Enum):
    """What a recognized engine error line says about the resource it names (#651).

    A closed, public enum: it is projected into ``--schema`` through the results
    that carry :class:`ScriptError`. Every kind except ``RUNTIME_ERROR`` and
    ``INCOMPATIBLE_SCRIPT`` reports that the named resource could **not be loaded
    or run**; ``RUNTIME_ERROR`` reports an error raised by a script that was
    already executing, and ``INCOMPATIBLE_SCRIPT`` reports a binding the engine
    refused — a compiled script whose base cannot bind its object, or a bound
    value that is not a Script at all (it names no resource either way).

    Whether such a failure ended the *run* depends on **which** resource it names:
    a load failure naming the entry script means the run never happened, while the
    same failure naming something the running script merely tried to load does
    not. :func:`entry_load_failure` is what applies that distinction; a ``kind``
    alone does not decide it.
    """

    #: A compile failure in the named script (its own syntax error, or a
    #: dependency it preloads that does not resolve). That script never ran.
    PARSE_ERROR = "parse_error"
    #: A GDScript error raised while the script was already executing. The ONLY
    #: kind that says the named script ran.
    RUNTIME_ERROR = "runtime_error"
    #: The named script does not exist.
    SCRIPT_MISSING = "script_missing"
    #: The named script exists but could not be loaded (an open failure other
    #: than a missing file, or the engine giving up on the entry point).
    LOAD_FAILED = "load_failed"
    #: The named script was read but did not compile.
    COMPILE_FAILED = "compile_failed"
    #: The named script compiles but does not extend ``SceneTree``/``MainLoop``,
    #: so it cannot be a one-shot ``--script`` entry point.
    NOT_A_MAIN_LOOP = "not_a_main_loop"
    #: A resource the run tried to load could not be loaded — typically a
    #: ``load()``/``preload()`` of a missing or unreadable non-script resource
    #: (e.g. a ``.tres``), but the engine reports a missing script this way too,
    #: beside its more specific sentence.
    RESOURCE_LOAD_FAILED = "resource_load_failed"
    #: A script binding the engine refused at assignment time: a compiled script
    #: whose native base cannot bind the object it was assigned to (e.g. an
    #: ``extends Resource`` script on a ``Node2D``), or a bound value that is not
    #: a Script at all (a plain Resource declared ``type="Script"`` in a scene).
    #: Either way the object runs script-less. Carries no ``path`` — neither
    #: sentence names a file — so it can never name an entry script and never
    #: decides a run verdict.
    INCOMPATIBLE_SCRIPT = "incompatible_script"


#: The kinds that prove a script never ran, in verdict precedence — the order
#: :func:`entry_load_failure` returns them in when a run emits several. It runs
#: EARLIEST-STAGE, MOST SPECIFIC first, because the engine reports the whole
#: cascade and only the first cause explains the rest:
#:
#: 1. ``SCRIPT_MISSING`` — a file that does not exist cannot compile, so it
#:    outranks the generic "can't load" the engine emits beside it;
#: 2. ``COMPILE_FAILED`` — the engine's explicit "Failed to load script … with
#:    error …" verdict sentence;
#: 3. ``PARSE_ERROR`` — the individual diagnostic that CAUSED (2). Ranked below it
#:    because (2) is the engine's own conclusion, but kept in the list so a
#:    non-compiling entry is still caught if a build ever emits the diagnostic
#:    without the conclusion;
#: 4. ``LOAD_FAILED`` — "can't load", the least specific script-level reason;
#: 5. ``RESOURCE_LOAD_FAILED`` — the generic resource-layer failure. It is emitted
#:    beside a missing script's own sentence, so it must rank below it; on its own
#:    naming the entry it still means the entry never loaded;
#: 6. ``NOT_A_MAIN_LOOP`` — last because it is only reachable by a script that
#:    already existed AND compiled; it is a refusal, not a load failure.
#:
#: ``RUNTIME_ERROR`` is absent by construction: it is the one kind that proves the
#: script DID run.
_ENTRY_FAILURE_PRECEDENCE = (
    ScriptErrorKind.SCRIPT_MISSING,
    ScriptErrorKind.COMPILE_FAILED,
    ScriptErrorKind.PARSE_ERROR,
    ScriptErrorKind.LOAD_FAILED,
    ScriptErrorKind.RESOURCE_LOAD_FAILED,
    ScriptErrorKind.NOT_A_MAIN_LOOP,
)


class ScriptError(BaseModel):
    """One recognized script error read out of the engine's stderr (#651).

    Best-effort and advisory in the ADR-0002 sense — parsed from stderr, not from
    a bound API — but unlike free-form diagnostics it is *classified*, so an agent
    can branch on ``kind`` instead of matching engine prose.
    """

    kind: ScriptErrorKind = Field(
        description=(
            "Which known engine failure this line reports. Every kind except "
            "'runtime_error' and 'incompatible_script' means the named resource "
            "could not be loaded or run; 'runtime_error' means a script was "
            "already executing when it raised, and 'incompatible_script' means "
            "the engine refused a script binding — a compiled script whose base "
            "cannot bind its object, or a bound value that is not a Script at "
            "all (path is null: neither sentence names a file). Whether the RUN "
            "failed "
            "depends on whether 'path' is the entry script: a load failure naming "
            "something the running script merely tried to load is not a failed "
            "run."
        )
    )
    message: str = Field(
        description=(
            "The engine's error text verbatim, with its 'ERROR:'/'SCRIPT ERROR:' "
            "prefix stripped."
        )
    )
    path: str | None = Field(
        default=None,
        description=(
            "The res:// resource this error is about, in canonical form ('.'/'..' "
            "segments and duplicate slashes collapsed), or null when the engine "
            "named none."
        ),
    )
    line: int | None = Field(
        default=None,
        description=(
            "The 1-based line in 'path' the engine reported, or null when it "
            "reported none (engine-side load errors carry no script line)."
        ),
    )


def parse_script_errors(stderr: str) -> list[ScriptError]:
    """Recognized script errors from an engine stderr capture, in emission order.

    Pure and best-effort: an error the engine formats in a way this module does
    not recognize — and every warning — is skipped rather than guessed at, and
    malformed input yields ``[]`` instead of raising. Callers keep the verbatim
    stderr, so nothing is lost by the narrow recognition.
    """
    errors: list[ScriptError] = []
    for record in parse_errors(stderr):
        recognized = _classify(record)
        if recognized is not None:
            errors.append(recognized)
    return errors


def entry_load_failure(
    errors: Sequence[ScriptError], script: str
) -> ScriptError | None:
    """The error proving ``script`` never ran as the entry point, or ``None``.

    ``script`` is the ``res://`` path the caller asked the engine to run. Matching
    on that path is what keeps the verdict honest: a running script that *itself*
    loads a missing or broken resource produces the very same engine sentences for
    a DIFFERENT path, and must not be reported as a failed run.

    Both sides are canonicalized (:func:`canonical_res_path`) before comparison,
    because the engine reports the canonical spelling of whatever it was given:
    invoking ``res://dir/../bad.gd`` yields errors naming ``res://bad.gd``, and a
    raw-string comparison would miss the match and report a phantom success. The
    paths on ``errors`` are already canonical (the parser canonicalizes on the way
    in); canonicalizing again here is idempotent and keeps the guarantee local, so
    a caller passing hand-built errors cannot defeat it.

    A dependency's compile failure still fails the entry: the engine reports the
    unresolvable preload as "Failed to load script" naming the **entry** script
    (verified against Godot 4.6.3), so no dependency walk is needed here.

    Returns the most specific matching error (see ``_ENTRY_FAILURE_PRECEDENCE``);
    ``None`` when the entry point loaded, whatever else went wrong afterwards.
    """
    entry = canonical_res_path(script)
    for kind in _ENTRY_FAILURE_PRECEDENCE:
        for error in errors:
            if error.kind is kind and _matches(error.path, entry):
                return error
    return None


def _matches(path: str | None, entry: str) -> bool:
    """Does a diagnostic's path name the (already canonical) entry script?"""
    return path is not None and canonical_res_path(path) == entry


def _classify(record: dict) -> ScriptError | None:
    """One ``parse_errors`` record as a :class:`ScriptError`, or ``None`` if unknown."""
    level = record.get("level")
    message = record.get("message") or ""
    if level == "script_error":
        return _script_error(record, message)
    if level != "error":
        # Warnings and the other engine levels say nothing about a script's fate.
        return None
    return _engine_error(message)


def _script_error(record: dict, message: str) -> ScriptError:
    """A ``SCRIPT ERROR:`` record: a compile failure or a runtime failure.

    The location comes from the engine's ``at:`` frame, which for a script error
    names the script itself (``GDScript::reload (res://entry.gd:4)`` for a parse
    error, the raising function for a runtime one), so both a ``path`` and a
    ``line`` are available here — unlike the engine-side load errors below.
    """
    kind = (
        ScriptErrorKind.PARSE_ERROR
        if message.startswith(_PARSE_ERROR_PREFIX)
        else ScriptErrorKind.RUNTIME_ERROR
    )
    file = record.get("file")
    path = (
        canonical_res_path(file)
        if isinstance(file, str) and file.startswith(_RES_PREFIX)
        else None
    )
    return ScriptError(
        kind=kind,
        message=message,
        path=path,
        # A line without a res:// path would be a line number in the engine's own
        # C++ source, which is meaningless to an agent — so both travel together.
        line=record.get("line") if path is not None else None,
    )


def _engine_error(message: str) -> ScriptError | None:
    """A plain ``ERROR:`` record, if it is one of the known load-failure sentences.

    The path is read out of the MESSAGE, not the record's ``at:`` frame: these are
    raised by the engine's own C++ (``main.cpp``, ``gdscript.cpp``,
    ``resource_loader.cpp``), so the frame names an engine source file. No script
    line is available for any of them.
    """
    open_failed = _OPEN_FAILED.match(message)
    if open_failed is not None:
        kind = (
            ScriptErrorKind.SCRIPT_MISSING
            if open_failed.group("reason") == _FILE_NOT_FOUND
            else ScriptErrorKind.LOAD_FAILED
        )
        return _engine_diagnostic(kind, message, open_failed.group("path"))
    load_failed = _LOAD_FAILED.match(message)
    if load_failed is not None:
        return _engine_diagnostic(
            ScriptErrorKind.COMPILE_FAILED, message, load_failed.group("path")
        )
    # Checked before the bare `Can't load script:` form — the two sentences share a
    # prefix word, and only the anchored patterns tell them apart.
    not_a_main_loop = _NOT_A_MAIN_LOOP.match(message)
    if not_a_main_loop is not None:
        return _engine_diagnostic(
            ScriptErrorKind.NOT_A_MAIN_LOOP, message, not_a_main_loop.group("path")
        )
    cant_load = _CANT_LOAD.match(message)
    if cant_load is not None:
        return _engine_diagnostic(
            ScriptErrorKind.LOAD_FAILED, message, cant_load.group("path")
        )
    # The two bind-time refusals, both with no res:// address: one names the two
    # incompatible TYPES, the other names nothing at all — so the diagnostic
    # carries the message and honestly no path, keeping both out of every
    # entry-verdict comparison.
    if _INCOMPATIBLE_BINDING.match(message) is not None:
        return ScriptError(
            kind=ScriptErrorKind.INCOMPATIBLE_SCRIPT, message=message, path=None
        )
    if _NOT_A_SCRIPT_BINDING.match(message) is not None:
        return ScriptError(
            kind=ScriptErrorKind.INCOMPATIBLE_SCRIPT, message=message, path=None
        )
    # The resource layer's two sentences (#651 review claim 4). Both name a
    # res:// address the run tried to load; whether that address is the ENTRY is
    # what decides the verdict, and that is entry_load_failure's job, not this
    # classifier's — so a runtime load() of a missing .tres lands here as an
    # ordinary diagnostic on a successful run.
    cannot_open = _CANNOT_OPEN_FILE.match(message)
    if cannot_open is not None:
        return _engine_diagnostic(
            ScriptErrorKind.RESOURCE_LOAD_FAILED, message, cannot_open.group("path")
        )
    failed_loading = _FAILED_LOADING_RESOURCE.match(message)
    if failed_loading is not None:
        return _engine_diagnostic(
            ScriptErrorKind.RESOURCE_LOAD_FAILED, message, failed_loading.group("path")
        )
    return None


def _engine_diagnostic(kind: ScriptErrorKind, message: str, path: str) -> ScriptError:
    """An engine-side load diagnostic, with its address canonicalized on the way in.

    The one construction point for the message-derived paths, so every address
    this module publishes is canonical and no future sentence can be added that
    quietly skips normalization (#651 review claim 1).
    """
    return ScriptError(kind=kind, message=message, path=canonical_res_path(path))
