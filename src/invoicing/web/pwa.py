"""What iOS needs to treat the site as an app: manifest, icons and the wake-up
service worker with its push subscription endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import FileResponse, JSONResponse, Response

from invoicing.constant import PWA_MANIFEST, WEB_STATIC_DIRECTORY
from invoicing.push import WebPushSender
from invoicing.utils import notice_redirect
from invoicing.web.page import database
from invoicing.web.store_queries import StoreQueries

router = APIRouter()


@router.get("/manifest.webmanifest")
def manifest() -> Response:
    return JSONResponse(PWA_MANIFEST, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker() -> Response:
    return FileResponse(WEB_STATIC_DIRECTORY / "sw.js", media_type="text/javascript")


class Subscription(BaseModel):
    endpoint: str
    keys: dict[str, str]


@router.get("/push/schluessel")
def subscription_key(session: Session = Depends(database)) -> Response:
    key = WebPushSender(
        session, StoreQueries(session).app_settings()
    ).application_server_key()
    return JSONResponse({"key": key})


@router.post("/push/abo", status_code=204)
def store_subscription(
    subscription: Subscription, session: Session = Depends(database)
) -> None:
    WebPushSender(session, StoreQueries(session).app_settings()).subscribe(
        endpoint=subscription.endpoint,
        p256dh=subscription.keys.get("p256dh", ""),
        auth=subscription.keys.get("auth", ""),
    )


@router.post("/push/abmelden", status_code=204)
def drop_subscription(
    subscription: Subscription, session: Session = Depends(database)
) -> None:
    WebPushSender(session, StoreQueries(session).app_settings()).unsubscribe(
        subscription.endpoint
    )


@router.post("/push/test")
def test_ring(request: Request, session: Session = Depends(database)) -> Response:
    delivered = WebPushSender(
        session, StoreQueries(session).app_settings()
    ).send_to_all(
        {"title": "Probeweckruf", "body": "So klingelt der Wecker.", "url": "/"}
    )
    if not delivered:
        return notice_redirect(
            request,
            "/einstellungen",
            "Kein Gerät hat den Weckruf angenommen — erst auf dem Handy aktivieren.",
        )
    return notice_redirect(
        request, "/einstellungen", f"Probeweckruf an {delivered} Gerät(e) geschickt."
    )
