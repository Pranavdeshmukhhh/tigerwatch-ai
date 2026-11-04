# Executed v6 verification — 2026-10-25

| Check | Actual result | What it establishes |
| --- | --- | --- |
| Python 3.12 full suite with local PostgreSQL 17 and Chromium | **245 passed, 0 failed, 0 skipped** | Includes 14 actual PostgreSQL tests, 7 rendered-browser tests and mocked provider/unit/security tests. |
| Clean Python 3.11 Linux container | **224 passed, 0 failed, 21 skipped** | Core/browser-policy/video/configuration code installs and executes on the advertised minimum version. Fourteen PostgreSQL tests skipped because no DSN was passed, seven rendered-page tests skipped because Chromium was not installed inside this separate container. Those tests passed on the 3.12 host above. |
| Windows CPython 3.11 x64 binary resolution | **13 runtime packages downloaded successfully** | Core + optional browser + optional video wheels resolve together. This is not Windows desktop execution. |
| Runtime dependency advisory scan | **13 dependencies, 0 known vulnerabilities** | `pip-audit` with core/video/browser requirements on this date; not a guarantee of no vulnerabilities. |
| Ruff | **Pass** | Configured lint rules pass. |
| GitHub workflow validation | **Pass, actionlint 1.7.12** | Both YAML workflow files validate. Hosted runs were not deployed here. |
| PowerShell parser | **Pass, PowerShell 7.6.8 on Linux** | `scripts/setup.ps1` parses. Windows `py`, installers, CMD launchers and camera still need user-machine acceptance. |
| Credential-free demo and planner | **Pass on Python 3.12 and clean 3.11** | Simulated queue/AI/Telegram behavior and no-network target planning. |
| Live Meta / Gemini / Telegram / hosted Supabase | **Not run** | No authorized user credentials or Meta approval available; no live integration success or recognition-accuracy claim. |

## What the tests cover

The complete pipeline uses mocked Instagram, Gemini, Telegram and database HTTP
responses, with both local SQLite and actual PostgreSQL-backed queue tests.
Coverage includes positive/negative matches, carousels, bounded/repeated-cursor
pagination, outages, retry/backoff, dead letters, persistence, expired URLs,
duplicates, lease fencing, concurrent claims and budgets, malicious redirects,
untrusted JSON, authentication errors, 429/5xx and daily budget exhaustion.

v6 adds ordinary public-browser link-to-queue-to-hydration-to-vision behavior,
120-link collection, blocked media/untrusted requests, login walls/403, partial
collection persistence, wrong canonical-post metadata, caption preflight,
sale-intent uncertainty, awareness false-positive veto, local no-bot review,
private saved watches, URL-only case dedup/status/export, and early reporting
CLI dispatch that forbids HTTP client creation. Real PostgreSQL regressions cover
hydrated metadata preservation and review-scope isolation.

**All Instagram pages in browser tests are synthetic HTML fulfilled locally by
Playwright routes in actual Chromium.** Collecting 120 synthetic links is not a
claim that a live profile exposed 120 posts. Gemini replies use synthetic decisions
and small generated images; these tests do not evaluate object recognition,
real-image authenticity, OCR accuracy, sale legitimacy or tracking precision.

The Windows resolution check found `pyee==14.0.0` required Python 3.12. It was
corrected to compatible `pyee==13.0.1`; the final wheel check, clean Python 3.11
installation, rendered-browser tests and advisory scan all use the corrected pin.
A local-review/Telegram-cooldown defect and an OCR routing/prompt ambiguity were
also corrected and regression-tested before final packaging.

## Raw evidence

- [Full suite output](docs/evidence/pytest-python312.txt) and [JUnit XML](docs/evidence/pytest-python312.xml)
- [Clean Python 3.11 run](docs/evidence/python311-container.txt)
- [Windows dependency resolution](docs/evidence/windows-wheels.txt)
- [Dependency audit JSON](docs/evidence/dependency-audit.json)
- [Ruff](docs/evidence/ruff.txt), [actionlint](docs/evidence/actionlint.txt), [PowerShell parser](docs/evidence/powershell.txt)
- Earlier v5 result report and full-suite evidence: `docs/history/v5/`.

## Reproduce

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
python -m ruff check .
python main.py --demo
```

For the complete 245-test run, set `TEST_POSTGRES_DSN` to a **disposable local**
PostgreSQL instance as shown in CONTRIBUTING.md. Tests truncate TigerWatch tables,
create roles and create/drop a temporary database; never use production. Without
a DSN the 14 PostgreSQL tests skip. Without Chromium the 7 rendered-page tests
skip. Linux installations may also need `playwright install --with-deps chromium`.
All tests must use synthetic/authorized ordinary material, never suspected abuse
media or actual provider tokens.

Provider acceptance, account permissions, free-plan eligibility, actual recognition
quality and unattended hosted operation remain owner checks in
[docs/LIVE_CHECKLIST.md](docs/LIVE_CHECKLIST.md). No 100% reliability claim is made.
