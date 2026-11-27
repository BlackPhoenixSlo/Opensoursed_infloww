# Platform mirror recipe

How to build a creator-UI Mirror for a new Platform: a static, scrubbed copy of its creator site inside the app, with identity, data and writes added on top. OF Manager (`/of-manager/*`) and Fansly Manager (`/fansly-manager/*`) are the two built so far. The Relay side of a Platform is `docs/platform-recipe.md`; this file covers the UI copy only.

## What it cost so far

- **OF Manager:** about 876 commits over 6 rounds and about 8 capture sittings. Day 1 built all 150 pages. The rest was rework:
  - captured example rows looked like fake data (133 commits);
  - an audit (93 commits);
  - splitting 37.6k lines of `ofMirror*.ts` (73 commits);
  - a sweep of controls that did nothing (~450 commits, 123 tickets, ended partial).
- **Fansly Manager:** 57 commits gave 64 pages (51 pages + 13 states). That is about 40% of OF's pages and 25% of its states. It has no data rows, no writes and no phone proof, and the owner still had to ask for "capture missing stuff".

The pattern both times: pages, states and assets that should have been captured in the first sitting turned up missing in every later round. Most rules below exist to avoid that.

## Rules learned

1. **Log in and capture the live page.** A crawler (SiteSucker) gets top-level pages only. Use it for assets at most.
2. **Read the page with evaluate, not a snapshot.** Run evaluate in the page and post the DOM to a localhost receiver. Snapshots fail while the preview pane is hidden.
3. **Chunk big results and verify them.** Evaluate results over 60k chars spill to files. Slice into 60k base64 chunks with a length and hash check; overlapping tail offsets corrupted one OF capture.
4. **Dump the whole `body`, with overlays open.** Modals and menus are teleported outside the app root. Record each dialog on every page that opens it, not just once.
5. **Collect every stylesheet and font from the network log**, including lazy-loaded CSS and icon fonts. OF lost its streaming CSS this way and Fansly its Font Awesome Pro icons. An icon font with a licence is an owner call; hide the icons until it is decided.
6. **Turn on the PII guard and `--check` before the first commit.** One early OF commit held the real username, and a harness ref still holds it. Key captures by route, never by handle. The guard scans whole files and fails hard.
7. **Capture with one account.** Mixing two accounts forced `--allow-multiple-accounts` and per-page identity detection.
8. **Use a creator account that has content.** An empty account captures only empty states. Fansly's had no avatar, banner, tiers or posts, so populated rows were never seen.
9. **Turn example rows into templates on day 1.** Tag every count with its API field (`data-oi-count`). Captured example rows and counts ("12+", lorem posts) shown as real cost OF a whole round.
10. **List every control right after capture.** Mark each one wired, disabled by the platform, or not yet (`scripts/of-mirror-check/dead*.py`). OF only did this a month later and found 123 dead controls.
11. **Check the first paint in dark mode on day 1.** Use a head boot script plus a CDP screencast that fails on any light frame (`dark.py`).
12. **Decide the All-models scope up front.** Identity swap happens client-side from the platform's `/me`. Carry `?row=` through states. Decide what All-models shows before building pages; OF spent about 10 fixes on it.
13. **Intercept writes before sending them.** Stub the platform's signed client to read the real request body without sending it. Send only bodies you know (ADR-0005). Keep an undo log for every proof write.
14. **Don't kill the logged-in session.** A browser that copied cookies but not localStorage logged out OF's stored session. Seed localStorage, probe `/me` first, and stop on a wrong user.
15. **Capture read-only, behind a default-deny gate** (ADR-0065, `fansly/capture/gate.py`): no writes, purchases, messages or read receipts. Use the owner's creator Chrome on its own CDP port. Only the coordinator runs the live capture. Agents never read the capture output, because it holds live tokens.
16. **Keep the Mirror out of public.** Its CSS and markup never ship public (ADR-0067): add the asset path to the leak-check never-public list in the same PR that adds the generator.

## Deep-details checklist

Before calling a Mirror complete, check every row against the captured platform. Count pages and states, and compare the counts with OF's 117 pages + 50 states.

- [ ] Routes: nested and id routes, redirects, landing tab.
- [ ] Dialogs, teleported ones too, per opener page; confirm modals; success and error toasts.
- [ ] Dropdowns, sort/filter and kebab menus (on your own item and on others'), avatar menu, phone overlays.
- [ ] Tabs, chips, date and period pickers (past and future days), calendar month and day.
- [ ] Hover tooltips, "i" icons, chart tooltips, focus states.
- [ ] Empty, loading, error with Retry, disabled with a reason.
- [ ] Infinite scroll, sticky header, story player, media viewer.
- [ ] Composer tools: poll, quiz, expiry, target, labels, format, tags, vault picker, upload states, price.
- [ ] Number formats (99+, 1.5K), cents, masked fields, line breaks.
- [ ] Dark first paint, theme switch, phone breakpoints.
- [ ] Identity in the page and in title/aria/alt; identity per row; All-models; dead session; no creator.
- [ ] CSS chunks, fonts, icon fonts.
- [ ] Writes: body, undo, read-back. Not-yet list at zero, or each item parked with a reason.
- [ ] Scrub: no ids, emails, IPs or signed URLs; `--check` green; never-public paths gated.

## Order of work

| # | Step | Done when |
|---|---|---|
| 0 | Owner: a creator account with real content, signed in on its own CDP port, and one capture account | `/me` returns the creator before any capture |
| 1 | Capture rig + gate: copy `fansly/capture/` (drive, record, gate, mirror plan) | gate self-test passes; nothing reaches the platform on a dry run |
| 2 | Mirror plan: every route, plus every state from the checklist reachable without a write | plan reviewed against the checklist before the sitting |
| 3 | One capture sitting: body dump with overlays, network log for CSS and fonts, chunked and hash-checked | every plan row captured, or listed under not captured with a reason |
| 4 | Generator: copy `scripts/fansly-mirror*` (scrub, kinds, assets, icons, wire) with the guard and `--check` | `--check` green; identity grep empty; never-public path in leak-check |
| 5 | Control list | every control marked wired, disabled by the platform, or not yet |
| 6 | App: route, nav entries behind a per-Platform flag, identity swap, theme | `render.py` / `navigate.py` / `dark.py` pass; desktop + phone × light + dark screenshots |
| 7 | Read-only data: fill Mirror pages from the Platform's Shim reads (OF hook pattern) | `data.py`-style check with a mocked relay |
| 8 | Writes, one at a time: intercepted body, owner OK, undo log | its own planning run; ADR-0005 and ADR-0070 |

Steps 0–6 are one spec-auto run; 7 and 8 each get their own. Proof needs a `verify-app` mode for the Platform; Fansly has none yet.

## Prompt template

Fill in the angle brackets and start a new main thread with it:

```
/spec-auto --execute --tickets 999
Goal: <Platform> Manager (/<key>-manager/*): static scrubbed copy of the <Platform> creator UI,
as deep as OF Manager, per docs/platform-mirror-recipe.md (rules, checklist, order of work).
Inputs: creator Chrome on CDP :<port> (owner signed in, account with content), capture rig copied
from fansly/capture/, generator copied from scripts/fansly-mirror*.
Phases: 1 rig + gate + mirror plan (checklist-complete); 2 one capture sitting; 3 generator + guard;
4 control list; 5 app route/nav/flag/identity/theme + verify-app mode + screenshots.
Constraints: capture read-only behind the gate (no writes, purchases, messages, read receipts);
only CDP :<port>, never other Chromes; agents never read capture output (coordinator only, counts
only); no identity values in commits or logs; Mirror never public (leak-check never-public path);
heavy processes nice 10; Fable plan check before executing; ship per CLAUDE.md (PR, merge green,
AE via the deploy-all window, WATCH.md line); per-agency flag write on AE waits for the owner.
```

## Fansly today (2026-11-27)

Fansly needs a second round on the template above, with these deltas:

1. Capture depth: composer sub-states, thread composer, inbox filters, notification type tabs, vault/list/stats sort and date pickers, settings dropdowns, account modals (fake the 2FA reply inside the gate), and hover states. Also co-performer detail, vault album and list detail.
2. Fonts: Font Awesome Pro webfonts were never captured. Capture them, but shipping them needs the owner's OK on the licence; icons stay hidden until then.
3. Proof: `verify-app --fansly` with a seeded avatar and banner, desktop + phone × light + dark.
4. Read-only data from the Fansly Shim reads.
5. Writes: a separate planning run.

Owner question first: can a populated creator account be captured? If not, the empty states stay.
