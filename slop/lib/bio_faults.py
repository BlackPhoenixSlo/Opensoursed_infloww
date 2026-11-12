"""Bio pages' break-it-once faults (scenarios/2026-11-11-bio-pages-public.py, 2026-11-11-bio-pages-editor.py):
lib/faults.py merges `register(Fault)` into FAULTS. Each patches a module attribute of service/bio_pages looked up at
call time. A fault is applied in both the relay (lib/relay.py) and the bio process (lib/bio.py); the public ones
patch bio_pages.app's modules, the admin ones (relay-side bio_pages.admin) do nothing in the bio process. The check
names live here and the scenarios import them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

import os

BIO_PAGE = ("bio pages: every page GET answers 200 html whose bootstrap block == the oracle's (username, tracking "
            "code, profile path) for its host and path; a bare root on a primary or spare host is the neutral stub")
BIO_PROFILE_JSON = "bio pages: every Profile JSON answer == the oracle's bytes (v2's public-profile.js shape)"
BIO_REVEAL = ("bio pages: every Reveal let through answers 200 {realUrl} == the oracle's destination for that link, "
              "tracking id and visitor location (script.js's trackingId rule, geo rules)")
BIO_NO_LEAK = ("bio pages: no answer but a Reveal 200 and no bio.log or relay.log line holds any seeded destination "
               "(`slopdest-` token)")
BIO_COUNTS = ("bio pages: nothing dropped: per (profile, link, UTC day) bio_daily views == seeded + ping 204s and "
              "clicks == seeded + Reveal 200s")
BIO_LIMIT = ("bio pages: no visitor is ever refused; each abuser gets exactly the limit of Reveals and of pings, "
             "the rest 429 Too many requests; its cross-origin 403s count none")
BIO_TLS_ASK = ("bio pages: /internal/tls-ask over the real rows: no/blank/bad domain 400, primary/spare/live custom "
               "200, pending/unknown 404")
BIO_ISOLATION = ("bio pages: BIO_PORT answers no relay route (page html or a 404) and the relay port answers no bio "
                 "route")
BIO_NO_5XX = "bio pages: no 5xx or transport error on any bio call"
BIO_SHARED_DB_NO_LOCK = ("bio pages: concurrent redirect clicks and fan DMs land exactly once; "
                         "relay logs no database is locked")
BIO_ESCAPE_TAP = ("bio pages: the Escape Overlay card (phone, avatar backdrop) has href instagram://extbrowser/?url= + "
                  "the escape target (https, the page's host, profile path + tracking code) only in iOS 17+ "
                  "Instagram with BIO_ESCAPE_TAP on, and each tap on it is one such navigation; no href and no "
                  "navigation on a tap in iOS 16 Instagram, iOS TikTok, Android Instagram or with the flag off; no "
                  "card in Safari; a page load alone navigates nowhere and Reveals nothing")
BIO_NO_OFFHOST_LOAD = ("UI: the public bio page requests nothing off-host; the only request leaving it is the "
                       "Continue navigation to the seeded destination host")

BIO_ADMIN_EDITS = ("bio editor: after every admin write the bio port's Profile JSON == the public view of the admin "
                   "answer P (display name, bio, mode, verified, avatar, links in P's order with their icons and "
                   "backgrounds)")
BIO_ADMIN_ORDER = ("bio editor: P's link order == each reorder PUT's ids and the bio JSON agrees; no visitor-read "
                   "Profile JSON drops or duplicates a link during reorders")
BIO_ADMIN_TENANCY = ("bio editor: the owner on another Agency's page/link ids gets 404 on every admin route, a chatter "
                     "403, and the other Agency's rows are unchanged")
BIO_ADMIN_STATS = ("bio editor: the list's 30-day views/clicks per page == SQL over bio_daily after load stops; the list "
                   "says serving (BIO_HEALTH_URL reaches the bio port)")
BIO_ADMIN_FILES = ("bio editor: every upload is served image/webp no bigger than its side, a replaced or removed "
                   "file and a deleted page's or link's files are gone from disk, a deleted link's Reveal is 404")
BIO_DRAIN = ("bio editor: a mid-load SIGTERM of the bio process (docker stop) loses no count: bio_daily == seeded + "
             "answered pings/Reveals, bio.log has no `drain lost` and no `counter flush dropped` but the orphan "
             "keys of deleted pages")
BIO_PUBLIC_URLS = ("bio editor: every list and P `public_url` (a live custom domain's `https://<domain>/`, else "
                   "BIO_PUBLIC_URL/<username>; a pending domain never) and its tracking URL `<public_url>/<code>` "
                   "answer 200 on the bio port with that URL's Host, bootstrap == the page's username and code")


def _bio_process() -> bool:
    return os.environ.get("DEMO_SHOTS_PROCESS") == "bio"


def _admin_reorder_drops_last() -> None:
    """A reorder writes every sort_order but the last id's (bug class: an off-by-one in the write loop). The answer P
    is read back from the DB, so it shows the wrong order honestly: only BIO_ADMIN_ORDER goes red."""
    if _bio_process():
        return
    from bio_pages import admin

    real = admin._write_order

    async def short(s, pid, ids):
        await real(s, pid, ids[:-1])

    admin._write_order = short


def _admin_no_owner_filter() -> None:
    """Remove the shared owner predicates, reaching page, link and file routes."""
    if _bio_process():
        return
    from bio_pages import admin
    from db.models import BioLink, BioProfile

    admin._own_profile = lambda owner, pid: (BioProfile.id == pid,)
    admin._own_link = lambda owner, lid, pid=None: ((BioLink.id == lid,) if pid is None else
                                                   (BioLink.id == lid, BioLink.profile_id == pid))


def _admin_delete_keeps_files() -> None:
    """File cleanup never runs (bug class: the unlink after commit skipped): replaced and deleted files stay."""
    if _bio_process():
        return
    from bio_pages import files

    files.remove = lambda *_a, **_k: None


def _admin_url_ignores_status() -> None:
    """The editor's URL uses the custom domain whatever its status (bug class: the `live` test dropped), so a
    pending domain that serves nothing is shown and linked: only BIO_PUBLIC_URLS goes red."""
    if _bio_process():
        return
    from bio_pages import admin

    real = admin._public_url

    def any_status(username, domain):
        return real(username, {**domain, "status": "live"} if domain else domain)

    admin._public_url = any_status


def _click_lost_1_in_20() -> None:
    """Every 20th Click write is dropped (bug class: the bounded event write swallowed, so the visitor still gets the
    destination and the stat is gone). `bio_pages.app` calls `store.record` through the module: every 20th `click`
    returns at once, writing nothing and logging nothing. Only BIO_COUNTS goes red."""
    import itertools

    from bio_pages import store

    real = store.record
    n = itertools.count(1)

    async def lossy(kind, *a, **k):
        if kind == "click" and next(n) % 20 == 0:
            return None
        return await real(kind, *a, **k)

    store.record = lossy


def _reveal_limit_off() -> None:
    """Reveal is never rate-limited (bug class: the click guard dropped): `guard.allow` always says yes."""
    from bio_pages import guard

    guard.allow = lambda _ip: True


def _json_leaks_destination() -> None:
    """The Profile JSON carries each Link's destination (bug class: a field allowlist widened, the leak v2's
    public-profile.js exists to prevent). `bio_pages.app` calls `decide.public_profile` through the module."""
    from bio_pages import decide, store

    real = decide.public_profile
    read = store.profile_with_links

    async def with_dest(username):
        found = await read(username)
        if found:
            profile, links = found
            for link in links:
                full = await store.link_by_link_id(link["link_id"])
                link["destination"] = full["destination"] if full else ""
            return profile, links
        return None

    def leaky(profile, links, *rest):
        out = real(profile, links, *rest)
        for pub, row in zip(out["links"], links):
            pub["destination"] = row["destination"]
        return out

    decide.public_profile = leaky
    store.profile_with_links = with_dest


def _escape_href_off_host() -> None:
    """The card's href is built from a URL other than the escape target (bug class: a Destination or another host
    handed to Instagram's open-in-browser link, what flagged links in-app): the served script.js points it at
    dest.slop.test, same path. Only the bio process serves it; the href is the only thing that changes, so only
    BIO_ESCAPE_TAP goes red."""
    if not _bio_process():
        return
    from bio_pages import app

    good = b"encodeURIComponent(target.url)"
    js = app.ASSETS["script.js"]
    if js.count(good) != 1:
        raise RuntimeError("bio-escape-href-off-host: script.js no longer builds the card href from target.url")
    app.ASSETS["script.js"] = js.replace(good, b"encodeURIComponent('https://dest.slop.test' + target.path)")


def _page_loads_offhost() -> None:
    """A served stylesheet imports an off-host asset; only BIO_NO_OFFHOST_LOAD goes red."""
    if not _bio_process():
        return
    from bio_pages import app

    app.ASSETS["style.css"] = b"@import url(https://cdn.slop.test/x.css);\n" + app.ASSETS["style.css"]


def register(Fault) -> dict:
    return {
        # slop/run bio-pages-public --break (the scenario's FAULT)
        "bio-click-lost-1-in-20": Fault(_click_lost_1_in_20, (BIO_COUNTS,)),
        # slop/run bio-pages-public --break --fault=<name>
        "bio-reveal-limit-off": Fault(_reveal_limit_off, (BIO_LIMIT,)),
        "bio-json-leaks-destination": Fault(_json_leaks_destination, (BIO_NO_LEAK, BIO_PROFILE_JSON)),
        "bio-escape-href-off-host": Fault(_escape_href_off_host, (BIO_ESCAPE_TAP,)),
        "bio-page-loads-offhost": Fault(_page_loads_offhost, (BIO_NO_OFFHOST_LOAD,)),
        # slop/run bio-pages-editor --break (the scenario's FAULT)
        "bio-admin-reorder-drops-last": Fault(_admin_reorder_drops_last, (BIO_ADMIN_ORDER,)),
        # slop/run bio-pages-editor --break --fault=<name>
        "bio-admin-no-owner-filter": Fault(_admin_no_owner_filter, (BIO_ADMIN_TENANCY,)),
        "bio-admin-delete-keeps-files": Fault(_admin_delete_keeps_files, (BIO_ADMIN_FILES,)),
        "bio-admin-url-ignores-status": Fault(_admin_url_ignores_status, (BIO_PUBLIC_URLS,)),
    }
