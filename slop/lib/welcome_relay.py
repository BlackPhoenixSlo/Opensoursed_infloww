import json
import os
import threading
from collections import defaultdict
from pathlib import Path

_lock = threading.Lock()
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

    real_get_user = getattr(relay._OfflineOF, "get_user", None)
    real_send = relay._OfflineOF.send_message

    def get_user(self, user_id, *a, **kw) -> dict:
        cfg = _cfg()
        u = _feed_user(cfg, self.account_id, user_id) if cfg is not None and str(user_id).isdigit() else None
        if u is None:
            if real_get_user is None:
                return relay._OfflineOF.__getattr__(self, "get_user")(user_id, *a, **kw)
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
