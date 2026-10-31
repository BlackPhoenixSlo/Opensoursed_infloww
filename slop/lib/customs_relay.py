"""The owed-customs queue's part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`, after any other flow's part sorted before it).

`POST /admin/customs/brief` asks DeepSeek (`deepseek-v4-flash`, purpose `customs_brief`) for
the work order. That one prompt is faked at DeepSeek's wire: `llm_providers.PROVIDERS
["deepseek"]` is re-pointed at a loopback server of this module's own (its own port, a
thread per call), which answers the brief's prompt (its system text opens with BRIEF_OPENER)
after LATENCY_S with JSON in the brief's schema read off the transcript the product built:
`summary` names the fan's first HIM line, `his_words` are his HIM lines that mention a
custom (copied whole, so `_whole_messages` keeps them), `call_him` is the name after
"call me". Every other prompt is forwarded unchanged to the provider this replaced when that
one is on loopback (another flow's fake), else answered 503: no
other purpose becomes reachable. Counted as `deepseek:customs_brief` at GET
/__slop/fake/calls. With SLOP_LIVE=1 nothing is installed.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit

BRIEF_OPENER = "You read one OnlyFans fan's chat with the creator and write the WORK ORDER"
LATENCY_S = 0.4  # a guess, as fm_fakes.DEEPSEEK_LATENCY_S


def _brief(user: str) -> dict:
    him = [ln.split(":", 1)[1].strip() for ln in user.splitlines() if ln.startswith("HIM ") and ":" in ln]
    call = next((m.group(1) for ln in him for m in [re.search(r"call me (\w+)", ln)] if m), None)
    asks = [ln for ln in him if "custom" in ln.lower()] or him[:1]
    return {"summary": f"Record the voice note he asked for: {him[0]}" if him else "",
            "his_words": asks[:3], "call_him": call, "found_request": bool(him)}


def _serve(prev: str, fake_calls) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    forward = urlsplit(prev).hostname in ("127.0.0.1", "localhost")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}"
            body = json.loads(raw)
            msgs = body.get("messages") or []
            system = next((m["content"] for m in msgs if m.get("role") == "system"), "")
            if self.path == "/chat/completions" and system.startswith(BRIEF_OPENER):
                fake_calls["deepseek:customs_brief"] += 1
                user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
                time.sleep(LATENCY_S)
                status, out = 200, json.dumps({
                    "id": f"slop-customs-{fake_calls['deepseek:customs_brief']}", "object": "chat.completion",
                    "model": body.get("model"), "created": int(time.time()),
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": json.dumps(_brief(user))}}],
                    "usage": {"prompt_tokens": 900, "completion_tokens": 60, "total_tokens": 960}}).encode()
            elif forward:
                req = urllib.request.Request(prev.rstrip("/") + self.path, data=raw, method="POST",
                                             headers={"content-type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        status, out = r.status, r.read()
                except urllib.error.HTTPError as e:
                    status, out = e.code, e.read()
            else:
                fake_calls["deepseek:other"] += 1
                status, out = 503, b'{"error": {"message": "slop: only customs_brief is faked"}}'
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *_a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="slop-fake-deepseek-customs", daemon=True).start()
    return srv.server_address[1]


def wire(app, _loopback, relay) -> None:
    if os.environ.get("SLOP_LIVE") == "1":
        return
    import dataclasses

    import llm_providers
    p = llm_providers.PROVIDERS["deepseek"]
    llm_providers.PROVIDERS["deepseek"] = dataclasses.replace(
        p, base_url=f"http://127.0.0.1:{_serve(p.base_url, relay._fake_calls)}")
