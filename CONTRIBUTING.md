# Contributing

The software is released under the [MIT License](LICENSE). This does not grant
rights to third-party Instagram photos or override provider terms.

v5 introduced `targets.py` (natural-language queries and planning), `video.py` (optional
local decoding/session tracking) and `setup.py` (private owner setup). The dev
requirements include optional OpenCV/NumPy so video tests execute. Keep the core
photo requirements small. Public-repository CI runs without production secrets;
private jobs are intentionally skipped to avoid paid runner usage.

Start with the credential-free demo and offline tests. You do not need Instagram,
Gemini, Telegram, Supabase, a GPU or a paid server to contribute to queue logic,
security, documentation and tests.

```bash
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python main.py --demo
```

Windows uses `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
Do not copy production secrets into test fixtures. Tests block real HTTP; mocked
classification is behavior testing, not an image-recognition benchmark.

The optional SQL tests need Docker/PostgreSQL. They **truncate TigerWatch tables,
create roles and create/drop a temporary database**. Use only a disposable local
instance, never a hosted production DSN:

```bash
docker run --rm --name tigerwatch-pg -e POSTGRES_PASSWORD=local-test-only \
  -p 127.0.0.1:55432:5432 -d postgres:17-alpine
# Wait until: docker exec tigerwatch-pg pg_isready
TEST_POSTGRES_DSN=postgresql://postgres:local-test-only@127.0.0.1:55432/postgres \
  .venv/bin/python -m pytest -q
docker stop tigerwatch-pg
```

PowerShell DSN form:

```powershell
$env:TEST_POSTGRES_DSN = 'postgresql://postgres:local-test-only@127.0.0.1:55432/postgres'
& .\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:TEST_POSTGRES_DSN
```

CI runs offline tests on Linux/Windows and Python 3.11/3.13 and a separate local
PostgreSQL job. Those are configured checks; the release report only claims
platforms/commands actually executed in the audit workspace.

When changing provider contracts, cite the current official endpoint reference,
add a contract/failure test and update `docs/API_VERIFICATION.md`. Do not add
undocumented endpoints, account passwords/cookies, private-profile access,
location extraction or quota bypasses. New image formats need a security review.

Keep changes small and describe the concrete before/after behavior and validation.
Update schema and SQLite semantics together. Preserve lease fencing, durable
positive/child results, reservation-before-call and delivery uncertainty handling.
Never enable production secrets on `pull_request_target` workflows that execute
untrusted contribution code. Review pinned dependency/action updates and rerun
the relevant tests. Use `pip-audit -r requirements.txt` to check current advisories;
the report is a time-specific advisory scan, not a security guarantee.

For a security issue, use private repository security reporting or contact the
maintainer privately. Include a minimal reproducer using fake credentials. Avoid
public real wildlife locations, original photos, private metadata or tokens.


## v6 adapters and tests

`public_browser.py` adds a normal DOM source adapter, `watches.py` adds private
saved configuration, and `cases.py` provides a separate no-network reference book.
Install `requirements-dev.txt` and `python -m playwright install chromium` for
rendered-page tests. On Linux install browser system dependencies as appropriate
(`python -m playwright install --with-deps chromium`). Without the browser, only
the seven rendered-page checks skip; network-policy and other unit tests still run.

Chromium tests fulfill synthetic Instagram pages with Playwright routes and no
live page access. The normal Requests HTTP client is blocked in the suite.
Do not replace these with real illegal-content samples or production credentials.
Add regression cases for SQLite and PostgreSQL when changing state semantics.
The URL-only reporting branch must continue to dispatch before HTTP/AI/browser
initialization and must never grow a media-fetch or auto-forward step.


## v7 development

See docs/OPERATIONS_V7.md and docs/AUDIT_V7.md. New modules implement the local
dashboard, deterministic rule preview, health records/digests, exact assessment
reuse and licensed sample evaluation. Real dashboard Chromium tests use a loopback
server and fake monitor, with no provider access. PostgreSQL CI runs both
tests/test_postgres.py and tests/test_postgres_v7.py. Keep SQLite/RPC behavior
aligned. Version/invalidate caches on prompt/contract changes, and never mistake
feedback counts or simulated results for real recognition accuracy. Dependabot
opens reviewable update PRs; no automatic merge/deployment is configured.


## v8 glass UI and access tests

Dashboard assets live in dashboard_assets.py and must remain CSP-compatible,
self-contained and safe-text-rendered. Every API requires a private fragment-link
key; never restore public session bootstrap or persist the key in browser storage.
Native browser tests use synthetic local data; no live provider accounts are needed.
Maintain reduced-motion/transparency/high-contrast fallbacks and scoped feedback.
The actual socket-cap test needs loopback permission; Node checks JS syntax.
The v7 database schema remains unchanged. See docs/AUDIT_V8.md and
docs/ARCHITECTURE_V8.md for exact findings and the trusted-local-device boundary.
