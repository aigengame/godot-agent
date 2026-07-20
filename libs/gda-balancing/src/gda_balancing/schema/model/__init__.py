"""The pydantic Design-document model — the single source of truth.

Every published structural artifact is a generated projection of these models
(bADR-0005); a hand-maintained second copy is prohibited. Model constraints
follow the placement rule: a constraint lives here iff it is local to one
instance element, expressible as a JSON Schema 2020-12 keyword, and
engine-agreed — everything needing cross-element context, parameter
resolution, graph analysis, or evaluation is a semantic-phase rule
(bADR-0004).
"""
