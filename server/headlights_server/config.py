"""Server configuration. Read from env vars or constructed directly in tests."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the FastAPI app."""

    database_url: str = "sqlite:///./headlights.db"
    """SQLAlchemy-style URL. v1 supports sqlite:/// only."""

    agent_id_prefix: str = "urn:headlights:agent:"
    """URI prefix prepended to the generated agent slug to form agent_id."""

    api_key_prefix: str = "hl_live_"
    """Plaintext prefix on every issued API key. Helps users spot keys in logs."""

    free_tier_session_cap: int = 100_000
    """Max records per session before further appends are rejected. ADR-006 / handover §11."""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("HEADLIGHTS_DATABASE_URL", cls.database_url),
            agent_id_prefix=os.getenv("HEADLIGHTS_AGENT_ID_PREFIX", cls.agent_id_prefix),
            api_key_prefix=os.getenv("HEADLIGHTS_API_KEY_PREFIX", cls.api_key_prefix),
            free_tier_session_cap=int(
                os.getenv("HEADLIGHTS_SESSION_CAP", str(cls.free_tier_session_cap))
            ),
        )
