"""The service worker as it is handed to the phone.

The file in ``static`` stays a plain, readable script; everything the app
knows about caching is put in front of it as one generated settings line.
"""

from __future__ import annotations

import json
from pathlib import Path

from invoicing.constant import (
    CACHE_CLEAR_PAGES_MESSAGE,
    CACHE_NETWORK_TIMEOUT_MILLISECONDS,
    CACHE_NEVER_PATH_PREFIXES,
    CACHE_NEVER_PATH_SUFFIXES,
    CACHE_OFFLINE_FALLBACK_TEXT,
    CACHE_PAGE_LIMIT,
    CACHE_PAGES_NAME_PATTERN,
    CACHE_PLAIN_PRELOADED_PATHS,
    CACHE_STATIC_NAME_PATTERN,
    CACHE_STATIC_PATH_PREFIXES,
    CACHE_VERSIONED_PATH_PATTERN,
    CACHE_VERSIONED_STATIC_PATHS,
    OFFLINE_PATH,
    SERVICE_WORKER_FILE_NAME,
    SERVICE_WORKER_SETTINGS_LINE,
    SIGN_IN_PATH,
    WEB_STATIC_DIRECTORY,
)
from invoicing.web.cache_deny_list import CacheDenyList
from invoicing.web.static_version import StaticFolderVersion


class ServiceWorkerScript:
    """Builds the script the browser registers under ``/sw.js``."""

    def __init__(self, static_folder: Path = WEB_STATIC_DIRECTORY) -> None:
        self._static_folder = static_folder
        self._version = StaticFolderVersion(static_folder).number()

    def body(self) -> str:
        """The generated settings line followed by the readable script."""
        script = (self._static_folder / SERVICE_WORKER_FILE_NAME).read_text(
            encoding="utf-8"
        )
        return SERVICE_WORKER_SETTINGS_LINE.format(settings=self._settings()) + script

    def deny_list(self) -> CacheDenyList:
        """The same deny list the generated settings hand to the worker."""
        return CacheDenyList()

    def preloaded_addresses(self) -> list[str]:
        """Everything the worker stores while it installs."""
        versioned = [
            CACHE_VERSIONED_PATH_PATTERN.format(path=path, version=self._version)
            for path in CACHE_VERSIONED_STATIC_PATHS
        ]
        return list(CACHE_PLAIN_PRELOADED_PATHS) + versioned

    def _settings(self) -> str:
        return json.dumps(
            {
                "statik": CACHE_STATIC_NAME_PATTERN.format(version=self._version),
                "seiten": CACHE_PAGES_NAME_PATTERN.format(version=self._version),
                "vorladen": self.preloaded_addresses(),
                "statikPfade": list(CACHE_STATIC_PATH_PREFIXES),
                "niemalsPfade": list(CACHE_NEVER_PATH_PREFIXES),
                "niemalsEndungen": list(CACHE_NEVER_PATH_SUFFIXES),
                "anmeldePfad": SIGN_IN_PATH,
                "offlineSeite": OFFLINE_PATH,
                "offlineText": CACHE_OFFLINE_FALLBACK_TEXT,
                "seitenGrenze": CACHE_PAGE_LIMIT,
                "netzZeitLimitMs": CACHE_NETWORK_TIMEOUT_MILLISECONDS,
                "leerenBotschaft": CACHE_CLEAR_PAGES_MESSAGE,
            }
        )
