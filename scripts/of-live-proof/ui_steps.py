"""prove.py's UI step helpers (ticket 34): a goto page filled with this proof's created id, and a click whose confirm()
is accepted only when its text matches. Split out so prove.py stays under 1000 lines."""
from __future__ import annotations

import time
from urllib.parse import quote


def goto_target(page: str, rows, timeout_s: float = 30, sleep=time.sleep) -> str:
    """A goto step's Mirror page (ticket 34: it may carry a query), with `{id}` filled from the newest OnlyFans id this
    proof's Undo log rows recorded (`rows()`, polled until one has it: the created folder's page)."""
    if "{id}" not in page:
        return page
    end = time.time() + timeout_s
    while True:
        ids = [x["of_id"] for x in sorted(rows(), key=lambda x: x["row"]) if x.get("of_id") is not None]
        if ids:
            return page.replace("{id}", quote(str(ids[-1]), safe=""))
        if time.time() > end:
            raise RuntimeError(f"goto {page}: no OnlyFans id recorded by this proof's writes")
        sleep(0.25)


def click_confirm(page, loc, want: str, wait_ms: int = 5000) -> None:
    """An ("accept", sel, want) step: click `loc` and accept the confirm() it opens when its text holds `want`. Any other
    dialog is dismissed and the step fails, as it does when no dialog opens within `wait_ms`."""
    seen = []
    on = lambda d: seen.append((d.type, d.message)) or (d.accept() if d.type == "confirm" and want in d.message  # noqa: E731
                                                        else d.dismiss())
    page.on("dialog", on)
    try:
        loc.click(timeout=30_000)
        for _ in range(wait_ms // 50):
            if seen:
                break
            page.wait_for_timeout(50)
    finally:
        page.remove_listener("dialog", on)
    if not seen or seen[0][0] != "confirm" or want not in seen[0][1]:
        raise RuntimeError(f"accept: wanted a confirm holding {want!r}, got {seen[0] if seen else 'no dialog'}")


# The Mirror's vault tiles are clones of OF's captured tile, which carries loading="lazy": a tile below the fold never
# starts loading until it is scrolled near. Each poll brings the next tile not yet complete and not yet visited into view
# (marked data-oi-tile-seen), so every tile is exercised: a failed load is complete too, and a hanging one is passed over,
# so neither stalls the walk for the tiles after it.
_SEEN = "data-oi-tile-seen"
_TILES_LOADED = """s => {
  const all = [...document.querySelectorAll(s)];
  if (all.every(i => i.complete)) return true;
  const t = all.find(i => !i.complete && !i.hasAttribute("%s"));
  if (t) { t.setAttribute("%s", ""); t.scrollIntoView({block: "center"}); }
  return false;
}""" % (_SEEN, _SEEN)


def collect_tiles(fr, sel: str, timeout_ms: int = 30_000) -> list:
    """An ("images", sel) step: every matching <img> in frame `fr`, scrolled into view one by one until each loaded or
    failed (or `timeout_ms` passed: a tile that never loads is the check's to report), as {src, complete, width}."""
    fr.locator(sel).first.wait_for(state="visible", timeout=60_000)
    try:
        fr.wait_for_function(_TILES_LOADED, arg=sel, polling=100, timeout=timeout_ms)
    except Exception:  # noqa: BLE001  (a tile that never loads is the check's to report)
        pass
    tiles = fr.evaluate("s => [...document.querySelectorAll(s)].map(i => (i.removeAttribute('%s'), "
                        "{src: i.currentSrc || i.src, complete: i.complete, width: i.naturalWidth}))" % _SEEN, sel)
    fr.locator(sel).first.scroll_into_view_if_needed(timeout=5_000)   # the settled shot shows the grid's top again
    return tiles
