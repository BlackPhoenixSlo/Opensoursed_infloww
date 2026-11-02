"""The vault describe sweep's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its
`_wire`; no `OF` class, so it adds no OnlyFans method). Used by scenarios/2026-11-01-vault-describe-sweep.py.

Inert unless the run wrote `$DEMO_SHOTS_TMP/deepinfra.json` (the scenario does, through `arm_run` below) AND then
armed it: without the file `POST /__slop/vault-describe/arm` is a 409 that changes nothing, and nothing else here
runs (the fake's port only exists after an arm), so every other scenario's relay is untouched.

  arm_run(http, tmp, items, latency_s)  (harness side, the scenario calls it before the seeder writes rows)
       writes `deepinfra.json` {items: {"WxH": [acct, id, outcome]}, latency_s} for the seeder's planned items,
       then POSTs the arm hook and answers its body.
  POST /__slop/vault-describe/arm {video_urls}   (loopback; 409 without the file or under SLOP_LIVE=1)
       0. reads `deepinfra.json` once (it is written before the arm and never after).
       1. DeepInfra's OpenAI-compatible wire, on its own loopback port (ThreadingHTTPServer, a thread per call,
          like lib/automation_relay.py's DeepSeek): `llm_providers.PROVIDERS["deepinfra"]` re-pointed there
          (`dataclasses.replace`), so `llm_client.chat` (key, cap reservation, grok_calls row, retries, cost)
          runs unchanged and only the HTTP answer is the fake's.
       2. The vision passes' still stores (`vault_stills.IMAGE_DIR` / `THUMB_DIR` / `POSTER_DIR`,
          `storyboard._STORYBOARD_DIR`, module globals read at call time) re-pointed into
          `$DEMO_SHOTS_TMP/vault-describe/`, so `vault_frames.collect` reads the seeded local stills (a photo's
          `IMAGE_DIR/<acct>/<id>.jpg`, a clip's warmed storyboard frames) and never touches OnlyFans or the
          checkout's /tmp stores. Answers {dirs, port, frames: storyboard._STORYBOARD_FRAMES,
          hashes: {video url: storyboard._video_path_hash(url)}}.
  GET  /__slop/vault-describe/calls?since=N&until=M   {calls}: every call the fake answered, in arrival order, [N:M].
  GET  /__slop/vault-describe/count                   {n}: how many calls so far.

What the fake answers (per call; the item is read off the first image's pixel size, which the seeder makes unique
per item: `shrink_data_url` never enlarges, so the flags pass's re-encode keeps it):
  a POST to any path but /chat/completions -> 404 (recorded: purpose "other", answer "unknown", billed 0)
  not a describe/flags prompt, or no seeded item -> 503 (recorded, answer "unknown", billed 0)
  describe prompt (`vault_ai_vision._DESCRIBE_PROMPT_V2` / `_DESCRIBE_PROMPT`), by the item's outcome in the file:
    ok      -> a describe answer whose description is `describe_text(acct, id, model)`
    refuse  -> M30: "I'm sorry, I can't help with that." (`vision.is_refusal`), M235: the ok answer
    blank   -> "" from both models
  flags prompt (`_FLAGS_PROMPT`) -> the flags JSON, plus a hostile `description` / `tags` the flags pass must ignore
Usage per answer (`_usage`), billed by `_billed_mc` from `llm_models.MODELS`' listed prices directly (not the
product's `llm_client._cost_millicents`, so a wrong product formula cannot agree with itself): that per-call
`billed_mc` is what the scenario sums against what the sweeps report. Every call waits `latency_s` (file; real
describe calls take ~14 s, compressed: declared).
Record per call: i, t, purpose (describe|flags|other), model, account_id, media_id, answer, images, tokens_in,
tokens_out, billed_mc, auth (the request carried the agency's dummy key as a Bearer).
"""

import json
import os
import threading
import time
from pathlib import Path

M30, M235 = "qwen3-vl-30b", "qwen3-vl-235b"  # the sweep's model and its escalation (vault_ai_vision)
_REFUSAL = "I'm sorry, I can't help with that."
FAKE_KEY = "slop-fake-deepinfra"  # the agency's dummy DeepInfra key (PUT /admin/my-llm-keys); never a real one
HOSTILE_DESC = "FLAGS PASS MUST NOT WRITE THIS"
HOSTILE_TAG = "flagspass"
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"items": {}, "latency_s": 0.0}
_port: int | None = None
CFG_FILE = "deepinfra.json"  # in $DEMO_SHOTS_TMP


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


def size_key(wh) -> str:
    return f"{wh[0]}x{wh[1]}"


def describe_text(account_id, media_id, model: str) -> str:
    """The description the fake's ok answer carries for one item and model (the scenario reads it back)."""
    return f"slop vault item {account_id}:{media_id} described by {model}"


async def arm_run(http, tmp: Path, items: list[dict], latency_s: float) -> dict:
    """Harness side: the outcomes file for the seeder's planned items, then the arm hook. Answers the arm body."""
    (Path(tmp) / CFG_FILE).write_text(json.dumps({
        "latency_s": latency_s,
        "items": {size_key(it["size"]): [it["account_id"], it["media_id"], it["outcome"]]
                  for it in items if it["outcome"]}}))
    r = await http.post("/__slop/vault-describe/arm", json={"video_urls": [it["url"] for it in items if it["url"]]})
    if r.status_code != 200:
        raise RuntimeError(f"slop: vault-describe arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


def _usage(purpose: str, answer: str, images: int) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) the fake reports for one answer."""
    if purpose == "flags":
        return 600, 60
    return 1000 + 400 * images, {"ok": 250, "refuse": 12, "blank": 0}.get(answer, 0)


def _billed_mc(model: str, t_in: int, t_out: int) -> int:
    """What DeepInfra would bill, in millicents, at the model's listed per-1k prices (no cache hits reported)."""
    import llm_models

    m = llm_models.MODELS[model]
    return round((t_in * m.input_per_1k_cents + t_out * m.output_per_1k_cents) / 10)


def _size_of(data_url: str) -> str | None:
    import base64
    import io

    from PIL import Image
    try:
        with Image.open(io.BytesIO(base64.b64decode(data_url.partition(",")[2]))) as im:
            return size_key(im.size)
    except Exception:  # noqa: BLE001 — an image the seeder did not make: no item
        return None


def _record(**rec) -> dict:
    with _lock:
        rec = {"i": len(_calls), "t": time.time(), **rec}
        _calls.append(rec)
    return rec


def _answer(body: dict, auth: str) -> tuple[int, dict]:
    import llm_client
    import vault_ai_vision

    msgs = body.get("messages") or []
    parts = (msgs[-1].get("content") if msgs else None) or []
    parts = parts if isinstance(parts, list) else [{"type": "text", "text": str(parts)}]
    text = next((p.get("text") for p in parts if p.get("type") == "text"), "")
    images = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
    wire = body.get("model")
    model = next((k for k, m in llm_client.MODELS.items() if m.wire_model() == wire), wire)
    purpose = ("describe" if text in (vault_ai_vision._DESCRIBE_PROMPT_V2, vault_ai_vision._DESCRIBE_PROMPT)
               else "flags" if text == vault_ai_vision._FLAGS_PROMPT else "other")
    item = _cfg["items"].get(_size_of(images[0])) if images else None
    base = {"purpose": purpose, "model": model, "images": len(images), "auth": auth == f"Bearer {FAKE_KEY}"}
    if purpose == "other" or item is None:
        _record(**base, account_id=None, media_id=None, answer="unknown", tokens_in=0, tokens_out=0, billed_mc=0)
        return 503, {"error": {"message": f"slop: deepinfra fake answers only the vault describe/flags prompts "
                                          f"for seeded items ({purpose}, item={item})"}}
    aid, mid, outcome = item
    answer = "flags" if purpose == "flags" else "ok" if outcome == "refuse" and model != M30 else outcome
    t_in, t_out = _usage(purpose, answer, len(images))
    rec = _record(**base, account_id=aid, media_id=mid, answer=answer, tokens_in=t_in, tokens_out=t_out,
                  billed_mc=_billed_mc(model, t_in, t_out))
    time.sleep(_cfg["latency_s"])
    if answer == "flags":
        content = json.dumps({"over_breasts": "white tank top", "over_vulva": None, "over_anus": None,
                              "breasts_vis": "covered", "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame",
                              "underwear_visible": False, "description": HOSTILE_DESC, "tags": [HOSTILE_TAG]})
    elif answer == "refuse":
        content = _REFUSAL
    elif answer == "blank":
        content = ""
    else:
        content = json.dumps({"description": describe_text(aid, mid, model), "tags": ["slop", "vault"],
                              "explicitness": "suggestive", "nsfw": True, "sellable": True,
                              "acts": ["posing"], "clothing_state": "lingerie_on", "beats": ["poses"],
                              "primary_folder": "lingerie", "confidence": 80})
    return 200, {"id": f"slop-di-{rec['i']}", "object": "chat.completion", "model": wire, "created": int(time.time()),
                 "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                 "usage": {"prompt_tokens": t_in, "completion_tokens": t_out, "total_tokens": t_in + t_out}}


def _serve() -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/chat/completions":
                _record(purpose="other", model=None, images=0, path=self.path, account_id=None, media_id=None,
                        answer="unknown", tokens_in=0, tokens_out=0, billed_mc=0,
                        auth=self.headers.get("authorization", "") == f"Bearer {FAKE_KEY}")
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            status, out = _answer(body, self.headers.get("authorization", ""))
            raw = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="slop-fake-deepinfra", daemon=True).start()
    return srv.server_address[1]


def _arm(video_urls: list[str]) -> dict:
    global _port
    import dataclasses

    import llm_providers
    import storyboard
    import vault_stills

    d = json.loads(_file().read_text())
    _cfg.update(items=d.get("items") or {}, latency_s=float(d.get("latency_s") or 0))
    root = Path(os.environ["DEMO_SHOTS_TMP"]) / "vault-describe"
    dirs = {"images": root / "images", "thumbs": root / "thumbs", "posters": root / "posters",
            "storyboard": root / "storyboard"}
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    vault_stills.IMAGE_DIR, vault_stills.THUMB_DIR = dirs["images"], dirs["thumbs"]
    vault_stills.POSTER_DIR, storyboard._STORYBOARD_DIR = dirs["posters"], dirs["storyboard"]
    if _port is None:
        _port = _serve()
        p = llm_providers.PROVIDERS["deepinfra"]
        llm_providers.PROVIDERS["deepinfra"] = dataclasses.replace(p, base_url=f"http://127.0.0.1:{_port}")
    return {"dirs": {k: str(v) for k, v in dirs.items()}, "port": _port, "frames": storyboard._STORYBOARD_FRAMES,
            "hashes": {u: storyboard._video_path_hash(u) for u in video_urls}}


def wire(app, loopback, relay) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def arm(request: Request):
        loopback(request)
        if not _on() or os.environ.get("SLOP_LIVE") == "1":
            return JSONResponse({"error": f"slop: no $DEMO_SHOTS_TMP/{CFG_FILE} (or SLOP_LIVE=1): not armed"},
                                status_code=409)
        body = await request.json()
        return _arm(list(body.get("video_urls") or []))

    async def calls(request: Request, since: int = 0, until: int | None = None) -> dict:
        loopback(request)
        with _lock:
            return {"calls": [dict(c) for c in _calls[since:until]]}

    async def count(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"n": len(_calls)}

    app.add_api_route("/__slop/vault-describe/arm", arm, methods=["POST"])
    app.add_api_route("/__slop/vault-describe/calls", calls, methods=["GET"])
    app.add_api_route("/__slop/vault-describe/count", count, methods=["GET"])
