# Official API verification — 2026-10-25

Documentation verification is separate from account authorization. No authorized
Meta token or external service credentials were supplied for this review. The
checks below confirm documented contracts, not that your app will receive data.

Meta's pages returned HTTP 429 in the search/browser tool. The same official
documentation was successfully retrieved by HTTPS from this workspace, parsed,
and read. References were updated July/August 2026 where indicated. No third-party
API wrapper or scraping service is used as evidence.

## Meta contracts used

**Approval scope is a material constraint.** The official Instagram Public
Content Access feature page lists campaign/brand/audience, customer-support,
contest and digital-rights-related uses. It requires business verification and
successful App Review (and may require additional contracts). Generic wildlife
surveillance is not explicitly listed as an allowed use. A conservation campaign
must still fit Meta's permitted use and receive approval for its actual behavior;
this project does not establish that eligibility. If Meta does not approve your
proposed hashtag use, leave hashtag monitoring disabled. Business Discovery also
remains subject to its own permissions and Meta terms.

| Operation | Token, permissions, feature | Implementation |
| --- | --- | --- |
| `GET /ig_hashtag_search?user_id=...&q=...` | Facebook **User** access token for a user approved for tasks on the linked Page; `instagram_basic`; approved **Instagram Public Content Access** feature. For a Page role granted through Business Manager, the reference additionally requires one of `ads_management`, `business_management`, or `pages_read_engagement`. | `Meta.hashtag_media`; numeric ID cache, reserved local seven-day hashtag window. |
| `GET /{hashtag-id}/recent_media` | Same hashtag token/permissions/feature. | Fields: `id`, `media_type`, `media_url`, `permalink`, `timestamp`, nested `children`. Identity fields are not requested. v6 requests `caption` only for sale-review queries and minimizes it immediately. Maximum 50 media per page. |
| `GET /{your-ig-user-id}?fields=business_discovery.username(handle){media{...}}` | Facebook **User** token with `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`. For a Page role granted through Business Manager, the current Business Discovery reference also lists one of `ads_management` or `ads_read`. | Queries the caller's ID with field expansion; cursor added to the nested `media.after(...)` expression. Only eligible public Business/Creator targets; age-gated targets unavailable. |
| Linked account/Page setup | `pages_show_list` for `/me/accounts`, plus permissions for requested Page fields and the discovery operations above. | Manual official setup; `--check-access` reads the configured professional ID, `/me/permissions`, and one configured source of each kind. No Page token is substituted for the documented User token. |
| Carousel images | `children` is a supported recent-media field; Business Discovery allows nested media field expansion. Direct `GET /{third-party-media-id}` is **not** granted by discovery. | Children are requested in the original source query, without a separate media/children GET. Child fields are `id,media_type,media_url`. At most 50 fetched/20 inspected by default. Truncation, missing children or inaccessible images cannot create a complete negative. |
| Expired third-party image URL | Discovery does not grant new direct-media access. | Re-query the original approved source, within the same bounded pagination and quota limits, and match the returned post ID. No direct third-party ID read, HTML scraping, or guessed CDN signature refresh. |

The extra Business Manager permission requirements differ between Meta reference
pages. They are reproduced per endpoint rather than merged into a fictitious
universal permission. Confirm your exact Page-task assignment and permission
dependencies in the App Dashboard. Do not request advertising permissions unless
your documented account setup requires them.

The current recent-media reference **does support `timestamp`** and describes a
Unix timestamp. IG media responses may also contain an ISO-8601 timestamp; both
formats are handled. A historical unsupported-field report is not sufficient to
remove a field supported by the current reference.

### Restrictions enforced or explicitly bounded

- Thirty distinct hashtags per calling professional account in a rolling seven-day
  window. Fetching recent/top media counts even with a cached hashtag ID. Repeating
  a hashtag inside its current seven-day window does not extend that window.
  The local store reserves slots atomically across workers/configuration changes.
  **Other applications/stores using the same account are not visible to this local
  ledger**. Meta remains authoritative; its `recently_searched_hashtags` edge can
  be inspected by the account operator to reconcile external usage. Do not use
  multiple apps or accounts to evade limits.
- Hashtag recent media covers only the API's accessible last 24 hours, not a full
  historical feed. Results need not be chronological. A `MAX_POST_AGE_HOURS` value
  above 24 does not expand that Meta window.
- The hashtag after cursor can repeat on successive pages. Continue while pages
  contain new IDs; stop at configured bounds or repeated page contents. Ignore
  the untrusted `paging.next` URL as a request target.
- Business Discovery pagination may contain before/after cursors **without**
  next/previous URLs. Construct the next nested query from a validated cursor.
- Videos/Reels, Stories, private profiles and direct personal-account discovery
  are not implemented. Public hashtag results are limited to what Meta lawfully
  exposes; their authors' usernames are not inferred.
- Business Discovery/hashtag search use Platform rate limiting. The code does not
  invent a universal hourly allowance. It bounds requests including retries,
  observes usage headers, honors retry delays and persists provider cooldowns.
- `v26.0` exists in the official version table (released 2026-07-29). The version
  is configurable; upgrading requires another contract review and live check.
- App Review/Advanced Access, app mode, account tasks, business verification and
  token lifecycle are external requirements. A successful development-mode probe
  is not production approval. The worker cannot renew a revoked permission.

Official Meta references:

1. [Hashtag Search guide](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/hashtag-search)
2. [Hashtag Search reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-hashtag-search)
3. [Hashtag recent-media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media)
4. [Business Discovery guide](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery)
5. [Business Discovery reference and pagination](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery)
6. [Carousel children](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/children)
7. [Recently searched hashtags](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags)
8. [Facebook Login setup](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/get-started)
9. [Instagram overview and rate limiting](https://developers.facebook.com/docs/instagram-platform/overview)
10. [Graph versions](https://developers.facebook.com/docs/graph-api/changelog/versions)
11. [Graph pagination](https://developers.facebook.com/docs/graph-api/results)
12. [Instagram Public Content Access](https://developers.facebook.com/docs/features-reference/instagram-public-content-access/)

## Gemini

### v5 additions (same verification date)

The current official pricing lists free input/output tiers for
`gemini-3.1-flash-lite`, `gemini-3.5-flash-lite` and `gemini-3.8-flash`, subject to
project/region access and quota. The v5 allowlist includes these models only;
`auto` is a local routing setting, never a provider model ID. See
[pricing](https://ai.google.dev/gemini-api/docs/pricing),
[billing/free-tier downgrade](https://ai.google.dev/gemini-api/docs/billing),
and the [3.8 model contract](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
3.8 supports image/video inputs and structured output; its thinking configuration
accepts low/medium/high and rejects minimal. v5 selects low for this model.

The [image-understanding reference](https://ai.google.dev/gemini-api/docs/image-understanding)
documents normalized object boxes in `[ymin,xmin,ymax,xmax]` order on a 0–1000
scale. v5 validates these approximate boxes, accepts natural-language target sets
and visual text queries, and uses three ordered inline frames for local video.
It does not claim native Live API support for 3.8, precise masks or frame-rate
semantic recognition. Output is now bounded at 1536 tokens for multiple targets.
The earlier single-tiger adapter described below had a smaller output contract.

Account owners must disable Google billing/select Free plans themselves. API keys
do not expose billing state to this client. `FREE_PLANS_CONFIRMED` is an explicit
owner attestation, not a verified platform-enforced currency limit.

Google's [model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
lists `gemini-3.1-flash-lite` with image input and structured output support.
The REST `generateContent` adapter uses inline JPEG pixels, an API-key header,
`responseJsonSchema`, and a bounded output budget; see
[structured output](https://ai.google.dev/gemini-api/docs/structured-output).
No SDK with opaque automatic POST retries is used. Every attempted call needs an
atomic local reservation, including diagnostic image calls.

Gemini's [quota documentation](https://ai.google.dev/gemini-api/docs/rate-limits)
describes project/model-dependent quotas and Pacific-time daily resets. TigerWatch
uses **UTC** application counters; these are distinct from provider quotas.
401/403/404 and request-configuration errors stop the run; 429/5xx preserve the
queue and persist cooldowns. Invalid or incomplete classification JSON is retried
with backoff. A false result is not proof that an image contains no tiger, and a
high score is neither calibrated accuracy nor proof of photographic authenticity.

Review [pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[terms](https://ai.google.dev/gemini-api/terms) before submitting third-party
photos. The free tier may use content to improve Google products. Removing EXIF
does not remove sensitive information visible inside image pixels.

## Telegram, Supabase and GitHub

- [Telegram sendMessage/sendPhoto](https://core.telegram.org/bots/api) responses
  require `ok=true` **and** a positive integer message ID. Link previews are
  disabled; photo permission is checked before upload. Telegram has no caller-
  supplied idempotency key here. Unknown delivery goes to manual review.
- [Telegram rate guidance](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
  informs the default four-second shared send interval; `retry_after` overrides
  a shorter local delay. No paid broadcast mode is enabled.
- [Supabase database functions](https://supabase.com/docs/guides/database/functions)
  and [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
  support the service-only RPC. Security is invoker-based, the search path is
  empty, tables are qualified, and anon/authenticated execution is revoked.
  PostgreSQL tests verify these controls locally, not against a hosted project.
- [GitHub scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
  can be delayed or dropped, runs from the default branch, and public-repository
  schedules may be disabled after inactivity. This is periodic polling with no SLA.
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
  and [Supabase pricing](https://supabase.com/pricing) determine current free-tier
  eligibility/limits. Neither an uninterrupted free service nor zero costs are
  guaranteed by this project.


## v6 public-browser and reporting boundary

The optional Playwright source renders ordinary logged-out public profile/post
pages. It is separate from Meta's official API, grants no additional approval or
content rights, and stops at login/challenge/403/429. It does not invent Graph
endpoints, import account sessions or guarantee profile completeness. The
[Playwright network reference](https://playwright.dev/python/docs/network)
documents request routing used to block ordinary media loads and untrusted hosts.
Rendered-page tests use synthetic HTML, not live Instagram approval/access.

Sale review obtains caption only through the chosen accessible source, retains
categorical offer/negation signals rather than raw caption/contacts, and treats
every positive as unverified private review. Known suspected child-exploitation
queries are refused from media processing; separate local reference intake
initializes no HTTP client. Reporting resources were checked against the official
[NCMEC CyberTipline page](https://www.missingkids.org/gethelpnow/cybertipline)
and [INHOPE directory](https://inhope.org/) on 2026-10-25. No report is submitted
automatically and no suspected media is acquired by that path.
