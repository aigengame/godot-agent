"""The host selection of the daemon platform seam (#1189).

:func:`host_platform` imports both adapters, and the adapters import
:mod:`gda.daemon.platform` and :mod:`gda.daemon.discovery`. So the selection is
a module of its own: in either of those modules it would make an import cycle
(ADR-0045 §3).
"""

from __future__ import annotations

import sys

from gda.daemon.platform import DaemonPlatform


def host_platform() -> DaemonPlatform:
    """The adapter for this host: Windows on a Windows host, Unix elsewhere.

    The one ``sys.platform`` read that chooses a daemon implementation. Each
    process calls it where it builds a server, a client, a session launch or a
    lifecycle operation, and passes the result on.
    """
    if sys.platform == "win32":
        from gda.daemon.windows import WindowsPlatform

        return WindowsPlatform()
    from gda.daemon.unix import UnixPlatform

    return UnixPlatform()
