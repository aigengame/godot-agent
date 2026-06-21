"""gda-daemon: the per-project supervisor + IPC broker for live operations.

A long-lived, per-project process that holds a transient engine session and
serves live operations over a Unix domain socket (ADR-0017, ADR-0021). This
package is the daemon's own runtime, distinct from the one-shot CLI.
"""
