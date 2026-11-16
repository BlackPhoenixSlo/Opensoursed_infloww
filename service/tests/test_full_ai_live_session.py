#!/usr/bin/env python3
"""test_full_ai_live_session — one Fan through a whole live session (04a ticket 82), OF faked.

Written to the specs (04a › Interfaces + Contracts, 04b › Contracts, 05 › Interfaces + Contracts,
06 › Saved scene), not to what main does today. Each case is one step on its own account (the
earlier steps' rows seeded as the spec says they land), so one miss never cascades. A step whose
owning ticket is not merged fails with `MISS (ticket N): ...`; every miss of a case is listed.

  case_1_chat_reply          his DM -> pre-look -> text bubbles on OF; one row; full LAST_LOOK per bubble
  case_2_sext_saved_scene    saved scene n1 opening -> sext Turn: scene n2 peak heat 3, Jev reads it
  case_3_content_ask_ppv     "send me pics" -> sell_now: priced PPV on the last bubble, offer_message_id,
                             vault_sends, priced `messages` row
  case_4_purchase_settles    purchase notice (real poll_purchases) -> the rule's tick settles the row
  case_5_next_turn_no_resell after the buy: a chat Turn (settled at Turn start, pending none, spend
                             line in the Writer request), then his ask for more (no bought media re-offered)
  case_6_complaint_free_item complaint after a buy -> make_right: Free item on OF unlocked, row price 0
  case_7_human_of_app_yield  a human writes in the OF app -> pre-look Stop, no row, yield cooldown;
                             his next DM inside the yield: nothing sent
  case_8_off_switch          FULL_AI_CHAT_OFF on -> nothing sent, no row; flipped before bubble 2 -> cut

OF faked at `ax._make_client` (`SessionOF` logs every call in order), Router / info Jev / Heat check
/ Writers faked (`_full_ai_live_helpers.world`). Temp DB only; no paid call, no real OF call.

Run: cd service && nice -n 10 ../venv/bin/python tests/test_full_ai_live_session.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import dm_rate  # noqa: E402
import purchase_notifications as pn  # noqa: E402
import runtime_switches  # noqa: E402
import vault_jev_rules  # noqa: E402
from _full_ai_fixtures import QUIET, _msg  # noqa: E402
from _full_ai_live_fixtures import LINE3  # noqa: E402
from _full_ai_live_helpers import HOSTS, NANO, clear_pause, get_fan, reply, seed_live, world  # noqa: E402
from _of_fixtures import VaultOF  # noqa: E402
from automations import full_ai_live  # noqa: E402
from automations.full_ai_scene import scene_words  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Message, VaultItem, VaultSend  # noqa: E402

NOW = datetime.utcnow
FAN = 8201                      # the one Fan; each step on its own Creator
PINNED = ("off_switch", "fans_list", "who_owns", "human_yield", "overtaken", "offer_valid")
SLOT_TICKET = {"off_switch": 81, "fans_list": 81, "who_owns": 81, "human_yield": 81,
               "overtaken": 66, "offer_valid": 89}
OFF = "FULL_AI_CHAT_OFF"
# Sell steps: sell on, one photo per Offer, no Chat tease / price Jev (both would need more fakes).
SELL = {"sell_on": True, "sext_scene": False, "chat_tease": False, "sell_bundle": "shoot",
        "sell_nearest": "off"}
VAULT = {101: "$10", 202: "$50", 303: "$10"}
BOUGHT = 101                    # step 3's PPV media (seeded for steps 4-6)


# ── Miss collector ────────────────────────────────────────────────────

class Misses:
    """Every failed expectation of a case, raised together at the end."""

    def __init__(self):
        self.items: list[str] = []

    def miss(self, ticket, what: str) -> None:
        self.items.append(f"MISS (ticket {ticket}): {what}" if ticket else f"FAIL: {what}")

    def need(self, ok, ticket, what: str) -> bool:
        if not ok:
            self.miss(ticket, what)
        return bool(ok)

    def done(self) -> None:
        if self.items:
            raise AssertionError(" | ".join(self.items))


# ── The faked OF client ───────────────────────────────────────────────

class SessionOF(VaultOF):
    """VaultOF logging every OF call in order: ("send", fan, text, price, media, previews),
    ("get_messages", fan), ("unsend", id, fan), ("mark_chat_read", fan). `chat` = what a read of
    his chat lists (the OF-app items)."""

    def __init__(self, chat=()):
        super().__init__()
        self.calls: list[tuple] = []
        self.ids: list[int] = []
        self.chat = list(chat)

    def send_message(self, chat_id, text, **kw) -> dict:
        res = super().send_message(chat_id, text, **kw)
        self.calls.append(("send", int(chat_id), text, kw.get("price"), tuple(kw.get("media_files") or ()),
                           tuple(kw.get("previews") or ())))
        self.ids.append(int(res["id"]))
        return res

    def get_messages(self, chat_id, **kw) -> dict:
        self.calls.append(("get_messages", int(chat_id)))
        return {"list": list(self.chat), "hasMore": False}

    def unsend_message(self, message_id, chat_id) -> None:
        self.calls.append(("unsend", int(message_id), int(chat_id)))

    def mark_chat_read(self, chat_id) -> None:
        self.calls.append(("mark_chat_read", int(chat_id)))

    def sends(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "send"]

    def read_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "get_messages"]


def _short(calls) -> list:
    return [tuple((x[:24] + "…") if isinstance(x, str) and len(x) > 25 else x for x in c) for c in calls]


def expect_send(fan: int, part: dict) -> tuple:
    """The OF call a bubble is, per spec: text -> send_message(fan, text); priced PPV ->
    send_message(..., price=, media_files=locked+previews, previews=) (05 › send_priced); Free item ->
    send_dropping_bad_media's send_message(..., media_files=) with no price."""
    ppv = part.get("ppv")
    if not ppv:
        return ("send", fan, part["text"], None, (), ())
    media = tuple(dict.fromkeys([*(ppv.get("media") or []), *(ppv.get("previews") or [])]))
    if ppv["price_cents"] > 0:
        return ("send", fan, part["text"], ppv["price_cents"] / 100, media, tuple(ppv.get("previews") or ()))
    return ("send", fan, part["text"], None, media, ())


# ── The LAST_LOOK spy ─────────────────────────────────────────────────

class Spy:
    def __init__(self):
        self.events: list[tuple[str, int]] = []   # (check name, look.index), in call order
        self.names: list[str] | None = None       # LAST_LOOK's names; None = no LAST_LOOK

    def at(self, i: int) -> list[str]:
        return [n for n, ix in self.events if ix == i]


@contextlib.contextmanager
def last_look(m: Misses):
    """Every Check of `full_ai_live.LAST_LOOK` wrapped to record (name, look.index); the list is
    restored after. Records a MISS per missing seam / slot / order."""
    spy = Spy()
    ll = getattr(full_ai_live, "LAST_LOOK", None)
    if not isinstance(ll, list):
        m.miss(66, "full_ai_live has no LAST_LOOK")
        yield spy
        return
    saved = list(ll)
    spy.names = [t[0] for t in saved]
    for n in PINNED:
        if n not in spy.names:
            m.miss(SLOT_TICKET[n], f"LAST_LOOK has no {n!r} slot (has {spy.names})")
    present = [n for n in spy.names if n in PINNED]
    m.need(present == [n for n in PINNED if n in present], 66,
           f"LAST_LOOK order {present} is not the pinned {list(PINNED)}")

    def wrap(name, check):
        def spied(look):
            spy.events.append((name, look.index))
            return check(look)
        return spied
    ll[:] = [(n, loader, wrap(n, chk)) for n, loader, chk in saved]
    try:
        yield spy
    finally:
        ll[:] = saved


def look_passed(m: Misses, spy: Spy, sent_idx: list[int]) -> None:
    """The pre-look (index -1, before bubble 0) and every sent bubble ran the FULL list, in order."""
    if spy.names is None:
        return
    m.need(spy.at(-1) == spy.names, 66, f"pre-look ran {spy.at(-1)}, not the full LAST_LOOK {spy.names}")
    order = [ix for _n, ix in spy.events]
    if -1 in order and 0 in order:
        m.need(order.index(-1) < order.index(0), 66, "pre-look ran after bubble 0's last look")
    for i in sent_idx:
        m.need(spy.at(i) == spy.names, 66, f"bubble {i} passed {spy.at(i)}, not the full LAST_LOOK {spy.names}")


def bubble_senders(m: Misses, *, ppv: bool) -> None:
    bs = getattr(full_ai_live, "BUBBLE_SENDERS", None)
    if not m.need(isinstance(bs, dict), 66, "full_ai_live has no BUBBLE_SENDERS"):
        return
    m.need("text" in bs, 66, f"BUBBLE_SENDERS has no 'text' (has {sorted(bs)})")
    if ppv:
        m.need("ppv" in bs, 90, f"BUBBLE_SENDERS has no 'ppv' (has {sorted(bs)})")


# ── Seeding ───────────────────────────────────────────────────────────

DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False, "description": "a mirror selfie in jeans"}


def _jev_fields(lane: str) -> dict:
    return {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": "photo",
            "breasts_bare": "n", "crotch_bare": "n", "penetration": "n", "tags": {}}


async def seed_vault(aid: str) -> None:
    """The Creator's vault: VAULT media, each priced by its Jev lane (as _full_ai_sell_helpers._vault)."""
    t0 = datetime(2026, 7, 1)
    async with get_session() as s:
        for mid, lane in VAULT.items():
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", created_at=t0 + timedelta(days=mid),
                            tags="[]", describe_status="described", of_folder_ids="[]",
                            ai_fields_json=json.dumps({**DRESSED, vault_jev_rules.JEV_KEY: _jev_fields(lane)})))


async def prior_turn(aid: str, fan: int, his: int, out: int, *, ago: int = 5, scene: dict | None = None,
                     ppv: tuple[int, list[int]] | None = None, text: str = "mm ok") -> int:
    """An earlier Turn as the live sender leaves it: his DM `his`, its `sent` live row, her bubble
    `out` (automation_kind full_ai_chat). `ppv` = (cents, locked): the row carries the Offer with
    `offer_message_id = out`, the bubble is priced, one vault_sends row per locked media
    (05 › send_outcome SENT). Returns the row id."""
    at = NOW() - timedelta(minutes=ago)
    await _msg(aid, fan, his, "in", "hey", at)
    part: dict = {"text": text, "message_id": out}
    cols: dict = {}
    if ppv:
        cents, locked = ppv
        ref = {"ref": f"v:{locked[0]}", "subject": "anything", "format": "photo", "lane": "chat", "kind": "offer"}
        part["ppv"] = {"ref": ref["ref"], "price_cents": cents, "media": list(locked), "previews": []}
        cols = dict(offer_price_cents=cents, offer_list_cents=cents, offer_message_id=out,
                    offer_media_json=json.dumps({"locked": list(locked), "previews": []}),
                    offer_item_ref=json.dumps(ref))
    rj: dict = {"parts": [part]}
    if scene is not None:
        rj["scene"] = scene
    async with get_session() as s:
        r = AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(his),
                       route="sell_now" if ppv else ("sext" if scene else "chat"), heat=2,
                       route_row="sell" if ppv else "otherwise", question_version="v", status="sent",
                       created_at=at + timedelta(seconds=20), anchor_message_id=his, anchor_created_at=at,
                       jev_json=json.dumps({"state": {"fan_new_messages": ["hey"]}}), reply_json=json.dumps(rj),
                       **cols)
        s.add(r)
        if ppv:
            for media in ppv[1]:
                s.add(VaultSend(account_id=aid, fan_id=fan, media_id=media, message_id=out,
                                price_cents=ppv[0], was_purchased=None))
        await s.flush()
        rid = r.id
    await _msg(aid, fan, out, "out", text, at + timedelta(seconds=30), automation_kind="full_ai_chat",
               price_cents=ppv[0] if ppv else 0)
    return rid


class FeedClient:
    """The purchases feed's client (as test_full_ai_settle_live._FakeClient): `get_json` only."""

    def __init__(self, items):
        self.items = items

    def get_json(self, path):
        assert "type=purchases" in path, path
        return {"list": self.items}


_NID = iter(range(910_000_000, 999_999_999))


async def buy(aid: str, fan: int, mid: int, cents: int) -> datetime:
    """He buys PPV `mid`: OF's purchase notice through the real `poll_purchases` (is_paid flip,
    purchase_notices row, vault_sends stamp). Returns the notice time."""
    at = (NOW() - timedelta(seconds=20)).replace(microsecond=0)
    n = {"id": next(_NID), "type": "paided_message", "subType": "subscriber_pay_for_chat_message",
         "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
         "replacePairs": {"{NAME}": "D", "{AMOUNT}": f"${cents / 100:.2f}",
                          "{MESSAGE_LINK}": f"/chats/chat/{fan}?firstId={mid}"}}
    out = await pn.poll_purchases(aid, FeedClient([n]))
    assert out["flipped"] == 1, ("setup: the notice did not flip is_paid", out)
    return at


async def dm(aid: str, fan: int, mid: int, body: str, *, ago_s: int = 30) -> None:
    await _msg(aid, fan, mid, "in", body, NOW() - timedelta(seconds=ago_s))


async def job(aid: str, fan: int, mid: int | None, of: SessionOF, *, jev=(QUIET, 1.0), writers=None,
              clear: bool = True):
    """One live job (`full_ai_live.run`, the job body) for his DM `mid` (None: the rule's interval
    tick). Returns (result, FakeJev, FakeWriterHTTP). `clear` ends the 10 s cooldown after."""
    rid = await full_ai_live.live_rule(aid)
    payload = ({"only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 0} if mid is not None
               else {"_rule_id": rid})
    with world(of, jev, writers=writers) as (_of, jevs, _info, fw):
        res = await full_ai_live.run(aid, payload, run_id=0)
    if clear:
        await clear_pause(aid, fan)
    return res, jevs, fw


async def rows_of(aid: str, fan: int, key: int | None = None) -> list[AiDecision]:
    async with get_session() as s:
        q = select(AiDecision).where(AiDecision.account_id == aid, AiDecision.fan_id == fan)
        if key is not None:
            q = q.where(AiDecision.trigger_key == str(key))
        return list((await s.execute(q.order_by(AiDecision.id))).scalars())


async def row(rid: int) -> AiDecision:
    async with get_session() as s:
        return await s.get(AiDecision, rid)


async def msg(aid: str, fan: int, mid: int) -> Message | None:
    async with get_session() as s:
        return await s.get(Message, (aid, fan, int(mid)))


async def vault_sends(aid: str, fan: int, message_id: int) -> list[VaultSend]:
    async with get_session() as s:
        return list((await s.execute(select(VaultSend).where(
            VaultSend.account_id == aid, VaultSend.fan_id == fan, VaultSend.message_id == message_id))).scalars())


# ── Shared Turn checks ────────────────────────────────────────────────

def check_of_calls(m: Misses, of: SessionOF, fan: int, parts: list[dict]) -> None:
    """The OF call list in order: one get_messages (the OF-app read) at the pre-look and again just
    before the first bubble and before a `ppv` bubble, one send per bubble as `expect_send`, then
    one mark_chat_read."""
    reads = of.read_calls()
    shape = [c[0] for c in of.calls if c[0] in ("get_messages", "send")]
    want_shape = ["get_messages"] + [k for i, p in enumerate(parts)
                                     for k in ((["get_messages"] if i == 0 or "ppv" in p else []) + ["send"])]
    m.need(set(reads) == {("get_messages", fan)} and shape == want_shape, 81,
           f"want get_messages (OF-app read) at the pre-look, before bubble 1 and before a ppv bubble only; "
           f"OF calls {_short(of.calls)}")
    want = [expect_send(fan, p) for p in parts]
    got = of.sends()
    text_want = [w for w, p in zip(want, parts) if "ppv" not in p]
    text_got = [g for g in got if g[3] is None and not g[4]]
    m.need(text_got == text_want, None, f"text bubbles on OF {_short(text_got)} != parts {_short(text_want)}")
    for i, (w, p) in enumerate(zip(want, parts)):
        if "ppv" in p:
            kind = "priced PPV" if p["ppv"]["price_cents"] else "Free item"
            m.need(w in got, 90, f"no {kind} on OF for bubble {i}: want {_short([w])}; sends {_short(got)}")
    if text_got == text_want and all(w in got for w in want):
        m.need(got == want, None, f"OF sends out of order: {_short(got)} != {_short(want)}")
    # A landed Turn clears his unread badge once, after its last send (plan › Switches, ticket 71).
    other = [c for c in of.calls if c[0] not in ("get_messages", "send")]
    read = [("mark_chat_read", fan)] if got else []
    m.need(other == read and of.calls[-len(read):] == read if read else not other, 71,
           f"want {read or 'no other call'} after the last send; OF calls {_short(of.calls)}")
    landed = [p["message_id"] for p in parts if p.get("message_id")]
    m.need(landed == [i for i in of.ids if i in landed] and set(landed) <= set(of.ids), None,
           f"parts' message ids {landed} are not OF's ids {of.ids}")


async def check_turn(m: Misses, spy: Spy, of: SessionOF, aid: str, fan: int, mid: int, *, route: str):
    """One sent Turn: exactly one row, its route, the OF call list, status sent with no cut, the
    full LAST_LOOK before every landed bubble, one full_ai_chat `messages` row per landed bubble.
    Returns (row, reply_json, parts) or None."""
    rows = await rows_of(aid, fan, mid)
    m.need(len(rows) == 1, None, f"want exactly one ai_decisions row for the Turn, got {len(rows)}")
    if not rows:
        return None
    r = rows[0]
    rj = reply(r)
    parts = rj.get("parts") or []
    m.need(r.route == route, None, f"route {r.route} != {route} (row_row {r.route_row})")
    m.need(parts, None, f"no bubbles on the row (status {r.status}, dropped {rj.get('dropped_reason')})")
    check_of_calls(m, of, fan, parts)
    cut = rj.get("cut")
    if cut and cut.get("reason") == "ppv_unbuilt":
        m.miss(90, f"the PPV bubble was cut ppv_unbuilt (row status {r.status})")
    else:
        m.need(r.status == "sent" and cut is None, None, f"row status {r.status}, cut {cut}")
    sent_idx = [i for i, p in enumerate(parts) if p.get("message_id")]
    look_passed(m, spy, sent_idx)
    for i in sent_idx:
        got = await msg(aid, fan, parts[i]["message_id"])
        m.need(got is not None and got.direction == "out" and got.automation_kind == "full_ai_chat", None,
               f"bubble {i}: no full_ai_chat messages row")
    return r, rj, parts


def offer_media(r: AiDecision) -> list[int]:
    om = json.loads(r.offer_media_json or "{}")
    return [*(om.get("locked") or []), *(om.get("previews") or [])]


async def check_ppv_landed(m: Misses, r: AiDecision, parts: list[dict], of: SessionOF, aid: str, fan: int) -> None:
    """05 › send_outcome SENT: offer_message_id = the PPV's OF id; one vault_sends row per locked
    media at the Offer's price, was_purchased NULL; the `messages` row priced, kind full_ai_chat."""
    last = parts[-1] if parts else {}
    ppv = last.get("ppv")
    if not m.need(ppv is not None, None, "setup: the Turn's last bubble carries no ppv"):
        return
    cents = int(ppv["price_cents"])
    m.need(r.offer_price_cents == cents, None, f"offer_price_cents {r.offer_price_cents} != {cents}")
    oid = last.get("message_id")
    if not m.need(oid is not None and r.offer_message_id == oid and oid in of.ids, 90,
                  f"PPV bubble message_id {oid}, row offer_message_id {r.offer_message_id}, OF ids {of.ids}"):
        return
    vs = await vault_sends(aid, fan, oid)
    m.need(sorted(v.media_id for v in vs) == sorted(ppv["media"]) and
           all(v.price_cents == cents and v.was_purchased is None for v in vs), 90,
           f"vault_sends for {oid}: {[(v.media_id, v.price_cents, v.was_purchased) for v in vs]}, "
           f"want {ppv['media']} at {cents} unpurchased")
    got = await msg(aid, fan, oid)
    m.need(got is not None and got.automation_kind == "full_ai_chat" and (got.price_cents or 0) == cents, 90,
           f"PPV messages row {getattr(got, 'automation_kind', None)} {getattr(got, 'price_cents', None)}")


# ── Steps ─────────────────────────────────────────────────────────────

async def case_1_chat_reply():
    m, aid, mid = Misses(), "fa_sess_1", 8211
    await seed_live(aid, {})
    await dm(aid, FAN, mid, "hey you, how was your day")
    of = SessionOF()
    with last_look(m) as spy:
        await job(aid, FAN, mid, of)
    bubble_senders(m, ppv=False)
    await check_turn(m, spy, of, aid, FAN, mid, route="chat")
    m.done()


async def case_2_sext_saved_scene():
    m, aid, mid = Misses(), "fa_sess_2", 8221
    await seed_live(aid, {"sext_scene": True})
    saved = {"n": 1, "stage": "opening", "heat": 2}
    await prior_turn(aid, FAN, 8218, 8219, scene=saved, text="mm u like that")
    await dm(aid, FAN, mid, "ur making me so hard rn")
    of = SessionOF()
    jev = ({**QUIET, "sexual_now": 0.9, "scene_on": 0.9}, 2.0, {"scene_stage": "peak"})
    with last_look(m) as spy:
        await job(aid, FAN, mid, of, jev=jev)
    got = await check_turn(m, spy, of, aid, FAN, mid, route="sext")
    if got:
        r, rj, _parts = got
        m.need(rj.get("scene") == {"n": 2, "stage": "peak", "heat": 3}, 98,
               f"scene after the Turn {rj.get('scene')}, want n2 peak heat 3 (saved n1 opening + Jev peak)")
        st = json.loads(r.jev_json or "{}").get("state") or {}
        m.need(st.get("scene") == scene_words(saved), 98, f"Jev's scene state {st.get('scene')!r}")
        hc = rj.get("heat_check") or {}
        m.need(hc.get("outcome") == "ok", 98, f"heat_check on the sext Turn {hc}")
    m.done()


async def case_3_content_ask_ppv():
    m, aid, mid = Misses(), "fa_sess_3", 8231
    await seed_live(aid, SELL)
    await seed_vault(aid)
    await prior_turn(aid, FAN, 8228, 8229)
    await dm(aid, FAN, mid, "send me pics")
    of = SessionOF()
    with last_look(m) as spy:
        await job(aid, FAN, mid, of, jev=({**QUIET, "wants_content": 0.9}, 1.0))
    bubble_senders(m, ppv=True)
    got = await check_turn(m, spy, of, aid, FAN, mid, route="sell_now")
    if got:
        r, _rj, parts = got
        m.need(r.offer_price_cents and r.offer_price_cents > 0, None,
               f"setup: no priced Offer on the row ({r.offer_price_cents}, refusal {_rj.get('refusal')})")
        await check_ppv_landed(m, r, parts, of, aid, FAN)
    m.done()


async def case_4_purchase_settles():
    m, aid = Misses(), "fa_sess_4"
    await seed_live(aid, SELL)
    rid = await prior_turn(aid, FAN, 8241, 8242, ppv=(1000, [BOUGHT]), text="just for u")
    at = await buy(aid, FAN, 8242, 1000)
    of = SessionOF()
    res, jevs, _fw = await job(aid, FAN, None, of)
    m.need(res != {"skipped": "unanchored"}, 68, f"the rule's interval tick is still {res}: no sweep body")
    r = await row(rid)
    ok = r.outcome == "bought" and r.join_src == "notice" and r.outcome_at is not None and \
        abs((r.outcome_at - at).total_seconds()) <= 2
    m.need(ok, 90, f"after the purchase notice + the tick the Offer row reads outcome={r.outcome} "
                   f"join_src={r.join_src} outcome_at={r.outcome_at} (notice {at})")
    m.need(r.offer_message_id == 8242, None, f"offer_message_id moved: {r.offer_message_id}")
    m.need(not of.sends() and not jevs.calls, None, f"the tick sent / asked: {_short(of.calls)}, Jev {len(jevs.calls)}")
    m.need(len(await rows_of(aid, FAN)) == 1, None, "the tick wrote an ai_decisions row")
    m.done()


async def case_5_next_turn_no_resell():
    m, aid, mid, mid2 = Misses(), "fa_sess_5", 8253, 8254
    await seed_live(aid, SELL)
    await seed_vault(aid)
    rid = await prior_turn(aid, FAN, 8251, 8252, ppv=(1000, [BOUGHT]), text="just for u")
    await buy(aid, FAN, 8252, 1000)
    # 5a: his next line, a plain chat Turn (the spend line rides only a Turn with no Pick,
    # full_ai_writers.messages_for "No spend line beside a Pick").
    await dm(aid, FAN, mid, "omg that was so hot", ago_s=60)
    of = SessionOF()
    with last_look(m) as spy:
        _res, _jevs, fw = await job(aid, FAN, mid, of)
    p = await row(rid)
    settled = m.need(p.outcome == "bought" and p.join_src == "notice", 90,
                     f"Turn start did not settle the bought Offer: outcome={p.outcome} join_src={p.join_src}")
    got = await check_turn(m, spy, of, aid, FAN, mid, route="chat")
    if got:
        r, _rj, _parts = got
        st = json.loads(r.jev_json or "{}").get("state") or {}
        if settled:     # an unsettled Offer still reads open: already reported under 90
            m.need(st.get("pending_offer") == "none", 90, f"pending_offer after the buy {st.get('pending_offer')!r}")
        lp = str(st.get("last_purchase"))
        m.need(any(w in lp for w in ("second", "minute", "hour", "just")), 90, f"last_purchase {lp!r}")
        m.need(r.offer_price_cents is None and not offer_media(r), None, f"a chat Turn carries an Offer: {offer_media(r)}")
    w = json.dumps([x["body"]["messages"] for x in fw.requests if x["host"] == NANO])
    m.need("unlocked 1 PPV" in w, 88, "no spend line ('unlocked 1 PPV') in the Writer request")
    # 5b: he asks for more: a new Offer, never the media he bought.
    await dm(aid, FAN, mid2, "send me more", ago_s=0)   # after her 5a bubbles
    of2 = SessionOF()
    with last_look(m) as spy2:
        await job(aid, FAN, mid2, of2, jev=({**QUIET, "wants_content": 0.9}, 1.0))
    got = await check_turn(m, spy2, of2, aid, FAN, mid2, route="sell_now")
    if got:
        r, _rj, parts = got
        media = offer_media(r)
        if m.need(media and BOUGHT not in media, 90, f"re-sell: the new Offer's media {media} (bought {BOUGHT})"):
            await check_ppv_landed(m, r, parts, of2, aid, FAN)
    m.need(len(await rows_of(aid, FAN)) == 3, None, "want 3 rows (the PPV Turn, 5a, 5b)")
    m.done()


async def case_6_complaint_free_item():
    m, aid, mid = Misses(), "fa_sess_6", 8263
    await seed_live(aid, SELL)
    await seed_vault(aid)
    rid = await prior_turn(aid, FAN, 8261, 8262, ppv=(1000, [BOUGHT]), text="just for u")
    at = await buy(aid, FAN, 8262, 1000)
    async with get_session() as s:      # step 4's end state: the Offer row settled
        await s.execute(update(AiDecision).where(AiDecision.id == rid).values(
            outcome="bought", outcome_at=at, join_src="notice"))
    await dm(aid, FAN, mid, "wtf that pic was so blurry, i want my money back")
    of = SessionOF()
    with last_look(m) as spy:
        await job(aid, FAN, mid, of, jev=({**QUIET, "complains_now": 0.9}, 1.0))
    bubble_senders(m, ppv=True)
    got = await check_turn(m, spy, of, aid, FAN, mid, route="make_right")
    if got:
        r, rj, parts = got
        ppv = (parts[-1] if parts else {}).get("ppv")
        if m.need(ppv is not None and ppv["price_cents"] == 0 and r.offer_price_cents == 0, None,
                  f"setup: no Free item on the row (ppv {ppv}, refusal {rj.get('refusal')})"):
            m.need(BOUGHT not in ppv["media"], None, f"the Free item {ppv['media']} is media he owns")
            await check_ppv_landed(m, r, parts, of, aid, FAN)
    m.done()


async def case_7_human_of_app_yield():
    m, aid, mid, mid2 = Misses(), "fa_sess_7", 8273, 8274
    await seed_live(aid, {})
    await prior_turn(aid, FAN, 8271, 8272)
    await dm(aid, FAN, mid, "u there?")
    human = {"id": 9_700_000_000_007, "text": "hey babe its really me", "fromUser": {"id": 999},
             "createdAt": (NOW() - timedelta(seconds=10)).isoformat() + "+00:00"}
    of = SessionOF(chat=[human])
    with last_look(m) as spy:
        res, jevs, _fw = await job(aid, FAN, mid, of, clear=False)
    m.need(res == {"skipped": "human_yield:human_of_app"}, 81, f"job result {res}")
    m.need(not of.sends(), 81, f"Full AI sent after a human's OF-app answer: {_short(of.sends())}")
    m.need(of.read_calls() == [("get_messages", FAN)], 81, f"OF-app read: OF calls {_short(of.calls)}")
    m.need(not jevs.calls, 81, f"the Router ran ({len(jevs.calls)}) after a pre-look Stop")
    m.need(not await rows_of(aid, FAN, mid), 81, "a stood-down pre-look wrote an ai_decisions row")
    if spy.names is not None and "human_yield" in spy.names:
        want = spy.names[:spy.names.index("human_yield") + 1]
        m.need(spy.at(-1) == want, 66, f"pre-look ran {spy.at(-1)}, want {want} (first reason wins)")
    f = await get_fan(aid, FAN)
    until = getattr(f, "automation_paused_until", None)
    m.need(until is not None and until >= NOW() + timedelta(seconds=30), 81,
           f"no Human yield cooldown (paused_until {until}; default yield 60 s from her send)")
    # His next DM inside the yield: nothing goes out, no row.
    await dm(aid, FAN, mid2, "hello??", ago_s=2)
    of2 = SessionOF()
    res2, _j, _f = await job(aid, FAN, mid2, of2, clear=False)
    m.need(not of2.sends(), 81, f"Full AI sent inside the Human yield: {_short(of2.sends())}")
    m.need(not await rows_of(aid, FAN, mid2), 81, "a Turn row inside the Human yield")
    m.need(str(res2.get("skipped", "")).startswith("busy"), 81, f"job inside the yield: {res2}")
    m.done()


async def case_8_off_switch():
    m = Misses()
    # A: the switch is on when his DM's job runs.
    aid, mid = "fa_sess_8a", 8281
    await seed_live(aid, {})
    await prior_turn(aid, FAN, 8279, 8280)
    await dm(aid, FAN, mid, "hey")
    of = SessionOF()
    await runtime_switches.set_override(OFF, True, by="test")
    try:
        with last_look(m) as spy:
            res, jevs, _fw = await job(aid, FAN, mid, of)
    finally:
        await runtime_switches.set_override(OFF, None, by="test")
    m.need(res == {"skipped": "off_switch:off_global"}, 81, f"switch on: job result {res}")
    m.need(not of.sends(), 81, f"switch on: Full AI sent {_short(of.sends())}")
    m.need(len(of.read_calls()) <= 1, None, f"switch on: OF reads {_short(of.read_calls())}")
    m.need(not jevs.calls, 81, f"switch on: the Router ran ({len(jevs.calls)})")
    m.need(not await rows_of(aid, FAN, mid), 81, "switch on: a stood-down pre-look wrote a row")
    if spy.names is not None and "off_switch" in spy.names:
        m.need(spy.at(-1) == ["off_switch"], 66, f"switch on: pre-look ran {spy.at(-1)} (first reason wins)")

    # B: flipped on after bubble 1 landed, before bubble 2's last look (spec: hold -> rate turn -> look).
    aid, mid = "fa_sess_8b", 8285
    await seed_live(aid, {})
    await prior_turn(aid, FAN, 8283, 8284)
    await dm(aid, FAN, mid, "hey how was ur day")
    of = SessionOF()
    real_turn, turns = dm_rate.turn, []

    async def turn(account_id, **kw):
        turns.append(account_id)
        if len(turns) == 2:
            await runtime_switches.set_override(OFF, True, by="test")
        return await real_turn(account_id, **kw)
    dm_rate.turn = turn
    try:
        with last_look(m) as spy:
            await job(aid, FAN, mid, of, writers=dict.fromkeys(HOSTS, LINE3))
    finally:
        dm_rate.turn = real_turn
        await runtime_switches.set_override(OFF, None, by="test")
    rows = await rows_of(aid, FAN, mid)
    m.need(len(rows) == 1, None, f"mid-Turn flip: want one row, got {len(rows)}")
    if rows:
        rj = reply(rows[0])
        parts = rj.get("parts") or []
        if m.need(len(parts) >= 2, None, f"setup: need >= 2 bubbles, got {len(parts)}"):
            m.need(len(of.sends()) == 1, 81, f"mid-Turn flip: {len(of.sends())} bubbles went out, want 1")
            m.need(rows[0].status == "sent" and rj.get("cut") == {"check": "off_switch", "reason": "off_global",
                                                                    "index": 1}, 81,
                   f"mid-Turn flip: status {rows[0].status}, cut {rj.get('cut')}")
            if spy.names is not None and "off_switch" in spy.names:
                m.need(spy.at(0) == spy.names, 66, f"bubble 0 passed {spy.at(0)}")
                m.need(spy.at(1) == ["off_switch"], 66, f"bubble 1 ran {spy.at(1)}, want ['off_switch']")
    m.done()


_harness.run()
