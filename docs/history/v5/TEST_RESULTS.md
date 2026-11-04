# Executed v5 verification — 2026-10-25

| Check | Actual result | What it establishes |
| --- | --- | --- |
| Python 3.12 suite with local PostgreSQL 17 | **177 passed, 0 failed, 0 skipped** | Includes 165 mock/SQLite/OpenCV/helper cases and 12 real local PostgreSQL cases. [Terminal output](docs/evidence/pytest-python312.txt), [JUnit XML](docs/evidence/pytest-python312.xml). |
| Clean official Python 3.11 container | **165 passed, 0 failed, 12 skipped** | Optional PostgreSQL DSN absent in that container. Those 12 cases passed in the main run. Includes real local synthetic-video decoding. [Output](docs/evidence/python311-container.txt). |
| Affected setup/CLI/pipeline tests after final publisher/privacy hardening | **38 passed, 0 failed** | Unknown secret keys excluded from public variables; credentials never appear in command arguments; existing pipeline behavior retained. Followed by a full main-suite rerun. |
| Ruff / compile / CLI help / offline demo / query planner | **PASS** | Python syntax, selected lint checks, importable entrypoint and credential-free simulation/planning. |
| actionlint 1.7.12 | **PASS**, exit 0 | Both public-only workflows; pinned action references retained. No hosted workflow was launched here. |
| PowerShell 7.6.8 parser | **PASS** | Updated installer parsed on Linux; not Windows desktop execution. |
| Windows CPython 3.11 amd64 dependency resolution | **PASS**, nine runtime/video wheels | Core plus optional OpenCV/NumPy binaries resolved. [Wheel record](docs/evidence/windows-wheels.txt). Actual Windows installation/camera remains unverified. |
| pip-audit, pinned photo+video requirements | **0 known advisories in 9 runtime packages** | Dated [advisory result](docs/evidence/dependency-audit.json); not proof of security or future advisory absence. |
| Live Meta, Gemini, Telegram, hosted Supabase | **NOT RUN** | No approved app/provider credentials supplied. All provider responses are mocked. |
| Live recognition accuracy, OCR precision, camera performance | **NOT MEASURED** | Requires authorized live model access, licensed labeled images/clips and the user's hardware. No invented benchmark or calibrated probability. |
| GitHub repository creation/publication | **NOT PERFORMED** | You chose to handle the repository yourself. Publisher subprocess/API behavior is simulated in tests. |

Counts across Python versions are not summed as unique tests. The Python 3.11
run preceded the final small publisher-variable allowlist/privacy/default-routing
hardening; those affected paths and the entire suite were rerun under Python 3.12.
Remote CI additionally configures Windows and Python 3.13; those remote jobs are
not claimed as executed here. No Windows `.cmd` execution or physical webcam test
was available.

## New v5 coverage

- Custom descriptions without category selection: Pokémon, animals, vehicles,
  colors/shapes/products, visible clothing descriptions and visual text queries.
- Multiple targets in one image/request; independent thresholds; art/fiction
  without a real-photo restriction; alerts use the actual matched query labels.
- Target/model/threshold scope changes, independent claims/decisions, preserved
  original-tiger scope and daily allowance shared across target sets.
- Automatic free-model routing, documented 3.8 `thinkingLevel=low`, blocked paid
  models/modes, live requests blocked without free-plan attestation, private
  GitHub runtime blocked, and no hidden paid fallback.
- Movement not confirmed from a still photo; ordered multi-frame context;
  unavailable precise masks; safe targets continuing alongside unsupported ones.
- Strict per-query result/schema validation, malformed boxes, invalid thresholds,
  invalid JSON/IDs, and explicit identity/face-reference rejection paths.
- Real OpenCV decoding of a generated moving-square MJPG video, with mocked
  vision boxes and temporary overlap-based track IDs. This tests decoding/logic,
  not the provider's motion recognition or real-world tracking quality.
- Session-only IDs, no cross-query identity link, normalized displacement,
  network-video rejection, budget pause without an AI call and capture cleanup.
- Setup finds linked account/chat IDs from mocked official API responses,
  never prints secrets, quotes configuration safely and stops before requests
  without free-plan confirmation. Environment interpolation is disabled.
- Publisher uses stdin for secrets, public-only empty repositories, explicit
  source-file allowlist and only known public variable names. Unknown private
  `.env` keys cannot become public variables. All subprocesses are mocked.

## Preserved regression coverage

The original pipeline tests remain: positive/false tiger decisions, carousel
resume, first-child outage/second-child match, incomplete albums, bounded/repeated-
cursor pagination, Business Discovery nested cursors, first-page persistence,
expired URL recovery, duplicates, restart/backlog retention, retry/dead letters,
Meta/Gemini/Telegram outages/authentication, reservations/pacing, malicious CDN
redirects/local addresses, byte/pixel/MIME/format limits, EXIF removal, Telegram
uncertain-delivery review and permission-scoped photo uploads.

Real local PostgreSQL tests execute idempotent migration, old v3 import,
service-only permissions/RLS, competing claims/fencing, atomic daily reservations,
pacing, rolling hashtag windows, expiry, target-scope separation and the full
pipeline through a simulated PostgREST transport backed by actual SQL.

## Commands and history

```bash
python -m pip install -r requirements-dev.txt
TEST_POSTGRES_DSN='<disposable local DSN>' \
  python -m pytest -q -p no:cacheprovider --junitxml=docs/evidence/pytest-python312.xml
python -m ruff check .
python -m compileall -q main.py tigerwatch scripts tests
actionlint .github/workflows/*.yml
python main.py --demo
python main.py --plan --target Pikachu --target 'a moving vehicle'
pip-audit -r requirements-video.txt --format=json
python -m pip download -r requirements-video.txt --only-binary=:all: \
  --platform win_amd64 --python-version 311 --implementation cp --abi cp311
```

The clean container preserved the managed environment's CA/proxy and installed
the complete pinned dev/video dependencies. TLS verification was not disabled.
The SQL fixture uses a disposable local admin database and truncates TigerWatch
tables; never use a production DSN. Original v3 had 16 passing mocked tests after
dependency installation; v4 had 123, with raw historical output preserved in
`docs/history/`. v5 does not relabel those earlier runs as live verification.

Development failures were fixed and affected tests rerun: named-real-person
phrase filtering, a lint-only unused import, strict target/coordinate validation,
scope-aware SQL tests, unknown-secret variable publication and Python 3.11's NumPy
compatibility. Prior v4 null-JSON/PLpgSQL ambiguity fixes remain covered.
