import json
import os
import threading
import time
from pathlib import Path

CFG_FILE = "fan-info-extracts.json"
SYSTEM_HEAD = "You build a concise CRM profile of an OnlyFans fan"
NAME_LINE = "Fan OF display name: "
_lock = threading.Lock()
_calls: list[dict] = []
_pushes: list[dict] = []
_cfg: dict | None = None


def prompt_name(user: str) -> str:
    first = user.split("\n", 1)[0]
    if not first.startswith(NAME_LINE):
        return ""
    return first[len(NAME_LINE):].split("  (", 1)[0].strip()


def write_extracts(tmp, extracts: dict) -> None:
    f = Path(tmp) / CFG_FILE
    part = f.with_suffix(".tmp")
    part.write_text(json.dumps({"fans": extracts}))
    os.replace(part, f)


def _extracts() -> dict | None:
    global _cfg
    if _cfg is None:
        tmp = os.environ.get("DEMO_SHOTS_TMP")
        f = Path(tmp or "") / CFG_FILE
        if not tmp or not f.is_file():
            return None
        _cfg = json.loads(f.read_text())["fans"]
    return _cfg


def _answer(system: str, user: str) -> str | None:
    if not system.startswith(SYSTEM_HEAD):
        return None
    cfg = _extracts()
    if cfg is None:
        return None
    name = prompt_name(user)
    ext = cfg.get(name)
    with _lock:
        _calls.append({"name": name, "known": ext is not None, "t": time.time()})
    if ext is None:
        return None
    _base._fake_calls["deepseek:gen_info"] += 1
    return json.dumps(ext, ensure_ascii=False)


class _FanInfoWalker:

    def _push(self, fan_id, field: str, value: str) -> dict:
        if _extracts() is None:
            raise self._err
        with _lock:
            _pushes.append({"account_id": str(self.account_id), "fan_id": int(fan_id), "field": field,
                            "value": value, "t": time.time()})
        return {"success": True}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return self._push(user_id, "displayName", name)

    def set_fan_note(self, user_id, note) -> dict:
        return self._push(user_id, "notice", note)


try:
    import automation_relay as _base
except ImportError:
    _base = None
else:
    _base.ANSWERS.insert(0, (None, _answer))
    _base.WALKER_MIXINS.insert(0, _FanInfoWalker)


def wire(app, _loopback, _relay) -> None:
    from fastapi import Request

    async def calls(request: Request) -> dict:
        _loopback(request)
        with _lock:
            return {"calls": list(_calls), "pushes": list(_pushes)}

    app.add_api_route("/__slop/fan-info/calls", calls, methods=["GET"])
