"""Which paths the phone is allowed to keep a copy of.

The one place that decides it. Everything that is not named here stays on the
server: Python asks this list in the tests, the service worker gets the very
same prefixes handed over as data.
"""

from __future__ import annotations

from invoicing.constant import CACHE_ALLOWED_PATH_PREFIXES


class CacheAllowList:
    """Answers whether a path may be stored on the device."""

    def allows(self, path: str) -> bool:
        """Whether the answer for ``path`` may be kept for the offline shell."""
        return path.startswith(CACHE_ALLOWED_PATH_PREFIXES)
