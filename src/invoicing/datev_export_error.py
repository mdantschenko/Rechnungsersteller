"""The one error the DATEV export raises towards the web pages."""


class DatevExportError(Exception):
    """The booking batch would not be importable; the reason is readable."""
