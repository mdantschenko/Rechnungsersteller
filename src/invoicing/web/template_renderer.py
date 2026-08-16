"""How the routers turn a template and a context into a page."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from invoicing.constant import WEB_STATIC_DIRECTORY, WEB_TEMPLATES_DIRECTORY
from invoicing.german_formatter import german_formatter
from invoicing.templating import GermanTemplateFilters
from invoicing.utils import recurrence_words


class GermanTemplateRenderer:
    """Renders the web pages with the German filters installed."""

    def __init__(
        self,
        templates_folder: Path = WEB_TEMPLATES_DIRECTORY,
        static_folder: Path = WEB_STATIC_DIRECTORY,
    ) -> None:
        self._templates = Jinja2Templates(directory=templates_folder)
        environment = self._templates.env
        GermanTemplateFilters(german_formatter).install_into(environment)
        environment.filters["short_date"] = german_formatter.short_date
        environment.filters["long_weekday"] = german_formatter.long_weekday
        environment.filters["clock"] = german_formatter.clock
        environment.filters["serie"] = recurrence_words
        environment.globals["static_version"] = self._static_version(static_folder)

    def render(
        self,
        request: Request,
        template_name: str,
        context: dict[str, object],
        status_code: int = 200,
    ) -> Response:
        return self._templates.TemplateResponse(
            request, template_name, context, status_code=status_code
        )

    @staticmethod
    def _static_version(static_folder: Path) -> int:
        """The newest change time among the static files.

        Read once at import; every deploy restarts the server, and that
        restart is what makes the phones drop their stale caches.
        """
        return max(int(entry.stat().st_mtime) for entry in static_folder.iterdir())


template_renderer = GermanTemplateRenderer()
"""One shared instance, because every router renders through the same environment."""
