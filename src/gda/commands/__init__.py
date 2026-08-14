"""One module per `Command group` (ADR-0040).

Each module in this package owns its group's whole vertical slice — the
params/result models, the human renderers, the group-specific classifiers, the
``HeadlessCommand`` descriptors (ADR-0023) and the Typer command bodies — and
exposes a single ``register(root: typer.Typer) -> None`` that mounts the group
on the root app. ``gda.cli`` (the composition root) calls those ``register``
functions in the historical ``add_typer`` order, so ``--help`` is unchanged;
mounting IS the registration, keeping the live Typer tree the only registry
(ADR-0012/0023). ``meta`` is the one non-domain module: its commands are
top-level and ungrouped (ADR-0005), so its ``register`` attaches them to
``root`` directly and closes over it for the ``gda schema`` surface walk.

Dependency direction (ADR-0040 §5): ``cli`` → ``commands/*`` → ``dispatch`` →
``headless`` → runners / ``errors`` / ``models``. A group module may import
another group's public model one-way where the language genuinely shares a
shape — ``node`` → ``scene`` for ``SceneNode`` and ``derive_scene_root_name``
(the filename-stem default an ``--instance`` composition reuses), ``shader`` →
``script`` for the ``ScriptSetMode`` edit interface ``shader set`` reuses,
``logger`` → ``diag`` for the ``SourceFrame`` location and the ``--limit`` tail
option the two log-reading groups share (the ADR-0022/0026 lineage that made
``logger`` the structured successor of ``diag``'s raw view); no reciprocal
group imports.
"""
