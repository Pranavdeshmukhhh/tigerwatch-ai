# Security and privacy

v5 introduced free-only model routing, scope-separated target decisions, hidden local
setup prompts and an owner-invoked public-repository publisher. The publisher
excludes `.env`, sends secret values through stdin, excludes unknown private keys
from public Variables and refuses source files containing configured secrets.
Dotenv interpolation is disabled so descriptions such as `${SOME_KEY}` stay
literal rather than expanding credentials into model input.

Local tracking uses overlapping boxes within one session, without faces,
embeddings or persistent trajectories. Specific-person identification from a name
or face, sensitive-attribute inference and cross-session identity matching are
not supported. Sampled video/camera assessments still submit frames to the chosen
provider under its free-tier terms; confirm processing rights first.

Keep `.env`, database files and server keys out of version control and public
logs. Rotate any exposed credential through its provider; deleting a commit alone
does not revoke a token. The Supabase service-role JWT is a privileged server
credential. Restrict repository write access and review scheduled-workflow code.

The downloader allows only HTTPS Meta CDN hosts, standard TLS ports, public DNS
addresses and validated redirects. TLS verification stays enabled. Responses,
image bytes and pixels are bounded; decoding starts with only JPEG/PNG/WebP
plugins enabled. The runtime uses the system's trusted DNS/TLS/proxy configuration;
its hostname checks are not a replacement for a trustworthy host/network.

Metadata is minimized at ingestion. Raw captions, geotags, profile bodies and image files are
not stored by the worker. v6 sale modes retain only categorical offer signals. Signed image URLs are private transient queue data, not
alert content. Successful/rejected/dead payloads are cleared, review payloads have
a bounded age, and terminal IDs have configurable retention. Legacy v3 backup
tables and provider/database backups need their own deletion process.

Removing EXIF does not remove sensitive information visible in pixels, source
names or linked posts. Restrict monitoring and Telegram membership accordingly.
Review provider data-processing terms and author rights before enabling AI or
photo redistribution. No automated classifier proves authenticity or location
safety; no detection score is a calibrated probability.

Report vulnerabilities privately with dummy tokens and synthetic data. The
dependency advisory scan in this release is a dated check and should be repeated
when dependencies or current advisories change.


## v6 source and review additions

Normal public browsing is conditional and is not an approval or access-control
workaround. Fresh logged-out contexts take no passwords, saved sessions or
imported cookies. Request guards block normal media loads, service workers,
downloads and untrusted destinations, but a rendered webpage is not a formal
proof that arbitrary embedded bytes can never contain an image. Only the fully
separate URL-only casebook provides the no-network reporting path. Never point
the image/browser workflow at suspected child sexual abuse material. Explicit
requests are blocked before fetching; English caption guards are best-effort,
not a validated abuse classifier or guarantee about unmarked content.

Sale modes produce private unverified review candidates and cannot determine
legality or authenticity. Caption context is minimized to fixed categories; no
raw contact, price, coordinate or profile enrichment is saved. Photo delivery is
disabled for sale queries, regardless of a generic re-sharing flag.

Watch definitions, casebooks and review exports contain sensitive references even
without media. Private writes use atomic replacement and POSIX 0600 permissions;
on Windows keep the folder under a private user account and review inherited
NTFS ACLs. These files are not encrypted. Casebooks are local and need a separate
manual retention/deletion process. Do not commit them or upload them as Actions
artifacts. SQL retention does not delete provider logs, backups or local exports.


## v7 local control

The dashboard binds only127.0.0.1 and uses launch-token, Host/Origin and cross-site
checks. No media previews, external assets, secret editor or arbitrary path-write
API is exposed. Do not publish or reverse-proxy it to the internet. Local control
is not multi-user authentication. Feedback is independent of queue decisions and
never resends an alert. Same-watch monitor and image-assessment leases are fenced;
daily digest reservations share the alert limit and respect cooldowns. New cache
metadata expires after seven days and stores no pixels/captions/URLs. Review links
remain private and suspected child-safety-blocked links are suppressed in the UI.


## v8 access boundary

All dashboard APIs now require the private per-launch link key; the old public
session bootstrap is removed. Open the full terminal link, keep it private, and
reopen it after reload. The key is stripped from the address bar and not persisted
in browser storage. Loopback binding, stricter HTTP/JSON parsing, bounded handlers
and request rates, same-origin policies and safe rendering are defense in depth.
Feedback is scope-checked and known safety blocks override older positive sends.
Unreadable Telegram responses remain uncertain delivery and cannot be blindly
resent. Full findings and threat limits are in docs/AUDIT_V8.md and
docs/ARCHITECTURE_V8.md. This is not public/multi-tenant hosting or a guarantee
against compromised local accounts, extensions, private-link holders or denial
of service. Native OS security and provider authorization remain necessary.
