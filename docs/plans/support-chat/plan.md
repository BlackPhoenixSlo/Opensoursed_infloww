# Support chat (owner 2026-11-27)

Goal: AE has only 2 of its chatters using the CRM; owner wants to ask every chatter (every agency, every instance) what is missing. Chatters write to support from inside the CRM; owner reads/replies from ONE central page `https://inflowwww.com/support` (password, from env), and can press "Summarise all" for an AI digest of what users say is missing/blocking.

## Decisions
- D1 Scope: support tab in the help widget (all users: owners, admins, chatters) + central hub. No nudge banner, no Discord, no attachments, no broadcast, not demo, not Twin (YAGNI, owner).
- D2 Hub lives inside the relay codebase, switched on only by env `SUPPORT_HUB_PASSWORD` (set only on the public instance's relay, on the landing host). Traefik routes `inflowwww.com` PathPrefix `/support` → that relay. Avoids a new container/deploy pipeline.
- D3 Hub storage: its own SQLite file (`service/data/support_hub.db`, stdlib sqlite3 or the repo's existing pattern for a side DB), isolated from tenant/agency DBs.
- D4 Every instance (AE on another host, public, the hub's own instance) talks to the hub over HTTPS with `SUPPORT_HUB_URL` + `SUPPORT_HUB_TOKEN` (shared secret, constant-time compare) + `SUPPORT_INSTANCE` label (e.g. "AE", "public"). Unset → support endpoints say "not configured" and the widget hides the tab.
- D5 Password never in the repo (public repo!). Owner session = HttpOnly Secure SameSite=Strict cookie, HMAC-signed expiry; login rate-limited.
- D6 Summarise: one LLM call on the hub over all threads; prompt entry in docs/prompts/README.md.
- D7 Unread: widget polls a cheap unread endpoint (≥60 s, only while tab visible); relay caches hub answer ~30 s per user.

## Risks
- Auth/fence on hub (internet-facing, weak owner password) → Fable diff review.
- PII: chatter names/agency names stored on hub; no real names in code/tests (public leak gate).
- Hub page XSS: render message text with textContent only.
