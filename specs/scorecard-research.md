# AI Conduct Scorecard — Vendor Research

Research date: 2026-05-19
Scope: public documentation only (vendor docs, security pages, compliance pages, blog posts, API docs). Where a vendor is silent, this is marked "no public documentation found." No claims are inferred.

The seven dimensions scored per product:

- **A.** Tamper evidence (hash chaining, append-only storage, immutable claims)
- **B.** Signature scheme (per-entry digital signatures, algorithm)
- **C.** Retention (length, defaults, configurability)
- **D.** Replayability (can the AI's actual behavior be reconstructed from logs?)
- **E.** External anchoring (blockchain / third-party notary / WORM beyond vendor control)
- **F.** Customer/auditor access (raw export for independent verification)
- **G.** Standards compliance (SOC 2, ISO 42001, NIST AI RMF, IETF AAT draft, etc.)

---

## 1. OpenAI — ChatGPT (Consumer + Enterprise) + OpenAI API

**Summary.** OpenAI runs two parallel logging surfaces: the Compliance Logs Platform for ChatGPT Enterprise/Edu, and the Admin/Audit Logs API for the API Platform. Both are described as "immutable, append-only," but there is no public mention of cryptographic chaining or per-entry signatures — the immutability claim appears to be a platform/policy guarantee, not a mathematically verifiable property. Default retention is short (30 days) and customers are expected to continuously download for longer storage.

- **A. Tamper evidence.** Documented as "immutable, append-only compliance log events" delivered as "immutable, time-windowed JSONL log files." There is no public statement of hash chaining, Merkle trees, or other cryptographic tamper-evidence. The immutability is a platform-level property; no public proof an OpenAI engineer could not modify the underlying store.
- **B. Signature scheme.** No public documentation found.
- **C. Retention.** Compliance Logs Platform retains data for 30 days; customers are explicitly told to "implement a system to continuously download all logs and retain them according to their policies." Deleted ChatGPT items remain in immutable logs for a 30-day post-deletion window. Audit logs for the API Platform are toggled on at Organization settings → Data controls → Data retention.
- **D. Replayability.** Strong on ChatGPT Enterprise/Edu: the Compliance API exposes "a record of time-stamped interactions, including conversations, uploaded files, workspace GPT configuration and metadata, memories, and workspace users." Raw JSON, dedicated API-key scopes. On the API platform, the Admin/Audit Logs API gives "complete visibility into the state of their OpenAI Organizations" but is event-oriented (admin actions, key changes) rather than per-inference replay. Inference-level replay requires customer-side capture.
- **E. External anchoring.** No public documentation found. SIEM/eDiscovery integrations (Purview, Netskope, Relativity) are downstream destinations, not third-party notarisation.
- **F. Customer/auditor access.** Yes — REST API, raw JSON. Enterprise-only, dedicated API-key scopes.
- **G. Standards compliance.** SOC 2 Type II (Jan–Jun 2025 covers API Platform, ChatGPT Enterprise/Team/Edu — Security, Availability, Confidentiality, Privacy). ISO/IEC 42001:2023 (AI Management System covering consumer and business products). ISO 27001. PCI-DSS for delegated payment components. CSA STAR. No public reference to the IETF AAT draft.

Sources:
- https://help.openai.com/en/articles/9261474-compliance-api-for-enterprise-customers
- https://help.openai.com/en/articles/9687866-admin-and-audit-logs-api-for-the-api-platform
- https://trust.openai.com/

---

## 2. Anthropic — Claude (claude.com / docs.claude.com)

**Summary.** Anthropic's Compliance API is the most expansive on paper: an Activity Feed retained for **6 years**, queryable within 1 minute, covering authentication, chat, file, project, administrative, and platform actions, with the ability to retrieve and delete underlying chat/file/project content. But there is no public claim of cryptographic tamper evidence or per-entry signatures, and the feature is Enterprise-only with no historical backfill — logging starts when the API is turned on (and is not self-serve to enable).

- **A. Tamper evidence.** No public documentation of hash chaining, append-only cryptographic structure, or Merkle trees in the Compliance API or Activity Feed. The feature is described as a record/feed; the trust model is "Anthropic-as-custodian."
- **B. Signature scheme.** No public documentation found for log-entry signing.
- **C. Retention.** Activity Feed records are "queryable within 1 minute of occurring and are retained for 6 years." A separate, narrower CSV export in claude.ai > Organization settings > Data and privacy lets owners download up to 180 days of events.
- **D. Replayability.** Strong on claude.ai organizations: the Compliance API reaches "the underlying chats, files, and projects" — i.e., actual content, not just metadata. Notable gap: **Claude Code (developer CLI) is excluded from audit logs, the Compliance API, and data exports** — agentic developer flows are not covered.
- **E. External anchoring.** No public documentation found.
- **F. Customer/auditor access.** Yes — programmatic via Compliance API. Enabling the Compliance API itself requires contacting Anthropic's account team — "this isn't a self-serve toggle."
- **G. Standards compliance.** SOC 2 Type I & II, ISO/IEC 27001:2022, **ISO/IEC 42001:2023** (accredited AI management system certification), HIPAA-ready with BAA available.

Sources:
- https://platform.claude.com/docs/en/manage-claude/compliance-api
- https://trust.anthropic.com/
- https://www.anthropic.com/news/anthropic-achieves-iso-42001-certification-for-responsible-ai

---

## 3. Microsoft 365 Copilot

**Summary.** M365 Copilot logs flow through the standard Microsoft Purview unified audit log. Retention is best-in-class on paper (configurable up to 10 years on Premium), and tamper-resistance can be layered on via Azure immutable blob storage. But Microsoft explicitly captures **metadata only** in the unified audit log — prompts and responses are not recorded there. To get actual content, an admin must use eDiscovery (Purview/Vault-style) tools or DSPM for AI.

- **A. Tamper evidence.** Microsoft Purview Audit itself does not claim cryptographic tamper-evidence on its log entries; protection is via retention policies and "Azure immutable blob storage" which "can preserve stored objects under time-based retention and legal hold configurations" (i.e., WORM, but at the storage tier — customer-configurable, not enabled by default).
- **B. Signature scheme.** No public documentation found of per-entry signatures.
- **C. Retention.** Standard Audit (M365 E3+): 90-day retention. Audit (Premium) (E5/A5/G5 or add-on): 1-year default, configurable up to 10 years via custom audit log retention policies. Pay-as-you-go AI app logs: 180 days.
- **D. Replayability.** **Partial — and this is the headline limitation.** The unified audit log captures the *occurrence* of Copilot interactions, references to files accessed, sensitivity labels — but explicitly does **not** capture prompt or response text. Documented: "doesn't record the actual user prompts or responses … by design, for privacy and security reasons, exactly how the audit log does not capture the subject line or body of an email." To reconstruct an interaction the customer must use eDiscovery on the Copilot interaction history (separate surface).
- **E. External anchoring.** No public documentation found (Azure immutable blob storage is in-tenant, not externally anchored).
- **F. Customer/auditor access.** Yes — Purview portal, Office 365 Management Activity API, SIEM streaming. Customers fully control retention policies and export.
- **G. Standards compliance.** Microsoft Security Copilot and Azure AI Foundry achieved ISO/IEC 42001:2023. M365 Copilot inherits the broad Microsoft 365 compliance posture (SOC 2, ISO 27001, etc.).

Sources:
- https://learn.microsoft.com/en-us/purview/audit-copilot
- https://learn.microsoft.com/en-us/purview/audit-solutions-overview

---

## 4. GitHub Copilot

**Summary.** Audit logs cover enterprise admin/policy events well (and stream to SIEMs), but **prompts and suggestions are explicitly not logged** by the platform. There's no replay surface at all for what a Copilot user actually asked or what the model produced — by stated design.

- **A. Tamper evidence.** No public documentation of cryptographic tamper-evidence. Standard GitHub audit log behaviour applies.
- **B. Signature scheme.** No public documentation found.
- **C. Retention.** "The audit log retains events for the last 180 days." For long-term retention, GitHub explicitly recommends streaming to a SIEM.
- **D. Replayability.** **Effectively none for inference content.** "Microsoft does not show or log the actual prompt text for privacy reasons; only usage counts are visible to admins. … the audit log does not include client session data, such as the prompts a user sends to Copilot locally. No request or response is stored at the proxy or LLM end."
- **E. External anchoring.** No public documentation found.
- **F. Customer/auditor access.** Yes for the events that *are* logged: enterprise audit log UI, REST API, JSON/CSV export, multi-endpoint streaming.
- **G. Standards compliance.** Inherits GitHub Enterprise's SOC 2 / ISO 27001 posture. No public reference to ISO 42001 specifically for Copilot.

Sources:
- https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-for-enterprise/review-audit-logs
- https://github.com/orgs/community/discussions/120745

---

## 5. Google Gemini (Workspace / Enterprise)

**Summary.** Mature integration with Google Workspace's existing audit machinery — Admin console, Reporting API, security & audit investigation tools, Cloud Audit Logs for Gemini Enterprise on GCP. Like Microsoft, Google captures interaction metadata but **not prompt content** in the audit log itself; actual prompts and responses live in Google Vault for eDiscovery.

- **A. Tamper evidence.** No public documentation of cryptographic chaining on the audit log entries themselves.
- **B. Signature scheme.** No public documentation found.
- **C. Retention.** Gemini in Workspace apps logs: rolling **180-day** history. Cloud Audit Logs for Gemini Enterprise: Admin Activity logs retained 400 days by default per Cloud Logging defaults; Data Access logs retained 30 days (configurable up to 10 years via Log Router sinks).
- **D. Replayability.** Metadata-rich but content-light: "logs contain no actual prompt content—only metadata about interactions." For prompt and response content, admins must "leverage Vault to search and export relevant prompts and responses from the Gemini app."
- **E. External anchoring.** No public documentation found.
- **F. Customer/auditor access.** Yes — Admin console audit & investigation tool, Reporting API (Admin SDK), Cloud Logging exports for Gemini Enterprise.
- **G. Standards compliance.** Inherits Google Cloud / Workspace compliance posture (SOC 2, ISO 27001). Google Cloud has been pursuing ISO 42001; coverage specific to Gemini in Workspace not surfaced in public docs.

Sources:
- https://support.google.com/a/answer/14521388
- https://workspaceupdates.googleblog.com/2025/07/gemini-audit-logs-reporting-api-audit-and-security-invesitgation-tools.html

---

## 6. Salesforce Einstein / Agentforce

**Summary.** Salesforce has the most explicit per-interaction logging surface of the major incumbents: the Einstein Trust Layer audit trail captures original prompt, masked prompt, the unfiltered LLM response, toxicity scores, user feedback, and any user-modified output — all written into Data Cloud. This is essentially replay-grade. But it's metered (Data Cloud is a separately licensed product), and there's no public claim of cryptographic tamper evidence — these are normal Data Cloud DMOs (data model objects).

- **A. Tamper evidence.** No public documentation of hash-chained or cryptographically tamper-evident audit records. Audit data is stored in Data Cloud as standard DMOs; admins can delete records: "Data stored in Data Cloud can be deleted, but careful management is necessary to avoid unintentionally removing critical audit information."
- **B. Signature scheme.** No public documentation found.
- **C. Retention.** Setup Audit Trail: 180 days, non-extensible. Einstein generative AI audit data: retained per Data Cloud retention configuration (customer-controlled).
- **D. Replayability.** **The strongest replay surface among the incumbents.** Captures: original prompt, masked prompt, "the unfiltered response," toxicity scores, user feedback (accept/reject), and any modifications a user made to the generation before using it. "Every prompt, every response, and every piece of user feedback gets logged and stored securely within Salesforce Data Cloud."
- **E. External anchoring.** No public documentation found.
- **F. Customer/auditor access.** Yes — Data Cloud is the customer's tenant; standard Data Cloud query/export tools apply. Requires separate Data Cloud licensing.
- **G. Standards compliance.** Salesforce holds SOC 2, ISO 27001/27017/27018, ISO 27701. Public ISO 42001 status for Einstein/Agentforce was not confirmed.

Sources:
- https://help.salesforce.com/s/articleView?id=ai.generative_ai_audit_trail.htm
- https://trailhead.salesforce.com/content/learn/modules/the-einstein-trust-layer/

---

## 7. Aigentsphere (Australia)

**Summary.** Australian AI-agent governance startup (seed-stage, AUD 4M from Main Sequence Ventures, May 2026). Public marketing claims "audit trails," "full observability with traces, sessions, prompts, datasets," and pre-built compliance templates for GDPR, EU AI Act, ISO 42001, NIST AI RMF, ISO 27001, SOX. As a governance overlay (not a model provider), it sits *above* the AI vendors and aggregates their telemetry. No public technical documentation of the underlying audit-log integrity mechanism could be found — claims are marketing-page level only. Scored as "claims unverifiable from public materials" rather than on equal evidentiary footing with incumbents.

Sources:
- https://www.aigentsphere.com/
- https://www.startupdaily.net/topic/funding/ai-governance-startup-pockets-4-million-seed-round/

---

## Cross-cutting observations

### Reference standard for context: IETF AAT draft

The IETF draft `draft-sharif-agent-audit-trail-00` (March 2026) is the most concrete public specification of what a "good" AI conduct record should look like. It mandates:

- SHA-256 hash chaining per RFC 8785 canonical JSON
- Optional ECDSA P-256 signatures per record (Base64url encoded per RFC 4648 §5)
- Mandatory fields: agent identity, action classification, outcome, trust level, session linkage
- Records must be monotonically time-ordered within a session
- Explicit mapping to EU AI Act Article 12 logging requirements, SOC 2 TSC, ISO/IEC 42001, PCI DSS v4.0.1

**None of the seven vendors above publicly claim AAT compliance.** This is expected — the draft is two months old — but it sets a useful yardstick.

Source: https://datatracker.ietf.org/doc/html/draft-sharif-agent-audit-trail-00

## Key surprises

1. **No major vendor publicly claims cryptographic tamper-evidence on their AI audit logs.** All seven describe their logs as "immutable" or "append-only," but none publicly document hash chaining, Merkle structures, or per-entry signatures on the *contents* of the audit log. The weakest dimension across the industry — and the easiest one for a new entrant to differentiate on.
2. **Replayability splits the field cleanly into two camps.** Content-replayable: Anthropic, OpenAI ChatGPT Enterprise, Salesforce. Metadata-only by design: Microsoft 365 Copilot, Google Gemini, GitHub Copilot.
3. **GitHub Copilot is the weakest on replay despite being the most "auditable-feeling" product.**
4. **Salesforce has the most thorough per-interaction capture of the incumbents** — gated behind Data Cloud licensing and opt-in setting.
5. **Anthropic's six-year retention on the Activity Feed is an outlier** — most peers default to 30 to 180 days.
6. **OpenAI's 30-day retention is surprisingly short** — they externalise long-term retention to the customer.
7. **External anchoring (blockchain / third-party notary / independent WORM) is universally absent.**
8. **Aigentsphere's marketing claims are broad but unverifiable from public sources.**
9. **ISO 42001 is becoming the de facto AI-governance signal.**
10. **No vendor references the IETF AAT draft.**
