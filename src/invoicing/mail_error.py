"""The one error the mail layer raises towards the web pages."""


class MailError(Exception):
    """Sending failed for a reason the user can read and act on."""
