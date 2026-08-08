"""Who may use the web interface.

The tunnel that makes the application reachable from a phone also makes it
reachable from everywhere else, and customer addresses sit behind it. One
password therefore guards every page except the login form itself.

The hash and the cookie signing key live in the database, so the password can
be changed from the application and never reaches the repository.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlmodel import Session, select

from invoicing.storage.models import AppSettings

SESSION_KEY = "signed_in"
SECRET_BYTES = 32

_hasher = PasswordHasher()


def set_password(session: Session, password: str) -> None:
    """Set or replace the password, keeping any existing signing key."""
    access = _row(session)
    if access is None:
        session.add(
            AppSettings(
                password_hash=_hasher.hash(password),
                session_secret=secrets.token_urlsafe(SECRET_BYTES),
            )
        )
        return
    access.password_hash = _hasher.hash(password)
    session.add(access)


def password_matches(session: Session, password: str) -> bool:
    """Whether the given password opens the interface."""
    access = _row(session)
    if access is None:
        return False
    try:
        return _hasher.verify(access.password_hash, password)
    except VerifyMismatchError:
        return False


def signing_key(session: Session) -> str:
    """The key session cookies are signed with.

    Raises:
        ValueError: if no password has been set yet, because there would be
            nothing to protect and no key to sign with.
    """
    access = _row(session)
    if access is None:
        raise ValueError("no password set yet; run 'main.py set-password' first")
    return access.session_secret


def is_configured(session: Session) -> bool:
    return _row(session) is not None


def _row(session: Session) -> AppSettings | None:
    return session.exec(select(AppSettings)).first()
