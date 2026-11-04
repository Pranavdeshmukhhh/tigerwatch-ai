# v8 UI, architecture and security audit — 2026-10-26

This addendum covers the runnable v7 project and the v8 changes. Prior original
archive and version audits remain retained. No blanket security certification or
live provider authorization is claimed.

| Severity | Exact finding | Fix and regression evidence |
| --- | --- | --- |
| High | GET /api/session returned the dashboard launch token without authentication, allowing another local caller to obtain private API access. | Every API now requires the key. The owner receives a random fragment link; UI consumes/clears it and uses memory only. Unauthenticated session/state/unknown API requests fail without exposing data. |
| High | A saved positive could be notified before newer safety-blocked metadata was checked. | Worker checks known media_safety_block before saved positive delivery and rechecks after refresh. Tests assert no CDN/Gemini/Telegram request for these cases. |
| High | Unreadable oversized/invalid-length Telegram responses lost uncertain-delivery semantics and could permit unsafe retry. | Response-read errors retain Telegram provider and delivery-unknown state; worker holds the item for review without automatic resend. |
| Medium | Duplicate keys and NaN/Infinity/overflow floats were accepted in provider/model JSON, making decisions ambiguous. | Shared strict provider parsing and strict Gemini classification JSON refuse these inputs and preserve retry/review behavior. |
| Medium | HTTP duplicate security/framing headers, malformed lengths and unbounded handler creation weakened the local control boundary. | Singular-header validation, bounded strict UTF-8 JSON, timeouts, max12 handler/backlog slots, bounded request rates and actual socket-cap regression. |
| Medium | Non-ASCII token comparison could raise instead of cleanly denying access. | ASCII-bounded constant-time token validation fails closed; regression covers long/non-ASCII/forged tokens. |
| Medium | Feedback from an old tab could attach to the same numeric post in a newer watch scope. | Feedback carries/validates snapshot scope, with configuration selection and write held under the dashboard lock. |
| Medium | A preview could overwrite a watch changed in another editor before save. | Preview records a bounded file revision and save refuses an intervening change. This detects prior changes; it is not an OS-wide lock against malicious/uncooperative file writers. |
| Medium | A thread-start failure could leave a phantom running state; repeated schedule enable reset cadence. | Thread acceptance/start is serialized with close/save, failed startup rolls back, and repeated Start preserves an existing cadence. |
| Medium | Malformed prefixed IDs and foreign-scope RPC rows were insufficiently rejected. | State validates full physical/logical identifiers and rejects foreign-scope responses before inspection/review exposure. |
| Low | Inbox refresh rebuilt unchanged cards and could remove keyboard focus. | Unchanged review signatures preserve DOM, changed cards restore appropriate feedback focus and actual browser tests exercise the behavior. |
| Low | Pasting the private link into an already-locked tab used hash navigation without bootstrapping a new session. | Serialized hash-change recovery consumes valid keys, ignores navigation anchors and adds no persistent storage. |

## UI changes

Original self-contained glass-inspired assets in dashboard_assets.py replace the
flat interface: soft radii, translucent panels, pastel gradients, system fonts,
light/dark themes, responsive mobile dock, budget/status cards, pipeline view,
clear rule summaries and private review cards. Diagnostic JSON is optional rather
than the default main view. Transitions are short and bounded; reduced motion,
reduced transparency and forced-colors styles are provided. No external asset,
paid UI dependency or media preview is added. This is not an official Apple/iOS
implementation or an accessibility certification.

## Verification and remaining boundary

TEST_RESULTS.md records actual counts and commands. Browser checks use actual
Chromium and the loopback server, synthetic Instagram pages and mocked monitor
responses. Pipeline tests use mocked providers and real disposable PostgreSQL.
No live Meta/Gemini/Telegram/hosted Supabase, native Windows desktop or production
schedule was verified. See ARCHITECTURE_V8.md for OS/extension/key-holder and local
network limits. No software audit can promise that nobody will ever gain access.
