# marketing/ — discovery + drafter agents

This package contains the two AI agents that complete the Headlights
email-as-demo loop. Both are themselves recorded into Headlights chains
when they run, so the agents are their own demo.

## What's in here

- **`discovery.py`** — walks GitHub stargazer lists for major AI-agent
  libraries (LangChain, Pydantic AI, CrewAI, AutoGen, MCP), filters for
  B2B prospects, outputs a CSV.
- **`drafter.py`** — takes the prospect CSV, pulls each prospect's
  public repos, generates a personalised email draft referencing their
  specific work. Embeds a per-draft trace URL. Writes `.eml` files for
  human review.
- **`github.py`** — minimal GitHub API client with on-disk caching.
- **`filters.py`** — B2B context detection (company, repos, bio).
- **`templates.py`** — email subject + body templates. No LLM
  dependency in v1; substitute a Claude call later.

## How the loop works

1. `discovery` produces `prospects.csv` plus its own conduct chain.
2. `drafter` consumes the CSV. For each prospect:
   - Opens a per-draft session (one chain per prospect).
   - Records every API call and filter decision.
   - Generates a templated email with a `trace_session_id` stamped in.
   - Writes `drafts/{login}.eml` and `drafts/chains/{trace_session_id}.json`.
3. A separate upload step (future work) POSTs each per-draft chain to
   the Headlights server and publishes it. The `X-Headlights-Trace`
   header in the email then points to a real, verifiable page.
4. After human review, deliverability provider (Smartlead / Instantly)
   sends the `.eml` files.

## Running locally

```bash
export GITHUB_TOKEN=ghp_...               # optional but lifts rate limit
python -m marketing.discovery \
    --output prospects.csv \
    --max-prospects 20

python -m marketing.drafter \
    --prospects prospects.csv \
    --output drafts/
```

Cached GitHub responses live at `.cache/github/`. Reruns are fast and
incremental.

## Why no LLM call (yet)

V1 generates emails from deterministic templates. Pros:
- Trivial to unit-test.
- No API key dependencies.
- Output is byte-identical for the same input — the chain audit ("we
  decided to write this subject because X") matches the actual subject.

To upgrade later, replace `templates.body_text()` with a Claude API call.
The rest of the pipeline does not change.

## Safety defaults

- The drafter writes `.eml` files. It does NOT send.
- The drafter opens one session per prospect. Trace URLs are unique per
  email. A prospect who clicks one trace URL sees only their own draft.
- The discovery filters reject obvious student / hobbyist accounts. The
  bar is intentionally practical — false negatives (missing a prospect)
  are cheap; false positives (emailing the wrong person) are expensive.
- `GITHUB_TOKEN` is read from env. Without it, you have ~60 requests/hr.

## Tests

```bash
PYTHONPATH=chain:sdk-python:. python -m pytest marketing/tests -q
```

54 tests cover filters, templates, GitHub-client behaviour with mocked
transport, and end-to-end runs of both agents against deterministic
fixtures.
