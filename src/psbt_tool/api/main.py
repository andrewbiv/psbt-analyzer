"""FastAPI application wiring: routes, templates, static files."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from .routes import router as api_router

def _asset_root() -> Path:
    """Project root in source checkout, or a fixed path in Docker / wheel installs.

    In development, ``src/psbt_tool/api/main.py`` -> parents[3] is the repo root.
    When the package is installed, ``__file__`` lives under site-packages, so
    parents[3] is not the deploy layout; set ``PSBT_ASSET_ROOT`` to the directory
    that contains ``templates/`` and ``static/`` (e.g. ``/app`` in the image).
    """
    if raw := os.getenv("PSBT_ASSET_ROOT"):
        return Path(raw)
    return Path(__file__).resolve().parents[3]


_AR = _asset_root()
_TEMPLATES_DIR = _AR / "templates"
_STATIC_DIR = _AR / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PSBT Analyzer",
        version="0.1.0",
        description=(
            "Analyze, compare, and edit Bitcoin PSBTs. Fee context from mempool.space."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"network": settings.network},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "network": settings.network}

    return app


app = create_app()


def run() -> None:
    """Console entry point: ``psbt-tool`` runs uvicorn."""
    import uvicorn

    uvicorn.run("psbt_tool.api.main:app", host="127.0.0.1", port=8000, reload=False)
