extends RefCounted

# gda headless operations payload: composed static validation of a scene and
# the sub-scenes it references (#664, #721, ADR-0043 §2). Static: callers reach
# it through a preload constant, and it reports no failure — a verdict is a list
# of problems the caller emits.

const GDSCRIPT_SCAN := preload("gdscript_scan.gd")
const SCENE_TEXT := preload("scene_text.gd")


# The problem kinds scene-validate reports, one per unresolvable dependency of a
# scene (#664). Values, not free prose: gda projects them into a closed enum on
# the published result, so an agent branches on the kind instead of matching a
# message. SCENE_PROBLEM_SCRIPT_COMPILE_FAILED deliberately spells the same string
# as the script_compile_failed error code — it is the same condition, reported as
# a verdict here rather than as a refusal.
const SCENE_PROBLEM_MISSING_RESOURCE := "missing_resource"
const SCENE_PROBLEM_UNLOADABLE_RESOURCE := "unloadable_resource"
const SCENE_PROBLEM_SCRIPT_COMPILE_FAILED := "script_compile_failed"
# Deliberately the same word OP_ERROR_INCOMPATIBLE_SCRIPT_TYPE's remedy speaks:
# the script compiles but its native base cannot bind the node that carries it.
const SCENE_PROBLEM_INCOMPATIBLE_SCRIPT := "incompatible_script"
# The three problems the SUB-SCENE walk can raise that a single file never does
# (#721). The first is a real defect: a scene references one that already
# references it, and Godot refuses the closing reference. The other two are LIMITS
# gda declares about ITSELF — the walk stopped or could not read the target, so
# what lies below is unchecked rather than sound. Both are reported for the same
# reason the depth one was: a gate must not answer "sound" about a subtree it never
# opened (GDA-DF-030).
const SCENE_PROBLEM_CYCLIC_INSTANCE := "cyclic_instance"
const SCENE_PROBLEM_INSTANCE_DEPTH_EXCEEDED := "instance_depth_exceeded"
# A referenced scene in the BINARY .scn form (#721 review). It loads perfectly
# well; what it does not carry is the [gd_scene] TEXT the walk reads its
# dependency set out of — the same reason the top-level op refuses a .scn
# outright. Measured on Godot 4.6.3: a .tscn parent instancing a .scn child whose
# script has a syntax error, or whose script cannot bind its node, answered
# `valid: true, problems: []` while the engine's own load of that parent reported
# the child's break. Silence there reproduces exactly the defect this command
# exists to prevent.
const SCENE_PROBLEM_UNREADABLE_SUB_SCENE := "unreadable_sub_scene"

# How many levels of referenced sub-scenes below the validated scene the walk
# descends before it stops and says so (#721 review). The bound is on the
# SHORTEST route to each file, not on the first route walked — see `reached_depth` in
# _new_scene_walk for why that distinction is the contract and not an internal.
#
# It bounds GDA'S OWN work, and nothing else. Measured on Godot 4.6.3 against a
# straight chain of N scenes each instancing the next (two runs each, quiet
# machine): the pre-#721 command is FLAT at ~2s for both N=100 and N=300, because
# it does ONE load and the engine walks the chain internally. The unbounded
# composed walk added a per-file pass on top of that load and went 5-7s at N=100
# and 38-47s at N=300 — superlinear, and close enough to the 60s launch ceiling
# that it CROSSES it into launch_timeout when the machine is under load, which is
# how the regression was first seen. Bounded, the same chains take 3-4s and 5-6s.
#
# It does NOT make deep chains safe, and must not be described as if it did: at
# N=1200 the engine's own loader overflows its stack and the run dies with signal
# 11 — on the PRE-#721 code too, where no gda recursion exists. That failure is the
# engine's, it is reached through the single top-level load this bound does not
# touch, and no cap here can prevent it.
#
# 16 is the number _packed_scene_root_type already refuses past, on the very same
# axis (it walks the instancing chain of a scene's root), and the number
# JSONIFY_MAX_DEPTH uses for value recursion. Real compositions nest a handful of
# levels deep; 16 leaves large headroom while keeping the walk's cost bounded.
const SCENE_INSTANCE_MAX_DEPTH := 16


# One scene file's OWN verdict — the two-stage check, without any sub-scene: the
# dependency walk, and, only when it found nothing, the binding scan of the loaded
# scene. Returns the problems, or null when the file did not load as a scene at
# all. Shared by the root and by every sub-scene the walk descends into (#721), so
# a composed verdict is the same question asked of each file rather than a second
# implementation.
#
# The load is only ASKED when the scan found nothing: a scene already known broken
# needs no second opinion, and loading it would only add the engine's own cascade
# to stderr. The BINDING scan (#720 review) then answers what the dependency walk
# cannot — the walk proves each referenced file loads, but not that a script can
# bind the node that carries it, and it never sees an EMBEDDED [sub_resource
# type="GDScript"] at all. Both are read off the loaded scene's state, so that
# stage runs only when the load did.
#
# The null return is a fact, not a verdict: what the CALLER does with it differs
# (the root refuses, the walk skips), which is why this reports the condition
# instead of deciding it.
static func _scene_own_problems(path: String) -> Variant:
	var problems := _scene_dependency_problems(path)
	if not problems.is_empty():
		return problems
	var packed := ResourceLoader.load(path, "PackedScene") as PackedScene
	if not _is_loaded_scene(packed):
		return null
	return _scene_binding_problems(packed)


# Stamp every problem with the scene file it was found in, and hand the array back
# (#721). ATTRIBUTION is what makes a composed verdict readable: without it a
# missing script inside child.tscn reads as a problem of parent.tscn, and each
# problem's `nodes` — which are relative to the scene that owns them — would be
# resolved against the wrong tree. Present on EVERY problem, the root's included,
# so a reader never has to infer it.
static func _attributed_problems(problems: Array, scene_path: String) -> Array:
	for problem in problems:
		(problem as Dictionary)["scene"] = scene_path
	return problems


# The OUTCOME an edge of the scene graph has been settled with, and the rule that
# promotes one into the other (#721 review round 4). An edge — one declaring file,
# one target — carries at most ONE problem, and these say which and whether it
# still stands:
#
# - SCENE_EDGE_DEPTH_PENDING is PROVISIONAL. The edge was declined because its
#   target lay past the depth bound ON THIS ROUTE, and the finding it holds is
#   published only at the end, and only if no route ever reached that target
#   inside the bound (_flush_pending_depth_problems);
# - SCENE_EDGE_REPORTED is TERMINAL. A problem about this edge is already in the
#   result, and nothing later can add a second one or take it back.
#
# PROMOTION: provisional -> terminal is allowed, and WITHDRAWS the pending
# finding; every other transition is refused. That rule is the whole reason an
# edge has an outcome instead of an "already reported" flag. With one flag for
# both states, a deep route's depth deferral SUPPRESSED the cyclic_instance a
# later, shorter route proved on the same edge, and the deferral was then dropped
# because its target had been reached — so a cyclic composition answered
# `valid: true`. Measured on Godot 4.6.3 over `root -> d1 ... d15 -> s -> t` plus
# `root -> t -> s`: valid deep-first, one cyclic_instance direct-first (#721
# review round 4).
#
# Promotion never loses a finding: a cycle target is by definition an ancestor of
# the current descent, and the walk records a file's depth before it descends into
# it, so that target was reached inside the bound — which is exactly the condition
# under which the flush drops a pending finding anyway.
const SCENE_EDGE_DEPTH_PENDING := "depth_pending"
const SCENE_EDGE_REPORTED := "reported"


# The traversal state of ONE composed verdict, in one bag (#721). Five fields that
# only ever move together, so they are passed as one rather than as five
# positionals that a later addition has to thread through every call site.
#
# Each answers exactly ONE question, and the comment says which — and, where it
# has been misread, which question it does NOT answer. Three rounds of review
# found the same defect three times, each time a single record standing for two
# states (seen/answered, answered/expanded, provisional/terminal), so the fields
# are documented as the questions they answer (#721 review round 4):
#
# - `problems` is the caller's own array, appended to in place;
#
# - `answered`: "has this file's OWN verdict been produced?" — validated, or
#   reported as one the walk cannot read. It is what makes a file's own problems
#   appear once however many sites reference it, and what keeps the one expensive
#   step (the load and the script compiles behind _scene_own_problems) to once per
#   file. It says NOTHING about the file's references: a file is answered for
#   before its subtree is walked, and stays answered when a later route walks that
#   subtree again;
#
# - `reached_depth`: "what is the SMALLEST depth at which the walk reached this
#   file INSIDE the bound?" — and, by carrying a key at all, "was this file
#   reached inside the bound?", which is the question every pending depth finding
#   is settled against. A file reached again at a strictly smaller depth is
#   expanded again from there, which is what makes the reachable SET a property of
#   the graph rather than of the order two [ext_resource] lines appear in. A file
#   with nothing below it to reach — missing, unreadable, or not a scene document
#   — is recorded at 0, the minimum, so no shorter route can improve on it. It
#   does NOT answer whether the file's own problems were produced (`answered`
#   does), and it is not a record of the routes taken, only of the best one;
#
# - `chain`: "which files are ancestors of the descent currently under way?" —
#   which is how a cycle is recognized, and whose SIZE is the depth of the edge
#   being examined (the same fact counted, not a second one). It is not a record
#   of what the walk has seen: it shrinks again on the way back up;
#
# - `edges`: "what OUTCOME has this edge — declaring file, then target — been
#   settled with, and what finding is still pending for it?" One record per edge;
#   see SCENE_EDGE_DEPTH_PENDING for the outcomes and the promotion rule between
#   them. Kept on the WALK rather than on one descent because a file can be
#   expanded more than once, and the same edge must not be reported once per
#   expansion.
#
# Every key is a CANONICAL path (_canonical_resource_path) — the root's included,
# which the caller must canonicalize before it seeds this. A root spelled
# `res://./main.tscn` seeded a key its own children's references could never match,
# so the file was answered for twice (#721 review round 3).
static func _new_scene_walk(root_path: String, problems: Array) -> Dictionary:
	return {
		"problems": problems,
		"answered": {root_path: true},
		"reached_depth": {root_path: 0},
		"chain": {root_path: true},
		"edges": {},
	}


# Descend into the scenes `scene_path` references, appending each one's own
# problems to the walk (#721). Depth-first in DECLARATION order, so the composed
# list reads parent-then-child, and each entry already carries the file it belongs
# to.
#
# Five decisions, none of them free:
#
# - WHAT is descended into is decided by _is_sub_scene_edge, the one projection
#   that owns "this reference is a sub-scene". Read it for the rule.
#
# - TERMINATION: `answered` holds every file the walk has produced a verdict
#   about, so it stops on its own — it is bounded by the number of DISTINCT scene
#   files reachable from the root, a finite set. A sub-scene is therefore reported
#   ONCE PER FILE, not once per referencing site: a broken child instanced at five
#   places is one broken file, which is the same rule the dependency walk already
#   applies to a path declared twice. Every key is the canonical path
#   (_resolve_ref_path), so an alias spelling is the same file.
#
# - DEPTH is bounded SEPARATELY, because terminating is not the same as finishing
#   in time (#721 review). Stopping was never the problem; COST was. Each level
#   adds a per-file pass on top of the single load the engine already walks the
#   chain for, and measured on a straight N-scene chain that term is superlinear:
#   the pre-#721 command is flat at ~2s for N=100 and N=300 while the unbounded
#   composed walk went 5-7s then 38-47s, near enough the 60s launch ceiling to
#   cross it under load. SCENE_INSTANCE_MAX_DEPTH
#   removes that term, and reaching it is REPORTED (instance_depth_exceeded) rather
#   than silently accepted, so an unchecked subtree never reads as a sound one. Read
#   that constant for what the bound does and does not do — in particular it does
#   not, and cannot, prevent the engine-side stack overflow that kills a 1200-deep
#   chain with or without any of this.
#
# - The bound is on the SHORTEST route, not on the first one walked.
#   `reached_depth` holds the smallest depth each file was reached at, and a file
#   reached again nearer the root is walked again from there — which is what makes
#   the published verdict independent of the order two [ext_resource] lines happen
#   to appear in. The cheap half of the walk (read the text, parse the lines) is
#   what repeats; the expensive half (`_scene_own_problems`: the load and the
#   script compiles) sits behind `answered` and runs once per file whatever the
#   shape of the graph. A file's recorded depth strictly decreases each time, and
#   depth is bounded by SCENE_INSTANCE_MAX_DEPTH, so the repetition is bounded too.
#
# - A CYCLE is reported, not merely survived: `chain` holds the ancestors of the
#   current descent, and a reference back into it becomes a cyclic_instance
#   problem attributed to the file that declares it. `answered` alone would stop
#   the walk silently, which would hide a composition the engine mutilates.
#   Checked BEFORE `answered` — every ancestor is also answered for, so the
#   cheaper test would swallow the diagnostic — and its outcome is TERMINAL, so it
#   also outranks whatever a deeper route left on the same edge
#   (see _report_cycle_edge).
static func _collect_sub_scene_problems(scene_path: String, walk: Dictionary) -> void:
	var text := FileAccess.get_file_as_string(scene_path)
	if text.is_empty():
		return
	var out: Array = walk["problems"]
	var answered: Dictionary = walk["answered"]
	var reached_depth: Dictionary = walk["reached_depth"]
	var chain: Dictionary = walk["chain"]
	for entry in SCENE_TEXT._ext_resource_entries_from_text(text, scene_path.get_base_dir()):
		if not _is_sub_scene_edge(entry):
			continue
		var ref_path := String(entry["normalized_path"])
		# Nothing is relaxed on this branch, and nothing needs to be: an ancestor
		# was reached at a smaller depth than the edge that points back at it, so
		# this route could not improve on its recorded depth.
		if chain.has(ref_path):
			_report_cycle_edge(walk, scene_path, text, entry)
			continue
		# `chain` holds the ancestors of this edge's target, so its size IS the
		# target's depth below the validated scene. DEFERRED rather than reported:
		# a shorter route to the same target may still reach it, and whether this
		# deep route or that short one is walked FIRST is nothing but declaration
		# order — see _flush_pending_depth_problems.
		var depth := chain.size()
		if depth > SCENE_INSTANCE_MAX_DEPTH:
			_defer_depth_edge(walk, scene_path, text, entry)
			continue
		# Already reached from here or from nearer the root: nothing this route can
		# add. Only a STRICTLY shorter route falls through, and then only to expand
		# the subtree again — never to repeat the file's own problems.
		if reached_depth.has(ref_path) and int(reached_depth[ref_path]) <= depth:
			continue
		if not answered.has(ref_path):
			answered[ref_path] = true
			# A referenced scene the walk cannot READ. Three cases, told apart
			# because the reader needs different things from them:
			#
			# - the file is not there, or is there but no loader opens it: the
			#   referencing file's own dependency walk has ALREADY named it
			#   (missing_resource / unloadable_resource) with the node that
			#   references it, so a second problem here would be one finding
			#   reported twice;
			# - the file LOADS as a PackedScene, but its bytes are not the
			#   [gd_scene] text the walk reads — a binary .scn, or a PackedScene
			#   saved into a .res resource file. Nothing has been said about it,
			#   and staying silent would let a composed verdict answer "sound"
			#   about a subtree it never opened;
			# - the file loads as something else entirely (a line that declares
			#   type="PackedScene" over a resource that is not one). The engine
			#   ignores that declaration and loads what is actually there, so there
			#   is no sub-scene here and nothing to report.
			#
			# All three are recorded at depth 0: there is nothing below them for a
			# shorter route to reach.
			if not FileAccess.file_exists(ref_path):
				reached_depth[ref_path] = 0
				continue
			if not _has_scene_header(FileAccess.get_file_as_string(ref_path)):
				if ResourceLoader.load(ref_path) is PackedScene:
					out.append(_sub_scene_edge_problem(SCENE_PROBLEM_UNREADABLE_SUB_SCENE, entry,
							scene_path, text,
							"this scene loads, but not as the [gd_scene] text gda reads a "
							+ "dependency set out of — a binary .scn, or a PackedScene saved "
							+ "into a resource file, carries none, which is why the command "
							+ "refuses such a file as its target too. This scene and "
							+ "everything it references are UNCHECKED, not judged sound. "
							+ "Re-save it as .tscn for a composed verdict that covers it"))
				reached_depth[ref_path] = 0
				continue
			var own: Variant = _scene_own_problems(ref_path)
			if own != null:
				out.append_array(_attributed_problems(own as Array, ref_path))
		# Descended into even when it did not load: its text is still readable, and
		# the scenes IT references can be broken for reasons of their own.
		reached_depth[ref_path] = depth
		chain[ref_path] = true
		_collect_sub_scene_problems(ref_path, walk)
		chain.erase(ref_path)


# Whether an [ext_resource] entry is an edge into a SUB-SCENE — the one projection
# that owns that question for the composed walk (#721 review round 3).
#
# A UNION of two triggers, because neither alone covers the scenes Godot writes:
#
# - the resolved PATH names a scene file: a .tscn, which the walk reads, or a
#   .scn, which it cannot and reports (unreadable_sub_scene). Extension is the
#   engine's own test for picking a format handler
#   (ResourceFormatLoader::recognize_path), and it is the only trigger that works
#   for a line whose declared type is wrong or absent;
# - the line DECLARES type="PackedScene". ResourceSaver will write a PackedScene
#   into a plain .res (ResourceFormatSaverBinary accepts "res" for any resource;
#   the text saver refuses, so .tres is not a form a PackedScene can be saved in),
#   and such a child was silently skipped by the extension test alone — a parent
#   instancing a .res scene with a broken script answered `valid: true` while the
#   engine's own load of that parent reported the break (measured on Godot 4.6.3).
#
# The declared type is an extra TRIGGER, never a FILTER. Selecting on it would
# MISS real edges, which is a separate measurement: Godot's text loader starts a
# load for EVERY [ext_resource] line before it parses a single node and passes
# `type` only as a HINT (ResourceLoaderText::load, ResourceFormatLoaderText::
# handles_type accepts every type), so a `.tscn` declared type="Resource" and
# never instanced breaks its referencing scene exactly as an instanced one does.
# Both facts point the same way: widen the trigger, never narrow it.
#
# What is still outside: a PackedScene stored under a non-scene extension AND
# declared as some other type. Nothing gda writes takes that form, and it is
# stated on the public surfaces rather than left implicit. Extending the union to
# "load every reference and ask what it is" is deliberately NOT done — it would
# load every texture and audio file a scene names to answer a question that has
# no known instance.
static func _is_sub_scene_edge(entry: Dictionary) -> bool:
	if _is_scene_reference_path(String(entry["normalized_path"])):
		return true
	return String(entry.get("type", "")) == "PackedScene"

# The per-declaring-file map of edge outcomes, created on the first edge that file
# settles (#721 review round 4). A Dictionary is a reference, so the caller writes
# through what it gets back.
static func _scene_edge_outcomes(walk: Dictionary, scene_path: String) -> Dictionary:
	var edges: Dictionary = walk["edges"]
	if not edges.has(scene_path):
		edges[scene_path] = {}
	return edges[scene_path]


# Publish the cyclic_instance this edge closes, and settle the edge TERMINALLY
# (#721).
#
# One edge problem per target per declaring file: a scene that references the same
# ancestor under two ids still closes ONE cycle, so a second call about the same
# edge publishes nothing. What it does do is PROMOTE — a provisional depth record
# left on this edge by a deeper route is replaced and its pending finding
# withdrawn. A cycle is a fact about the graph; a depth deferral is a statement
# about one route, so the cycle stands whichever order the two are met in, and the
# edge still carries exactly one problem. Read SCENE_EDGE_DEPTH_PENDING for the
# order-dependent false-clean verdict that came of not making that distinction.
static func _report_cycle_edge(walk: Dictionary, scene_path: String, scene_text: String,
		entry: Dictionary) -> void:
	var outcomes := _scene_edge_outcomes(walk, scene_path)
	var ref_path := String(entry["normalized_path"])
	var record: Dictionary = outcomes.get(ref_path, {})
	if String(record.get("outcome", "")) == SCENE_EDGE_REPORTED:
		return
	outcomes[ref_path] = {"outcome": SCENE_EDGE_REPORTED}
	(walk["problems"] as Array).append(
			_sub_scene_edge_problem(SCENE_PROBLEM_CYCLIC_INSTANCE, entry, scene_path, scene_text,
			"the scene at this path is an ancestor in this scene's reference chain, "
			+ "so referencing it here closes a cycle. Measured on Godot 4.6.3, the "
			+ "engine refuses the closing reference ([ext_resource] referenced "
			+ "non-existent resource), drops it, and the nodes it would have "
			+ "contributed vanish from the composition it loads. gda stopped the "
			+ "walk at this edge; break the cycle to get a verdict for what lies "
			+ "beyond it"))


# Hold this edge's depth finding PROVISIONALLY: the target lies past the bound on
# the route currently being walked, and a shorter route may still reach it (#721
# review).
#
# Recorded only on an edge nothing has settled yet — neither a pending finding of
# its own (one unchecked subtree, not one per route that declines it) nor a
# published problem, which already says what became of this edge. The finding
# itself is published, or dropped, by _flush_pending_depth_problems once every
# route has been walked.
static func _defer_depth_edge(walk: Dictionary, scene_path: String, scene_text: String,
		entry: Dictionary) -> void:
	var outcomes := _scene_edge_outcomes(walk, scene_path)
	var ref_path := String(entry["normalized_path"])
	if outcomes.has(ref_path):
		return
	outcomes[ref_path] = {
		"outcome": SCENE_EDGE_DEPTH_PENDING,
		"problem": _sub_scene_edge_problem(SCENE_PROBLEM_INSTANCE_DEPTH_EXCEEDED, entry,
				scene_path, scene_text,
				"gda validates " + str(SCENE_INSTANCE_MAX_DEPTH) + " levels of "
				+ "sub-scenes below the scene it was given, and no route to this one is "
				+ "inside that bound — this scene and everything it references are "
				+ "UNCHECKED, not judged sound. The bound is on gda's own walk: the "
				+ "engine still loads the whole chain itself, and at extreme depth its "
				+ "loader overflows and the run dies with no verdict at all, which this "
				+ "bound does not change. Validate this scene directly to get a verdict "
				+ "for it"),
	}


# Publish the depth findings the finished walk still stands behind (#721 review).
#
# A depth finding is a statement about a TARGET — "no verdict was established for
# this scene" — but the walk can only see one ROUTE at a time. In a diamond where a
# leaf sits both past the bound and one edge below the root, whichever route is
# declared first decided the verdict: deep-first reported the bound and then
# validated the leaf anyway (valid: false, with a stale finding), while
# direct-first validated the leaf and let the visited record swallow the deep edge
# in silence (valid: true). One graph, two published verdicts, chosen by the order
# two lines happen to appear in — which is not a contract.
#
# Deferring settles it in BOTH directions with the walk's own record: a pending
# finding survives only when nothing ever reached its target inside the bound.
# Order cannot change that, because it is read after every route has been walked.
# The other two halves of the same guarantee are `reached_depth` in
# _collect_sub_scene_problems, which is what makes a shorter route to an ANCESTOR
# of the deep target reach the target at all, and the promotion rule in
# _report_cycle_edge, which turns a pending record into the cycle a later route
# proves rather than letting it suppress one.
static func _flush_pending_depth_problems(walk: Dictionary) -> void:
	var reached_depth: Dictionary = walk["reached_depth"]
	var out: Array = walk["problems"]
	for scene_path in walk["edges"]:
		var outcomes: Dictionary = walk["edges"][scene_path]
		for ref_path in outcomes:
			var record: Dictionary = outcomes[ref_path]
			if String(record["outcome"]) != SCENE_EDGE_DEPTH_PENDING:
				continue
			if reached_depth.has(ref_path):
				continue
			out.append(record["problem"])


# One problem about an EDGE of the scene graph rather than about a file's
# contents (#721 review): the walk reached this reference and did not follow it.
# All three such kinds carry the same three facts — the target the edge points at,
# the file that declares it, and the nodes that reference it — so they are built in
# one place instead of three times.
#
# The nodes come from a per-TARGET map, not from this entry's id: one file can
# declare the same target under several [ext_resource] ids, and reading only the
# id that happened to settle the edge dropped the sites the others reference
# (#721 review round 3). It is the per-file merge _scene_dependency_problems
# already does for an ordinary dependency, applied to the edge kinds too.
#
# The map is built HERE, from the declaring file's text, rather than once per
# descent: an edge problem is the rare case, and the walk now expands a file again
# whenever a shorter route reaches it, so a map built eagerly would be rebuilt for
# every expansion of every file to serve the few that report one.
static func _sub_scene_edge_problem(kind: String, entry: Dictionary, scene_path: String,
		scene_text: String, message: String) -> Dictionary:
	var ref_path := String(entry["normalized_path"])
	var problem := _scene_problem(kind, ref_path, String(entry.get("type", "")), message)
	var nodes_by_path := _scene_ext_resource_nodes_by_path(scene_text, scene_path.get_base_dir())
	problem["nodes"] = (nodes_by_path.get(ref_path, []) as Array).duplicate()
	problem["scene"] = scene_path
	return problem


# Every node that references each [ext_resource] TARGET of one scene's text,
# merged across the ids that name it (#721 review round 3).
#
# _scene_ext_resource_nodes_by_id answers per id, which is the wrong grain for a
# report keyed by the file the reference points AT: two ids for one path — an
# alias spelling, or simply a hand-written duplicate — are one target with two
# sets of referencing nodes. In declaration order, deduplicated, which is the
# order and the rule _scene_dependency_problems merges by.
static func _scene_ext_resource_nodes_by_path(text: String, base_dir: String) -> Dictionary:
	var nodes_by_id := SCENE_TEXT._scene_ext_resource_nodes_by_id(text)
	var by_path := {}
	for entry in SCENE_TEXT._ext_resource_entries_from_text(text, base_dir):
		var ref_path := String(entry["normalized_path"])
		if not by_path.has(ref_path):
			by_path[ref_path] = []
		var nodes: Array = by_path[ref_path]
		for node_path in nodes_by_id.get(String(entry["id"]), []):
			if not nodes.has(node_path):
				nodes.append(node_path)
	return by_path


# Whether the text OPENS with a complete, CLOSED `[gd_scene …]` section header
# (#720 recheck ×2). Two requirements, each defeating a real bypass:
#
# - the section NAME must be exactly "gd_scene" (_is_section_header_line, the one
#   owner of that rule), or "[gd_scenery]" would pass a bare prefix test;
# - the header LINE must close with "]" — an unclosed "[gd_scene load_steps=2"
#   is not a header, and the load cannot be relied on to catch it: when the
#   dependency walk finds problems the load is deliberately skipped, so
#   admission must be decided here, completely.
#
# Leading whitespace and a UTF-8 BOM are tolerated. The question is identity,
# not well-formedness — a closed header over a broken body is still admitted,
# and the load has the final word only on that admitted case.
static func _has_scene_header(text: String) -> bool:
	var stripped := text.lstrip(" \t\r\n" + String.chr(0xFEFF))
	var line_end := stripped.find("\n")
	var line := stripped if line_end == -1 else stripped.substr(0, line_end)
	line = line.strip_edges()
	if not line.ends_with("]"):
		return false
	return SCENE_TEXT._is_section_header_line(line, "gd_scene")


# Whether a load produced a scene with a root — the two conditions _load_scene
# refuses separately, asked as one question by the validate path, which only needs
# to know whether the file is a scene at all.
static func _is_loaded_scene(packed: PackedScene) -> bool:
	if packed == null:
		return false
	var state := packed.get_state()
	return state != null and state.get_node_count() > 0


# One entry per SCRIPT the loaded scene binds that cannot actually serve its node
# (#720 review). The dependency walk above proves each referenced FILE loads; this
# walk asks the questions only the loaded state can answer:
#
# - an EMBEDDED [sub_resource type="GDScript"] never appears as an [ext_resource],
#   so a syntax error inside one is invisible to the text walk — here it shows up
#   as a script that cannot instantiate, named by its ::id sub-resource path;
# - a script that compiles can still be REFUSED by the engine at bind time when
#   the node's native class is outside the script's base (an `extends Resource`
#   script on a Node2D boots silently script-less). The compatibility rule is the
#   one _op_script_attach enforces at attach time, asked statically: the node's
#   type must be the script's base or inherit from it;
# - a `script` slot can hold a value that is not a Script at all — an embedded
#   [sub_resource] of another type (#709 review). The engine refuses that at
#   bind time too ("Cannot set object script") and the node boots script-less.
#
# Reported per SCRIPT with the referencing nodes merged, the dependency walk's own
# shape. A node without a type of its own (an instanced/inherited child) is
# skipped honestly: its real class lives in another scene, and guessing it would
# turn this into the false positive it exists to remove.
static func _scene_binding_problems(packed: PackedScene) -> Array:
	var state := packed.get_state()
	var problems: Array = []
	var by_script := {}
	for i in state.get_node_count():
		var node_type := String(state.get_node_type(i))
		for j in state.get_node_property_count(i):
			if String(state.get_node_property_name(i, j)) != "script":
				continue
			var value: Variant = state.get_node_property_value(i, j)
			if value == null:
				continue
			var problem: Variant
			if value is Script:
				problem = _script_binding_problem(value as Script, node_type)
			else:
				# A NON-Script value in the script slot — an embedded
				# [sub_resource] that is not a script, or anything the dependency
				# walk could not see. Discarding it silently (#709 review) turned
				# the engine's deterministic bind-time refusal into a clean
				# verdict.
				problem = _non_script_binding_problem(value)
			if problem == null:
				continue
			var key := String((problem as Dictionary)["path"]) + "|" + String((problem as Dictionary)["kind"])
			if not by_script.has(key):
				(problem as Dictionary)["nodes"] = []
				by_script[key] = problems.size()
				problems.append(problem)
			var nodes: Array = (problems[int(by_script[key])] as Dictionary)["nodes"]
			var node_path := String(state.get_node_path(i))
			if not nodes.has(node_path):
				nodes.append(node_path)
	return problems


# One bound script's verdict against one node type: a problem Dictionary (without
# its `nodes`, the caller owns attribution), or null when the binding is sound.
static func _script_binding_problem(script: Script, node_type: String) -> Variant:
	if not script.can_instantiate():
		# The scene loaded with the script attached, but the script itself never
		# compiled — the embedded-GDScript case (an external one is caught by the
		# dependency walk before the load is even asked). reload() on a script
		# that never compiled retries the compile and runs no project code.
		var err := script.reload()
		if err == OK and script.can_instantiate():
			return null
		return _scene_problem(SCENE_PROBLEM_SCRIPT_COMPILE_FAILED,
				script.resource_path, "Script",
				"the script does not compile: " + error_string(err))
	var base := script.get_instance_base_type()
	if String(base).is_empty() or node_type.is_empty():
		return null
	if not ClassDB.class_exists(node_type):
		return null
	if node_type == String(base) or ClassDB.is_parent_class(node_type, base):
		return null
	return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT,
			script.resource_path, "Script",
			"the script extends " + String(base) + ", which cannot bind a node of type "
			+ node_type + " — the engine would refuse the assignment and the node "
			+ "would run script-less. Bind it to a " + String(base)
			+ "-compatible target, or change the script's extends")


# The verdict for a `script` property whose value is not a Script at all (#709
# review): the engine refuses the assignment at instantiate time ("Cannot set
# object script. Parameter should be null or a reference to a valid script.",
# object.cpp set_script) and the node boots script-less — the same consequence as
# an incompatible base, so it is the same problem kind. The path names the bound
# resource where it has one (a res:// file, or the ::id sub-resource form for an
# embedded one); a non-resource value can only name its Variant type.
static func _non_script_binding_problem(value: Variant) -> Dictionary:
	var shown := type_string(typeof(value))
	var bound_path := ""
	if value is Resource:
		shown = (value as Resource).get_class()
		bound_path = (value as Resource).resource_path
	return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT, bound_path, "Script",
			"the node's script property binds a " + shown + ", not a Script — the "
			+ "engine would refuse the assignment (Cannot set object script) and "
			+ "the node would run script-less")


# One entry per DEPENDENCY the scene declares and gda could not resolve, in the
# order the .tscn declares them (#664).
#
# The dependency set is read from the file's [ext_resource] lines as text, not
# from the loaded PackedScene: the engine drops a reference it could not resolve,
# so the loaded object no longer knows the path that was asked for — which is the
# one thing a report has to name. Reading the text is also what attributes each
# dependency to the nodes that use it.
#
# A path declared twice (two ids for one file) is checked ONCE and reported once,
# with the referencing nodes merged: it is one broken file, not two problems.
static func _scene_dependency_problems(path: String) -> Array:
	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		return []
	var nodes_by_id := SCENE_TEXT._scene_ext_resource_nodes_by_id(text)
	var problems: Array = []
	# ref_path -> the index of its problem, or -1 when the dependency is fine. The
	# -1 rows matter as much as the others: they are what keeps a healthy path
	# declared twice from being re-checked (and re-loaded) on its second id.
	var checked := {}
	for entry in SCENE_TEXT._ext_resource_entries_from_text(text, path.get_base_dir()):
		var ref_path := String(entry["normalized_path"])
		if not checked.has(ref_path):
			var problem: Variant = _scene_dependency_problem(ref_path, String(entry.get("type", "")))
			if problem == null:
				checked[ref_path] = -1
			else:
				(problem as Dictionary)["nodes"] = []
				checked[ref_path] = problems.size()
				problems.append(problem)
		var at: int = int(checked[ref_path])
		if at >= 0:
			var nodes: Array = (problems[at] as Dictionary)["nodes"]
			for node_path in nodes_by_id.get(String(entry["id"]), []):
				if not nodes.has(node_path):
					nodes.append(node_path)
	return problems


# One dependency's verdict: a problem Dictionary, or null when it resolves (#664).
# `declared_type` is the type= the [ext_resource] line names ("Script",
# "Texture2D", …), reported back so a reader can tell WHAT was expected there.
#
# The three kinds answer three different questions, and the split is not cosmetic:
# a missing file needs the file, an unimported asset needs an import, and a broken
# script needs an edit.
static func _scene_dependency_problem(ref_path: String, declared_type: String) -> Variant:
	if not ResourceLoader.exists(ref_path):
		# ResourceLoader.exists() is the loadability question, not the file
		# question: an asset that was never imported (a .png with no import
		# artifacts) is present on disk yet has no loader in a non-editor run, and
		# the game would lose it at runtime exactly as this scene does. So the two
		# are told apart rather than both called missing.
		if FileAccess.file_exists(ref_path):
			return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
					"the file exists but no ResourceLoader can open it — typically an asset that was never imported")
		return _scene_problem(SCENE_PROBLEM_MISSING_RESOURCE, ref_path, declared_type,
				"the referenced file does not exist")
	if GDSCRIPT_SCAN._is_script_path(ref_path):
		# Ask the ALREADY-loaded script first (the scene's own load brought it in, so
		# this costs nothing and runs nothing): a script that compiled can be
		# instantiated, and one that did not reports an empty base type. Only when
		# that first answer is negative is a fresh compile run, which both confirms
		# the verdict and yields the Error the message quotes. Order matters for a
		# reason beyond speed: GDScript.reload() executes a script's STATIC
		# INITIALIZERS, so compiling every healthy script a second time would run
		# project code twice per validate.
		var loaded := ResourceLoader.load(ref_path) as GDScript
		if loaded == null:
			return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
					"the script file could not be loaded")
		if loaded.can_instantiate():
			return null
		var err := _script_compile_error(ref_path)
		if err != OK:
			return _scene_problem(SCENE_PROBLEM_SCRIPT_COMPILE_FAILED, ref_path, declared_type,
					"the script does not compile: " + error_string(err)
					+ " — run 'gda script validate " + ref_path + "' for the line and message")
		return null
	var resource := ResourceLoader.load(ref_path)
	if resource == null:
		return _scene_problem(SCENE_PROBLEM_UNLOADABLE_RESOURCE, ref_path, declared_type,
				"the resource could not be loaded")
	if declared_type == "Script" and not (resource is Script):
		# Declared as a script but the file is not one — a plain .tres in an
		# `[ext_resource type="Script"]` line (#709 review). The load alone cannot
		# answer this: the loader returns the Resource it found, and the engine
		# only refuses at bind time ("Cannot set object script"), when the node
		# has already booted script-less.
		return _scene_problem(SCENE_PROBLEM_INCOMPATIBLE_SCRIPT, ref_path, declared_type,
				"the file loads as " + resource.get_class() + ", not a Script — the engine "
				+ "would refuse the assignment (Cannot set object script) and the node "
				+ "would run script-less")
	return null


static func _scene_problem(kind: String, ref_path: String, declared_type: String, message: String) -> Dictionary:
	return {
		"kind": kind,
		"path": ref_path,
		"type": null if declared_type.is_empty() else declared_type,
		"message": message,
	}


# Whether a .gd compiles, as an Error — the SAME check script-validate makes, so
# "does not compile" means one thing across the two commands (#664).
#
# Loading a script that does not compile still hands back a GDScript object
# (verified against Godot 4.6.3), so the loaded object cannot produce the ERROR; a
# fresh compile can, which is why the caller falls back to this once the cheap check
# has already said something is wrong. take_over_path is what makes the script's own
# relative preloads resolve as in-engine (issue #131); it displaces the cached copy
# for the rest of this one-shot process, which nothing after this reads.
static func _script_compile_error(ref_path: String) -> int:
	var script := GDScript.new()
	script.source_code = FileAccess.get_file_as_string(ref_path)
	script.take_over_path(ref_path)
	return script.reload()


# Whether a path names a SCENE FILE in either of the two forms Godot saves one
# under a scene extension: the .tscn text gda reads, or the binary .scn it cannot.
# The composed walk asks this rather than _is_scene_path because the two answers
# it needs are different: what it can descend into, and what it must REPORT as
# unread rather than skip (#721 review). Extension is the engine's own test too —
# ResourceLoader picks a format handler by recognized extension
# (ResourceFormatLoader::recognize_path), not by the type an [ext_resource] line
# declares.
#
# The PATH half of the sub-scene edge rule only: a PackedScene saved into a plain
# .res carries no scene extension, so _is_sub_scene_edge unions this with the
# line's declared type. Read that function for the whole rule.
static func _is_scene_reference_path(path: String) -> bool:
	var ext := path.get_extension().to_lower()
	return ext == "tscn" or ext == "scn"
