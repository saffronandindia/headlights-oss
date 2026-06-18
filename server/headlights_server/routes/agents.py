"""Agent registration endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from headlights_server.auth import (
    generate_api_key,
    hash_api_key,
    key_prefix,
)
from headlights_server.chains import make_agent_id, utc_now
from headlights_server.config import Settings
from headlights_server.deps import get_settings, get_store
from headlights_server.models import RegisterAgentRequest, RegisterAgentResponse
from headlights_server.storage import AgentRow, ApiKeyRow, Store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/agents", tags=["agents"])

# Per-IP rate limit applied to the unauthenticated registration endpoint.
# 10 registrations per hour is generous for legitimate use while making
# bulk-registration attacks expensive. The limiter instance lives on
# app.state.limiter so each app (including test apps) has its own state.
_REGISTER_RATE = "10/hour"


@router.post(
    "",
    response_model=RegisterAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent and receive an API key (shown once).",
)
def register_agent(
    request: Request,
    body: RegisterAgentRequest,
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterAgentResponse:
    # Rate-limit check: raises 429 if the caller has exceeded _REGISTER_RATE.
    # Reads limiter from app.state so test apps can pass enabled=False.
    limiter = getattr(request.app.state, "limiter", None)
    if limiter is not None:
        limiter.check(request, _REGISTER_RATE, "register_agent")

    agent_id = make_agent_id(settings.agent_id_prefix, body.agent_name)
    created_at = utc_now()

    api_key = generate_api_key(settings.api_key_prefix)
    key_row = ApiKeyRow(
        key_prefix=key_prefix(api_key),
        key_hash=hash_api_key(api_key),
        agent_id=agent_id,
        created_at=created_at,
        revoked_at=None,
    )
    agent_row = AgentRow(
        agent_id=agent_id,
        agent_name=body.agent_name,
        owner_email=body.owner_email,
        purpose=body.purpose,
        agent_version=body.agent_version,
        public_key_pem=body.public_key_pem,
        created_at=created_at,
    )

    try:
        # Atomic: agent row + API key committed together; no orphaned agents.
        store.create_agent_with_key(agent_row, key_row)
    except Exception:
        logger.exception("failed to register agent %s", agent_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal error registering agent",
        )

    return RegisterAgentResponse(
        agent_id=agent_id,
        api_key=api_key,
        created_at=created_at,
    )
