"""Storage abstraction + SQLite backend.

The `Store` interface is the contract a hosted backend exposes to the
server. Production deployments swap SQLiteStore for a Postgres or
CockroachDB-backed implementation by writing a new subclass.

Records are stored as opaque canonical JSON strings. The server never
unmarshals them with Pydantic on the read path — that keeps GET /conduct
fast and makes the storage layer agnostic to AAT version bumps.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


# ── Row dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentRow:
    agent_id: str
    agent_name: str
    owner_email: str
    purpose: str
    agent_version: str
    public_key_pem: str | None
    created_at: str


@dataclass(frozen=True)
class ApiKeyRow:
    key_prefix: str
    key_hash: str
    agent_id: str
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    agent_id: str
    started_at: str
    closed_at: str | None
    session_hash: str | None


# ── Abstract Store ──────────────────────────────────────────────────────


class Store(ABC):
    """Storage interface for the Headlights server."""

    # Agents
    @abstractmethod
    def create_agent(self, agent: AgentRow) -> None: ...
    @abstractmethod
    def get_agent(self, agent_id: str) -> AgentRow | None: ...

    # API keys
    @abstractmethod
    def create_api_key(self, row: ApiKeyRow) -> None: ...
    @abstractmethod
    def lookup_api_key(self, key_prefix: str) -> ApiKeyRow | None: ...

    # Sessions
    @abstractmethod
    def create_session(self, session: SessionRow) -> None: ...
    @abstractmethod
    def get_session(self, session_id: str) -> SessionRow | None: ...
    @abstractmethod
    def close_session(
        self, session_id: str, session_hash: str, closed_at: str
    ) -> None: ...
    @abstractmethod
    def latest_open_session(self, agent_id: str) -> SessionRow | None: ...

    # Records
    @abstractmethod
    def append_record(
        self,
        *,
        session_id: str,
        position: int,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> None: ...
    @abstractmethod
    def get_record_at(self, session_id: str, position: int) -> dict[str, Any] | None: ...
    @abstractmethod
    def get_last_record(self, session_id: str) -> tuple[int, dict[str, Any]] | None: ...
    @abstractmethod
    def get_session_records(self, session_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def get_session_record_count(self, session_id: str) -> int: ...
    @abstractmethod
    def get_agent_records(
        self,
        agent_id: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]: ...


# ── SQLite implementation ───────────────────────────────────────────────


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    owner_email     TEXT NOT NULL,
    purpose         TEXT NOT NULL,
    agent_version   TEXT NOT NULL,
    public_key_pem  TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_prefix  TEXT PRIMARY KEY,
    key_hash    TEXT NOT NULL,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL REFERENCES agents(agent_id),
    started_at   TEXT NOT NULL,
    closed_at    TEXT,
    session_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(agent_id, closed_at);

CREATE TABLE IF NOT EXISTS records (
    session_id     TEXT NOT NULL REFERENCES sessions(session_id),
    position       INTEGER NOT NULL,
    record_id      TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    canonical_json TEXT NOT NULL,
    PRIMARY KEY (session_id, position)
);

CREATE INDEX IF NOT EXISTS idx_records_record_id ON records(record_id);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
"""


class SQLiteStore(Store):
    """SQLite-backed Store. Threadsafe via a per-instance lock."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Agents ──────────────────────────────────────────────────────────

    def create_agent(self, agent: AgentRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO agents (agent_id, agent_name, owner_email, purpose, "
                "agent_version, public_key_pem, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    agent.agent_id,
                    agent.agent_name,
                    agent.owner_email,
                    agent.purpose,
                    agent.agent_version,
                    agent.public_key_pem,
                    agent.created_at,
                ),
            )

    def get_agent(self, agent_id: str) -> AgentRow | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT agent_id, agent_name, owner_email, purpose, agent_version, "
                "public_key_pem, created_at FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            return AgentRow(*row) if row else None

    # ── API keys ────────────────────────────────────────────────────────

    def create_api_key(self, row: ApiKeyRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (key_prefix, key_hash, agent_id, created_at, revoked_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (row.key_prefix, row.key_hash, row.agent_id, row.created_at, row.revoked_at),
            )

    def lookup_api_key(self, key_prefix: str) -> ApiKeyRow | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT key_prefix, key_hash, agent_id, created_at, revoked_at "
                "FROM api_keys WHERE key_prefix = ?",
                (key_prefix,),
            )
            row = cur.fetchone()
            return ApiKeyRow(*row) if row else None

    # ── Sessions ────────────────────────────────────────────────────────

    def create_session(self, session: SessionRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (session_id, agent_id, started_at, closed_at, session_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    session.agent_id,
                    session.started_at,
                    session.closed_at,
                    session.session_hash,
                ),
            )

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT session_id, agent_id, started_at, closed_at, session_hash "
                "FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            return SessionRow(*row) if row else None

    def close_session(
        self, session_id: str, session_hash: str, closed_at: str
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE sessions SET closed_at = ?, session_hash = ? WHERE session_id = ?",
                (closed_at, session_hash, session_id),
            )

    def latest_open_session(self, agent_id: str) -> SessionRow | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT session_id, agent_id, started_at, closed_at, session_hash "
                "FROM sessions WHERE agent_id = ? AND closed_at IS NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (agent_id,),
            )
            row = cur.fetchone()
            return SessionRow(*row) if row else None

    # ── Records ─────────────────────────────────────────────────────────

    def append_record(
        self,
        *,
        session_id: str,
        position: int,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, position, record_id, timestamp, canonical_json),
            )

    def get_record_at(self, session_id: str, position: int) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT canonical_json FROM records WHERE session_id = ? AND position = ?",
                (session_id, position),
            )
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def get_last_record(self, session_id: str) -> tuple[int, dict[str, Any]] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT position, canonical_json FROM records WHERE session_id = ? "
                "ORDER BY position DESC LIMIT 1",
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return row[0], json.loads(row[1])

    def get_session_records(self, session_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT canonical_json FROM records WHERE session_id = ? ORDER BY position ASC",
                (session_id,),
            )
            return [json.loads(r[0]) for r in cur.fetchall()]

    def get_session_record_count(self, session_id: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM records WHERE session_id = ?",
                (session_id,),
            )
            return cur.fetchone()[0]

    def get_agent_records(
        self,
        agent_id: str,
        *,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["s.agent_id = ?"]
        params: list[Any] = [agent_id]
        if since is not None:
            clauses.append("r.timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("r.timestamp <= ?")
            params.append(until)
        sql = (
            "SELECT r.canonical_json FROM records r "
            "JOIN sessions s ON s.session_id = r.session_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY r.timestamp ASC, r.session_id ASC, r.position ASC"
        )
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [json.loads(row[0]) for row in cur.fetchall()]
