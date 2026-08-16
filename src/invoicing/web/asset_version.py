"""One fingerprint for every version of the files a browser downloads.

Templates append it to their ``?v=`` links and the service worker builds its
cache name from it, so both always talk about exactly the same files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from invoicing.constant import ASSET_VERSION_FOLDERS, ASSET_VERSION_HEX_LENGTH


class AssetVersion:
    """A hash over the contents of the static files and the templates."""

    def __init__(self, folders: tuple[Path, ...] = ASSET_VERSION_FOLDERS) -> None:
        self._folders = folders

    def fingerprint(self) -> str:
        """The leading hex characters of one sha256 over all file contents."""
        digest = hashlib.sha256()
        for file in self._files_in_a_fixed_order():
            digest.update(file.read_bytes())
        return digest.hexdigest()[:ASSET_VERSION_HEX_LENGTH]

    def _files_in_a_fixed_order(self) -> list[Path]:
        ordered: list[Path] = []
        for folder in self._folders:
            found = [entry for entry in folder.rglob("*") if entry.is_file()]
            ordered.extend(sorted(found, key=lambda entry: entry.as_posix()))
        return ordered


ASSET_VERSION = AssetVersion().fingerprint()
"""Read once at import, so the pages and the worker share one number."""
