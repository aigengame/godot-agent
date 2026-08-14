"""One module per `Command group` (ADR-0040).

Each module in this package owns its group's whole vertical slice — the
params/result models, the human renderers, the group-specific classifiers, the
``HeadlessCommand`` descriptors (ADR-0023) and the Typer command bodies — and
exposes a single ``register(root: typer.Typer) -> None`` that mounts the group
on the root app. ``gda.cli`` (the composition root) calls those ``register``
functions in the historical ``add_typer`` order, so ``--help`` is unchanged;
mounting IS the registration, keeping the live Typer tree the only registry
(ADR-0012/0023).

Dependency direction (ADR-0040 §5): ``cli`` → ``commands/*`` → ``dispatch`` →
``headless`` → runners / ``errors`` / ``models``. A group module may import
another group's public model one-way where the language genuinely shares a
shape (``node`` → ``scene`` for ``SceneNode``); no reciprocal group imports.
"""
