"""The service worker as it is handed to the phone.

The file in ``static`` stays a plain, readable script; everything the app
knows about caching is put in front of it as one generated settings line.
"""

from __future__ import annotations

import json
from pathlib import Path

from invoicing.constant import (
    CACHE_ALLOWED_PATH_PREFIXES,
    CACHE_OFFLINE_FALLBACK_TEXT,
    CACHE_OPTIONAL_PLAIN_PATHS,
    CACHE_OPTIONAL_VERSIONED_PATHS,
    CACHE_REQUIRED_PLAIN_PATHS,
    CACHE_REQUIRED_VERSIONED_PATHS,
    CACHE_SHELL_NAME_PATTERN,
    CACHE_VERSIONED_PATH_PATTERN,
    OFFLINE_PATH,
    OFFLINE_UNSAVED_PATH,
    SERVICE_WORKER_FILE_NAME,
    SERVICE_WORKER_SETTINGS_LINE,
    WEB_STATIC_DIRECTORY,
)
from invoicing.web.asset_version import ASSET_VERSION


class ServiceWorkerScript:
    """Builds the script the browser registers under ``/sw.js``."""

    def __init__(self, static_folder: Path = WEB_STATIC_DIRECTORY) -> None:
        self._static_folder = static_folder

    def body(self) -> str:
        """The generated settings line followed by the readable script."""
        script = (self._static_folder / SERVICE_WORKER_FILE_NAME).read_text(
            encoding="utf-8"
        )
        return SERVICE_WORKER_SETTINGS_LINE.format(settings=self._settings()) + script

    def required_addresses(self) -> list[str]:
        """What has to be stored, or the worker does not take over at all."""
        return list(CACHE_REQUIRED_PLAIN_PATHS) + self._versioned(
            CACHE_REQUIRED_VERSIONED_PATHS
        )

    def optional_addresses(self) -> list[str]:
        """The rest of the shell; each of these may fail on its own."""
        return list(CACHE_OPTIONAL_PLAIN_PATHS) + self._versioned(
            CACHE_OPTIONAL_VERSIONED_PATHS
        )

    def _versioned(self, paths: tuple[str, ...]) -> list[str]:
        return [
            CACHE_VERSIONED_PATH_PATTERN.format(path=path, version=ASSET_VERSION)
            for path in paths
        ]

    def _settings(self) -> str:
        return json.dumps(
            {
                "geruest": CACHE_SHELL_NAME_PATTERN.format(version=ASSET_VERSION),
                "pflichtVorladen": self.required_addresses(),
                "zusatzVorladen": self.optional_addresses(),
                "erlaubtePfade": list(CACHE_ALLOWED_PATH_PREFIXES),
                "offlineSeite": OFFLINE_PATH,
                "offlineOhneSpeichern": OFFLINE_UNSAVED_PATH,
                "offlineText": CACHE_OFFLINE_FALLBACK_TEXT,
            }
        )
