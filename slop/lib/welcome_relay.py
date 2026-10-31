"""send_welcome's part of the slop relay (lib/relay.py loads it: `OF` joins `_OfflineOF`'s
bases, `wire` runs at the end of its `_wire`): OnlyFans' side of a welcome sweep, at the
client boundary (`automation_executor._make_client`'s offline client).

Only when a scenario writes `$DEMO_SHOTS_TMP/of-welcome.json` ({"feed": {account_id:
[notification items, newest first]}, "of_welcome_on": [account_id]}; read on every call, so a
scenario rewrites it between phases); without it every call re-raises the client build's
error as before:
  notifications(limit, offset, type)  GET /api2/v2/users/notifications: the Creator's feed,
                       `limit` from `offset`, `hasMore`; with `type` only items of that type
                       (OF's own filter; `type=subscribed` is what send_welcome asks).
  my_settings()        GET /users/me/settings: `replyOnSubscribe` true for an `of_welcome_on`
                       Creator, false otherwise.
  message_templates()  the Creator's `reply_on_subscribe` template, with a text when OF's
                       welcome is on (empty list otherwise).
  follow_user(id)      POST /api2/v2/users/{id}/subscribe (the follow-back): recorded, `{ok}`.
  get_user(id)         GET /api2/v2/users/{id} for a fan in the Creator's feed: `{id, username,
                       name, subscribePrice: 0}` (a free profile, not followed yet: the
                       follow-back's money gate passes). Wrapped in `wire` (lib/focus_relay.py's
                       `OF.get_user` comes first in the bases); any other id: as before.
  send_message         (wrapped in `wire`) answered by `_OfflineOF` as before, recorded per
                       Creator: {fan, id, text, giphy}.

  GET /__slop/welcome  {sends: {account: [...]}, follows: {account: [fan, ...]},
                       feed_reads: {account: n}, settings_reads: {account: n}}: what OF received.

Declared fakes: the feed's shape (`type`, `createdAt`, `user`) is the one send_welcome's parser
reads (its tests' and OF's `user` key); OF's latency is nil; a template's body is a guess.
"""

import json
import os
import threading
from collections import defaultdict
from pathlib import Path

_lock = threading.Lock()   # the run's sends and follows come from worker threads
_seen: dict = {"sends": defaultdict(list), "follows": defaultdict(list),
               "feed_reads": defaultdict(int), "settings_reads": defaultdict(int)}


def _cfg() -> dict | None:
    f = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-welcome.json"
    return json.loads(f.read_text()) if f.is_file() else None


def _feed_user(cfg: dict, aid: str, uid: int) -> dict | None:
    for it in cfg.get("feed", {}).get(aid, ()):
        if int(it["user"]["id"]) == int(uid):
            return it["user"]
    return None


class OF:
    def notifications(self, *, limit: int = 10, offset: int = 0, type=None, **_kw) -> dict:
        cfg = _cfg()
        if cfg is None:
            raise self._err
        items = [it for it in cfg.get("feed", {}).get(self.account_id, ())
                 if not type or it.get("type") == type]
        with _lock:
            _seen["feed_reads"][self.account_id] += 1
        page = items[int(offset):int(offset) + int(limit)]
        return {"list": page, "hasMore": int(offset) + int(limit) < len(items)}

    def my_settings(self) -> dict:
        cfg = _cfg()
        if cfg is None:
            raise self._err
        with _lock:
            _seen["settings_reads"][self.account_id] += 1
        return {"replyOnSubscribe": self.account_id in cfg.get("of_welcome_on", ())}

    def message_templates(self) -> dict:
        cfg = _cfg()
        if cfg is None:
            raise self._err
        if self.account_id not in cfg.get("of_welcome_on", ()):
            return {"list": []}
        return {"list": [{"template": "reply_on_subscribe", "text": "<p>thanks for subbing babe</p>",
                          "mediaCount": 0}]}

    def follow_user(self, user_id) -> dict:
        if _cfg() is None:
            raise self._err
        with _lock:
            _seen["follows"][self.account_id].append(int(user_id))
        return {"ok": True}


def wire(app, loopback, relay) -> None:
    from fastapi import Request

    real_get_user = relay._OfflineOF.get_user
    real_send = relay._OfflineOF.send_message

    def get_user(self, user_id, *a, **kw) -> dict:
        cfg = _cfg()
        u = _feed_user(cfg, self.account_id, user_id) if cfg is not None and str(user_id).isdigit() else None
        if u is None:
            return real_get_user(self, user_id, *a, **kw)
        return {**u, "subscribePrice": 0}

    def send_message(self, chat_id, text, **kw) -> dict:
        msg = real_send(self, chat_id, text, **kw)
        if _cfg() is not None:
            with _lock:
                _seen["sends"][self.account_id].append(
                    {"fan": int(chat_id), "id": msg["id"], "text": text, "giphy": kw.get("giphy_id")})
        return msg

    relay._OfflineOF.get_user = get_user
    relay._OfflineOF.send_message = send_message

    async def seen(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {k: dict(v) for k, v in _seen.items()}

    app.add_api_route("/__slop/welcome", seen, methods=["GET"])
