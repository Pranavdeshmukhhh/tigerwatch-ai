# Start here — Windows 11 / v8

## Fewest steps: public profiles and local review

1. Install **Python 3.11+** from python.org, including the Windows `py` launcher.
2. Extract the ZIP to a normal writable folder. Double-click **START_PUBLIC.cmd**.
3. The private wizard asks for profiles, natural-language targets, a mode and your
   Gemini **Free** API key. Keep Google billing disabled. Confirm processing
   rights and provider terms. Keys are hidden and saved only in ignored `.env`.
4. Double-click **OPEN_DASHBOARD.cmd** and open its complete printed private link, including the access-key fragment. Preview and
   save your rules, then choose Run once or Start local automation.
   **RUN_WATCH.cmd** still runs a saved watch directly. **CHANGE_WATCH.cmd** opens
   the terminal editor; several target descriptions can be separated with `;`.

Local review uses SQLite. No Meta token, bot or Supabase account is needed for
this route. AI requires your own eligible Free key; code cannot create provider
accounts or approve terms for you. If Free is unavailable, pause; do not enable
paid billing. The app does not contain a local offline AI model.

PowerShell equivalents (no environment activation or execution-policy change):

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
& .\.venv\Scripts\python.exe main.py --setup-public
& .\.venv\Scripts\python.exe main.py --watch watch.json
& .\.venv\Scripts\python.exe main.py --watch watch.json --review --output review.json
```

Use `py -3` if another installed version is your Python 3.11+ interpreter.
`watch.json` contains profiles, targets and mode; `.env` holds the key and limits.
Keep both private. Local matches appear in the review export; Telegram is off by
default in this wizard. A blocked profile or an empty feed can produce no matches.

To collect links only, no AI key is needed:

```powershell
& .\.venv\Scripts\python.exe main.py --collect-only --scan-profile YOUR_PROFILE --max-posts 200 --output public-posts.json
```

The upper limit can be 1–500, but Instagram decides what is visible. It may expose
fewer than 100 links or demand login. The browser stops on access restrictions.
It is not a complete-history scraper or a workaround for Meta approval.
To process collected items later, use exactly the same watch/target configuration
and `--drain-only`; see `--plan` for its scope. New target scopes are independent.

## Optional Telegram alerts

Create a bot with BotFather, send it `/start`, and obtain its chat ID. Edit the
ignored `.env` locally:

```dotenv
ALERTS_ENABLED=true
TELEGRAM_BOT_TOKEN=YOUR_PRIVATE_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_PRIVATE_CHAT_ID
SEND_PHOTO=false
```

Then run `python main.py --test-telegram` using the virtual-environment Python.
This is a live message and uses the alert budget. Sale-review alerts always stay
link-only. General photo re-sharing also requires explicit source/post-specific
permission; do not turn it on merely because a post is public.

## Official Meta route

`START_HERE.cmd` or `python main.py --setup` opens the original official-API wizard.
It attempts to find your linked Instagram ID and bot chat ID from your authorized
credentials. You still need a Meta app, linked professional Instagram account and
Page, authorized **Facebook User** token, permissions and relevant App Review.
Hashtag public-content eligibility/business verification cannot be granted by
this code. See [the exact permission table](docs/API_VERIFICATION.md).

`--check-access` makes live source probes. In browser mode it collects visible
links; in Meta mode it probes permissions/metadata and uses API/hashtag quota.
It is not a live full-pipeline verification.

## Run while your laptop is off — GitHub Actions

You said you will create the repository yourself. Use a **public** dedicated
repository and standard runners. Upload project source at the repository root,
including `.github/workflows`, `.env.example`, and `schema.sql`.
**Never upload `.env`, watch files, databases or review exports.**

1. Create a **Supabase Free** project. Run all of `schema.sql` in SQL Editor as
   owner, including when upgrading from v6 or earlier. v7 adds feedback/cache tables and
   digest/health operations, and preserves existing queue IDs and usage. Stop old workers first.
2. GitHub repository Settings → Secrets and variables → Actions → Secrets:
   `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (legacy privileged
   service-role JWT). Add `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` only for alerts.
   Meta source additionally needs `META_ACCESS_TOKEN`/`IG_USER_ID` and optionally
   `META_APP_SECRET`.
3. Set Variables: `SOURCE_KIND=browser` or `meta`, `ACCOUNTS=YOUR_PROFILE`,
   `TARGET_DESCRIPTION=your description`, `GEMINI_MODEL=auto`,
   `ALERTS_ENABLED=false` for local-database-only review or `true` for Telegram,
   `FREE_PLANS_CONFIRMED=true`, `AI_ANALYSIS_RIGHTS_CONFIRMED=true` after checking
   these conditions. Browser mode requires **blank HASHTAGS**. Use `MONITOR_MODE`
   of `general`, `sale_review` or `wildlife_sales`. `TARGETS_JSON` supports multiple
   queries and takes precedence over the single description.
4. Open Actions → **VisualWatch free monitor** → Run workflow. Inspect its result
   and a later scheduled run. Default polling is hourly; no laptop is required.

Saved local watch files are not deployed automatically. GitHub uses Actions
Variables. To read private cloud review candidates locally, configure the same
Supabase project, target/model/threshold and use `--review --output review.json`.
The URL-only child-safety casebook stays local and is never deployed or synced.

Browser jobs install Chromium on each fresh runner; that takes time and download
bandwidth. Datacenter access may be blocked. In that case use approved Meta access
where available or permitted local observation; no access bypass is supplied.
Private-repository monitor and CI jobs intentionally skip to avoid paid minutes.
Supabase Free can pause, schedules can be delayed/disabled, and Free AI quotas
can vary. Do not expect guaranteed uninterrupted free hosting.

The optional `scripts/deploy_github.py OWNER/NAME` helper only runs when you invoke
it yourself after `gh auth login`. It refuses populated/private repositories,
sets secrets through stdin and never commits `.env`. Publishing was not performed
in this workspace. Manual repository setup is sufficient.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `py` not found | Install Python with the launcher; open a fresh terminal. |
| Chromium unavailable | Run `.venv\Scripts\python.exe -m playwright install chromium`. Linux also needs browser libraries; CI uses `install --with-deps`. |
| Login/challenge, 401/403, zero visible links | Stop. Check source permissions and logged-out availability. Do not add credentials/cookies or attempt evasion. No 100-post guarantee exists. |
| Browser 429 / cooldown | Wait for the recorded delay and reduce collection frequency. |
| Gemini authentication/permission or unavailable model | Check your Free key, project/region/model eligibility and current official docs. No paid fallback is enabled. |
| Daily budget exhausted | Leave billing disabled; wait for application/provider reset. UTC application limits differ from provider resets. |
| Queue has pending/retry items | Check `--stats`, `--inspect-id`, budgets and provider cooldowns. `--drain-only` skips initial discovery. |
| No Telegram message | Local setup disables alerts; review candidates may be uncertain or no match. Check explicit bot configuration and run `--test-telegram` if enabled. |
| Supabase operation failed | Re-run current `schema.sql`; verify project connectivity, Free project status, and the server-only service-role JWT. |
| Workflow skipped | This build requires a public repository for free runners. |
| Sensitive suspected child-abuse link | Use `--report-url ... --category child_safety` only; report via official channels without fetching, screenshotting or forwarding the material. |

No live Meta/Gemini/Telegram/hosted Supabase success or Windows desktop/camera
execution is claimed by this release. [TEST_RESULTS.md](TEST_RESULTS.md) records
what was actually executed and what remains for your accounts.


## v7 upgrade and daily use

Back up state and stop old workers before replacing source files. Local SQLite
migrates on open. For Supabase, run the entire updated `schema.sql` before using
v7. Review files, `.env` and existing `watch.json` remain private; do not upload
them to your public repository. The URL-only child-safety casebook stays separate.

The dashboard starts idle. You explicitly save a preview and enable a run. Local
automation needs the terminal and computer to remain on; Stop prevents future
cycles while active work finishes safely. An active CLI/cloud monitor for the same
watch is not duplicated. Changing rules requires stopping local automation first.

To enable a daily private health message, set `ALERTS_ENABLED=true` and
`SEND_DAILY_DIGEST=true` in `.env`, or the equivalent GitHub Variables after adding
bot secrets. The digest uses the same alert cap; a full budget can prevent it.
Daily limits are UTC, and summaries describe the current watch's queue while
usage counters cover the entire store. See `docs/OPERATIONS_V7.md` for details.


## v8 private launch links

Open the entire link printed in the dashboard terminal. Its trailing fragment is
the per-launch access key; a plain local URL stays locked. The key is removed
from the address bar and never saved in browser storage. Reopen the original
terminal link after a reload, or restart the dashboard for a new key. Pasting the
complete key link into an already-locked tab also unlocks it. Do not share that
link or include it in screenshots, issues or logs.

The UI supports light/dark mode, narrow screens, keyboard focus and operating
system reduced-motion/transparency/high-contrast preferences. Review candidates
remain link-only. No image/video is fetched just by opening the dashboard.

v8 uses the v7 Supabase schema unchanged. Existing v7 databases need no new SQL
for this update; older versions still require the complete current schema.sql.
The dashboard HTTP API is intentionally stricter: manual tools must provide the
launch key, and feedback includes the current scope. Use the bundled UI rather
than older dashboard pages. Native Windows/actual provider acceptance still
requires your own credentials and machine.
