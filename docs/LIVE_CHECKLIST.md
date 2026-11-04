# Owner setup and live acceptance checklist

Choose a route in [START_HERE.md](../START_HERE.md). These boxes remain unchecked:
external accounts, consent, billing settings and approval require their owner.
No repository was published and no authorized live API token was available here.

## Minimum local public-browser monitoring

- [ ] Python 3.11+ and optional `requirements-browser.txt`/Chromium installed.
- [ ] Sources are authorized for your intended collection/processing; you accept
      Instagram may block logged-out automation and no bypass is supplied.
- [ ] Gemini Developer API Free key in `.env`, billing disabled, model/region
      eligible, processing rights and Free-tier data-use terms reviewed.
- [ ] `FREE_PLANS_CONFIRMED=true`, `AI_ANALYSIS_RIGHTS_CONFIRMED=true` only after
      checking; these are attestations, not automatic billing verification.
- [ ] Profiles and ordinary visual targets saved through `--setup-public` or
      `--configure-watch`. No name/face identity matching or abuse-media scanning.
- [ ] `ALERTS_ENABLED=false` for local review, or the optional bot configured below.
- [ ] Private folder/review destinations and a retention/deletion process chosen.

Link-only `--collect-only` needs no Gemini key. URL-only `--report-url` uses no
provider/network credentials. The casebook does not fetch/submit anything.

## Optional official Meta source

- [ ] App configured for **Instagram API with Facebook Login**.
- [ ] Your Business/Creator account linked to a Facebook Page; token owner has the
      required Page tasks and the querying numeric `IG_USER_ID` is known.
- [ ] Authorized Facebook **User** token in `META_ACCESS_TOKEN`; check token and
      data-access expiry privately in Meta's official tools.
- [ ] For hashtag endpoints: `instagram_basic`, approved **Instagram Public Content
      Access**, business verification and App Review for the actual permitted use.
      Generic wildlife surveillance is not automatically an approved use.
- [ ] For Business Discovery: `instagram_basic`, `instagram_manage_insights`,
      `pages_read_engagement`; eligible public professional target accounts only.
- [ ] `pages_show_list` for Page/account setup and endpoint-specific Business
      Manager role/dependency permissions from [the matrix](API_VERIFICATION.md).
- [ ] Any required Advanced Access, Live app mode, additional contracts and
      `META_APP_SECRET`/appsecret proof configured in Meta Dashboard.
- [ ] Small approved `HASHTAGS`/`ACCOUNTS`; reconcile any other applications' use
      of the same account's rolling hashtag allowance. No quota circumvention.

## Optional Telegram and free cloud scheduling

- [ ] Bot token/chat ID in private secrets, `/start` completed, correct destination
      permissions and restricted membership. Enable alerts explicitly.
- [ ] `SEND_PHOTO=false` unless general non-sale photos have documented precise
      account/post re-sharing permission. Sale review remains link-only.
- [ ] Supabase **Free** project, current whole `schema.sql` successfully applied,
      privileged legacy service-role JWT and URL in private secrets. Stop older
      workers before migration. Verify anon/authenticated roles cannot read RPC/data.
- [ ] Public dedicated GitHub repository; source at root; Actions enabled, standard
      runners only. Never commit `.env`, watch files, databases or review exports.
- [ ] Variables set for source/targets/mode/limits/rights, blank HASHTAGS in browser
      mode, and no paid model/service fallback. Cloud uses Variables, not local
      ignored watch JSON. Supabase is required for durable scheduled work.
- [ ] Provider dashboards confirm free eligibility; review delays, quota resets,
      Supabase pauses and GitHub inactivity/schedule behavior.
- [ ] Operator assigned token renewal, deletion requests, dead-letter review and
      failed workflow notifications. Casebook/reference files have separate
      retention and stay local.

## Acceptance with your authorized accounts

1. `--plan` makes no API calls. Check intended query/mode and current scope.
2. Use a small licensed, human-labeled positive/negative image set with `--image`
   within the budget. Include lookalikes/art/AI images and near misses. Evaluate
   false positives/negatives for your actual query; test counts do not prove accuracy.
3. Probe the chosen source using `--check-access`. A Meta probe uses metadata and
   hashtag quota; a browser probe collects visible links only. Check restrictions
   and visibility without trying to bypass them.
4. With rights/credentials configured, run the saved watch. Inspect `--stats`,
   `--inspect-id` and private `--review --output review.json`. Empty/no-match feeds
   need not produce an alert. Confirm source links, subject and sale evidence on
   permitted ordinary content; no classification establishes guilt/authenticity.
5. If enabled, run `--test-telegram` and check the destination/previews. Check a
   normal accepted match and repeat the run to confirm no routine duplicate AI/send.
6. Run the GitHub workflow manually, then confirm a scheduled run with the laptop
   off. Browser datacenter access may differ from local access. Local/cloud
   budgets only coordinate when using the same Supabase project.
7. In a disposable test store, test a low daily cap and retry. Never break real
   production credentials just to manufacture an outage. Offline failure coverage
   is already provided. Expired URLs can only recover if the original source
   still returns that post; inaccessible posts may dead-letter.
8. For video, install optional video requirements and assess your own local files
   before a camera session. Check track stability; sampled boxes are not identity
   or accurate speed measurements. Instagram video is unsupported.
9. For a known suspected child-exploitation link, use only the offline URL intake
   and official reporting channels. Do not download, screenshot or forward media;
   no Gemini, browser or Telegram workflow should be used for that task.

Record results privately without tokens, signed CDN URLs or wildlife locations.
Live access/approval, real model accuracy, hosted scheduling and Windows camera
execution remain external acceptance tasks. No 100% production reliability claim
is made.


## v7 additions

- [ ] Stop older workers and apply the updated whole schema.sql on Supabase.
- [ ] Preview and save dashboard rules; confirm its loopback-only address.
- [ ] Enable local automation deliberately; keep that computer on, or configure
      the separate GitHub workflow for laptop-off operation.
- [ ] If desired, enable SEND_DAILY_DIGEST only with a private authorized bot;
      verify one summary and its shared alert reservations.
- [ ] Evaluate ordinary licensed examples for your actual targets; inspect
      abstentions and false matches before changing thresholds.
- [ ] Keep private watch/review/benchmark files and databases out of GitHub.
