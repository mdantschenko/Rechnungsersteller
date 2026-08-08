"""What iOS needs to treat the site as an app: manifest, icons and the wake-up
service worker with its push subscription endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import FileResponse, JSONResponse, Response

from invoicing import push
from invoicing.web.page import STATIC_FOLDER, database, notice_redirect, settings_of

router = APIRouter()

MANIFEST = {
    "name": "Rechnungsersteller",
    "short_name": "Rechnungen",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#ffffff",
    "lang": "de",
    "icons": [
        {"src": "/static/icon-180.png", "sizes": "180x180", "type": "image/png"},
        {
            "src": "/static/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ],
}


@router.get("/manifest.webmanifest")
def manifest() -> Response:
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker() -> Response:
    return FileResponse(STATIC_FOLDER / "sw.js", media_type="text/javascript")


class Subscription(BaseModel):
    endpoint: str
    keys: dict[str, str]


@router.get("/push/schluessel")
def subscription_key(session: Session = Depends(database)) -> Response:
    key = push.application_server_key(session, settings_of(session))
    return JSONResponse({"key": key})


@router.post("/push/abo", status_code=204)
def store_subscription(
    subscription: Subscription, session: Session = Depends(database)
) -> None:
    push.subscribe(
        session,
        endpoint=subscription.endpoint,
        p256dh=subscription.keys.get("p256dh", ""),
        auth=subscription.keys.get("auth", ""),
    )


@router.post("/push/abmelden", status_code=204)
def drop_subscription(
    subscription: Subscription, session: Session = Depends(database)
) -> None:
    push.unsubscribe(session, subscription.endpoint)


@router.post("/push/test")
def test_ring(request: Request, session: Session = Depends(database)) -> Response:
    delivered = push.send_to_all(
        session,
        settings_of(session),
        {"title": "Probeweckruf", "body": "So klingelt der Wecker.", "url": "/"},
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
