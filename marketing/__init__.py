"""Headlights marketing agents — discovery + drafter.

These agents are themselves the demo. Every API call, every filter
decision, every drafted line is recorded into a Headlights chain via the
local SDK. The resulting chains are uploaded to the Headlights server
and published as public traces, so each outreach email carries a
verifiable record of exactly what the agents did to find and contact
the recipient.

The agents are designed to be run from CLI:

    python -m marketing.discovery --output prospects.csv
    python -m marketing.drafter --prospects prospects.csv --output drafts/

Both default to dry-run mode (no live GitHub calls, no sends) so the
pipeline is safe to iterate on.
"""

__version__ = "0.1.0a0"
