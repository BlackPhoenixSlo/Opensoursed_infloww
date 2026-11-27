# Leak history lives in the Removal service; the CRM is a thin client

**Status: proposed** (2026-11-27, `.scratch/leak-tracker/goal.md` Phase 1; tickets 01, 03, 05; nothing built yet).

The Leak tracker needs daily discovery, Origin probes, spend control and Notices, and every CRM install (AE, public, self-hosted, demo, Twin) ships from one tree. We decided the Removal service owns all of it: a new tenant-scoped Tracker API beside its Quick scan, per-Agency Tracker keys under a stable Tracker tenant, header auth, per-tenant caps, and every Leak, event and Probe state. The CRM keeps only what it needs while the service is down: the Tracker key, the `leak_watch` row (Leak identity, on/off, keyed (agency_id, account_id) after the `s4s_profiles` precedent, `service/db/models.py:1962-1978`) and the tombstone queue; it reads Leaks through the Relay and shows "last checked <time>" rather than invent state when the service is unreachable. We chose this because one place then owns host rules, spend and Notices, nothing engine-side ever reaches the public replay, and one scan can serve every Agency tracking the same Creator. The cost: tracked Creators' Leak identities leave each install for the owner's server (opt-in per Agency, behind the consent attestation), the service needs real multi-tenancy it lacks today (one shared partner key, one 10/hour bucket, slug reads with no tenant check), and the CRM's page is only as fresh as the service.

ASSUMPTION: the owner accepts handles from third-party installs going to the Removal service, opt-in. Overturned if Creator data must stay inside each install; then the CRM-owned variant below wins.

## Considered Options

- **The CRM owns history and probes, using the service only for discovery.** Viable (the free-scan hit tables are not capped at 80 and survive 3 days) but every install would fetch pirate sites from its own server and could never see Notices.
- **Hosting the owner's existing local leak pipeline as-is.** Rejected: its UI is loopback-only, it reaches a client every second night at best, and it records a removal date once. Its URL key and availability rules are reused as code inside the service.
