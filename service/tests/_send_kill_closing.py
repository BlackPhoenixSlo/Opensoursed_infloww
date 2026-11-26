from __future__ import annotations

import contextlib
import itertools
from unittest.mock import patch

import _send_kill_cell as kc
from _send_kill import Killed, db_row, seed_account
from _send_kill_chat import _CLOSING, _WCFI_REPLY, _msgs, _stubs

KIND = "welcome_closing_ppv"
_n = itertools.count(1)


async def _setup() -> tuple[str, int]:
    from db.engine import get_session
    from db.models import Fan
    aid, fan = f"9508397001243{next(_n):05d}", 72007
    await seed_account(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Tom", lifetime_spend_cents=0))
    await _msgs(aid, fan, [("in", f"msg {i}", 40 - i) for i in range(10)])
    return aid, fan


async def _tick(aid: str, http: kc.FakeHttp, on: bool = True) -> bool:
    import automation_executor as ax
    import dm_rate
    from automation_executor import run_once
    dm_rate._reset()
    with kc.cells(on, accounts=f"onlyfans:{aid}"), patch.object(ax, "_make_client", lambda a: kc.client(http)), \
            _stubs(_WCFI_REPLY):
        try:
            await run_once(aid, "welcome_chatter_for_info", payload=dict(_CLOSING))
        except Killed:
            return True
    return False


def _op(aid: str, fan: int):
    return db_row("SELECT state, attempts, upstream_id FROM send_ops WHERE account=? AND kind=? AND target=?",
                  (aid, KIND, str(fan)))


def _fan(aid: str, fan: int):
    return db_row("SELECT gather_close_at IS NOT NULL, gather_close_sending_at IS NOT NULL FROM fans"
                  " WHERE account_id=? AND fan_id=?", (aid, fan))


def _out_rows(aid: str, fan: int) -> list:
    import sqlite3

    import _harness
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return [r[0] for r in c.execute("SELECT message_id FROM messages WHERE account_id=? AND fan_id=?"
                                        " AND direction='out'", (aid, fan))]


def _posts(http: kc.FakeHttp, fan: int) -> int:
    return sum(1 for m, p, _ in http.calls if m == "POST" and p.startswith(f"/chats/{fan}/messages"))


async def clean() -> list[kc.Check]:
    aid, fan = await _setup()
    http = kc.FakeHttp()
    await _tick(aid, http)
    op = _op(aid, fan)
    ok = (len(http.accepts) == 1 and _posts(http, fan) == 1 and op is not None and op[0] == "sent"
          and op[2] == str(http.accepts[0]["id"]) and _fan(aid, fan) == (1, 0)
          and _out_rows(aid, fan) == [http.accepts[0]["id"]])
    return [("closing PPV clean run = 1 accept + 1 sent row, gather_close_at stamped, anchor cleared", ok,
             {"calls": http.calls, "op": op, "fan": _fan(aid, fan), "out": _out_rows(aid, fan)})]


async def kill(point: str) -> list[kc.Check]:
    import send_ops
    aid, fan = await _setup()
    at_kill: dict = {}

    def die_before(fake, url, body):
        at_kill.update(op=_op(aid, fan), fan=_fan(aid, fan))
        raise Killed()

    def die_after_accept(fake, url, body):
        kc.accept(fake, url, body)
        at_kill.update(op=_op(aid, fan), fan=_fan(aid, fan))
        raise Killed()

    real_finish = send_ops._finish

    def die_after_mark(account, op, state, budget, result=None):
        real_finish(account, op, state, budget, result)
        at_kill.update(op=_op(aid, fan), fan=_fan(aid, fan))
        raise Killed()

    http = kc.FakeHttp({"after_claim": die_before, "accepted": die_after_accept, "after_update": kc.accept}[point])
    with patch.object(send_ops, "_finish", die_after_mark) if point == "after_update" else contextlib.nullcontext():
        killed = await _tick(aid, http)
    state = "sent" if point == "after_update" else "claimed"
    reached = killed and (at_kill.get("op") or (None,))[0] == state and at_kill.get("fan") == (0, 1)
    out: list[kc.Check] = [(f"closing PPV kill {point}: reached (anchor saved, claim {state}, not stamped)",
                            reached, {"killed": killed, **at_kill})]
    kc.restart()
    again = kc.FakeHttp()
    await _tick(aid, again)
    accepts = len(http.accepts) + len(again.accepts)
    if point == "after_update":
        ok = (_op(aid, fan)[0] == "sent" and _fan(aid, fan) == (1, 0) and not again.calls
              and _out_rows(aid, fan) == [http.accepts[0]["id"]])
        want = "replays the stored answer: stamped, attribution written once"
    else:
        ok = _op(aid, fan)[0] == "uncertain" and _fan(aid, fan) == (0, 1) and not again.calls
        want = "op stays uncertain for a person to mark, never resent"
    out.append((f"closing PPV kill {point}: rerun {want}; 0 more accepts", ok and accepts <= 1,
                {"op": _op(aid, fan), "fan": _fan(aid, fan), "accepts": accepts, "rerun_calls": again.calls,
                 "out": _out_rows(aid, fan)}))
    return out


async def env_unset_failures() -> list[kc.Check]:
    out: list[kc.Check] = []
    import of_pacing
    for name, step, anchor in (("known refusal before the wire", kc.raises(of_pacing.SendDispatchExpired()), 0),
                               ("OF 4xx (no wire budget to prove it)", kc.status(400), 1),
                               ("unknown outcome (timeout)", kc.raises(TimeoutError("read timed out")), 1)):
        aid, fan = await _setup()
        http = kc.FakeHttp(step)
        await _tick(aid, http, on=False)
        out.append((f"env unset, {name}: 1 call, not stamped, anchor kept={bool(anchor)}",
                    len(http.calls) == 1 and _fan(aid, fan) == (0, anchor), {"calls": http.calls, "fan": _fan(aid, fan)}))
    return out


async def run_all() -> list[kc.Check]:
    checks = await clean() + await env_unset_failures()
    for point in ("after_claim", "accepted", "after_update"):
        checks += await kill(point)
    return checks
