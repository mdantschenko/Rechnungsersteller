"""Signing in and out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session
from starlette.responses import RedirectResponse, Response

from invoicing.constant import SIGNED_IN_SESSION_KEY
from invoicing.web.page import database, templates
from invoicing.web.security import password_matches

router = APIRouter()


@router.get("/anmelden")
def sign_in_form(request: Request) -> Response:
    return templates.TemplateResponse(request, "sign_in.html", {"failed": False})


@router.post("/anmelden")
def sign_in(
    request: Request,
    password: str = Form(...),
    session: Session = Depends(database),
) -> Response:
    if not password_matches(session, password):
        return templates.TemplateResponse(
            request, "sign_in.html", {"failed": True}, status_code=401
        )
    request.session[SIGNED_IN_SESSION_KEY] = True
    return RedirectResponse("/", status_code=303)


@router.post("/abmelden")
def sign_out(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/anmelden", status_code=303)
