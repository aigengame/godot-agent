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

import os
import re
import tempfile
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

import typer
from pydantic import BaseModel, Field, model_validator

from gda import dispatch
from gda.binary import resolve_godot_binary
from gda.dispatch import dispatch_domain, dispatch_recipe, params_or_bad_parameter
from gda.errors import (
    classify_launch_or_crash,
    classify_run,
    containment_refusal,
    Failure,
    make_failure,
    script_did_not_run_failure,
    script_escapes_project_failure,
    script_exit_status_failure,
    script_path_invalid_failure,
    script_run_aborted_failure,
    script_run_project_not_found_failure,
    script_run_timeout_failure,
    termination_phase,
    unresolvable_binary_failure,
)
from gda.engine_log import lines as engine_log_lines
from gda.execution import ExecutionKind
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
)
from gda.models import (
    CREATED_DIRS_DESC,
    NormalizedPath,
    ProjectRootedResult,
    TerminationPhase,
)
from gda.project import (
    RES_PREFIX,
    canonical_res_path,
    project_absolute,
    res_escape_remainder,
)
from gda.runner import LaunchFailure, LaunchFn, RunResult, launch
from gda.script_errors import (
    ScriptError,
    ScriptErrorKind,
    entry_load_failure,
    parse_script_errors,
    script_error_line,
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

    The params model derives exactly one mode from the supplied fields — via
    :func:`resolve_set_mode`, run once by the model's own ``_resolve_mode``
    validator on BOTH the argv and ``--params-json`` paths (ADR-0015, #713) —
    and stamps it here, so the operation dispatches on this explicit
    discriminator instead of re-inferring the mode from which params are
    present. The CLI is a thin argv-to-model adapter; it does not re-derive the
    mode itself, so the derivation cannot drift from the model's exclusivity
    rule.

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
    violation. Its only callers are the two params models' ``_resolve_mode``
    ``model_validator``s (:class:`ScriptSetParams` here, :class:`ShaderSetParams`
    in ``gda.commands.shader``) — so the rule runs exactly ONCE per invocation,
    on both commands (issue #713). The argv body builds that model through
    :func:`~gda.dispatch.params_or_bad_parameter`, which turns the raised error
    into the Click usage error (exit 2); ``--params-json`` builds the same model
    and surfaces it as the structured ``invalid_params`` instead.
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
    edit modes; the model derives which one and stamps it on ``mode`` (issue
    #133, ADR-0015) — the SAME derivation on both the argv and ``--params-json``
    paths (#713) — so the operation dispatches on that explicit discriminator
    rather than re-inferring it from which params are present:

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


def check_validate_selection(paths: list[str], all_scripts: bool) -> None:
    """Check ``script validate``'s target selection: a batch OR the whole project (#663).

    Exactly one selector must be given: at least one PATH, or ``--all``. Raises
    ``ValueError`` on a violation.

    It has ONE caller — :class:`ScriptValidateParams`'s validator — because the
    model is the input-rule authority (ADR-0015) and both input paths go through
    it: ``--params-json`` surfaces the raised error as the structured
    ``invalid_params``, and the argv body builds the same model through
    :func:`~gda.dispatch.params_or_bad_parameter`, which turns it into the Click
    usage error (exit 2). It stays a named function rather than inlined prose in
    the validator so the rule can be read, and tested, on its own.

    The naming deliberately departs from :func:`resolve_set_mode`, the sibling
    rule: that one collapses three flag combinations into one mode and RETURNS it,
    so there is something to resolve; here the two selectors are already the answer
    the operation runs on, and inventing a value to hand back would be ceremony.

    Both violations are worth naming separately. NEITHER is the unset-variable
    shape (``gda script validate $SCRIPTS`` with nothing to expand), which would
    otherwise reach the engine as an empty batch and report a vacuously valid
    verdict for zero scripts. BOTH is a contradiction rather than a precedence
    question: ``--all`` already covers every project script, so silently letting
    one selector win would hide which set was actually validated.
    """
    if all_scripts and paths:
        raise ValueError("PATH arguments and --all are mutually exclusive.")
    if not all_scripts and not paths:
        raise ValueError(
            "give at least one .gd PATH to validate, or --all for every script "
            "in the resolved project."
        )


class ScriptValidateParams(BaseModel):
    """The operation params of ``gda script validate``: the scripts to check (#118, #663).

    ``paths`` is the BATCH: one or more ``.gd`` scripts, each addressed by its
    ``res://`` or filesystem path. The whole batch is validated in ONE engine
    launch, so validating the four-to-six related scripts a change usually touches
    costs one process instead of one each (#663). A single path is simply a batch
    of one — there is no second code path. ``all_scripts`` (the ``--all`` flag) is
    the project-wide alternative: the engine enumerates every ``.gd`` under the
    resolved project's ``res://`` tree and validates that set instead, so it needs
    a resolved project (``project_not_found`` otherwise, exactly as ``script
    list`` does). Exactly one of the two selectors is given
    (:func:`check_validate_selection`).

    A path given twice is validated twice and reported twice: gda never silently
    drops an input, so result entry *i* always corresponds to requested path *i*.

    Unlike the other script-file ops, validate DOES compile each script (it sets
    the source on a fresh ``GDScript`` and reloads it to learn whether it parses),
    but it never instantiates the script, so it does not run instance code. Pass
    ``--project`` when a script extends a project ``class_name`` or preloads a
    project resource and so needs project context to compile.
    """

    paths: list[NormalizedPath] = Field(
        default_factory=list,
        description=(
            "The .gd script files to validate, as one batch in a single engine "
            "launch. A repeated path is validated and reported once per "
            "occurrence. EXACTLY ONE selector must be given — a non-empty 'paths' "
            "or 'all_scripts' — which JSON Schema cannot express across two "
            "fields, so an empty or contradictory selection is refused by "
            "validation ('invalid_params') rather than by the schema."
        ),
    )
    all_scripts: bool = Field(
        default=False,
        description=(
            "Validate every .gd script in the resolved project instead of a "
            "named batch (the --all flag). Mutually exclusive with 'paths', and "
            "requires a resolved project."
        ),
    )

    @model_validator(mode="after")
    def _one_selector(self) -> "ScriptValidateParams":
        # Model-side (ADR-0015) so the --params-json route refuses an empty or
        # contradictory selection as structured invalid_params, not just argv.
        check_validate_selection(list(self.paths), self.all_scripts)
        return self


class ValidatedScript(BaseModel):
    """One script's verdict inside a ``gda script validate`` result (#118, #663).

    The per-file half of the batch result, and it carries exactly what the
    single-path result used to carry at the top level: the ``path`` that was
    validated, whether it compiles, the engine's one-line ``error_string``, and
    the best-effort ``diagnostics`` parsed from that script's own window of the
    engine's stderr. The batch-level facts — the aggregate verdict and the one
    resolved project — live on the enclosing result instead of being repeated per
    entry (ADR-0006 resolves ONE project per call, so a per-entry copy would be a
    duplicate with no way to differ).
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
            "Best-effort advisory diagnostics parsed from this script's window of "
            "the engine's stderr (line + message). May hold only the first error; "
            "empty when the script is valid or nothing could be parsed."
        ),
    )


class ScriptValidateResult(ProjectRootedResult):
    """The result of ``gda script validate``: one verdict per script, plus the aggregate (#118, #663).

    Validating an INVALID script is a SUCCESSFUL operation — the command exits 0
    and reports ``valid=false`` rather than failing. That holds for a batch too:
    the top-level ``valid`` is the AGGREGATE (false when any entry is invalid) and
    the exit code stays 0, so an agent reads the verdict from the result and never
    from the process status.

    ``scripts`` carries one :class:`ValidatedScript` per validated file, in the
    order they were requested (or, under ``--all``, the order the engine
    enumerated them). A single-path invocation yields exactly one entry — the
    shape does not vary with the batch size, so no consumer has to branch on it.

    ``project_root`` names the project the scripts were compiled against, so a
    reader can tell a real compile error from one caused by the wrong project
    context without re-deriving gda's resolution (#658). It is REQUIRED and
    nullable, not optional: every public result carries the key (``null`` means
    projectless), so an agent can read it unconditionally. The engine's sentinel
    does not report it — ADR-0006 keeps the project CLI-side, and the engine is
    told it through ``--path`` — which is what
    :class:`~gda.models.ProjectRootedResult` above reconciles: it supplies the
    absent key for the internal sentinel parse, and :func:`_script_validate_recipe`
    stamps the real value immediately after.
    """

    valid: bool = Field(
        description=(
            "The AGGREGATE verdict: true only when every entry in 'scripts' "
            "compiles. False when any one of them does not — the command still "
            "exits 0, so read this field, not the exit code. Vacuously true for "
            "an empty '--all' run in a project with no scripts."
        )
    )
    scripts: list[ValidatedScript] = Field(
        description=(
            "One verdict per validated script, in requested order (a single path "
            "yields exactly one entry)."
        )
    )
    project_root: str | None = Field(
        description=(
            "The Godot project the whole batch was compiled against — the root "
            "its res:// dependencies resolved to, reported as an absolute path "
            "(ADR-0006: --project, then $GDA_PROJECT, then the current "
            "directory). One per call, never per script. Always present; null "
            "when gda ran projectless (no project resolved), where only "
            "filesystem paths resolve. A script whose res:// dependencies were "
            "reported missing with a null or unexpected root here has a "
            "project-context problem, not a source problem."
        ),
    )


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
            "key on the process exit code. The envelope keeps the evidence, typed "
            "and as prose: 'evidence.exit_status' is the CHILD's status (gda's own "
            "exit code stays 4) and 'evidence.script_errors' the parsed errors, "
            "while the message names the status and the 'diagnostics' string "
            "carries BOTH of the script's streams under the fixed labels "
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
            "phase — 'launched' (the engine wrote nothing at all) or "
            "'output_seen' (it was alive and did not finish) — so a "
            "slow-but-live run is distinguishable from a hang. A run ended EARLY "
            "by the completion-marker rule below is not this envelope: it "
            "reports 'script_aborted', whose phase is 'aborted_on_error'. Both "
            "carry 'elapsed_seconds' and 'termination_phase' as typed 'evidence' "
            "fields as well as in the message, plus 'evidence.script_errors' — "
            "advisory under a timeout (#687); 'timeout_seconds', the reached "
            "ceiling, rides the timeout envelope only (an abort stops short of "
            "its ceiling, which stays in the message)."
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


# The returned-stdout cap of a `script run` SUCCESS result (#665, GDA-DF-036):
# production-scale inspector output grows linearly with content, and an envelope
# that grows with it blows the consuming agent's context. 64 KiB keeps on the
# order of a thousand record lines readable inline while bounding the envelope;
# the COMPLETE stream above it spills to a named file, so nothing is lost —
# bounded, not summarized (record semantics stay with the project tool). The cap
# qualifies ONLY the success result's `stdout` field (ADR-0031 amendment):
# `stderr` and the failure envelopes' partial-output evidence keep their shapes.
SCRIPT_STDOUT_CAP = 64 * 1024


def _script_run_result_schema_extra(schema: dict) -> None:
    """Publish the bounded-stdout truth table into the OUTPUT schema (#748 review).

    ADR-0015's one-authority rule, applied to a result model: every
    SCHEMA-EXPRESSIBLE projection of the runtime validator's truth table is
    published. Truncated implies a string spill file, a full-stream size above
    the cap, and a maximal UTF-8-safe inline head; `minLength` / `maxLength`
    publish the safe CHARACTER bounds implied by its BYTE range. Untruncated
    implies a null spill file, a full-stream size at or below the cap, and the
    safe character cap.

    Two CLASSES of value-dependent identities stay model-side: Draft 2020-12
    cannot relate `stdout_bytes` to another field's encoded length, and its
    string lengths count characters rather than UTF-8 bytes. The corpus asserts
    parity for every published projection and pins representative model-reject /
    schema-accept rows for both disclosed classes.
    """
    schema["allOf"] = [
        {
            "if": {"properties": {"stdout_truncated": {"const": True}}},
            "then": {
                "properties": {
                    "stdout_file": {"type": "string"},
                    "stdout_bytes": {"exclusiveMinimum": SCRIPT_STDOUT_CAP},
                    "stdout": {
                        # A maximal UTF-8-safe cut loses at most three bytes;
                        # at four bytes/code point, this is the weakest implied
                        # character floor a standard validator can publish.
                        "minLength": SCRIPT_STDOUT_CAP // 4,
                        "maxLength": SCRIPT_STDOUT_CAP,
                    },
                }
            },
        },
        {
            "if": {"properties": {"stdout_truncated": {"const": False}}},
            "then": {
                "properties": {
                    "stdout_file": {"type": "null"},
                    "stdout_bytes": {"maximum": SCRIPT_STDOUT_CAP},
                    "stdout": {"maxLength": SCRIPT_STDOUT_CAP},
                }
            },
        },
    ]


def _spill_failure(exit_status: int, full_bytes: int, error: OSError) -> Failure:
    """The typed ``stdout_spill_failed`` for a spill file gda could not write (#665).

    The bound is unconditional (AC2): a stream above the cap either returns as
    its truncated head WITH the complete stream persisted, or the operation is
    this structured failure — never an unbounded result and never a silently
    lost tail. The message carries the run's forensics (it DID run) and the
    remediation: the spill lands in the platform temp dir, so point TMPDIR at a
    writable location and re-run.
    """
    return make_failure(
        "stdout_spill_failed",
        f"the script ran (exit status {exit_status}) and printed {full_bytes} "
        f"bytes of stdout — above the {SCRIPT_STDOUT_CAP} byte cap — but the "
        f"complete-stream spill file could not be written ({error}); the "
        "bounded result cannot be delivered without it. Point TMPDIR at a "
        "writable directory and re-run",
        "",
    )


def _bounded_stdout(
    stdout: str, exit_status: int
) -> "tuple[str, int, bool, str | None] | Failure":
    """Bound a success result's stdout (#665): (returned, full_bytes, truncated, file).

    At or below :data:`SCRIPT_STDOUT_CAP` the stream returns verbatim. Above it,
    the COMPLETE stream is written to a gda-named spill file and the returned
    text is the leading cap bytes, cut on a UTF-8 boundary (a multi-byte
    character straddling the cap is dropped, never mangled). A spill file that
    cannot be created OR completed is the typed ``stdout_spill_failed`` (#748
    review: the bound is unconditional, and a post-create failure must not
    leave a partial file or an open fd behind).
    """
    data = stdout.encode("utf-8")
    if len(data) <= SCRIPT_STDOUT_CAP:
        return stdout, len(data), False, None
    try:
        fd, spill_path = tempfile.mkstemp(prefix="gda-script-stdout-", suffix=".log")
    except OSError as error:
        return _spill_failure(exit_status, len(data), error)
    spill = None
    try:
        spill = os.fdopen(fd, "wb")
        spill.write(data)
        spill.close()
    except OSError as error:
        # Post-create failure: release what was created before failing typed —
        # the fd (ours until fdopen takes it), then the partial file.
        if spill is None:
            try:
                os.close(fd)
            except OSError:
                pass
        else:
            try:
                spill.close()
            except OSError:
                pass
        try:
            os.unlink(spill_path)
        except OSError:
            pass
        return _spill_failure(exit_status, len(data), error)
    # Interior bytes re-encoded from str are valid UTF-8; only the cut edge can
    # split a character, so "ignore" drops at most that one partial character.
    head = data[:SCRIPT_STDOUT_CAP].decode("utf-8", "ignore")
    return head, len(data), True, spill_path


class ScriptRunResult(BaseModel):
    """The result of ``gda script run``: the user script's own run, passed through (ADR-0031).

    This is the **public promotion of the internal Raw-run shape**
    (:class:`gda.runner.RunResult`): a boundary DTO built from a ``RunResult``
    by dropping its ``launch_failure`` axis (that becomes the Error envelope),
    renaming ``exit_code`` → ``exit_status``, and — since #665 — BOUNDING the
    promoted ``stdout`` at :data:`SCRIPT_STDOUT_CAP` (the command-owned bounded
    public projection of the raw stream; the complete stream survives in the
    spill file the result names). Unlike every other command,
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
    stdout: str = Field(
        description=(
            "The script's standard output — verbatim up to the "
            f"{SCRIPT_STDOUT_CAP // 1024} KiB cap (#665): above it, this is "
            "the stream's leading cap bytes (cut on a UTF-8 boundary) and the "
            "COMPLETE stream is at 'stdout_file'. Read 'stdout_truncated' "
            "before treating this as the whole stream."
        )
    )
    stderr: str = Field(description="The script's standard error, captured verbatim.")
    stdout_bytes: int = Field(
        ge=0,
        description=(
            "The script's COMPLETE standard-output length in UTF-8 bytes "
            "(#665) — the full stream's size whether or not 'stdout' was "
            "truncated. Always present."
        ),
    )
    stdout_truncated: bool = Field(
        description=(
            "Whether 'stdout' is the truncated head of a stream above the "
            f"{SCRIPT_STDOUT_CAP // 1024} KiB cap (#665). False means "
            "'stdout' IS the whole stream. Always present."
        ),
    )
    stdout_file: str | None = Field(
        description=(
            "The file holding the script's COMPLETE standard output when "
            "'stdout' was truncated (#665); null when it was not. Always "
            "present (required-but-nullable)."
        ),
    )
    diagnostics: list[ScriptError] = Field(
        default_factory=list,
        description=(
            "Recognized script errors parsed out of the engine's stderr, in "
            "emission order; empty when the run reported none. Advisory and "
            "best-effort — the verbatim stream stays in 'stderr'."
        ),
    )

    model_config = {
        "json_schema_extra": lambda schema: _script_run_result_schema_extra(schema)
    }

    @model_validator(mode="after")
    def _check_stdout_projection(self) -> "ScriptRunResult":
        # The bounded-stdout truth table (#748 review): the three markers are
        # ONE machine contract, not three independent fields. Truncated means a
        # spill file exists and the full stream is above the cap; untruncated
        # means no spill file and 'stdout' IS the whole stream.
        inline_bytes = len(self.stdout.encode("utf-8"))
        if self.stdout_truncated:
            if self.stdout_file is None:
                raise ValueError(
                    "a truncated stdout must name its complete-stream spill file."
                )
            if self.stdout_bytes <= SCRIPT_STDOUT_CAP:
                raise ValueError(
                    "a truncated stdout implies a full stream above the cap "
                    f"({SCRIPT_STDOUT_CAP} bytes)."
                )
            if inline_bytes < SCRIPT_STDOUT_CAP - 3:
                raise ValueError(
                    "a truncated stdout is the maximal UTF-8-safe prefix at the "
                    f"{SCRIPT_STDOUT_CAP} byte cap — it cannot be shorter than "
                    f"{SCRIPT_STDOUT_CAP - 3} bytes."
                )
            if inline_bytes > SCRIPT_STDOUT_CAP:
                raise ValueError(
                    "a truncated stdout is the stream's leading cap bytes — it "
                    f"cannot itself exceed {SCRIPT_STDOUT_CAP} bytes."
                )
        else:
            if self.stdout_file is not None:
                raise ValueError("an untruncated stdout carries no spill file.")
            if inline_bytes > SCRIPT_STDOUT_CAP:
                raise ValueError(
                    "an untruncated stdout is the complete stream at or below "
                    f"the {SCRIPT_STDOUT_CAP} byte cap."
                )
            if self.stdout_bytes != inline_bytes:
                raise ValueError(
                    "an untruncated stdout's byte count is the returned "
                    "stream's own length."
                )
        return self


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
#   ``{exit_status, stdout, stderr, diagnostics}`` **passed through — stderr
#   verbatim, stdout bounded at SCRIPT_STDOUT_CAP with the complete stream
#   spilled to a named file (#665) — even
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
# Imported from ADR-0006's path authority (`gda.project`) with the canonicalizer
# it belongs to, rather than restated here (#763).


def _project_scoped_res_path(script: str) -> "str | Failure":
    """The canonical ``res://`` address of an accepted script path, or the refusal (#675).

    The single acceptance gate for ``script run``'s path argument, applied BEFORE any
    launch so every refusal is a structured ``invalid_path`` and never an engine
    failure. It accepts the two PORTABLE forms — a ``res://`` address and a
    project-relative path — and folds them onto one address through the shared
    :func:`canonical_res_path`, so the argv, the entry-load verdict and the reported
    path cannot diverge by input spelling.

    Returns a structured :class:`~gda.errors.Failure` for the seven shapes that
    are not project-scoped script addresses. Each must be caught HERE, because each
    is otherwise launched. Six are ``invalid_path`` — this gate's own ADR-0031 ABI
    edge, about the shape of an ADDRESS — and the seventh, the upward escape, is
    ``target_outside_project``: that one is not a spelling question but the shared
    containment question, decided by the shared rule and reported under the code
    every other command reports it under (#763). It is also the one refusal this
    gate makes with no project in hand, since the whole path edge is decided ahead
    of the projectless check, which is why its message names no root:

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
    - a path whose canonical address ends in a code point at or below **U+0020** —
      Godot 4.6.3 removes that exact suffix set (``String::strip_edges``) before it
      echoes the ``--script`` path in a load-failure diagnostic. The canonical
      identity then loses a character and the never-ran verdict misses. Python's
      Unicode ``rstrip`` set is deliberately NOT used: Godot preserves NBSP and EM
      SPACE, so those remain accepted;
    - a path containing an **engine-log line boundary** — the engine can emit that
      character inside its diagnostic, but :mod:`gda.engine_log` necessarily splits
      the address into separate records. No one record retains the canonical entry
      identity, so a never-run entry can again report a phantom success. Ordinary
      leading and internal ASCII spaces remain accepted;
    - a path that names the project **root** (``""``, ``"."``, ``"sub/.."``, and the
      ``res://`` / ``res://.`` spellings) — it names a directory, not a script. An
      unset shell variable makes ``gda script run "$SCRIPT"`` exactly this. ONE
      remainder now spells the root, the engine's own empty one, because the shared
      canonicalizer reproduces ``simplify_path``'s empty join too (#763) — the
      former two-member root set was this gate accommodating a parity gap in a
      primitive it did not own;
    - a path that **escapes above the root** (``".."``, ``"../outside.gd"``, and their
      ``res://`` spellings) — the project is the whole addressable scope, so an
      upward escape names something the ``--project`` contract does not cover. This
      is the one clause this gate no longer decides for itself: it asks
      :func:`gda.project.res_escape_remainder`, the shared rule ``script validate``
      and ``resource import`` reach through :func:`gda.project.path_outside_project`.

    The last two are load-bearing, and it is not tidiness. The root-address clause
    is ALSO belt-and-suspenders against a parser risk: the engine answers a root
    address with ``Can't load script: res://.`` (or ``res://..``), a sentence
    whose trailing dot is part of the ADDRESS, not punctuation. A parser that
    folds it as though it WERE punctuation — reading ``res://.`` back as
    ``res://``, ``res://..`` back as ``res://.`` — would miss the launched
    entry, and the never-ran verdict would report a PHANTOM SUCCESS instead of
    the refusal it should be. Issue #698 (its fix, PR #756) targets exactly that
    fold in :mod:`gda.script_errors`'s ``_CANT_LOAD`` regex; this paragraph's own
    argument does not depend on whether that PR has landed at any point in this
    branch's history, because THIS guard already closes the gap on its own,
    independent of the parser's fold either way: a root address is refused
    HERE, before any launch, so it never reaches the parser at all. The root
    address therefore stays refused for the plainer reason already given above
    (it names a directory, not a script). The escape clause is the one still
    load-bearing for the reason it always was: an escape that RESOLVES
    (``../outside.gd``)
    executes a script outside the project entirely, which would widen the
    Project-code execution surface past ADR-0009's Trusted project — the very
    consequence the amendment cites for keeping absolute paths refused, so
    admitting it by the relative spelling would make that reasoning false.
    Refusing both before the launch keeps this gate, not the error parser, as the
    one place that decides.

    The escape test is on the canonical remainder's first SEGMENT, not a string
    prefix: ``res://..foo.gd`` is a legal file whose name merely starts with two dots,
    and must stay accepted.

    The two rules that stay wholly local are the last two above, and deliberately
    (#763): the trailing-``strip_edges`` suffix and the engine-log line boundary are
    not containment at all but VERDICT MATCHING — they keep the canonical identity
    matchable against what the engine echoes back on stderr, a concern only a
    channel that reads that stderr has.
    """
    if Path(script).is_absolute():
        return script_path_invalid_failure(script)
    if "://" in script and not script.startswith(RES_PREFIX):
        return script_path_invalid_failure(script)
    # Only a LEADING `~` is a home reference (expanduser's own rule), so `sub/~x.gd`
    # stays a legal project-relative filename.
    if script.startswith("~"):
        return script_path_invalid_failure(script)
    lifted = script if script.startswith(RES_PREFIX) else RES_PREFIX + script
    canonical = canonical_res_path(lifted)
    # What the canonical address names UNDER the project root. canonical_res_path has
    # already collapsed `.`/`..` — and, like the engine, spells the fully collapsed
    # case as the bare scheme — so an EMPTY remainder is the root itself.
    remainder = canonical[len(RES_PREFIX) :]
    if not remainder:
        return script_path_invalid_failure(script)
    if res_escape_remainder(canonical) is not None:
        return script_escapes_project_failure(script)
    # Godot 4.6.3's String::strip_edges() removes trailing code points <= U+0020.
    # Refuse exactly that engine-normalized suffix set; Python str.rstrip() is wider
    # and would reject NBSP / EM SPACE even though Godot preserves them. Do not trim:
    # that would silently launch a different address from the one the caller named.
    if ord(remainder[-1]) <= 0x20:
        return script_path_invalid_failure(script)
    # engine_log owns the line protocol through str.splitlines(). Sentinels make a
    # boundary at either edge observable (splitlines otherwise suppresses a terminal
    # empty record), while any ordinary one-line address still produces one record.
    if len(engine_log_lines(f"x{remainder}x")) != 1:
        return script_path_invalid_failure(script)
    return canonical


# ``TerminationPhase`` moved to :mod:`gda.models` with the #687 ADR-0004 amendment:
# it is projected into the shared failure envelope now (``evidence.termination_phase``)
# and is reported by every launch-backed channel, not only by ``script run``, so it is
# a property of the public contract rather than of this command. It is imported here
# because this module USES it; ``gda.models`` is the one name to import it by
# (ADR-0040's Considered Options rejected re-export facades).


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
      construction** (one of the two kinds proving the script DID run) and which is
      exactly the dogfooded case: an error raised inside the entry's own
      ``_initialize`` aborts it before its ``quit()``.

    ``PUSH_ERROR`` is deliberately NOT here (#722), though it too can name the
    entry. The watch's whole premise is that something interrupted the run: a
    GDScript runtime error abandons the function it was raised in, which is why a
    silence window after one is evidence. A ``push_error`` interrupts nothing —
    the engine prints it and execution continues at the next statement — so a
    script that reports an invariant and then computes quietly is alive by
    construction, and killing it would break the very projects that use
    ``push_error`` as ordinary logging. Widening recognition (#722) therefore adds
    diagnostics to what ``script run`` REPORTS without changing when it aborts.

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
    outcome = _project_scoped_res_path(script)
    if isinstance(outcome, Failure):
        return outcome
    # Then require a resolved project — BOTH accepted forms resolve against one.
    if project is None:
        return script_run_project_not_found_failure()
    script = outcome
    # And require it to be the script's OWNER (ADR-0006 amendment, #697): the
    # address gate above is lexical, so it cannot see a `project.godot` nested
    # between the resolved root and the script. Running against the outer root
    # would resolve the script's own `res://` references against a root that is
    # not its own — GDA-DF-035 in the executing form. One rule, three commands:
    # the same shared gate `script validate` and `resource import` apply, reported
    # under the same code.
    #
    # This site asked ownership ALONE until #802, because the address gate above
    # has already decided containment for it — every escaping spelling is refused
    # there, and a non-escaping res:// address is inside the root by construction.
    # It now calls the whole gate anyway: the containment half is inert here (the
    # consistency table proves it spelling by spelling rather than assuming it),
    # and one call site cannot drift from the other two.
    refusal = containment_refusal(script, project)
    if refusal is not None:
        return refusal

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
    # Pass a watch, this channel's POLICY over the shared primitive (#655): only
    # when the caller declared a completion marker can a run whose script died be
    # ended in seconds instead of at the ceiling. The watch is inert without a
    # marker; the captured output and the measured wall clock come from the launch
    # itself, which every channel gets.
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
            diagnostics,
        )

    # The script RAN. Its own status is data by default (the ADR-0031 crux) and a
    # gda failure only when the caller opted in with --strict.
    if strict and raw.exit_code != 0:
        return script_exit_status_failure(
            script, raw.exit_code, raw.stdout, raw.stderr, diagnostics
        )

    # The public promotion of the internal Raw run: the boundary DTO built by
    # dropping launch_failure (lifted into the Error envelope above) and renaming
    # exit_code → exit_status, plus the parsed diagnostics. This is the one success
    # result that can be non-zero. The stdout is BOUNDED here (#665): above the
    # cap the complete stream spills to a named file and the result carries its
    # head — the one qualification of ADR-0031's verbatim passthrough — and a
    # spill gda cannot write is the typed stdout_spill_failed, never an
    # unbounded result (#748 review, AC2).
    bounded = _bounded_stdout(raw.stdout, raw.exit_code)
    if isinstance(bounded, Failure):
        return bounded
    stdout, full_bytes, truncated, spill = bounded
    return ScriptRunResult(
        path=script,
        exit_status=raw.exit_code,
        stdout=stdout,
        stderr=raw.stderr,
        stdout_bytes=full_bytes,
        stdout_truncated=truncated,
        stdout_file=spill,
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
    # ONE parse of the partial stderr serves both forms the envelope now carries
    # (#687): the typed ``evidence.script_errors`` and the prose block in
    # ``diagnostics``, which the builders render from this same list.
    recognized = parse_script_errors(raw.stderr)
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
            phase=TerminationPhase.ABORTED_ON_ERROR,
            script_errors=recognized,
            stdout=raw.stdout,
            stderr=raw.stderr,
        )
    if raw.launch_failure is LaunchFailure.TIMEOUT:
        return script_run_timeout_failure(
            script,
            timeout=timeout,
            elapsed=_elapsed(raw, at_least=timeout),
            phase=termination_phase(raw),
            script_errors=recognized,
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


# ``_timeout_phase`` and ``_render_captured_errors`` moved to :mod:`gda.errors` with
# the #687 amendment, as ``termination_phase`` (public — this module still calls it)
# and ``_recognized_errors_prose`` (private — only the builders render it now). The
# phase is reported by every launch-backed channel's ``launch_timeout`` envelope, and
# the prose is rendered from the SAME parsed list the envelope carries typed, so both
# belong beside the builders that emit them.


# A `SCRIPT ERROR: <message>` line and the `GDScript::reload (...:<line>)` frame
# that follows it carry, between them, the one advisory diagnostic the engine
# emits for a failed validate (issue #118). The line number is the final `:`
# part of the reload frame; there is NO column on the standard build.
# `[ \t]` (not `\s`) bounds the message capture so it cannot span newlines — an
# empty SCRIPT ERROR message must not swallow the following reload frame.
# The backtrace frames under it (`[n] _op_script_validate (…/operations.gd:…)`)
# are gda's OWN payload lines, not the validated script's — they carry a line
# number too — so requiring the literal `GDScript::reload` is what keeps them out.
#
# `\r` joins the trailing character class for the same reason the marker below
# tolerates one: on Windows the engine's C runtime writes stderr in TEXT mode, so
# every `\n` reaches gda as `\r\n`, and the runner decodes raw bytes with no
# newline translation (a locale-aware decode would mojibake a non-ASCII path,
# #33). Without it the captured message ended in a stray `\r` on that platform.
_SCRIPT_ERROR_LINE = re.compile(
    r"^[ \t]*SCRIPT ERROR:[ \t]*(?P<message>.*?)[ \t\r]*$", re.MULTILINE
)
_RELOAD_FRAME = re.compile(r"GDScript::reload \([^)]*:(?P<line>\d+)\)")

# The line ``operations.gd`` writes to stderr immediately before it compiles one
# script of the batch (#663) — the delimiter that makes a batch's diagnostics
# attributable to individual FILES. It is emitted through the op's ordinary
# ``_diag`` channel, so the full line is this prefix plus the script's path.
#
# A marker rather than the path inside the engine's own ``GDScript::reload`` frame:
# that frame's spelling is the engine's, and gda would have to guess how the engine
# renders whatever address it was handed (``res://``, absolute, relative) to match
# it back. The marker is gda's own text, written by gda, in the order gda asked for
# — so attribution needs no agreement about path spellings at all.
#
# This is the Python half of a cross-language constant: ``operations.gd`` composes
# the same line from its ``DIAG_PREFIX`` and ``VALIDATE_MARKER`` consts, and a test
# pins this string against those two VALUES (not against the call site that writes
# them), the way the harness's ``LOG_MARKER`` is mirrored.
VALIDATE_MARKER_PREFIX = "gda: validating: "

# `\r?$` (not a bare `$`) because the path is CAPTURED and then compared for
# equality: on Windows every engine line arrives as `\r\n` (see the note on
# `_SCRIPT_ERROR_LINE` above), and a `\r` swallowed into the capture makes the
# attribution guard reject every verdict — which reported empty diagnostics for
# every validate on that platform rather than misattributing anything. The lazy
# `.*?` is what lets the optional `\r` be the one to consume it.
_VALIDATE_MARKER = re.compile(
    rf"^{re.escape(VALIDATE_MARKER_PREFIX)}(?P<path>.*?)\r?$", re.MULTILINE
)


def parse_validate_diagnostics(stderr: str) -> list[ScriptDiagnostic]:
    """Parse advisory ``script validate`` diagnostics from ONE script's stderr window.

    A pure function (no engine, no I/O): the line/message of a failed
    ``GDScript.reload()`` are available only from stderr, not from any bound API
    (ADR-0002's stderr is advisory only — it is never parsed for the stable
    success/failure outcome or error codes, only surfaced here as best-effort
    diagnostics). ``column`` is always null (the engine exposes none).

    The window is one script's, which :func:`parse_validate_segments` cuts out, so
    the only legitimate ``GDScript::reload`` frame in it is that script's own. Each
    ``SCRIPT ERROR: <message>`` line is paired with a reload frame found ONLY in
    the sub-window up to the next ``SCRIPT ERROR`` line, and a ``SCRIPT ERROR``
    with no reload frame there is dropped: bounding the search keeps a later
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


def parse_validate_segments(stderr: str) -> list[tuple[str, list[ScriptDiagnostic]]]:
    """Cut the engine's stderr into one ``(path, diagnostics)`` window per script (#663).

    The batch's attribution step, and the reason a batch can report per-FILE
    diagnostics at all: the engine compiles the scripts one after another into a
    single stderr stream, so without a delimiter every error would belong to "the
    batch" and a six-script run would report six errors with nothing saying which
    file each came from. ``operations.gd`` writes
    :data:`VALIDATE_MARKER_PREFIX` + the path before each compile, and this splits
    on those markers and hands each window to :func:`parse_validate_diagnostics`
    unchanged — the per-script pairing rule is reused, not re-implemented.

    Text BEFORE the first marker is dropped, which is what makes the batch strictly
    more precise than the old whole-stream parse: engine startup noise, and an
    autoload's own errors under ``--project``, arrive before any script is compiled
    and can no longer reach any verdict.

    Returns the windows in engine order. The path is carried out of the marker
    rather than assumed, so the caller can verify it against the verdict it is
    about to attach the diagnostics to.
    """
    markers = list(_VALIDATE_MARKER.finditer(stderr))
    segments: list[tuple[str, list[ScriptDiagnostic]]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(stderr)
        window = stderr[marker.end() : end]
        segments.append((marker.group("path"), parse_validate_diagnostics(window)))
    return segments


def classify_script_validate(
    result: RunResult, binary: Path
) -> ScriptValidateResult | Failure:
    """Classify the raw ``script validate`` result (issue #118, #663).

    The per-command layer for ``script validate``: the shared decision tree comes
    from ``classify_run`` (an op error — a missing path, a wrong extension, an
    unreadable file — is still a ``Failure``, and it refuses the whole batch). For
    a SUCCESSFUL op, the line/message diagnostics are not in the sentinel — they
    live only in the engine's stderr — so this layer parses them in and attaches
    each script's own to its own verdict.

    Attribution is POSITIONAL — the engine emits its markers and its verdicts in
    the same order — under TWO guards, and both are needed because a duplicate
    path defeats either one alone:

    - the **count** must match. The op writes exactly one marker per verdict, so a
      different number of segments means the stream is not the one this result came
      from: a path containing a newline has split into a phantom marker, or output
      was lost. A shift of one is invisible to a path check when the same script
      appears twice in the batch (``a.gd b.gd a.gd``), which is a supported input.
    - each segment's **path** must equal the verdict's. This catches a
      substitution that keeps the count, and it is what a mismatch degrades to.

    A failed guard leaves the affected entries with their empty advisory
    ``diagnostics`` rather than another script's errors — wrong evidence about a
    named file is worse than none. The authoritative verdict is the engine's
    ``valid`` either way, which no guard here can change.
    """
    outcome = classify_run(result, binary, ScriptValidateResult)
    if isinstance(outcome, Failure):
        return outcome
    segments = parse_validate_segments(result.stderr)
    if len(segments) != len(outcome.scripts):
        return outcome
    for script, (path, diagnostics) in zip(outcome.scripts, segments):
        if not script.valid and path == script.path:
            script.diagnostics = diagnostics
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


def _render_validated_script(script: "ValidatedScript", indent: str) -> list[str]:
    """One script's verdict as human lines: the answer, then its evidence.

    Shared by both shapes :func:`render_script_validate` prints, so a per-file
    block reads the same whether it stands alone or sits inside a batch.
    """
    if script.valid:
        return [f"{indent}valid {script.path}"]
    lines = [f"{indent}invalid {script.path}"]
    if script.error_string is not None:
        lines.append(f"{indent}  {script.error_string}")
    for diag in script.diagnostics:
        location = f"line {diag.line}" if diag.line is not None else "unknown line"
        lines.append(f"{indent}  {location}: {diag.message}")
    return lines


def render_script_validate(validated: "ScriptValidateResult") -> str:
    """Render a validate result: the verdict(s) plus best-effort diagnostics.

    An INVALID verdict leads with the project the scripts were compiled against
    (#658), before the diagnostics rather than after them: when the root is the
    wrong one, every diagnostic below it is an artefact of that single mistake,
    and the reader needs to see the cause before the cascade. A valid verdict
    stays the short answer — the root only explains a failure.

    ONE script renders as the one-line/one-block form it always has. A BATCH leads
    with the aggregate ("invalid (1 of 6 scripts)"), then the project when that
    aggregate is false, then each script's block indented under it — conclusion
    first, so a six-script run's answer is the first line rather than something the
    reader has to derive by scanning six blocks. The batch-level facts appear once,
    because ADR-0006 resolves one project for the whole call.
    """
    if len(validated.scripts) == 1:
        lines = _render_validated_script(validated.scripts[0], "")
        if not validated.valid:
            lines.insert(1, f"  project: {_render_project_root(validated)}")
        return "\n".join(lines)

    # Two or more from here on: the single-script form returned above, so the
    # plural is unconditional.
    total = len(validated.scripts)
    if validated.valid:
        lines = [f"valid ({total} scripts)"]
    else:
        failed = sum(1 for script in validated.scripts if not script.valid)
        lines = [
            f"invalid ({failed} of {total} scripts)",
            f"  project: {_render_project_root(validated)}",
        ]
    for script in validated.scripts:
        lines += _render_validated_script(script, "  ")
    return "\n".join(lines)


def _render_project_root(validated: "ScriptValidateResult") -> str:
    """The project line's value, naming the projectless case explicitly (#658)."""
    return validated.project_root or "(none resolved: projectless)"


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
    if ran.stdout_truncated:
        # The bounded head is above (#665); tell the reader where the rest is.
        parts.append(
            f"  [stdout truncated at {SCRIPT_STDOUT_CAP} of {ran.stdout_bytes} "
            f"bytes; complete stream: {ran.stdout_file}]"
        )
    if ran.stderr:
        parts.append(ran.stderr.rstrip("\n"))
    for diag in ran.diagnostics:
        parts.append(f"  {script_error_line(diag)}")
    return "\n".join(parts)


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
    """Refuse → compile → report the root: ``script validate``'s recipe (#658, #663).

    The sentinel op still does the compiling (``cmd.execute``, as the export
    recipe runs its preflight); this wraps it in the two decisions only the CLI
    can make, because ADR-0006 keeps project resolution CLI-side and the engine
    is TOLD the project through ``--path``, never asked about it.

    First the refusal, now applied to EVERY path in the batch (#663). ADR-0006
    resolves one project per call, so a batch whose paths span projects is exactly
    the hazard that decision's rejection rationale names: the outsiders would be
    compiled against a root that does not own them. A script outside the resolved
    project is refused HERE, before the engine is spawned, so the false ``res://``
    dependency cascade is never produced (see
    :func:`~gda.errors.target_outside_project_failure`). The FIRST offender in
    requested order is named, and it refuses the whole batch: the whole call has
    one project, so one outsider makes the requested set unservable, not just its
    own entry.

    The refusal has TWO halves since ADR-0006's 2026-08-31 amendment (#697), and
    the second is why a *projectless* call is now checked too. Both are asked by
    ONE call to :func:`~gda.errors.containment_refusal` (#802), which maps the
    ordered decision :func:`~gda.project.containment_violation` makes to whichever
    envelope fires; this recipe only chooses the targets. Containment (:func:`~gda.project.path_outside_project`) asks whether
    the target is in the resolved project's tree, which only a resolved project
    can fail. Ownership (:func:`~gda.project.owning_project`) asks whether that
    project is really the target's OWNER — a ``project.godot`` nearer to the
    target claims it — and that is the half GDA-DF-035 exposed in both its
    readings: an ancestor that is a project, with the target in a nested one; and
    a projectless run of a file that does have an owner. Both compiled the target
    against a root that was not its own and produced the same cascade of false
    ``res://`` errors. gda refuses and names the owner instead of adopting it:
    deriving the root from the target is what ADR-0006 rejected and the amendment
    keeps rejected, so ``--project`` naming the owner stays the way to say what
    you mean. A standalone script with
    no owner is still validated projectless by filesystem path, exactly as before.

    ``--all`` has nothing to check: the engine enumerates the resolved project's
    own tree, so every path it produces is inside by construction — and any nested
    project it enumerates is one the engine itself compiles against this root.

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
    # The SUCCESS path's root, normalized the way the refusal path's is (#807
    # review): both sides of one verdict must reach the project by one reading, and
    # the same call answering two spellings of one root is what #799 was.
    # `project_absolute` differs only in staying total on an unresolvable `~user`.
    root = None if project is None else project_absolute(project).resolve()
    for path in params.paths:
        # ONE call for both halves and their ordering (#802): the gate on ADR-0006's
        # path authority owns them, so this recipe states only WHICH targets it is
        # asking about — the batch, in requested order, first offender wins.
        refusal = containment_refusal(path, project)
        if refusal is not None:
            return refusal
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
    # The model owns the mode-selection rule and the argv body does not restate
    # it: the shared builder turns any model-construction failure (resolve_set_mode,
    # via ScriptSetParams's validator) into the Click usage error (exit 2) — the
    # same translation an argv-side pre-check used to do by hand — so the rule
    # runs once per invocation on both input paths (ADR-0015, issue #713).
    dispatch_domain(
        SCRIPT_SET_COMMAND,
        params_or_bad_parameter(
            ScriptSetParams,
            path=path,
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
    paths: Optional[list[str]] = typer.Argument(
        None,
        help=(
            "The .gd script files to validate. Repeat the argument to validate a "
            "batch in ONE engine launch. Omit them and pass --all instead."
        ),
    ),
    all_scripts: bool = typer.Option(
        False,
        "--all",
        help=(
            "Validate every .gd script in the resolved project instead of named "
            "paths. Requires a resolved project; mutually exclusive with PATH."
        ),
    ),
    json_output: bool = json_option(),
    schema: bool = SCRIPT_VALIDATE_COMMAND.schema_option(),
    params_json: Optional[str] = params_json_option(),
    godot: Optional[str] = godot_option(),
    project: Optional[str] = project_option(),
) -> None:
    """Syntax/compile-check .gd scripts; invalid exits 0 with valid=false.

    Pass several PATHs to validate them as one BATCH in a single engine launch —
    the four to six related scripts a change usually touches cost one process, not
    one each. Pass --all instead to validate every script in the resolved project.
    Either way the result is the same shape: one entry per script under 'scripts',
    plus one aggregate 'valid' that is false when ANY of them fails. A single path
    is simply a batch of one.

    The scripts are compiled against the resolved project (ADR-0006: --project,
    then $GDA_PROJECT, then the current directory) — the root their res://
    dependencies resolve against — and the result reports that root as
    'project_root'. Read it before trusting a verdict: a script compiled against
    the wrong project reports every res:// dependency as missing, plus the type
    errors derived from them.

    A path OUTSIDE the resolved project refuses the whole batch with
    'project_not_found' before anything is parsed, naming both the file and the
    project, rather than reporting that false cascade. gda never derives the
    project from a script's own path (ADR-0006), so pass --project for the project
    that owns the files. A missing file or a non-.gd path likewise refuses the
    batch (path_not_found / invalid_path) instead of becoming a verdict.
    """
    # The model owns the selection rule and the argv body does not restate it: the
    # shared builder turns any model-construction failure into the Click usage
    # error (exit 2), which is the SAME translation an argv-side pre-check did by
    # hand — and it keeps working when a future rule is added to the model, where a
    # hand-written pre-check would silently stop covering argv (ADR-0015).
    dispatch_recipe(
        SCRIPT_VALIDATE_COMMAND,
        params_or_bad_parameter(
            ScriptValidateParams, paths=list(paths or []), all_scripts=all_scripts
        ),
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
            "shell '&&' chains and CI gates. The envelope carries the child's "
            "status as 'evidence.exit_status' and the parsed errors as "
            "'evidence.script_errors'; its message names the status too, and its "
            "diagnostics carry both script streams, labelled "
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
            "termination phase: 'launched' (the engine wrote nothing) or "
            "'output_seen' (alive but unfinished). A run ended early by "
            "--completion-marker reports 'script_aborted' (phase "
            "'aborted_on_error') instead. Both put the clocks, the phase and the "
            "parsed errors on the envelope's typed 'evidence' key. Raise it for a "
            "suite that outgrew the default; lower it to fail fast."
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
    --script <res://…>`` and passes its result through (ADR-0031): ``stderr``
    verbatim, ``stdout`` verbatim up to a 64 KiB cap (#665) — above it the
    result carries the stream's leading cap bytes while the COMPLETE stream is
    written to the file named in ``stdout_file``, with ``stdout_bytes`` and
    ``stdout_truncated`` always reporting the full size and whether truncation
    happened; a spill file gda cannot write is the typed
    ``stdout_spill_failed``, never an unbounded result. This is the
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
    suite that is merely slow is distinguishable from one that hung. Every failure
    of this command that computed such facts also carries them TYPED, on the
    envelope's optional ``evidence`` key (#687), so an agent branches on numbers
    rather than on the message. For a script
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
    # The params model is the single authority for the bounds (ADR-0015): the
    # finite positive ceiling and the non-blank marker are its field constraints,
    # enforced identically for --params-json — this argv body only translates a
    # model refusal into the Click usage error (#709 review).
    dispatch_recipe(
        SCRIPT_RUN_COMMAND,
        params_or_bad_parameter(
            ScriptRunParams,
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
