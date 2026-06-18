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
    public_view: bool = False


class Store(ABC):
    @abstractmethod
    def create_agent(self, agent: AgentRow) -> None: ...
    @abstractmethod
    def get_agent(self, agent_id: str) -> AgentRow | None: ...
    @abstractmethod
    def create_api_key(self, row: ApiKeyRow) -> None: ...
    @abstractmethod
    def create_agent_with_key(self, agent: AgentRow, key: ApiKeyRow) -> None:
        """Atomically insert an agent row and its initial API key.

        Must commit both or neither — no orphaned agent rows.
        """
        ...
    @abstractmethod
    def lookup_api_key(self, key_prefix: str) -> ApiKeyRow | None: ...
    @abstractmethod
    def create_session(self, session: SessionRow) -> None: ...
    @abstractmethod
    def get_session(self, session_id: str) -> SessionRow | None: ...
    @abstractmethod
    def close_session(self, session_id: str, session_hash: str, closed_at: str) -> None: ...
    @abstractmethod
    def latest_open_session(self, agent_id: str) -> SessionRow | None: ...
    @abstractmethod
    def set_session_public_view(self, session_id: str, public: bool) -> None: ...
    @abstractmethod
    def append_record(self, *, session_id: str, position: int, record_id: str, timestamp: str, canonical_json: str) -> None: ...
    @abstractmethod
    def open_session_atomic(
        self,
        *,
        session: SessionRow,
        position: int,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> None:
        """Atomically write the SessionRow and the genesis record.

        Must commit both or neither — no orphaned session rows.
        """
        ...
    @abstractmethod
    def append_record_atomic(
        self,
        *,
        session_id: str,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> tuple[int, dict]:
        """Atomically read the last record, determine next position, and insert.

        Returns (new_position, last_record_dict) so callers that already have
        the canonical_json pre-built can still use this path. For the common
        case where prev_hash must be computed inside the lock, prefer
        append_record_with_chain_link instead.

        Raises LookupError if the session has no genesis record.
        Raises sqlite3.IntegrityError on PK collision (should not occur).
        """
        ...

    @abstractmethod
    def append_record_with_chain_link(
        self,
        *,
        session_id: str,
        build_record_fn,
    ) -> tuple[int, str, str]:
        """Atomically read the last record, build the next record, and insert it.

        ``build_record_fn(prev_position, prev_dict)`` is called *inside* the
        lock and must return ``(record_id, timestamp, canonical_json,
        record_hash)``.

        This collapses the read-compute-insert of the hash chain into a single
        locked transaction, eliminating the prev_hash fork race: two concurrent
        callers serialise here and each sees the other's committed record before
        computing its own prev_hash.

        Returns ``(new_position, record_id, record_hash)``.
        Raises ``LookupError`` if the session has no genesis record.
        Raises ``sqlite3.IntegrityError`` on PK collision (should not occur).
        """
        ...

    @abstractmethod
    def close_session_atomic(
        self,
        *,
        session_id: str,
        session_hash: str,
        closed_at: str,
        record_id: str,
        timestamp: str,
        canonical_json: str,
        position: int,
    ) -> None:
        """Atomically write the session_end record and mark the session closed.

        Must commit both or neither.
        """
        ...
    @abstractmethod
    def get_record_at(self, session_id: str, position: int) -> dict[str, Any] | None: ...
    @abstractmethod
    def get_last_record(self, session_id: str) -> tuple[int, dict[str, Any]] | None: ...
    @abstractmethod
    def get_session_records(self, session_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def get_session_record_count(self, session_id: str) -> int: ...
    @abstractmethod
    def get_agent_records(self, agent_id: str, *, since: str | None = None, until: str | None = None, limit: int | None = None, cursor: tuple[str, str, int] | None = None) -> list[dict[str, Any]]: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, owner_email TEXT NOT NULL,
    purpose TEXT NOT NULL, agent_version TEXT NOT NULL,
    public_key_pem TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    key_prefix TEXT PRIMARY KEY, key_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    started_at TEXT NOT NULL, closed_at TEXT, session_hash TEXT,
    public_view INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent_id ON sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_open ON sessions(agent_id, closed_at);
CREATE TABLE IF NOT EXISTS records (
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    position INTEGER NOT NULL, record_id TEXT NOT NULL,
    timestamp TEXT NOT NULL, canonical_json TEXT NOT NULL,
    PRIMARY KEY (session_id, position)
);
CREATE INDEX IF NOT EXISTS idx_records_record_id ON records(record_id);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);
"""


class SQLiteStore(Store):
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        try:
            # M-001: add public_view column to sessions (added in v0.1.0a1)
            cur.execute("PRAGMA table_info(sessions)")
            cols = {row[1] for row in cur.fetchall()}
            if "public_view" not in cols:
                cur.execute(
                    "ALTER TABLE sessions ADD COLUMN public_view INTEGER NOT NULL DEFAULT 0"
                )

            # M-002: key_prefix length raised from 16 to 24 (v0.1.0a2)
            # Old rows have a 16-char prefix stored as the PRIMARY KEY. SQLite
            # TEXT columns carry no enforced length limit, so a plain UPDATE on
            # the PK column is sufficient — no table rebuild required. Because
            # api_keys.key_prefix is not referenced by any foreign key, updating
            # the PK in-place is safe.
            #
            # Rows that need migration get a sentinel prefix of the form
            # 'MIGRATED_' + first-15-hex-chars-of-key_hash (exactly 24 chars).
            # The sentinel will never match a real lookup (lookups use the
            # live key_prefix() output), so affected keys are effectively
            # revoked. The migration is idempotent: re-running on an already-
            # migrated DB finds LENGTH(key_prefix) >= 24 everywhere and skips.
            #
            # In practice this migration only matters for development DBs;
            # production deployments start fresh.
            cur.execute("PRAGMA table_info(api_keys)")
            key_info = {row[1]: row for row in cur.fetchall()}
            if "key_prefix" in key_info:
                # Check if any prefix is shorter than 24 chars.
                cur.execute("SELECT COUNT(*) FROM api_keys WHERE LENGTH(key_prefix) < 24")
                short_count = cur.fetchone()[0]
                if short_count > 0:
                    # Extend short prefixes using the stored key_hash (first 24
                    # hex chars). The resulting prefix won't match any future
                    # lookup (lookups use the real key_prefix(key) output), so
                    # these keys are effectively revoked. Log clearly.
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "M-002: found %d api_keys row(s) with key_prefix shorter than 24 chars. "
                        "These keys pre-date the prefix-length migration and can no longer be "
                        "looked up — they are effectively revoked. Rotate affected API keys.",
                        short_count,
                    )
                    cur.execute(
                        """
                        UPDATE api_keys
                        SET key_prefix = 'MIGRATED_' || SUBSTR(key_hash, 1, 15)
                        WHERE LENGTH(key_prefix) < 24
                        """
                    )
        finally:
            cur.close()

    @contextmanager
    def _cursor(self):
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

    def create_agent(self, agent: AgentRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO agents (agent_id, agent_name, owner_email, purpose, agent_version, public_key_pem, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent.agent_id, agent.agent_name, agent.owner_email, agent.purpose, agent.agent_version, agent.public_key_pem, agent.created_at),
            )

    def get_agent(self, agent_id: str) -> AgentRow | None:
        with self._cursor() as cur:
            cur.execute("SELECT agent_id, agent_name, owner_email, purpose, agent_version, public_key_pem, created_at FROM agents WHERE agent_id = ?", (agent_id,))
            row = cur.fetchone()
            return AgentRow(*row) if row else None

    def create_api_key(self, row: ApiKeyRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO api_keys (key_prefix, key_hash, agent_id, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
                (row.key_prefix, row.key_hash, row.agent_id, row.created_at, row.revoked_at),
            )

    def create_agent_with_key(self, agent: AgentRow, key: ApiKeyRow) -> None:
        """Atomically insert an agent row and its initial API key in one transaction."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO agents (agent_id, agent_name, owner_email, purpose, agent_version, public_key_pem, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (agent.agent_id, agent.agent_name, agent.owner_email, agent.purpose, agent.agent_version, agent.public_key_pem, agent.created_at),
                )
                cur.execute(
                    "INSERT INTO api_keys (key_prefix, key_hash, agent_id, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
                    (key.key_prefix, key.key_hash, key.agent_id, key.created_at, key.revoked_at),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def lookup_api_key(self, key_prefix: str) -> ApiKeyRow | None:
        with self._cursor() as cur:
            cur.execute("SELECT key_prefix, key_hash, agent_id, created_at, revoked_at FROM api_keys WHERE key_prefix = ?", (key_prefix,))
            row = cur.fetchone()
            return ApiKeyRow(*row) if row else None

    def create_session(self, session: SessionRow) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (session_id, agent_id, started_at, closed_at, session_hash, public_view) VALUES (?, ?, ?, ?, ?, ?)",
                (session.session_id, session.agent_id, session.started_at, session.closed_at, session.session_hash, 1 if session.public_view else 0),
            )

    def open_session_atomic(
        self,
        *,
        session: SessionRow,
        position: int,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> None:
        """Atomically write the SessionRow and the genesis record in one transaction."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO sessions (session_id, agent_id, started_at, closed_at, session_hash, public_view) VALUES (?, ?, ?, ?, ?, ?)",
                    (session.session_id, session.agent_id, session.started_at, session.closed_at, session.session_hash, 1 if session.public_view else 0),
                )
                cur.execute(
                    "INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) VALUES (?, ?, ?, ?, ?)",
                    (session.session_id, position, record_id, timestamp, canonical_json),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._cursor() as cur:
            cur.execute("SELECT session_id, agent_id, started_at, closed_at, session_hash, public_view FROM sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if row is None: return None
            return SessionRow(session_id=row[0], agent_id=row[1], started_at=row[2], closed_at=row[3], session_hash=row[4], public_view=bool(row[5]))

    def close_session(self, session_id: str, session_hash: str, closed_at: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE sessions SET closed_at = ?, session_hash = ? WHERE session_id = ?", (closed_at, session_hash, session_id))

    def latest_open_session(self, agent_id: str) -> SessionRow | None:
        with self._cursor() as cur:
            cur.execute("SELECT session_id, agent_id, started_at, closed_at, session_hash, public_view FROM sessions WHERE agent_id = ? AND closed_at IS NULL ORDER BY started_at DESC LIMIT 1", (agent_id,))
            row = cur.fetchone()
            if row is None: return None
            return SessionRow(session_id=row[0], agent_id=row[1], started_at=row[2], closed_at=row[3], session_hash=row[4], public_view=bool(row[5]))

    def set_session_public_view(self, session_id: str, public: bool) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE sessions SET public_view = ? WHERE session_id = ?", (1 if public else 0, session_id))

    def append_record(self, *, session_id, position, record_id, timestamp, canonical_json) -> None:
        with self._cursor() as cur:
            cur.execute("INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) VALUES (?, ?, ?, ?, ?)", (session_id, position, record_id, timestamp, canonical_json))

    def append_record_atomic(
        self,
        *,
        session_id: str,
        record_id: str,
        timestamp: str,
        canonical_json: str,
    ) -> tuple[int, dict]:
        """Atomically read the last record, determine next position, and insert.

        Returns (new_position, last_record_dict).
        Raises LookupError if the session has no genesis record.
        Raises sqlite3.IntegrityError on PK collision (should not occur).
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT position, canonical_json FROM records "
                    "WHERE session_id = ? ORDER BY position DESC LIMIT 1",
                    (session_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"session {session_id} has no genesis record")
                last_pos = row[0]
                last_dict = json.loads(row[1])
                new_position = last_pos + 1
                cur.execute(
                    "INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, new_position, record_id, timestamp, canonical_json),
                )
                self._conn.commit()
                return new_position, last_dict
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def append_record_with_chain_link(
        self,
        *,
        session_id: str,
        build_record_fn,
    ) -> tuple[int, str, str]:
        """Atomically read the last record, build the next record, and insert it.

        ``build_record_fn(prev_position, prev_dict)`` is called inside the lock
        and must return ``(record_id, timestamp, canonical_json, record_hash)``.

        This collapses the read-compute-insert of the hash chain into a single
        locked transaction, eliminating the prev_hash fork race: two concurrent
        callers serialise here and each sees the other's committed record before
        computing its own prev_hash.

        Returns ``(new_position, record_id, record_hash)``.
        Raises ``LookupError`` if the session has no genesis record.
        Raises ``sqlite3.IntegrityError`` on PK collision (should not occur).
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT position, canonical_json FROM records "
                    "WHERE session_id = ? ORDER BY position DESC LIMIT 1",
                    (session_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"session {session_id} has no genesis record")
                prev_position = row[0]
                prev_dict = json.loads(row[1])

                record_id, timestamp, canonical_json, record_hash = build_record_fn(
                    prev_position, prev_dict
                )

                new_position = prev_position + 1
                cur.execute(
                    "INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, new_position, record_id, timestamp, canonical_json),
                )
                self._conn.commit()
                return new_position, record_id, record_hash
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def close_session_atomic(
        self,
        *,
        session_id: str,
        session_hash: str,
        closed_at: str,
        record_id: str,
        timestamp: str,
        canonical_json: str,
        position: int,
    ) -> None:
        """Atomically insert the session_end record and mark the session closed."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO records (session_id, position, record_id, timestamp, canonical_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, position, record_id, timestamp, canonical_json),
                )
                cur.execute(
                    "UPDATE sessions SET closed_at = ?, session_hash = ? WHERE session_id = ?",
                    (closed_at, session_hash, session_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_record_at(self, session_id, position):
        with self._cursor() as cur:
            cur.execute("SELECT canonical_json FROM records WHERE session_id = ? AND position = ?", (session_id, position))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def get_last_record(self, session_id):
        with self._cursor() as cur:
            cur.execute("SELECT position, canonical_json FROM records WHERE session_id = ? ORDER BY position DESC LIMIT 1", (session_id,))
            row = cur.fetchone()
            if not row: return None
            return row[0], json.loads(row[1])

    def get_session_records(self, session_id):
        with self._cursor() as cur:
            cur.execute("SELECT canonical_json FROM records WHERE session_id = ? ORDER BY position ASC", (session_id,))
            return [json.loads(r[0]) for r in cur.fetchall()]

    def get_session_record_count(self, session_id):
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM records WHERE session_id = ?", (session_id,))
            return cur.fetchone()[0]

    def get_agent_records(self, agent_id, *, since=None, until=None, limit=None, cursor=None):
        """Fetch records for an agent with optional time-range filter and cursor pagination.

        ``cursor`` must be either None or a tuple ``(timestamp, session_id, position)``
        as returned by ``encode_conduct_cursor`` / ``decode_conduct_cursor`` in
        ``routes/conduct.py``.  A raw RFC 3339 string is *no longer accepted* — callers
        that pass a plain string will get a TypeError from SQLite's tuple parameter
        binding, which is the correct failure mode.

        The pagination predicate is a row-value comparison:
            (r.timestamp, r.session_id, r.position) > (?, ?, ?)
        which guarantees that no records are skipped when multiple records share
        the same millisecond timestamp at a page boundary.
        """
        clauses = ["s.agent_id = ?"]
        params: list[Any] = [agent_id]
        if since is not None:
            clauses.append("r.timestamp >= ?"); params.append(since)
        if until is not None:
            clauses.append("r.timestamp <= ?"); params.append(until)
        if cursor is not None:
            cur_ts, cur_sid, cur_pos = cursor
            # Row-value comparison: deterministic total order over (ts, sid, pos).
            clauses.append(
                "(r.timestamp, r.session_id, r.position) > (?, ?, ?)"
            )
            params.extend([cur_ts, cur_sid, int(cur_pos)])
        sql = ("SELECT r.canonical_json, r.session_id, r.position "
               "FROM records r JOIN sessions s ON s.session_id = r.session_id "
               f"WHERE {' AND '.join(clauses)} ORDER BY r.timestamp ASC, r.session_id ASC, r.position ASC")
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [json.loads(row[0]) for row in cur.fetchall()]
