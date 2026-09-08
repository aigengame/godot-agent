"""`gda.import_evidence` — the reimport-test adapter, read directly (#741).

Every verdict here is a question about PROJECT ARTIFACTS: given this sidecar,
this cache file and this `.md5` receipt, what would
`EditorFileSystem::_test_for_reimport` decide? Asking it of `asset_state` costs
a temp tree and a function call; the same question used to pay the whole Typer +
JSON-envelope toll, which is what made the adapter's seam worth cutting.

What stays on the CLI side (`test_resource_import_commands`) is everything the
COMMAND decides on top of a verdict: whether a pass runs, the before/after
accounting, the settlement vocabulary, the request refusals, the render — plus a
dry-run smoke per evidence state, so the wire ABI keeps its own cover.
"""

import hashlib

from gda.import_evidence import (
    CACHE_ROOT_REL,
    asset_state,
    classify_created_file,
    project_import_gaps,
)
from tests.resource.import_artifacts import (
    cached_asset,
    icon_project,
    md5_companion,
    receipt_path,
    sidecar,
)

DEST = ".godot/imported/icon.png-" + "a" * 32 + ".ctex"


# --- the four evidence states, from the artifacts alone -------------------------


def test_keep_importer_sidecar_counts_as_cached(tmp_path):
    project = icon_project(tmp_path)
    sidecar(project, "icon.png", None, importer="keep")

    assert asset_state(project, "res://icon.png").status == "cached"


def test_stale_source_is_stale_not_cached(tmp_path):
    # #738 review [P1]: freshness rides the engine's own md5 receipt — a source
    # that hashes differently from the recorded source_md5 would be re-imported
    # by the engine, so gda agrees.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    (project / "icon.png").write_bytes(b"\x89PNG different bytes")

    assert asset_state(project, "res://icon.png").status == "stale"


def test_minimal_sidecar_is_stale_not_cached(tmp_path):
    # #738 re-review 2 [P1]: a parseable sidecar with only a uid line proved
    # nothing, yet fell through to cached and suppressed the pass the engine
    # would run. A CACHED verdict needs positive evidence.
    project = icon_project(tmp_path)
    (project / "icon.png.import").write_text('uid="uid://test"\n', encoding="utf-8")

    assert asset_state(project, "res://icon.png").status == "stale"


def test_sidecar_without_an_importer_line_is_stale(tmp_path):
    # The engine's importer-existence check re-imports a sidecar whose
    # importer cannot be resolved; a missing declaration proves nothing. The
    # tree is otherwise CACHEABLE — destination present, receipt matching — so
    # the missing declaration alone decides (PR #882 review round 3: the old
    # fixture fell through to a missing receipt and pinned nothing).
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    (project / "icon.png.import").write_text(
        f'[remap]\n\nuid="uid://test"\n\n[deps]\n\nsource_file="res://icon.png"\n'
        f'dest_files=["res://{DEST}"]\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "stale"


def test_copied_sidecar_naming_another_source_is_stale(tmp_path):
    # #738 review [P1], the alias reproduction: copying icon.png + its sidecar
    # to alias2.png leaves source_file="res://icon.png" inside the copy — the
    # engine re-imports that; a destination-exists heuristic called it cached.
    # The alias has its OWN matching receipt, so the tree is cacheable except
    # for the source name — only that check can produce the verdict (PR #882
    # review round 3: without the receipt the fixture fell through to stale).
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    (project / "alias2.png").write_bytes((project / "icon.png").read_bytes())
    (project / "alias2.png.import").write_text(
        (project / "icon.png.import").read_text(encoding="utf-8"), encoding="utf-8"
    )
    md5_companion(project, DEST, "alias2.png")

    assert asset_state(project, "res://alias2.png").status == "stale"


def test_wrong_source_beside_a_malformed_receipt_is_invalid_not_stale(tmp_path):
    # Engine order (PR #882 review round 3): _test_for_reimport reads the .md5
    # receipt BEFORE it compares source_file, and a receipt parse error is the
    # deliberate skip — so a copied sidecar whose receipt is malformed is left
    # alone by the engine. Checking the source name first reported stale and
    # spent a pass the engine would not.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    (project / "alias2.png").write_bytes((project / "icon.png").read_bytes())
    (project / "alias2.png.import").write_text(
        (project / "icon.png.import").read_text(encoding="utf-8"), encoding="utf-8"
    )
    receipt = receipt_path(project, "alias2.png")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('source_md5="unterminated\n', encoding="utf-8")

    assert asset_state(project, "res://alias2.png").status == "invalid"


def test_no_destination_sidecar_with_matching_receipt_is_cached(tmp_path):
    # #738 re-review 4 [P1]: a sidecar declaring no destinations, whose
    # path-derived receipt exists and matches, is CURRENT to the engine
    # (there is nothing to check and the receipts pass) — the pass leaves it
    # untouched, so gda must not spend a pass on it or settle it failed.
    project = icon_project(tmp_path)
    sidecar(project, "icon.png", None)  # importer=texture, uid, source_file
    md5_companion(project, "", "icon.png")

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "cached"
    assert evidence.sidecar == "res://icon.png.import"
    assert evidence.dest_files == []


def test_an_asset_with_no_sidecar_is_missing(tmp_path):
    # The fourth evidence state asked of the adapter directly: no `.import`
    # sidecar at all is `missing` — a pass would run — with no sidecar facts to
    # report. (The CLI smoke covers the same state through the wire; this pins
    # the adapter's own branch so a later per-state `reason` (#853) has a home.)
    project = icon_project(tmp_path)

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "missing"
    assert evidence.sidecar is None
    assert evidence.dest_files == []


# --- the .md5 receipt: the engine's own freshness proof -------------------------


def test_missing_md5_receipt_is_stale_not_cached(tmp_path):
    # #738 review [P1]: without the receipt the engine cannot prove freshness
    # and re-imports; gda must not claim a hit the engine would not.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").unlink()

    assert asset_state(project, "res://icon.png").status == "stale"


def test_receipt_lacking_source_md5_is_stale_not_invalid(tmp_path):
    # The boundary NEXT to the parse error: a receipt that PARSES but lacks
    # source_md5 is the engine's "Lacks md5, so just reimport" — a pass
    # state, not the deliberate skip.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").write_text(
        'dest_md5="' + "a" * 32 + '"\n', encoding="utf-8"
    )

    assert asset_state(project, "res://icon.png").status == "stale"


def test_dest_md5_mismatch_is_stale(tmp_path):
    # The engine's receipt also digests the DESTINATION bytes (one MD5 over
    # every dest, in order); a tampered cache file must not stay a hit.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt = receipt_path(project, "icon.png")
    dest_digest = hashlib.md5(b"OTHER BYTES").hexdigest()
    receipt.write_text(
        receipt.read_text(encoding="utf-8") + f'dest_md5="{dest_digest}"\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "stale"


# --- the receipt grammar: gda's VariantParser-compatible subset -----------------


def test_receipt_uses_the_last_source_md5_assignment(tmp_path):
    # #738 re-review 6 [P1]: VariantParser consumes every assignment, so a
    # later source_md5 replaces an earlier value. Taking the first value spends
    # a pass the engine would skip.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    receipt_path(project, "icon.png").write_text(
        f'source_md5="{"0" * 32}"\nsource_md5="{source_digest}"\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "cached"


def test_receipt_last_source_md5_mismatch_is_stale(tmp_path):
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    receipt_path(project, "icon.png").write_text(
        f'source_md5="{source_digest}"\nsource_md5="{"0" * 32}"\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "stale"


def test_receipt_uses_the_last_dest_md5_assignment(tmp_path):
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    dest_digest = hashlib.md5((project / DEST).read_bytes()).hexdigest()
    receipt_path(project, "icon.png").write_text(
        f'source_md5="{source_digest}"\n'
        f'dest_md5="{"0" * 32}"\n'
        f'dest_md5="{dest_digest}"\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "cached"


def test_receipt_accepts_spacing_comments_and_escaped_string_values(tmp_path):
    # VariantParser accepts spacing, semicolon comments, and quoted-string
    # escapes even though the engine's own writer emits a canonical subset.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    receipt_path(project, "icon.png").write_text(
        "; retained hand-written comment\n"
        'note = "escaped \\"quote\\"" ; ignored assignment\n'
        f'source_md5 = "{source_digest}" ; current source\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "cached"


def test_receipt_lone_surrogate_escape_is_invalid_not_stale(tmp_path):
    # #738 review follow-up: json.loads accepts a LONE UTF-16 surrogate
    # escape, but VariantParser rejects it ("unpaired lead surrogate") — the
    # engine's deliberate parse-error skip. Classifying it stale would spend
    # a pass the engine would not run.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").write_text(
        'source_md5="\\ud800"\n', encoding="utf-8"
    )

    assert asset_state(project, "res://icon.png").status == "invalid"


def test_receipt_paired_surrogate_escape_still_parses(tmp_path):
    # The boundary pin: a PAIRED surrogate escape decodes to one real code
    # point on both sides (json.loads and VariantParser agree), so it stays
    # inside the subset — with a matching source_md5 the asset is cached.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    source_digest = hashlib.md5((project / "icon.png").read_bytes()).hexdigest()
    receipt_path(project, "icon.png").write_text(
        'note="\\ud83d\\ude00"\n' + f'source_md5="{source_digest}"\n',
        encoding="utf-8",
    )

    assert asset_state(project, "res://icon.png").status == "cached"


# --- the project-wide gap scan --------------------------------------------------


def test_no_destination_sidecar_is_excluded_from_the_gap_scan(tmp_path):
    # A state the pass leaves untouched must not be listed as work it will do.
    project = icon_project(tmp_path)
    sidecar(project, "icon.png", None)
    md5_companion(project, "", "icon.png")
    (project / "fresh.png").write_bytes(b"\x89PNG fresh")

    assert project_import_gaps(project, {"res://fresh.png"}) == []


def test_malformed_receipt_neighbor_is_excluded_from_the_gap_scan(tmp_path):
    # The engine's deliberate parse-error skip, seen from the inventory side:
    # an `invalid` neighbour is never pass work when ANOTHER asset triggers it.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")
    (project / "fresh.png").write_bytes(b"\x89PNG fresh")

    assert asset_state(project, "res://icon.png").status == "invalid"
    assert project_import_gaps(project, {"res://fresh.png"}) == []


def test_the_gap_scan_skips_every_directory_the_engines_scan_never_reaches(tmp_path):
    # #804: the prediction must not promise work the engine's pass never does.
    # `EditorFileSystem::_should_skip_directory` skips a directory holding a
    # `project.godot` or a `.gdignore`, so a stale sidecar under one is never
    # re-imported — the gap scan reads the project's files directly and used to
    # report both. A stale asset in an ordinary directory is still a gap, so this
    # narrows the scan rather than emptying it.
    #
    # The DOT-prefixed directory is the third case, and the one the marker clauses
    # alone still got wrong (#808 review): `_scan_new_dir` drops such a directory
    # BEFORE it consults the skip rule, so `res://.hidden/pic.png` is unreachable
    # too. Measured against a real pass, which re-imported the ordinary asset and
    # left the hidden one's sidecar and cache artefacts untouched.
    project = icon_project(tmp_path)
    for directory, marker in (("nested", "project.godot"), ("ignored", ".gdignore")):
        (project / directory).mkdir()
        (project / directory / marker).write_text("", encoding="utf-8")
        (project / directory / "pic.png").write_bytes(b"\x89PNG skipped")
        sidecar(project, f"{directory}/pic.png", None)
    for hidden in (".hidden", "sub/.hidden"):
        (project / hidden).mkdir(parents=True)
        (project / hidden / "pic.png").write_bytes(b"\x89PNG hidden")
        sidecar(project, f"{hidden}/pic.png", None)
    (project / "ordinary").mkdir()
    (project / "ordinary" / "pic.png").write_bytes(b"\x89PNG reached")
    sidecar(project, "ordinary/pic.png", None)

    gaps = project_import_gaps(project, {"res://icon.png"})

    assert gaps == ["res://ordinary/pic.png"], gaps


# --- the created-file classification the command and #839 share -----------------


def test_created_files_are_classified_against_the_cache_root(tmp_path):
    # The one-line rule `resource import` applied inline until #741, named once
    # so `export run`'s tree-mutation report (#839) reuses it. The input is the
    # project-relative posix path `_project_files` yields.
    assert CACHE_ROOT_REL == ".godot"
    assert classify_created_file(".godot") == "cache_owned"
    assert classify_created_file(".godot/imported/icon.png-a.ctex") == "cache_owned"
    assert classify_created_file("icon.png.import") == "source_adjacent"
    assert classify_created_file("scripts/tool.gd.uid") == "source_adjacent"
    # A sibling whose name only STARTS with the cache root is not under it.
    assert classify_created_file(".godotignore") == "source_adjacent"


# --- the reason behind an `invalid` verdict (#853) -------------------------------


def test_a_sidecar_that_is_not_utf8_names_the_unparsable_reason(tmp_path):
    # The first `invalid` branch: the bytes do not decode, so no line can be
    # named — the sidecar path IS the offending artifact and the record already
    # carries it, so `detail` stays empty rather than repeating it.
    project = icon_project(tmp_path)
    (project / "icon.png.import").write_bytes(b'importer="texture"\n\xff\xfe\n')

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "invalid"
    assert evidence.reason == "sidecar_unparsable"
    assert evidence.detail is None
    assert evidence.sidecar == "res://icon.png.import"


def test_a_malformed_dest_files_line_names_that_line(tmp_path):
    # The second spelling of the same reason, and the one that CAN name a line:
    # `dest_files=` looks like the engine's list but does not parse.
    project = icon_project(tmp_path)
    (project / "icon.png.import").write_text(
        '[remap]\n\nimporter="texture"\nuid="uid://test"\n\n[deps]\n\n'
        'source_file="res://icon.png"\ndest_files=[oops]\n',
        encoding="utf-8",
    )

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "invalid"
    assert evidence.reason == "sidecar_unparsable"
    assert evidence.detail == "dest_files=[oops]"


def test_a_malformed_files_line_names_that_line(tmp_path):
    # The engine's OTHER remap list (`files=`), read after the destinations:
    # one reason, whichever list failed, and the line says which.
    project = icon_project(tmp_path)
    (project / "icon.png.import").write_text(
        '[remap]\n\nimporter="texture"\nuid="uid://test"\nfiles=[oops]\n\n'
        '[deps]\n\nsource_file="res://icon.png"\n',
        encoding="utf-8",
    )

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "invalid"
    assert evidence.reason == "sidecar_unparsable"
    assert evidence.detail == "files=[oops]"


def test_a_valid_false_sidecar_names_the_engines_own_verdict(tmp_path):
    # Not a parse failure at all: the ENGINE marked the last import failed, and
    # the reason must say so — the caller's fix is a source repair, not a syntax
    # repair (PIPE-DF-191 could not tell the two apart).
    project = icon_project(tmp_path)
    sidecar(project, "icon.png", None, valid=False)

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "invalid"
    assert evidence.reason == "sidecar_marked_invalid"
    assert evidence.detail is None


def test_unsupported_receipt_syntax_names_the_receipt_path(tmp_path):
    # The third reason, whose `detail` earns its place: the `.md5` receipt is
    # derived from the asset path and appears NOWHERE else on the record, so the
    # offending artifact would otherwise be unnameable.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").write_text("source_md5=[\n", encoding="utf-8")

    evidence = asset_state(project, "res://icon.png")

    assert evidence.status == "invalid"
    assert evidence.reason == "receipt_unsupported"
    assert (
        evidence.detail
        == "res://" + receipt_path(project, "icon.png").relative_to(project).as_posix()
    )


def test_a_lone_surrogate_receipt_is_the_same_receipt_reason(tmp_path):
    # The VariantParser divergence has its own state test above; here it must
    # arrive under the SAME reason, because the caller's fix is the same one.
    project = icon_project(tmp_path)
    cached_asset(project, "icon.png", DEST)
    receipt_path(project, "icon.png").write_text(
        'source_md5="\\ud800"\n', encoding="utf-8"
    )

    assert asset_state(project, "res://icon.png").reason == "receipt_unsupported"


def test_the_states_the_engine_would_act_on_carry_no_reason(tmp_path):
    # The reason explains a verdict the pass will NOT change. `cached`,
    # `missing` and `stale` are all states the engine acts on itself, so
    # attaching an explanation to them would invent a failure.
    project = icon_project(tmp_path)
    assert asset_state(project, "res://icon.png").reason is None  # missing
    cached_asset(project, "icon.png", DEST)
    cached = asset_state(project, "res://icon.png")
    assert cached.status == "cached" and cached.reason is None
    (project / "icon.png").write_bytes(b"\x89PNG different bytes")
    stale = asset_state(project, "res://icon.png")
    assert stale.status == "stale"
    assert stale.reason is None and stale.detail is None
