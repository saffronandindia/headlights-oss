# headlights-server

FastAPI backend for [Headlights](https://useheadlights.com) — the open-source AI conduct record server.

Every AI agent action is appended to a tamper-evident SHA-256 hash chain, optionally signed with ECDSA P-256, and published as a public audit page that anyone can verify offline with [`headlights-verify`](../verify/).

Implements [IETF draft-sharif-agent-audit-trail-00](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/).

---

## Quick start (Docker)

```bash
docker compose up
```

The server starts on `http://localhost:8000`. Register your first agent:

> **Single-worker constraint:** The rate limiter is in-process. The default `--workers 1` in the Docker image must be kept. Scaling to multiple workers multiplies the effective rate limit by the worker count. Replace the in-memory limiter with a Redis-backed counter before deploying multi-worker. See [#3](https://github.com/saffronandindia/headlights-oss/issues/3).

```bash
curl -s -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "my-agent",
    "owner_email": "you@example.com",
    "purpose": "Customer support automation"
  }' | jq .
```

Save the `api_key` — it is shown **once**.

---

## Quick start (local Python)

Requires Python 3.10+.

```bash
pip install -e ".[dev]"
HEADLIGHTS_DEBUG=true uvicorn headlights_server.app:app --reload
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `HEADLIGHTS_DATABASE_URL` | `sqlite:///./headlights.db` | SQLite database path. Prefix with `sqlite:///`. |
| `HEADLIGHTS_DEBUG` | `false` | Set `true` to enable `/docs`, `/redoc`, `/openapi.json`. |
| `HEADLIGHTS_AGENT_ID_PREFIX` | `urn:headlights:agent:` | URI prefix for generated agent IDs. |
| `HEADLIGHTS_API_KEY_PREFIX` | `hl_live_` | Plaintext prefix on issued API keys. |
| `HEADLIGHTS_SESSION_CAP` | `100000` | Maximum records per session (free-tier guard). |

---

## API overview

All authenticated endpoints require `Authorization: Bearer <api-key>`.

### Agent registration (unauthenticated)

```
POST /v1/agents
```

Rate-limited to **10 registrations per hour per IP**. Returns an `api_key` shown once.

### Session lifecycle

```
POST /v1/agents/{agent_id}/sessions          → open a session (genesis record)
POST /v1/agents/{agent_id}/sessions/{id}/close   → close + write session_end record
```

### Appending actions

```
POST /v1/agents/{agent_id}/actions
```

Appends an AAT action record to the agent's current open session. Opens a new session automatically if none is active.

### Viewing conduct

```
GET /v1/agents/{agent_id}/conduct            → paginated record list (max 1000/page)
GET /v1/agents/{agent_id}/sessions/{id}/conduct  → all records for one session
```

Query parameters: `since` (RFC 3339), `until` (RFC 3339), `cursor` (opaque, from `next_cursor`).

### Public trace (unauthenticated)

```
POST /v1/agents/{agent_id}/sessions/{id}/publish   → make session public
GET  /v1/sessions/{id}/trace                        → HTML audit page
GET  /v1/sessions/{id}/trace.json                   → canonical JSON export
```

Sessions are **private by default**. Publishing is an explicit opt-in. The HTML page shows a badge:

| Badge | Meaning |
|---|---|
| 🟢 `CHAIN INTACT · SIGNED` | Hash chain intact, session closed, ECDSA signatures verified |
| 🟡 `CHAIN INTACT · HASH ONLY` | Hash chain intact, session closed, no public key on file |
| 🟡 `OPEN SESSION · NOT FINALISED` | Session not yet closed — records may still be appended |
| 🔴 `CHAIN BROKEN` | Hash chain integrity failure at a specific position |

The "Download canonical JSON" button on the trace page lets anyone verify the chain offline:

```bash
pip install headlights-verify
headlights-verify trace.json
```

---

## Database migrations

`SQLiteStore` runs all migrations automatically on startup via `_migrate()`. Current migrations:

| ID | Description |
|---|---|
| M-001 | Add `public_view` column to `sessions` |
| M-002 | Extend `api_keys.key_prefix` rows shorter than 24 chars (from pre-v0.1.0a2 DBs). **Affected keys are revoked** — rotate them after first startup. |

---

## Security notes

- **Reverse proxy / X-Forwarded-For:** The rate limiter uses `request.client.host` when no `X-Forwarded-For` header is present. If you deploy behind nginx, Caddy, or a cloud load balancer you **must** configure trusted proxy IPs (see [#1](https://github.com/saffronandindia/headlights-oss/issues/1)) otherwise rate-limit bypass is trivially possible.
- **No CORS middleware.** This is intentional — the API uses bearer tokens, and same-origin policy is the correct default for authenticated APIs. Add an explicit origin allowlist if you need browser access.
- **`/docs` disabled in production.** Set `HEADLIGHTS_DEBUG=true` locally.
- **API keys are hashed.** Only the SHA-256 hash of each key is stored. The plaintext is shown once at registration.
- **Sensitive fields are hashed before storage.** `input_hash`, `output_hash` in action records accept `sha256:...` values — never raw content.
- **Public key optional.** Agents without a stored ECDSA P-256 public key get hash-chain-only integrity, surfaced as the amber `HASH ONLY` badge on the public trace page.

---

## Running tests

```bash
cd server
pip install -e ".[dev]"
pytest
```

---

## Licence

Apache 2.0 — see [LICENSE](../LICENSE).
