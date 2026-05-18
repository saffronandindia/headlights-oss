"""FastAPI app factory.

Usage:

    from headlights_server import create_app
    from headlights_server.storage import SQLiteStore

    app = create_app(store=SQLiteStore("./headlights.db"))
"""

from __future__ import annotations

from fastapi import FastAPI

from headlights_server import __version__
from headlights_server.config import Settings
from headlights_server.routes.agents import router as agents_router
from headlights_server.routes.conduct import router as conduct_router
from headlights_server.storage import SQLiteStore, Store


def create_app(
    *,
    store: Store | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build a FastAPI app instance.

    Pass a custom Store for tests; otherwise an SQLiteStore is constructed
    from the configured database_url.
    """
    settings = settings or Settings.from_env()
    if store is None:
        if not settings.database_url.startswith("sqlite:///"):
            raise ValueError(
                f"unsupported database_url {settings.database_url!r}; "
                "v1 supports sqlite:/// only"
            )
        path = settings.database_url[len("sqlite:///") :]
        store = SQLiteStore(path)

    app = FastAPI(
        title="Headlights",
        version=__version__,
        description=(
            "GitHub for AI conduct records. Records every AI agent action into a "
            "tamper-evident, AAT-aligned hash chain. See "
            "https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/."
        ),
    )
    app.state.store = store
    app.state.settings = settings

    app.include_router(agents_router)
    app.include_router(conduct_router)

    @app.get("/healthz", tags=["meta"], summary="Liveness probe.")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

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
