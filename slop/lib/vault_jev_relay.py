"""The vault Jev v8 pass's part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its `_wire`; its
`OF` joins `_OfflineOF`'s bases). Used by scenarios/2026-11-11-vault-jev-flags.py, beside lib/vault_describe_relay.py
(DeepInfra, stills) and lib/img_relay.py (OF's CDN: the clips' mp4s).

TypeSafe's System One wire for `service/vault_jev.py`: the product's real `typesafe_sdk` client posts to
`$TYPESAFE_BASE_URL/v1/systemone` (lib/stack.py points it at the relay's `/__slop/fake/typesafe`, served by
lib/typesafe_relay.py). This module adds one `typesafe_relay.HANDLERS` entry, registered in `wire`: it claims a
request only once armed and only when it is the SDK's multipart body (a JSON `request` part + one image part per
asset); everything else falls through to the route's other handlers, untouched.

Inert unless the run wrote `$DEMO_SHOTS_TMP/typesafe-vault.json` (the scenario does, through `arm_jev`) AND armed it
(`POST /__slop/vault-jev/arm`; 409 without the file or under SLOP_LIVE=1).

  arm_jev(http, tmp, items, latency_s)  (harness side) writes {items: {"WxH": [acct, id, profile], "WxH:gT": [acct,
       id, [profile per frame]]}, clips: {"acct:id": {240, 720, full, duration}}, latency_s}, arms.
  photo_sizes(items), price_mc(tokens)  (harness side) the sizes it tells apart, what its tokens cost.
  GET /__slop/vault-jev/calls?since=N&until=M  {calls}   GET /__slop/vault-jev/count  {n}
  OF.vault_media_by_id(id)  an armed clip's media, OF's shape, signed now (`clip_keys`; "no720": 720 null, no full);
       any other id falls through to the next plugin (lib/vault_relay.py's minted media).

Which item: the image of state `photo` (pass 1 / pass 2) or `full_photo` (pass L), by `vault_describe_relay
.image_key`: a photo by its pixel size, a clip frame by its size + tint, its frame by its red. The scenario gives
every photo a size with both edges in [280, 448] and every clip 800 x H frames (H in [480, 958]), which every pass
keeps: `vault_jev.shrink` (EDGE 1024 / 1568) neither enlarges nor shrinks a still whose short edge is >= 280 and long
edge <= 1024, `enc` never enlarges, and the describe side's `shrink_data_url` keeps <= 448 (lib/vault_describe_relay.py
reads the same key; a clip's describe frames are its 400 px scrub frames, 400 x H/2 + tint).

Which pass: the question set (`vault_jev.Q` on `photo` = 1, `vault_jev.Q2` on `photo` = 2, the two vulva twins on
`full_photo` + crops = L); anything else is a 500 (recorded `pass: "other"`).

What it answers: `PROFILES[profile]` (below), per pass. Every Noul not named is 0.01 and every Choice its BASE pick
at 0.95 (the rest share 0.05), so an item is "nothing there" unless its profile says otherwise. The scenario plans
the lane each profile must end in from what the answers SAY (a bare vulva at .95 is a $50 photo), never from the
product's rules. Usage: `TOKENS[pass] + media_id % 89` input tokens (deterministic, per call; the scenario prices
them), output 1 per question. Profile `down`: a 400 and no answer, recorded status 400 / tokens 0.
Record per call: i, t (arrival), pass, account_id, media_id, frame (a clip's, else None), profile, tokens_in, status,
auth (Bearer of the stack's
TYPESAFE_API_KEY), danger (the `TypeSafe-Danger-Zone-Images: true` header), model, questions, state (keys).
"""

import json
import os
import re
import threading
import time
from pathlib import Path

CFG_FILE = "typesafe-vault.json"  # in $DEMO_SHOTS_TMP
TOKENS = {"1": 2900, "2": 1700, "L": 2300}
LOW, HIGH = 0.01, 0.95
# Choice questions' pick when a profile does not name one: a dressed woman, nothing added, no toy.
# The Jev-down profile: every call about it is a 400 (the SDK does not retry a 4xx; `vault_jev.run` -> status error).
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
# profile -> {pass: overrides}; pass "2" reads "1"'s overrides plus its own, pass "L" only its own.
PROFILES = {
    "none": {},                                                       # dressed, nothing bare
    "pen": {"1": {"penetration": HIGH, "penetration_b": HIGH}},       # something inserted
    "vulva": {"1": {"vulva_visible_a": HIGH, "vulva_visible_b": HIGH,
                    "crotch_state_a": "bare", "crotch_state_b": "bare"}},  # bare vulva
    "nipple": {"1": _NIPPLE},                                         # topless, crotch dressed
    "lower": {"1": {**_NIPPLE, "crotch_state_a": "hidden_not_worn", "crotch_state_b": "hidden_not_worn"},
              "L": {"vulva_visible_a": 0.9, "vulva_visible_b": 0.9}},  # topless, the zoomed lower crop: bare vulva
    "unsure": {"1": _HALF_NIPPLE},                                    # a coin-flip nipple, every pass, NudeNet 0
    "pen_unsure": {"1": {"penetration": 0.66, "penetration_b": 0.66}},  # a coin-flip insertion, every pass
    "p2_clear": {"1": _HALF_NIPPLE, "2": _NIPPLE},                    # a coin flip at 1024 px, plainly topless at 1568
    DOWN: {},                                                         # TypeSafe refuses it: HTTP 400, never answers
}
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"items": {}, "clips": {}, "latency_s": 0.0, "armed": False}


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


def clip_keys(it: dict) -> dict[str, str | None]:
    """A planned clip's CDN keys ("host/path"): its 240p (the seeder's url's path), 720p and `files.full` mp4s;
    `it["src"]` "no720": both None (no 720p rendition and no native file, so the product reads the 240p: a native
    `full` would be read first, and this fake's frames are all >= 480 px, D54's no-review size)."""
    base = f"cdn2.onlyfans.com/files/slop/{it['account_id']}/{it['media_id']}"
    no720 = it["src"] == "no720"
    return {"240": f"{base}_240.mp4", "720": None if no720 else f"{base}_720.mp4",
            "full": None if no720 else f"{base}_full.mp4"}


async def arm_jev(http, tmp: Path, items: list[dict], latency_s: float) -> dict:
    """Harness side: the profile file for every planned photo (`it["jev"]`) and clip (`it["frames"]`: a profile per
    frame, keyed by its frames' size + tint; its `clip_keys` for `OF.vault_media_by_id`), then the arm hook."""
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


# Harness side, for every scenario that arms this fake: the photo sizes it can tell apart (module docstring) and
# what its billed tokens cost. TypeSafe Jev 1.14: $0.042 per million input tokens, output free
# (docs.typesafe.ai/models, read 11-11), in the cap unit (1 cent = 100 millicents): 0.042 * 100 * 100 / 1e6 =
# 42 / 100,000 per token, rounded up per photo.
MC_PER_TOKEN = (42, 100_000)
PHOTO_EDGE = (280, 448)


def price_mc(tokens: int) -> int:
    n, d = MC_PER_TOKEN
    return -(-tokens * n // d)


def photo_sizes(items) -> None:
    """Every planned photo a unique size, both edges in PHOTO_EDGE (clips and audio keep the seeder's)."""
    lo, hi = PHOTO_EDGE
    span = hi - lo + 1
    photos = [it for it in items if it["kind"] == "photo"]
    if len(photos) > span * span:
        raise ValueError(f"slop: {len(photos)} photos > {span * span} sizes in {PHOTO_EDGE}")
    for j, it in enumerate(photos):
        it["size"] = (lo + j % span, lo + j // span)


def _signed(key: str) -> str:
    """`https://<key>` with a CloudFront custom Policy good for a day and no SourceIp (lib/img_relay.py's check)."""
    from img_relay import policy_b64  # relay side: lib/relay.py loaded it by its stem

    url = f"https://{key}"
    pol = policy_b64({"Statement": [{"Resource": url, "Condition": {
        "DateLessThan": {"AWS:EpochTime": int(time.time()) + 86_400}}}]})
    return f"{url}?Policy={pol}&Signature=slop&Key-Pair-Id=slop"


class OF:
    """GET /vault/media/{id} for an armed clip: OF's video shape, freshly signed (`videoSources` 240 / 720, the
    720 null when OF has none; `files.full` when planned, the thumb and preview). Any other id: the next plugin's
    answer."""

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
    """multipart/form-data parts by name (the SDK's `encode_multipart`: CRLF, one Content-Disposition each)."""
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
    """typesafe_relay.HANDLERS entry: None (not ours) unless armed and the body is the SDK's multipart."""
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
    from vault_describe_relay import image_key  # relay side: lib/relay.py loaded it by its stem

    state, qs = body.get("state") or {}, body.get("questions") or {}
    pss = _pass(state, set(qs))
    ref = state.get("full_photo" if pss == "L" else "photo")
    part = ((body.get("assets") or {}).get(ref) or {}).get("part") if isinstance(ref, str) else None
    key, frame = image_key(parts.get(part) or b"") if part else (None, None)
    item = _cfg["items"].get(key)
    if item is not None and isinstance(item[2], list):   # a clip: the profile of the frame its red spells
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

    import typesafe_relay  # owns the TypeSafe route

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
