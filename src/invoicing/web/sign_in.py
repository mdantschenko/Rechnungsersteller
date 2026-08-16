"""Signing in and out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session
from starlette.responses import RedirectResponse, Response

from invoicing.constant import CLEAR_SITE_DATA_ON_SIGN_OUT, SIGNED_IN_SESSION_KEY
from invoicing.web.dependencies import database_session
from invoicing.web.password_gate import PasswordGate
from invoicing.web.template_renderer import template_renderer

router = APIRouter()


@router.get("/anmelden")
def sign_in_form(request: Request) -> Response:
    return template_renderer.render(request, "sign_in.html", {"failed": False})


@router.post("/anmelden")
def sign_in(
    request: Request,
    password: str = Form(...),
    session: Session = Depends(database_session),
) -> Response:
    if not PasswordGate(session).matches(password):
        return template_renderer.render(
            request, "sign_in.html", {"failed": True}, status_code=401
        )
    request.session[SIGNED_IN_SESSION_KEY] = True
    return RedirectResponse("/", status_code=303)


@router.post("/abmelden")
def sign_out(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse(
        "/anmelden",
        status_code=303,
        headers={"Clear-Site-Data": CLEAR_SITE_DATA_ON_SIGN_OUT},
    )
