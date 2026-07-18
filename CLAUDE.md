@AGENTS.md

## Subagent model tier configuration (including built-in Explore/Plan/General subagents and workflow fan-out subagents)

Concretizes the model-selection principle of RULES.md (if exists), which this
table implements — pass `model:` explicitly on every dispatch; never silently inherit
the session model.

- Reconnaissance, exploration, summarization, and retrieval: **Sonnet** by default;
  escalate to **Opus** only when the digest's precision directly gates downstream
  design quality (e.g. ADR/issue digests feeding a design gate).
- Large fan-out stages (N-vote adversarial panels, bulk refutation voters, bulk
  search/fetch): **Sonnet** per voter/fetcher; the single synthesis, judge, or
  high-stakes verifier stays **Opus**.
- Design reviews, single-point adversarial validation, consistency checks, and
  routine tasks: **Opus**.
- **Fable** is used only for main-loop coordination, orchestration, final judgment,
  or the design and implementation of the most complex tasks.
