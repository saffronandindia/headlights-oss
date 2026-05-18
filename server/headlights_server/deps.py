"""FastAPI dependencies — auth and store wiring."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path, Request, status

from headlights_server.auth import constant_time_equal, hash_api_key, key_prefix
from headlights_server.config import Settings
from headlights_server.storage import Store


def get_store(request: Request) -> Store:
    """Pull the configured Store off app.state. Wired in create_app()."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise RuntimeError(
            "no Store configured on app.state. create_app() must set app.state.store."
        )
    return store


def get_settings(request: Request) -> Settings:
    """Pull the active Settings off app.state."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise RuntimeError("no Settings configured on app.state.")
    return settings


def _strip_bearer(auth_header: str) -> str:
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be `Bearer <api-key>`",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1]


def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    store: Store = Depends(get_store),
) -> str:
    """Validate the bearer token and return the associated agent_id."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key = _strip_bearer(authorization)
    row = store.lookup_api_key(key_prefix(key))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key"
        )
    if not constant_time_equal(row.key_hash, hash_api_key(key)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key"
        )
    if row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key revoked"
        )
    return row.agent_id


def require_api_key_for_agent(
    agent_id: Annotated[str, Path()],
    authenticated_agent_id: Annotated[str, Depends(require_api_key)],
) -> str:
    """Ensure the API key belongs to the agent named in the URL."""
    if authenticated_agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not authorize access to this agent",
        )
    return agent_id
