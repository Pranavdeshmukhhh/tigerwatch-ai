# v7 implementation audit — 2026-10-26

The original archive audit and v6 findings remain in AUDIT_REPORT.md and
AUDIT_V6.md. This release adds local control and operational safeguards without
claiming live provider authorization, measured recognition accuracy or guaranteed
free availability.

| Severity | Finding | Correction |
| --- | --- | --- |
| High | A browser control surface could expose private links, credentials, state-changing actions or untrusted HTML. | Loopback-only standard-library server, launch tokens, strict Host/Origin/cross-site checks, bounded JSON, CSP, safe textContent rendering, no external assets/media/secret editor, sanitized failures. Known child-safety-blocked links are suppressed. |
| High | Concurrent workers could spend AI quota on the exact same normalized image. | Scoped SHA-256 assessment cache, strict response revalidation, fenced claims, atomic SQL/SQLite operations, TTL and capacity bounds. Sale-context assessments never reuse results. |
| High | Supabase's old counter constraint rejected the new daily-digest resource. | Complete idempotent v6 constraint/RPC migration plus real PostgreSQL regression, including actual DB transport to a mocked bot. |
| High | A per-query photograph_only=false could defeat sale mode's required physical-photo constraint. | Sale modes force photograph_only=true on each query as well as the parent target. |
| Medium | A failed alert followed by a digest could retry Telegram during its cooldown. | Digest checks persisted cooldown before any send reservation; tests cover cooldown expiry. |
| Medium | Reserving a daily digest before a full alert budget prevented all later opportunities despite no send. | Atomic combined digest/alert reservation; neither count increments when cap/pacing rejects it. Failed/uncertain actual send consumes the attempt to prevent duplicates. |
| Medium | Concurrent monitors could replace newer health state when an older run completed. | Scope-specific monitor leases and token-fenced completion records, with expired-run recovery. |
| Medium | Exclusion wording could add/remove sale intent or invent motion/segmentation requirements. | Planner/inferred sale cues use the positive description before the generated exclusion suffix. Tests cover both false additions and false removal. |
| Medium | Fixed three-hour staleness misrepresented a valid longer local schedule. | Dashboard passes expected cadence; summaries disclose the actual stale threshold. |
| Medium | An old SQLite DB relied on umask and could expose signed metadata to other local users. | POSIX 0600 mode before WAL and symlink refusal, with Windows inherited-ACL limitations documented. |
| Medium | Oldest-first processing could spend scarce free quota before discovering current matches. | Fair source turns, durable-progress priority, then newest discoveries; visible backlog age/expiry pressure, with no starvation/completeness claim. |
| Medium | Feedback and mock pass counts were easily confused with model accuracy. | Independent review feedback with no automatic retraining, plus explicit licensed local evaluation reporting precision/recall, abstention and coverage under shared budgets. |

New components: dashboard.py, rules.py, health.py, cache.py, evaluate.py and their
regression tests. Existing Worker/State/SQL/CLI/configuration/workflows are wired
to them; no separate paid web stack or GPU service is added. OPEN_DASHBOARD.cmd
provides Windows entry. Dependabot requests reviewable updates without auto-merging.

Real Chromium testing exercises the local dashboard and synthetic Instagram DOM,
not live Instagram. PostgreSQL testing uses a disposable local instance and mocked
provider traffic. No real Meta/Gemini/Telegram/hosted Supabase success, app approval,
Windows desktop run or production schedule is certified. See current executed
counts in TEST_RESULTS.md and owner checks in LIVE_CHECKLIST.md.
