# demo-shots

Regenerates the marketing-site product shots in `web/public/img/` from the real
app, fed a synthetic agency ("Northstar Studio") so every screen is busy and
believable. Nothing leaves the machine.

## Run

```sh
scripts/demo-shots/run.sh                               # every screen: capture, compose, encode
scripts/demo-shots/run.sh --only dashboard,creators     # a subset (slugs from screens.py)
scripts/demo-shots/run.sh --keep-png --no-encode        # PNGs only, in .scratch/demo-shots/png/
scripts/demo-shots/run.sh serve                         # start the stack and wait (prints its URLs)
```

Needs the repo's `venv/` (uvicorn, FastAPI, Playwright with Chromium), `node`
with `app/node_modules`, `cwebp` and `magick` (`brew install webp imagemagick`).
A full run takes about 6 minutes. It exits non-zero if any shot fails its
checks; the failing shot's PNG is still written so you can see why.

Environment:

- `DEMO_SHOTS_NOW=2026-10-22T22:40:00Z` pins the time anchor. By default it is
  the latest 22:40 UTC that has passed, so "today" is nearly over and the
  period comparisons are not dragged down by a day that has just begun. The
  dataset, the seed and the browser clock (`ctx.clock.install`) all use it.
  Same seed and anchor give the same figures.
- `DEMO_SHOTS_PROBE='<js expression>'` prints its value per shot (debugging).

Outputs per screen in `web/public/img/`: `<slug>.webp` 1280x800, `-640`
640x400, `-phone` 390x844, `-phone-780` 780x1688, `-combo` 1440x900 (the phone
at ~24% width over the desktop's bottom-right, 5px dark ring, rounded corners,
soft shadow, solid page background) and `-combo-720` 720x450. Captured at
device scale 2 and encoded with `cwebp -q 80 -m 6 -sharp_yuv` after a Lanczos
resize.

## Files

| File | Role |
|---|---|
| `run.sh` | Starts the throwaway stack in a temp dir, seeds it, runs capture.py, tears down and restores `app/tsconfig.json` and `app/next-env.d.ts` (which `next dev` rewrites). |
| `relay_guarded.py` | The relay on a temp SQLite DB with network guards and the secret store and `sessions/` redirected into the temp dir (same model as `scripts/ui-shots.sh`). |
| `fetch-guard.cjs` | Preloaded into `next dev`: refuses any non-loopback request and logs it. |
| `dataset.py` | The synthetic agency, built from a fixed seed relative to the anchor. |
| `seed.py` | Writes the dataset into the relay's DB and API (sales, messages, shifts, clock events, scripts, posts, links, roles, employees). |
| `fixtures.py` | Answers, from the same dataset, what the relay would fetch live from OnlyFans (`/api/of/*`) plus the few `/admin/*` reads that depend on OF or on the real clock (health, auto-follow stats, automation rules, OF tracking links, S4S discover, errors, roster counts, referrals, and the manager's `/admin/shifts/me`), so totals agree across pages. |
| `screens.py` | The 23 screens: route, session, viewport, texts that must be visible (`placeholder=` for input hints), texts that must not ("$0.00", "No creators", "Jumping to latest"), clicks and scrolls, a minimum bubble count for the Messages Pro thread, and the key figure the combo phone must not cover. |
| `capture.py` | Playwright: light mode, the owner signed in (the dashboard shot signs in as manager Jordan Lee, whose My shifts card has shifts), cursor and dev overlays hidden, animations off; waits for the data, rejects loading skeletons, checks the app font (next/font's Instrument Sans face loaded, first in body's font-family, and painting a visible text node per CSS.getPlatformFontsForNode), then composes and encodes. Combos put the phone bottom-right and lower it, or move it bottom-left, if it would cover the shot's key figure. |
| `assets/` | Avatars and photos served to the browser from `https://demo-assets.invalid`, so no image is fetched from the internet. |

## Safety model

- The relay and `next dev` run on loopback with guards that refuse any
  off-host connection. Each run uses a fresh temp DB, a redirected secret store
  and a temp `sessions/` dir. No real account, session or secret is read or
  written.
- The browser routes every request: app and relay on localhost pass, the
  asset host is served from `assets/`, `/api/of/*` gets fixtures, and anything
  else is aborted and counted (`off-host requests aborted: 0` in the log).
- Unmatched OnlyFans reads are listed at the end of a run. They get no answer,
  and the app shows their empty state.

## Dataset

20 creators earning $1,000,419.71 net month to date (Oct 1 to the anchor),
skewed from $180,000 to $8,000. There are 12 employees (owner, 2 managers,
9 chatters) with shifts and 435 clock events, and 2,600 fans on 18,703
subscriptions. The 62,494 sales span the 35 days to the anchor, with a mild
upward trend, and there are 150,437 messages. Also included: 14 scripts,
8 vault folders with 40 photos, 18 posts, 5 auto posts, 47 tracking links,
7 smart messages, 12 S4S partners and roles. The Messages Pro thread (Ava and
Carlos K.) has 12 short fan and creator lines with a photo, a paid $45 PPV
and a $50 tip; its desktop shots use a 1600x1000 viewport so 9 or more
bubbles fit. Every name, handle,
id, amount and message is generated.

## Asset sources and licences

Downloaded once and committed here; runs never fetch them again.

- **Portraits:** pravatar.cc (`https://i.pravatar.cc/300?img=<id>`). The images
  are from Unsplash and offered by pravatar.cc under CC0. The ids are listed in
  file order.
  - `creator-01..20`: 5 9 16 19 20 21 23 24 26 27 28 29 30 32 36 38 42 44 45 47
  - `employee-01..12`: 12 8 31 13 18 34 35 48 49 52 53 59
  - `fan-01..30`: 3 7 11 14 15 17 33 51 54 55 56 57 58 60 61 62 63 64 65 67 68 69 70 1 6 50 22 10 41 43
  - `partner-01..12`: derived locally from `creator-09..20`, mirrored with
    slightly lower saturation (`magick -flop -modulate 100,92,100`).
- **Photos:** picsum.photos (`https://picsum.photos/id/<id>/...`), Unsplash
  License. The ids for `media-01..40`, in file order, are: 64 65 91 103 129
  177 203 212 225 237 247 256 274 287 292 305 309 314 319 325 338 342 352
  360 367 380 399 401 416 429 445 453 469 488 513 517 550 628 659 823.

## Known quirks (product behaviour, not the generator)

- The owner's "My shifts" card on the dashboard is empty by design (owners
  have no shifts), so the dashboard shot signs in as a manager; a chatter-side
  session hides the clocked-in and scheduled-hours cards. Fan reports'
  "Total fans" card reads no data by design.
- Messages Pro's "Jumping to latest" chip can stay up when the list refetches
  within its 5s backstop, because the timer lives in an effect keyed on
  `messages`. `screens.unpin` ends it with a real mouse wheel over the thread.
- OF Manager's feed renders inside an iframe, so its checks use `frame_wait`.
- The login page is dark by design.
