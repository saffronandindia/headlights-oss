"""FastAPI app factory.

Usage:

    from headlights_server import create_app
    from headlights_server.storage import SQLiteStore

    app = create_app(store=SQLiteStore("./headlights.db"))

CORS stance
-----------
No CORSMiddleware is added. Headlights is a bearer-token API intended to be
called by server-side agent runtimes, not from browser scripts. The browser's
same-origin policy blocks cross-origin XHR/fetch by default, which is the safe
default for an API that carries authentication credentials in the Authorization
header. If you need browser-accessible access in a future version, add
CORSMiddleware with an explicit allowlist of origins; do not use
allow_origins=["*"].

Interactive docs
----------------
/docs and /openapi.json are disabled in production (HEADLIGHTS_DEBUG=false,
the default). Set HEADLIGHTS_DEBUG=true to enable them locally. Leaking the
full schema in production is a recon gift; the OpenAPI spec is available in the
source repo for integrators.
"""

from __future__ import annotations

import logging
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from headlights_server import __version__
from headlights_server.config import Settings
from headlights_server.routes.agents import router as agents_router
from headlights_server.routes.conduct import router as conduct_router
from headlights_server.routes.trace import router as trace_router
from headlights_server.storage import SQLiteStore, Store

logger = logging.getLogger(__name__)

# Docs are enabled only when explicitly requested (local dev / CI).
_DEBUG = os.getenv("HEADLIGHTS_DEBUG", "false").lower() in {"1", "true", "yes"}


def create_app(
    *,
    store: Store | None = None,
    settings: Settings | None = None,
    debug: bool | None = None,
) -> FastAPI:
    """Build a FastAPI app instance.

    Pass a custom Store for tests; otherwise an SQLiteStore is constructed
    from the configured database_url.

    Pass debug=True to enable /docs and /openapi.json (default: off in
    production, controlled by HEADLIGHTS_DEBUG env var).
    """
    settings = settings or Settings.from_env()
    if store is None:
        if not settings.database_url.startswith("sqlite:///"):
            raise ValueError(
                f"unsupported database_url {settings.database_url!r}; "
                "v1 supports sqlite:/// only"
            )
        path = settings.database_url[len("sqlite:///"):]
        store = SQLiteStore(path)

    enable_docs = debug if debug is not None else _DEBUG

    app = FastAPI(
        title="Headlights",
        version=__version__,
        description=(
            "GitHub for AI conduct records. Records every AI agent action into a "
            "tamper-evident, AAT-aligned hash chain. See "
            "https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/."
        ),
        # /docs and /openapi.json are disabled in production.
        # Enable with HEADLIGHTS_DEBUG=true or debug=True in create_app().
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
    )
    app.state.store = store
    app.state.settings = settings

    app.include_router(agents_router)
    app.include_router(conduct_router)
    app.include_router(trace_router)

    @app.get("/healthz", tags=["meta"], summary="Liveness probe.")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # ── Global exception handler ────────────────────────────────────────
    # Catches any unhandled exception that escapes a route handler.
    # Logs the full traceback server-side; returns a safe generic envelope
    # to the caller — no internal detail (schema names, file paths, etc.)
    # is forwarded to the response body.
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled exception on %s %s\n%s",
            request.method,
            request.url.path,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error"},
        )

    return app


# Lazy module-level `app` for `uvicorn headlights_server.app:app`. We build
# on first ASGI call so just importing the module doesn't try to open the
# configured database (irritating in tests, hostile to CI, broken on
# read-only mounts).
class _LazyApp:
    _instance: FastAPI | None = None

    def _build(self) -> FastAPI:
        if self._instance is None:
            self._instance = create_app()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._build(), name)

    async def __call__(self, scope, receive, send):
        return await self._build()(scope, receive, send)


app = _LazyApp()
