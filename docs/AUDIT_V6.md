# v6 integration audit and exact changes — 2026-10-25

The original archive audit is retained in `AUDIT_REPORT.md`; v4/v5 evidence remains
in `docs/history`. This addendum covers the later public-browser collector,
custom watches, sale-review and reporting requirements. No production credentials
were supplied, and no provider access/approval is certified.

| Severity | Finding / before | Correction / remaining boundary |
| --- | --- | --- |
| Critical | A general image tool must not become an acquisition or redistribution system for suspected child sexual abuse material. The previous ordinary-photo path had no separate reference-only reporting workflow. | `safety.py` blocks explicit exploitation visual requests before discovery/download/AI; `cases.py` and early CLI dispatch record only canonical URLs locally, with no network client initialization, attachments or automatic reports. Caption preflight can stop known suspicious media. Text heuristics are English-focused and cannot certify unseen media safety. Ordinary child appearance is not evidence of abuse. |
| High | The separately delivered public collector saved links but never connected them to the persistent image queue. | `public_browser.py` implements source/refresh adapters, stable URL-derived IDs, per-scroll commits, on-demand hydration and strict network request filtering. It uses a normal logged-out context and stops at restrictions. No promise of live availability, approval bypass or 100+ actual Instagram results is made. |
| High | A tiger photograph match cannot establish a wildlife sale or an offence; automatically re-sharing suspected-sale photos risks privacy and false accusations. | `Query.require_sale`, explicit sale modes and per-query sale-intent results require pixels plus intent. Fixed minimized caption signals supplement visual offer text; awareness/negation cues veto sale confirmation. Results stay unverified review candidates; sale photos are never re-shared. Legality/authenticity/species provenance still require authorized expert review. |
| High | Rediscovery of a public link could replace hydrated retry metadata, wasting post visits and impairing carousel resume. | SQLite upsert and PostgreSQL RPC preserve hydrated pending/retry data against a new link-only stub. Per-child progress remains durable. Real PostgreSQL and SQLite regression tests cover the rule. |
| High | A source service failure during early post hydration could leave work processing until lease expiry. | Worker catches provider errors around the whole claimed item, releases/defer work, preserves attempts and records provider-specific cooldowns. Existing lease fencing still rejects stale writers. |
| Medium | Local matches could be delayed by Telegram caps/cooldowns despite notifications being disabled. | `Worker.notify` bypasses Telegram limits/cooldowns/reservations in local mode, persists a canonical review reference and needs no bot credentials. A regression test covers a zero alert cap plus active cooldown. |
| Medium | The previous mandatory Meta/bot setup prevented a minimal local public-browser run. | Conditional credential checks, `--setup-public`, three Windows launchers and `setup.ps1 -PublicBrowser -Configure` install only the relevant runtime and save a private watch. Actual AI still requires a user-owned eligible Free key and processing rights. |
| Medium | Changing profiles/queries required editing environment text and users could accidentally publish watch details. | Versioned exact-key bounded JSON watch format, private writes, hidden setup prompts, ignored runtime files and explicit cloud Variables documentation. Watches are not silently deployed. Windows uses inherited folder ACLs; keep the project in a private user folder. |
| Medium | Browser DOM and caption context are untrusted and can contain signed URLs, personal contacts or prompt instructions. | Bounded extraction, canonical post validation, CDN allowlist, categorized offer cues only, strict structured outputs, no raw caption/contacts/prices/location storage and no raw provider exception text. Known caption safeguards precede image fetching. |
| High | A new browser dependency pin (`pyee` 14) required Python 3.12 and broke the advertised Python 3.11 install. | Windows wheel resolution caught the mismatch. Pin changed to compatible `pyee==13.0.1`, followed by installation, rendered-browser regression and advisory checks. |
| Medium | Browser dependencies, initial installation and cloud source choice were absent from workflows. | Pinned optional Playwright requirements, conditional Chromium installation, mapped source/mode/alert/bounds Variables and synthetic rendered-page CI checks. Existing public-only standard runners, no caches/artifacts, shared budgets and no paid fallback remain. Hosted execution is still an owner acceptance task. |
| Low | Setup/check-access text and migration documentation described only earlier versions. | Updated source-specific setup, current idempotent SQL migration, owner checklist, architecture, troubleshooting and explicit simulated/live distinctions. |

## Exact changed components

- `targets.py`, `config.py`: sale-aware query contract, safety validation, source
  selection, minimal credential requirements and bounded public-browser settings.
- `public_browser.py`: rendered public DOM discovery/hydration, guarded network,
  safe stop conditions, durable link-only queueing and incomplete-carousel policy.
- `watches.py`, `setup.py`, `cli.py`: saved watches, minimal hidden-key setup,
  profile/target/mode selection, collection-only and private review commands.
- `services.py`: isolated sale schema, minimized untrusted context, separate
  subject/offer decisions and forced link-only sale delivery.
- `worker.py`, `store.py`, `schema.sql`: hydration recovery, provider stop handling,
  dedup/progress preservation, service-only review listing and local review fixes.
- `safety.py`, `cases.py`: explicit query guard and entirely separate no-fetch
  local reference/status/export path.
- `START_PUBLIC.cmd`, `RUN_WATCH.cmd`, `CHANGE_WATCH.cmd`, `scripts/setup.ps1`,
  optional dependency pins and workflows: installation and deployment support.
- Tests: rendered Chromium pages, more than 100 synthetic links, blocked media,
  source outages, known unsafe-caption preflight, sale false positives, mixed
  targets, independent schemas, no-bot operation, watch parsing, private casebook,
  URL validation and PostgreSQL upsert/review isolation.

A final preview-identity guard rejects canonical metadata pointing to a profile or a different post before any image request. OCR routing now recognizes “reading” descriptions, and the prompt explicitly allows requested visual-text matching while still requiring subject pixels for object matches.

## Verification limits

Synthetic model replies establish software behavior, not recognition accuracy.
The 120-link browser check uses simulated Instagram pages in actual Chromium;
it is not a claim that Instagram exposed those links. Local PostgreSQL tests
exercise the actual migration/RPC, not hosted Supabase HTTP or RLS configuration
in a user's project. No live Meta/Gemini/Telegram transaction, GitHub deployment,
Windows desktop launch or camera test was performed with user credentials.
`TEST_RESULTS.md` contains the executed counts and dated advisory scan.
