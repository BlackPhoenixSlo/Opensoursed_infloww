"""Priority mass message's part of the slop relay (lib/relay.py loads it: `wire` runs at the end
of its `_wire`). The legs (`automations.priority_mass`) run on demand through relay.py's
`POST /__slop/run-automation {kind: "priority_mass", claim: true}` (and the real supervisor's
ticks, a scenario's SLOP_SUPERVISOR=1).

Inert unless a scenario writes its files under `$DEMO_SHOTS_TMP`:
  `of-rosters.json` {account: [{"id": OF list id, "name": str, "members": [fan ids]}]}
       OF's custom lists. The leg's freeze reads them through `audiences.roster_audience_blocking`
       -> `of_paging.list_member_ids` -> `client.list_users_in`. The automation client is
       lib/automation_relay.py's offline walker (`ax._make_client`, no `OF_API_ORIGIN`), whose
       `list_users_in` serves its in-process lists (`_of_lists` / `_of_members`, its call
       latency `list_s` from its own `of-mass.json`, which the scenario writes). This module only
       FEEDS those lists from the file (`add_lists`): at wire (so a restarted relay has them again) and on
       `POST /__slop/priority-mass/rosters`. No OF method is redefined here.
  `of-pm.json` {"write_gap_s": s, "hang": {"<account>:<fan>": hang_s}}, read on every call (the
       scenario replaces it whole). While it exists:
    OF's record of every send (`_OfflineOF.send_message`, wrapped as send_once_relay does):
       `$DEMO_SHOTS_TMP/of-pm-sends.jsonl`, one line per message OF took ({account_id, fan_id, id,
       price, t}), each one write(2) on an O_APPEND fd, so it outlives a SIGKILLed relay; in send
       order. relay.py keeps only a counter (and PPV prices per fan in-process, lost with a kill),
       hence this file.
    A hung send, for the crash leg (`hang`): OF takes that fan's message (its line is written),
       then the call blocks `hang_s` in its worker thread, as a curl whose answer never comes. The
       scenario SIGKILLs the relay meanwhile.
    The per-Creator OF write gap, compressed (declared bypass): `of_write._OF_WRITE_GAP_S` (11 s) is
       bound as `of_write_paced`'s `min_gap_s` default, so `ax.of_write_paced` is wrapped to pass
       `write_gap_s` when the caller names no gap. The gate, its order and the operator tier stay
       the product's (write_gate.WriteGate).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import Request   # module level: the route's annotation is a string here


def _tmp() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", ""))


def _cfg() -> dict | None:
    """`of-pm.json`; None = inert."""
    f = _tmp() / "of-pm.json"
    return json.loads(f.read_text()) if f.is_file() else None


def read_sends(tmp: Path) -> list[dict]:
    """OnlyFans' record under `tmp` (the run's DEMO_SHOTS_TMP), in order; the scenario reads it."""
    f = tmp / "of-pm-sends.jsonl"
    if not f.is_file():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def _line(row: dict) -> None:
    fd = os.open(_tmp() / "of-pm-sends.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)


def _feed_lists() -> int:
    """automation_relay's in-process OF lists from `of-rosters.json`; answers the lists fed."""
    import automation_relay as ar
    f = _tmp() / "of-rosters.json"
    if not f.is_file():
        return 0
    rows = [(str(aid), lst["name"], (int(m) for m in lst["members"]), int(lst["id"]))
            for aid, lists in json.loads(f.read_text()).items() for lst in lists]
    return len(ar.add_lists(rows))


def wire(app, loopback, relay) -> None:
    import automation_executor as ax

    real_send = relay._OfflineOF.send_message

    def send_message(self, chat_id, text, **kw) -> dict:
        msg = real_send(self, chat_id, text, **kw)
        cfg = _cfg()
        if cfg is None:
            return msg
        aid, fid = str(self.account_id), int(chat_id)
        _line({"account_id": aid, "fan_id": fid, "id": int(msg["id"]), "price": kw.get("price") or 0,
               "t": time.time()})          # OnlyFans has it from here on
        hang = float(cfg["hang"].get(f"{aid}:{fid}", 0.0))
        if hang:
            time.sleep(hang)
        return msg

    relay._OfflineOF.send_message = send_message

    real_paced = ax.of_write_paced

    async def of_write_paced(account_id, fn, **kw):
        cfg = _cfg()
        if cfg is not None and "min_gap_s" not in kw:
            kw["min_gap_s"] = float(cfg["write_gap_s"])
        return await real_paced(account_id, fn, **kw)

    ax.of_write_paced = of_write_paced
    _feed_lists()     # a restarted relay: OF still has the lists

    async def rosters(request: Request) -> dict:
        loopback(request)
        return {"lists": _feed_lists()}

    app.add_api_route("/__slop/priority-mass/rosters", rosters, methods=["POST"])
