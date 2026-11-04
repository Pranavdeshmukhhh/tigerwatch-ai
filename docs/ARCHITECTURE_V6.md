# v6 architecture and extension points

The v5 natural-language/model/video architecture remains in ARCHITECTURE_V5.md.
This version adds source selection, private saved watches and review workflows.

```
Private watch / CLI / environment
          | target validation and safety routing
          +--> URL-only casebook (local; no network clients)
          |
          +--> Source adapter: approved Meta / normal public browser
                 | per-page durable discovery
                 v
             State: local SQLite / Supabase RPC
                 | atomic claims + lease fencing + shared budgets
                 v
             Worker: hydrate -> safety preflight -> safe CDN normalization
                 -> budgeted Gemini -> durable decision
                 -> local review or bounded Telegram link alert
```

`watches.py` reads/writes a versioned 32-KB-bounded JSON format with exact allowed
keys. It carries no secrets. `Config.with_mode` supplies general or sale-review
behavior. Query scope includes target text, model, thresholds and sale semantics;
daily counters remain global within one store.

`public_browser.py` implements the same `source`/`refresh` interface as `meta.py`.
It reads rendered anchors with Playwright and blocks normal image/video/font
requests, service workers, downloads, popups and off-allowlist requests. It creates
a fresh logged-out context, takes no credentials or imported session, and stops
at authentication challenges, 403/429 and configured bounds. Collection is normal
DOM browsing, not a private endpoint adapter. It persists stubs before scrolling.
A stable numeric URL hash is its queue ID. Hydration visits only a known queued
post, extracts bounded visible/OG metadata, minimizes caption signals and validates
CDN hosts and declared canonical post identity. It cannot certify complete carousel coverage. Profile/post DOM changes
require maintenance. It is not an alternative grant of permission to collect data.

`Worker` owns image download, persistent per-child progress, AI reservations and
decisions. Browser stubs cannot overwrite hydrated retry data. A service-wide
error before or during hydration releases/defer the lease and records cooldowns.
No-notify review is independent of Telegram budgets/credentials/cooldowns.

`services.py` retains the general response contract. Sale queries use a deep-copied
schema that requires per-query sale-intent status. The pixel subject match and
sale intent must both pass; explicit awareness/negation cues veto a sale match.
Model output cannot prove legality or authenticity. Sale results stay in review,
even after a Telegram alert, and photos are never redistributed for these modes.

`safety.py` refuses explicit child-exploitation media queries and minimizes offer
signals. Its English text guard is intentionally described as best-effort; it is
not a classifier and cannot guarantee recognition of ambiguous or unlabeled abuse.
`cases.py` records only canonical Instagram references/category/manual status in a
separate local SQLite file. CLI dispatch occurs before Config/HTTP/State creation.
No media attachments, URL visits, uploads or automatic authority submissions exist.

Extensions must preserve source boundaries, processing rights, query safety,
reservation-before-AI-call, lease fencing, retention and delivery uncertainty.
A dedicated OCR/detector backend or exact segmentation needs a real implementation
and acceptance tests. Never advertise it merely because a planner detected that
requirement. Session-only tracking cannot become identity recognition by adding
a persistent face embedding store. Do not add login/cookie import, access bypass,
quota evasion, automated suspected-CSAM acquisition or public accusations.
