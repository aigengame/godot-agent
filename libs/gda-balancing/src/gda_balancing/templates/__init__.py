"""The shipped Genre templates (bADR-0012).

Each ``<id>.json`` here is a Genre template: a genre family's numeric design
baseline shipped as a canonical *instance of the Standard Schema* — data,
never code paths keyed on genre (bADR-0002). ``template get`` emits one
verbatim; the isolation gate exempts this directory from its per-game-config
scan (a Genre template is genre-generic, not a per-game config) while still
holding it to the game-identity vocabulary scan.
"""
