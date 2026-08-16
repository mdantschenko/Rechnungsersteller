"""The contract every PDF renderer fulfils.

All renderers produce the same layout because the document carries its fonts
and measurements inside itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PdfRenderer(Protocol):
    """Writes a self-contained HTML document to a PDF file."""

    def write(self, html: str, destination: Path) -> None: ...
