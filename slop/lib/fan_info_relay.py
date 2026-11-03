"""The fan-info sweep's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its `_wire`; no
`OF` class, so it adds no OnlyFans method). Used by scenarios/2026-11-02-fan-info-sweep.py.

Its DeepSeek answer joins lib/automation_relay.py's ANSWERS at import (`insert(0)`, purpose None: the fake's 503
body still names only the other purposes, byte for byte). Inert unless the run wrote
`$DEMO_SHOTS_TMP/fan-info-extracts.json` (the scenario does, from seed/fan_info_history.py, before Run now):
without it every prompt passes through to the next answer as before.

  DeepSeek  a chat completion whose system turn is gen_info's profile prompt (`SYSTEM_HEAD`) and whose user turn
            names a seeded fan on its first line (`Fan OF display name: <name>`, gen_info's `_build_user_prompt`;
            the seeder makes each name unique per Creator x fan) gets that fan's extract from the file, as JSON
            text (gen_info asks `response_format=json_object`), after automation_relay.DEEPSEEK_LATENCY_S. Any
            other gen_info prompt (a fan the file does not know) is recorded and passed on (-> the 503).
            Counted at GET /__slop/fake/calls as deepseek:gen_info.
  OF push   gen_info's best-effort drawer push (`_fan_notes.push_nick_and_notes`: OF's PUT /subscriptions/{fan}
            with `displayName`, then `notice`) on the lane's client (`WALKER_MIXINS`): with the file present,
            `set_fan_custom_name` / `set_fan_note` are kept and answered `{"success": true}` (OF's body here is
            a guess; the product ignores it); without it they raise as before.
  GET /__slop/fan-info/calls   (loopback) {calls: [{name, known, t}], pushes: [{account_id, fan_id, field,
            value, t}]}: every gen_info prompt the fake saw and every push OF took, in arrival order (t: epoch s).
"""
import json
import os
import threading
import time
from pathlib import Path

CFG_FILE = "fan-info-extracts.json"   # in $DEMO_SHOTS_TMP: {"fans": {display name: extract}}
SYSTEM_HEAD = "You build a concise CRM profile of an OnlyFans fan"   # gen_info._SYSTEM_PROMPT's opening
NAME_LINE = "Fan OF display name: "                                  # gen_info._build_user_prompt's first line
_lock = threading.Lock()
_calls: list[dict] = []
_pushes: list[dict] = []
_cfg: dict | None = None


def prompt_name(user: str) -> str:
    """The display name on gen_info's user turn's first line ('' if the turn has none)."""
    first = user.split("\n", 1)[0]
    if not first.startswith(NAME_LINE):
        return ""
    return first[len(NAME_LINE):].split("  (", 1)[0].strip()


def write_extracts(tmp, extracts: dict) -> None:
    """Harness side: the file the fake answers from ({display name: extract}), atomically."""
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
        _cfg = json.loads(f.read_text())["fans"]   # written once, before Run now, never after
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
    """OF's side of gen_info's drawer push (module docstring), on the lane's client."""

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


try:   # relay side only: the harness imports this module for its helpers above
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
