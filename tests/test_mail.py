from __future__ import annotations

from pathlib import Path

import pytest

from invoicing.mail import SmtpMailer
from invoicing.mail_error import MailError
from invoicing.storage.models import AppSettings


def _mailer(**overrides: object) -> SmtpMailer:
    values: dict[str, object] = {"password_hash": "x", "session_secret": "y"}
    values.update(overrides)
    return SmtpMailer(AppSettings(**values))  # type: ignore[arg-type]


def test_configuration_needs_host_user_and_password() -> None:
    assert not _mailer().is_configured()
    assert not _mailer(smtp_host="smtp.example.com").is_configured()
    assert _mailer(
        smtp_host="smtp.example.com", smtp_user="u", smtp_password="p"
    ).is_configured()


def test_sending_unconfigured_names_the_problem(tmp_path: Path) -> None:
    pdf = tmp_path / "Rechnung.pdf"
    pdf.write_bytes(b"%PDF-")

    with pytest.raises(MailError, match="nicht eingerichtet"):
        _mailer().send_pdf("wer@example.com", "Rechnung", "Hallo", pdf)


def test_a_line_break_in_the_address_cannot_inject_headers(tmp_path: Path) -> None:
    pdf = tmp_path / "Rechnung.pdf"
    pdf.write_bytes(b"%PDF-")
    configured = _mailer(smtp_host="smtp.example.com", smtp_user="u", smtp_password="p")

    with pytest.raises(MailError, match="unzulässige Zeichen"):
        configured.send_pdf("wer@example.com\r\nBcc: x@y.z", "Rechnung", "Hallo", pdf)


def test_the_sender_carries_a_display_name() -> None:
    assert (
        SmtpMailer.from_header("Michael Dantschenko", "info@example.com")
        == "Michael Dantschenko <info@example.com>"
    )
    assert SmtpMailer.from_header("", "info@example.com") == "info@example.com"


def test_the_sent_folder_is_recognised_by_its_flag() -> None:
    listing: list[bytes | None] = [
        b'(\\HasNoChildren) "." "INBOX"',
        b'(\\HasNoChildren \\Sent) "." "Gesendete Objekte"',
    ]
    assert SmtpMailer.pick_sent_folder(listing) == '"Gesendete Objekte"'
    assert (
        SmtpMailer.pick_sent_folder([b'(\\HasNoChildren) "." "Sent Items"'])
        == '"Sent Items"'
    )
    assert SmtpMailer.pick_sent_folder([]) == "Sent"


def test_the_message_carries_the_pdf_by_name() -> None:
    message = SmtpMailer.build_message(
        sender="max@example.com",
        to="erika@example.com",
        subject="Rechnung Nr. 115",
        body="Guten Tag",
        content=b"%PDF-",
        file_name="Rechnung Nr 115 Erika Beispiel.pdf",
    )

    attachments = list(message.iter_attachments())
    assert message["From"] == "max@example.com"
    assert message["To"] == "erika@example.com"
    assert message["Subject"] == "Rechnung Nr. 115"
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_filename() == "Rechnung Nr 115 Erika Beispiel.pdf"
