"""Agent registration endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

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

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post(
    "",
    response_model=RegisterAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent and receive an API key (shown once).",
)
def register_agent(
    body: RegisterAgentRequest,
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterAgentResponse:
    agent_id = make_agent_id(settings.agent_id_prefix, body.agent_name)
    created_at = utc_now()

    store.create_agent(
        AgentRow(
            agent_id=agent_id,
            agent_name=body.agent_name,
            owner_email=body.owner_email,
            purpose=body.purpose,
            agent_version=body.agent_version,
            public_key_pem=body.public_key_pem,
            created_at=created_at,
        )
    )

    api_key = generate_api_key(settings.api_key_prefix)
    try:
        store.create_api_key(
            ApiKeyRow(
                key_prefix=key_prefix(api_key),
                key_hash=hash_api_key(api_key),
                agent_id=agent_id,
                created_at=created_at,
                revoked_at=None,
            )
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to provision API key: {e}",
        )

    return RegisterAgentResponse(
        agent_id=agent_id,
        api_key=api_key,
        created_at=created_at,
    )
