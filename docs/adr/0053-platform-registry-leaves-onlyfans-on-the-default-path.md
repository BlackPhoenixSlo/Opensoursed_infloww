# The Platform registry dispatches non-OnlyFans Platforms through a Backend module and leaves OnlyFans on the default path

**Status: proposed** (2026-11-24, `.scratch/multi-platform-p1/plan.md` Phase 1a; tickets 01 and 06 in `.scratch/multi-platform/issues/`; nothing built yet).

Fansly reached the Relay as 29 `"fansly"` / `is_fansly` branches across 17 `service/` files, and a new Platform would add as many again. We decided on one Platform registry, `service/platforms.py`, extracted from those real branches rather than designed for imagined sites: a frozen entry per Platform (key, label, session file, Backend module, Lacks flags, free follow), looked up per Creator at call time. A non-OnlyFans entry names a Backend module (`fansly_backend`) that hands the Relay its client, Live connection, eviction, revenue tick, send check and API error; OnlyFans's entry names none, and an empty slot runs today's `client_pool`, `OFWebSocket` and ledger code untouched. Lacks flags are one per observed policy, never grouped, and free follow is a positive opt-in so a new Platform cannot skip the price check by default. The Shim stays one whole file per Platform, with no generic core: under 3 % of Fansly's 131 defs is generic. The eager startup imports stay, so the Backend module's API error still answers 502 on the first request. A scan test forbids Platform-key comparisons outside the registry's own files, and dispatch tests drive the real entry points with missing and explicit OnlyFans meta. We chose this because the owner's constraint is that OnlyFans behaviour does not change, and only a default path that is today's code proves it without re-testing every OnlyFans feature. The cost: OnlyFans is not a Backend module like the others, OF-only implementations (`sign_rules.py`, `link_prewarm.py`, …) stay plain checks, and "one entry and one Backend module" covers Relay dispatch only; capture route, `/img` allowlist, login extension hosts and the Platform table are separate edits listed in the Platform recipe.

ASSUMPTION: an unknown `meta.platform` reads as OnlyFans, as today (`service/accounts.py:416-421`, rung 3); overturned if the owner wants a loud failure.

## Considered Options

- **OnlyFans wrapped as a Backend module too.** Rejected: rewrites the OnlyFans path the owner froze.
- **Lazy-loaded Backend modules.** Rejected: the first request would lose the 502 body the startup import registers.
- **Grouped Lacks flags (`UNREAD`, `SCHEDULED_MEDIA`).** Rejected: each grouped three policies or misstated one.
- **A shared Shim core split out for site #2.** Rejected: nothing generic to split; a new Platform copies the layout and imports `service/of_shapes.py`.
