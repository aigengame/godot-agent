"""The meta commands: ``info``, ``skill``, ``schema``, ``version``, ``help`` (ADR-0005).

The one non-domain slice of the per-command-group split (ADR-0040): a meta
command is about ``gda`` or the engine ITSELF rather than a Godot domain object,
so these stay TOP-LEVEL and ungrouped. This module owns their
params/result models, the ``gda skill`` emitter (formerly ``gda.skill_ops``),
``info``'s version-gate classifier, their human renderers, their
``HeadlessCommand`` descriptors (ADR-0023) and their command bodies — and,
because they attach directly to the root app, :func:`register` defines them
against the ``root`` it is handed and closes over it for the ``gda schema``
surface walk.

``version`` and ``help`` are the two ADR-0005 named from the start and delivered
late (#670): the taxonomy listed them, the dogfooding record showed agents typing
them, and neither existed. Both are pure emitters — no Godot, no project — and
neither invents an answer: ``version`` renders the ``gda.provenance`` payload the
root ``--version`` flag already renders, and ``help`` renders the text
``<command> --help`` already renders.

It imports the shared machinery downward — the dispatch tail (``gda.dispatch``),
the descriptor machinery (``gda.headless``), the shared failure taxonomy
(``gda.errors``), the cross-command contract core (``gda.models``), the
agent-directory quarantine (``gda.skill_targets``, ADR-0027) and the surface walk
(``gda.surface``) — and is imported by nothing but the composition root
(``gda.cli``).
"""

import contextlib
import io
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Optional

import typer
from pydantic import BaseModel, Field, model_validator

from gda.dispatch import dispatch_meta, dispatch_recipe
from gda.errors import (
    MIN_GODOT_VERSION,
    Failure,
    make_failure,
    classify_run,
)
from gda.headless import (
    HeadlessCommand,
    godot_option,
    json_option,
    params_json_option,
    project_option,
    schema_command_class,
    schema_option,
)
from gda.hints import DISCOVERY, UNKNOWN_COMMAND, near_miss
from gda.models import EngineVersion, SurfaceManifest
from gda.provenance import (
    VersionProvenance,
    build_version_provenance,
    render_version_line,
)
from gda.runner import RunResult
from gda.skill_targets import SkillProvider, SkillScope, resolve_skill_dir
from gda.surface import build_surface_manifest


class InfoParams(BaseModel):
    """The operation params of ``gda info`` — none (ADR-0004).

    ``gda info`` takes no operation params, so its ``input`` schema is trivially
    empty; this is expected, not an error. The model still exists so the
    ``--schema`` document is derived model-side rather than hand-written.
    """


class SchemaAllParams(BaseModel):
    """The operation params of ``gda schema`` — none (ADR-0012).

    Like ``gda info``, ``gda schema`` takes no operation params, so its
    ``input`` schema is trivially empty. The model still exists so ``gda schema
    --schema`` is derived model-side rather than hand-written, keeping the meta
    command self-describing under the same ADR-0004 gate as every other command.
    """


class VersionParams(BaseModel):
    """The operation params of ``gda version`` — none (ADR-0004).

    Like ``gda info`` it takes no operation params, so its ``input`` schema is
    trivially empty; the model exists so the ``--schema`` document is derived
    model-side rather than hand-written.
    """


class HelpParams(BaseModel):
    """The operation params of ``gda help``: the command path to describe.

    ``command`` is the path as it is typed after ``gda`` — ``["scene", "get"]`` for
    ``gda help scene get`` — so the argv form and a ``--params-json`` object name the
    target the same way (ADR-0015). Empty (the default) describes the CLI itself,
    which is what a bare ``gda help`` asks for.
    """

    command: list[str] = Field(
        default_factory=list,
        description="The command path to describe, as the words typed after `gda` "
        '(e.g. ["scene", "get"]); empty describes the whole CLI.',
    )


class HelpResult(BaseModel):
    """The result of ``gda help``: one command's help text, and whose it is.

    ``text`` is the SAME rendering ``--help`` produces — this command re-renders
    nothing — so the two forms cannot drift. ``command`` names the target as its full
    invocation, so a caller reading the payload alone knows which help it holds.
    """

    command: str = Field(
        description="The command the help text describes, as its full invocation "
        "(`gda`, `gda scene`, `gda scene get`)."
    )
    text: str = Field(
        description="The command's help text, exactly as `--help` renders it."
    )


class SkillParams(BaseModel):
    """The operation params of ``gda skill`` (ADR-0024, extended ADR-0027).

    ``gda skill`` is a pure emitter meta command: it reads the bundled
    ``SKILL.md`` from the package and emits or installs it — no Godot is spawned.
    ``install`` writes the manifest to a target instead of printing it. The target
    is named one of two ways: a caller-supplied ``install_dir`` (the neutral path,
    ADR-0024 — core carries no default location), or a known ``provider`` whose
    skills directory is resolved at ``scope`` (the opt-in convenience, ADR-0027).
    The two are mutually exclusive; ``provider`` normalizes to ``install_dir`` here so
    the argv and ``--params-json`` paths resolve identically (ADR-0015).
    """

    install: bool = Field(
        default=False,
        description="If true, WRITE the bundled SKILL.md to the target "
        "instead of returning it; the result then reports the written path.",
    )
    install_dir: str | None = Field(
        default=None,
        description="The skills directory to install into (caller-supplied; the neutral "
        "path, no default). Parent dirs are created and an existing file is overwritten. "
        "Providing it implies an install (ADR-0015 parity with argv --dir). Mutually "
        "exclusive with provider.",
    )
    provider: SkillProvider | None = Field(
        default=None,
        description="Install into a KNOWN agent's skills directory instead of a "
        "caller-supplied install_dir: resolves that agent's directory at scope "
        "(ADR-0027). Mutually exclusive with install_dir; providing it implies an install.",
    )
    scope: SkillScope = Field(
        default=SkillScope.USER,
        description="With provider, whether to install into the agent's per-project "
        "(committed) or per-user (all projects) skills directory; default user.",
    )

    @model_validator(mode="after")
    def _resolve_install_target(self) -> "SkillParams":
        # Single source of truth (ADR-0015): normalize the target HERE, in the model, so
        # argv and a --params-json object agree. A named provider resolves to its known
        # skills dir (ADR-0027) — but provider and an explicit install_dir name the SAME
        # thing two ways, so giving both is ambiguous and rejected. Then, whichever way a
        # target was named, naming one means "install there".
        if self.provider is not None:
            if self.install_dir is not None:
                raise ValueError(
                    "provider and install_dir are mutually exclusive: name an agent "
                    "(--provider) OR a directory (--dir), not both"
                )
            self.install_dir = resolve_skill_dir(self.provider, self.scope)
        if self.install_dir is not None:
            self.install = True
        return self


class SkillResult(BaseModel):
    """The result of ``gda skill``: the bundled Skill, version-locked (ADR-0024).

    ``name``/``version``/``content`` carry the manifest's identity, the installed
    ``gda`` version (from ``importlib.metadata``, so the guidance cannot skew from
    the CLI it describes), and the full ``SKILL.md`` text. ``installed_path`` is the
    path written on ``--install`` and ``None`` for a plain emit, so one model serves
    both the emit and install paths.
    """

    name: str
    version: str
    content: str
    installed_path: Path | None = None


# The bundled Skill manifest, resolved package-relative (NOT importlib.resources)
# so it works the same in a source checkout and an installed wheel — the same
# pattern ``gda.runner.OPERATIONS_GD`` uses for the GDScript payload. The payload
# ships under the ``gda`` package root, so the walk is up one level out of
# ``gda/commands/`` (ADR-0040 moved this module, not the shipped file).
SKILL_MD = Path(__file__).parent.parent / "skill" / "SKILL.md"


def read_skill_text() -> str:
    """Return the bundled ``SKILL.md`` text."""
    return SKILL_MD.read_text(encoding="utf-8")


def build_skill_result(
    *, install: bool = False, install_dir: str | None = None
) -> SkillResult:
    """Build the ``gda skill`` result, optionally installing the manifest.

    The plain (non-install) result carries the manifest identity — ``name``, the
    installed ``gda`` ``version`` (so the guidance is version-locked, ADR-0024), and
    the full ``content``. On ``install`` the bundled ``SKILL.md`` is written to
    ``<install_dir>/SKILL.md`` (parents created, overwrite is fine), and the written
    path is reported on ``installed_path``. ``install_dir`` is **required** for an
    install — core carries no agent-specific default location (ADR-0024); the caller
    supplies the per-agent path. ``~`` is expanded so a tilde path resolves.
    """
    content = read_skill_text()
    result = SkillResult(
        name="gda",
        version=package_version("gda"),
        content=content,
    )
    if not install:
        return result
    if not install_dir:
        raise ValueError("an install needs an explicit target directory (--dir)")
    target_dir = Path(install_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    target.write_text(content, encoding="utf-8")
    return result.model_copy(update={"installed_path": target})


# The name the help text addresses the CLI by. Fixed rather than read from the
# process, so `gda help` reads the same under the console script and under
# `python -m gda` (which names itself "python -m gda" in its own usage line).
CLI_NAME = "gda"


def build_help_result(app: typer.Typer, path: list[str]) -> "HelpResult | Failure":
    """Render the help of the command ``path`` names, or refuse the path.

    Walks the LIVE Typer command tree — the same authority ``gda schema`` projects
    from (ADR-0012) — so `help` describes exactly what is installed. The text is
    produced by the command's own help renderer, so this adds no second rendering to
    keep in step with ``--help``.

    A path that names nothing is the SAME refusal an unrecognized command gets at the
    parser (``gda.hints``), curated hint included: `gda help scene inspect` is the
    same mistake as `gda scene inspect`, so it must not get a different answer.
    """
    command = typer.main.get_command(app)
    walked: list[str] = []
    # The chain root-first, so the help can be rendered under contexts that spell the
    # full invocation in its usage line.
    lineage: list[object] = [command]
    for token in path:
        subcommands = getattr(command, "commands", None)
        target = subcommands.get(token) if subcommands is not None else None
        if target is None:
            named = " ".join([CLI_NAME, *walked, token])
            hit = near_miss(tuple(walked), token, on_group=False)
            return make_failure(
                UNKNOWN_COMMAND,
                f"`{named}` is not a gda command"
                + (
                    f". Use `{hit.use}` instead: {hit.because}"
                    if hit is not None
                    else f"; {DISCOVERY}"
                ),
                "",
                hint=hit.use if hit is not None else None,
            )
        command = target
        walked.append(token)
        lineage.append(target)
    return HelpResult(
        command=" ".join([CLI_NAME, *walked]), text=_rendered_help(lineage, walked)
    )


def _rendered_help(lineage: list, path: list[str]) -> str:
    """The help text the last command in ``lineage`` prints for ``--help``.

    Typer renders help through Rich, which WRITES to the console instead of filling
    click's help formatter — so ``get_help`` returns an empty string and the text
    arrives on stdout. Capturing that stdout is therefore how to get the REAL
    rendering rather than a second one; the non-Rich fallback returns the text
    instead, so both arms are read. The contexts are built parent-first, from the
    lineage, so the usage line spells the full invocation (`Usage: gda scene get …`)
    — which is the line a reader needs most.
    """
    context = None
    for name, node in zip([CLI_NAME, *path], lineage):
        context = typer.Context(node, info_name=name, parent=context)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        returned = lineage[-1].get_help(context)
    return returned or buffer.getvalue()


def classify_info(result: RunResult, binary: Path) -> EngineVersion | Failure:
    """Classify the raw ``info`` result into a success model or a ``Failure``.

    The per-command layer for ``info``: the shared decision tree comes from
    ``classify_run``; only the ADR-0003 minimum-version gate is ``info``'s own.
    """
    outcome = classify_run(result, binary, EngineVersion)
    if isinstance(outcome, Failure):
        return outcome
    version = outcome

    if (version.major, version.minor) < MIN_GODOT_VERSION:
        # The engine ran fine but is older than gda supports (ADR-0003), making
        # "version too old" a programmatically detectable failure rather than an
        # implicit one — distinct from the environment-error case.
        minimum = ".".join(str(part) for part in MIN_GODOT_VERSION)
        return make_failure(
            "unsupported_version",
            f"Godot {version.string} is below the minimum supported version {minimum}",
            result.stderr,
        )

    return version


def render_engine_version(version: "EngineVersion") -> str:
    """Render the engine version as its one-line version string."""
    return version.string


def render_skill(skill: "SkillResult") -> str:
    """Render ``gda skill`` as text (ADR-0024).

    A plain emit prints the raw ``SKILL.md`` verbatim, so
    ``gda skill > .../SKILL.md`` drops the manifest straight to disk; an
    ``--install`` instead reports the written path (the file already holds the
    same content) rather than echoing it twice.
    """
    if skill.installed_path is not None:
        return f"Installed the gda Skill to {skill.installed_path}"
    return skill.content


def render_version(provenance: "VersionProvenance") -> str:
    """Render ``gda version`` as text: the one line the root ``--version`` prints.

    The same one-liner, from the same builder, so the flag and the command are one
    answer in both channels rather than two that can drift.
    """
    return render_version_line()


def render_help(help_result: "HelpResult") -> str:
    """Render ``gda help`` as text: the help itself, verbatim.

    The same shape ``gda skill`` uses for the manifest it emits (ADR-0024) — the
    payload IS the human output, so the text form prints it unchanged and the JSON
    form carries it as a field.
    """
    return help_result.text


INFO_COMMAND: HeadlessCommand[EngineVersion] = HeadlessCommand(
    operation="info",
    input_model=InfoParams,
    output_model=EngineVersion,
    render=render_engine_version,
    classify=classify_info,
    # A meta command about the ENGINE, so it inherits no project context — but it does
    # accept and validate an explicit `--project` (#670). See the field's own doc.
    projectless=True,
)


def _skill_recipe(params, *, project, godot):
    # A pure local emitter (ADR-0024): no project, no Godot — it reads the bundled
    # SKILL.md and either returns it (version-locked) or installs it. ``project`` /
    # ``godot`` are part of the recipe contract but unused here (a meta command).
    return build_skill_result(install=params.install, install_dir=params.install_dir)


# `gda skill` is a pure emitter meta command (ADR-0024): it reads the in-package
# SKILL.md and emits or installs it, spawning no Godot — so, like `export run` and
# the daemon lifecycle, it carries a `recipe` on its descriptor and dispatches
# through it (`dispatch_recipe`) rather than the sentinel pipeline. It stays
# HEADLESS `kind` (the default) and meta (no --project), a sibling of info/schema.
SKILL_COMMAND: HeadlessCommand[SkillResult] = HeadlessCommand(
    operation="skill",
    input_model=SkillParams,
    output_model=SkillResult,
    render=render_skill,
    recipe=_skill_recipe,
    # A pure meta emitter (ADR-0024): no --project, resolves none — so the recipe
    # dispatcher must not resolve a project for it (an inherited invalid $GDA_PROJECT
    # must not make `gda skill` fail, #357).
    projectless=True,
)


def _version_recipe(params, *, project, godot):
    # A pure local emitter (ADR-0005 meta, #659 payload): it reads this install's own
    # metadata and never launches Godot — which is the point, since the environment
    # where provenance matters most is one where an engine spawn fails.
    return build_version_provenance()


def _help_recipe(params, *, project, godot):
    # The composition root imports THIS module, so the app is imported here rather
    # than at module scope; `build_help_result` takes it as an argument and stays a
    # pure function of the tree it is handed.
    from gda.cli import app

    return build_help_result(app, list(params.command))


# Both are pure emitter meta commands, so — like `gda skill` (ADR-0024) — they carry a
# `recipe` and dispatch through it rather than the sentinel pipeline, and both are
# `projectless`: they take no --project and must not resolve one, or an inherited
# invalid $GDA_PROJECT would break the two commands an agent reaches for FIRST when
# something is wrong (#357's rule, same reasoning).
VERSION_COMMAND: HeadlessCommand[VersionProvenance] = HeadlessCommand(
    operation="version",
    input_model=VersionParams,
    output_model=VersionProvenance,
    render=render_version,
    recipe=_version_recipe,
    projectless=True,
)

HELP_COMMAND: HeadlessCommand[HelpResult] = HeadlessCommand(
    operation="help",
    input_model=HelpParams,
    output_model=HelpResult,
    render=render_help,
    recipe=_help_recipe,
    projectless=True,
)


def register(root: typer.Typer) -> None:
    """Attach the meta commands to the root app (ADR-0005/0040).

    A meta command is top-level and ungrouped, so — unlike a domain group, which
    mounts its own sub-app — this defines the three commands directly against the
    ``root`` it is handed. ``gda schema`` additionally CLOSES OVER ``root`` for
    its surface walk: the manifest is read off the live Typer tree, which is the
    only registry (ADR-0012/0023).
    """

    @root.command(cls=INFO_COMMAND.command_class())
    def info(
        json_output: bool = json_option(),
        schema: bool = INFO_COMMAND.schema_option(),
        params_json: Optional[str] = params_json_option(),
        godot: Optional[str] = godot_option(),
        project: Optional[str] = project_option(),
    ) -> None:
        """Report the Godot engine version info.

        `--project` is accepted so an orchestrator can pass one argv shape to every
        command (#670). It is validated like anywhere else — a directory that is not a
        Godot project is a structured `project_not_found` — and the engine then runs
        against it, so that project's autoloads run as they do for any `--project` op.
        The reported version does not depend on it; omit it for the plain engine probe,
        which is also what an inherited `$GDA_PROJECT` gets you: this command never
        acquires a project it was not explicitly given.
        """
        dispatch_meta(
            INFO_COMMAND,
            InfoParams(),
            json_output=json_output,
            godot=godot,
            project=project,
        )

    @root.command(cls=SKILL_COMMAND.command_class())
    def skill(
        install: bool = typer.Option(
            False,
            "--install",
            help="Write the bundled SKILL.md into the skills directory instead of printing it.",
        ),
        dir: Optional[str] = typer.Option(
            None,
            "--dir",
            help="The skills directory to install into (caller-supplied; the neutral path, "
            "no default). Implies --install. Mutually exclusive with --provider.",
        ),
        provider: Optional[SkillProvider] = typer.Option(
            None,
            "--provider",
            "-p",
            help="Install into a known agent's skills directory (claude/codex) instead of "
            "--dir, resolved with --scope (ADR-0027). Implies --install.",
        ),
        scope: SkillScope = typer.Option(
            SkillScope.USER,
            "--scope",
            help="With --provider: the agent's per-project (committed) or per-user (all "
            "projects) skills dir; default user.",
        ),
        json_output: bool = json_option(),
        schema: bool = SKILL_COMMAND.schema_option(),
        params_json: Optional[str] = params_json_option(),
    ) -> None:
        """Emit or install the bundled gda Agent Skill (no Godot is spawned).

        The canonical `SKILL.md` ships inside the `gda` package and is version-locked to
        the install (ADR-0024): a plain run prints it verbatim (so
        `gda skill > .../SKILL.md` drops it to disk), `--json` emits
        `{name, version, content}`, and an install writes it to a directory, creating
        parents and overwriting, then reports the path. The install target is named one
        of two ways: `--dir <path>` (the neutral path; core carries no agent-specific
        default, ADR-0024), or `--provider <agent> --scope <scope>` which resolves a known
        agent's skills directory (the opt-in convenience, ADR-0027). A sibling of
        `info`/`schema`, carrying `--schema` like them.
        """
        # The target is named by --dir OR --provider; they name the SAME thing two ways, so
        # both at once is ambiguous, and an install with neither has nowhere to write. Both
        # rules are mirrored in SkillParams (so the --params-json path enforces them too,
        # ADR-0015); resolving provider→dir also happens there. The CLI raises the friendly
        # usage errors and otherwise just forwards the raw flags.
        if dir is not None and provider is not None:
            raise typer.BadParameter(
                "`--dir` and `--provider` are mutually exclusive: name a directory OR an "
                "agent, not both"
            )
        if install and dir is None and provider is None:
            raise typer.BadParameter(
                "`--install` requires `--dir` or `--provider` (where to write the SKILL.md)"
            )
        dispatch_recipe(
            SKILL_COMMAND,
            SkillParams(
                install=install, install_dir=dir, provider=provider, scope=scope
            ),
            json_output=json_output,
            godot=None,
            project=None,
        )

    @root.command(cls=schema_command_class(SchemaAllParams, SurfaceManifest))
    def schema(
        json_output: bool = json_option(),
        schema: bool = schema_option(),
    ) -> None:
        """Emit the whole command surface as one JSON manifest; no Godot is spawned.

        The aggregate generalisation of per-command ``--schema`` (ADR-0004/0012):
        one entry per command in every group, each carrying
        ``{name, description, input, output, error}``. gda-mcp introspects this once
        at startup to generate its tool surface, so it stays a faithful mirror of the
        installed ``gda`` with no codegen step. As a meta command (ADR-0005) it is
        top-level and ungrouped, a sibling of ``gda info``.

        `--json` is accepted and idempotent: the manifest is already the JSON
        result, so the flag changes nothing and an agent can pass it uniformly.
        """
        # `json_output` is DECLARED but not read — the same idiom as `schema` /
        # `params_json` on every other command, which the command class intercepts
        # rather than the body. Here there is nothing to switch on: this command's
        # only output IS the JSON manifest, so `--json` cannot change it. Declaring
        # it is the point (#671): the ONE rule an agent follows — "always pass
        # --json" — must not exit 2 on the very surface that describes the others,
        # and the declared option is what inherits a root `--json` (gda.headless).
        typer.echo(build_surface_manifest(root).model_dump_json())

    @root.command(cls=VERSION_COMMAND.command_class())
    def version(
        json_output: bool = json_option(),
        schema: bool = VERSION_COMMAND.schema_option(),
        params_json: Optional[str] = params_json_option(),
    ) -> None:
        """Report which gda is installed, and where it came from (no Godot is spawned).

        The command spelling of the root `--version` flag, and the same answer: bare,
        one human-readable line; with `--json`, the structured install provenance —
        version, executable, interpreter, imported package path, install kind, an
        editable install's source checkout with its Git revision and dirty flag, and
        the Godot binary gda would use (resolved, never launched). Run it first in a
        long session and keep the output: it is what ties later results to the code
        that produced them. For the ENGINE's version, run `gda info`.
        """
        dispatch_recipe(
            VERSION_COMMAND,
            VersionParams(),
            json_output=json_output,
            godot=None,
            project=None,
        )

    @root.command(cls=HELP_COMMAND.command_class())
    def help(
        command: Optional[list[str]] = typer.Argument(
            None,
            help="The command to describe, as the words typed after `gda` "
            "(e.g. `scene get`); omit it for the whole CLI.",
        ),
        json_output: bool = json_option(),
        schema: bool = HELP_COMMAND.schema_option(),
        params_json: Optional[str] = params_json_option(),
    ) -> None:
        """Show the help for a command, or for gda itself (no Godot is spawned).

        `gda help scene get` is `gda scene get --help`, reached from the argv form
        agents reach for; a bare `gda help` is `gda --help`. The text is the command's
        own rendering, never a second one, so the two forms cannot drift. `--json`
        returns it as `{command, text}` — the ONE rule ("always pass `--json`") holds
        here too, while the `--help` FLAG stays text-only. A path that names no
        command is refused exactly as the parser refuses it, curated hint included.
        """
        dispatch_recipe(
            HELP_COMMAND,
            HelpParams(command=list(command or [])),
            json_output=json_output,
            godot=None,
            project=None,
        )
