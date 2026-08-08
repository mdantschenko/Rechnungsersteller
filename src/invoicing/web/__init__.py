"""The web interface: four screens, server rendered, no client framework."""

from invoicing.web.app import create_app

__all__ = ["create_app"]
