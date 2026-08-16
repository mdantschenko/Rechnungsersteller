"""What iOS needs to treat the site as an app.

Manifest, icons and the wake-up service worker with its push subscription
endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import JSONResponse, Response

from invoicing.constant import (
    OFFLINE_TEMPLATE_NAME,
    PWA_MANIFEST,
    SERVICE_WORKER_CACHE_CONTROL,
    SERVICE_WORKER_MEDIA_TYPE,
)
from invoicing.push import WebPushSender
from invoicing.utils import notice_redirect
from invoicing.web.dependencies import database_session
from invoicing.web.service_worker_script import ServiceWorkerScript
from invoicing.web.store_queries import StoreQueries
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/manifest.webmanifest")
def manifest() -> Response:
    return JSONResponse(PWA_MANIFEST, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker() -> Response:
    return Response(
        ServiceWorkerScript().body(),
        media_type=SERVICE_WORKER_MEDIA_TYPE,
        headers={"Cache-Control": SERVICE_WORKER_CACHE_CONTROL},
    )


@router.get("/offline")
def offline_page(request: Request) -> Response:
    return template_renderer.render(request, OFFLINE_TEMPLATE_NAME, {})


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: dict[str, str]


@router.get("/push/schluessel")
def subscription_key(session: Session = Depends(database_session)) -> Response:
    key = WebPushSender(
        session, StoreQueries(session).app_settings()
    ).application_server_key()
    return JSONResponse({"key": key})


@router.post("/push/abo", status_code=204)
def store_subscription(
    subscription: PushSubscriptionPayload, session: Session = Depends(database_session)
) -> None:
    WebPushSender(session, StoreQueries(session).app_settings()).subscribe(
        endpoint=subscription.endpoint,
        p256dh=subscription.keys.get("p256dh", ""),
        auth=subscription.keys.get("auth", ""),
    )


@router.post("/push/abmelden", status_code=204)
def drop_subscription(
    subscription: PushSubscriptionPayload, session: Session = Depends(database_session)
) -> None:
    WebPushSender(session, StoreQueries(session).app_settings()).unsubscribe(
        subscription.endpoint
    )


@router.post("/push/test")
def test_ring(
    request: Request, session: Session = Depends(database_session)
) -> Response:
    sender = WebPushSender(session, StoreQueries(session).app_settings())
    subscribed = sender.subscription_count()
    if not subscribed:
        return notice_redirect(
            request,
            "/einstellungen",
            "Auf keinem Gerät aktiviert — aktiviere den Wecker in den Einstellungen.",
        )
    delivered = sender.send_to_all(
        {"title": "Probeweckruf", "body": "So klingelt der Wecker.", "url": "/"}
    )
    failed = subscribed - delivered
    if failed:
        return notice_redirect(
            request,
            "/einstellungen",
            f"Probeweckruf: {failed} von {subscribed} Sendung(en) fehlgeschlagen.",
        )
    return notice_redirect(
        request, "/einstellungen", f"Probeweckruf an {delivered} Gerät(e) geschickt."
    )
