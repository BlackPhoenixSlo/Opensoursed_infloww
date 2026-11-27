# The Fansly mirror has its own generator that copies the OF mirror's guard primitives

**Status: proposed** (2026-11-26, `.scratch/fansly-manager-mirror/map.md` Phase 2; ticket 03; nothing built yet).

A second mirror invites one shared generator, but `scripts/of-mirror.mjs` is ~1,700 of 3,833 lines of OnlyFans-specific DOM reconstruction (:626-2335), and any change to it touches the signed-off OF mirror output (167 pages), which would then need a byte-identical regeneration proof from captures that are not in the repo. A Fansly Mirror capture saves whole rendered documents, so its generator is mostly sanitise, scrub and link rewrite. We decided on a new `scripts/fansly-mirror.mjs` that copies the generic parts of the OF generator (args and fail, `mapHtml`/`rewriteTag`, fakers and self-test, Leak guard, `--check`, stage and swap) and adds what full documents need: a parsed allowlist of every URL sink, Fansly hosts, money in attributes, name-scoped `_ngcontent`/`_nghost` digit exemptions, and a planted-leak fixture the guard must fail. Output goes to `app/public/fansly-mirror/` with `app/lib/fansly-mirror-pages.ts` in the OF table's shape. The cost is two copies of the guard primitives that can drift apart; a fix to one guard must be checked against the other.

## Considered Options

- **Parameterise `scripts/of-mirror.mjs` by Platform.** Rejected: proving the OF output unchanged costs more than the copy.
- **Extract a shared `mirror-guard.mjs` now.** Rejected as premature (YAGNI); revisit when the two guards are seen drifting.
