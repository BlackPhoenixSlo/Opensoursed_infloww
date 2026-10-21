# Messages Pro look and feel: close the visible differences to Infloww, keep our improvements

Goal: a person who knows Infloww's Messages Pro opens ours at 1440 and 390 and sees Infloww,
plus clearly marked Inflowwww extras. Follow-on to `docs/plans/messages-pro-parity.md`
(Phases 0–7 done, parity doc at `docs/messages-pro-parity.md`). Same floors as that plan:
no push, no live OnlyFans, synthetic data only, colours never enter the Geometry token module,
untrusted ground truth stays in the capture folder and is never copied into the repo.

Ground truth, in this order:
1. The real Infloww desktop captures of 2026-10-12 (the thread shot with Fan insights open and
   the empty-state shot). They hold real handles: read them, never commit them, never quote a
   name or handle from them.
2. The in-repo Clone `ui-redesign/infloww-exact/messages.html` / `messages.js` and the extracted
   Infloww stylesheet, for exact px, colours and fonts.
3. `docs/messages-pro-parity.md` for what is already known to differ.

Decisions already made (binding):
- Keep every Inflowwww extra in `app/lib/openinflowwwwExtras.ts`. Nothing we built is removed;
  it is restyled or moved so the Infloww skeleton reads first.
- Keep the Fan List cache and the background refresh exactly as they are (online dot, unread,
  signal from the cached list; no extra relay calls per row).
- Keep the Composer's free-preview divider and the PPV price field; they stay visible when the
  Composer is in PPV mode, styled as a Composer row in Infloww's typography.
- The Notifications panel inside the pane is ours and stays. It gains an on/off toggle in the
  Fan List header row; off shows Infloww's plain count badge only.
- Colours: Infloww's blue accent, grey bubbles and near-black shell become the Messages Pro
  default. Our purple stays available as the app-level theme accent outside Messages Pro.

Phase 0 — Measure and pin
- Side-by-side harness state: the existing `scripts/ui-shots.sh` gains no new state; instead a
  one-page `docs/screenshots/messages-pro-compare.md` places `clone-messages-pro.png` beside
  `messages-pro-desktop.png` and lists each visible difference with the Region, the Clone px,
  ours, and the ticket that owns it. Every item in Phases 1–5 below must appear here first.
- Colour inventory: list every colour literal used in Messages Pro JSX and map each to the
  Infloww value from the stylesheet. No code change yet.

Phase 1 — Colour and shell
- Accent, bubble, shell, divider and text colours in Messages Pro switch to Infloww's values
  (JSX only, per ADR 0001). Outgoing bubbles blue, incoming grey, PPV card grey with price line.
- Messages Pro hides the Inflowwww top bar when it is the open route at desktop width, so the
  Creator tabs row is the first row like in Infloww; the sidebar toggle, clock and avatar move
  into the Creator tabs row's right end (SFW toggle, language, pop-out already live there).
- Acceptance: colour check in `app/lib/messagesPro.test.ts` still finds no colour in tokens;
  harness `ok=True`; the compare page's colour rows all read "matched".

Phase 2 — Fan List rows and header
- Row layout as Infloww: avatar left with the online dot and spend under it, name + verified
  badge + handle on one line, ✕ at the right, one-line preview, time at the right, muted bell
  where muted. 96px rows. Our unread dot and owe dot become the row's left-edge markers in
  Infloww's size.
- Header row: Creator name left, gallery / search / + right, as Infloww. The "All inboxes"
  selector and the gear sit in the second row with "Newest first" and the sort/refresh icons.
- Notifications toggle: a small switch at the right end of the Online Fans / Notifications
  button row. On: the in-pane panel opens as today. Off: the button shows the count badge only
  and opens nothing (Infloww behaviour). Default on. Stored per Employee in the existing
  preferences key, no new storage key.

Phase 3 — Chat header
- Two-line header as Infloww: line 1 name, verified badge, edit pencil, with "Open in new tab",
  refresh and kebab at the right; line 2 status, star, bell, notes, pin, Gallery, Find.
- Our extras (trend, +, Persona ⓘ, All Models marker) move into the kebab menu or the "+"
  overflow, each keeping its "Inflowwww extra" title. The 44px flag-on shift goes away because
  nothing extra renders inline.

Phase 4 — Thread and bubbles
- Per-bubble action row on incoming messages: pin, reply, heart, translate, at Infloww's size
  and spacing, visible on hover at desktop and always on phone.
- Date dividers ("Sep 29", "Today") between days, Infloww style.
- Incoming avatar circle at the left of each incoming group; outgoing avatar at the right.
- "Jumping to latest…" pill stays (ours) but restyled to Infloww's chip.

Phase 5 — Composer
- Three rows as Infloww: row 1 emoji and gear left, AI, Scripts, timer right; row 2 the input
  with the "Press "/" + keyword to quickly search scripts" placeholder; row 3 the media/GIF/
  vault/calendar/tag/@/Aa/translate icons left and Send right.
- Our PPV button, price field and free-preview divider: the PPV button joins row 1 right of
  Scripts; when on, a fourth row shows the price field and the free-preview notice in Infloww's
  input styling. The "+" overflow gets its own placement token so it opens on-screen at 390
  (closes the Phase 7 gap).
- Fan insights slide-over at 390 fits the viewport (closes the 11px overhang).

Phase 6 — Sign-off
- Re-run the Messages Pro parity Acceptance blocks (Phases 1–7 of the parent plan) on the final
  commit; flag-on sweep; phone and desktop shots; `docs/messages-pro-parity.md` regraded with
  the compare page as evidence. Any Region still "partial" names the remaining px difference.
