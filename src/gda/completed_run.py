"""The completed-run result base shared by ``script run`` and ``export smoke``.

A `Raw run` (:class:`gda.runner.RunResult`) is normally internal. Two commands
promote part of it to a public result — ``gda script run`` (ADR-0031) and
``gda export smoke`` (ADR-0042) — and they promote the SAME part: the child's
exit status, its bounded stdout with the spill metadata that bounds it, its
stderr, and the recognized diagnostics. This module owns that shared half so
neither command copies it:

- :data:`STDOUT_CAP`, the one cap both bounded projections use, and
  :data:`DEFAULT_COMPLETED_RUN_TIMEOUT_SECONDS`, the one default ceiling both
  commands publish as the same number;
- :func:`bounded_stdout`, the projection itself, and :func:`spill_failure`, the
  typed refusal for a spill file gda could not write;
- :func:`completed_run_schema_extra`, the truth table both results publish;
- :class:`CompletedRunResult`, the base that carries that schema extra and the
  matching runtime validator.

It sits BELOW both command groups (ADR-0040) rather than inside either: the
shared half belongs to neither ``script`` nor ``export``, and
``gda.commands.export`` imports its machinery downward only. Nothing here knows
about a script, an artifact, or a project — each command adds its own addressing
fields and their prose.

**The base declares no fields, deliberately.** Pydantic orders a subclass's
fields base-first, so declaring them here would move ``script run``'s ``path``
out of the first position and change its result bytes and its published schema.
``gda.models.ProjectRootedResult`` made the same choice for the same reason: a
field-less base leaves a subclass's schema — field order included — exactly what
it was. What is shared is therefore the RULE (the validator, the schema
projection, the cap and the spill mechanics), while each result spells its own
fields with its own descriptions, which differ because the subjects differ: one
passes a user script's run through, the other an exported game's.
"""

import os
import tempfile
from typing import Protocol, cast

from pydantic import BaseModel, model_validator

from gda.errors import Failure, make_failure

# The returned-stdout cap of a completed-run SUCCESS result (#665, GDA-DF-036):
# production-scale inspector output grows linearly with content, and an envelope
# that grows with it blows the consuming agent's context. 64 KiB keeps on the
# order of a thousand record lines readable inline while bounding the envelope;
# the COMPLETE stream above it spills to a named file, so nothing is lost —
# bounded, not summarized (record semantics stay with the project tool). The cap
# qualifies ONLY the success result's `stdout` field (ADR-0031 amendment):
# `stderr` and the failure envelopes' partial-output evidence keep their shapes.
STDOUT_CAP = 64 * 1024

# The DEFAULT ceiling on ONE completed run, when the caller states none — shared
# by both consumers because it bounds the same thing: a child gda launched, whose
# own work it cannot predict, ended by an external wall clock. A user script is
# arbitrary project code and an exported game loads a whole project, so both need
# more room than a single sentinel op's tight bound and far less than the export
# channel's; 120s is enough for a logic-seam test or a startup without leaving a
# hung run to block forever.
#
# It is a default, not the only value (#655): a fixed ceiling made a healthy suite
# that had grown past it indistinguishable from a hang, with no way to raise it
# (GDA-DF-032). Each command's ``--timeout`` is that way.
#
# ONE authority, not two equal numbers (#979 review): `script run`'s help, `export
# smoke`'s help and params description, and the catalog all state that the two
# ceilings are the same number, and a duplicated literal would let an edit to
# either silently falsify three published sentences. Each command keeps its own
# public name as an alias, so nothing else moves.
DEFAULT_COMPLETED_RUN_TIMEOUT_SECONDS = 120.0


def completed_run_schema_extra(schema: dict) -> None:
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
                    "stdout_bytes": {"exclusiveMinimum": STDOUT_CAP},
                    "stdout": {
                        # A maximal UTF-8-safe cut loses at most three bytes;
                        # at four bytes/code point, this is the weakest implied
                        # character floor a standard validator can publish.
                        "minLength": STDOUT_CAP // 4,
                        "maxLength": STDOUT_CAP,
                    },
                }
            },
        },
        {
            "if": {"properties": {"stdout_truncated": {"const": False}}},
            "then": {
                "properties": {
                    "stdout_file": {"type": "null"},
                    "stdout_bytes": {"maximum": STDOUT_CAP},
                    "stdout": {"maxLength": STDOUT_CAP},
                }
            },
        },
    ]


def spill_failure(
    subject: str, exit_status: int, full_bytes: int, error: OSError
) -> Failure:
    """The typed ``stdout_spill_failed`` for a spill file gda could not write (#665).

    The bound is unconditional (AC2): a stream above the cap either returns as
    its truncated head WITH the complete stream persisted, or the operation is
    this structured failure — never an unbounded result and never a silently
    lost tail. The message carries the run's forensics (it DID run) and the
    remediation: the spill lands in the platform temp dir, so point TMPDIR at a
    writable location and re-run.

    ``subject`` names WHAT ran, because the two consumers run different things —
    a user script and an exported game — and the sentence leads with the run that
    produced the stream. That is the whole generalization the second consumer
    needed (ADR-0042): the bound, the remedy and the code are unchanged.
    """
    return make_failure(
        "stdout_spill_failed",
        f"the {subject} ran (exit status {exit_status}) and printed {full_bytes} "
        f"bytes of stdout — above the {STDOUT_CAP} byte cap — but the "
        f"complete-stream spill file could not be written ({error}); the "
        "bounded result cannot be delivered without it. Point TMPDIR at a "
        "writable directory and re-run",
        "",
    )


def bounded_stdout(
    stdout: str, exit_status: int, *, subject: str, prefix: str
) -> "tuple[str, int, bool, str | None] | Failure":
    """Bound a success result's stdout (#665): (returned, full_bytes, truncated, file).

    At or below :data:`STDOUT_CAP` the stream returns verbatim. Above it, the
    COMPLETE stream is written to a gda-named spill file and the returned text is
    the leading cap bytes, cut on a UTF-8 boundary (a multi-byte character
    straddling the cap is dropped, never mangled). A spill file that cannot be
    created OR completed is the typed ``stdout_spill_failed`` (#748 review: the
    bound is unconditional, and a post-create failure must not leave a partial
    file or an open fd behind).

    ``prefix`` names the spill file after the channel that wrote it, so two
    channels spilling into one temp directory stay tellable apart; ``subject``
    is what :func:`spill_failure` calls the run.
    """
    data = stdout.encode("utf-8")
    if len(data) <= STDOUT_CAP:
        return stdout, len(data), False, None
    try:
        fd, spill_path = tempfile.mkstemp(prefix=prefix, suffix=".log")
    except OSError as error:
        return spill_failure(subject, exit_status, len(data), error)
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
        return spill_failure(subject, exit_status, len(data), error)
    # Interior bytes re-encoded from str are valid UTF-8; only the cut edge can
    # split a character, so "ignore" drops at most that one partial character.
    head = data[:STDOUT_CAP].decode("utf-8", "ignore")
    return head, len(data), True, spill_path


class BoundedStdout(Protocol):
    """The four fields :func:`bounded_stdout` produces, as one result states them.

    The base below validates a model it declares no fields on, so this names what
    that model must carry. A Protocol rather than a set of declared fields,
    because declaring them would fix their ORDER for every subclass — see the
    module docstring.
    """

    stdout: str
    stdout_bytes: int
    stdout_truncated: bool
    stdout_file: str | None


def check_stdout_projection(result: BoundedStdout) -> None:
    """Raise ``ValueError`` unless the four bounded-stdout markers agree (#748 review).

    The bounded-stdout truth table: the markers are ONE machine contract, not
    independent fields. Truncated means a spill file exists and the full stream
    is above the cap; untruncated means no spill file and ``stdout`` IS the whole
    stream.
    """
    inline_bytes = len(result.stdout.encode("utf-8"))
    if result.stdout_truncated:
        if result.stdout_file is None:
            raise ValueError(
                "a truncated stdout must name its complete-stream spill file."
            )
        if result.stdout_bytes <= STDOUT_CAP:
            raise ValueError(
                "a truncated stdout implies a full stream above the cap "
                f"({STDOUT_CAP} bytes)."
            )
        if inline_bytes < STDOUT_CAP - 3:
            raise ValueError(
                "a truncated stdout is the maximal UTF-8-safe prefix at the "
                f"{STDOUT_CAP} byte cap — it cannot be shorter than "
                f"{STDOUT_CAP - 3} bytes."
            )
        if inline_bytes > STDOUT_CAP:
            raise ValueError(
                "a truncated stdout is the stream's leading cap bytes — it "
                f"cannot itself exceed {STDOUT_CAP} bytes."
            )
    else:
        if result.stdout_file is not None:
            raise ValueError("an untruncated stdout carries no spill file.")
        if inline_bytes > STDOUT_CAP:
            raise ValueError(
                "an untruncated stdout is the complete stream at or below "
                f"the {STDOUT_CAP} byte cap."
            )
        if result.stdout_bytes != inline_bytes:
            raise ValueError(
                "an untruncated stdout's byte count is the returned "
                "stream's own length."
            )


class CompletedRunResult(BaseModel):
    """The base of a result that publishes one completed child run (ADR-0042).

    It declares no fields (see the module docstring) and carries the two things
    both completed-run results owe their readers: the published bounded-stdout
    truth table, and the runtime validator that enforces it. A subclass spells
    ``exit_status``, ``stdout``, ``stderr``, ``stdout_bytes``,
    ``stdout_truncated``, ``stdout_file`` and ``diagnostics`` in the order its
    own result reports them, plus whatever addresses the run: the canonical
    script path and the launch's `User-data placement` for ``script run``, the
    caller's artifact and the resolved executable for ``export smoke``.
    """

    model_config = {
        "json_schema_extra": lambda schema: completed_run_schema_extra(schema)
    }

    @model_validator(mode="after")
    def _check_stdout_projection(self) -> "CompletedRunResult":
        # `self` carries the four markers by the base's own contract — the one
        # the Protocol above names and that no declared field can state here
        # without fixing every subclass's field order (see the module docstring).
        check_stdout_projection(cast(BoundedStdout, self))
        return self
