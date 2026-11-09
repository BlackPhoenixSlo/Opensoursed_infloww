"""OnlyFans tracking links' part of the slop relay (lib/relay.py loads it: `OF` joins `_OfflineOF`'s
bases, `wire` runs at the end of its `_wire`). scenarios/2026-11-01-tracking-links-clicks.py uses it.

OnlyFans' /campaigns side is faked only when a scenario writes `$DEMO_SHOTS_TMP/of-campaigns.json`
(seed/tracking_campaigns.py): `{"latency_s": s, "accounts": {account_id: [OF /campaigns rows, OF's
order]}, "claimers": {"<campaign id>": [{id, name, username}, ...]}}`. Without it every method below
raises the client build's error, as `_OfflineOF.__getattr__` would for a method it lacks.

  tracking_links(limit, offset, with_deleted)  GET /api2/v2/campaigns: the Creator's rows (deleted ones
                                only with `with_deleted`) paged by offset / limit, `hasMore`; bare: the
                                first 10 (OF's default page). Rows created this run come first.
  campaign_claimers(id, limit, offset)         GET /api2/v2/campaigns/{id}/claimers: the link's fans
                                paged, `hasMore`; a link with none answers an empty list.
  create_tracking_link(name, code)             POST /api2/v2/campaigns: a new row (0 transitions, 0
                                subscribers, createdAt now), answered as OF's bare campaign dict.
Each call waits `latency_s` (a guess at OF's latency); the reads are counted per Creator / per link.

  GET /__slop/tracking-calls  {campaigns: {account: n}, claimers: {"account:campaign": [offset, ...]}}:
                               what OnlyFans received, in order.

Cloudflare Turnstile's siteverify (custom redirect links' "Bot check before redirect") is faked at its
wire: when the relay has TURNSTILE_SECRET_KEY (a scenario's RELAY_ENV) and no TURNSTILE_VERIFY_URL,
`wire` points the product's TURNSTILE_VERIFY_URL env seam (read per call by tracking_links_api) at

  POST /__slop/fake/turnstile-siteverify  Cloudflare's form body (secret, response, remoteip) -> {success}:
                               success iff the secret is the relay's and the token starts with "pass-"
                               (TURNSTILE_LATENCY_S a call, a guess at Cloudflare's).
  GET  /__slop/turnstile-calls {n, bad_secret, no_remoteip, tokens: {token: n}}: what Cloudflare received.
"""

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CREATED_ID_BASE = 990_000_000
TURNSTILE_LATENCY_S = 0.03   # a guess at Cloudflare's siteverify latency
_lock = threading.Lock()  # the product calls OF from worker threads (asyncio.to_thread)
_calls: dict = {"campaigns": defaultdict(int), "claimers": defaultdict(list)}
_world: dict = {}   # of-campaigns.json, read on the first call that finds it
_created: dict[str, list[dict]] = defaultdict(list)   # account -> rows created this run, newest first
_turnstile: dict = {"n": 0, "bad_secret": 0, "no_remoteip": 0, "tokens": defaultdict(int)}


def _data() -> dict | None:
    with _lock:
        if not _world:
            f = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-campaigns.json"
            if not f.is_file():
                return None
            _world.update(json.loads(f.read_text()))
        return _world


class OF:
    def _tracking_answer(self) -> dict:
        """The world, after OF's latency; the client build's error without one."""
        d = _data()
        if d is None:
            raise self._err
        time.sleep(float(d["latency_s"]))
        return d

    def tracking_links(self, *, limit=None, offset=0, with_deleted=False, **_kw):
        d = self._tracking_answer()
        with _lock:
            _calls["campaigns"][str(self.account_id)] += 1
            rows = list(_created[str(self.account_id)]) + list(d["accounts"].get(str(self.account_id), ()))
        if not with_deleted:
            rows = [r for r in rows if not r.get("isDeleted")]
        off, lim = int(offset or 0), int(limit if limit is not None else 10)
        return {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)}

    def campaign_claimers(self, campaign_id, *, limit=10, offset=0, query=None, **_kw) -> dict:
        d = self._tracking_answer()
        with _lock:
            _calls["claimers"][f"{self.account_id}:{int(campaign_id)}"].append(int(offset or 0))
        fans = d["claimers"].get(str(int(campaign_id)), [])
        off = int(offset or 0)
        return {"list": fans[off:off + int(limit)], "hasMore": off + int(limit) < len(fans)}

    def create_tracking_link(self, *, name, code=None, **_kw):
        self._tracking_answer()
        with _lock:
            n = sum(map(len, _created.values())) + 1
            row = {"id": CREATED_ID_BASE + n, "campaignCode": code if code is not None else 90_000 + n,
                   "campaignName": name, "countTransitions": 0, "countSubscribers": 0,
                   "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                   "endDate": None, "isDeleted": False}
            _created[str(self.account_id)].insert(0, row)
        return dict(row)


def wire(app, loopback, _relay) -> None:
    from fastapi import Request

    async def tracking_calls(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"campaigns": dict(_calls["campaigns"]),
                    "claimers": {k: list(v) for k, v in _calls["claimers"].items()}}

    app.add_api_route("/__slop/tracking-calls", tracking_calls, methods=["GET"])

    secret = os.environ.get("TURNSTILE_SECRET_KEY", "")
    if not secret or os.environ.get("TURNSTILE_VERIFY_URL"):
        return
    os.environ["TURNSTILE_VERIFY_URL"] = (
        f"http://127.0.0.1:{os.environ['DEMO_SHOTS_RELAY_PORT']}/__slop/fake/turnstile-siteverify")

    async def siteverify(request: Request) -> dict:
        import asyncio
        from urllib.parse import parse_qs

        loopback(request)
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        await asyncio.sleep(TURNSTILE_LATENCY_S)
        token = form.get("response", "")
        with _lock:
            _turnstile["n"] += 1
            _turnstile["bad_secret"] += form.get("secret") != secret
            _turnstile["no_remoteip"] += not form.get("remoteip")
            _turnstile["tokens"][token] += 1
        ok = form.get("secret") == secret and token.startswith("pass-")
        return {"success": ok, "error-codes": [] if ok else ["invalid-input-response"]}

    async def turnstile_calls(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {**_turnstile, "tokens": dict(_turnstile["tokens"])}

    app.add_api_route("/__slop/fake/turnstile-siteverify", siteverify, methods=["POST"])
    app.add_api_route("/__slop/turnstile-calls", turnstile_calls, methods=["GET"])
