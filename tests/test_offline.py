"""What the phone keeps when the connection is gone."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoicing.constant import (
    CACHE_CLEAR_PAGES_MESSAGE,
    CACHE_PAGES_NAME_PATTERN,
    CACHE_STATIC_NAME_PATTERN,
    OFFLINE_PATH,
    SIGN_IN_EXEMPT_PATHS,
    WEB_STATIC_DIRECTORY,
)
from invoicing.web import create_app
from invoicing.web.cache_deny_list import CacheDenyList
from invoicing.web.service_worker_script import ServiceWorkerScript
from invoicing.web.static_version import STATIC_VERSION, StaticFolderVersion

SENSITIVE_PATH_MARKS = (".pdf", ".zip", ".csv", ".png")
SENSITIVE_PATH_STARTS = (
    "/push/",
    "/anmelden",
    "/einstellungen",
    "/rechnungen/vorschau",
)
STATIC_LINK_PATTERN = re.compile(r"/static/[\w.-]+(?:\?v=\d+)?")
SETTINGS_LINE_PATTERN = re.compile(r"^self\.APP_CACHE = (\{.*\});$")


@pytest.fixture
def static_copy(tmp_path: Path) -> Path:
    folder = tmp_path / "static"
    shutil.copytree(WEB_STATIC_DIRECTORY, folder)
    return folder


def test_the_service_worker_answers_without_signing_in(stranger: TestClient) -> None:
    answer = stranger.get("/sw.js")

    assert answer.status_code == 200
    assert "showNotification" in answer.text
    assert answer.headers["cache-control"] == "no-cache"
    assert answer.headers["content-type"].startswith("text/javascript")


def test_the_service_worker_carries_the_static_version(stranger: TestClient) -> None:
    script = stranger.get("/sw.js").text

    assert CACHE_STATIC_NAME_PATTERN.format(version=STATIC_VERSION) in script
    assert CACHE_PAGES_NAME_PATTERN.format(version=STATIC_VERSION) in script


def test_a_touched_static_file_changes_the_script(static_copy: Path) -> None:
    before = ServiceWorkerScript(static_copy).body()
    later = StaticFolderVersion(static_copy).number() + 60
    os.utime(static_copy / "app.css", (later, later))

    assert ServiceWorkerScript(static_copy).body() != before


def test_no_sensitive_route_may_be_stored(location: Path) -> None:
    deny_list = CacheDenyList()

    for route in create_app(location).routes:
        path = getattr(route, "path", "")
        sensitive = path.endswith(SENSITIVE_PATH_MARKS) or path.startswith(
            SENSITIVE_PATH_STARTS
        )
        assert not sensitive or deny_list.forbids(path), path


def test_the_static_files_may_be_stored() -> None:
    deny_list = CacheDenyList()

    assert not deny_list.forbids("/static/icon-180.png")
    assert not deny_list.forbids("/static/app.css")
    assert not deny_list.forbids("/manifest.webmanifest")


def test_every_static_link_of_a_page_is_preloaded(
    stranger: TestClient, client: TestClient
) -> None:
    preloaded = ServiceWorkerScript().preloaded_addresses()

    for page in (client.get("/").text, stranger.get("/anmelden").text):
        for link in STATIC_LINK_PATTERN.findall(page):
            assert link in preloaded, link


def test_the_offline_page_needs_no_password(stranger: TestClient) -> None:
    answer = stranger.get(OFFLINE_PATH)

    assert answer.status_code == 200
    assert "Kein Netz" in answer.text
    assert "app-tabs" not in answer.text


def test_the_offline_page_is_exempt_from_the_password() -> None:
    assert OFFLINE_PATH in SIGN_IN_EXEMPT_PATHS


def test_the_sign_in_page_asks_the_worker_to_forget_the_pages(
    stranger: TestClient,
) -> None:
    assert CACHE_CLEAR_PAGES_MESSAGE in stranger.get("/anmelden").text
    assert CACHE_CLEAR_PAGES_MESSAGE in stranger.get("/sw.js").text


def test_every_page_registers_the_worker(client: TestClient) -> None:
    assert 'navigator.serviceWorker.register("/sw.js")' in client.get("/").text


def test_the_settings_line_is_valid_json(stranger: TestClient) -> None:
    first_line = stranger.get("/sw.js").text.splitlines()[0]
    match = SETTINGS_LINE_PATTERN.match(first_line)

    assert match
    assert json.loads(match.group(1))["offlineSeite"] == OFFLINE_PATH


def test_the_delivered_script_parses(stranger: TestClient, tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = tmp_path / "sw.js"
    script.write_text(stranger.get("/sw.js").text, encoding="utf-8")

    assert subprocess.run([node, "--check", str(script)], check=False).returncode == 0
