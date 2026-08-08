"""Sending an invoice PDF by email, straight over SMTP.

No mail service SDK and no queue: one message with one attachment to one
recipient at a time, which is exactly the shape of this application's traffic.
The SMTP account comes from the settings row, so it is entered once on the
settings screen and never reaches the repository.
"""

from __future__ import annotations

import imaplib
import smtplib
import ssl
import time
from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from invoicing.storage.models import AppSettings

SSL_PORT = 465
IMAP_PORT = 993
TIMEOUT_SECONDS = 30
SENT_FOLDER_CANDIDATES = ("Sent", "Sent Items", "Gesendete Objekte", "INBOX.Sent")


class MailError(Exception):
    """Sending failed for a reason the user can read and act on."""


def is_configured(settings: AppSettings) -> bool:
    """Whether the settings hold enough to reach an SMTP server."""
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_pdf(
    settings: AppSettings,
    to: str,
    subject: str,
    body: str,
    pdf: Path,
    sender_name: str = "",
) -> None:
    """Send ``pdf`` as an attachment.

    ``sender_name`` is what the recipient's inbox shows instead of the bare
    mailbox name.

    Raises:
        MailError: if the settings are incomplete or the server refuses.
    """
    if not is_configured(settings):
        raise MailError(
            "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
            "Benutzername und Passwort in den Einstellungen ein."
        )
    try:
        message = build_message(
            sender=from_header(
                sender_name, settings.smtp_from or settings.smtp_user or ""
            ),
            to=to,
            subject=subject,
            body=body,
            pdf_content=pdf.read_bytes(),
            file_name=pdf.name,
        )
    except ValueError as error:
        # The email policy refuses header values with line breaks in them,
        # which is also what keeps injected extra headers out.
        raise MailError("Die Empfängeradresse enthält unzulässige Zeichen.") from error
    _deliver(settings, message)
    _copy_into_sent(settings, message)


def send_text(
    settings: AppSettings, to: str, subject: str, body: str, sender_name: str = ""
) -> None:
    """Send a short plain-text message to the account's own mailbox.

    Used for the password confirmation code. No attachment and no copy into
    the Sent folder: the mail is the notification itself.

    Raises:
        MailError: if the settings are incomplete or the server refuses.
    """
    if not is_configured(settings):
        raise MailError(
            "Der E-Mail-Versand ist noch nicht eingerichtet. Trage Server, "
            "Benutzername und Passwort in den Einstellungen ein."
        )
    message = EmailMessage()
    try:
        message["From"] = from_header(
            sender_name, settings.smtp_from or settings.smtp_user or ""
        )
        message["To"] = to
        message["Subject"] = subject
    except ValueError as error:
        raise MailError("Die Empfängeradresse enthält unzulässige Zeichen.") from error
    message.set_content(body)
    _deliver(settings, message)


def from_header(name: str, address: str) -> str:
    """The From value: "Michael Dantschenko <info@...>", or just the address."""
    return formataddr((name, address)) if name else address


def build_message(
    sender: str, to: str, subject: str, body: str, pdf_content: bytes, file_name: str
) -> EmailMessage:
    """One plain-text message with the PDF attached."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        pdf_content, maintype="application", subtype="pdf", filename=file_name
    )
    return message


def _deliver(settings: AppSettings, message: EmailMessage) -> None:
    try:
        with _verified_connection(settings) as server:
            server.login(settings.smtp_user or "", settings.smtp_password or "")
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as error:
        raise MailError(
            "Der Server hat Benutzername oder Passwort abgelehnt. Für Gmail "
            "braucht es ein App-Passwort, nicht das Kontopasswort."
        ) from error
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"Senden fehlgeschlagen: {error}") from error


def _verified_connection(settings: AppSettings) -> smtplib.SMTP:
    """A ready connection that has checked the server's certificate.

    smtplib alone would accept any certificate; the default context is what
    actually checks it against the system store and the host name.
    """
    tls = ssl.create_default_context()
    host = settings.smtp_host or ""
    if settings.smtp_port == SSL_PORT:
        return smtplib.SMTP_SSL(
            host, settings.smtp_port, timeout=TIMEOUT_SECONDS, context=tls
        )
    server = smtplib.SMTP(host, settings.smtp_port, timeout=TIMEOUT_SECONDS)
    server.starttls(context=tls)
    return server


def _copy_into_sent(settings: AppSettings, message: EmailMessage) -> None:
    """File a copy in the mailbox's own Sent folder, best effort.

    Plain SMTP delivers but leaves no trace in the account; the copy is what
    makes the mail show up under "Gesendet". A failure here must never undo
    a delivery that already happened, so it stays silent.
    """
    host = (settings.smtp_host or "").replace("smtp.", "imap.", 1)
    try:
        with imaplib.IMAP4_SSL(host, IMAP_PORT, timeout=TIMEOUT_SECONDS) as archive:
            archive.login(settings.smtp_user or "", settings.smtp_password or "")
            answer, listing = archive.list()
            folder = pick_sent_folder(listing if answer == "OK" else [])
            archive.append(
                folder,
                "\\Seen",
                imaplib.Time2Internaldate(time.time()),
                message.as_bytes(),
            )
    except (imaplib.IMAP4.error, OSError, ValueError):
        pass


def pick_sent_folder(listing: Sequence[object]) -> str:
    """The mailbox folder flagged \\Sent, or the most common name."""
    names = []
    for line in listing:
        if not isinstance(line, bytes):
            continue
        text = line.decode("utf-8", "replace")
        name = _folder_name(text)
        names.append(name)
        if "\\Sent" in text:
            return f'"{name}"'
    for candidate in SENT_FOLDER_CANDIDATES:
        if candidate in names:
            return f'"{candidate}"'
    return "Sent"


def _folder_name(line: str) -> str:
    """The folder at the end of a LIST line; names may carry spaces."""
    if '"' in line:
        return line.split('"')[-2]
    return line.rsplit(" ", 1)[-1]
