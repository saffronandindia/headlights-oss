"""Session and conduct endpoints — open, append, close, retrieve."""

import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from headlights_server.chains import (
    append_action,
    close_session,
    open_session,
)
from headlights_server.config import Settings
from headlights_server.deps import get_settings, get_store, require_api_key_for_agent
from headlights_server.models import (
    AppendActionRequest,
    AppendActionResponse,
    CloseSessionResponse,
    CONDUCT_PAGE_SIZE,
    ConductResponse,
    OpenSessionRequest,
    OpenSessionResponse,
)
from headlights_server.storage import Store

router = APIRouter(prefix="/v1/agents", tags=["conduct"])

# Loose RFC 3339 pattern accepted as since/until values.
# Full validation is left to SQLite's text comparison, but obviously
# malformed values are rejected early with a 422.
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _validate_timestamp(value: str | None, name: str) -> None:
    if value is not None and not _RFC3339_RE.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{name} must be an RFC 3339 timestamp (e.g. 2024-01-01T00:00:00Z)",
        )


@router.post(
    "/{agent_id}/sessions",
    response_model=OpenSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a new session and write the genesis record.",
)
def open_session_endpoint(
    body: OpenSessionRequest,
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    store: Annotated[Store, Depends(get_store)],
) -> OpenSessionResponse:
    agent = store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    session_id, position, record_hash, started_at = open_session(
        store=store,
        agent_id=agent_id,
        agent_version=agent.agent_version,
        trust_level=body.trust_level,
        genesis_detail=body.genesis_detail,
    )
    return OpenSessionResponse(
        session_id=session_id,
        genesis_position=position,
        genesis_record_hash=record_hash,
        started_at=started_at,
    )


@router.post(
    "/{agent_id}/sessions/{session_id}/close",
    response_model=CloseSessionResponse,
    summary="Close a session — writes session_end with the session_hash.",
)
def close_session_endpoint(
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    session_id: Annotated[str, Path()],
    store: Annotated[Store, Depends(get_store)],
) -> CloseSessionResponse:
    session = store.get_session(session_id)
    if session is None or session.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if session.closed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="session is already closed"
        )

    agent = store.get_agent(agent_id)
    assert agent is not None
    record_count, session_hash, closed_at = close_session(
        store=store,
        agent_id=agent_id,
        agent_version=agent.agent_version,
        session_id=session_id,
    )
    return CloseSessionResponse(
        session_id=session_id,
        record_count=record_count,
        session_hash=session_hash,
        closed_at=closed_at,
    )


@router.post(
    "/{agent_id}/actions",
    response_model=AppendActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append an action to a session. Opens a session if none is active.",
)
def append_action_endpoint(
    body: AppendActionRequest,
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AppendActionResponse:
    agent = store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    session_id = body.session_id
    if session_id is not None:
        session = store.get_session(session_id)
        if session is None or session.agent_id != agent_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
            )
        if session.closed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="session is closed; open a new one",
            )
    else:
        latest = store.latest_open_session(agent_id)
        if latest is None:
            session_id, _, _, _ = open_session(
                store=store,
                agent_id=agent_id,
                agent_version=agent.agent_version,
                trust_level=body.trust_level,
                genesis_detail={},
            )
        else:
            session_id = latest.session_id

    if store.get_session_record_count(session_id) >= settings.free_tier_session_cap:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"session has hit the free-tier cap of "
                f"{settings.free_tier_session_cap} records; close the session and open a new one"
            ),
        )

    optional_fields: dict = {}
    if body.risk_score is not None:
        optional_fields["risk_score"] = body.risk_score
    if body.input_hash is not None:
        optional_fields["input_hash"] = body.input_hash
    if body.output_hash is not None:
        optional_fields["output_hash"] = body.output_hash
    if body.latency_ms is not None:
        optional_fields["latency_ms"] = body.latency_ms
    if body.jurisdiction is not None:
        optional_fields["jurisdiction"] = body.jurisdiction

    position, record_id, record_hash = append_action(
        store=store,
        agent_id=agent_id,
        agent_version=agent.agent_version,
        session_id=session_id,
        action_type=body.action_type,
        action_detail=body.action_detail,
        outcome=body.outcome,
        trust_level=body.trust_level,
        optional_fields=optional_fields,
    )
    return AppendActionResponse(
        session_id=session_id,
        position=position,
        record_id=record_id,
        record_hash=record_hash,
    )


@router.get(
    "/{agent_id}/conduct",
    response_model=ConductResponse,
    summary=(
        "List records for an agent. Supports time-range filtering and cursor pagination. "
        f"Returns at most {CONDUCT_PAGE_SIZE} records per page."
    ),
)
def get_conduct_endpoint(
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    store: Annotated[Store, Depends(get_store)],
    since: Annotated[Optional[str], Query(description="RFC 3339 lower bound (inclusive)")] = None,
    until: Annotated[Optional[str], Query(description="RFC 3339 upper bound (inclusive)")] = None,
    cursor: Annotated[Optional[str], Query(description="Opaque pagination cursor from a previous response")] = None,
) -> ConductResponse:
    _validate_timestamp(since, "since")
    _validate_timestamp(until, "until")
    _validate_timestamp(cursor, "cursor")

    # Fetch one extra record to determine whether a next page exists.
    records = store.get_agent_records(
        agent_id,
        since=since,
        until=until,
        cursor=cursor,
        limit=CONDUCT_PAGE_SIZE + 1,
    )
    next_cursor: str | None = None
    if len(records) > CONDUCT_PAGE_SIZE:
        records = records[:CONDUCT_PAGE_SIZE]
        next_cursor = records[-1].get("timestamp")

    return ConductResponse(
        agent_id=agent_id,
        record_count=len(records),
        records=records,
        next_cursor=next_cursor,
    )


@router.get(
    "/{agent_id}/sessions/{session_id}/conduct",
    response_model=ConductResponse,
    summary="List records for one session, in chain order.",
)
def get_session_conduct_endpoint(
    agent_id: Annotated[str, Depends(require_api_key_for_agent)],
    session_id: Annotated[str, Path()],
    store: Annotated[Store, Depends(get_store)],
) -> ConductResponse:
    session = store.get_session(session_id)
    if session is None or session.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    records = store.get_session_records(session_id)
    return ConductResponse(
        agent_id=agent_id,
        record_count=len(records),
        records=records,
    )
