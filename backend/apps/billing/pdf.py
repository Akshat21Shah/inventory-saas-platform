"""PDF rendering adapter (ADR-046 item 12): HTML to PDF.

- ``weasyprint``: the real renderer. It needs Pango and a font with the rupee sign (the Docker image
  and CI install them); it is imported only when used, so the app runs without them.
- ``fake``: a stand-in for tests and machines without the libraries. It returns a small
  PDF-looking file that carries the HTML, so tests can check what would be printed.
"""

from functools import lru_cache
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class PdfRenderer(Protocol):
    def render(self, html: str) -> bytes: ...


class WeasyPrintRenderer:
    def render(self, html: str) -> bytes:
        from weasyprint import HTML

        pdf: bytes = HTML(string=html).write_pdf()
        return pdf


class FakeRenderer:
    def render(self, html: str) -> bytes:
        return b"%PDF-1.7\n% fake renderer\n" + html.encode()


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):  # OSError: the Python package is there, Pango isn't
        return False
    return True


@lru_cache(maxsize=1)
def get_renderer() -> PdfRenderer:
    backend = settings.PDF_RENDERER
    if backend == "weasyprint":
        return WeasyPrintRenderer()
    if backend == "fake":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("The fake PDF renderer is for development and tests only.")
        return FakeRenderer()
    raise ImproperlyConfigured(f"Unknown PDF_RENDERER {backend!r}")
