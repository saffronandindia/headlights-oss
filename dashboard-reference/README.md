# dashboard-reference

Reference dashboard for inspecting Headlights chains. Coming in v0.2.

Until then, the simplest visualisation is to retrieve a chain from the reference server and pipe it through a JSON pretty-printer:

```bash
curl -H "Authorization: Bearer $KEY" \
     "http://localhost:8080/v1/agents/$AGENT/conduct" | jq
```

Or use the `/v1/agents/{agent_id}/sessions/{session_id}/trace` endpoint for the human-readable trace-viewer JSON, which is what the eventual Next.js dashboard will render.

Want to build the dashboard yourself? The reference server's API is the only contract. Issues and PRs welcome.
