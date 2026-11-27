# A Fansly Mirror capture runs behind a browser-wide gate that denies every write by default

**Status: proposed** (2026-11-26, `.scratch/fansly-manager-mirror/map.md` Phase 1; ticket 02; nothing built yet).

The Fansly mirror is built from the owner's signed-in creator session, and the owner's constraint is that capture writes nothing on Fansly, yet Fansly sends On-open writes (message ack, notifications ack, presence, impression log, story view) with no click, most pages' open-time traffic was never recorded, and `record.py` drops redirected POSTs (`fansly/capture/CAPTURE_LOG.md:83-99`). We decided a Capture gate (`fansly/capture/gate.py`) attaches to every target of that Chrome, bypasses service workers and pauses every request on every host at request stage (redirect hops included): GET, HEAD and OPTIONS continue; each known On-open write gets a local reply in its recorded shape; anything else fails and halts the run. Fansly's sockets are blocked and the page reloaded after arming, so no socket opened earlier survives. The gate keeps its own decision log and heartbeat, `drive.py` refuses to act on a stale heartbeat, and a Gate audit (no continued non-GET, no outbound socket frame, per-group unread counts unchanged) must pass before the generator may read the capture. We chose default-deny on all hosts because an allowlist of known writes cannot cover the unrecorded pages, and a host filter on Fansly's API would miss the presigned S3 upload host. The cost: a page whose GET has a write effect is caught only by the unread audit, and a new On-open write halts the run until its reply shape is recorded.

ASSUMPTION: AWS WAF challenge POSTs continue past the gate (bot-check tokens, not account writes; rung 4); overturned by blocking them and accepting re-login risk.

## Considered Options

- **Fail-closed egress proxy.** Rejected: needs a fresh browser profile and re-login under Cloudflare fingerprinting; the gate gives the same decision point in the session already signed in.
- **Offline replay of saved bundles and API responses.** Rejected for now: every lazy chunk would need a scrubbed fixture. It stays the fallback if the gate proves leaky.
- **Blocking only the known On-open writes.** Rejected: open-time writes for vault, stats, wallet, scheduled and streaming pages are unrecorded.
