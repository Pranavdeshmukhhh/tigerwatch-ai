# Executed v8 verification — 2026-10-26

| Check | Actual result | Scope |
| --- | --- | --- |
| Complete Python 3.12 suite | **464 passed, 0 failed, 0 skipped** | 26 PostgreSQL tests, 7 synthetic Instagram Chromium tests, 8 local-dashboard Chromium cases, one actual socket-limit test, and mocked-provider/unit/security tests. |
| Clean Python 3.11 container | **422 passed, 0 failed, 42 skipped** | 26 database cases skipped without DSN, 15 Chromium cases skipped without browser binaries, one Node syntax case skipped without Node. All 42 passed on the 3.12 host. The real socket-cap test also passed inside the clean container. |
| Dependency audit | **13 runtime packages, 0 known vulnerabilities** | Current core/browser/video pins on 2026-10-26. Advisory scans cannot prove absence of vulnerabilities. No runtime dependencies added for the glass UI. |
| Ruff / actionlint | **Pass** | Configured Python lint and both GitHub workflows. Hosted jobs were not deployed. |
| JavaScript syntax | **Pass with Node 24.19.0** | Self-contained same-origin asset parses; Chromium tests execute it under the real CSP. |
| PowerShell syntax | **Pass on Linux PowerShell 7.6.8** | Native Windows desktop/installer/CMD/camera execution remains unverified. |
| UI visual inspection | **Desktop light/dark and 390px mobile rendered and inspected** | Screenshots contain only synthetic local fixtures; no real provider data or images. This is not an Apple/iOS or WCAG certification. |
| Live providers | **Not run** | No authorized Meta/Gemini/Telegram/hosted Supabase credentials available. No app approval, measured visual accuracy or production scheduling success claimed. |

## Browser and access checks

Actual Chromium and BoundedDashboardServer tests exercise private launch-key
access, a locked bare URL, locked-tab hash recovery, key removal from the address
bar, absence of persistent browser credentials, watch preview/save, feedback,
run/schedule/stop controls and cross-origin rejection. The key is never present
in request URLs or rendered DOM. Reload deliberately requires the original link.

Four layout cases cover 390px/1440px light/dark themes without horizontal overflow
and with main controls at least44px tall. Preference checks exercise reduced
motion, reduced transparency and forced colors. Literal HTML targets remain text,
unsaved fields survive state refresh, and unchanged inbox polling preserves
keyboard focus. The separate actual-socket test proves excess connections are
closed after the configured simultaneous-handler limit is reached.

Wire-level tests use the real HTTP parser/handler on in-memory bytes to exercise
forged/non-ASCII/long tokens, all-API protection, DNS-rebinding/CSRF headers,
duplicate framing/security headers, JSON duplicates/non-finite values/oversized
integers, malformed/truncated bodies, read/write/auth limits, browser policy
headers, blocked project-file routes, stale feedback scopes, watch revision
checks, symlinks and thread/schedule guards. These are software checks, not a
penetration-test certification or denial-of-service immunity claim.

## Pipeline and database checks

The pipeline uses mocked Instagram/Gemini/Telegram/database HTTP responses and
synthetic images. It covers positive/negative matches, carousels, pagination,
retry/outage handling, persistence, expired URLs, duplicates, redirects,
authentication failures, budgets, cache fencing, sales review and abstentions.
New regressions require known safety blocks to override saved positives and
post-refresh delivery, reject ambiguous provider/model JSON, hold unreadable
Telegram responses as uncertain delivery, and reject malformed/foreign-scope IDs.

The 26 PostgreSQL tests run actual v7-compatible migration/RPC logic on a
throwaway PostgreSQL 17 server: role restrictions, queue/cache/monitor claims,
capacity/expiry, atomic budgets/digests, feedback and migrations. HTTP providers
remain mocked; this is not hosted Supabase verification. v8 changes no SQL schema.
The seven Instagram DOM cases use synthetic HTML, including 120-link collection;
they do not prove that a live Instagram profile exposes that many posts.

Mocks establish behavior, not model accuracy, authenticity, sale legality, OCR,
identity, safe locations or tracker precision. No suspected abuse content is
collected, downloaded, scanned or used as a test dataset. The existing offline
reference-only reporting path remains separate from media/AI/Telegram clients.

## Evidence

- [Full output](docs/evidence/pytest-v8-python312.txt) / [JUnit XML](docs/evidence/pytest-v8-python312.xml)
- [Clean Python 3.11 output](docs/evidence/v8-python311-container.txt)
- [Dependency audit](docs/evidence/v8-dependency-audit.json)
- [Ruff](docs/evidence/v8-ruff.txt), [actionlint](docs/evidence/v8-actionlint.txt), [PowerShell](docs/evidence/v8-powershell.txt)
- v7 report/full-suite evidence is retained in docs/history/v7/. Earlier history remains.
- Runtime pins are unchanged; previous Windows 3.11 x64 wheel evidence remains dated 2026-10-25, not represented as a new native Windows run.

## Reproduce

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
python -m ruff check .
python main.py --demo
```

For the complete suite also provide Node for its syntax case and a disposable
local TEST_POSTGRES_DSN, with browser system libraries where needed. Database
tests truncate project tables/create roles/create and drop a temporary database;
never use production. Sandboxed environments that disallow loopback/browser
processes may skip or block those integration checks; release execution used
approved local test access. See CONTRIBUTING.md and docs/LIVE_CHECKLIST.md.

Security assumes a trusted local OS/account/browser and private launch link.
A compromised device, privileged extension, unlocked authorized browser or key
holder remains outside the access boundary. Do not expose the server publicly.
No software can guarantee that nobody will ever gain access.
