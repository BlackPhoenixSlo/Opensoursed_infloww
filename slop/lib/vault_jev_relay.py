import json
import os
import re
import threading
import time
from pathlib import Path

CFG_FILE = "typesafe-vault.json"
TOKENS = {"1": 2900, "2": 1700, "L": 2300}
LOW, HIGH = 0.01, 0.95
DOWN = "down"
BASE = {"people_count": "one", "breasts_state_a": "normal_covered", "breasts_state_b": "normal_covered",
        "crotch_state_a": "normal_covered", "crotch_state_b": "normal_covered", "butt_state_a": "not_visible",
        "added_text": "nothing_added", "toy": "no_toy", "feet_detail_a": "not_in_picture",
        "feet_detail_b": "not_in_picture", "outfit": "everyday_clothes", "setting": "bedroom", "hair": "down",
        "pose": "standing", "framing": "upper_body", "face_visible": "full_face", "facing": "toward_camera",
        "person_present": 0.97}
_NIPPLE = {"nipple_visible_a": HIGH, "nipple_visible_b": HIGH, "topless": HIGH,
           "breasts_state_a": "bare", "breasts_state_b": "bare"}
_HALF_NIPPLE = {"nipple_visible_a": 0.5, "nipple_visible_b": 0.5}
PROFILES = {
    "none": {},
    "pen": {"1": {"penetration": HIGH, "penetration_b": HIGH}},
    "vulva": {"1": {"vulva_visible_a": HIGH, "vulva_visible_b": HIGH,
                    "crotch_state_a": "bare", "crotch_state_b": "bare"}},
    "nipple": {"1": _NIPPLE},
    "lower": {"1": {**_NIPPLE, "crotch_state_a": "hidden_not_worn", "crotch_state_b": "hidden_not_worn"},
              "L": {"vulva_visible_a": 0.9, "vulva_visible_b": 0.9}},
    "unsure": {"1": _HALF_NIPPLE},
    "pen_unsure": {"1": {"penetration": 0.66, "penetration_b": 0.66}},
    "p2_clear": {"1": _HALF_NIPPLE, "2": _NIPPLE},
    # TypeSafe refuses it: HTTP 400 (the SDK does not retry a 4xx)
    DOWN: {},
}
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"items": {}, "clips": {}, "latency_s": 0.0, "armed": False}


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


def clip_keys(it: dict) -> dict[str, str | None]:
    base = f"cdn2.onlyfans.com/files/slop/{it['account_id']}/{it['media_id']}"
    no720 = it["src"] == "no720"
    return {"240": f"{base}_240.mp4", "720": None if no720 else f"{base}_720.mp4",
            "full": None if no720 else f"{base}_full.mp4"}


async def arm_jev(http, tmp: Path, items: list[dict], latency_s: float) -> dict:
    from slop.lib.vault_describe_relay import clip_key, size_key

    (Path(tmp) / CFG_FILE).write_text(json.dumps({
        "latency_s": latency_s,
        "items": {**{size_key(it["size"]): [it["account_id"], it["media_id"], it["jev"]]
                     for it in items if it.get("jev")},
                  **{clip_key(it["frame_size"], it["tint"]): [it["account_id"], it["media_id"], it["frames"]]
                     for it in items if it.get("frames")}},
        "clips": {f"{it['account_id']}:{it['media_id']}": {**clip_keys(it), "duration": it["duration"]}
                  for it in items if it.get("frames")}}))
    r = await http.post("/__slop/vault-jev/arm", json={})
    if r.status_code != 200:
        raise RuntimeError(f"slop: vault-jev arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


# TypeSafe Jev 1.14: $0.042 per million input tokens, output free; 1 cent = 100 millicents, rounded up per photo
MC_PER_TOKEN = (42, 100_000)
PHOTO_EDGE = (280, 448)


def price_mc(tokens: int) -> int:
    n, d = MC_PER_TOKEN
    return -(-tokens * n // d)


def photo_sizes(items) -> None:
    lo, hi = PHOTO_EDGE
    span = hi - lo + 1
    photos = [it for it in items if it["kind"] == "photo"]
    if len(photos) > span * span:
        raise ValueError(f"slop: {len(photos)} photos > {span * span} sizes in {PHOTO_EDGE}")
    for j, it in enumerate(photos):
        it["size"] = (lo + j % span, lo + j // span)


def _signed(key: str) -> str:
    from img_relay import policy_b64

    url = f"https://{key}"
    pol = policy_b64({"Statement": [{"Resource": url, "Condition": {
        "DateLessThan": {"AWS:EpochTime": int(time.time()) + 86_400}}}]})
    return f"{url}?Policy={pol}&Signature=slop&Key-Pair-Id=slop"


class OF:

    def vault_media_by_id(self, media_id) -> dict:
        c = _cfg["clips"].get(f"{self.account_id}:{int(media_id)}") if _cfg["armed"] else None
        if c is None:
            nxt = getattr(super(), "vault_media_by_id", None)
            if nxt is None:
                raise self._err
            return nxt(media_id)
        base = c["240"].rsplit("_", 1)[0]
        return {"id": int(media_id), "type": "video", "isReady": True, "hasError": False, "canView": True,
                "duration": c["duration"],
                "videoSources": {"240": _signed(c["240"]), "720": _signed(c["720"]) if c["720"] else None},
                "files": {**({"full": {"url": _signed(c["full"])}} if c["full"] else {}),
                          "thumb": {"url": f"https://{base}_thumb.jpg"},
                          "preview": {"url": f"https://{base}_preview.jpg"}}}


def _parts(body: bytes, ctype: str) -> dict[str, bytes]:
    m = re.search(r'boundary="?([^";]+)"?', ctype)
    if not m:
        return {}
    out = {}
    for chunk in body.split(b"--" + m.group(1).encode())[1:]:
        if chunk.startswith(b"--"):
            break
        head, _, data = chunk.partition(b"\r\n\r\n")
        n = re.search(rb'name="([^"]+)"', head)
        if n:
            out[n.group(1).decode()] = data[:-2] if data.endswith(b"\r\n") else data
    return out


def _pass(state: dict, qs: set) -> str:
    import vault_jev

    if "photo" in state and qs == set(vault_jev.Q):
        return "1"
    if "photo" in state and qs == set(vault_jev.Q2):
        return "2"
    if "full_photo" in state and qs == {"vulva_visible_a", "vulva_visible_b"}:
        return "L"
    return "other"


def _answers(profile: str, pss: str, questions: dict) -> dict:
    prof = PROFILES[profile]
    over = {**BASE, **(prof.get("L", {}) if pss == "L" else {**prof.get("1", {}), **(prof.get("2", {}) if pss == "2"
                                                                                         else {})})}
    out = {}
    for q, spec in questions.items():
        if spec.get("type") == "noul":
            out[q] = {"type": "noul", "noul": float(over.get(q, LOW))}
            continue
        keys = list(spec.get("criteria") or {})
        pick = over.get(q) if over.get(q) in keys else keys[0]
        rest = (1 - HIGH) / max(1, len(keys) - 1)
        probs = {k: (HIGH if k == pick else rest) for k in keys}
        out[q] = {"type": "choice", "choice": pick, "confidence": HIGH, "probabilities": probs}
    return out


def _record(**rec) -> dict:
    with _lock:
        rec = {"i": len(_calls), "t": time.time(), **rec}
        _calls.append(rec)
    return rec


async def _handle(request):
    import asyncio

    from fastapi.responses import JSONResponse

    ctype = request.headers.get("content-type", "")
    if not _cfg["armed"] or not ctype.startswith("multipart/form-data"):
        return None
    parts = _parts(await request.body(), ctype)
    try:
        body = json.loads(parts.get("request") or b"{}")
    except ValueError:
        body = {}
    from vault_describe_relay import image_key

    state, qs = body.get("state") or {}, body.get("questions") or {}
    pss = _pass(state, set(qs))
    ref = state.get("full_photo" if pss == "L" else "photo")
    part = ((body.get("assets") or {}).get(ref) or {}).get("part") if isinstance(ref, str) else None
    key, frame = image_key(parts.get(part) or b"") if part else (None, None)
    item = _cfg["items"].get(key)
    if item is not None and isinstance(item[2], list):
        item = [*item[:2], item[2][frame]] if frame is not None and 0 <= frame < len(item[2]) else None
    base = {"pass": pss, "model": body.get("model"), "questions": len(qs), "state": sorted(state), "frame": frame,
            "auth": request.headers.get("authorization", "") == f"Bearer {os.environ.get('TYPESAFE_API_KEY', '')}",
            "danger": request.headers.get("typesafe-danger-zone-images") == "true"}
    if pss == "other" or item is None:
        _record(**base, account_id=None, media_id=None, profile=None, tokens_in=0, status=500)
        return JSONResponse({"detail": f"slop fake Jev (vault): unplaced call (pass={pss}, item={item})"},
                            status_code=500)
    aid, mid, profile = item
    if profile == DOWN:
        _record(**base, account_id=aid, media_id=mid, profile=profile, tokens_in=0, status=400)
        return JSONResponse({"detail": "slop fake Jev (vault): this photo's profile is down"}, status_code=400)
    t_in = TOKENS[pss] + int(mid) % 89
    _record(**base, account_id=aid, media_id=mid, profile=profile, tokens_in=t_in, status=200)
    await asyncio.sleep(_cfg["latency_s"])
    return {"model": body.get("model"), "usage": {"input_tokens": t_in, "output_tokens": len(qs)},
            "answers": _answers(profile, pss, qs)}


def wire(app, loopback, _relay) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    import typesafe_relay

    if _handle not in typesafe_relay.HANDLERS:
        typesafe_relay.HANDLERS.append(_handle)

    async def arm(request: Request):
        loopback(request)
        if not _on() or os.environ.get("SLOP_LIVE") == "1":
            return JSONResponse({"error": f"slop: no $DEMO_SHOTS_TMP/{CFG_FILE} (or SLOP_LIVE=1): not armed"},
                                status_code=409)
        d = json.loads(_file().read_text())
        _cfg.update(items=d.get("items") or {}, clips=d.get("clips") or {}, latency_s=float(d.get("latency_s") or 0),
                    armed=True)
        return {"items": len(_cfg["items"]), "clips": len(_cfg["clips"])}

    async def calls(request: Request, since: int = 0, until: int | None = None) -> dict:
        loopback(request)
        with _lock:
            return {"calls": [dict(c) for c in _calls[since:until]]}

    async def count(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"n": len(_calls)}

    app.add_api_route("/__slop/vault-jev/arm", arm, methods=["POST"])
    app.add_api_route("/__slop/vault-jev/calls", calls, methods=["GET"])
    app.add_api_route("/__slop/vault-jev/count", count, methods=["GET"])
