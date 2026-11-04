# Supabase/SQLite migration to v7

Run repository-root `schema.sql` in Supabase SQL Editor as project owner. It is
the complete idempotent fresh-install schema and v3/v4/v5/v6-to-v7 migration.
Stop older workers and back up the database first.

v5 prefixes original tiger IDs with `legacy-tiger-v4:` and other decisions with
a target hash. v6 retains those IDs and shared counters, adds a service-only
review-list operation, and preserves hydrated browser metadata on rediscovery.
Re-run the whole script before starting v6 cloud workers. Browser numeric IDs
are stable URL hashes, not actual Meta Graph media IDs.

1. Stop all scheduled/local workers; back up the database.
2. Run `schema.sql` as one script, then inspect queue/counter preservation.
3. Install v6 and run `python main.py --stats` with the intended configuration.
4. Follow `docs/LIVE_CHECKLIST.md` for your chosen source.

The original v3 import runs once, guarded by `tigerwatch_kv['migration/v3']`.
Legacy tables remain for backup: `tigerwatch_seen`, `tigerwatch_pending`,
`tigerwatch_tags`, `tigerwatch_daily_usage`, plus the obsolete
`tigerwatch_reserve_ai(date,integer)` function. Remove these through your database
administration process after validating the import. Their retained metadata and
provider/database backups are outside current retention. Keep migration markers.
Never run incompatible worker versions against the same store concurrently.

Local SQLite migrates legacy tables on open; back up its file with workers stopped.
No manual SQLite SQL is required. The separate URL-only casebook stays local and
is never synced to Supabase by this application.


## v7

Stop older workers and re-run the complete current schema.sql. v7 adds server-only
feedback/cache tables, dashboard operations, atomic digest/alert reservations and
fenced monitor state. It replaces the old counter resource check to permit digests.
Existing queue scopes/IDs and usage remain. Local SQLite applies its additions
on open, tightens POSIX permissions to0600 and refuses a symlink DB path. New SQL
tests verify idempotent v6 migration and service-only access.
