# TigerWatch v3 → v4 audit and repair report

**v5 update:** The historical v3/v4 audit below is retained. The current release
adds natural-language/multi-target detection, task routing, text/box outputs,
bounded local video/camera sessions, temporary box tracking, a private setup
wizard and free-plan guards. See [the v5 architecture/change record](docs/ARCHITECTURE_V5.md)
and [current test evidence](TEST_RESULTS.md). Old counts describe the earlier run.

New defects addressed during v5 work: cache/queue decisions needed target
namespaces; multi-target alerts needed the actual matching query labels; temporal
claims needed an explicit still-image override; generated box/schema values
needed strict validation; model thinking settings differ (3.8 rejects `minimal`);
dotenv interpolation could alter literal query text; and optional video NumPy
needed a Python 3.11-compatible pin. The v5 tests cover these paths.

Reviewed 2026-10-25. The supplied archive contained ten files. Every file was
extracted and inspected: `main.py`, `tests/test_main.py`, `requirements.txt`,
`schema.sql`, `.env.example`, `.github/workflows/monitor.yml`, `.gitignore`,
`README.md`, `AUDIT_REPORT.md`, and `GEMINI_BUILD_PROMPT.md`. The original archive
was preserved outside the corrected working copy. [Original file hashes and
line inventory](docs/ORIGINAL_INVENTORY.md) identify the exact reviewed input.

The old suite initially could not import `requests` in the empty workspace.
After installing its declared dependencies, **all 16 original mocked tests
passed**. Passing that suite did not detect the permission, queue concurrency,
retry-cost or repeated-cursor problems below. It included no real tiger accuracy
test and no hosted API integration.

Official documentation was checked separately from code execution. See the
[dated API verification record](docs/API_VERIFICATION.md) and
[actual test results](TEST_RESULTS.md). No live Meta approval/token, Google key,
Telegram bot or hosted Supabase access was supplied.

## Severity-ranked findings and concrete changes

Severity reflects potential impact in this particular worker, not a claim that
every advisory has a reachable exploit. No proven credential compromise was found.

| ID / severity | Exact v3 defect or risk | v4 change and evidence |
| --- | --- | --- |
| H00 — High, external blocker | The original README implied broad public wildlife hashtag monitoring could be enabled by generic app permissions. The current Instagram Public Content Access feature has specific campaign/brand/audience/support/content-rights uses, requires business verification and App Review, and does not explicitly list generic wildlife surveillance. | Document the exact permitted-use constraint prominently in README, the API review and live checklist. Approval for this actual use is required; code cannot resolve an ineligible use case. Leave hashtag monitoring disabled if Meta declines it. [Official feature requirements](https://developers.facebook.com/docs/features-reference/instagram-public-content-access/). |
| H01 — High | `State.lookup` → `pending` → classify → `mark` was a check-then-act sequence with no claim or lease. Actions' workflow concurrency cannot coordinate local/independent runners. Two workers could classify and alert the same ID. | `store.py`, `schema.sql`: atomic claims, `FOR UPDATE SKIP LOCKED` in PostgreSQL, `BEGIN IMMEDIATE` in SQLite, unique media ID, random lease token and fenced heartbeats/saves. Executed competing-claim and stale-token tests on both databases. External calls still cannot provide transactional exactly-once semantics. |
| H02 — High | `process` retained no positive classification or per-child progress when Telegram failed or a carousel exhausted budget. Retrying the same photo spent another Gemini reservation and replayed earlier negative children. | `worker.py`: checkpoint every completed child and save positive result before notification. Retry delivery from saved positive. Tests cover carousel resume, alert budget and Telegram 429 without a second classification. |
| H03 — High | `Meta.carousel_media` performed `GET /{discovered-id}/children` for third-party discoveries. Business Discovery explicitly does not grant direct access to discovered media objects. It also inspected only five children. | `meta.py`: permitted `children` field expansion inside source queries, no direct third-party-media read. Bounded larger child expansion, persistent decisions, and incomplete-album review. Mocked second-child/missing-first/incomplete-album tests; live account child access remains unverified. |
| H04 — High | `Meta.hashtag_media` stopped when `after == previous_after`. The current official recent-media reference says the after cursor can remain identical across pages. This silently truncated available results. | `meta.py`: bounded pagination continues through repeated cursors while new IDs arrive and stops on repeated content/caps. Dedicated three-page repeated-cursor regression test. |
| H05 — High | `requirements.txt` required `Pillow>=11,<13`, excluding current 13.0 security fixes. The initial resolver selected 12.3.0; the actual advisory scan reported 37 known package advisories. `Image.open` ran unrestricted plugin detection before format filtering. | Pin Pillow 13.0.0 and limit decoder plugins to JPEG/PNG/WebP **at open time**. Verify byte/pixel/MIME/format limits before normalization. Final advisory scan is recorded in `TEST_RESULTS.md`; do not equate all package advisories with reachable worker exploits. [Official release](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html). |
| H06 — High | `SEND_PHOTO=true` was sufficient to upload any discovered positive; no runtime evidence/scope acknowledgement of re-sharing permission existed. Default `disable_web_page_preview=false` could still cause third-party previews in link mode. | `config.py`, `services.py`, `worker.py`: explicit rights acknowledgement plus exact licensed @accounts or media-ID allowlist, no broad hashtag license. Always disable link previews. Strip metadata and upload normalized bytes only. Rights outside the software remain the operator's responsibility. |
| H07 — High | Error handling could expose untrusted exception text: Gemini transport failures escaped to generic logging; Supabase requests could carry a service-role key in exception/library context. Meta query strings contained its token. | `net.py`, `errors.py`, CLI: token in Meta Authorization header, optional appsecret proof, generic stable provider codes, no upstream body/URL/traceback logging, handler redaction and quiet HTTP logs. Tests exercise transport errors, body echoes and bot-path redaction. |
| H08 — High | No safe distinction between confirmed Telegram rejection and an uncertain timeout. Photo fallback after a failed/unclear attempt could create an extra message, and retry always reclassified. | `worker.py`, `services.py`: validate `ok=true` + message ID, durable sending marker, hold uncertain delivery for manual review, and fallback to link only before any send. Manual retry of an uncertain send requires explicit duplicate-risk acknowledgement. Exactly-once delivery is not claimed. |
| M01 — Medium | `State.prune_pending` silently deleted candidates older than a fixed TTL. Other item failures retried every run without attempt count, retry time or dead-letter reason. A poison oldest item could consume repeated scans. | Durable pending/processing/retry/dead/review states, exponential backoff/jitter, failure counter, provider cooldowns and explicit `queue_expired` records. Quota deferrals do not consume failure attempts. Executed retry timing, dead-letter, expiry and persistence tests. |
| M02 — Medium | Only the first Business Discovery page was read. The docs provide nested before/after cursors but no next/previous URLs. | `Meta.business_media`: validated cursor in nested `media.after(...)`, bounded source/page/request caps. Tests cover missing-next pagination and grammar-injection attempts. |
| M03 — Medium | Source batches were accumulated before enqueue. An exception on a later page lost earlier fetched candidates from that source. | Commit each page before the next request. Executed later-page-outage regression proving the first page remains queued. |
| M04 — Medium | The 30-hashtag rolling restriction was documented but not enforced. Editing a list across runs could exceed it; cached IDs did not change Meta's accounting. | Atomic per-account/tag seven-day local windows persist across configuration changes. Tests cover 31st tag, repeated query not extending timer, expiry and different accounts. Meta's cross-app/account accounting remains authoritative. |
| M05 — Medium | Expired URLs were refreshed only if the post happened to reappear during normal discovery. No deliberate recovery existed; direct third-party media GET would be an unsupported shortcut. | On missing/403/404/410 image, bounded original-source rescan, ID match and re-download. No refresh through unsupported media access or CDN signature guessing. Tests cover successful source refresh and unrecoverable dead-letter behavior. |
| M06 — Medium | Daily Supabase AI reservation was atomic, but SQLite's SELECT-before-INSERT reservation was not protected by a write transaction from the start. No Telegram daily/run/pacing cap existed. | Both stores reserve counters atomically; SQLite starts with `BEGIN IMMEDIATE`. Shared per-resource UTC counters and pacing, per-run caps and provider cooldowns. Concurrent cap tests execute on SQLite and PostgreSQL. Use the same store across workers. |
| M07 — Medium | `--image` bypassed the persistent AI budget and sent Telegram alerts without a matching monitor-state reservation. | CLI image test now reserves AI usage and only classifies. Telegram diagnostic reserves alert usage. This is an intentional command behavior change documented in README. |
| M08 — Medium | JSON validation coerced scores with `float(...)`, accepting booleans and numeric strings; incomplete/blocked candidate structures could fail inconsistently. No output-token cap or response schema was supplied. | Strict boolean/finite numeric validation, exact result keys, `real_photo` field, JSON Schema request, finish-reason validation and 512-token output cap. Invalid/truncated responses receive retry/backoff, never a trusted negative. |
| M09 — Medium | CDN/permalink URL checks allowed nonstandard ports and some malformed authority/path forms. An invalid Content-Length escaped the intended media error handling. Decoder plugin selection happened too late. | `net.py`, `media.py`: HTTPS, standard port, no userinfo/control/backslash/fragment/trailing-dot host, allowlisted CDN on every hop, public DNS check, bounded reads, MIME-to-decoder agreement, no animation and fresh metadata-free JPEG. Tests include SSRF redirects, local DNS, large/mislabeled/broken content and redirect loops. |
| M10 — Medium | Gemini 401/403/429/5xx all stopped the run but had no persistent differentiated cooldown/backoff; generic per-item transport/JSON failures could retry rapidly on later runs. Meta GET retries could sleep on long Retry-After without a worker-wide request budget. | Explicit service/item errors, bounded Meta GET-only retries, persistent provider cooldowns, respect Retry-After and observed usage headers, cap requests including retries. Gemini and Telegram POSTs are never blindly retried by the HTTP adapter. |
| M11 — Medium | Round-robin fairness applied only after selecting a fixed oldest-first queue window. A busy source could fill that entire window and starve other sources. | Claims order by least recently claimed source across the eligible queue, then due/first-seen order; each claim changes durable source scheduling metadata. |
| M12 — Medium | Supabase/SQLite were weakly separated integration paths, and SQL/RLS had only a mocked quota-shape test. There was no real database contention or upgrade validation. | Common operation contract; service-only invoker RPC with empty search path and qualified tables; idempotent v3 import and database test suite. Actual local PostgreSQL migration, service-role, anon/authenticated access, claims and quotas executed. Hosted PostgREST still needs acceptance. |
| M13 — Medium | New models/actions/dependency ranges and workflow values were hard-coded without reproducible supply-chain/version checks. Schedules at 48/day risked consuming private-runner minutes, and configuration variables were incomplete. | Pin tested runtime versions and immutable action commits; all relevant runtime knobs mapped to Actions variables, credentials scoped to one step; hourly default and separate credential-free contribution CI. YAML passed actionlint. Python 3.11/Windows-wheel checks are recorded separately from real Windows execution. |
| M14 — Medium | v3 documentation's permissions were examples with ambiguous “user/Page token” language and omitted required Business Discovery scopes. Its older audit implied broad verified behavior from a narrow mock suite. | Exact per-endpoint Facebook User token/permission matrix with current official links; distinguish Page setup and Business Manager extras, App Review and live acceptance. No live-success claim. |
| L01 — Low | Code/CLI/schema banners still said v2, the audit mixed v1/v3 claims, and the rebuild prompt duplicated stale requirements. Contributor setup/testing was unclear. | v4 entrypoint/package, rewritten README/report/prompt, migration notes, security/contributor guides, PowerShell installer and offline demo. |
| L02 — Low | `.gitignore` missed SQLite WAL/SHM files and alternative `.env.*` files; those can retain queued signed URLs/secrets. | Ignore these files, preserve `.env.example`, and exclude runtime state/caches from the delivered ZIP. |

## Things deliberately retained after verification

- `v26.0` is an actual documented Graph version and remains configurable.
- `gemini-3.1-flash-lite` is a documented stable image-input/structured-output
  model. It was not changed merely because newer models exist.
- `timestamp` is supported by the current hashtag recent-media reference. Both
  Unix and ISO timestamp forms are accepted; an absent/invalid timestamp is not
  used to invent a location or identity.
- Official API-only access and link-first notifications remain the project model.
  No cookies, Instagram passwords, private-account access or bypasses were added.

## Defects discovered and fixed during this implementation

The expanded tests found a valid JSON `null` being rejected by the generic HTTP
parser (breaking empty Supabase claims/cache reads) and a PostgreSQL aggregate
column colliding with a PL/pgSQL variable (`n`). The parser now distinguishes
malformed JSON from a valid null, and the aggregate uses qualified columns.
Both failed tests were rerun successfully. A first caption-leak test also matched
the instruction word “captions”; it was corrected to use a private caption
sentinel so it tests actual content leakage. These are reported as development
findings, not falsely attributed to the supplied archive.

## Remaining limits and operational risks

1. **External access:** code cannot grant Meta App Review, token scopes, Page
   tasks, region/model access, rights or provider availability. No live provider
   integration was executed. Complete [the live checklist](docs/LIVE_CHECKLIST.md).
2. **Coverage:** only returned pages can be queued. High-volume feeds, cron gaps,
   unsupported videos, missing children, queue age and expired URLs can miss real
   tigers. There is no complete Instagram or historical recovery guarantee.
3. **Model validity:** mocks verify software decisions, not species accuracy,
   authenticity or calibration. Human evaluation is required; false negatives
   and false positives are possible. Review is private state, not an automatic
   human-approval publishing interface.
4. **External side effects:** no distributed DB transaction can atomically commit
   a Gemini computation or Telegram send with its response. A crash before a saved
   AI result can repeat classification. A durable send marker holds uncertain
   alerts for review, trading automatic duplicates for possible delayed/missed
   delivery. Manual retries may duplicate an already accepted message.
5. **Cost/storage:** small defaults favor free-tier use, not high throughput.
   Counters cap reserved attempts, not dollars. Multiple independent stores or
   other apps add usage. A large source list can fill storage/dead letters despite
   a small AI budget; monitor counts/DB size and choose retention/volume accordingly.
6. **Secret lifecycle/privacy:** manual token renewal and access-withdrawal/data
   deletion remain operator duties. Original v3 backup tables are not scrubbed by
   v4 retention. Links/image backgrounds can expose locations despite metadata
   removal; choose restricted destinations and permitted content.
7. **Execution:** Linux tests, local PostgreSQL, PowerShell parsing, workflow lint
   and Windows wheel resolution are not a live Windows 11 desktop or GitHub
   deployment acceptance test. Workflow schedules and third-party services have
   no project-provided uptime/SLA.

No 100% production reliability, zero-cost guarantee, calibrated probability or
real Instagram success is claimed.


## v6 integration audit

See [severity-ranked v6 findings and exact component changes](docs/AUDIT_V6.md)
for public-profile queue integration, configurable watches, sale review, no-bot
operation and separate URL-only child-safety reporting. Current execution counts
are in [TEST_RESULTS.md](TEST_RESULTS.md); earlier dated results remain historical.


## v7 automation and control

See [v7 findings and exact fixes](docs/AUDIT_V7.md) for the local dashboard,
review feedback, assessment reuse, scheduling, atomic digests, monitor fencing
and operational diagnostics. Current test evidence is in TEST_RESULTS.md.


## v8 hardening and glass interface

See [exact v8 findings and fixes](docs/AUDIT_V8.md), the
[architecture and threat model](docs/ARCHITECTURE_V8.md), and current
[executed test evidence](TEST_RESULTS.md).
