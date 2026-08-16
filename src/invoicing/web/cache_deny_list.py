"""Which paths must never end up in the offline cache.

The one place that decides it. Python asks it in the tests, the service
worker gets the very same lists handed over as data.
"""

from __future__ import annotations

from invoicing.constant import (
    CACHE_NEVER_PATH_PREFIXES,
    CACHE_NEVER_PATH_SUFFIXES,
    CACHE_STATIC_PATH_PREFIXES,
)


class CacheDenyList:
    """Answers whether a path may be stored on the device."""

    def forbids(self, path: str) -> bool:
        """Whether the answer for ``path`` must always come from the network."""
        if path.startswith(CACHE_STATIC_PATH_PREFIXES):
            return False
        if path.startswith(CACHE_NEVER_PATH_PREFIXES):
            return True
        return path.endswith(CACHE_NEVER_PATH_SUFFIXES)
