class_name GeneratedConfig
extends RefCounted

## The single seam for loading a derived .tres config (gADR-0000: a Resource is a
## derived artifact, regenerated from JSON by scripts/build_config.py). Every
## controller routes its config load through here, so the loud guard and the
## pipeline-pointing remediation live in ONE place instead of duplicated across
## the controllers — one string to update when the builder moves (gADR-0011),
## and the read-side home of gADR-0000's "Resource is a derived artifact" contract.
##
## Returns the loaded Resource, or null after emitting the ONE canonical
## push_error naming the missing path. A committed .tres is expected to be
## present, so a null load means a half-checkout or a skipped build, not a
## gameplay condition. Callers keep their typed config vars and null-guard the
## return (behavior identical to the old inline load-then-guard idiom).


static func load_config(path: String) -> Resource:
	var config: Resource = load(path)
	if config == null:
		# The derived .tres is committed; guard loudly rather than crash on a
		# half-checkout, pointing at the pipeline that regenerates it from JSON.
		push_error("GeneratedConfig: could not load %s — run scripts/build_config.py." % path)
	return config
