"""What iOS needs to treat the site as an app on the home screen."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import JSONResponse, Response

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
