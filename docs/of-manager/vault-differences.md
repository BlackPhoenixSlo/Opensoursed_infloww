# OF Manager Vault: where it still differs from live OnlyFans

As of 2026-10-17, after f610bea5 (sort menu, phone Back, folder title, fresh media, viewer), 6cef35a7 (cache then
revalidate on open) and b199b415 (folder Search, Go to date, Customize order, composer folder title).

Ground truth came from OF's web bundle (lazy chunks 362, 7108, 99459, 40906 and app.js modules 393607, 463670,
551564), a static REA read of Infloww 1.3.6's app.asar, read-only relay GETs and the committed OF page captures.
No live OF tab was driven on the Vault, so nothing below was watched on onlyfans.com itself.

## Needs action

- **Relay on 8787 runs main.** Folder Search (`query`) and Go to date (`beforePublishDate`) need relay code from
  b199b415. Until the relay runs it, both are ignored silently and show unfiltered results.

## Behaviour that differs

- **Folder Search:** opening a folder from the search results drops `?slist=`; OF probably keeps it.
- **Folder Search in the composer vault pickers** is wired in New post, Home and a chat's or New message's picker, with
  the same `?slist=` → `query` as the Vault page. The generator still greys the chat pickers' buttons; the bind turns
  them back on.
- **Go to date** opens OF's day popup (`ofMirrorDatepicker`, one day, from the model's first day to today). The label's
  YYYY-MM-DD format is unconfirmed against OF. How OF combines a date with `sort=asc` is unknown (its bundle just
  sends both).
- **Customize order:** every folder is draggable, including Stories, Messages, Posts and Streams; only All media is
  pinned. No keyboard reordering. The live Save (a write to OF) was never sent in testing; only its body was checked.
- **Media viewer** is a plain overlay over `/img`, not OF's PhotoSwipe / video.js look. Previous / next buttons and
  ← / → step through the folder's loaded tiles; Escape closes it. That a tile click opens a viewer on OF was inferred
  from OF's tile classes.
- **Phone Back** in an open folder copies the folder column's Back; OF's phone markup isn't in the captures.
- **Ascending/Descending** are disabled only for the Custom sort, per OF's code. Not watched live.
- **Folder sort with Ascending** was not tested live (the reversible test used Name + Descending, then restored
  Recent + Descending; both confirmed).

## Freshness

- Vault grid: always read with `refresh=1`.
- Vault folder list and composer vault pickers: cached copy first, then one `refresh=1` re-read per page open
  (1 extra OF GET on the Vault page, 2 per composer picker).
- Messages Pro's picker keeps its manual "↻ refresh" button.

## Not verified live

Sort menu stacking, phone Back, the viewer, refresh behaviour, folder Search and Go to date were all built from
OF's code and captures. A logged-in OF tab on Chrome :9222, opened on the Vault, would let REA confirm them passively.
