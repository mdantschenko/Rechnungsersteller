"""One number for every copy of a static file.

Templates append it to their ``?v=`` links and the service worker builds its
cache names from it, so both talk about exactly the same files.
"""

from __future__ import annotations

from pathlib import Path

from invoicing.constant import WEB_STATIC_DIRECTORY


class StaticFolderVersion:
    """The newest change time among the static files."""

    def __init__(self, static_folder: Path = WEB_STATIC_DIRECTORY) -> None:
        self._static_folder = static_folder

    def number(self) -> int:
        """The version as a whole number of seconds."""
        return max(
            int(entry.stat().st_mtime) for entry in self._static_folder.iterdir()
        )


STATIC_VERSION = StaticFolderVersion().number()
"""Read once at import; every deploy restarts the server and lifts the number."""
