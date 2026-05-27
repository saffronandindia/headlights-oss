# headlights-server

If you're going to record what your AI agent does, you need somewhere to put the records. This is the reference backend — a FastAPI service over SQLite, with the endpoints needed to register an agent, open a session, append actions, and retrieve the chain for verification. Run it locally for development. Swap SQLite for Postgres for production. Or skip it entirely and write your own; the `Store` interface in `storage.py` is the only contract.

## Endpoints

- `POST /v1/agents` — register an agent, receive an API key (shown once).
- `POST /v1/agents/{agent_id}/sessions` — open a session, get the genesis record back.
- `POST /v1/agents/{agent_id}/actions` — append an action to a session (auto-opens one if none active).
- `POST /v1/agents/{agent_id}/sessions/{session_id}/close` — close a session, get the `session_hash`.
- `GET  /v1/agents/{agent_id}/conduct` — list all records for an agent (supports `?since=&until=` filtering).
- `GET  /v1/agents/{agent_id}/sessions/{session_id}/conduct` — list records in one session.

All `/v1/agents/{agent_id}/*` routes require `Authorization: Bearer hl_live_…` where the API key belongs to that agent.

Records live in SQLite at v1. The `Store` interface in `storage.py` is the swap-out point for Postgres (or anything else) without touching routes or models.

## Install

```bash
pip install -e ./chain ./server
headlights-server --host 127.0.0.1 --port 8080
```

OpenAPI docs at `http://localhost:8080/docs` once running.

## Quickest possible smoke test

```bash
# Register
curl -X POST http://localhost:8080/v1/agents \
  -H 'content-type: application/json' \
  -d '{"agent_name":"loan-analyser","owner_email":"e@example.com","purpose":"demo","agent_version":"1.0.0"}'
# → { "agent_id":"urn:headlights:agent:loan-analyser-abc123def0", "api_key":"hl_live_…", "created_at":"…" }

AGENT=urn:headlights:agent:loan-analyser-abc123def0
KEY=hl_live_…

# Append an action (auto-opens a session)
curl -X POST http://localhost:8080/v1/agents/$AGENT/actions \
  -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' \
  -d '{"action_type":"tool_call","action_detail":{"tool_name":"credit_lookup","parameters_hash":"sha256:abc"},"outcome":"success","trust_level":"L1"}'

# Retrieve the chain
curl -H "Authorization: Bearer $KEY" http://localhost:8080/v1/agents/$AGENT/conduct
```

Pipe the conduct response into `headlights-verify` to confirm tamper-evidence end-to-end.

## License

Apache 2.0.
