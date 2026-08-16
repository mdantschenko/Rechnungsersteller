"""The sender survives dead subscriptions and flaky networks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from pywebpush import WebPushException
from sqlalchemy import Engine
from sqlmodel import Session, select

from invoicing.push import WebPushSender
from invoicing.storage.models import AppSettings, PushSubscription

FLAKY_DEVICE = "https://push.example.com/wackliges-geraet"
STEADY_DEVICE = "https://push.example.com/stabiles-geraet"


@pytest.fixture
def session(engine: Engine):
    with Session(engine) as inside:
        yield inside


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(password_hash="egal", session_secret="egal")


def _subscribed(session: Session, endpoint: str) -> None:
    session.add(PushSubscription(endpoint=endpoint, p256dh="schloss", auth="geheim"))
    session.flush()


def test_a_key_mismatch_drops_the_subscription(
    session: Session, settings: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subscribed(session, STEADY_DEVICE)

    def refuse(**_: Any) -> None:
        raise WebPushException("forbidden", response=SimpleNamespace(status_code=403))

    monkeypatch.setattr("invoicing.push.webpush", refuse)

    assert WebPushSender(session, settings).send_to_all({"title": "Test"}) == 0
    assert session.exec(select(PushSubscription)).all() == []


def test_a_network_error_does_not_silence_the_other_devices(
    session: Session, settings: AppSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _subscribed(session, FLAKY_DEVICE)
    _subscribed(session, STEADY_DEVICE)
    reached: list[str] = []

    def flaky(*, subscription_info: dict[str, Any], **_: Any) -> None:
        if subscription_info["endpoint"] == FLAKY_DEVICE:
            raise requests.ConnectionError("Leitung tot")
        reached.append(subscription_info["endpoint"])

    monkeypatch.setattr("invoicing.push.webpush", flaky)

    assert WebPushSender(session, settings).send_to_all({"title": "Test"}) == 1
    assert reached == [STEADY_DEVICE]
    assert len(session.exec(select(PushSubscription)).all()) == 2
