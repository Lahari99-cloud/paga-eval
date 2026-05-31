"""Local-only FastAPI wrapper for the institution demo console."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from paga.api import ServiceSettings, create_app

DEMO_HTML = Path(__file__).with_name("institution_demo.html")


def create_demo_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Build the real service plus a same-origin local demo console."""

    app = create_app(settings)

    @app.get("/", include_in_schema=False)
    def demo_redirect() -> RedirectResponse:
        return RedirectResponse("/demo")

    @app.get("/demo", include_in_schema=False)
    def demo_console() -> HTMLResponse:
        return HTMLResponse(DEMO_HTML.read_text(encoding="utf-8"))

    return app
