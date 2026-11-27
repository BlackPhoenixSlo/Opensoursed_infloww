# Phase 03 — Fansly mirror generator and guard

**Objective.** `scripts/fansly-mirror.mjs` turns a passed Mirror capture into a scrubbed Fansly mirror under `app/public/fansly-mirror/` plus its pages table and build constant, publishing only when the Leak guard and the completeness check pass, and `--check` re-proves a committed tree with no inputs; all of it proven on a synthetic fixture capture and a planted-leak fixture. It ships in one PR with Phase 4, coded against the Tracer facts Phase 2's live tracer records.

## Problem Statement
Phase 2 leaves the owner's whole signed-in Fansly creator UI as raw rendered documents in `~/Downloads/fansly-live-capture/`: real handles, display names, account ids, fans' names and messages, wallet and payout amounts, session IPs, snowflake ids in links and attributes, `ng-reflect-*` echoes of bound data, user media on `cdn3`/`mediav2`, and live hosts (Intercom, WAF, GTM, the Fansly API and sockets). None of that can reach the repo, and a page that loads anything from Fansly in the browser leaks the viewer. The OF generator cannot take it: ~1,700 of its lines rebuild OnlyFans DOM page by page, and changing it would need a byte-identical regeneration of the signed-off OF mirror from captures that are not in the repo (ADR-0066). Its guard also misses sinks full documents carry (meta refresh, form `action`, object `data`) and checks money in text only. Phase 4 needs a pages table, a build constant and identity placeholders to route, frame and swap.

## Solution
A new generator, copied from the OF generator's generic parts, reads Phase 2's Capture manifest, refuses a capture that is not `complete` or whose entries do not cover the committed mirror plan, maps each Fansly route and State to a Fansly Manager section page, resolves links, openers and identity hooks on the raw document, then scrubs it (identities to placeholders, other people to "Fan N", free text to lorem, numbers and money to fakes, media to a blank image, live hosts, comments and scripts dropped, canvas charts to placeholders), copies the CSS, fonts and SVG Phase 2 collected into a static build folder (every `data:` URI extracted to a file there), and wires each State's opener and close controls to and from its State page the way OF Manager does. It builds into a stage, runs the Leak guard (every URL sink in pages, CSS and SVG parsed and allowlisted, money in text and attributes, name-scoped Angular attribute exemptions), a completeness check (every entry produced a page, every link and asset resolves) and the unreviewed-text check, and only then renames the stage, the pages table and the build constant in. A failure writes nothing and names the file and leak kind, never the leaked value. `--check` re-runs the structural guard and table↔files checks on the committed tree. Every run self-tests the guard against an inline planted page first.

## User Stories
1. As the coordinator, I want `node scripts/fansly-mirror.mjs` to read `~/Downloads/fansly-live-capture/` by default and any other capture via `--capture <dir>`, so that the real run needs no edits.
2. As the coordinator, I want the generator to refuse a capture whose manifest does not record `audit.passed: true` and `complete: true`, or whose `entries` and `skipped` together do not cover every id in `fansly/capture/mirror_plan.json` (a `skipped` id must be `optional` in the plan), so that a partial capture or a run that may have written to Fansly never replaces a complete mirror.
3. As the coordinator, I want the generator to fail when the manifest's `identities` lacks a `creator` or a `fan`, holds a role twice, holds an `accountId` that is not a string, or names a creator whose username never appears in any captured document, so that identity provenance is checked before anything is scrubbed.
4. As the owner, I want no identity value printed in any message (it says "creator username found in pages/home/index.html", not the name), so that terminal and agent logs stay clean.
5. As the owner, I want no leak value printed at all, only file and leak kind, so that a failed run leaks nothing into logs either.
6. As the coordinator, I want every captured manifest entry mapped to exactly one section page (Fansly route table below) and an unmapped route, two entries landing on one page, or an entry's `file` that does not exist to fail the run, while a `skipped` id produces no page and links or openers to it become `#`, so that the copy is complete or not published.
7. As the coordinator, I want every section's root page present, so that Phase 4's bare section routes resolve.
8. As the coordinator, I want a State entry saved as `<sub>/state-<name>` (or `state-<name>` on a section root), so that States follow the OF precedent (ADR-0006).
9. As the coordinator, I want snowflake path segments collapsed to fixed subs (`messages/thread`, `lists/list`, `vault/album`, `profile/post`, `creator/coperformers/detail`), so that no id reaches a path.
10. As the coordinator, I want Fansly links that were captured as redirects (`url` ≠ `final_url`) to point at the landing page, so that legacy aliases resolve in the copy.
11. As a Fansly Manager user, I want every link to a mirrored page rewritten to `/fansly-manager/<section>/<sub>` with `target="_top"`, and every other link to `#`, so that clicks stay in the app.
12. As a Fansly Manager user, I want links to Fansly's own `/scheduled`, `/lists`, `/notifications` and `/creator/stats/earnings` rewritten like any mirrored page, so that Phase 4's exact-path and redirect tables send them to the Built pages.
13. As a Fansly Manager user, I want a State's opener in its parent page covered by a link to the State page, and the State page's backdrop, opener and close controls (close/cancel buttons inside the overlay) linking back to that page, so that the avatar and balance menus and dialogs open and close as in Fansly.
14. As Phase 4, I want the creator's username and display name replaced by `yourmodel` and `Your Model` everywhere, so that the Identity swap has fixed strings to replace.
15. As Phase 4, I want the creator's avatar images tagged `data-oi-avatar` and banner images `data-oi-banner`, so that the Identity swap finds them; a profile root page with neither tag fails the run.
16. As Phase 4, I want Fansly's left rail tagged `data-oi-nav` on every page that has it, so that the frame can hide it; no tagged page in the whole run fails it.
17. As the owner, I want the fan test account's username, display name and id replaced by `fan1` / `Fan 1`, so that the second identity never ships.
18. As the owner, I want every other person found by a profile link, an `@handle` or an avatar `alt` collected and replaced as `Fan N` (stable numbering in manifest then document order) wherever the string appears, so that other people's names never ship even outside a known field.
19. As the owner, I want message bodies, post text, bios, notes and list names replaced with lorem of similar length by a kind-keyed text rule table, so that free text never ships.
20. As the owner, I want the run to fail, listing per page the element path (tags and classes, never the text), when a long text node (20+ characters or 3+ words) no rule touched is not on the generator's reviewed keep list, so that unmatched free text is resolved before publication and the coordinator extends the rule table or keep list from the real capture without reading values in a log.
21. As the owner, I want numbers faked (dates and times kept) and `$` amounts mapped to the fixed fake buckets in text and in attribute values, so that wallet, tier price and earnings never ship.
22. As the owner, I want every text input's `value`, every textarea's content and every contenteditable's text dropped or lorem'd, and session, payout and tax fields blanked, so that settings pages carry no account data.
23. As the owner, I want emails replaced by the placeholder email and attributes with 6+ digit values dropped (geometry attributes and `_ngcontent-*` / `_nghost-*` attribute names excepted), so that ids hidden in markup never ship.
24. As the owner, I want every `ng-reflect-*` attribute dropped, so that Angular's echoes of bound values never ship.
25. As a Fansly Manager user, I want `_ngcontent-*` / `_nghost-*` attributes and the matching selectors in inline `<style>` kept, so that Angular's scoped CSS still styles the copy.
26. As the owner, I want `<script>`, `<noscript>`, `<iframe>`, `<object>`, `<embed>`, `<base>`, `<meta http-equiv>`, HTML comments, `srcset`, `on*` handlers, `<form action>`/`formaction`, preconnect/prefetch/preload/manifest/icon links and the Intercom, WAF, GTM, maps and live-video nodes dropped, so that nothing in a page can run or call out.
27. As the owner, I want user media on any Fansly media host (`cdn3`, `mediav2`, ...) and every raster image (remote, `data:` or not collected) replaced with the blank image file `static/<build>/oi-blank.png`, including CSS backgrounds and SVG `<image>`, so that no creator or fan photo ships.
28. As a Fansly Manager user, I want the stylesheets, fonts and SVG Phase 2 collected (manifest `assets`, 2 MB cap per file, OF's `MAX_ASSET_BYTES`, total bytes printed in the summary) copied into `static/<build>/`, every non-raster `data:` URI written out as `static/<build>/data/<sha256-12>.<ext>`, and every reference rewritten to `/fansly-mirror/static/<build>/...`; a reference to an asset that is missing or over the cap is rewritten to the blank image (images) or `none` (other CSS `url()`) and listed in the summary, so that the copy looks like Fansly with no remote load and no dangling reference.
29. As a Fansly Manager user, I want each `<canvas>` replaced by a same-size neutral placeholder, so that stats pages keep their layout where the captured chart pixels were lost.
30. As a Fansly Manager user, I want each page to carry a one-line dark boot script that sets Fansly's dark marker when the app frame's theme is not light, so that the copy, captured in light, boots dark like OF (Fable 2026-11-26, supersedes issue 05 §8).
31. As the coordinator, I want the run to fail when a captured document already carries the dark marker or when no copied stylesheet uses the marker's selector, so that a dark capture or a wrong marker is caught at generation.
32. As the coordinator, I want the run to fail when the manifest's entries carry more than one bundle hash, so that two Fansly builds' CSS never mix in one copy.
33. As the owner, I want the Leak guard to parse every URL sink in pages, CSS, SVG and the pages table (`href`, `src`, `action`, `formaction`, `data`, `poster`, `xlink:href`, `background`, `style` `url()`, `<meta>` refresh, CSS `@import` / `url()`) and fail any that is not `#`, `/fansly-manager/...` or an existing file under `/fansly-mirror/static/...` (no `data:` at all: ticket 03's allowlist), and fail any attribute not written as `name="value"` or a bare name, so that full documents cannot smuggle a load past it.
34. As the owner, I want the Leak guard to also fail any Fansly host, other remote URL, email but the placeholder, IPv4/IPv6 but the safe ones, 9+ digit run (outside geometry and the name-scoped Angular exemptions), `@handle` but the placeholders, non-fake amount in text or attributes, script but the boot script, `ng-reflect-*`, HTML comment, `data:` URI, identity needle or scrubbed-string needle, in file contents and in every output file path, so that every leak kind the scrubber handles is proven gone.
35. As the owner, I want every invocation, `--check` included, to run a self-test that feeds an inline planted page holding one of each leak kind through the guard and fails unless every kind is reported, so that a weakened guard cannot run.
36. As the owner, I want the generator to build into `<out>.tmp`, guard the stage and the pages-table text, write the two TS files beside their targets as temporaries, and rename all three in only when every check passed; a red check leaves the previous output and TS files untouched and removes the stage (kept only under `FANSLY_MIRROR_KEEP_STAGE=1`), and a run refuses to start while an `<out>.old` from a killed swap exists, so that a red run never publishes.
37. As Phase 4, I want `app/lib/fansly-mirror-pages.ts` in the OF table's shape and `app/lib/fansly-mirror-build.ts` holding the build, so that routing copies `mirrorPageOf` unchanged.
38. As anyone on a fresh checkout, I want an empty committed pages table and a `null` build until the coordinator's real run, so that Phase 4 compiles and tests before any mirror file exists.
39. As a reviewer, I want `node scripts/fansly-mirror.mjs --check` with no inputs to verify the committed tree (every listed page has a file and every file is listed, every section index is listed, every `/fansly-manager/` link resolves to a listed page or a Built page path, every static ref exists, the build dir exists, NOTICE present, no `.tmp`/`.old` beside it, structural guard clean), so that a hand edit or a stale tree is caught.
40. As anyone on a Never-public tree (public, demo, Twin), I want `--check` to pass with a "no mirror in this tree" line when `app/public/fansly-mirror/` is absent, so that a stripped export stays green (ADR-0067).
41. As a tester, I want `--out <dir>` and `--lib <dir>` to redirect the mirror and the two TS files, so that tests never touch the repo's real output.
42. As the owner, I want the generator to write `NOTICE.md` into the mirror saying it holds Fansly's CSS, fonts and markup and is a Never-public path, so that the folder explains itself.
43. As the owner, I want `app/public/fansly-mirror.old/` git-ignored (Phase 1 ignores `.tmp`), so that a killed swap's old tree is never committed.
44. As a tester, I want the generator, `--check` and every failure path exercised by one vitest file on a committed synthetic capture with fake identities and no real data, so that the Phase is proven without the live capture.
45. As the owner, I want the committed fixtures to pass the public leak-check content rules (fake names, ids starting `900`, `@example.com` emails, TEST-NET IPs), so that the fixtures can ship to public like any test.

## Implementation Decisions
- **Owns.**
  - `scripts/fansly-mirror.mjs` (new): generator, scrubber, Leak guard, completeness check, `--check`, self-test.
  - `app/lib/fansly-mirror-pages.ts` and `app/lib/fansly-mirror-build.ts` (new, generated; committed initially empty / `null`).
  - `app/public/fansly-mirror/` (generated output; written only by the coordinator's real run, after Phase 1 lands).
  - `app/lib/__fixtures__/fansly-mirror/capture/` (synthetic Mirror capture in Phase 2's layout: `manifest.json`, `pages/<id>.{html,meta.json}`, `static/`, plus a small `mirror_plan.json` passed with `--plan`) and `app/lib/__fixtures__/fansly-mirror/planted-leak/` (an output tree with one page or asset file per structural leak kind, named after the kind).
  - `app/lib/fanslyMirrorGenerator.test.ts` (new) and `app/lib/fansly-mirror-pages.test.ts` (copy of `of-mirror-pages.test.ts`, every file read inside `it.skipIf(!existsSync(dir))`).
  - `.gitignore`: the old-output folder `app/public/fansly-mirror.old/` (the `.tmp` line is Phase 1's).
- **Not owned.** `scripts/of-mirror.mjs` and its output are untouched (ADR-0066). The route, redirect table, frame, chrome, nav, Identity swap, theme hook and the served-browser check (`scripts/fansly-mirror-check/render.py`, which absorbs the raw-page checks) are Phase 4. `NEVER_PATHS`, export check and docs are Phase 1. The capture and Gate audit are Phase 2.
- **Interfaces.** CLI only:
  - `node scripts/fansly-mirror.mjs [--capture <dir>] [--plan <file>] [--out <dir>] [--lib <dir>]` — defaults `~/Downloads/fansly-live-capture`, `fansly/capture/mirror_plan.json`, `app/public/fansly-mirror`, `app/lib`. Exit 0 and a summary (pages per section, assets copied and their total bytes, asset refs blanked as missing or too large, people scrubbed, canvases replaced, entries whose meta counts shadow roots or iframes) on success; exit 1 and `fansly-mirror: <reason>` on any failure.
  - `node scripts/fansly-mirror.mjs --check [--out <dir>] [--lib <dir>]` — no capture read.
  - `FANSLY_MIRROR_KEEP_STAGE=1` keeps the stage on exit for inspection (OF's `OF_MIRROR_KEEP_STAGE`).
- **Schema.** None.
- **Contracts.**
  - Consumed (Phase 2's Capture manifest, `docs/spec/phase-02-fansly-mirror-capture.md` Contracts, the producer; both specs hold this one shape):
    ```ts
    { audit: { passed: boolean; sessions: { id: string; verdict: string }[] };
      bundle_hash: string; theme: "light" | string; complete: boolean;
      identities: { role: "creator" | "fan"; username: string; displayName: string; accountId: string }[],
      entries: { id: string /* path-like, a State under its parent's id */; kind: "page" | "state"; file: string /* "pages/<id>.html" */;
                 url: string; final_url: string; state: string; opener?: string /* the CSS selector tclick used */;
                 settled_selector: string; reset: unknown; bundle_hash: string; theme: string; session: string;
                 canvases: number; shadow_roots: number; iframes: number; meta: string; png: string }[],
      skipped: { id: string; reason: string; tried?: string[] }[],
      assets: { url: string; file: string /* "static/<...>" */ }[] }
    ```
    plus the committed `mirror_plan.json` (`[{id, kind, url, parent?, opener?, tracer?, optional?}]`). Each `file` is a whole document (`document.documentElement.outerHTML`, overlays included). A State's parent is its plan `parent`, always a page. Unknown extra fields are ignored. Every path must stay inside the capture root.
  - Produced, `app/public/fansly-mirror/`: `NOTICE.md`, `pages/<section>/<sub or "index">.html`, `static/<build>/<path on assets.fansly.com>`, `static/<build>/data/<sha256-12>.<ext>`, `static/<build>/oi-blank.png`. A State page's key is its parent page's key plus `/state-<name>`. Pages reference statics as `/fansly-mirror/static/<build>/...` and pages as `/fansly-manager/<section>/<sub>`. Identity placeholders: text `yourmodel` / `Your Model`, attributes `data-oi-avatar` / `data-oi-banner`; rail `data-oi-nav`; canvas placeholder `data-oi-chart-placeholder`; state links `class="oi-state-link"` / `"oi-state-backdrop"` anchors with `target="_top"`; one `<style id="fansly-mirror-overrides">` for those classes; one boot `<script>` (the only script the guard allows, by exact text).
  - Produced, `app/lib/fansly-mirror-pages.ts` (OF table's shape, ADR-0066):
    ```ts
    export interface FanslyMirrorSection { index: string; pages: Record<string, string> }
    export const FANSLY_MIRROR_SECTIONS: Record<string, FanslyMirrorSection>;
    ```
    and `app/lib/fansly-mirror-build.ts`: `export const FANSLY_MIRROR_BUILD: string | null` (the main bundle hash). Both carry the OF files' "Generated by …; do not edit by hand." line. Titles are `<Section label>` or `<Section label>: <Sub label>`, States `<base title>: <State label>`, labels sentence-cased from the slug.
- **Route table** (Fansly path → section/sub; `<u>` = the creator's username, `:id` = a 15–20 digit snowflake):
  | Fansly | Section / sub |
  |---|---|
  | `/home` | `home` / `` |
  | `/<u>`, `/<u>/posts` | `profile` / `` |
  | `/<u>/media`, `/<u>/media/pictures`, `/<u>/followers`, `/<u>/following` | `profile` / same rest |
  | `/post/:id` | `profile` / `post` |
  | `/messages`, `/messages/:id` | `messages` / ``, `thread` |
  | `/notifications` (+ tab segments) | `notifications` / `` (+ rest) |
  | `/creator/vault`, `/creator/vault/:id` | `vault` / ``, `album` |
  | `/creator/stats/<x>` | `statistics` / `<x>` (index `overview`) |
  | `/creator/trackinglinks` | `tracking-links` / `` |
  | `/creator/coperformers/:id` | `creator` / `coperformers/detail` |
  | `/creator`, other `/creator/<rest>` | `creator` / ``, `<rest>` |
  | `/scheduled`, `/lists`, `/lists/:id`, `/bookmarks`, `/bookmarks/<n>`, `/subscriptions` | own section / ``, `list`, `<n>` |
  | `/settings/<tab>` | `settings` / `<tab>` (index `account`) |
  Sections: `home`, `profile`, `vault`, `messages`, `creator`, `statistics`, `tracking-links`, `subscriptions`, `bookmarks`, `settings`, `scheduled`, `lists`, `notifications` (issue 05 §1; the last three are the Built pages' landings, generated but routed by Phase 4). Explore, FYP, search, tag, affiliates, leaderboard, `/live/*`, legal and other users' profiles are not mapped: a link to them becomes `#`; a manifest entry for them fails the run. A State whose parent is a Built landing (`/lists`, `/scheduled`, `/notifications` index) is still generated and wired on its generated landing page, which Phase 4 does not serve, so it is reachable only from mirror pages that Phase 4 dispatches (`lists/list`); this Phase does not re-parent it.
- **Generic parts copied from `scripts/of-mirror.mjs`** (ADR-0066), not imported: `fail`/arg parsing, the `mapHtml` tokenizer and a `rewriteTag` over it, `element`, `fakeNumbers`/`fakeMoney`/`lorem` and the fixed fake buckets, `selfTest`, `guard` (extended), `check`, stage-and-swap. No new dependency; Node built-ins only, as the OF generator.
- **Opener matching.** Over `mapHtml`'s element stack of the State's parent page. The `opener` (the CSS selector Phase 2's `tclick` used) is matched by the selector forms the Tracer facts list under `opener_forms` (starting set: compound simple selectors of tag, `#id`, `.class`, `[attr]`, `[attr="v"]` joined by descendant spaces); first match in document order. Other selector syntax, a State entry with no `opener`, or no match fails the run naming the entry id. Close controls in a State page: the overlay's buttons whose text or `aria-label` is Close, Cancel, × or Done.
- **Resolve, then scrub, per document.** Pass 1 on the raw document: resolve every URL sink to its final target (route table needs the real username and snowflakes), match openers and close controls, and tag avatar, banner and rail (`data-oi-*` attributes, link targets written in place). Pass 2: drop dead nodes, comments and attributes → people needles (manifest identities, then collected others) → rule-table text → numbers/money/emails/inputs → media and assets → canvas → overrides and boot script. Pass 2 never reads attributes pass 1 wrote except to keep them. People needles are collected from every document before any page is scrubbed, so a name seen on one page is scrubbed on all.
- **Tracer facts.** The dark marker, the avatar/banner/rail hooks, the text-rule class words and the opener forms are generator constants set from the Tracer facts section of `fansly/capture/RECIPES.md` (Phase 2 story 39), names only. The fixture uses those same names.
- **Text rule table.** Kind-keyed (`name`, `handle`, `text`, `bio`, `list`, `note`, `session`, `bank`) and matched on class tokens or custom-element tag names by word (`message`, `post-text`/`post-content`, `bio`/`about`, `username`, `display-name`, `list-name`, `note`, `session`, `payout`/`tax`/`bank`). Over-matching costs only look. A long text node (20+ characters or 3+ words) no rule touched fails the run unless its element path is on `KEEP_TEXT_PATHS` (a generator constant the coordinator fills from the real capture); the fixture keep list holds the fixture's UI copy only.
- **Dark marker.** One generator constant names Fansly's dark-theme marker (a root class or attribute, Tracer facts `dark_marker`); the boot script adds it on `<html>` when `parent.document.documentElement.getAttribute("data-theme") !== "light"`, OF's add-only boot (`of-mirror.mjs` `THEME_BOOT`).
- **Stage and swap.** Refuse to start if `<out>.old` exists. Guard + completeness + unreviewed text on the stage and table text first; write both TS temporaries beside their targets; then rename `<out>` → `<out>.old`, stage → `<out>`, each TS temporary → its target, remove `<out>.old`. No rollback code: a crash mid-swap leaves `<out>.old`, which the next run refuses until the coordinator restores or removes it. Nothing before the first rename touches the old output; the stage and TS temporaries are removed on every exit unless the stage is kept by env.
- **Determinism.** Sorted directory walks, manifest order for entries, document order for Fan N, no timestamps or randomness in output.
- **Run hygiene.** The coordinator runs it at `nice -n 10`. The generator makes no network request; assets come only from the capture.

## Testing Decisions
- **One seam: the CLI of `scripts/fansly-mirror.mjs`**, driven by `app/lib/fanslyMirrorGenerator.test.ts` through `spawnSync(process.execPath, [script, ...])` with `--capture`/`--out`/`--lib` in a per-test temp dir; variants are made by copying the committed clean capture into the temp dir and editing its manifest or one page. Tests assert exit code, files written, output text and stderr, never internals. Cases:
  - clean capture → exit 0; layout, every captured entry has its page, a skipped entry has none and links to it are `#`, table and build TS content, NOTICE; then `--check` on that output exits 0.
  - no fixture identity value (usernames, display names, account ids, emails, IPs), no `fansly.com` host, no `data:` and no planted other-person name appears in any output file or path; `yourmodel`, `Your Model`, `data-oi-avatar`, `data-oi-banner`, `Fan 1`, `data-oi-nav` do.
  - snowflake routes collapse; mirrored links → `/fansly-manager/...` with `target="_top"`, unmapped → `#`, a captured redirect alias → its landing; built-landing links → their mirror path; a creator self-link and a snowflake link resolve (pass 1 on raw markup).
  - scrub rules: a fixture amount in text and in an attribute becomes a fake bucket; message, post, bio, note and list-name text becomes lorem; text input values, textarea and contenteditable text are gone; session, payout and tax fields blank; a 6+ digit attribute value is dropped while `_ngcontent-*`/`_nghost-*` and their inline-CSS selectors stay.
  - `ng-reflect-*`, comments, scripts, iframes, meta refresh, form action, object, srcset gone; canvas → placeholder; media and a raster `data:` image → `oi-blank.png`; a non-raster `data:` in CSS → a file under `static/<build>/data/`; CSS, font and SVG copied and rewritten; a missing asset ref blanked and listed; boot script present once.
  - a State's parent page carries an `oi-state-link` to the State page and the State page's backdrop and Cancel button link back.
  - `--check` on each file of `app/lib/__fixtures__/fansly-mirror/planted-leak/` (one kind per file) exits 1 and reports that file with its own kind, the union equals the full set of structural leak kinds, and stderr contains none of the planted values.
  - leaky capture (clean plus an unexpected IPv4 in a plain text node) after a clean run → exit 1, previous output tree hash and both TS files unchanged, no `.tmp` or `.old` left.
  - an existing `<out>.old` → exit 1 before any write.
  - unreviewed text: a planted long message in an unmatched element → exit 1 naming the element path, not the text; a short planted name in an unmatched element is still scrubbed by its people needle.
  - each refusal → exit 1, nothing written: `audit.passed: false`; `complete: false` with `audit.passed: true` (after a clean run: previous tree and TS files unchanged); a plan id in neither `entries` nor `skipped`; a `skipped` id not `optional` in the plan; missing `fan` role; duplicate `creator`; numeric `accountId`; creator username absent from the DOM; an entry `file` missing; unmapped route; two entries on one page; missing section root; opener with no match; mixed bundle hashes; dark marker already on a captured page; dark marker selector absent from every copied stylesheet. Identity refusals' stderr contains no identity value.
  - `--check` mutations of a clean output, each → exit 1: a listed page deleted, an unlisted page added, a linked static file deleted, NOTICE deleted, a `.old` dir beside it.
  - `--check` with the out dir absent: exit 0 with the "no mirror" line.
- `app/lib/fansly-mirror-pages.test.ts`: the OF pages-table test, skipping when `public/fansly-mirror/pages` is absent (always true until the real run, and on public).
- The served-browser check (non-localhost requests aborted before dispatch, State links landing, planted remote image as negative control, light/dark boot) is Phase 4's `render.py`, run on this Phase's output in the same PR.
- The in-script self-test runs on every invocation, so every vitest case also proves it.
- **Prior art:** `app/lib/ofMirrorCheckScripts.test.ts` (vitest spawning a process), `app/lib/of-mirror-pages.test.ts` (table↔files), `scripts/of-mirror.mjs` `selfTest`/`guard`/`check`, `scripts/of-mirror-check/plants/` (committed planted fixtures).

## Acceptance
```sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
F=app/lib/__fixtures__/fansly-mirror
node scripts/fansly-mirror.mjs --check
(cd app && pnpm exec vitest run lib/fanslyMirrorGenerator.test.ts lib/fansly-mirror-pages.test.ts)
T=$(mktemp -d)
nice -n 10 node scripts/fansly-mirror.mjs --capture "$F/capture" --plan "$F/capture/mirror_plan.json" --out "$T/fansly-mirror" --lib "$T/lib"
node scripts/fansly-mirror.mjs --check --out "$T/fansly-mirror" --lib "$T/lib"
rc=0; node scripts/fansly-mirror.mjs --check --out "$F/planted-leak/fansly-mirror" --lib "$F/planted-leak/lib" 2>"$T/plant.err" || rc=$?
[ "$rc" = 1 ] && grep -q 'ipv4' "$T/plant.err" && grep -q 'remote' "$T/plant.err"
[ -d "$T/fansly-mirror/pages" ]; rc=0; grep -rqiE 'fansly\.com|data:' "$T/fansly-mirror/pages" || rc=$?; [ "$rc" = 1 ]
git check-ignore -q app/public/fansly-mirror.tmp/x && git check-ignore -q app/public/fansly-mirror.old/x
git diff --quiet main -- scripts/of-mirror.mjs app/public/of-mirror app/lib/of-mirror-pages.ts app/lib/of-mirror-build.ts
scripts/run-tests.sh
# manual (coordinator, needs Phase 1 merged and a Phase-2 capture with manifest "complete": true):
#   nice -n 10 node scripts/fansly-mirror.mjs                     # reads ~/Downloads/fansly-live-capture
#   on an unreviewed-text failure: extend the text rule table or KEEP_TEXT_PATHS (from the capture's screenshots) and rerun until green
#   node scripts/fansly-mirror.mjs --check
#   Phase 4's render.py on the real output; review the per-page screenshots for real text left
#   LEAK_PROFILE=ae .claude/skills/public-sync/leak-check.sh --tree HEAD   # Phase 1's AE handoff: no `fail` hit inside app/public/fansly-mirror/
```

## Depends on
- Phase 1 — merged to main before this Phase's PR (map: gates PR first, then the mirror PR): `^app/public/fansly-mirror` in public/strip `NEVER_PATHS` and the `.tmp` ignore line. Phase 1's AE `$lock` assumption is settled by this Phase's first AE `--tree` run (manual Acceptance).
- Phase 2 Tracer facts — the coordinator's "Tracer facts" section in `fansly/capture/RECIPES.md` (dark marker, banner field, class hooks, opener forms, telemetry halts) before any code of this Phase is written (plan review 2026-11-27 reorder).
- Phase 4 — same PR: this Phase's code and Phase 4's ship together, the coordinator's real output committed in that PR before merge.
- Phase 2 — `fansly/capture/mirror_plan.json` (committed; the generator's default `--plan`) and the Mirror capture in `~/Downloads/fansly-live-capture/` with `manifest.json` (`audit.passed` and `complete` true) and `static/`. The capture is needed only for the coordinator's real run; the implementer codes against Phase 2's contract and the fixture.

## Out of Scope
- Real Fansly data rows and writes in mirror pages — later phase per the plan's "Not yet specified".
- Route, redirect table, frame, chrome, nav, flags, permissions, Identity swap runtime, theme hook, stand-in Creator, in-frame render/navigate/dark checks — Phase 4.
- `NEVER_PATHS`, `check-public-export.sh`, `docs/OPEN_SOURCING.md` — Phase 1.
- Capture, Capture gate, Gate audit and recovering shadow-root content outerHTML drops — Phase 2 (tracer spot-check, Fable 2026-11-26).
- Any change to `scripts/of-mirror.mjs` or a shared `mirror-guard.mjs` — rejected, ADR-0066 (YAGNI until the guards are seen drifting).
- A dark capture or a both-directions theme marker — Fable 2026-11-26 (light capture, add-only dark boot).
- Per-page DOM reconstruction like OF's — full documents need none (issue 03 a).
- Redrawing canvas charts from data — placeholder only in phase 1; real stats are later data work.
- Fan-side (:9232) UI, explore/FYP/search — plan out of scope.
- The OF mirror on public/Twin — parked for the owner.
- Swap rollback code and the `FANSLY_MIRROR_FAIL_AT` failpoint tests — deferred (YAGNI, six-hats): a crash mid-swap leaves `<out>.old`, which the next run refuses.
- Two-run idempotence check — deferred (YAGNI, six-hats); determinism rules stay.
- `--check --absent-ok` and the bootstrap-state split — deferred (YAGNI, six-hats): plain `--check` passes an absent dir.
- Nested States (State-in-State keys, Edit Post from the own-post menu) — deferred (YAGNI, six-hats), matching Phase 2's plan.
- `scripts/fansly-mirror-check/raw.py` as a separate script — merged into Phase 4's `render.py` (six-hats).
- A total asset size cap — rejected (six-hats White, partial): the 2 MB per-file cap stays and the summary prints total bytes; OF has no total cap.

## Further Notes
The consumed manifest shape under Contracts is Phase 2's (rung 1: `docs/spec/phase-02-fansly-mirror-capture.md` Contracts, the producer).
ASSUMPTION: the opener forms the tracer recorded cover every `opener` `tclick` records in the full capture (rung 1 for the tracer pages, rung 5 beyond them); overturned by the real run's "unknown opener syntax" refusal, in which case the matcher learns that syntax.
ASSUMPTION: unmatched text of 20+ characters or 3+ words fails the run unless keep-listed, and shorter unmatched text is left as is, relying on people needles and the screenshot review for short names (rung 4: a red run is cheaper than a published message; the threshold is a guess); overturned if the real capture shows short private text the needles miss, in which case the threshold drops or short text in content regions is lorem'd.
ASSUMPTION: copied assets are only what Phase 2 collects (CSS, fonts, SVG; rung 1, Phase 2 story 34); UI rasters become the blank image; overturned if the screenshots show a missing UI raster the copy needs, which would need Phase 2 to collect it.
ASSUMPTION: a missing or over-cap asset reference is blanked and listed rather than failing the run (rung 4: OF blanks, and a missing font must not block the mirror); overturned if a blanked asset breaks a page's look, in which case that asset kind fails instead.
ASSUMPTION: closing controls in a State page are found by button text or `aria-label` Close/Cancel/×/Done (rung 5); overturned by the real DOM, where a class hook may be better.
ASSUMPTION: guard and refusal messages print file and kind but never the matched value, for every kind, not only identities (rung 4; OF prints values); overturned if debugging the real run needs values, via an opt-in env that prints to the terminal only.
ASSUMPTION: the text rule table's class/tag words come from the Tracer facts `class_hooks` for the five tracer pages (rung 1 once recorded), and the unreviewed-text failure makes the coordinator extend it or `KEEP_TEXT_PATHS` for pages beyond the tracer at the real run; overturned if the tracer pages' hooks do not carry over to the rest, which only grows the rule table.
ASSUMPTION: avatar, banner and rail are found by the Tracer facts hooks, falling back to image `alt`/`src` naming the creator, `banner`/`cover` class words and a nav/sidebar landmark, and a profile root with no avatar or banner tag (or no rail on any page) fails the run (rung 1 for the tracer hooks, rung 5 for the fallback).
ASSUMPTION: the dark marker is one constant taken from the Tracer facts `dark_marker`, enforced by the "selector unused" refusal (rung 1 once recorded); if the tracer records "stylesheet swap", add-only boot cannot work and the dark copy is parked for the owner before this Phase's code starts.
ASSUMPTION: mixed bundle hashes fail rather than pick one (rung 4: re-capture is cheaper than debugging mixed CSS; OF picks the latest); overturned if Phase 2 cannot capture all pages on one build.
ASSUMPTION: `/post/:id` maps to `profile/post` (issue 05 §1) rather than issue 03's `post/post`, since 05 fixed the section list later (rung 2, later ticket).
ASSUMPTION: an unexpected IPv4 in plain text is a guard failure, not something the scrubber rewrites, so a surprise field stops the run for a human (rung 3: OF scrubs IPs only in known session fields).
ASSUMPTION: `--check` passes whenever `app/public/fansly-mirror/` is absent (rung 5, coordinator trim 2026-11-27), so a mirror deleted on private main or AE is not caught here; Phase 4's `render.py` and its Acceptance (`app/public/fansly-mirror/pages` must exist) catch it. Overturned if a deletion reaches AE unnoticed, which brings back the `--absent-ok` split.
The raw browser check (issue 03 c) lives in Phase 4's `render.py`, not here (coordinator trim 2026-11-27, six-hats Green).
The `.tmp` ignore line is Phase 1's (rung 1: `docs/spec/phase-01-fansly-mirror-never-public.md` Owns); this Phase adds only `.old`.
ASSUMPTION: attributes not written `name="value"` or bare fail the guard rather than being parsed, since Chrome's `outerHTML` always double-quotes (rung 5: OF's tokenizer reads only double quotes); overturned if a real capture page fails on it, in which case the tokenizer learns single and unquoted values.
ASSUMPTION: the empty committed table and `null` build (story 38) stay the first commit of the joint Phase 3+4 PR, so both Phases' code and tests run against them before the coordinator's real output is committed in the same PR (rung 4, additive; coordinator 2026-11-27: Phase 3+4 one PR); overturned if the real output cannot be produced before that PR is ready, in which case the empty-table commit merges alone.

## Review
codex (`codex exec`, read-only sandbox, reasoning high), 2026-11-27. Blind call on the plan and source only; draft call on this spec without this section. In the draft call codex read the sibling specs through `git show HEAD:docs/spec/...`, so the workspace was not fully blind through git objects. Mid-reconcile, Phase 2's own review moved its manifest onto this spec's consumed shape (Phase 2 Review D5), so D1 below is settled against Phase 2 as it now stands.
- B1 Tracer: an overlay that opens and closes in the served mirror with zero off-origin requests — **accept**: `raw.py` maps Manager paths through the pages table, clicks every `oi-state-link`/backdrop/close control and asserts the landing page (story 45).
- B2 Phase 1 not landed in this checkout — **partial**: already a dependency; tightened to merge-after under D12.
- B3 Use a real HTML/CSS parser, OF's tokenizer reads only double-quoted attributes and drops nothing for comments — **partial**: keep the copied tokenizer (ADR-0066, no new dependency), but the guard fails any attribute not double-quoted or bare and any HTML comment, and the scrubber drops comments (stories 26, 33, 34; ASSUMPTION in Further Notes).
- B4 Shared validator with OF — **reject**: ADR-0066 decides copy, not share; OF's policy deliberately differs (external handoffs, `data:` links).
- B5 Input proof: bind audit to manifest, check against the decided inventory, dispositions for unavailable States and collisions — **accept** in part: `audit.passed` and `complete` both required, `entries` ∪ `skipped` must cover `mirror_plan.json` with skips only for `optional` ids, skipped ids produce no page and links become `#` (stories 2, 6); collisions and mixed hashes were already refusals. The WAF-POST vs audit question is **reject** here: it is the gate's rule, owned by Phase 2.
- B6 Artifact policy — **partial**: filenames and titles are output, so the guard scans output paths for needles (story 34); `--check` without capture needles was already stated; form submission to the current origin is **reject** (same-origin `#`/Manager targets leak nothing, `action` is dropped anyway); private text without a pattern is handled by the unreviewed-text failure (D4) with a short-text residual flagged.
- B7 Navigation and publication: who owns cancel/back links, interrupted publish across tree and two TS files — **accept**: close controls link back (story 13, Opener matching), swap rollback and `.old` refusal (story 36, Stage and swap).
- B8 Plant each leak independently, plus missing asset and interrupted publish — **accept**: one planted file per kind with file↔kind asserted, `--check` mutations, rollback failpoint cases (Testing Decisions).
- B9 Served Chromium check of styles, font, icon, chart placeholder, overlay; keep screenshot and request log — **partial**: `raw.py` saves screenshots and the request log and runs the light/dark boot check (story 45); shadow-root/iframe counts are listed in the summary for the coordinator; per-region fidelity assertions are left to the coordinator's screenshot review, since the real DOM is not in the repo.
- D1 Phase 3 rejects Phase 2's capture format — **accept**: Contracts now cite Phase 2 as producer and match its current manifest (`audit`, `complete`, `entries[].file`, `skipped[]`, `assets[]`, `opener` as the `tclick` selector, plan ids); fixture uses that layout.
- D2 A passed partial capture can replace a complete mirror — **accept**: `complete: true` required and a test proves an audited incomplete capture leaves the previous output intact (story 2, refusal list).
- D3 A failed swap can half-publish; story 36 contradicts KEEP_STAGE — **accept**: ordered swap with in-memory TS backup and rollback, `FANSLY_MIRROR_FAIL_AT` failpoint tests every post-rename step, story 36 names the env exception (Stage and swap, Interfaces).
- D4 Free-text review happens after publication — **accept**: unmatched long text fails the run unless keep-listed, reported by element path only; fixture plants short and long cases (stories 20, Text rule table, Testing). Short-text residual flagged ASSUMPTION.
- D5 Scrub order destroys inputs later steps need — **accept**: resolve links, openers, close controls and identity tags on the raw document first, then scrub (Resolve, then scrub).
- D6 State model cannot represent Edit Post from the overflow menu; List States parented to a Built `/lists` — **accept** for State-to-State (a parent may be a State; story 13, keys in Contracts, nested-State test); **partial** for List States: generated and wired, reachable only via mirror pages Phase 4 dispatches, consistent with Phase 4's exact-path Built dispatch (route table note).
- D7 URL contract widens ticket 03's allowlist with `data:`; copied SVG outside the scan — **accept**: no `data:` survives (non-raster extracted to `static/<build>/data/`, raster blanked to `oi-blank.png`), guard allows only `#`, Manager routes and existing static files, copied SVG gets the full sink checks (stories 27, 28, 33, 34).
- D8 `--check` green on a deleted private mirror — **accept**: absent passes only with `--absent-ok` or in the bootstrap state; `--check` mutations for stale table entry, missing asset, missing NOTICE, leftover `.old` (stories 40, 41, Testing; ASSUMPTION).
- D9 Acceptance can finish green after failures — **accept**: `set -euo pipefail`, explicit `rc` checks for expected failures with diagnostic greps, directory guard before the negative grep, `git diff --quiet main --` (Acceptance).
- D10 No egress fence in the raw browser precedent — **accept**: non-localhost requests aborted in `context.route` before dispatch, with a planted remote image as negative control (story 45, Testing).
- D11 Scrub and theme behaviour untested — **accept**: CLI cases for money in text and attribute, text-rule kinds, input/textarea/contenteditable, payout/tax/session, 6-digit attribute vs `_ngcontent`, missing section root, opener with no match, dark selector absent from CSS; `raw.py` checks the dark marker under a same-origin parent in both themes (Testing, story 45).
- D12 Phase 1 dependency weakened and `.tmp` ignore claimed twice; AE tree check omitted — **accept**: merge after Phase 1, `.tmp` left to Phase 1 (Owns, story 44, Further Notes), AE `--tree` run added to manual Acceptance and Depends on.
- D13 UI rasters and the 2 MB cap have no producer contract — **accept**: copy only what Phase 2 collects (CSS, fonts, SVG); UI rasters become the blank image; missing or over-cap refs are rewritten to blank or `none` and listed, so completeness still holds (story 28; ASSUMPTIONs).
Counts (headline verdict per finding): accept 17 (B1, B5, B7, B8, D1–D13), partial 4 (B2, B3, B6, B9), reject 1 (B4), needs-human 0. Split parts: B5's WAF part, B6's form-origin part and D6's List-State part are the split-off reject/reject/partial.

### Six hats (plan review, 2026-11-27)
Story numbers in the codex lines above refer to the pre-trim draft (47 stories; now 45).
- White, unresolved guesses (dark marker, class names, opener syntax) — **accept**: each is now a Tracer facts constant measured by Phase 2's live tracer before this Phase's code (Depends on, Tracer facts decision, Further Notes rewritten).
- White, no asset size budget — **partial**: the 2 MB per-file cap stays and the summary prints total bytes; no total cap, since OF has none and a budget without a measured size is a guess.
- Black, Phases 3/4 built on guesses — **accept**: same as White; Depends on now names the Tracer facts.
- Green, Phase 3 cuts (rollback failpoint tests, two-run idempotence, `--absent-ok`/bootstrap split, State-in-State nesting; `raw.py` into Phase 4's `render.py`; keep planted-leak self-test, unreviewed long text fail, URL sink allowlist) — **accept**: done as listed (stories 13, 36, 40; Stage and swap; Testing; Out of Scope).
- Reorder (Phase 3+4 one PR after the tracer) — **accept**: Depends on, Objective and the story-38 ASSUMPTION rewritten.
