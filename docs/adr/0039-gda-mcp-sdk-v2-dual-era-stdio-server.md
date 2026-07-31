---
status: accepted
---

# gda-mcp on MCP SDK v2: one low-level stdio server serving both protocol eras

The MCP spec revision **2026-07-28** turns the protocol from bidirectional-stateful
into request/response-stateless: the `initialize` handshake is retired in favor of
`server/discover`, each request self-describes in `_meta`, and the server→client
back-channels — **roots**, sampling, logging — are deprecated (SEP-2577, 12-month
window) in favor of multi round-trip requests (MRTR: a tool returns
`InputRequiredResult{input_requests, request_state}` and the client retries with
`input_responses`). The Python SDK's v2.0.0 implements the revision with a breaking
API: constructor-callback handler registration, snake_case wire-model fields, the
in-memory test client (`mcp.Client`), and no automatic wrapping of tool results.

gda-mcp (ADR-0011/0012/0013/0014) was pinned to `mcp>=1.12,<2` and used two things
the revision deprecates: the `roots/list` back-channel (ADR-0014 precedence level 2)
and its `roots/list_changed` invalidation (#209). Staying pinned means riding a
deprecated protocol generation to its removal; migrating naively means breaking one
era or the other — every surveyed agent (Claude Code, Codex, Cursor, Claude Desktop)
still speaks the pre-2026 protocol over stdio, while new clients will arrive
stateless.

## Decision

**gda-mcp adopts MCP SDK v2 (`mcp>=2,<3`) and serves both protocol eras from the one
low-level stdio `Server`.** Pre-2026 clients complete the legacy `initialize`
handshake and keep today's behavior bit-for-bit; 2026-07-28 clients are served the
stateless path by the same binary. Both eras are a permanent automated gate (the
real console script driven under `mode="legacy"` **and** `mode="auto"`), not a
compatibility claim. Concretely:

- **Stay on the low-level `Server`.** The ADR-0012 rationale is unchanged by v2:
  our schemas come *from* gda, tools are discovered at runtime and served by one
  generic dispatcher, and the result/error channels need direct control — v2 keeps
  the low-level API first-class (constructor callbacks), so the generated-surface
  design ports mechanically.
- **Roots is acquired by capability, not by era.** ADR-0014's precedence is
  untouched (`GDA_PROJECT` strict → client roots → cwd); only level 2's acquisition
  becomes connection-dependent: gda-mcp calls the deprecated-but-working
  `list_roots()` **iff** `session.can_send_request` and the client advertises the
  roots capability. A 2026-07-28 connection has no back-channel (`can_send_request`
  is `False`), so the roots level is skipped silently — no `NoBackChannelError`, no
  failed round trip — landing on env → cwd, exactly the setup every registration
  recipe already pins. `GDA_PROJECT` is thereby promoted from "recommended" to
  **the durable anchor**: it is the one resolution input that survives the roots
  deprecation clock. The `roots/list_changed` invalidation (#209) stays registered
  and is legacy-only by nature (modern connections never deliver it).
- **The SDK's deprecation warnings are suppressed at exactly two sites** — the
  `Server(...)` construction (registering `on_roots_list_changed` warns) and the
  `list_roots()` call — because stderr is the agent-visible log channel of a stdio
  server, and a per-session warning would read as noise in every agent's MCP log.
  The suppression is commented with SEP-2577 and the 12-month window; when the SDK
  actually removes the APIs, the fallback is already the code's other branch.
- **The v1 success wrap is reproduced in-house.** v2 no longer auto-wraps a
  handler's return: gda-mcp constructs `CallToolResult` itself — the success dict
  as `structured_content` **plus** the indented-JSON `TextContent` block v1 used to
  emit (clients that render `content` rather than `structured_content` would
  otherwise silently lose every result). Output-schema validation **moved sides**
  in v2 — v1 validated on the server (downgrading a non-conforming success to a
  structured error result); v2 validates on the SDK *client* only, so a non-SDK
  client sees results unvalidated. Accepted: gda-mcp's conformance is by
  construction (result and `output_schema` share one Pydantic model), so the
  check was redundant on this server. Spike-verified either way: an
  `is_error=True` result without `structured_content` bypasses the validation
  entirely, so ADR-0011's verbatim-envelope error relay is untouched.

## Considered options

- **Drop roots now (env → cwd only).** Where the deprecation clock ends anyway, but
  doing it inside the migration turns a dependency bump into a user-visible
  regression for the one agent whose recipe ships an empty `env` and relies on
  roots auto-detection. Behavior preservation is the point of the migration slice;
  roots retirement happens by attrition when the SDK removes `list_roots()`.
- **MRTR `ListRootsRequest` now.** The revision's sanctioned roots replacement —
  but it turns the first tool call of a modern session into an `input_required`
  interstitial that *fails* on clients without a roots callback (today's silent
  fall-through is strictly better), it models "fetch ambient workspace config" as
  a user-facing prompt, and no real agent can exercise it yet, so it would ship
  verified only against the SDK's own client. **Deferred with a trigger**: revisit
  when a real agent ships a 2026-07-28 client whose users cannot pin
  `GDA_PROJECT`. If it lands, gate it on the client advertising roots and cap it at
  one MRTR round per connection (an unanswerable retry marks roots permanently
  unavailable and falls to cwd).
- **Per-request MRTR, no caching.** Doubles round trips on every call and discards
  ADR-0014's snapshot-then-cache contract for zero gain.
- **A `project` tool argument.** The spec's own suggested replacement for roots —
  and still rejected: ADR-0014 keeps the project out of the tool surface so it
  stays a faithful `--schema` mirror (ADR-0012).
- **A `gda_use_project` meta-tool.** Real multi-project support without touching
  any mirrored tool's schema — but it hand-writes a tool into a deliberately
  generated surface and is *stateful*, precisely what the 2026-07-28 revision moves
  away from (it cannot work behind a load balancer).
- **Streamable-HTTP transport.** The revision makes stateless HTTP trivially
  load-balanceable, but for gda-mcp an HTTP listener is a **trust-boundary
  change**, not a transport flag: nearly every gda command executes target-project
  code (ADR-0009), so anyone who can reach the socket gets code execution on the
  host, and ADR-0013 fixes the launch contract as a stdio console script. If ever
  wanted it needs its own PRD and an ADR extending ADR-0009 / amending ADR-0013
  (auth story, loopback-only default bind, per-connection project resolution).

## Consequences

- The `mcp` pin moves to `>=2,<3` everywhere it appears (the `[mcp]` extra, the
  `dev` group, and the `assets-live` group — one `uv.lock`), which also migrates
  the second in-repo SDK consumer, panda-adventure's asset-gen MCP channel
  (`FastMCP` → `MCPServer`, `ClientSession` → `Client`, `McpError` → `MCPError`,
  `timedelta` timeout → float seconds).
- The fast tier drives the server through `mcp.Client` in-memory
  (`raise_exceptions=True`, so server crashes surface instead of the SDK's
  sanitized internal-error reply); the stdio e2e gate is parameterized over both
  eras; a degrade test pins "stateless connection + no pin → projectless success".
- SDK v2 validates structured content on **every** call (v1 skipped it when the
  tool definition wasn't cached), so canned test results must conform to the real
  output schemas — a test-tier tightening, not a behavior change.
- Cache hints on `tools/list` (`ttlMs`/`cacheScope`, new in the revision) are a
  natural follow-up for the process-immutable generated surface; they only reach
  2026-07-28 clients and are tracked separately (#602).
