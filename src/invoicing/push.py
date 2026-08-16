"""Web push straight to the subscribed devices.

No notification service in between: the server signs each message with its
own VAPID key and hands it to the browser vendor's push relay, which is the
only road onto a phone's lock screen. The key pair is created once and lives
in the settings row, like everything else the app is configured with.
"""

from __future__ import annotations

import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

from invoicing.constant import PUSH_SUBSCRIPTION_GONE_STATUS_CODES
from invoicing.storage.models import AppSettings, PushSubscription
from invoicing.utils import base64url_without_padding, mailbox_address_of


def application_server_key(session: Session, settings: AppSettings) -> str:
    """The public key a device subscribes with, creating the pair if needed."""
    if not settings.vapid_public_key or not settings.vapid_private_key:
        private = ec.generate_private_key(ec.SECP256R1())
        settings.vapid_private_key = base64url_without_padding(
            private.private_numbers().private_value.to_bytes(32, "big")
        )
        settings.vapid_public_key = base64url_without_padding(
            private.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        )
        session.add(settings)
    return settings.vapid_public_key


def subscribe(session: Session, endpoint: str, p256dh: str, auth: str) -> None:
    stored = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first() or PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
    stored.p256dh = p256dh
    stored.auth = auth
    session.add(stored)


def unsubscribe(session: Session, endpoint: str) -> None:
    stored = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    if stored is not None:
        session.delete(stored)


def send_to_all(
    session: Session, settings: AppSettings, message: dict[str, str]
) -> int:
    """Deliver ``message`` to every subscribed device.

    A device that answers "gone" has revoked its subscription and is dropped;
    any other failure leaves the subscription alone and moves on, because one
    unreachable phone must not silence the others.
    """
    application_server_key(session, settings)
    delivered = 0
    for subscription in session.exec(select(PushSubscription)).all():
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(message),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": _contact(settings)},
                headers={"Urgency": "high"},
            )
            delivered += 1
        except WebPushException as error:
            if (
                error.response is not None
                and error.response.status_code in PUSH_SUBSCRIPTION_GONE_STATUS_CODES
            ):
                session.delete(subscription)
    return delivered


def _contact(settings: AppSettings) -> str:
    address = mailbox_address_of(settings) or "wecker@example.invalid"
    return f"mailto:{address}"
