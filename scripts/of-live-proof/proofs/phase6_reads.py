from __future__ import annotations

import json
import urllib.error
from urllib.parse import parse_qs, urlsplit

from proof_core import Proof


TILE = "[data-oi-media] .b-photos__item__img"
RELAY_PATHS = ("/img", "/admin/vault-ai/thumb")
CDN_SUFFIXES = (".onlyfans.com", ".ofcdn.com", ".mycdn.dev")


def _cdn(host: str) -> bool:
    host = (host or "").lower()
    return host == "onlyfans.com" or host.endswith(CDN_SUFFIXES)


def thumbnails_check(seen) -> dict:
    out = []
    origins = set(seen.get("origins") or ())
    relay = [r for r in seen.get("responses") or [] if urlsplit(r["url"]).path in RELAY_PATHS]
    misses = {r["url"] for r in relay if r.get("cache") == "MISS"}
    cold = 0
    for shot in seen.get("images") or []:
        tiles = shot.get("tiles") or []
        if not tiles:
            out.append(f"{shot['page']}: no vault tile")
        for t in tiles:
            u = urlsplit(t.get("src") or "")
            if _cdn(u.hostname or ""):
                out.append(f"{shot['page']}: tile src on a CDN host {u.hostname}")
            elif f"{u.scheme}://{u.netloc}" not in origins or u.path not in RELAY_PATHS:
                out.append(f"{shot['page']}: tile src not through the Relay: {u.scheme}://{u.netloc}{u.path}")
            elif not (t.get("complete") and (t.get("width") or 0) > 0):
                out.append(f"{shot['page']}: tile did not load: {u.path}")
            elif u.path == "/img" and t["src"] in misses:
                cold += 1
    for r in relay:
        if r["status"] >= 400:
            out.append(f"{urlsplit(r['url']).path} answered {r['status']}"
                       + (" (host not allowed)" if r["status"] == 400 else ""))
    for o in seen.get("offhost") or []:
        host = urlsplit(o.get("url") or "").hostname or ""
        if _cdn(host):
            out.append(f"browser request to an OnlyFans CDN host: {host}")
    if not cold:
        out.append("no tile loaded through a cold /img (every /img tile was a disk-cache hit or a stored square)")
    return {"problems": out, "parked": None, "record": {}}


VAULT_THUMBNAILS = Proof(
    id="vault--thumbnails", phase=6, page="vault/index", control="Vault tiles (Vault page, New post vault dialog)",
    kind="live",
    trigger=(("images", TILE), ("goto", "new-post/state-vault"), ("images", TILE)),
    check=thumbnails_check,
)

NEEDS_CAPTURE = "needs capture (ticket 12 sitting)"


def _read(get, path: str, query=None) -> dict:
    try:
        return {"path": path, "status": 200, "body": get(path, dict(query or {}))}
    except urllib.error.HTTPError as e:
        return {"path": path, "status": e.code, "body": None}


def _rows(r) -> list:
    b = (r or {}).get("body")
    b = b.get("list") if isinstance(b, dict) else b
    return [x for x in b if isinstance(x, dict)] if isinstance(b, list) else []


def _img_u(src) -> str | None:
    u = urlsplit(src or "")
    return (parse_qs(u.query).get("u") or [None])[0] if u.path == "/img" else None


def _dom(seen, n: int) -> list:
    snaps = seen.get("dom") or []
    return (snaps[n].get("items") or []) if n < len(snaps) else []


def _squash(s) -> str:
    return " ".join(str(s or "").split())


def _loaded(item, page: str, out: list) -> None:
    for i in item.get("_imgs") or []:
        if _img_u(i.get("src")) and not (i.get("complete") and (i.get("width") or 0) > 0):
            out.append(f"{page}: picture did not load through the Relay: {_img_u(i['src'])}")


def _answers(seen, path: str) -> list:
    return [r["status"] for r in seen.get("responses") or [] if urlsplit(r["url"]).path == path]



TIP_TYPES = ("tip", "tipped")


def read_tips(get, fan) -> dict:
    return {t: _read(get, "/api2/v2/users/notifications", {"limit": 20, "offset": 0, "type": t}) for t in TIP_TYPES}


def tips_check(seen) -> dict:
    read, out = seen.get("of_read") or {}, []
    results = {t: {"status": (read.get(t) or {}).get("status"), "rows": len(_rows(read.get(t))),
                   "types": sorted({str(r.get("type")) for r in _rows(read.get(t))})} for t in TIP_TYPES}
    for r in results.values():
        r["answer"] = "refused" if r["status"] != 200 else "accepted" if r["rows"] else "accepted-but-empty"
    for t in TIP_TYPES:
        if results[t]["status"] != 200:
            out.append(f"OnlyFans refused the type={t} read: {results[t]['status']}")
        out += [f"OnlyFans's type={t} read has a {x} row" for x in results[t]["types"] if x not in TIP_TYPES]
    want = []
    for r in _rows(read.get("tip")):
        u = r.get("user") or r.get("fromUser") or {}
        text = str(r.get("text") or "")
        for k, v in (r.get("replacePairs") or {}).items():
            text = text.replace(k, str(v))
        want.append({"name": _squash(u.get("name")), "handle": f"@{u.get('username')}", "text": _squash(text)})
    page = _dom(seen, 0)
    got = [{"name": _squash(i.get("name")), "handle": _squash(i.get("handle")), "text": _squash(i.get("text"))}
           for i in page]
    if got != want:
        out.append(f"notifications/tip: the page shows {len(got)} rows that do not equal OnlyFans's {len(want)} "
                   f"tip rows: {[g for g in got if g not in want][:2] or [w for w in want if w not in got][:2]}")
    for i in page:
        if "icon-price" not in f"{i.get('icon') or ''} {i.get('icon_use') or ''}":
            out.append(f"notifications/tip: row {_squash(i.get('name'))!r} has no tip badge")
        _loaded(i, "notifications/tip", out)
    results["agree"] = got == want and not out
    parked = None
    if not out and not want:
        if results["tipped"]["rows"]:
            out.append("OnlyFans has tipped rows but no type=tip row: the Tips tab reads the wrong filter")
        else:
            parked = "no tip notification on the Proof Creator: type=tip and type=tipped accepted but empty"
    return {"problems": out, "parked": parked, "record": {"results": results}}


TIP_ROW = ".b-notifications__list .vue-recycle-scroller__item-view[data-oi-data]"
NOTIFICATIONS_TIPS = Proof(
    id="notifications--tips", phase=6, page="notifications/tip", control="Tips tab", kind="live",
    trigger=(("dom", ".b-notifications__list", TIP_ROW,
              (("name", ".b-username .g-user-name"), ("handle", ".g-user-username"),
               ("text", ".b-notifications__list__item__text .g-truncated-text"),
               ("icon", ".b-notifications__avatar__icon svg@data-icon-name"),
               ("icon_use", ".b-notifications__avatar__icon use@href"))),),
    of_read=read_tips, check=tips_check,
)



def _stubs(body) -> bool:
    return isinstance(body, list) and all(isinstance(x, dict) and "userId" in x and "storyId" in x for x in body)


def read_strip(get, fan) -> dict:
    m = _read(get, "/api2/v2/stories/map")
    stubs = m["body"] if _stubs(m["body"]) else []
    out = {"map": m}
    if stubs:
        out["items"] = _read(get, "/api2/v2/stories/items", {f"map[{s.get('userId')}]": s.get("storyId") for s in stubs})
    return out


def strip_check(seen) -> dict:
    read, out = seen.get("of_read") or {}, []
    relay = _answers(seen, "/api/of/v2/stories")
    refused = any(s >= 400 for s in relay) or not relay
    shown = _dom(seen, 0)
    record = {"relay_stories": "refused" if relay and refused else "not read" if refused
              else "empty" if not shown else "matching"}
    m = read.get("map") or {}
    if m.get("status") != 200:
        if shown:
            return {"problems": [f"home/index: the page shows {len(shown)} story tiles, OnlyFans's strip read "
                                 f"answered {m.get('status')}"], "parked": None, "record": record}
        return {"problems": [], "parked": f"OnlyFans's strip read answered {m.get('status')}: {NEEDS_CAPTURE}",
                "record": record}
    if not _stubs(m.get("body")):
        return {"problems": [], "parked": f"OnlyFans's strip answer is not a list of {{userId, storyId}}: "
                                          f"{NEEDS_CAPTURE}", "record": record}
    stubs = m["body"]
    if not stubs:
        if shown:
            return {"problems": [f"home/index: the page shows {len(shown)} story tiles, OnlyFans's strip is empty"],
                    "parked": None, "record": record}
        return {"problems": [], "parked": "no story on OnlyFans's own strip for the Proof Creator", "record": record}
    items = _rows(read.get("items"))
    tiles = {str(t.get("user")): t for t in _dom(seen, 0)}
    want = {str(s.get("userId")): s for s in stubs}
    out += [f"home/index: OnlyFans's strip has creator {u}, the page has no tile" for u in want if u not in tiles]
    out += [f"home/index: tile for creator {u} is not on OnlyFans's strip" for u in tiles if u not in want]
    for u, s in want.items():
        t = tiles.get(u)
        if not t:
            continue
        mine = [x for x in items if str(x.get("userId")) == u]
        media = [m_ for x in mine for m_ in x.get("media") or []]
        try:
            shown = len(json.loads(t.get("story") or "[]"))
        except ValueError:
            shown = -1
        if shown != len(media):
            out.append(f"home/index: creator {u}'s tile carries {shown} stories, OnlyFans {len(media)}")
        if bool(s.get("isWatched")) != ("m-viewed" in (t.get("viewed") or "").split()):
            out.append(f"home/index: creator {u}'s watched mark differs from OnlyFans's")
        first = next((x for x in mine if not x.get("isWatched")), mine[0] if mine else None)
        thumb = next((((x.get("files") or {}).get("thumb") or {}).get("url") for x in (first or {}).get("media") or []),
                     None)
        stills = [_img_u(i.get("src")) for i in t.get("_imgs") or []]
        if thumb and thumb not in stills:
            out.append(f"home/index: creator {u}'s tile still is not its story's picture")
        _loaded(t, "home/index", out)
    if out and record["relay_stories"] == "matching":
        record["relay_stories"] = "differs"
    return {"problems": out, "parked": None, "record": record}


HOME_STORY_STRIP = Proof(
    id="home--story-strip", phase=6, page="home/index", control="Story strip", kind="live",
    trigger=(("dom", ".stories-list", "button[at-attr='story_item'][data-oi-story-user]",
              (("user", "@data-oi-story-user"), ("story", "@data-oi-story"), ("name", ".b-story-item__text"),
               ("viewed", "@class"))),),
    of_read=read_strip, check=strip_check,
)



def read_highlights(get, fan) -> dict:
    me = _read(get, "/api2/v2/users/me")
    uid = (me.get("body") or {}).get("id") if isinstance(me.get("body"), dict) else None
    out = {"me": {"status": me["status"], "id": uid}}
    if uid is None:
        return out
    out["row"] = _read(get, f"/api2/v2/users/{uid}/stories/highlights")
    first = next(iter(_rows(out["row"])), None)
    if first and first.get("id") is not None:
        out["playback"] = _read(get, f"/api2/v2/stories/highlights/{first['id']}")
    return out


def highlights_check(seen) -> dict:
    read, out, branches = seen.get("of_read") or {}, [], {}
    row = read.get("row") or {}
    if row.get("status") != 200:
        why = f"OnlyFans's highlights read answered {row.get('status') or (read.get('me') or {}).get('status')}"
        return {"problems": [why], "parked": None, "record": {"branches": {"row": "fail", "playback": "fail"}}}
    hs = _rows(row)
    if not hs and _dom(seen, 0):
        why = f"profile/index: the page shows {len(_dom(seen, 0))} highlight tiles, OnlyFans has no highlight"
        return {"problems": [why], "parked": None, "record": {"branches": {"row": "fail", "playback": "fail"}}}
    if not hs:
        why = "no highlight on the Proof Creator"
        return {"problems": [], "parked": why, "record": {"branches": {b: f"parked: {why}" for b in ("row", "playback")}}}
    tiles, mine = _dom(seen, 0), []
    want = [(str(h.get("id")), _squash(h.get("title")), h.get("cover")) for h in hs]
    got = [(str(t.get("id")), _squash(t.get("title")), _img_u(t.get("cover"))) for t in tiles]
    if got != want:
        mine.append(f"profile/index: highlight tiles {[(i, n, bool(c)) for i, n, c in got]} differ from OnlyFans's "
                    f"{[(i, n, bool(c)) for i, n, c in want]}" + ("" if [g[:2] for g in got] != [w[:2] for w in want]
                                                                    else " (cover)"))
    for t in tiles:
        _loaded(t, "profile/index", mine)
    branches["row"] = "pass" if not mine else "fail"
    out += mine
    play, mine = read.get("playback") or {}, []
    body = play.get("body") if isinstance(play.get("body"), dict) else {}
    stories = [s for s in body.get("stories") or [] if isinstance(s, dict)]
    media = [m for s in stories for m in s.get("media") or []]
    viewer = next(iter(_dom(seen, 1)), None)
    if play.get("status") != 200:
        mine.append(f"OnlyFans's highlight read answered {play.get('status')}")
    elif not viewer:
        mine.append("profile/index: a click on the first highlight opened no viewer")
    else:
        if viewer.get("bars") != len(media):
            mine.append(f"profile/index: the viewer shows {viewer.get('bars')} bars, the highlight has {len(media)} stories")
        full = (((media[0] if media else {}).get("files") or {}).get("full") or {}).get("url")
        if _img_u(viewer.get("media")) != full:
            mine.append("profile/index: the viewer does not show the highlight's first story")
        _loaded(viewer, "profile/index", mine)
    branches["playback"] = "pass" if not mine else "fail"
    out += mine
    return {"problems": out, "parked": None, "record": {"branches": branches}}


HIGHLIGHT_TILE = "[data-oi-highlight]"
PROFILE_HIGHLIGHTS = Proof(
    id="profile--highlights", phase=6, page="profile/index", control="Highlights row and playback", kind="live",
    branches=("row", "playback"),
    trigger=(("dom", ".stories-list", HIGHLIGHT_TILE,
              (("id", "@data-oi-highlight"), ("title", ".b-story-item__text"),
               ("cover", ".b-story-item__inside > img@src"))),
             ("click", HIGHLIGHT_TILE),
             ("dom", "#oi-vault-viewer", "#oi-vault-viewer",
              (("bars", "[data-oi-story-bars] > span@*"), ("media", "[data-oi-viewer-media]@src"),
               ("title", ".b-story-header__author__title")))),
    of_read=read_highlights, check=highlights_check,
)



PAYOUT_FIELDS = ("invoiceId", "createdAt", "amount", "state", "rejectReason")
PAYOUT_STATES = ("approved", "pending", "rejected")
PAYOUT_PAGES = (("statements/payouts", "/api2/v2/payouts/requests"),
                ("statements/referrals", "/api2/v2/payouts/requests/referral"))


def read_payouts(get, fan) -> dict:
    return {page: _read(get, path, {"limit": 20, "offset": 0}) for page, path in PAYOUT_PAGES}


def _state(s) -> str:
    return "pending" if s in ("new", "pending") else str(s)


def payouts_check(seen) -> dict:
    read, out, record = seen.get("of_read") or {}, [], {}
    for n, (page, _path) in enumerate(PAYOUT_PAGES):
        r = read.get(page) or {}
        rows = _rows(r)
        f_seen = [f for f in PAYOUT_FIELDS if any(x.get(f) not in (None, "") for x in rows)]
        s_seen = [s for s in PAYOUT_STATES if any(_state(x.get("state")) == s for x in rows)]
        record[page] = {"status": r.get("status"), "rows": len(rows),
                        "observed": {"fields": f_seen, "states": s_seen},
                        "unobserved": {"fields": [f for f in PAYOUT_FIELDS if f not in f_seen],
                                       "states": [s for s in PAYOUT_STATES if s not in s_seen]}}
        if r.get("status") != 200:
            out.append(f"OnlyFans refused the {page} read: {r.get('status')}")
            continue
        shown = _dom(seen, n)
        if len(shown) != len(rows):
            out.append(f"{page}: the page shows {len(shown)} rows, OnlyFans {len(rows)}")
        for i, (x, t) in enumerate(zip(rows, shown), 1):
            if _squash(t.get("invoice")) != str(x.get("invoiceId") or ""):
                out.append(f"{page}: row {i} invoice {_squash(t.get('invoice'))!r} is not OnlyFans's")
            try:
                amount = float(_squash(t.get("amount")).lstrip("$").replace(",", ""))
            except ValueError:
                amount = None
            if amount is None or round(amount, 2) != round(float(x.get("amount") or 0), 2):
                out.append(f"{page}: row {i} amount {_squash(t.get('amount'))!r} is not OnlyFans's")
            marks = [s for s in PAYOUT_STATES if t.get(s)]
            if marks != [_state(x.get("state"))]:
                out.append(f"{page}: row {i} state mark {marks} is not OnlyFans's {x.get('state')!r}")
            if x.get("rejectReason") and f"Reason: {_squash(x['rejectReason'])}" not in _squash(t.get("text")):
                out.append(f"{page}: row {i} does not show OnlyFans's reject reason")
    parked = None
    if not out and not any(record[p]["rows"] for p, _ in PAYOUT_PAGES):
        parked = "no payout request or referral payout on the Proof Creator"
    return {"problems": out, "parked": parked, "record": record}


PAYOUT_ROW = ".b-table tbody > tr[data-oi-data]"
PAYOUT_DOM = ("dom", ".b-table", PAYOUT_ROW,
              (("invoice", ".b-table__invoice"), ("amount", ".b-table__amount strong > span"),
               ("approved", ".b-table__desc > span.approved@*"), ("pending", ".b-table__desc > span.pending@*"),
               ("rejected", ".b-table__desc > span.rejected@*"), ("text", "")))
STATEMENTS_PAYOUT_ROWS = Proof(
    id="statements--payout-rows", phase=6, page="statements/payouts", control="Payouts and Referrals rows",
    kind="live",
    trigger=(PAYOUT_DOM, ("goto", "statements/referrals"), PAYOUT_DOM),
    of_read=read_payouts, check=payouts_check,
)

PROOFS = (VAULT_THUMBNAILS, NOTIFICATIONS_TIPS, HOME_STORY_STRIP, PROFILE_HIGHLIGHTS, STATEMENTS_PAYOUT_ROWS)
