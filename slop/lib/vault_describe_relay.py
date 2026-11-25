import json
import os
import threading
import time
from pathlib import Path

M30, M235 = "qwen3-vl-30b", "qwen3-vl-235b"
_REFUSAL = "I'm sorry, I can't help with that."
FAKE_KEY = "slop-fake-deepinfra"
HOSTILE_DESC = "FLAGS PASS MUST NOT WRITE THIS"
HOSTILE_TAG = "flagspass"
FLAGS_PROMPT = "slop: the retired qwen flags prompt. Answer the flags JSON."
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"items": {}, "latency_s": 0.0}
_port: int | None = None
CFG_FILE = "deepinfra.json"


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


def size_key(wh) -> str:
    return f"{wh[0]}x{wh[1]}"


# blue marks a clip frame; survives h264 yuv420p, the product's JPEG re-encodes and 400 px scrub (measured: worst channel error 2 of 9/14 margin)
CLIP_B = 230


def clip_rgb(g: int, i: int) -> tuple[int, int, int]:
    return 16 + 18 * i, 40 + 28 * g, CLIP_B


def clip_key(wh, g: int) -> str:
    return f"{size_key(wh)}:g{g}"


def image_key(data: bytes) -> tuple[str | None, int | None]:
    import io

    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            wh = im.size
            r, g, b = im.convert("RGB").getpixel((wh[0] // 2, wh[1] // 2))
    except Exception:  # noqa: BLE001 — an image the seeder did not make: no item
        return None, None
    if b < (CLIP_B + 120) // 2:
        return size_key(wh), None
    return clip_key(wh, round((g - 40) / 28)), round((r - 16) / 18)


def item_key(it: dict) -> str:
    return clip_key(it["size"], it["tint"]) if it.get("tint") is not None else size_key(it["size"])


def describe_text(account_id, media_id, model: str) -> str:
    return f"slop vault item {account_id}:{media_id} described by {model}"


PROSE_CLAIMS = {"nipple": "Her nipples are visible.", "vulva": "Her pussy is visible.",
                "pen": "A toy is inserted into her."}


PROSE_GARMENTS = ["red lace bra", "black thong"]


def prose_text(account_id, media_id, model: str) -> str:
    return " ".join([describe_text(account_id, media_id, model) + ".", *PROSE_CLAIMS.values()])


def recipe_of(text: str) -> tuple[str | None, list[str]]:
    import vault_ai_vision
    import vault_describe_jev

    if text in (vault_ai_vision._DESCRIBE_PROMPT_V2, vault_ai_vision._DESCRIBE_PROMPT):
        return "v2", []
    v2, jd = vault_ai_vision._DESCRIBE_PROMPT_V2, vault_describe_jev
    for name, base, top in (("v6", v2, jd.HEAD), ("prose", jd.PROSE_PROMPT, jd.HEAD), ("vid", v2, jd.VIDEO_HEAD)):
        i = base.index("RULES\n")
        head, tail = base[:i], base[i:]
        if len(text) > len(base) and text.startswith(head) and text.endswith(tail):
            block = text[len(head):len(text) - len(tail)]
            if block.startswith(top):
                return name, [ln[2:] for ln in block[len(top):].splitlines() if ln.startswith("- ")]
    return None, []


async def arm_run(http, tmp: Path, items: list[dict], latency_s: float) -> dict:
    (Path(tmp) / CFG_FILE).write_text(json.dumps({
        "latency_s": latency_s,
        "items": {item_key(it): [it["account_id"], it["media_id"], it["outcome"]]
                  for it in items if it["outcome"]}}))
    r = await http.post("/__slop/vault-describe/arm", json={"video_urls": [it["url"] for it in items if it["url"]]})
    if r.status_code != 200:
        raise RuntimeError(f"slop: vault-describe arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


def _usage(purpose: str, answer: str, images: int) -> tuple[int, int]:
    if purpose == "flags":
        return 600, 60
    return 1000 + 400 * images, {"ok": 250, "refuse": 12, "blank": 0}.get(answer, 0)


def _billed_mc(model: str, t_in: int, t_out: int) -> int:
    import llm_models

    m = llm_models.MODELS[model]
    return round((t_in * m.input_per_1k_cents + t_out * m.output_per_1k_cents) / 10)


def _size_of(data_url: str) -> str | None:
    import base64
    try:
        return image_key(base64.b64decode(data_url.partition(",")[2]))[0]
    except ValueError:
        return None


def _record(**rec) -> dict:
    with _lock:
        rec = {"i": len(_calls), "t": time.time(), **rec}
        _calls.append(rec)
    return rec


def _answer(body: dict, auth: str) -> tuple[int, dict]:
    import llm_client

    msgs = body.get("messages") or []
    parts = (msgs[-1].get("content") if msgs else None) or []
    parts = parts if isinstance(parts, list) else [{"type": "text", "text": str(parts)}]
    text = next((p.get("text") for p in parts if p.get("type") == "text"), "")
    images = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
    wire = body.get("model")
    model = next((k for k, m in llm_client.MODELS.items() if m.wire_model() == wire), wire)
    recipe, facts = recipe_of(text)
    purpose = "describe" if recipe else "flags" if text == FLAGS_PROMPT else "other"
    ikey = _size_of(images[0]) if images else None
    item = _cfg["items"].get(ikey)
    base = {"purpose": purpose, "model": model, "images": len(images), "key": ikey,
            "auth": auth == f"Bearer {FAKE_KEY}"}
    if recipe:
        import vault_describe_jev
        base.update(recipe=recipe, facts=facts,
                    hedge=vault_describe_jev.HEDGE in facts or vault_describe_jev.VIDEO_HEDGE in facts)
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
    elif recipe == "prose":
        content = json.dumps({"description": prose_text(aid, mid, model), "clothing_items": PROSE_GARMENTS})
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
