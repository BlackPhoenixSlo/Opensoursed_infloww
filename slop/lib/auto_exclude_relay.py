"""Auto_Exclude past the 20k paging backstop: this flow's part of the slop relay (lib/relay.py loads
it; `wire` runs at the end of its `_wire`). It adds methods to lib/automation_relay.py's offline
walker (the lane's OF client, `ax._make_client` without `OF_API_ORIGIN`) with
`WALKER_MIXINS.insert(0, ...)`; each one calls `super()` (the walker's own answer) unless the
scenario wrote `$DEMO_SHOTS_TMP/auto-exclude.json` and armed it (`POST /__slop/auto-exclude/arm`),
and then only for the Creators that file names.

`auto-exclude.json` {"page_ms", "add_ms", "accept_ms", "gap_s", "refresh_every_s",
  "accounts": {account: {"roster": [fan ids], "members": [the pre-made Auto_Exclude],
                         "refuse": [ids], "watch": [ids], "exact": bool}}}. Armed:
  subscribers(...)              OF's fans roster (`roster`, sorted, 50 a page): the send's recipient
                                crawl (`audiences.resolve_recipients_blocking`).
  list_users_in(...)            the walker's in-process list, after `page_ms` (a guess at OF's page).
  add_user_to_list(...)         after `add_ms` (a guess at OF's per-user add): an id in `refuse` is
                                OF's 403 "Unable to add user to user list" (a deleted / blocked
                                account, declared), never listed; else the walker's add.
  remove_user_from_list(...)    after `add_ms`, the walker's remove.
  send_mass_message(...)        OF accepts after `accept_ms`; AT ACCEPT the recipients are `roster`
                                minus every member of its `excluded_user_lists` (the walker's lists,
                                read then). Journaled: {ev: send, account_id, text, t, n, leak:
                                recipients ∩ watch, leak_excl: recipients ∩ the send's own
                                `excluded_users` (the product's guard), lists, and for an `exact`
                                Creator only members: the Auto_Exclude's members, excl: the
                                send's `excluded_users`}.
The Creator's Auto_Exclude is pre-made at arm (automation_relay `add_lists`, name "Auto_Exclude"),
so the product finds it through `get_lists` as on a live account.

Journal `$DEMO_SHOTS_TMP/auto-exclude.jsonl` (one write(2) per line, O_APPEND), in order:
  send            above.
  refresh_begin / refresh_end   around the product's `audiences._refresh_auto_exclude` (patched by
                  module attr, observation only): t, account_id; at the end the product's stats, the
                  list's size and which dropped ids are members again (`dropped_back`).
  add             an add of a dropped id: t, account_id, uid, ok, via ("refresh" inside the
                  product's `_ae_apply_batch_blocking`, else "send").
  hold            one `broadcast_lock` hold taken by a refresh (`audiences.broadcast_lock`
                  patched by module attr, timing only): t, account_id, ms (acquired -> released).
  drop            `POST /__slop/auto-exclude/drop {account_id, ids}`: OF's side drops those members
                  (an operator edit on OF, declared); no product call.
Counters per Creator (pages, adds / removes by via, refused) at `GET /__slop/auto-exclude`;
`GET /__slop/auto-exclude/members?account_id=` answers the Auto_Exclude's members now.

Bypasses, declared (armed only): `of_write_paced`'s 11 s per-Creator write gap is passed as
`gap_s` (the gate is the product's, as lib/priority_mass_relay.py does);
`auto_exclude_decide.REFRESH_EVERY_S` is set to `refresh_every_s` (time compression: the refresh
cadence, the rule the same); `server._load_client` answers the lane's client for an armed Creator, so
the composer route and the automations share one OF account, its lists and this journal.
"""
import contextvars
import dataclasses
import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

from fastapi import Request   # module level: the routes' annotations resolve against this module

AE_NAME = "Auto_Exclude"          # audiences.AUTO_EXCLUDE_LIST_NAME
QUEUE_BASE = 8_900_000_000
_tl = threading.local()           # .via = "refresh" inside the product's refresh step
_jlock = threading.Lock()
_cfg: dict | None = None          # the armed config (None = inert)
_acc: dict[str, dict] = {}        # account -> {roster (sorted list), roster_set, refuse, watch, exact, lid}
_drops: dict[str, set[int]] = {}
_counts: Counter = Counter()
_sends = [0]
_in_refresh = contextvars.ContextVar("slop_ae_in_refresh", default=None)   # account inside its refresh


def _tmp() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", ""))


def _on() -> bool:
    return _cfg is not None


def _line(row: dict) -> None:
    raw = (json.dumps(row) + "\n").encode()
    with _jlock:
        fd = os.open(_tmp() / "auto-exclude.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)


def read_journal(tmp: Path) -> list[dict]:
    """The journal under `tmp` (the run's DEMO_SHOTS_TMP), in order; the scenario reads it."""
    f = tmp / "auto-exclude.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def _sleep_ms(key: str) -> None:
    ms = float((_cfg or {}).get(key, 0))
    if ms > 0:
        time.sleep(ms / 1000.0)


class _AutoExcludeWalker:
    """The armed answers above; `super()` (the walker's) for any other Creator or unarmed."""

    def _ae(self) -> dict | None:
        return _acc.get(str(self.account_id)) if _on() else None

    def subscribers(self, *, type="active", limit=10, offset=0, **kw) -> dict:
        a = self._ae()
        if a is None:
            return super().subscribers(type=type, limit=limit, offset=offset, **kw)
        r = a["roster"]
        return {"list": [{"id": i} for i in r[offset:offset + limit]], "hasMore": offset + limit < len(r)}

    def list_users_in(self, list_id, *, limit=20, offset=0, **kw) -> dict:
        a = self._ae()
        if a is not None:
            _sleep_ms("page_ms")
            _counts[(str(self.account_id), "pages")] += 1
        return super().list_users_in(list_id, limit=limit, offset=offset, **kw)

    def add_user_to_list(self, list_id, user_id) -> dict:
        a = self._ae()
        if a is None:
            return super().add_user_to_list(list_id, user_id)
        aid, uid, via = str(self.account_id), int(user_id), getattr(_tl, "via", None) or "send"
        _sleep_ms("add_ms")
        ok = uid not in a["refuse"]
        _counts[(aid, f"adds_{via}" if ok else f"refused_{via}")] += 1
        if uid in _drops.get(aid, ()):
            _line({"ev": "add", "t": time.time(), "account_id": aid, "uid": uid, "ok": ok, "via": via})
        if not ok:
            raise RuntimeError("OF 403: Unable to add user to user list")
        return super().add_user_to_list(list_id, user_id)

    def remove_user_from_list(self, list_id, user_id) -> dict:
        a = self._ae()
        if a is None:
            return super().remove_user_from_list(list_id, user_id)
        _sleep_ms("add_ms")
        _counts[(str(self.account_id), f"removes_{getattr(_tl, 'via', None) or 'send'}")] += 1
        return super().remove_user_from_list(list_id, user_id)

    def send_mass_message(self, text, *, price=0, media_files=None, **kw) -> dict:
        a = self._ae()
        if a is None:
            return super().send_mass_message(text, price=price, media_files=media_files, **kw)
        from datetime import datetime, timezone
        import automation_relay as ar
        _sleep_ms("accept_ms")
        excluded: set[int] = set()
        for lid in kw.get("excluded_user_lists") or []:
            excluded |= set(ar._of_members.get(int(lid), ()))   # a C-level copy: one GIL hold
        rec = a["roster_set"] - excluded
        excl = {int(x) for x in kw.get("excluded_users") or ()}
        row = {"ev": "send", "t": time.time(), "account_id": str(self.account_id), "text": text, "n": len(rec),
               "leak": sorted(rec & a["watch"]), "leak_excl": sorted(rec & excl),
               "lists": [int(x) for x in kw.get("excluded_user_lists") or []]}
        if a["exact"]:
            row["members"] = sorted(set(ar._of_members.get(a["lid"], ())))
            row["excl"] = sorted(excl)
        _line(row)
        _sends[0] += 1
        return {"id": QUEUE_BASE + _sends[0], "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "text": text, "price": price or 0, "isFree": not price, "mediaCount": len(media_files or [])}


try:   # relay side only: the harness imports this module for `read_journal`
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.WALKER_MIXINS.insert(0, _AutoExcludeWalker)


def _arm() -> dict:
    """Read auto-exclude.json, pre-make each Creator's Auto_Exclude, compress the cadence."""
    global _cfg
    import auto_exclude_decide
    import automation_relay as ar
    cfg = json.loads((_tmp() / "auto-exclude.json").read_text())
    rows = [(str(aid), AE_NAME, (int(x) for x in a["members"]), None) for aid, a in cfg["accounts"].items()]
    made = ar.add_lists(rows)
    for (aid, a), lst in zip(cfg["accounts"].items(), made):
        roster = sorted({int(x) for x in a["roster"]})
        _acc[str(aid)] = {"roster": roster, "roster_set": frozenset(roster), "lid": int(lst["id"]),
                          "refuse": frozenset(int(x) for x in a.get("refuse") or ()),
                          "watch": frozenset(int(x) for x in a.get("watch") or ()), "exact": bool(a.get("exact"))}
    auto_exclude_decide.REFRESH_EVERY_S = float(cfg["refresh_every_s"])
    _cfg = cfg
    return {aid: a["lid"] for aid, a in _acc.items()}


def wire(app, loopback, _relay) -> None:
    import audiences
    import automation_executor as ax

    real_refresh = audiences._refresh_auto_exclude

    async def journaled(account_id, client, *a, **kw):
        aid = str(account_id)
        if not _on() or aid not in _acc:
            return await real_refresh(account_id, client, *a, **kw)
        _line({"ev": "refresh_begin", "t": time.time(), "account_id": aid})
        stats, err = None, None
        tok = _in_refresh.set(aid)
        try:
            stats = await real_refresh(account_id, client, *a, **kw)
            return stats
        except BaseException as e:
            err = repr(e)
            raise
        finally:
            _in_refresh.reset(tok)
            import automation_relay as ar
            members = set(ar._of_members.get(_acc[aid]["lid"], ()))
            _line({"ev": "refresh_end", "t": time.time(), "account_id": aid, "err": err,
                   "stats": dataclasses.asdict(stats) if stats is not None else None,
                   "members": len(members), "dropped_back": sorted(_drops.get(aid, set()) & members)})

    audiences._refresh_auto_exclude = journaled

    real_apply = audiences._ae_apply_batch_blocking

    def apply_batch(*a, **kw):
        _tl.via = "refresh"
        try:
            return real_apply(*a, **kw)
        finally:
            _tl.via = None

    audiences._ae_apply_batch_blocking = apply_batch

    real_lock = audiences.broadcast_lock

    class _TimedHold:
        def __init__(self, inner, aid):
            self._inner, self._aid, self._t0 = inner, aid, 0.0

        async def __aenter__(self):
            r = await self._inner.__aenter__()
            self._t0 = time.monotonic()
            return r

        async def __aexit__(self, *exc):
            ms = (time.monotonic() - self._t0) * 1000.0
            try:
                return await self._inner.__aexit__(*exc)
            finally:
                _line({"ev": "hold", "t": time.time(), "account_id": self._aid, "ms": round(ms, 2)})

    def broadcast_lock(account_id):
        inner = real_lock(account_id)
        aid = _in_refresh.get()
        return _TimedHold(inner, aid) if aid is not None and aid == str(account_id) else inner

    audiences.broadcast_lock = broadcast_lock

    # The composer's client (`server._load_client`, lib/relay.py's offline fallback around it) for an
    # armed Creator: the lane's (`ax._make_client`), so a composer blast and an automation share one
    # OF account, its lists and the journal (both are the one session's OFClient in the product).
    import server
    real_load = server._load_client

    def _load_client(account_id):
        if _on() and str(account_id) in _acc:
            return ax._make_client(str(account_id))
        return real_load(account_id)

    server._load_client = _load_client

    real_paced = ax.of_write_paced

    async def of_write_paced(account_id, fn, **kw):
        if _on() and str(account_id) in _acc and "min_gap_s" not in kw:
            kw["min_gap_s"] = float(_cfg["gap_s"])
        return await real_paced(account_id, fn, **kw)

    ax.of_write_paced = of_write_paced

    async def arm(request: Request) -> dict:
        loopback(request)
        return {"lists": _arm()}

    async def drop(request: Request) -> dict:
        import automation_relay as ar
        loopback(request)
        body = await request.json()
        aid, ids = str(body["account_id"]), {int(x) for x in body["ids"]}
        _drops.setdefault(aid, set()).update(ids)
        mem = ar._of_members.setdefault(_acc[aid]["lid"], set())
        gone = sorted(ids & mem)
        mem.difference_update(ids)
        t = time.time()
        _line({"ev": "drop", "t": t, "account_id": aid, "ids": sorted(ids), "were_members": gone})
        return {"t": t, "dropped": gone}

    async def state(request: Request) -> dict:
        loopback(request)
        out: dict = {}
        for (aid, k), v in list(_counts.items()):
            out.setdefault(aid, {})[k] = v
        return {"counts": out, "lists": {aid: a["lid"] for aid, a in _acc.items()}}

    async def members(request: Request, account_id: str) -> dict:
        import automation_relay as ar
        loopback(request)
        return {"members": sorted(set(ar._of_members.get(_acc[str(account_id)]["lid"], ())))}

    app.add_api_route("/__slop/auto-exclude/arm", arm, methods=["POST"])
    app.add_api_route("/__slop/auto-exclude/drop", drop, methods=["POST"])
    app.add_api_route("/__slop/auto-exclude", state, methods=["GET"])
    app.add_api_route("/__slop/auto-exclude/members", members, methods=["GET"])
