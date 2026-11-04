# v7 operation, quality evaluation and recovery

## Local dashboard and cloud worker

Run `python main.py --dashboard` or `OPEN_DASHBOARD.cmd` after setup. Open the
printed loopback URL. The default is port 8765; `--port 8766` changes it. Keep the
app private on your machine; it is not a hosted website or multi-user login system.

The editor accepts up to ten descriptions, authorized profiles, visual exclusions,
threshold and photo constraint. Preview shows normalized descriptions, inferred
sale requirement, selected model, query scope and unsupported requirements before
saving. This uses deterministic rules/keyword hints, not a paid planning call or
an autonomous agent. Exclusions are appended as visible constraints, and cannot
add/remove the positive description's inferred sale intent. Ambiguous visual
requirements still need human judgement. Sale modes force photographs for every
query and disable image re-sharing.

Saving does not start work. Run once starts one background cycle. Local automation
is explicitly enabled at 15–1440-minute intervals; no overlapping local cycle is
started. Same-watch run leases also coordinate CLI/cloud cycles in a shared store.
Stop disables future cycles, while active work finishes within its existing
bounds. Closing the server does not abruptly kill an active delivery. The computer
must remain on. For laptop-off operation use the existing hourly public-repository
GitHub workflow and Supabase Free; local SQLite cannot coordinate remote workers.
Local dashboard rules remain in ignored watch JSON; GitHub uses Actions Variables.

## Review and cost visibility

The inbox contains unverified review candidates and already-alerted matches, with
matched query IDs/descriptions where available. Correct/incorrect/uncertain feedback
is recorded independently of queue status. It does not resend, retrain, adjust
thresholds or change previous model decisions. No media previews or downloads are
triggered by dashboard review. Known child-safety-blocked entries have no clickable
source link; use the separate offline reference/reporting process.

Health shows current queue counts, pending/due backlog, oldest age, UTC daily
reservations, cooldowns, feedback totals and last-run state. Empty successful runs
are distinct from partial, failed, interrupted/stale or never-run records.
The stale threshold is reported explicitly; the dashboard accounts for a longer
enabled local cadence. Health cannot detect your project's billing plan or grant
source access. A missing run can result from a closed laptop, disabled workflow,
expired credential or provider failure.

Scheduling gives each source turns, prioritizes saved positives/child progress,
then favors newer discoveries. It does not guarantee every old item is processed.
Backlog warnings are conservative pressure signals, not precise completion-time
predictions: carousels may need several calls and cache hits need none. Old work
can still expire at MAX_QUEUE_AGE_HOURS. Never increase paid usage to hide a backlog.

An exact SHA-256 of normalized JPEG bytes can reuse a validated general still-image
assessment for seven days, within the same target/model/threshold scope. Atomic
cache claims prevent concurrent fresh classifications. Sale context, video and
similar-but-different images do not reuse results. Source links and photo rights
remain independent. Hashes/decision metadata are private; pixels are not cached.
Up to 5000 entries per scope are bounded with eviction, and expired entries are
cleaned during maintenance. A miss still consumes a fresh reserved AI attempt.

## Daily health digests

`SEND_DAILY_DIGEST=true` is opt-in and requires alerts/bot credentials. Every
monitor cycle can attempt a private summary, at most one reserved send per UTC
calendar day/store. The reservation atomically consumes one shared alert slot and
one digest slot. A cooldown or budget/pacing rejection does not consume a digest
slot. Pacing can wait at most 60 seconds. Once a send is attempted, a timeout/error
consumes the attempt; uncertain delivery is never blindly repeated that day.

Digests contain only health/counts/warnings, not post URLs, captions or wildlife
locations. Counts are for the current watch; AI/alert reservations are global
within the store. Multiple watches share one daily digest slot. A daily digest is
not guaranteed if no worker runs, state is unavailable, credentials fail or the
alert cap is already exhausted. CLI `--send-digest` uses the same controls.

## Measure your actual query quality

Use a small licensed, ordinary image set with human labels. Do not create or
submit suspected child-abuse datasets, face-identification datasets or private
content. A benchmark is explicit and can submit pixels to Gemini Free under its
terms; it is not an offline model and consumes the shared AI budget.

Place `examples.json` beside its images (only local relative paths, no symlinks
or directory traversal). With one explicit query:

```json
{"examples":[
  {"path":"positive.jpg","expected":{"q1":true}},
  {"path":"negative.jpg","expected":{"q1":false}}
]}
```

```powershell
& .\.venv\Scripts\python.exe main.py --evaluate 'C:\MyLicensedExamples\examples.json' --target 'a red bicycle' --output evaluation-report.json
```

For several targets, provide a boolean for every q1..qN in the configured order.
Up to 100 examples/200KB manifest and 32MB normalized image batch are accepted;
the whole batch is validated before any AI reservation. Reports use example
indexes/query IDs, omit paths/descriptions/pixels, and distinguish precision,
recall, confusion counts and abstentions/coverage. Uncertain/unsupported results
are not silently counted as negatives. A small or biased sample does not establish
universal accuracy or calibrated probabilities. The default run/day caps can
leave examples unevaluated; the report identifies the limit rather than spending
more. Evaluation is an explicit assessment, not automatic training or model rollout.

## Recovery and maintenance

- Check --health and --stats before manually retrying an item. Respect provider
  cooldowns and review the stable error code. Login walls/403/429 are stop signals,
  not instructions to import cookies, rotate proxies or bypass restrictions.
- Keep the same persistent store for cloud/local budgets and deduplication.
- After a crash, leases expire; fenced updates stop stale writers from overwriting
  newer run/cache/queue ownership. Exactly-once external Telegram delivery cannot
  be guaranteed. Unknown delivery needs manual destination checking.
- Preserve processing-rights/re-sharing checks and the URL-only no-fetch casebook.
  No illegality, identity or authenticity is established by a match.
- Re-run current schema.sql on Supabase upgrades with older workers stopped.
  Existing queue IDs, target namespaces and daily usage are preserved.
- Dependabot configuration requests weekly dependency/action updates. Review the
  PR, run CI and the licensed benchmark as appropriate before merging. It does not
  auto-merge or deploy models. On prompt/response-contract changes invalidate or
  version the assessment cache; old results must not silently cross a new contract.
- Review SQLite/review/export folder ACLs on Windows. POSIX database mode is 0600,
  but local files are not encrypted. Cloud backups, exports and casebooks require
  their own retention/deletion process.

Broad website/RSS adapters, multi-language sale-intent guarantees, automatic
training, paid fallbacks, public dashboards and automatic authority submissions
are outside this release. Existing official Meta/public profile/local input
capabilities remain bounded by access, rights, quota and actual model performance.


## v8 private-link upgrade

The source/queue/cloud behavior remains as above. Open the complete private link
printed by the dashboard terminal, including its fragment key; a bare URL stays
locked. The key is memory-only, so reopen the original link after a reload.
Restart rotates it. Do not share it or expose the local server publicly. The
bundled v8 UI supplies stricter API authentication and feedback scopes. Existing
v7 SQL is unchanged. See ARCHITECTURE_V8.md for the precise security boundary.
