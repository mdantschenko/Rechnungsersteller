"""What the phone keeps when the connection is gone: the shell, nothing else."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from invoicing.constant import (
    CACHE_SHELL_NAME_PATTERN,
    CLEAR_SITE_DATA_ON_SIGN_OUT,
    NO_STORE_CACHE_CONTROL,
    OFFLINE_PATH,
    OFFLINE_UNSAVED_PATH,
    SERVICE_WORKER_CACHE_CONTROL,
    SERVICE_WORKER_PATH,
    SIGN_IN_EXEMPT_PATHS,
    WEB_STATIC_DIRECTORY,
    WEB_TEMPLATES_DIRECTORY,
)
from invoicing.web import create_app
from invoicing.web.asset_version import ASSET_VERSION, AssetVersion
from invoicing.web.cache_allow_list import CacheAllowList
from invoicing.web.service_worker_script import ServiceWorkerScript

SHELL_ROUTES_THAT_MAY_BE_STORED = ("/manifest.webmanifest", OFFLINE_PATH)
STATIC_LINK_PATTERN = re.compile(r"/static/[\w.-]+(?:\?v=[0-9a-f]+)?")
SETTINGS_LINE_PATTERN = re.compile(r"^self\.APP_CACHE = (\{.*\});$")
BENCH_SCRIPT = Path(__file__).parent / "service_worker_bench.js"
BENCH_CHECKS = (
    "handlers-are-registered",
    "push-shows-a-notification",
    "a-navigation-without-network-gets-the-offline-page",
    "a-post-without-network-says-nothing-was-saved",
    "a-good-navigation-is-not-stored",
    "a-missing-required-file-fails-the-install",
    "a-missing-icon-does-not-fail-the-install",
    "the-stylesheet-is-stored",
)


@pytest.fixture
def asset_copy(tmp_path: Path) -> tuple[Path, ...]:
    """A private copy of the two folders the version is built from."""
    static_folder = tmp_path / "static"
    templates_folder = tmp_path / "templates"
    shutil.copytree(WEB_STATIC_DIRECTORY, static_folder)
    shutil.copytree(WEB_TEMPLATES_DIRECTORY, templates_folder)
    return (static_folder, templates_folder)


@pytest.fixture
def delivered_worker(stranger: TestClient, tmp_path: Path) -> Path:
    """The script exactly as the phone receives it, written to a file."""
    script = tmp_path / "sw.js"
    script.write_text(stranger.get(SERVICE_WORKER_PATH).text, encoding="utf-8")
    return script


@pytest.mark.parametrize("check", BENCH_CHECKS)
def test_the_delivered_worker_behaves(delivered_worker: Path, check: str) -> None:
    finished = subprocess.run(
        [_node(), str(BENCH_SCRIPT), str(delivered_worker), check],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert finished.returncode == 0, finished.stdout + finished.stderr


def test_the_service_worker_answers_without_signing_in(stranger: TestClient) -> None:
    answer = stranger.get(SERVICE_WORKER_PATH)

    assert answer.status_code == 200
    assert "showNotification" in answer.text
    assert answer.headers["cache-control"] == SERVICE_WORKER_CACHE_CONTROL
    assert answer.headers["content-type"].startswith("text/javascript")


def test_the_settings_line_is_valid_json(stranger: TestClient) -> None:
    first_line = stranger.get(SERVICE_WORKER_PATH).text.splitlines()[0]
    match = SETTINGS_LINE_PATTERN.match(first_line)

    assert match
    settings = json.loads(match.group(1))
    assert settings["offlineSeite"] == OFFLINE_PATH
    assert settings["offlineOhneSpeichern"] == OFFLINE_UNSAVED_PATH


def test_only_the_shell_may_be_stored(location: Path) -> None:
    allow_list = CacheAllowList()

    for path in _get_paths(create_app(location)):
        may_be_stored = path in SHELL_ROUTES_THAT_MAY_BE_STORED
        assert allow_list.allows(path) == may_be_stored, path


def test_the_static_files_may_be_stored() -> None:
    allow_list = CacheAllowList()

    assert allow_list.allows("/static/app.css")
    assert allow_list.allows("/static/icon-180.png")
    assert not allow_list.allows("/rechnungen/115.pdf")


def test_every_static_link_of_a_page_is_preloaded(
    stranger: TestClient, client: TestClient
) -> None:
    script = ServiceWorkerScript()
    preloaded = script.required_addresses() + script.optional_addresses()

    for page in (client.get("/").text, stranger.get("/anmelden").text):
        for link in STATIC_LINK_PATTERN.findall(page):
            assert link in preloaded, link


def test_the_offline_page_says_that_nothing_is_stored(stranger: TestClient) -> None:
    page = stranger.get(OFFLINE_PATH)

    assert page.status_code == 200
    assert "Kein Netz" in page.text
    assert "Auf dem Handy ist nichts gespeichert" in page.text
    assert "app-tabs" not in page.text
    assert "nicht abgeschickt" not in page.text


def test_a_lost_form_is_named_on_the_offline_page(stranger: TestClient) -> None:
    assert "nicht abgeschickt" in stranger.get(OFFLINE_UNSAVED_PATH).text


def test_the_offline_page_is_exempt_from_the_password() -> None:
    assert OFFLINE_PATH in SIGN_IN_EXEMPT_PATHS


def test_every_page_registers_the_worker(client: TestClient) -> None:
    assert 'navigator.serviceWorker.register("/sw.js")' in client.get("/").text


def test_a_signed_in_answer_must_not_be_kept_by_the_browser(
    client: TestClient,
) -> None:
    for path in ("/", "/kunden", "/rechnungen", "/einstellungen"):
        assert client.get(path).headers["cache-control"] == NO_STORE_CACHE_CONTROL, path


def test_the_shell_stays_storable_for_the_browser(stranger: TestClient) -> None:
    for path in ("/static/app.css", "/manifest.webmanifest", OFFLINE_PATH):
        stored = stranger.get(path).headers.get("cache-control", "")
        assert "no-store" not in stored, path


def test_signing_out_tells_the_browser_to_throw_everything_away(
    client: TestClient,
) -> None:
    answer = client.post("/abmelden", follow_redirects=False)

    assert answer.headers["clear-site-data"] == CLEAR_SITE_DATA_ON_SIGN_OUT


def test_the_version_is_twelve_hex_characters() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", ASSET_VERSION)


def test_the_pages_and_the_worker_name_the_same_version(
    client: TestClient, stranger: TestClient
) -> None:
    assert f"/static/app.css?v={ASSET_VERSION}" in client.get("/").text
    assert (
        CACHE_SHELL_NAME_PATTERN.format(version=ASSET_VERSION)
        in stranger.get(SERVICE_WORKER_PATH).text
    )


def test_a_copied_change_time_alone_does_not_move_the_version(
    asset_copy: tuple[Path, ...],
) -> None:
    before = AssetVersion(asset_copy).fingerprint()
    tomorrow = time.time() + 86400
    os.utime(asset_copy[0] / "app.css", (tomorrow, tomorrow))

    assert AssetVersion(asset_copy).fingerprint() == before


def test_a_changed_static_file_moves_the_version(
    asset_copy: tuple[Path, ...],
) -> None:
    before = AssetVersion(asset_copy).fingerprint()
    (asset_copy[0] / "app.css").write_text("body { color: red }", encoding="utf-8")

    assert AssetVersion(asset_copy).fingerprint() != before


def test_a_changed_template_moves_the_version(asset_copy: tuple[Path, ...]) -> None:
    before = AssetVersion(asset_copy).fingerprint()
    (asset_copy[1] / "layout.html").write_text("<html></html>", encoding="utf-8")

    assert AssetVersion(asset_copy).fingerprint() != before


def test_a_file_in_a_subfolder_counts(asset_copy: tuple[Path, ...]) -> None:
    before = AssetVersion(asset_copy).fingerprint()
    nested = asset_copy[0] / "schriften"
    nested.mkdir()
    (nested / "neu.css").write_text("body { color: blue }", encoding="utf-8")

    assert AssetVersion(asset_copy).fingerprint() != before


def _node() -> str:
    node = shutil.which("node")
    assert node, "node is needed to run the service worker test bench"
    return node


def _get_paths(app: FastAPI) -> list[str]:
    return [
        str(getattr(route, "path", ""))
        for route in app.routes
        if "GET" in (getattr(route, "methods", None) or set())
    ]
