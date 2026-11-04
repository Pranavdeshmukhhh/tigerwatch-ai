# v5 architecture, constraints and extension points

## Preserved and corrected

`meta.py`, `media.py`, `store.py` and `schema.sql` preserve the audited v4 pipeline:
official Facebook Login discovery, nested carousel expansion, repeated-cursor
pagination, bounded trusted-CDN downloads, metadata minimization, fenced claims,
durable child/positive results, atomic shared reservations and dead letters.

The original architecture embedded one animal and a binary tiger response into
the prompt/worker. Its saved rejection applied to a post forever within retention,
even if the user wanted a different subject. It could not permit fictional art,
associate different target thresholds, localize targets or distinguish still
images from motion evidence. v5 addresses these limitations explicitly.

## Request-to-result flow

1. `targets.py` accepts one description or up to ten simultaneous `Query` values.
   `TARGETS_JSON` supports individual thresholds/photo constraints; `--target`
   offers repeatable command-line descriptions. Category hints are optional,
   retained for backward compatibility. Face references/identity matching have
   no configuration/API surface.
2. `plan_query` exposes explainable capability hints. Visual text requests route
   toward OCR-capable vision; temporal requirements need video. Precise mask
   requests are surfaced as unsupported. This is a small rule-based planner
   backed by semantic interpretation in the model, not an additional paid agent.
3. `services.select_model` chooses a documented free-tier model before inference.
   With `auto`, simple stills use 3.5 Flash-Lite; multi-target/text/temporal/video
   uses 3.8 Flash. Explicit supported free models are allowed. No probing of
   expensive models, hidden tools, grounding, paid failover or retries against a
   succession of quota pools occurs.
4. A single structured response returns `real_photo` and one entry per query ID:
   safety allowance, match, uncalibrated score, support state and up to five
   approximate normalized boxes. The validator requires exactly the configured
   query IDs, strict booleans/finite scores, supported states and safe box bounds.
   Missing/duplicate IDs or invalid coordinates are errors, not trusted negatives.
5. An aggregation step applies each query's threshold/photo rule, overrides motion
   from a still to `needs_video`, and overrides unavailable segmentation claims.
   Safe matching queries may alert even if another query is unsupported. Borderline
   or incomplete results go to review. A positive alert lists the queries actually
   matched, not merely the first configured query.
6. `worker.py` persists this result before Telegram delivery and persists negative
   child progress. `video.py` uses the same validator/reservations but emits local
   JSON rather than Instagram alerts. It supplies up to three ordered normalized
   images, with no original filename/caption/location in model context.

For cost control, an Instagram carousel stops at its first confirmed matching
photo and sends one post alert. All queries are evaluated on that photo, but
uninspected later children can contain additional target matches. Full per-album
enumeration is not claimed; incomplete/unavailable children cannot prove a full
negative. The default per-run budget bounds the number of inspected images.

## Persistent target scopes

The physical queue key is `scope:media-id`; the Python State interface still
accepts/returns the numeric Instagram media ID. Scope hashes the target set,
thresholds, photo constraints and model choice. Claims and statistics are scope-
filtered. Save/inspect/retry operations map logical IDs to their physical keys.

Old v3/v4 tiger records are adopted as `legacy-tiger-v4:media-id`. Legacy default
tiger settings retain that scope to preserve old deduplication and backlog. New
target sets receive separate decisions. Database schema reruns are idempotent.

Daily `ai`/`alerts` counters, pacing, provider cooldowns and hashtag query windows
remain **global to the store**. A new target never resets allowance. Historical
scopes retain IDs only for the configured retention period. The same Supabase
project must be shared by independent workers; separate SQLite files are separate
budgets. Stop old v4 workers before applying the updated RPC/ID migration.

## Video and temporary tracking

OpenCV is an optional CPU codec dependency; it is not an extra neural detector.
Local files are capped at 512 MB and network-video endpoints are rejected. A
bounded sampling loop retains only three normalized frames in memory and releases
the capture in a `finally` block. Frame groups and individual photos share daily
reservations. A frame group is one request, but may use more provider tokens than
one photo; requests/day are not a currency meter.

The tracker greedily associates same-query boxes by intersection-over-union,
expires missing tracks and assigns numeric IDs that restart each session. It
does not infer faces/identity, persist trajectories or link separate clips.
Displacement is relative image geometry, not physical motion/speed. Fast motion,
camera movement, occlusion, ambiguous subjects and imprecise boxes can change IDs.

This implements **sampled camera/video assessment**, not continuous frame-rate
semantic recognition. API latency blocks each assessment, quotas cap it, and the
local process must remain on. GitHub's hourly job handles permitted Instagram
photos and does not provide a persistent webcam/video service.

## What is intentionally unsupported

- Real-person identification from a name/face, cross-person face comparison,
  sensitive-attribute inference and cross-session person tracking.
- Exact per-pixel segmentation masks, calibrated probabilities, physical speed,
  complete object enumeration, forensic photo authenticity or accuracy guarantees.
- Downloading/analyzing third-party Instagram videos through guessed permissions,
  global Instagram surveillance, private/personal-account Business Discovery.
- Unlimited requests or payment-required provider/project/region access. The app
  cannot inspect billing plans from an API key; use actual Free plans and disable
  billing. Free confirmations are owner attestations, not independent verification.

## Contributing a genuine backend

Keep target parsing, safety, normalized result validation and budget reservation
outside any model-specific implementation. A new backend should return one
validated result per query with explicit unsupported states. Add a capability
entry and regression tests before making the planner select it. Measure quality
on a licensed human-labeled dataset rather than comparing generated confidence.

If adding dedicated OCR, detectors or masks, document model/weight licensing,
CPU/RAM/download sizes, current free access, exact supported classes and whether
data leaves the machine. A backend must not silently fall back to billable APIs,
reset shared budgets, weaken URL/lease checks or enable biometric identification.
For asynchronous live inference, preserve bounded queues and frame timestamps;
do not associate stale boxes with a new camera frame without a tested tracker.

## New verification

Tests cover arbitrary descriptions without categories, multi-query aggregation,
custom thresholds, fictional art, target-separated decisions with shared budgets,
motion rejection from stills, ordered frames, OCR/model routing, unsupported masks,
malformed boxes and blocked identity requests. Real local OpenCV decodes a
synthetic MJPG video; Gemini responses remain mocked. Setup/publishing tests use
fake credentials and mocked subprocesses. Live accuracy and Windows camera
behavior remain explicit acceptance tasks in `LIVE_CHECKLIST.md`.
