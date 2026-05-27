# examples

Two commands to see a tamper-evident AI conduct chain prove itself.

## loan_analyser_demo.py

A fictional loan-analyser agent wrapped in the Headlights chain primitive. The demo writes a four-record session (credit-score lookup → decision → escalation → close), signs every record with a freshly-minted ECDSA P-256 key, verifies the intact chain, then deliberately tampers with one record's confidence score and re-verifies. Green on the first check, red on the second, with the failing position and reason printed.

```bash
# From the repo root, with headlights-chain installed:
pip install -e ./chain
PYTHONPATH=chain python3 examples/loan_analyser_demo.py
```

You should see roughly:

```
== Headlights chain demo ==
  Genesis written: session_id=...
  Session closed at position 4
  session_hash: ...

  GREEN: chain intact, all signatures verify.

  Tampering with position 2 (the decision record's confidence)...
  RED: chain broken at position 2
  Reason: prev_hash mismatch: record claims ..., computed ...
```

That's the entire promise of the project, in one script. Open the file and read it — under 120 lines. Every line of the chain construction maps to a section of [`draft-sharif-agent-audit-trail-00`](https://datatracker.ietf.org/doc/draft-sharif-agent-audit-trail/).

Future demos will add: customer-service agent with refusal patterns, coding agent with constraint gates, multi-agent delegation chain.
