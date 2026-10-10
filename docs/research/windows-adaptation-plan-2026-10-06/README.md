# Windows Live feasibility probes

Recorded on 2026-10-06 using Windows 11, Python 3.13.7 and Godot 4.6.3 against
the pre-layering source at `6d5da3df36d7bf3ba6972c485ef955a2bf8c1926`.
These probes support [ADR-0047](../../adr/0047-windows-live-uses-local-tcp-and-owned-session-adapters.md);
the directory's historical name does not make it another implementation plan.

| Records | What was verified |
| --- | --- |
| `primitives_probe.py.txt`, `primitives-results.json` | Drive/UNC URI parsing and equivalent canonical project references; a separate Windows lock excludes another process, leaves metadata readable and releases on owner termination; controlled nested Jobs retire descendants while the leader runs and after it exits. |
| `acl-results.json` | A separately captured Get-Acl snapshot of the same private directory recorded in primitives results: explicit owner/SYSTEM/administrator rights and inherited metadata permissions. |
| `tcp_harness_probe.py.txt`, `tcp-harness-results.json` | A copied full harness with peer/readiness/receive adaptation completes token/scene verification, tree/get/set/read-back and 16 monitor entries through loopback TCP. A 400 ms partial-body delay still allows 25 scene ticks. |

These are isolated feasibility results, not product CLI/daemon e2e. Native URI
parsing does not prove a mounted-share run. Controlled Job children do not prove
the real daemon/Godot/console-wrapper topology or parent-host detachment. Rendered
desktop behavior, native export and complete Live acceptance remain unverified
by these probes. The TCP prototype does not implement authenticated CLI discovery
or daemon lifecycle.

The probe scripts and result files named above are not in the repository; they
stay in the workspace that produced them. A repeated probe records its new
revision, environment and result separately.
