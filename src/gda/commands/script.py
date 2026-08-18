"""The ``script`` command group: Godot script files (.gd) as the domain object.

One vertical slice per `Command group` (ADR-0040): this module owns the group's
params/result models, its ``script run`` operation (formerly ``gda.script_run``),
its ``script validate`` classifier, its human renderers, its ``HeadlessCommand``
descriptors (ADR-0023), and its Typer command bodies, and mounts them on the
root app through :func:`register`. It imports the shared machinery downward —
the dispatch tail (``gda.dispatch``), the descriptor machinery (``gda.headless``),
the shared failure taxonomy (``gda.errors``), the cross-command contract core
(``gda.models``) and the launch primitive (``gda.runner``) — and is imported by
the composition root (``gda.cli``) and its one sanctioned sibling,
``gda.commands.shader`` (which reuses the ``ScriptSetMode`` edit interface,
ADR-0040 §5).

C# (.cs) is out of scope for now — it needs the .NET build of Godot (ADR-0003
targets the standard build) and a dedicated decision.
"""

import math
import re
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import typer
from pydantic import BaseModel, Field, model_validator

from gda import dispatch
from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe
from gda.errors import (
    Failure,
    classify_launch_or_crash,
    classify_run,
    script_did_not_run_failure,
    script_exit_status_failure,
    script_outside_project_failure,
    script_path_invalid_failure,
    script_run_aborted_failure,
    script_run_project_not_found_failure,
    script_run_timeout_failure,
    unresolvable_binary_failure,
)
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import CREATED_DIRS_DESC, NormalizedPath
from gda.project import path_outside_project
from gda.runner import LaunchFailure, LaunchWatch, RunResult, launch
from gda.script_errors import (
    ScriptError,
    ScriptErrorKind,
    canonical_res_path,
    entry_load_failure,
    parse_script_errors,
)


class ScriptCreateParams(BaseModel):
    """The operation params of ``gda script create`` (issue #110).

    ``path`` is the target ``.gd`` script file, addressed by its ``res://`` or
    filesystem path (script-file addressing — by file path, not by
    ``class_name``). ``content`` supplies verbatim source; when omitted, the
    operation writes a minimal built-in template extending ``extends_type``.
    ``content`` and ``extends_type`` are mutually exclusive at the CLI: verbatim
    content is not templated, so a base class would have nowhere to go.
    """

    path: NormalizedPath = Field(description="Target .gd script path to write.")
    content: str | None = Field(
        default=None,
        description=(
            "Verbatim script source to write. When omitted, a minimal built-in "
            "template extending 'extends_type' is written instead. Mutually "
            "exclusive with the template's base class."
        ),
    )
    extends_type: str | None = Field(
        default=None,
        description=(
            "Base class for the built-in template's 'extends' line (e.g. Node, "
            "Node2D). Ignored when 'content' is supplied; defaults to 'Node' "
            "when neither is given."
        ),
    )

    @model_validator(mode="after")
    def _content_xor_extends(self) -> "ScriptCreateParams":
        # Verbatim content is not templated, so a base class has nowhere to go:
        # the two are mutually exclusive. Enforced model-side (ADR-0015) so the
        # --params-json path rejects the conflict too, not just argv.
        if self.content is not None and self.extends_type is not None:
            raise ValueError("'content' and 'extends_type' are mutually exclusive.")
        return self


class ScriptCreateResult(BaseModel):
    """The result of ``gda script create``: what was written where (issue #110).

    Echoes the saved ``path`` and the ``class_name``/``extends`` the written
    source declares, so an agent can assert the effect without a second call.
    ``created_dirs`` lists parent directories the operation created before
    saving, from outermost to innermost. The ``class_name``/``extends`` are
    parsed from the written source.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the written script declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the written script extends, or null when it declares none."
        ),
    )
    created_dirs: list[str] = Field(description=CREATED_DIRS_DESC)


class ScriptGetParams(BaseModel):
    """The operation params of ``gda script get``: the script file to read (issue #110).

    ``path`` addresses the ``.gd`` script by its ``res://`` or filesystem path.
    The source is read as raw text — the script is never loaded or compiled, so
    reading it can never run project code (issue #30).
    """

    path: NormalizedPath = Field(description="The .gd script file to read.")


class ScriptGetResult(BaseModel):
    """The result of ``gda script get``: a script's source and metadata (issue #110).

    Echoes the ``path``, the full ``source`` read as raw text, and the
    ``class_name``/``extends`` the source declares (parsed from the text).
    Carrying the source verbatim makes a ``create`` verifiable end-to-end:
    ``create`` then ``get`` returns the same source.
    """

    path: str
    source: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the script declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the script extends, or null when it declares none."
        ),
    )


class ScriptListParams(BaseModel):
    """The operation params of ``gda script list`` — none (ADR-0004).

    ``script list`` enumerates the ``.gd`` scripts in the resolved project's
    ``res://`` tree; the project is process context (``--project``), not an
    operation param (ADR-0006), so the ``input`` schema is trivially empty.
    """


class ListedScript(BaseModel):
    """One enumerated script of ``gda script list``: its path and metadata.

    ``path`` is the script's ``res://`` path — the address an agent feeds back
    into other script commands. ``class_name``/``extends`` are parsed cheaply
    from the script's raw source (no compilation, issue #30); both are null when
    the script declares neither, so the entry still names a file the listing
    found rather than dropping it.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description="The class_name the script declares, or null when it declares none.",
    )
    extends: str | None = Field(
        default=None,
        description="The base class the script extends, or null when it declares none.",
    )


class ScriptListResult(BaseModel):
    """The result of ``gda script list``: the project's enumerated ``.gd`` scripts.

    An empty project is a valid, empty listing — ``scripts == []`` — not a
    failure.
    """

    scripts: list[ListedScript]


class ScriptDeleteParams(BaseModel):
    """The operation params of ``gda script delete``: the ``.gd`` file to remove."""

    path: NormalizedPath = Field(description="The .gd script file to delete.")


class ScriptDeleteResult(BaseModel):
    """The result of ``gda script delete``: what was removed (issue #117).

    Echoes the deleted script's ``path`` and the ``class_name``/``extends`` its
    source declared (parsed from the raw text before deletion), so the result
    names the content removed, not just the file path.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description="The class_name the deleted script declared, or null when it declared none.",
    )
    extends: str | None = Field(
        default=None,
        description="The base class the deleted script extended, or null when it declared none.",
    )


class ScriptSetMode(str, Enum):
    """The edit mode of ``gda script set``, the single source of truth (issue #133).

    The CLI resolves exactly one mode from the supplied flags (its mutual-exclusion
    check) and stamps it here, so the operation dispatches on this explicit
    discriminator instead of re-inferring the mode from which params are present —
    the inference precedence can no longer drift from the CLI's exclusivity rule.

    - ``SEARCH_REPLACE`` — ``search``/``replace``: every literal (not regex)
      occurrence of ``search`` is replaced with ``replace``.
    - ``LINE_RANGE`` — ``start_line`` (+ optional ``end_line``) with ``content``:
      the given 1-based, inclusive line span is replaced with ``content``.
    - ``FULL`` — ``content`` only: the whole file is overwritten.
    """

    SEARCH_REPLACE = "search_replace"
    LINE_RANGE = "line_range"
    FULL = "full"


def resolve_set_mode(
    search: str | None,
    replace: str | None,
    start_line: int | None,
    end_line: int | None,
    content: str | None,
) -> ScriptSetMode:
    """Resolve a script/shader-set edit mode from the supplied params (issue #133).

    The single home of the edit-mode rule, shared by ``script set`` and ``shader
    set`` and by BOTH input paths (ADR-0015): exactly one of the three
    mutually-exclusive modes must be supplied. Raises ``ValueError`` on a
    violation — the CLI wrapper translates it to a usage error (exit 2) for argv,
    while the params models surface it as the structured ``invalid_params`` for
    ``--params-json``.
    """
    has_search = search is not None or replace is not None
    has_line_range = start_line is not None or end_line is not None

    if has_search:
        if search is None or replace is None:
            raise ValueError("'search' and 'replace' must be used together.")
        if content is not None or has_line_range:
            raise ValueError(
                "'search'/'replace' cannot be combined with 'content', "
                "'start_line', or 'end_line'."
            )
        return ScriptSetMode.SEARCH_REPLACE

    if has_line_range:
        if content is None:
            raise ValueError("'start_line'/'end_line' require 'content'.")
        if start_line is None:
            raise ValueError("'end_line' requires 'start_line'.")
        return ScriptSetMode.LINE_RANGE

    if content is None:
        raise ValueError(
            "a set command needs an edit: 'search'/'replace', 'start_line' "
            "(+ 'content'), or 'content' (full overwrite)."
        )
    return ScriptSetMode.FULL


class ScriptSetParams(BaseModel):
    """The operation params of ``gda script set`` (issue #118).

    Edits an existing ``.gd`` script on disk as RAW TEXT — it never compiles or
    loads the script, so editing one can never run project code (the read trust
    boundary of issue #30). ``path`` addresses the script by its ``res://`` or
    filesystem path. The remaining params carry one of three mutually-exclusive
    edit modes; the CLI resolves which one and stamps it on ``mode`` (issue #133),
    so the operation dispatches on that explicit discriminator rather than
    re-inferring it from which params are present:

    - **search-replace** (``mode = search_replace``) — ``search``/``replace`` both
      present: every literal (not regex) occurrence of ``search`` is replaced with
      ``replace``.
    - **line-range** (``mode = line_range``) — ``start_line`` (+ optional
      ``end_line``) with ``content``: the given 1-based, inclusive line span is
      replaced with ``content``.
    - **full** (``mode = full``) — only ``content`` present: the whole file is
      overwritten.
    """

    path: NormalizedPath = Field(description="The .gd script file to edit.")
    mode: ScriptSetMode | None = Field(
        default=None,
        description=(
            "The resolved edit mode, the single source of truth the operation "
            "dispatches on (issue #133). Derived model-side from the supplied "
            "edit params (ADR-0015); a value passed in is ignored."
        ),
    )
    search: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal substring to find (NOT a regex). "
            "Every occurrence is replaced with 'replace'. Requires 'replace'."
        ),
    )
    replace: str | None = Field(
        default=None,
        description=(
            "search-replace mode: the literal text each occurrence of 'search' "
            "is replaced with. Requires 'search'."
        ),
    )
    start_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the first line to replace, 1-based and inclusive. "
            "Lines are the parts of the source split on '\\n', so a trailing "
            "newline yields a final empty part: 'a\\nb\\n' is 3 lines "
            "(['a', 'b', '']). Valid range is 1..N where N is that part count. "
            "Requires 'content'."
        ),
    )
    end_line: int | None = Field(
        default=None,
        description=(
            "line-range mode: the last line to replace, 1-based and inclusive; "
            "defaults to 'start_line' (a single-line replace). Must satisfy "
            "start_line <= end_line <= N (the line count). Requires 'content'."
        ),
    )
    content: str | None = Field(
        default=None,
        description=(
            "The replacement text. In line-range mode it replaces the "
            "start_line..end_line span; with no 'start_line' it overwrites the "
            "entire file (full mode)."
        ),
    )

    @model_validator(mode="after")
    def _resolve_mode(self) -> "ScriptSetParams":
        # Derive the edit mode from the supplied params (ADR-0015), so the argv
        # and --params-json paths agree and a JSON caller cannot pass a mode
        # inconsistent with the other edit fields.
        self.mode = resolve_set_mode(
            self.search, self.replace, self.start_line, self.end_line, self.content
        )
        return self


class ScriptSetResult(BaseModel):
    """The result of ``gda script set``: the edited script's metadata (issue #118).

    Echoes the saved ``path`` and the ``class_name``/``extends`` re-parsed from
    the source as written, so an edit round-trips through ``script get`` (the
    verifier) without a second call — and an agent can assert the post-edit
    metadata directly.
    """

    path: str
    class_name: str | None = Field(
        default=None,
        description=(
            "The class_name the edited source declares, or null when it declares none."
        ),
    )
    extends: str | None = Field(
        default=None,
        description=(
            "The base class the edited source extends, or null when it declares none."
        ),
    )


class ScriptAttachParams(BaseModel):
    """The operation params of ``gda script attach`` (issue #118).

    Binds a ``.gd`` script to a node inside a ``.tscn`` scene: load the scene,
    resolve the node by node path, attach the script, then re-pack and save. As a
    scene mutation it instantiates the scene (the same inherent trust boundary as
    ``node set``, ADR-0009): instantiating runs the ``_init`` of scripts already
    attached in the scene, and for a script that compiles ``set_script``
    constructs an instance of the newly-attached script, running its ``_init``
    too. ``path`` is the scene; ``script`` is the ``.gd`` to attach. The script
    must COMPILE: the headless engine silently rejects a non-compiling script
    from ``set_script`` (it cannot be persisted into the scene), so attach
    refuses one with ``script_compile_failed`` rather than report a phantom
    success — check a script with ``script validate`` first.
    """

    path: NormalizedPath = Field(description="The .tscn scene file to mutate.")
    node: str = Field(
        description=(
            "Node path relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        )
    )
    script: NormalizedPath = Field(
        description="The .gd script file to attach to the node."
    )


class ScriptAttachResult(BaseModel):
    """The result of ``gda script attach``: what was bound where (issue #118).

    Echoes the ``scene_path``, the addressed ``node``, and the attached
    ``script``, plus the script's ``class_name`` when it declares a global one —
    the result an agent asserts to confirm the binding took effect, verifiable by
    reading the saved scene back (the script now appears on the node).

    ``attach`` is a mutation verb: it OVERWRITES an existing binding rather than
    refusing it (issue #132). ``replaced_script`` makes that displacement visible
    so the overwrite is never silent — an agent reads it to detect a clobber.
    """

    scene_path: str
    node: str = Field(
        description="The node path the script was attached to, relative to the scene root."
    )
    script: str = Field(description="The .gd script that was attached.")
    class_name: str | None = Field(
        default=None,
        description=(
            "The global class_name the attached script declares, or null when "
            "it declares none."
        ),
    )
    replaced_script: str | None = Field(
        default=None,
        description=(
            "The resource_path of the script this attach DISPLACED, reported "
            "verbatim — including a built-in/embedded script's sub-resource ref "
            "(e.g. 'res://scene.tscn::GDScript_xxx'). Non-null whenever the node "
            "already carried a script (attach overwrites-and-reports, issue "
            "#132); null only when the node had no prior script."
        ),
    )


class ScriptDiagnostic(BaseModel):
    """One advisory diagnostic from ``gda script validate`` (issue #118).

    Best-effort: parsed from the engine's stderr, not from a bound API, so it may
    carry only the FIRST parse error. ``line`` is 1-based when the engine
    reported it; ``column`` is ALWAYS null on the standard Godot build — the
    engine does not expose a column for a parse error — and is kept as a field
    only so the shape is stable if a future build ever does. ``message`` is the
    engine's error text with its ``SCRIPT ERROR:`` prefix stripped.
    """

    line: int | None = Field(
        default=None,
        description="The 1-based source line the error was reported at, or null when unknown.",
    )
    column: int | None = Field(
        default=None,
        description=(
            "Always null on the standard Godot build: the engine does not "
            "expose a column for a parse error."
        ),
    )
    message: str


class ScriptValidateParams(BaseModel):
    """The operation params of ``gda script validate``: the script to check (issue #118).

    ``path`` addresses the ``.gd`` script by its ``res://`` or filesystem path.
    Unlike the other script-file ops, validate DOES compile the script (it sets
    the source on a fresh ``GDScript`` and reloads it to learn whether it parses),
    but it never instantiates the script, so it does not run instance code. Pass
    ``--project`` when the script extends a project ``class_name`` or preloads a
    project resource and so needs project context to compile.
    """

    path: NormalizedPath = Field(description="The .gd script file to validate.")


class ScriptValidateResult(BaseModel):
    """The result of ``gda script validate``: whether the script compiles (issue #118).

    Validating an INVALID script is a SUCCESSFUL operation — the command exits 0
    and reports ``valid=false`` rather than failing. ``error_string`` carries the
    engine's one-line summary of the compile error (null when valid).
    ``diagnostics`` is a best-effort list parsed from the engine's stderr (the
    only place line/message are available); it may hold only the first error, and
    is empty when the script is valid or nothing could be parsed.

    ``project_root`` names the project the script was compiled against, so a
    reader can tell a real compile error from one caused by the wrong project
    context without re-deriving gda's resolution (#658). It is REQUIRED and
    nullable, not optional: every public result carries the key (``null`` means
    projectless), so an agent can read it unconditionally. The engine's sentinel
    does not report it — ADR-0006 keeps the project CLI-side, and the engine is
    told it through ``--path`` — so the ``before`` validator below supplies the
    key for the internal sentinel parse and the CLI stamps the real value
    immediately after (:func:`_script_validate_recipe`). The leniency is
    therefore inward-facing only: it never reaches the published contract, which
    lists ``project_root`` in ``required``.
    """

    path: str
    valid: bool = Field(
        description="True when the script compiles (GDScript.reload() == OK), false otherwise."
    )
    error_string: str | None = Field(
        default=None,
        description=(
            "The engine's one-line summary of the compile failure, or null when "
            "the script is valid."
        ),
    )
    diagnostics: list[ScriptDiagnostic] = Field(
        default_factory=list,
        description=(
            "Best-effort advisory diagnostics parsed from the engine's stderr "
            "(line + message). May hold only the first error; empty when valid."
        ),
    )
    project_root: str | None = Field(
        description=(
            "The Godot project this script was compiled against — the root its "
            "res:// dependencies resolved to, reported as an absolute path "
            "(ADR-0006: --project, then $GDA_PROJECT, then the current "
            "directory). Always present; null when gda ran projectless (no "
            "project resolved), where only filesystem paths resolve. A script "
            "whose res:// dependencies were reported missing with a null or "
            "unexpected root here has a project-context problem, not a source "
            "problem."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _supply_absent_project_root(cls, data: Any) -> Any:
        """Fill the key the ENGINE never sends, so the field can stay required.

        ``project_root`` is gda's own addition to the engine's answer: the
        ADR-0002 sentinel this model is parsed from carries only the fields
        ``operations.gd`` reports. Declaring the field required — so it appears
        in the published ``required`` list every consumer reads — would make
        that internal parse fail, so the absent key is supplied as ``null``
        here and the recipe stamps the resolved project immediately after.
        Anything that DOES carry the key (the recipe's own ``model_copy``, a
        round-trip of an emitted result) passes through untouched.
        """
        if isinstance(data, dict) and "project_root" not in data:
            return {**data, "project_root": None}
        return data


# The DEFAULT ceiling on one ``script run``, when the caller states none. A user
# script is arbitrary project code (it may load resources), so it is more generous
# than a single sentinel op's tight bound but well below the export channel's —
# enough for a logic-seam test without leaving a hung run to block forever.
#
# It is now a default rather than the only value (#655). A fixed ceiling made a
# healthy suite that grew past it indistinguishable from a hang, with no way to
# raise it (GDA-DF-032); ``--timeout`` is that way, and the ceiling still bounds a
# hung engine so the CLI fails loudly rather than blocking forever.
DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS = 120.0

# How long a run must stay SILENT, after an entry-attributable script error has
# appeared and while the caller's declared completion marker has not, before gda
# ends it (#655).
#
# This window is a CONTRACT PARAMETER, not a detector threshold. Whether a Godot
# run that printed an error can still finish is not observable from outside the
# process: a GDScript runtime error aborts only the function that raised it, so a
# script can survive one and keep working — and working can look exactly like
# death (blocked in a wait it consumes no CPU; during an ``await`` the main loop
# iterates just as an abandoned one does). Declaring ``--completion-marker`` is
# therefore what SETTLES the question, by contract: the caller asserts the script
# keeps producing output (any line resets this window) until the marker line says
# it finished, so an entry-attributable error followed by this much total silence
# without the marker IS the run being dead, by the caller's own declaration.
# Measured at 0.2s from spawn to the error line, 3s is a wide margin over the
# engine's own cadence while staying far below any usable ``--timeout``.
#
# Fixed, not an option: it is part of the declared contract and the abort's stated
# bound, and a caller whose script goes quiet for longer has two escape hatches —
# print anything during the quiet stretch, or omit the marker and wait out
# ``--timeout``. It is stated in the failure message so the bound is legible
# rather than folklore.
SCRIPT_RUN_ABORT_SILENCE_SECONDS = 3.0

# How many trailing stderr lines the watch re-parses to attribute an error. Godot
# writes one error as a header, an ``at:`` frame and possibly a backtrace, and a
# read syscall can split them across batches, so the window must span a whole
# record; it is bounded so the parse stays linear in the total output.
_STDERR_WINDOW_LINES = 64


class ScriptRunParams(BaseModel):
    """The operation params of ``gda script run`` (issue #343, ADR-0031, #675).

    ``path`` is the user script to run as a one-shot ``godot --headless --path
    <project> --script <res://…>``, addressed in EITHER of the two PORTABLE forms —
    project-relative (``tests/logic.gd``) or ``res://`` (``res://tests/logic.gd``) —
    which the rest of the ``script`` group takes as well. Both resolve against the
    ``--project`` context (ADR-0006) and converge on one canonical ``res://`` address
    in the operation. Refused with ``invalid_path`` (ADR-0031 amendment): an absolute
    path, another engine scheme (``user://``, ``uid://``), a path naming the project
    root, and one escaping above it (``..``). ``script validate`` does take an
    absolute path, so the two are not at full parity. It carries the same
    ``NormalizedPath`` as every other path field, so both input paths normalize
    identically (ADR-0015) and a ``~`` prefix expands to the absolute path it means —
    and is refused as one — rather than being read as a directory named ``~`` under
    the project. The project is process context (``--project``), not an operation
    param.
    """

    path: NormalizedPath = Field(
        description=(
            "The script to run, project-relative (tests/logic.gd) or as a res:// "
            "path (res://tests/logic.gd). An absolute path, another engine scheme "
            "(user://, uid://), or a path naming or escaping above the project "
            "root is refused."
        )
    )
    strict: bool = Field(
        default=False,
        description=(
            "Treat a non-zero script exit status as a gda failure: emit the error "
            "envelope with code 'script_failed' and exit 4, instead of the default "
            "passthrough success. Opt-in, for shell '&&' chains and CI gates that "
            "key on the process exit code. The envelope keeps the evidence: its "
            "message names the exit status, and its 'diagnostics' string carries "
            "BOTH of the script's streams under the fixed labels "
            "'--- script stdout ---' and '--- script stderr ---'. A script that "
            "never ran fails either way (ADR-0031 amendment)."
        ),
    )
    timeout: float = Field(
        default=DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
        gt=0,
        allow_inf_nan=False,
        description=(
            "How many seconds to let the run take before gda ends it and reports "
            "'launch_timeout'. Must be a FINITE positive number: JSON Schema cannot "
            "express finiteness, so a non-finite value is refused by validation "
            "rather than by the schema below — an infinite ceiling would never be "
            "reached and so would not bound the run at all. Raise it for a suite "
            "that outgrew the default of "
            f"{DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS}s; lower it to fail fast. The "
            "envelope reports the value that was reached, the elapsed wall clock, "
            "the captured output (tail-capped, cap stated), and one termination "
            "phase from the closed set 'launched' (the engine wrote nothing at "
            "all), 'output_seen' (it was alive and did not finish) and "
            "'aborted_on_error' (ended early by the rule below) — so a "
            "slow-but-live run is distinguishable from a hang. Reported as prose "
            "in the message, not as envelope fields (#655)."
        ),
    )
    completion_marker: str | None = Field(
        default=None,
        min_length=1,
        # A blank marker is compared as a stripped whole line, so it would equal
        # every blank line the run prints; `min_length` alone lets " " through.
        pattern=r"\S",
        description=(
            "Opt-in liveness contract: a string the script prints on its own line "
            "when it has finished its work. Declaring it asserts the script keeps "
            "producing output (any line counts) until that marker line — so when a "
            "recognized error ATTRIBUTABLE TO THE ENTRY script appears on stderr "
            "(one about another resource arms nothing), the marker has not "
            "appeared, and neither stream then produces output for "
            f"{SCRIPT_RUN_ABORT_SILENCE_SECONDS}s, gda ends the run and reports "
            "'script_aborted' with the captured error — in seconds rather than at "
            "the timeout, deterministically on every platform. Matched by "
            "WHOLE-LINE equality (both sides stripped), not as a substring. The "
            "contract cuts both ways: a script that goes silent for longer than "
            f"{SCRIPT_RUN_ABORT_SILENCE_SECONDS}s after such an error is ended "
            "even if it would have finished — a script with long quiet stretches "
            "should print progress during them, or run without a marker and wait "
            "out 'timeout' as before. Caller-declared, never imposed: gda does not "
            "require or inject anything in the script (ADR-0031), and this is not "
            "the ADR-0002 op-dispatch sentinel. Note a 'timeout' at or below "
            f"{SCRIPT_RUN_ABORT_SILENCE_SECONDS}s leaves the marker inert, "
            "because the ceiling arrives first (#655)."
        ),
    )


class ScriptRunResult(BaseModel):
    """The result of ``gda script run``: the user script's own run, passed through (ADR-0031).

    This is the **public promotion of the internal Raw-run shape**
    (:class:`gda.runner.RunResult`): a THIN boundary DTO built from a ``RunResult``
    by dropping its ``launch_failure`` axis (that becomes the Error envelope) and
    renaming ``exit_code`` → ``exit_status``. Unlike every other command,
    ``script run`` does not interpret the user script's semantics — a deliberate
    ``quit(1)`` is meaningful data the agent reads, not a gda failure — so this is
    the **one** command whose *success* result can carry a non-zero
    ``exit_status``. Agents must read ``exit_status`` and must not assume
    ``success == zero``.

    Not interpreting the script's semantics is NOT the same as not reading the
    engine's: ``diagnostics`` carries the recognized script errors gda parsed out
    of the engine's stderr (#651), so a runtime GDScript error that the script
    swallowed — leaving a clean ``exit_status`` — is still visible structurally
    rather than only as prose inside ``stderr``.

    ``path`` is the one field that is gda's own rather than the run's: the two
    accepted input forms (project-relative and ``res://``) converge on a single
    canonical ``res://`` address, and this reports which one ran (#675). Without
    it a project-relative caller would have no way to connect the path they typed
    to the one every failure message quotes.

    NOTE: a second passthrough consumer should promote the raw
    ``{exit_status, stdout, stderr}`` core to a shared ``RawRunResult`` model. Do
    NOT build that shared abstraction now: there is only one consumer today
    (``export run`` returns a different domain shape — the produced artifact — and
    does not reuse the raw run).
    """

    path: str = Field(
        description=(
            "The canonical res:// path of the script that was run (#675). Both "
            "accepted input forms — project-relative and res:// — converge on this "
            "one address, so a caller who addressed the script project-relatively "
            "reads back what the engine was actually asked to run."
        )
    )
    exit_status: int = Field(
        description=(
            "The user script's own process exit code, passed through verbatim — "
            "non-zero (e.g. a deliberate quit(1)) is still a SUCCESS result, not a "
            "gda failure, unless --strict was passed (ADR-0031)."
        )
    )
    stdout: str = Field(description="The script's standard output, captured verbatim.")
    stderr: str = Field(description="The script's standard error, captured verbatim.")
    diagnostics: list[ScriptError] = Field(
        default_factory=list,
        description=(
            "Recognized script errors parsed out of the engine's stderr, in "
            "emission order; empty when the run reported none. Advisory and "
            "best-effort — the verbatim stream stays in 'stderr'."
        ),
    )


# --- The ScriptRun operation — ``gda script run``'s user-script passthrough run
# (ADR-0031). Formerly ``gda.script_run``; merged into its group by ADR-0040 §1.
#
# ``gda script run res://path.gd`` runs the user's own script as a one-shot
# ``godot --headless --path <project> --script <res://…>`` process and returns a
# structured result. It is the **third execution shape** (ADR-0031): neither the
# ADR-0002 sentinel op-dispatch (the entry script is the user's own, so it cannot
# emit the sentinel) nor the native-export recipe (gda does not know the script's
# semantics, so it has no gda-defined typed result to synthesize). The outcome
# therefore **bifurcates by whose failure it is**:
#
# - **gda-/engine-level failure** — the binary could not be launched, the run timed
#   out, or the engine died on a signal (``exit_code < 0``) → an **Error envelope**,
#   classified by the SAME shared :func:`gda.errors.classify_launch_or_crash` the
#   export channel uses, into its existing codes (``binary_not_found`` /
#   ``launch_timeout`` / ``engine_crashed``). No new GDScript-mirrored codes.
# - **gda ENDED the run** — the caller's ``--timeout`` was reached, or (opt-in)
#   ``--completion-marker`` was declared and the run died before printing it → an
#   **Error envelope** carrying the run's EVIDENCE: the captured partial output,
#   the elapsed clock, a termination phase and the recognized script errors, all as
#   prose (``launch_timeout`` / ``script_aborted``, #655). Classified by this
#   channel rather than the shared prefix, because only this channel has that
#   evidence — see :func:`_classify_ended_run`.
# - **the script never RAN** — the engine exited normally but its stderr proves it
#   could not run the entry script: it is missing, it (or a dependency it preloads)
#   failed to parse/compile, or it compiles but is not a ``SceneTree``/``MainLoop``
#   → an **Error envelope** carrying ``script_not_found`` /
#   ``script_compile_failed`` / ``incompatible_script_type`` (#651, ADR-0031
#   amendment). Godot reports all of these on stderr and STILL exits 0, so passing
#   that status through reported a phantom success. gda is the authority on whether
#   the engine ran what it was asked to; the verdict is read from the parsed stderr
#   evidence (:mod:`gda.script_errors`), never from the exit code.
# - **the script ran to completion** — the engine exited normally
#   (``exit_code >= 0``) → a **success** :class:`ScriptRunResult` carrying
#   ``{exit_status, stdout, stderr, diagnostics}`` **passed through verbatim, even
#   when ``exit_status != 0``**. gda does not interpret the script's semantics: a
#   deliberate ``quit(1)`` (e.g. an assertion-failed logic-seam test) is meaningful
#   DATA the agent reads, not a gda failure. Under the opt-in ``--strict`` that one
#   default is inverted — a non-zero status becomes the ``script_failed`` envelope —
#   for the shell-chain / CI callers whose gate IS the process exit code.
#
# Two explicit pre-run ABI edges (ADR-0031), both decided at the CLI before any
# launch and returned as a structured ``GdaError`` (never a crash): a path that is
# not a project-scoped script address → ``invalid_path``; no resolved project →
# ``project_not_found``. The path edge is the narrowed one (ADR-0031 amendment,
# #675): the project-relative form the rest of the group accepts is now accepted
# here too, lifted onto res:// — while an absolute path, another engine scheme, and
# a path naming or escaping above the project root stay refused
# (:func:`_project_scoped_res_path`).
#
# Like ``export run`` (:mod:`gda.commands.export`), :func:`run_script_run_operation`
# RETURNS its outcome (``ScriptRunResult | Failure``) instead of emitting or
# exiting, so the CLI command stays the thin shared shape and the recipe gets its
# own engine-free test surface. The engine-touching step delegates to the
# deep-module headless-launch primitive :func:`gda.runner.launch` — the SINGLE home
# of the spawn / timeout / launch-failure / UTF-8-decode normalization — reused,
# not re-implemented. It is injected (``make_launch``) only so the bifurcation is
# testable without a real engine.

# The res:// scheme prefix — the ONE address form script run works in internally.
# Both accepted input spellings are folded onto it (ADR-0031 amendment, #675): a
# res:// path is already one, and a project-relative path is relative to exactly
# this root. An absolute/filesystem path is not, which is why it stays refused.
_RES_PREFIX = "res://"

# The canonical remainders that name the project ROOT itself rather than a script
# inside it. Both spellings occur: an EMPTY remainder (`res://`) and one that
# normalizes to `.` (`res://.`), so the degenerate check must cover the pair.
_ROOT_REMAINDERS = frozenset({"", "."})


def _project_scoped_res_path(script: str) -> str | None:
    """The canonical ``res://`` address of an accepted script path, or ``None`` (#675).

    The single acceptance gate for ``script run``'s path argument, applied BEFORE any
    launch so every refusal is a structured ``invalid_path`` and never an engine
    failure. It accepts the two PORTABLE forms — a ``res://`` address and a
    project-relative path — and folds them onto one address through the shared
    :func:`canonical_res_path`, so the argv, the entry-load verdict and the reported
    path cannot diverge by input spelling.

    Returns ``None`` for the five shapes that are not project-scoped script
    addresses. Each must be caught HERE, because each is otherwise launched:

    - an **absolute** path — outside the ``--project`` context (the reasons it stays
      refused are recorded on :func:`gda.errors.script_path_invalid_failure`);
    - **another engine scheme** (``user://``, ``uid://``) — lifting one would splice a
      second scheme into a res:// address (``user://x.gd`` → ``res://user:/x.gd``) and
      send the engine hunting for a path the caller never typed;
    - a leading ``~`` — a HOME reference, which is a filesystem address form, not a
      project-relative one. It reaches here only when the shared normalizer could not
      expand it (an unknown user, #699); a resolvable ``~/x.gd`` was already expanded
      to the absolute path refused above. So both tilde outcomes land on one refusal
      instead of one being refused and the other spliced into ``res://~user/x.gd``;
    - a path that names the project **root** (``""``, ``"."``, ``"sub/.."``) — it names
      a directory, not a script. An unset shell variable makes ``gda script run
      "$SCRIPT"`` exactly this;
    - a path that **escapes above the root** (``".."``, ``"../outside.gd"``, and their
      ``res://`` spellings) — the project is the whole addressable scope, so an
      upward escape names something the ``--project`` contract does not cover.

    The last two are load-bearing for the same reason, and it is not tidiness. The
    engine answers a root address with ``Can't load script: res://.`` (or
    ``res://..``), whose address the error parser reads back with the sentence period
    stripped — ``res://`` for the first, ``res://.`` for the second. Neither matches
    the entry, so the never-ran verdict misses it and the run reports a PHANTOM
    SUCCESS. And an escape that RESOLVES (``../outside.gd``) executes a script outside
    the project entirely, which would widen the Project-code execution surface past
    ADR-0009's Trusted project — the very consequence the amendment cites for keeping
    absolute paths refused, so admitting it by the relative spelling would make that
    reasoning false. Refusing both before the launch closes them without touching the
    error parser's own res:// handling.

    The escape test is on the canonical remainder's first SEGMENT, not a string
    prefix: ``res://..foo.gd`` is a legal file whose name merely starts with two dots,
    and must stay accepted.
    """
    if Path(script).is_absolute():
        return None
    if "://" in script and not script.startswith(_RES_PREFIX):
        return None
    # Only a LEADING `~` is a home reference (expanduser's own rule), so `sub/~x.gd`
    # stays a legal project-relative filename.
    if script.startswith("~"):
        return None
    lifted = script if script.startswith(_RES_PREFIX) else _RES_PREFIX + script
    canonical = canonical_res_path(lifted)
    # What the canonical address names UNDER the project root. canonical_res_path has
    # already collapsed `.`/`..`, so a remainder that STILL leads with a `..` segment
    # is an irreducible upward escape, and an empty/`.` one is the root itself.
    remainder = canonical[len(_RES_PREFIX) :]
    if remainder in _ROOT_REMAINDERS:
        return None
    if remainder == ".." or remainder.startswith("../"):
        return None
    return canonical


class LaunchFn(Protocol):
    """The headless-launch seam — the shape of :func:`gda.runner.launch` (#343).

    Injected into :func:`run_script_run_operation` so the launch/crash bifurcation
    is exercised with a canned :class:`~gda.runner.RunResult`, without spawning a
    real engine — the ``script run`` twin of the sentinel channel's ``RunnerFactory``
    and the export channel's ``ExportRunnerFactory``. The default is the real
    ``launch`` (the deep module is reused, never re-implemented).
    """

    def __call__(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None,
        timeout: float,
        timeout_label: str = ...,
        watch: LaunchWatch | None = ...,
    ) -> RunResult: ...


class TerminationPhase(str, Enum):
    """How far a ``script run`` gda ENDED had got when gda ended it (#655).

    Reported as PROSE in the failure message — never as an envelope field, which
    would change ADR-0004's uniform failure ABI (**#687 owns that decision**;
    ADR-0031's amendment records that this issue adopts its outcome). The enum
    exists so the set is closed and the spelling cannot drift, not because the
    envelope is typed here.

    The set answers the question an agent asks of a run that did not finish: was it
    working, or was it stuck? The issue's illustrative set named a third phase for
    "killed at the timeout", which both timeout phases below already are — what a
    reader cannot infer from the code is whether the run had got anywhere, so that
    is what the phases distinguish.
    """

    #: gda ended the run at ``--timeout`` and the engine had written NOTHING to
    #: either stream. Rare in practice and deliberately narrow: Godot prints its
    #: version banner within ~0.1s of a normal spawn (measured), so this marks the
    #: engine never reaching its own startup output — a wrapper that did not exec,
    #: or a hang before stdio.
    LAUNCHED = "launched"
    #: gda ended the run at ``--timeout`` after output had appeared. The usual
    #: timeout phase: the run was alive and did not finish, so the captured tail is
    #: how far it got and ``--timeout`` is the knob.
    OUTPUT_SEEN = "output_seen"
    #: gda ended the run EARLY, before ``--timeout``: a script error appeared, the
    #: declared completion marker did not, and the run went silent.
    ABORTED_ON_ERROR = "aborted_on_error"


def _entry_attributable(errors: list[ScriptError], entry: str) -> bool:
    """Does any recognized error say the ENTRY script itself is in trouble (#655)?

    The arming condition of :class:`_CompletionMarkerWatch`, and it reuses the
    classification that already exists rather than inventing a second reading of the
    same stderr:

    - :func:`gda.script_errors.entry_load_failure` covers every kind that proves the
      entry never ran — missing, uncompilable, not a ``SceneTree``/``MainLoop``, or
      the resource-layer cascade behind those — already matched on the canonical
      ``res://`` identity, on both sides;
    - plus a ``RUNTIME_ERROR`` naming the entry, which that function excludes **by
      construction** (it is the one kind proving the script DID run) and which is
      exactly the dogfooded case: an error raised inside the entry's own
      ``_initialize`` aborts it before its ``quit()``.

    Attribution is what keeps a *survivable* failure from arming the abort at all. A
    running script that merely ``load()``s a missing ``.tres``, or whose helper
    script fails, produces the same engine sentences for a DIFFERENT path — and the
    e2e suite pins such runs as successes. Only the entry's own trouble is grounds
    to start the silence window at all; what authorises the kill is the caller's
    declared contract (see :class:`_CompletionMarkerWatch`), not an inference that
    the run cannot continue — a runtime error aborts one function, not necessarily
    the run, and no observation from outside the process can tell the difference.
    """
    if entry_load_failure(errors, entry) is not None:
        return True
    return any(
        error.kind is ScriptErrorKind.RUNTIME_ERROR
        and error.path is not None
        and canonical_res_path(error.path) == entry
        for error in errors
    )


class _CompletionMarkerWatch:
    """``script run``'s :class:`~gda.runner.LaunchWatch`: end a run that died (#655).

    The POLICY half of the streaming launch — the primitive owns the mechanism (see
    :class:`gda.runner.LaunchWatch`) and this owns what the output MEANS. It is
    here, in the ``script`` group, because that meaning is this command's domain
    knowledge and no other channel's.

    Killing a run is destructive and unrecoverable, and whether a run that printed
    an error can still finish is **not observable from outside the process**:
    review falsified every observational stand-in tried here. Silence alone killed
    a script computing quietly after a survivable error; a CPU-idleness probe was
    indistinguishable from a run blocked in a legitimate wait (``OS.execute``, an
    ``await`` — alive, but consuming nothing), and on a host where CPU time cannot
    be read it silently forfeited the seconds-bound the issue promises. So this
    watch does not CLAIM to detect death. It enforces the contract issue #655
    defines (in its 2026-08-18 amendment, which replaced the undecidable "fatal
    error" wording) and the caller opted into by declaring a marker: *the script signals
    completion with the marker line and keeps producing output until then; an
    entry-attributable error followed by sustained total silence without the
    marker means the run is dead* — by declaration, not inference. That makes the
    abort a pure function of the observed text and the clock: deterministic,
    identical on every platform, and honest about what it knows. All three
    conditions must hold:

    1. a recognized error attributable to the **entry script** appeared on stderr —
       see :func:`_entry_attributable`, which reuses
       :func:`gda.script_errors.entry_load_failure` and the canonical ``res://``
       identity, so the abort recognizes exactly the sentences the rest of
       ``script run`` does and nothing is parsed twice in two ways. An error about
       some *other* resource says nothing about the entry's fate; warnings are not
       errors and are already skipped by the shared parser;
    2. the caller's **declared marker** has not appeared. This is the opt-in:
       ADR-0031 rejected imposing a gda-owned sentinel wrapper on a user-authored
       entry script, so gda cannot know a run "should" have finished — only the
       caller can say what finishing looks like. With no marker declared, this
       watch NEVER aborts and the launch simply gains its captured output;
    3. neither stream has produced output for
       :data:`SCRIPT_RUN_ABORT_SILENCE_SECONDS` — the contract's liveness bound.
       Any output line resets it, which is the compliant escape hatch for a script
       with long quiet stretches: print progress, or omit the marker.

    The contract cuts both ways and the price is stated where the caller declares
    it (the ``--completion-marker`` help): a script that survives an
    entry-attributable error and then works past the bound in total silence is
    ended even though it would have finished. That is the declared semantics, not
    a detection error — the alternative heuristics that tried to save such a run
    are the ones review proved wrong in both directions.

    Marker matching is **whole-line equality** (both sides stripped), not a
    substring test. Substring matching made ``NOT DONE YET`` count as the marker
    ``DONE``, silently disarming the abort for a run that had in fact died — and the
    marker is defined as a LINE the script prints, so the line is the unit to
    compare. GDScript's ``print()`` always ends with a newline, so buffering to a
    line boundary is also what lets each byte be seen exactly once, keeping the
    watch linear in the output however chatty the run.

    Note this is NOT the ADR-0002 op-dispatch sentinel: that is gda's own contract
    with its own ``operations.gd`` payload, emitted on stdout and parsed for a
    structured result. This is a caller's arbitrary line, used for one boolean.
    """

    def __init__(
        self,
        completion_marker: str | None,
        *,
        entry: str,
        silence: float = SCRIPT_RUN_ABORT_SILENCE_SECONDS,
    ) -> None:
        # A marker that is blank once stripped would equal every blank line the run
        # prints and arm the abort on nothing, so it is treated as UNDECLARED. The
        # params model and the argv guard both refuse one, making this unreachable;
        # it is here so the hazard cannot be reintroduced from a third call site.
        stripped = completion_marker.strip() if completion_marker is not None else ""
        self._marker = stripped or None
        self._entry = canonical_res_path(entry)
        self._silence = silence
        self._partial: dict[str, str] = {"stdout": "", "stderr": ""}
        # A bounded tail of stderr lines, re-parsed as new ones arrive. A window,
        # not the whole stream, because the parse must stay linear overall; but a
        # window rather than only the newest batch because Godot writes an error as
        # SEVERAL lines (``ERROR:`` then ``at:`` then a backtrace) and a read syscall
        # can split them — parsing each batch alone would drop the ``at:`` frame that
        # carries the res:// path, and with it the attribution in (1).
        self._stderr_window: deque[str] = deque(maxlen=_STDERR_WINDOW_LINES)
        self._marker_seen = False
        self._error_seen = False
        self._last_output_at = 0.0

    def observe(self, *, stdout: str, stderr: str, elapsed: float) -> bool:
        if stdout or stderr:
            # Any output restarts the wait from scratch: under the declared
            # contract, a run that is still talking is not a run to kill.
            self._last_output_at = elapsed
        for stream, text in (("stdout", stdout), ("stderr", stderr)):
            if not text:
                continue
            lines = self._complete_lines(stream, text)
            if not lines:
                continue
            if self._marker is not None and any(
                line.strip() == self._marker for line in lines
            ):
                self._marker_seen = True
            if stream == "stderr" and not self._error_seen:
                self._stderr_window.extend(lines)
                errors = parse_script_errors("\n".join(self._stderr_window))
                self._error_seen = _entry_attributable(errors, self._entry)
        return self._should_abort(elapsed)

    def _should_abort(self, elapsed: float) -> bool:
        """Conditions (2) and (3) — see the class docstring for why each is required."""
        if self._marker is None or self._marker_seen or not self._error_seen:
            return False
        return elapsed - self._last_output_at >= self._silence

    def _complete_lines(self, stream: str, text: str) -> list[str]:
        """The newly-completed lines of one stream; the trailing partial is held.

        Splitting on ``"\\n"`` rather than using ``str.splitlines`` because only the
        split can tell a COMPLETE final line from a partial one: ``"a\\nb"`` and
        ``"a\\nb\\n"`` both give ``["a", "b"]`` from ``splitlines``, so a fragment a
        read syscall stopped mid-line would be consumed as though it were whole — and
        the marker or error record continuing on the next feed would never match.
        ``split("\\n")`` puts that fragment last, which is exactly what ``parts.pop()``
        holds back for the next feed. (It also leaves ``\\v`` / ``\\x1c`` /
        ``\\u2028`` alone, which ``splitlines`` breaks on and the engine's
        line-oriented format never uses.)
        """
        buffered = self._partial[stream] + text
        parts = buffered.split("\n")
        self._partial[stream] = parts.pop()
        return parts


# The verdict each proven entry-load failure maps to (#651). Two of the three codes
# are REUSED from ``script attach`` rather than duplicated, because the conditions
# are the ones it already names (ADR-0002 — reuse the code, discriminate via the
# message):
#
# - ``script_compile_failed`` — this script does not compile. The engine's explicit
#   load-failure sentence (COMPILE_FAILED), the parse diagnostic behind it
#   (PARSE_ERROR), and the generic give-up (LOAD_FAILED) all land here: whichever
#   sentence the engine chose, what gda knows is that the entry could not be loaded
#   or compiled.
# - ``incompatible_script_type`` — this script compiles, but its base type is wrong
#   for the requested use. ``script attach`` means "wrong for the target node";
#   ``script run`` means "does not extend SceneTree/MainLoop, so it cannot be a
#   one-shot entry point". Same condition, different target.
#
# Every kind in ``_ENTRY_FAILURE_PRECEDENCE`` MUST have a row here — a missing row
# would be a KeyError on a real failure path, so a test pins the two in lockstep.
_ENTRY_FAILURE_CODES: dict[ScriptErrorKind, str] = {
    ScriptErrorKind.SCRIPT_MISSING: "script_not_found",
    ScriptErrorKind.COMPILE_FAILED: "script_compile_failed",
    ScriptErrorKind.PARSE_ERROR: "script_compile_failed",
    ScriptErrorKind.LOAD_FAILED: "script_compile_failed",
    ScriptErrorKind.RESOURCE_LOAD_FAILED: "script_compile_failed",
    ScriptErrorKind.NOT_A_MAIN_LOOP: "incompatible_script_type",
}


def run_script_run_operation(
    *,
    script: str,
    godot: Optional[str],
    project: Optional[Path],
    strict: bool = False,
    make_launch: Optional[LaunchFn] = None,
    timeout: float = DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
    completion_marker: Optional[str] = None,
) -> ScriptRunResult | Failure:
    """Run ``script run``'s validate → launch → classify recipe (ADR-0031, #651, #675).

    ``script`` is the user script in either accepted form — project-relative or
    ``res://`` (#675); both are folded onto one canonical ``res://`` address before
    the launch, and that address is what the result reports.

    Returns its outcome instead of emitting or exiting: the passthrough
    :class:`ScriptRunResult` on a completed run (even a non-zero ``exit_status``)
    or a :class:`~gda.errors.Failure` — a pre-run ABI-edge failure
    (``invalid_path`` / ``project_not_found``), a ``classify_launch_or_crash``
    env/crash outcome, the ``script_not_found`` / ``script_compile_failed`` verdict
    for a script the engine never ran, the ``launch_timeout`` / ``script_aborted``
    verdict for a run gda ENDED (#655), or — with ``strict`` — ``script_failed`` for
    a completed run that chose a non-zero status. ``project`` is the
    already-resolved directory (resolution stays CLI-side, ADR-0006); ``None``
    means none resolved. ``make_launch`` is the injected headless-launch seam;
    ``None`` (the default) uses the real deep-module :func:`gda.runner.launch`,
    resolved at call time — the ``screen`` group's idiom — so a test can inject a fake
    OR patch ``gda.commands.script.launch``.

    ``timeout`` is the caller's ceiling and ``completion_marker`` its opt-in
    early-termination declaration (#655); both come from the params model, so the
    argv and ``--params-json`` paths behave identically (ADR-0015).
    """
    run_launch = make_launch or launch
    # Pre-run ABI edges (ADR-0031), decided BEFORE any launch so they never surface
    # as a crash or a raw engine failure. Path first (it is the direct argument).
    #
    # ONE gate does both halves of the path edge (ADR-0031 amendment, #675): it
    # ACCEPTS the two portable forms — the project-relative path the rest of the
    # script group also takes, and the res:// address — and REFUSES everything that
    # is not a project-scoped script address. What it returns is the single canonical
    # resource identity for the rest of this operation (#651 review claim 1, extended
    # to both forms): fixed HERE, at the input boundary, so the argv handed to the
    # engine and every later comparison and message use the same spelling. The engine
    # canonicalizes internally before it names a path in an error, so a raw
    # `res://dir/../bad.gd` would never match the `res://bad.gd` it reports back — and
    # the entry-load verdict would silently fall through to a phantom success. The
    # raw `script` is kept for the refusal message, so it still quotes what the user
    # actually typed.
    canonical = _project_scoped_res_path(script)
    if canonical is None:
        return script_path_invalid_failure(script)
    # Then require a resolved project — BOTH accepted forms resolve against one.
    if project is None:
        return script_run_project_not_found_failure()
    script = canonical

    try:
        binary = resolve_godot_binary(godot)
    except ValueError as exc:
        # An empty ``--godot ""`` (a natural $GDA_GODOT mistake) makes resolution
        # raise before a launch — the same environment failure as a missing binary,
        # mapped to the structured envelope so it never escapes as a raw traceback
        # (mirrors gda.headless.execute's binary resolution, #33).
        return unresolvable_binary_failure(str(exc))

    # Build only this channel's argv tail — the user script under the resolved
    # project — and delegate the spawn / timeout / OSError / UTF-8-decode handling
    # to the shared launch primitive (the deep module, reused not re-implemented).
    # cwd=None mirrors the sentinel SubprocessGodotRunner: a res:// script resolves
    # via --path, so no working directory is needed (unlike the export channel,
    # whose relative output path needs cwd=project).
    args = ["--path", str(project), "--script", script]
    # Pass a watch, which is what switches the shared primitive from buffered
    # capture to STREAMING capture (#655): whatever the run produced survives a
    # timeout, the wall clock is measured, and — only when the caller declared a
    # completion marker — a run whose script died can be ended in seconds instead
    # of at the ceiling. The watch is inert without a marker, so the no-marker
    # invocation gains the captured output and nothing else.
    raw = run_launch(
        binary,
        args,
        cwd=None,
        timeout=timeout,
        timeout_label="Godot script",
        watch=_CompletionMarkerWatch(completion_marker, entry=script),
    )

    # A run gda ENDED is classified here rather than by the shared
    # classify_launch_or_crash prefix, because only this channel has what those two
    # envelopes carry: the captured partial output, the elapsed clock, and the
    # script errors read with this command's own parser (#655). The shared prefix
    # still owns everything else — a missing binary, an unusable placement, a signal
    # death — so the two channels stay identical on those.
    ended = _classify_ended_run(
        raw,
        script=script,
        timeout=timeout,
        completion_marker=completion_marker,
    )
    if ended is not None:
        return ended

    # Bifurcate by whose failure it is (ADR-0031): a launch failure or a signal
    # death (exit_code < 0) is a gda-/engine-level Error envelope, classified by the
    # SAME shared prefix the export channel uses. Everything else — a clean engine
    # exit, INCLUDING a non-zero exit_status — is a success passthrough.
    crash = classify_launch_or_crash(raw, binary)
    if crash is not None:
        return crash

    # The engine exited normally, so the exit status is ITS answer — but the engine
    # answers 0 whether the script ran or was never loadable at all. Read the stderr
    # evidence before trusting the status (#651): a proven entry-load failure means
    # the passthrough has nothing to pass through, so it is a gda verdict, not data.
    diagnostics = parse_script_errors(raw.stderr)
    did_not_run = entry_load_failure(diagnostics, script)
    if did_not_run is not None:
        return script_did_not_run_failure(
            _ENTRY_FAILURE_CODES[did_not_run.kind],
            script,
            did_not_run.message,
            raw.stderr,
        )

    # The script RAN. Its own status is data by default (the ADR-0031 crux) and a
    # gda failure only when the caller opted in with --strict.
    if strict and raw.exit_code != 0:
        return script_exit_status_failure(script, raw.exit_code, raw.stdout, raw.stderr)

    # The public promotion of the internal Raw run: the thin boundary DTO built by
    # dropping launch_failure (lifted into the Error envelope above) and renaming
    # exit_code → exit_status, plus the parsed diagnostics. This is the one success
    # result that can be non-zero.
    return ScriptRunResult(
        path=script,
        exit_status=raw.exit_code,
        stdout=raw.stdout,
        stderr=raw.stderr,
        diagnostics=diagnostics,
    )


def _classify_ended_run(
    raw: RunResult,
    *,
    script: str,
    timeout: float,
    completion_marker: Optional[str],
) -> Failure | None:
    """The envelope for a run GDA ended — timeout or early abort — else ``None`` (#655).

    Both outcomes are the same kind of thing: the engine never gave an answer,
    because gda stopped waiting for one. What the caller then needs is not the bare
    fact of stopping but the EVIDENCE — the output the run had already produced, how
    long it ran, how far it got, and any script error the engine had already printed.
    Dogfooding had a run whose error was on stderr within a second and a 120s
    envelope that contained only "timed out" (GDA-DF-012), and a healthy suite that
    outgrew its ceiling and looked identical to a hang (GDA-DF-032).

    All of it is PROSE in the message and ``diagnostics``. Structured envelope
    fields would change ADR-0004's uniform failure ABI; **#687 owns that decision**,
    and ADR-0031's amendment records that this path adopts its outcome. Do not add
    envelope fields here.

    The recognized script errors are read with the SAME parser stack the rest of
    ``script run`` uses — :mod:`gda.engine_log` through
    :func:`gda.script_errors.parse_script_errors` — over the partial stderr, so the
    lines an agent sees on a timeout are the ones it sees on a completed run. What
    is deliberately NOT done is re-verdicting: a captured ``script_missing`` or
    ``not_a_main_loop`` error stays a diagnostic under the timeout envelope rather
    than being promoted to the entry-load verdict, because ADR-0031 records that
    shape as reaching a failure "by another route" and narrowing it is a separate
    decision.
    """
    if raw.launch_failure is LaunchFailure.ABORTED:
        # Only the watch produces this, and it can only abort with a marker declared,
        # so ``completion_marker`` is set in every reachable case. It is still passed
        # as OPTIONAL rather than asserted: an assert here would be a crash on a
        # boundary value (and would vanish under ``-O``), and the builder can name the
        # condition truthfully without the string — so an unreachable state degrades
        # to slightly vaguer prose instead of killing the command.
        return script_run_aborted_failure(
            script,
            marker=completion_marker,
            timeout=timeout,
            elapsed=_elapsed(raw, at_least=SCRIPT_RUN_ABORT_SILENCE_SECONDS),
            silence=SCRIPT_RUN_ABORT_SILENCE_SECONDS,
            phase=TerminationPhase.ABORTED_ON_ERROR.value,
            script_errors=_render_captured_errors(raw.stderr),
            stdout=raw.stdout,
            stderr=raw.stderr,
        )
    if raw.launch_failure is LaunchFailure.TIMEOUT:
        return script_run_timeout_failure(
            script,
            timeout=timeout,
            elapsed=_elapsed(raw, at_least=timeout),
            phase=_timeout_phase(raw).value,
            script_errors=_render_captured_errors(raw.stderr),
            stdout=raw.stdout,
            stderr=raw.stderr,
        )
    return None


def _elapsed(raw: RunResult, *, at_least: float) -> float:
    """The run's MEASURED wall clock, or ``at_least`` when it was not measured.

    The streaming capture — the only strategy that produces these two envelopes —
    always measures the clock, so the fallback is for a hand-built
    :class:`~gda.runner.RunResult` (the injected test seam). It exists so an
    unmeasured run is never reported as ``0.00s``, which would read as "ended
    instantly" rather than "not measured".

    Each call site passes the truthful LOWER BOUND its own rule guarantees, which is
    why the value is the caller's rather than a constant here: a timeout ran at least
    as long as the ceiling it reached, and an abort waited out at least the silence
    window that triggered it.
    """
    return raw.elapsed_seconds if raw.elapsed_seconds is not None else at_least


def _timeout_phase(raw: RunResult) -> TerminationPhase:
    """Which timeout phase a gda-ended run reached — see :class:`TerminationPhase`.

    Keyed on whether the engine wrote ANYTHING, which is the only honest signal the
    capture carries. It is not "did the script start": Godot prints its own version
    banner to stdout within ~0.1s of a normal spawn (measured against 4.6.3), so
    output arriving does not prove the entry script ran — only that the engine
    reached its startup. That is still the distinction worth reporting, because its
    absence means the engine never got that far.
    """
    return (
        TerminationPhase.OUTPUT_SEEN
        if raw.stdout or raw.stderr
        else TerminationPhase.LAUNCHED
    )


def _render_captured_errors(stderr: str) -> str:
    """The recognized script errors of a partial capture, as ``diagnostics`` lines.

    Reuses :func:`gda.script_errors.parse_script_errors` and the SAME
    ``<kind>: <path>:<line>: <message>`` layout the human renderer uses for a
    successful run's structured diagnostics, so the curated high-signal lines read
    identically whether they arrive typed (on a success) or as prose (on a
    gda-ended run, where ADR-0004's ``diagnostics`` is a plain string). Empty when
    the engine printed nothing this module recognizes.
    """
    errors = parse_script_errors(stderr)
    if not errors:
        return ""
    return "".join(
        f"gda:   {error.kind.value}: {_render_script_error_location(error)}\n"
        for error in errors
    )


# A `SCRIPT ERROR: <message>` line and the `GDScript::reload (...:<line>)` frame
# that follows it carry, between them, the one advisory diagnostic the engine
# emits for a failed validate (issue #118). The line number is the final `:`
# part of the reload frame; there is NO column on the standard build.
# `[ \t]` (not `\s`) bounds the message capture so it cannot span newlines — an
# empty SCRIPT ERROR message must not swallow the following reload frame.
# Backtrace frames (`[n] _initialize (...)`) are operations.gd's own lines, not
# the validated script's, so they are deliberately not matched.
_SCRIPT_ERROR_LINE = re.compile(
    r"^[ \t]*SCRIPT ERROR:[ \t]*(?P<message>.*?)[ \t]*$", re.MULTILINE
)
_RELOAD_FRAME = re.compile(r"GDScript::reload \([^)]*:(?P<line>\d+)\)")


def parse_validate_diagnostics(stderr: str) -> list[ScriptDiagnostic]:
    """Parse advisory ``script validate`` diagnostics from the engine's stderr.

    A pure function (no engine, no I/O): the line/message of a failed
    ``GDScript.reload()`` are available only from stderr, not from any bound API
    (ADR-0002's stderr is advisory only — it is never parsed for the stable
    success/failure outcome or error codes, only surfaced here as best-effort
    diagnostics). ``column`` is always null (the engine exposes none).

    The validate op does exactly ONE ``reload()``, so the only legitimate
    ``GDScript::reload`` frame in stderr is the validated script's. Each
    ``SCRIPT ERROR: <message>`` line is paired with a reload frame found ONLY in
    the window up to the next ``SCRIPT ERROR`` line, and a ``SCRIPT ERROR`` with
    no reload frame in that window is dropped: bounding the search keeps a later
    error's frame from being mis-attributed to an earlier message, and the
    frame requirement excludes unrelated engine ``SCRIPT ERROR`` noise — e.g. an
    autoload's own startup error under ``--project``, whose frame is its
    ``_init``/``_ready``, not ``GDScript::reload``. Returns ``[]`` when nothing
    matches.
    """
    matches = list(_SCRIPT_ERROR_LINE.finditer(stderr))
    diagnostics: list[ScriptDiagnostic] = []
    for index, match in enumerate(matches):
        window_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(stderr)
        )
        frame = _RELOAD_FRAME.search(stderr, match.end(), window_end)
        if frame is None:
            continue
        diagnostics.append(
            ScriptDiagnostic(
                line=int(frame.group("line")),
                column=None,
                message=match.group("message"),
            )
        )
    return diagnostics


def classify_script_validate(
    result: RunResult, binary: Path
) -> ScriptValidateResult | Failure:
    """Classify the raw ``script validate`` result (issue #118).

    The per-command layer for ``script validate``: the shared decision tree comes
    from ``classify_run`` (an op error — missing path, wrong extension,
    unreadable file — is still a ``Failure``). For a SUCCESSFUL op reporting an
    invalid script (``valid=false``), the line/message diagnostics are not in the
    sentinel — they live only in the engine's stderr — so this layer parses them
    in and attaches them to the result.
    """
    outcome = classify_run(result, binary, ScriptValidateResult)
    if isinstance(outcome, Failure):
        return outcome
    if not outcome.valid:
        outcome.diagnostics = parse_validate_diagnostics(result.stderr)
    return outcome


@runtime_checkable
class ScriptMetadata(Protocol):
    """The shared human-facing surface of every script result type.

    A structural (typing-only) interface — fields, no methods — over the
    ``path``/``class_name``/``extends`` that :class:`ScriptCreateResult`,
    :class:`ScriptGetResult`, :class:`ListedScript`,
    :class:`ScriptDeleteResult` and :class:`ScriptSetResult`
    all carry. The metadata renderer types against this surface, so adding a
    script result type that carries the same fields needs no renderer change and
    the renderer never reads across a union. It is a ``Protocol`` rather than a
    shared base model so it imposes nothing on the models' JSON Schema or field
    order (the ``--schema`` contract stays byte-for-byte unchanged).
    """

    path: str
    class_name: str | None
    extends: str | None


def render_script_metadata(script: ScriptMetadata) -> str:
    """Render a script's path plus its class_name/extends for humans.

    Reads the shared :class:`ScriptMetadata` surface, so it serves every script
    result type without naming the union.
    """
    meta = []
    if script.extends is not None:
        meta.append(f"extends {script.extends}")
    if script.class_name is not None:
        meta.append(f"class_name {script.class_name}")
    if not meta:
        return script.path
    return f"{script.path} ({', '.join(meta)})"


def render_script_create(created: "ScriptCreateResult") -> str:
    """Render a created script as ``created <metadata>``."""
    return f"created {render_script_metadata(created)}"


def render_script_get(got: "ScriptGetResult") -> str:
    """Render a read script as its metadata line followed by its source."""
    return "\n".join([render_script_metadata(got), got.source])


def render_script_list(listed: "ScriptListResult") -> str:
    """Render the enumerated scripts as ``path (extends X, class_name Y)`` lines."""
    if not listed.scripts:
        return "(no scripts)"
    return "\n".join(render_script_metadata(script) for script in listed.scripts)


def render_script_delete(removed: "ScriptDeleteResult") -> str:
    """Render a deleted script as ``deleted <metadata>``."""
    return f"deleted {render_script_metadata(removed)}"


def render_script_set(edited: "ScriptSetResult") -> str:
    """Render an edited script as ``set <metadata>``."""
    return f"set {render_script_metadata(edited)}"


def render_script_attach(attached: "ScriptAttachResult") -> str:
    """Render an attached script as ``attached <script> to <node> in <scene>``."""
    return f"attached {attached.script} to {attached.node} in {attached.scene_path}"


def render_script_validate(validated: "ScriptValidateResult") -> str:
    """Render a validate result: valid/invalid plus best-effort diagnostics.

    An INVALID verdict leads with the project the script was compiled against
    (#658), before the diagnostics rather than after them: when the root is the
    wrong one, every diagnostic below it is an artefact of that single mistake,
    and the reader needs to see the cause before the cascade. A valid verdict
    stays the one-line answer — the root only explains a failure.
    """
    if validated.valid:
        return f"valid {validated.path}"
    lines = [f"invalid {validated.path}"]
    root = validated.project_root or "(none resolved: projectless)"
    lines.append(f"  project: {root}")
    if validated.error_string is not None:
        lines.append(f"  {validated.error_string}")
    for diag in validated.diagnostics:
        location = f"line {diag.line}" if diag.line is not None else "unknown line"
        lines.append(f"  {location}: {diag.message}")
    return "\n".join(lines)


def render_script_run(ran: "ScriptRunResult") -> str:
    """Render a passed-through script run: its exit status then its captured output.

    ``script run`` passes the user script's own output through verbatim (ADR-0031),
    so the human view leads with the ``exit_status`` — which can be non-zero on a
    SUCCESS (a deliberate ``quit(1)``) — then the script's stdout and stderr as it
    emitted them (each trailing newline trimmed; empty streams are omitted). Any
    recognized script errors follow as a short classified summary (#651): the
    verbatim lines are already in the stderr block above, so this adds only the
    ``kind`` and location a reader would otherwise have to infer.
    """
    parts = [f"exit_status: {ran.exit_status}"]
    if ran.stdout:
        parts.append(ran.stdout.rstrip("\n"))
    if ran.stderr:
        parts.append(ran.stderr.rstrip("\n"))
    for diag in ran.diagnostics:
        parts.append(f"  {diag.kind.value}: {_render_script_error_location(diag)}")
    return "\n".join(parts)


def _render_script_error_location(diag: "ScriptError") -> str:
    """``<path>:<line>: <message>`` for a diagnostic, dropping the parts it lacks."""
    where = diag.path or ""
    if diag.path is not None and diag.line is not None:
        where = f"{diag.path}:{diag.line}"
    return f"{where}: {diag.message}" if where else diag.message


SCRIPT_CREATE_COMMAND: HeadlessCommand[ScriptCreateResult] = HeadlessCommand(
    operation="script-create",
    input_model=ScriptCreateParams,
    output_model=ScriptCreateResult,
    render=render_script_create,
)

SCRIPT_GET_COMMAND: HeadlessCommand[ScriptGetResult] = HeadlessCommand(
    operation="script-get",
    input_model=ScriptGetParams,
    output_model=ScriptGetResult,
    render=render_script_get,
)

SCRIPT_LIST_COMMAND: HeadlessCommand[ScriptListResult] = HeadlessCommand(
    operation="script-list",
    input_model=ScriptListParams,
    output_model=ScriptListResult,
    render=render_script_list,
)

SCRIPT_DELETE_COMMAND: HeadlessCommand[ScriptDeleteResult] = HeadlessCommand(
    operation="script-delete",
    input_model=ScriptDeleteParams,
    output_model=ScriptDeleteResult,
    render=render_script_delete,
)

SCRIPT_SET_COMMAND: HeadlessCommand[ScriptSetResult] = HeadlessCommand(
    operation="script-set",
    input_model=ScriptSetParams,
    output_model=ScriptSetResult,
    render=render_script_set,
)

SCRIPT_ATTACH_COMMAND: HeadlessCommand[ScriptAttachResult] = HeadlessCommand(
    operation="script-attach",
    input_model=ScriptAttachParams,
    output_model=ScriptAttachResult,
    render=render_script_attach,
)


def _script_validate_recipe(
    params: ScriptValidateParams,
    *,
    project: Optional[Path],
    godot: Optional[str],
) -> ScriptValidateResult | Failure:
    """Refuse → compile → report the root: ``script validate``'s recipe (#658).

    The sentinel op still does the compiling (``cmd.execute``, as the export
    recipe runs its preflight); this wraps it in the two decisions only the CLI
    can make, because ADR-0006 keeps project resolution CLI-side and the engine
    is TOLD the project through ``--path``, never asked about it.

    First the refusal. A script outside the resolved project is refused HERE,
    before the engine is spawned, so the false ``res://`` dependency cascade is
    never produced (see :func:`~gda.errors.script_outside_project_failure`).
    Only a *resolved* project can be missed, so projectless is not a refusal:
    with no project resolved, gda validates a standalone script by filesystem
    path exactly as before (ADR-0006's projectless fallback). Whether the script
    belongs to some OTHER project is not asked — deriving a project from the
    target path is what ADR-0006 rejected, and discovering the nearest
    ``project.godot`` waits on an amendment to it.

    Then the report: the resolved project is stamped onto the result as
    ``project_root``, so a caller reading a ``valid=false`` verdict sees which
    root the ``res://`` dependencies resolved against instead of inferring it.
    Both the report and the refusal name the project in its RESOLVED form: the
    flag may be spelled relatively (``--project game``), and a bare ``game`` in a
    machine-readable result or in a "this is outside that" message tells the
    reader nothing about which directory was meant.

    ``project`` arrives ALREADY resolved from ``dispatch_recipe`` (an invalid
    ``--project``/``$GDA_PROJECT`` became a structured ``project_not_found``
    before this runs, #353); ``None`` means projectless. ``params`` is the model
    built once by the caller, identical on the argv and ``--params-json`` paths
    (ADR-0015).
    """
    root = None
    if project is not None:
        root = project.expanduser().resolve()
        outside = path_outside_project(params.path, project)
        if outside is not None:
            return script_outside_project_failure(outside, root)
    # The runner seam is read off the module at call time — never imported by
    # name — so a test monkeypatch on ``gda.dispatch.make_runner`` still binds.
    # Naming the HEADLESS factory directly is correct only while this command is
    # HEADLESS: unlike ``gda.dispatch._emit``, which picks the factory from
    # ``cmd.kind``, a recipe states its own channel. Changing this command's
    # ``kind`` (or reusing this recipe for a live twin) must change this line
    # too — the descriptor would otherwise say one channel and the run take
    # another. The registry invariant test pins the recipe set, not this pairing.
    outcome = SCRIPT_VALIDATE_COMMAND.execute(
        params,
        godot=godot,
        project=project,
        make_runner=dispatch.make_runner,
    )
    if isinstance(outcome, Failure):
        return outcome
    # A copy, not an in-place set: the classified result is the engine's answer,
    # and ``project_root`` is gda's addition to it, so the union is built rather
    # than the parsed model mutated after validation.
    return outcome.model_copy(
        update={"project_root": str(root) if root is not None else None}
    )


# ``script validate`` stays a HEADLESS sentinel op — the engine does the
# compiling — but carries a ``recipe`` (ADR-0023) because two parts of its
# contract are decided at the CLI, where ADR-0006's resolved project lives: the
# outside-the-project refusal and the ``project_root`` on the result. The recipe
# channel is the ONE descriptor-driven hook both input paths share, so argv and
# ``--params-json`` get the same behaviour (ADR-0015) without the shared dispatch
# tail learning anything about this command. ``classify`` is untouched: the recipe
# runs the same ``cmd.execute``, so the stderr diagnostics are still parsed in by
# :func:`classify_script_validate`.
SCRIPT_VALIDATE_COMMAND: HeadlessCommand[ScriptValidateResult] = HeadlessCommand(
    operation="script-validate",
    input_model=ScriptValidateParams,
    output_model=ScriptValidateResult,
    render=render_script_validate,
    classify=classify_script_validate,
    recipe=_script_validate_recipe,
)


def _script_run_recipe(params, *, project, godot):
    # ``project`` arrives ALREADY resolved by dispatch_recipe — an invalid
    # --project/$GDA_PROJECT was converted to a structured project_not_found before
    # this runs, so no per-recipe ValueError handling is needed here (#353 folded in
    # script run's former try/except). A projectless None remains the op's own ABI
    # edge: run_script_run_operation returns script_run_project_not_found_failure()
    # for it (ADR-0031).
    return run_script_run_operation(
        script=params.path,
        godot=godot,
        project=project,
        strict=params.strict,
        timeout=params.timeout,
        completion_marker=params.completion_marker,
    )


# ``script run`` is the third execution shape (ADR-0031): a user-script passthrough
# run. Its entry script is the user's own, so it emits no ADR-0002 sentinel, and gda
# does not know the script's semantics — so it routes through the recipe channel
# (ADR-0023) like ``export run``, and carries the fourth ``SCRIPT_RUN`` kind, which is
# self-description only (ADR-0004 / ADR-0012) — dispatch is by ``recipe``, adding no
# runner-selection branch. The descriptor lives with its group (ADR-0040 §1),
# beside the operation its recipe drives; project resolution stays in the shared
# dispatch tail (``gda.dispatch.dispatch_recipe``), so the recipe needs no seam of
# its own.
SCRIPT_RUN_COMMAND: HeadlessCommand[ScriptRunResult] = HeadlessCommand(
    operation="script-run",
    input_model=ScriptRunParams,
    output_model=ScriptRunResult,
    kind=ExecutionKind.SCRIPT_RUN,
    render=render_script_run,
    recipe=_script_run_recipe,
)


# The script command group (issue #110): commands acting on .gd script files on
# disk (write text / read text back), so they stay headless. C# (.cs) is out of
# scope for now — it needs the .NET build of Godot (ADR-0003 targets the standard
# build) and a dedicated decision.
_app = typer.Typer(help="Act on script files (.gd).", no_args_is_help=True)


@_app.command(cls=SCRIPT_CREATE_COMMAND.command_class())
def create(
    path: str = typer.Argument(..., help="Target .gd script path to write."),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Verbatim script source to write. Mutually exclusive with --extends; "
            "when omitted, a minimal template extending --extends is written."
        ),
    ),
    extends_type: Optional[str] = typer.Option(
        None,
        "--extends",
        help=(
            "Base class for the built-in template's 'extends' line (e.g. Node, "
            "Node2D). Defaults to Node. Ignored — and rejected — with --content."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_CREATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Create a new .gd script from a template or verbatim --content."""
    if content is not None and extends_type is not None:
        raise typer.BadParameter("--content and --extends are mutually exclusive.")
    dispatch_domain(
        SCRIPT_CREATE_COMMAND,
        ScriptCreateParams(
            path=path,
            content=content,
            extends_type=extends_type,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="get", cls=SCRIPT_GET_COMMAND.command_class())
def get_script(
    path: str = typer.Argument(..., help="The .gd script file to read."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_GET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Read a script's source and report its class_name/extends metadata."""
    dispatch_domain(
        SCRIPT_GET_COMMAND,
        ScriptGetParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="list", cls=SCRIPT_LIST_COMMAND.command_class())
def list_scripts(
    json_output: bool = json_option(),
    schema: bool = SCRIPT_LIST_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Enumerate the .gd scripts in the resolved project."""
    dispatch_domain(
        SCRIPT_LIST_COMMAND,
        ScriptListParams(),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="delete", cls=SCRIPT_DELETE_COMMAND.command_class())
def delete_script(
    path: str = typer.Argument(..., help="The .gd script file to delete."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_DELETE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Delete a script file and report what was removed."""
    dispatch_domain(
        SCRIPT_DELETE_COMMAND,
        ScriptDeleteParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="set", cls=SCRIPT_SET_COMMAND.command_class())
def set_script(
    path: str = typer.Argument(..., help="The .gd script file to edit."),
    search: Optional[str] = typer.Option(
        None,
        "--search",
        help=(
            "search-replace mode: literal substring to find (not regex); all "
            "occurrences are replaced. Requires --replace."
        ),
    ),
    replace: Optional[str] = typer.Option(
        None,
        "--replace",
        help="search-replace mode: literal replacement text. Requires --search.",
    ),
    start_line: Optional[int] = typer.Option(
        None,
        "--start-line",
        help=(
            "line-range mode: first line to replace (1-based, inclusive). "
            "Requires --content."
        ),
    ),
    end_line: Optional[int] = typer.Option(
        None,
        "--end-line",
        help=(
            "line-range mode: last line to replace (1-based, inclusive); "
            "defaults to --start-line. Requires --content and --start-line."
        ),
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help=(
            "Replacement text: the line span in line-range mode, or the whole "
            "file (full mode) when --start-line is omitted."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_SET_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Edit a .gd script via search-replace, line-range, or full overwrite."""
    mode = parse_set_mode_argv(search, replace, start_line, end_line, content)
    dispatch_domain(
        SCRIPT_SET_COMMAND,
        ScriptSetParams(
            path=path,
            mode=mode,
            search=search,
            replace=replace,
            start_line=start_line,
            end_line=end_line,
            content=content,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def parse_set_mode_argv(
    search: Optional[str],
    replace: Optional[str],
    start_line: Optional[int],
    end_line: Optional[int],
    content: Optional[str],
) -> ScriptSetMode:
    """Resolve a set command's edit mode for the argv path (issue #133).

    The rule itself lives in :func:`resolve_set_mode` — the single source shared
    with ``ScriptSetParams`` / ``ShaderSetParams`` (ADR-0015). This thin wrapper
    translates its ``ValueError`` into a Click usage error (exit 2) so the argv
    path keeps its usage-error ergonomics, while ``--params-json`` surfaces the
    same rule as a structured ``invalid_params`` via the model.
    """
    try:
        return resolve_set_mode(search, replace, start_line, end_line, content)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@_app.command(name="attach", cls=SCRIPT_ATTACH_COMMAND.command_class())
def attach_script(
    path: str = typer.Argument(..., help="The .tscn scene file to mutate."),
    node: str = typer.Option(
        ...,
        "--node",
        help=(
            "Node path, relative to the scene root: '.' addresses the root "
            "itself, 'Player/Arm' a nested node."
        ),
    ),
    script: str = typer.Option(
        ..., "--script", help="The .gd script file to attach to the node."
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_ATTACH_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Attach a .gd script to a node (by node path) in a scene and save."""
    dispatch_domain(
        SCRIPT_ATTACH_COMMAND,
        ScriptAttachParams(
            path=path,
            node=node,
            script=script,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="validate", cls=SCRIPT_VALIDATE_COMMAND.command_class())
def validate_script(
    path: str = typer.Argument(..., help="The .gd script file to validate."),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_VALIDATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Syntax/compile-check a .gd script; invalid exits 0 with valid=false.

    The script is compiled against the resolved project (ADR-0006: --project, then
    $GDA_PROJECT, then the current directory) — the root its res:// dependencies
    resolve against — and the result reports that root as 'project_root'. Read it
    before trusting a verdict: a script compiled against the wrong project reports
    every res:// dependency as missing, plus the type errors derived from them.

    A script OUTSIDE the resolved project is refused with 'project_not_found'
    before it is parsed, naming both the file and the project, rather than
    reporting that false cascade. gda never derives the project from the script's
    own path (ADR-0006), so pass --project for the project that owns the file.
    """
    dispatch_recipe(
        SCRIPT_VALIDATE_COMMAND,
        ScriptValidateParams(path=path),
        json_output=json_output,
        godot=godot,
        project=project,
    )


@_app.command(name="run", cls=SCRIPT_RUN_COMMAND.command_class())
def run_script(
    path: str = typer.Argument(
        ...,
        help=(
            "The script to run, project-relative (tests/logic.gd) or as a res:// "
            "path (res://tests/logic.gd). An absolute path, another engine scheme "
            "(user://, uid://), or a path naming or escaping above the project "
            "root is refused."
        ),
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Fail when the script exits non-zero: emit the 'script_failed' error "
            "envelope and exit 4 instead of the default passthrough success. For "
            "shell '&&' chains and CI gates. The envelope's message names the exit "
            "status and its diagnostics carry both script streams, labelled "
            "'--- script stdout ---' / '--- script stderr ---'. A script that never "
            "ran fails either way."
        ),
    ),
    timeout: float = typer.Option(
        DEFAULT_SCRIPT_RUN_TIMEOUT_SECONDS,
        "--timeout",
        help=(
            "Seconds to let the run take before gda ends it and reports "
            "'launch_timeout' with the captured output, the elapsed time and one "
            "termination phase: 'launched' (the engine wrote nothing), "
            "'output_seen' (alive but unfinished) or 'aborted_on_error' (ended by "
            "--completion-marker). Raise it for a suite that outgrew the default; "
            "lower it to fail fast."
        ),
    ),
    completion_marker: Optional[str] = typer.Option(
        None,
        "--completion-marker",
        help=(
            "Opt-in liveness contract: a line the script prints when its work is "
            "done, matched by WHOLE-LINE equality. Declaring it asserts the script "
            "keeps printing until that line — so gda reports 'script_aborted' with "
            "the captured error when all three hold: a recognized error "
            "attributable to the ENTRY script appears, this marker does not, and "
            "neither stream then produces output for "
            f"{SCRIPT_RUN_ABORT_SILENCE_SECONDS}s — landing in seconds, not the "
            "whole --timeout, on every platform alike. The contract cuts both "
            "ways: a script that goes quiet for longer after such an error is "
            "ended even if it would have finished, so print progress during long "
            "quiet stretches or omit the marker. Caller-declared: gda requires "
            "nothing in your script and injects nothing (it is NOT the op-dispatch "
            "sentinel). Omit it and gda waits out --timeout; a --timeout at or "
            f"below {SCRIPT_RUN_ABORT_SILENCE_SECONDS}s leaves the marker inert."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_RUN_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Run a user script one-shot and pass its exit_status/stdout/stderr through.

    Address the script in either portable form — project-relative
    (``tests/logic.gd``) or as a ``res://`` path — the same two the rest of the
    ``script`` group takes. Both resolve against the ``--project`` context and are
    reported back as one canonical ``res://`` ``path`` on the result. An absolute
    path, another engine scheme (``user://``, ``uid://``), and a path naming or
    escaping above the project root (``..``) are refused before any launch; note
    ``script validate`` does accept
    an absolute path, so the two commands are not at full parity.

    Runs the user's own script as ``godot --headless --path <project>
    --script <res://…>`` and returns its result verbatim (ADR-0031). This is the
    ONE command whose success result can carry a non-zero ``exit_status``: gda does
    not interpret the script's semantics, so a deliberate ``quit(1)`` (e.g. an
    assertion-failed logic-seam test) is data the agent reads, not a gda failure —
    read ``exit_status``, do not assume ``success == zero``. Pass ``--strict`` to
    invert that one default and get the ``script_failed`` envelope (exit 4) for a
    non-zero status, so a shell ``&&`` chain or CI gate stops on it; that envelope
    carries the script's own stdout and stderr in its ``diagnostics``.

    A script that never RAN is a failure either way. Godot reports these on stderr and
    still exits 0, so gda decides them from the engine's error stream, not its exit
    code: a missing res:// entry script is ``script_not_found``; an entry script (or a
    dependency it preloads) that fails to parse or compile is
    ``script_compile_failed``; and one that compiles but does not extend
    ``SceneTree``/``MainLoop``, so it cannot be an entry point at all, is
    ``incompatible_script_type`` — though that last shape may instead leave the engine
    idling with nothing on stderr, which surfaces as ``launch_timeout``. Recognized
    script errors — including a runtime GDScript error the script itself survived —
    are also surfaced as structured ``diagnostics`` on a successful result.

    Only a gda-/engine-level failure (binary not launchable, timeout, or a signal
    crash) is a ``binary_not_found`` / ``launch_timeout`` / ``engine_crashed``
    envelope. A path that is not a project-scoped script address, or no resolved
    project, is a structured ``invalid_path`` / ``project_not_found``.

    A run gda has to END reports what it captured, not just that it stopped:
    ``--timeout`` sets the ceiling, and the ``launch_timeout`` envelope carries the
    captured partial output, the elapsed seconds and a termination phase, so a
    suite that is merely slow is distinguishable from one that hung. For a script
    that DIES before its own ``quit()`` — a GDScript error aborts the function that
    raised it and the engine then idles — declare ``--completion-marker <line>``:
    gda ends that run within seconds and reports ``script_aborted`` with the error
    the engine had already printed, instead of waiting out the full ceiling. The
    marker is yours, not gda's: nothing is required of or injected into the script.
    The marker is a declared liveness contract, not a detector — gda arms it only
    on an error naming the ENTRY script, and the caller's declaration is what makes
    the following silence mean death; a script with long quiet stretches should
    print progress during them, or run without a marker.
    """
    # A FINITE positive ceiling, checked on both input paths (ADR-0015): the model
    # below enforces it for --params-json, this for argv. `inf` passes a bare `> 0`
    # test on both routes and then makes `elapsed >= timeout` unsatisfiable, so the
    # run gda promised to bound would never be bounded at all — the opposite of what
    # this option is for. `math.isfinite` rejects `nan` too, which compares false
    # against everything and fails the same way.
    if not math.isfinite(timeout) or timeout <= 0:
        raise typer.BadParameter("--timeout must be a finite number greater than 0.")
    # Blank (not merely empty) is refused: the marker is compared as a stripped
    # whole line, so a whitespace-only one would equal every blank line the run
    # prints and arm the abort on nothing.
    if completion_marker is not None and not completion_marker.strip():
        raise typer.BadParameter("--completion-marker must not be blank.")
    dispatch_recipe(
        SCRIPT_RUN_COMMAND,
        ScriptRunParams(
            path=path,
            strict=strict,
            timeout=timeout,
            completion_marker=completion_marker,
        ),
        json_output=json_output,
        godot=godot,
        project=project,
    )


def register(root: typer.Typer) -> None:
    """Mount the ``script`` group on the root app (ADR-0040).

    Mounting IS the registration: the live Typer tree stays the only registry
    (ADR-0012/0023), so no parallel table records this group.
    """
    root.add_typer(_app, name="script")
