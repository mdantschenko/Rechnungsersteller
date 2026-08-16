"""Who may use the web interface.

The tunnel that makes the application reachable from a phone also makes it
reachable from everywhere else, and customer addresses sit behind it. One
password therefore guards every page except the login form itself.

The hash and the cookie signing key live in the database, so the password can
be changed from the application and never reaches the repository. Changing it
takes a code from the mailbox first: whoever holds an open session must still
prove they hold the mailbox before they can lock the owner out.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlmodel import Session, select

from invoicing.constant import (
    PASSWORD_CODE_DIGITS,
    PASSWORD_CODE_MINUTES,
    SESSION_SECRET_BYTES,
)
from invoicing.storage.models import AppSettings

_hasher = PasswordHasher()


def set_password(session: Session, password: str) -> None:
    """Set or replace the password, keeping any existing signing key."""
    access = _row(session)
    if access is None:
        session.add(
            AppSettings(
                password_hash=_hasher.hash(password),
                session_secret=secrets.token_urlsafe(SESSION_SECRET_BYTES),
            )
        )
        return
    access.password_hash = _hasher.hash(password)
    session.add(access)


def request_password_change(session: Session, password: str) -> str:
    """Park the new password and hand back the code that will confirm it.

    Raises:
        ValueError: if no password is set yet; the first one is set directly.
    """
    access = _row(session)
    if access is None:
        raise ValueError("no password set yet")
    access.pending_password_hash = _hasher.hash(password)
    access.pending_password_code = (
        f"{secrets.randbelow(10**PASSWORD_CODE_DIGITS):0{PASSWORD_CODE_DIGITS}d}"
    )
    access.pending_password_until = datetime.now() + timedelta(
        minutes=PASSWORD_CODE_MINUTES
    )
    session.add(access)
    return access.pending_password_code


def confirm_password_change(session: Session, code: str) -> bool:
    """Make the parked password the real one, if the code is right and fresh."""
    access = _row(session)
    if (
        access is None
        or not access.pending_password_hash
        or not access.pending_password_code
        or access.pending_password_until is None
        or datetime.now() > access.pending_password_until
    ):
        return False
    if not secrets.compare_digest(access.pending_password_code, code.strip()):
        return False
    access.password_hash = access.pending_password_hash
    _clear_pending(session, access)
    return True


def cancel_password_change(session: Session) -> None:
    access = _row(session)
    if access is not None:
        _clear_pending(session, access)


def has_pending_password(session: Session) -> bool:
    access = _row(session)
    return bool(
        access
        and access.pending_password_hash
        and access.pending_password_until
        and datetime.now() <= access.pending_password_until
    )


def _clear_pending(session: Session, access: AppSettings) -> None:
    access.pending_password_hash = None
    access.pending_password_code = None
    access.pending_password_until = None
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
