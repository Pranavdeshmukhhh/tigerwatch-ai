# Executed v7 verification — 2026-10-26

| Check | Actual result | Scope |
| --- | --- | --- |
| Full Python 3.12 suite | **380 passed, 0 failed, 0 skipped** | Includes 26 real PostgreSQL tests, 7 rendered synthetic Instagram tests, one actual local-dashboard Chromium test, and mocked-provider/unit/security tests. |
| Clean Python 3.11 Linux container | **346 passed, 0 failed, 34 skipped** | All available tests passed. The 26 database checks skipped without a DSN; 8 browser checks skipped without Chromium inside that separate container. All 34 passed on the 3.12 host above. |
| Runtime dependency audit | **13 packages, 0 known vulnerabilities** | Current pip-audit check on 2026-10-26, core/browser/video requirements. A dated advisory result, not a security guarantee. |
| Ruff / actionlint | **Pass** | Python lint and both GitHub workflows. Hosted deployment was not performed. |
| PowerShell parser | **Pass on Linux PowerShell 7.6.8** | Setup script syntax only; native Windows launchers/installer/desktop/camera remain owner acceptance. |
| Demo and rule preview | **Pass, no provider calls** | Synthetic image/AI/Telegram pipeline and deterministic editable rules. |
| Windows CPython 3.11 x64 wheels | **13 runtime packages resolved in v6** | Runtime pins unchanged in v7; no new third-party dashboard dependency. Previous dated wheel evidence is retained, not represented as native Windows execution. |
| Live Meta / Gemini / Telegram / hosted Supabase | **Not run** | No authorized provider credentials supplied; no production authorization, live accuracy or scheduling claim. |

## Browser and database evidence

The new dashboard test starts the actual loopback HTTP server and Chromium,
previews/saves a two-target watch, records inbox feedback, starts a fake monitoring
cycle, enables/stops local automation, and verifies cross-origin rejection and no
external media loads. Its monitor is deliberately mocked; it sends no bot message
or vision request. Other dashboard tests execute the real HTTP parser/handler over
in-memory wire bytes to check tokens, Host/Origin, cross-site requests, bounded
JSON, CSP, save confirmation, thread controls and private error behavior.

The seven Instagram browser tests render synthetic HTML through Playwright
routes. They cover 120-link collection, queue/vision integration, login walls,
partial-discovery persistence, access blocks, known safety preflight and wrong
canonical metadata. They do not establish access to any real Instagram profile.

The 26 PostgreSQL tests use a disposable PostgreSQL 17 instance. They exercise
idempotent migrations, real RPC SQL, service-only grants/RLS, concurrent claims,
shared budgets, cache leases/capacity/expiry, feedback isolation, digest migration,
atomic digest/alert reservation and fenced monitor ownership. One uses actual
PostgreSQL RPC logic through mocked HTTP transport to mocked Telegram; it is not
hosted Supabase or a real bot verification.

The complete mocked pipeline retains positive/negative detections, carousels,
pagination, retries/outages, queue persistence, expired URLs, duplicates,
malicious redirects, invalid provider data, authentication errors and exhausted
budgets. New cases cover exact-image reuse across separate links, no reuse of
sale context or different pixels, no extra AI reservation on cache hits, corrupt
cache rejection, private review feedback, labeled evaluation/abstentions and
all five final-review operational fixes listed in docs/AUDIT_V7.md.

The fixture images/decisions are synthetic. Passing tests do not measure visual
recognition, authenticity, sale legality, OCR or tracking accuracy. Benchmark
software is tested using fake model responses; the user's actual licensed sample
quality remains unmeasured. No suspected abuse material is collected or used.

## Raw results

- [Full output](docs/evidence/pytest-v7-python312.txt) and [JUnit XML](docs/evidence/pytest-v7-python312.xml)
- [Clean Python 3.11 output](docs/evidence/v7-python311-container.txt)
- [Current dependency audit](docs/evidence/v7-dependency-audit.json)
- [Ruff](docs/evidence/v7-ruff.txt), [actionlint](docs/evidence/v7-actionlint.txt), [PowerShell parser](docs/evidence/v7-powershell.txt)
- Previous v6 report/full-suite evidence: docs/history/v6/. Existing v5 history remains retained.
- Unchanged-runtime Windows wheel evidence: docs/evidence/windows-wheels.txt (2026-10-25).

## Reproduce

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
python -m ruff check .
python main.py --demo
```

For all 380 checks, install Linux browser system libraries when necessary and set
TEST_POSTGRES_DSN to a disposable local server as in CONTRIBUTING.md. Database
tests truncate project tables/create roles/create and drop a temporary database;
never use production. Without DSN, 26 tests skip. Without Chromium, 8 tests skip.
Native Windows and provider acceptance remain in docs/LIVE_CHECKLIST.md.
