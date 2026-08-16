"""Web push straight to the subscribed devices.

No notification service in between: the server signs each message with its
own VAPID key and hands it to the browser vendor's push relay, which is the
only road onto a phone's lock screen. The key pair is created once and lives
in the settings row, like everything else the app is configured with.
"""

from __future__ import annotations

import json
import logging

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

from invoicing.constant import (
    PUSH_ENDPOINT_LOG_PREFIX_LENGTH,
    PUSH_MESSAGE_TTL_SECONDS,
    PUSH_SEND_TIMEOUT_SECONDS,
    PUSH_SUBSCRIPTION_DEAD_STATUS_CODES,
)
from invoicing.storage.models import AppSettings, PushSubscription
from invoicing.utils import base64url_without_padding, mailbox_address_of


class WebPushSender:
    """Manages the push subscriptions and delivers messages to them."""

    def __init__(self, session: Session, settings: AppSettings) -> None:
        self._session = session
        self._settings = settings

    def application_server_key(self) -> str:
        """The public key a device subscribes with, creating the pair if needed."""
        if not self._settings.vapid_public_key or not self._settings.vapid_private_key:
            private = ec.generate_private_key(ec.SECP256R1())
            self._settings.vapid_private_key = base64url_without_padding(
                private.private_numbers().private_value.to_bytes(32, "big")
            )
            self._settings.vapid_public_key = base64url_without_padding(
                private.public_key().public_bytes(
                    serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint,
                )
            )
            self._session.add(self._settings)
        return self._settings.vapid_public_key

    def subscribe(self, endpoint: str, p256dh: str, auth: str) -> None:
        stored = self._session.exec(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first() or PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
        stored.p256dh = p256dh
        stored.auth = auth
        self._session.add(stored)

    def unsubscribe(self, endpoint: str) -> None:
        stored = self._session.exec(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        if stored is not None:
            self._session.delete(stored)

    def subscription_count(self) -> int:
        """How many devices are currently subscribed."""
        return len(self._session.exec(select(PushSubscription)).all())

    def send_to_all(self, message: dict[str, str]) -> int:
        """Deliver ``message`` to every subscribed device.

        Returns:
            How many devices accepted the message. A device that answers
            forbidden or gone can never be reached with our key and is
            dropped; any other failure is logged and skipped, because one
            unreachable phone must not silence the others.
        """
        self.application_server_key()
        delivered = 0
        for subscription in self._session.exec(select(PushSubscription)).all():
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {
                            "p256dh": subscription.p256dh,
                            "auth": subscription.auth,
                        },
                    },
                    data=json.dumps(message),
                    vapid_private_key=self._settings.vapid_private_key,
                    vapid_claims={"sub": self._contact()},
                    headers={"Urgency": "high"},
                    ttl=PUSH_MESSAGE_TTL_SECONDS,
                    timeout=PUSH_SEND_TIMEOUT_SECONDS,
                )
                delivered += 1
            except WebPushException as error:
                self._drop_if_dead(subscription, error)
            except requests.RequestException as error:
                logging.getLogger(__name__).warning(
                    "Weckruf an %s nicht rausgegangen: %s",
                    self._loggable_endpoint(subscription.endpoint),
                    type(error).__name__,
                )
        return delivered

    def _drop_if_dead(
        self, subscription: PushSubscription, error: WebPushException
    ) -> None:
        status = error.response.status_code if error.response is not None else None
        endpoint = self._loggable_endpoint(subscription.endpoint)
        logger = logging.getLogger(__name__)
        if status in PUSH_SUBSCRIPTION_DEAD_STATUS_CODES:
            self._session.delete(subscription)
            logger.warning(
                "Weckruf an %s abgelehnt (Status %s), Abo gelöscht", endpoint, status
            )
        else:
            logger.warning("Weckruf an %s fehlgeschlagen (Status %s)", endpoint, status)

    @staticmethod
    def _loggable_endpoint(endpoint: str) -> str:
        return endpoint[:PUSH_ENDPOINT_LOG_PREFIX_LENGTH]

    def _contact(self) -> str:
        address = mailbox_address_of(self._settings) or "wecker@example.invalid"
        return f"mailto:{address}"
