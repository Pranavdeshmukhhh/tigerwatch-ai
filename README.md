# VisualWatch v8 — private glass dashboard

This is the corrected, extended TigerWatch project. Describe a visible target in
natural language, choose public Instagram profiles, and run a persistent,
budgeted image-monitoring pipeline. Change targets without editing Python.

**Windows: start with [START_HERE.md](START_HERE.md).** `START_PUBLIC.cmd` installs
and configures public browsing; `RUN_WATCH.cmd` runs your saved watch;
`CHANGE_WATCH.cmd` changes its profiles, targets and mode.



## v8: a smoother interface, tighter boundaries

A new glass-style dashboard adds soft curves, light/dark themes, responsive mobile
navigation, status/budget cards, clearer rule previews and a visible monitoring
pipeline. It uses system fonts and CSS gradients, without external assets, new
runtime dependencies, photo previews or paid UI hosting. Reduced motion,
reduced transparency and high-contrast preferences have dedicated fallbacks.
Unchanged inbox polling preserves keyboard focus and avoids rebuilding cards.

**Open the complete private launch link printed by OPEN_DASHBOARD.cmd.** A bare
`http://127.0.0.1:8765/` shows only a locked interface. The per-launch access key
is consumed from its fragment, removed from the address bar, and held only in
page memory. Reloading requires reopening the original terminal link. Restarting
the server rotates the key. Treat that link like a password; never share it.

Every dashboard API requires the key. Strict Host/Origin checks, request/connection
limits, safe response headers and strict JSON protect the local control boundary.
Known safety blocks now take precedence over earlier positive results throughout
delivery. Unreadable Telegram replies preserve uncertain-delivery review, and
foreign/malformed queue IDs are rejected. See the [v8 audit](docs/AUDIT_V8.md)
and [architecture/threat model](docs/ARCHITECTURE_V8.md).

This is an original glass-inspired interface, not an official Apple/iOS product.
It remains a single-device local tool. No audit or test can make an unhackable
promise: a compromised OS account, privileged extension or someone holding your
private launch link can defeat its intended boundary. Do not expose it publicly.

## Automation retained from v7

After private setup, double-click **OPEN_DASHBOARD.cmd**, then open the complete private link printed in the terminal (including its key). The local dashboard lets you:

- Edit profiles, targets, visual exclusions, thresholds and review modes.
- Preview the exact interpreted rules before saving; saving starts no collection.
- Run once or deliberately enable local periodic monitoring (15 minutes–24 hours).
- See budget remaining, backlog age, source cooldowns and completed/partial/failed
  runs, rather than confusing no matches with a broken monitor.
- Review link-only candidates and record correct/incorrect/uncertain feedback.
  Feedback does not retrain the model or automatically establish accuracy.

The queue spreads work across sources, resumes saved positives/child progress
first, then favors newer discoveries. Backlog pressure warns when the free budget
may be too small before queue expiry. Identical normalized images can reuse a
strictly validated assessment for seven days within the same watch/model/threshold
scope, with atomic leases preventing concurrent duplicate AI. Each source link
remains separate. Sales always require fresh context; similar images are not
reused. A bounded image download is still needed to calculate the fingerprint,
even when no fresh AI calls remain. There is no zero-bandwidth guarantee.

Optional daily Telegram health digests share the alert cap, respect provider
cooldowns and reserve their daily attempt atomically with an alert slot. Enable
`SEND_DAILY_DIGEST=true` only with an explicitly configured private bot. Sending
or uncertain delivery consumes the attempt to prevent duplicate messages; budget
or cooldown rejection does not. Private run summaries contain no post links.

```powershell
& .\.venv\Scripts\python.exe main.py --dashboard
& .\.venv\Scripts\python.exe main.py --watch watch.json --health
& .\.venv\Scripts\python.exe main.py --watch watch.json --feedback-id NUMERIC_ID --verdict correct
```

The dashboard binds to loopback only, uses launch-token/Host/Origin checks, loads
no media or external assets, and exposes no secret editor. Do not expose it to
the internet. Local scheduling stops when the app/computer closes; GitHub's
separate hourly workflow with Supabase still provides laptop-off operation.
Same-watch monitor leases prevent overlapping CLI/dashboard/cloud cycles; expired
leases permit recovery and token fencing protects newer health records.

Use the [v7 operations guide](docs/OPERATIONS_V7.md) for labeled quality evaluation,
migration, digests and recovery. The existing Instagram and local image/video
sources below remain supported. Broad website/RSS adapters, automatic model
training and automatic provider-account creation are not implemented in this
release. Weekly dependency-update PRs are configured, without automatic merging.

## Choose a source

| Source | What works | What you configure |
| --- | --- | --- |
| Public browser | Collects visible post/reel links from configured logged-out Instagram profile pages; queues them; inspects accessible post photos later. | Python, Chromium, a Gemini Free key for AI. Local SQLite and local review work without Meta, Telegram or Supabase credentials. |
| Official Meta API | Approved hashtag search/recent media and Business Discovery for eligible professional accounts. Existing TigerWatch behavior is preserved. | Authorized Facebook User token, linked professional account/Page, relevant permissions and Meta approval. |
| Local image/video/camera | Natural-language image matching, ordered video samples and temporary box tracking. | Gemini Free key; optional CPU video dependencies. The local computer must remain on for camera sessions. |

Public browsing is conditional: Instagram may return only a few posts, no image
metadata, a login wall, 403 or 429. The browser stops there. It does not log in,
import cookies, access private accounts, use stealth or bypass restrictions.
`--max-posts 200` is a collection ceiling, **not a guarantee of 200 accessible
posts**. Visibility is not permission for automated collection or AI processing;
use sources you are authorized to monitor and comply with provider terms.
The official API remains the supported approved integration.

## Custom targets and saved watches

```powershell
& .\.venv\Scripts\python.exe main.py --configure-watch watch.json
& .\.venv\Scripts\python.exe main.py --watch watch.json
& .\.venv\Scripts\python.exe main.py --watch watch.json --review --output review.json
```

The wizard accepts several descriptions separated by `;`, for example
`Pikachu; a red car; a person wearing a blue shirt; a sign reading STOP`.
Up to ten queries are evaluated together per image. Targets have individual
optional thresholds and photo constraints; scores are **uncalibrated estimates**.
Results can be uncertain or unsupported. No target catalogue or retraining step
is required, but arbitrary descriptions do not imply arbitrary capabilities.

One-off examples, after setup:

```powershell
& .\.venv\Scripts\python.exe main.py --plan --target 'Pikachu'
& .\.venv\Scripts\python.exe main.py --scan-profile YOUR_PROFILE --target 'a red car' --target 'a person wearing a blue shirt' --no-notify
& .\.venv\Scripts\python.exe main.py --image 'C:\Photos\sample.jpg' --target 'a sign reading STOP'
```

`--plan` makes no provider calls. Other image/monitoring commands require
processing rights, an eligible free key and available budget. Watches are private
JSON files containing profiles and queries, with no credentials. `.env` stores
credentials locally. A changed query/model/threshold gets its own decision scope;
all scopes share daily usage limits. Explicit repeat queries therefore do not
silently reuse unrelated old decisions or reset spending counters.

For environment/GitHub configuration, use `TARGET_DESCRIPTION` or `TARGETS_JSON`:

```dotenv
TARGETS_JSON='[{"description":"Pikachu","threshold":0.8},{"description":"a red car","threshold":0.9}]'
GEMINI_MODEL=auto
```

`TARGETS_JSON` takes precedence. Each description is 1–300 characters. Omit both
settings to retain the original living-tiger photograph target. Custom targets
permit drawings/fictional depictions unless `photograph_only` is true.

## Sale-review modes

Choose `wildlife_sales` or `sale_review` in the wizard, or use:

```powershell
& .\.venv\Scripts\python.exe main.py --scan-profile YOUR_AUTHORIZED_PROFILE --target 'tiger skin or another visible tiger body part' --mode wildlife_sales --no-notify
& .\.venv\Scripts\python.exe main.py --scan-profile YOUR_AUTHORIZED_PROFILE --target 'a bicycle' --mode sale_review --no-notify
```

These modes require both a visual product match and sale intent. The model can
read visible offer text; caption context is reduced to fixed categorical offer,
price-present, contact-offer and awareness/negation signals. Raw captions,
contacts, prices and coordinates are not persisted or sent as prompt context.
Explicit awareness/negation signals veto automatic sale matches. This English
heuristic can miss other languages, slang or sarcasm.

Candidates stay in private human review. Alerts say authenticity and legality
are unverified and always contain links rather than re-shared photos. No result
proves a product is genuine, a protected species is present, an offence occurred,
or an account owner committed a crime. No automatic reports, public accusations
or seller contact are implemented. Local no-notify mode requires no bot.

## Suspected child exploitation: reference-only reporting

This application does **not** search for, download, classify, store or forward
suspected child sexual abuse material. Explicit child-exploitation visual queries
are refused. Known suspicious caption signals stop media fetching; this is a
best-effort text guard, not an abuse detector or a guarantee about unseen media.
An ordinary child appearing in a video is not evidence of exploitation.

For an already-known suspicious Instagram URL, the separate offline casebook
records only its canonical reference and your manual status:

```powershell
& .\.venv\Scripts\python.exe main.py --report-url 'https://www.instagram.com/p/REFERENCE/' --category child_safety
& .\.venv\Scripts\python.exe main.py --cases
& .\.venv\Scripts\python.exe main.py --export-cases review-references.json
```

These commands initialize no HTTP/AI/Telegram client and do not visit the URL.
They do not submit a report. Report through Instagram's in-app reporting,
[NCMEC CyberTipline](https://www.missingkids.org/gethelpnow/cybertipline), or the
[INHOPE national hotline directory](https://inhope.org/). Do not download,
screenshot, forward or upload suspected material to an AI service. The casebook
is local, not synced to Supabase, and needs your own retention/deletion process.

## Video, actions and tracking

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-video.txt
& .\.venv\Scripts\python.exe main.py --video 'C:\Clips\example.mp4' --target 'a moving vehicle' --sample-seconds 2 --max-samples 30
& .\.venv\Scripts\python.exe main.py --camera 0 --target 'a person wearing a blue shirt'
```

OpenCV decodes bounded local files (512 MB maximum) or an explicit camera index.
Up to three ordered normalized frames are sent per assessment. The same daily
AI budget applies. Approximate normalized boxes are linked by overlap within the
session; no face embeddings or persistent trajectories are stored. Results are
JSON lines, without Telegram delivery or saved video frames.

This is sampled monitoring, **not frame-rate semantic detection**. Camera
movement, occlusion and missed frames can break tracks. Motion cannot be proven
from an Instagram still, so explicit motion queries go to review. Instagram
videos/Reels are queued as unsupported, not downloaded. Exact segmentation masks,
face/name identification, sensitive-attribute inference and live Instagram video
tracking are unsupported. Boxes/OCR are model estimates, not validated geometry
or perfect transcripts. No single model is claimed to be universally best.

Automatic routing uses verified free-tier Gemini models: simple queries use
`gemini-3.5-flash-lite`; multiple targets, OCR, video and sale review use
`gemini-3.8-flash` with low thinking. `gemini-3.1-flash-lite` remains supported.
There is no paid fallback, GPU service or dedicated detection-model ensemble.

## Queue, limits and recovery

Visible links can be collected without an AI key or image downloads:

```powershell
& .\.venv\Scripts\python.exe main.py --collect-only --scan-profile YOUR_PROFILE --max-posts 200 --output public-posts.json
```

For the same watch/targets, later run normal monitoring or `--drain-only`.
Metadata is hydrated only when needed. Atomic lease-fenced claims, persistent
carousel-child results and saved positives prevent routine duplicate AI calls.
Rediscovering a link does not erase hydrated metadata or retry progress.
Telegram delivery with an unknown outcome is held for review, never blindly
resent. Exactly-once external delivery cannot be guaranteed.

CDN downloads enforce HTTPS/host/DNS/redirect checks, byte and pixel limits,
allowed image formats and EXIF removal. Expired URLs are refreshed only through
the original source when still accessible. Backoff, provider cooldowns and dead
letters preserve work through outages. Default caps are four AI attempts per run,
twenty per UTC day and ten Telegram alerts/day. These are application caps,
not provider quotas. Changing watches shares counters in the same store.

The default queue expires after 72 hours, with up to seven days configurable;
terminal IDs last 90 days. A large backlog can expire before a small free budget
processes it. Browser discovery is bounded and cannot prove complete carousel or
profile coverage. A carousel stops at its first accepted match to save calls;
it does not enumerate every occurrence of every query in later slides.

```powershell
& .\.venv\Scripts\python.exe main.py --watch watch.json --stats
& .\.venv\Scripts\python.exe main.py --watch watch.json --inspect-id NUMERIC_ID
& .\.venv\Scripts\python.exe main.py --watch watch.json --drain-only
```

## Free scheduled operation and privacy

Use Gemini Free with **billing disabled**, Supabase Free and standard runners in
a **public** GitHub repository. There is no paid fallback, paid broadcast,
Actions cache or artifact storage. The app cannot read billing status from an
API key: `FREE_PLANS_CONFIRMED` is your attestation. Provider eligibility,
quotas, service pauses and policy changes can prevent operation; unlimited,
uninterrupted zero-cost operation cannot be promised.

The supplied hourly workflow supports either source and persists state in
Supabase, allowing your laptop to be off. Browser access from a datacenter may
be blocked even when your local browser works. Scheduled jobs can be delayed or
disabled for inactivity. See [setup](START_HERE.md) and
[owner checklist](docs/LIVE_CHECKLIST.md); you create the repository yourself.

Image pixels, backgrounds and links can expose wildlife locations even after
metadata removal. Keep review files, destinations and bot membership private.
Review Google's Free-tier data-use terms before submitting third-party photos.
No live provider success, measured recognition accuracy or 100% reliability is
claimed. See [actual test results](TEST_RESULTS.md).

## Development and audit

- [Severity-ranked original audit and changes](AUDIT_REPORT.md)
- [v7 implementation audit and fixes](docs/AUDIT_V7.md)
- [v6 integration findings and fixes](docs/AUDIT_V6.md)
- [Official API contracts](docs/API_VERIFICATION.md)
- [v6 architecture](docs/ARCHITECTURE_V6.md)
- [Contributor guide](CONTRIBUTING.md)
- [Security](SECURITY.md)

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe main.py --demo
```

The demo and provider tests are simulated. Chromium tests render synthetic
Instagram pages; PostgreSQL tests use a disposable local server. External
acceptance with your own authorized accounts remains necessary.
