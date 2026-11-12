"""vault_jev.py — the Jev v8 vault flags pass for one stored still: questions, calls, NudeNet, spend.

Per-account opt-in (`account_ai_config.vault_jev_enabled`, default off), photos only. The owner-accepted
bench config (D48, `.scratch/jev-vault-bench/`: jev_flags8.py + jev_crop8.py MODE "lower", frozen with
score8 `--veto --promote` and settle.py `nn.10`) ported as-is:

  pass 1   every question (`Q`) on the still shrunk to EDGE 1024 (`shrink`)
  pass 2   the lane-critical twelve (`Q2`) at EDGE2 1568, when `vault_jev_rules.derive8` says `need2`
  pass L   the full still + its lower part at 1568 (`crops`, `enc`), the vulva twins (`crop_questions`),
           when derive8 says `needL`
  NudeNet  640m.onnx on the SAME still at native resolution, max score per class (bench nn_detect.py)
  rules    `vault_jev_rules.final`: derive8 → NN_D34 veto/promote → settle nn.10

Question wording, criteria and their order, the `rev` twins, FEET, `state_opts`, crop geometry, edges,
JPEG q88 LANCZOS RGB and the shrink k rule are byte-identical to the bench; the golden test
(`tests/test_vault_jev.py`) checks the exported spec against one generated from the bench files.

NudeNet is a HARD dependency: without it (package, weights, md5) the pass refuses before any TypeSafe
call and stamps `_jev.status = "no_nudenet"` — never a Jev-only answer. The key is the deployment's
`TYPESAFE_API_KEY` (`llm_providers.typesafe_key`); spend is reserved and recorded against the
account's daily cap on the `typesafe` provider row (`llm_client.reserve_external`), like every
other provider's.

Storage contract (`ai_fields_json["_jev"]`, read by the vault lanes): see `vault_jev_rules.blob`.
A failure keeps the last good answer's fields and sets `status` (`no_nudenet` | `no_key` |
`error`) + `error` + `failed_at`; `status == "ok"` is the only state with a trustworthy `lane5`.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import os
import threading
import time
from datetime import datetime
from typing import Any, TypedDict

import vault_jev_rules as rules

log = logging.getLogger("of-relay.vault_jev")

MODEL = "jev-1.14.0"
EDGE = 1024     # pass 1
EDGE2 = 1568    # pass 2
EDGE_L = 1568   # pass L (jev_crop8 EDGE)
JPEG_QUALITY = 88
HEADERS = {"TypeSafe-Danger-Zone-Images": "true"}
PROVIDER = "typesafe"
PURPOSE = "vault_jev_flags"
# Jev 1.14: $0.042 per million input tokens, output free (docs.typesafe.ai/models, read 11-11).
# In llm_client's cap unit: $ → cents ×100 → millicents ×100.
MILLICENTS_PER_INPUT_TOKEN = 0.042 / 1e6 * 100 * 100
# Reserved up front for one image (pass 1 + 2 + L; bench max ~14k input tokens), settled to the real count.
RESERVE_TOKENS = 20000
# Per call, retries included (the SDK's RetryPolicy.timeout); the bench retried twice.
TIMEOUT_S = 90.0
MAX_RETRIES = 2

# ── Questions (jev_flags8.py, verbatim) ─────────────────────────────
# Kept as plain data so the spec can be exported and diffed; `_sdk_questions` builds the SDK objects.

REG = {"breasts": "breasts", "crotch": "crotch", "butt": "butt"}
BARE = {"breasts": "a nipple or areola is visible", "crotch": "the labia / vulva are visible",
        "butt": "the butt cheeks are bare (a thong string between them does not cover them)", "anus": "the anus itself is visible"}


def state_opts(r):
    return {
        "bare": f"Its skin is on show: {BARE[r]}.",
        "sheer_covered": "Covered only by see-through lace, mesh or wet fabric; the skin or nipple shows through.",
        "sexy_covered": "Fully hidden by a bra, lingerie, thong, panties, bikini or bodysuit.",
        "normal_covered": "Fully hidden by everyday clothes: top, t-shirt, dress, shorts, jeans, hoodie, sportswear.",
        "hidden_not_worn": "No garment is on it, but a hand, arm, hair, sheet, object, or a blur/pixelation/emoji hides it.",
        "not_visible": ("You cannot see her butt at all: she faces the camera, or it is cropped out." if r == "butt" else
                        "You cannot see that part of her body at all: it is cropped out of the picture or on the far side of her body."),
    }


def rev(d): return dict(reversed(list(d.items())))


FEET = {
    "not_in_picture": "Her feet cannot be seen in the picture.",
    "bare": "Bare feet: toes or soles with nothing on them.",
    "socks": "Ankle or knee socks cover her feet.",
    "stockings_fishnets_nylons": "Stockings, fishnets, nylons, pantyhose or thigh-highs cover her feet.",
    "heels": "High heels (any kind, including clear platform stripper heels).",
    "other_shoes": "Sneakers, boots, flats, slippers or sandals.",
}


def N(s): return {"type": "noul", "instructions": s}


def Choice(instructions, criteria): return {"type": "choice", "instructions": instructions, "criteria": criteria}


Q = {
    "person_present": N("Is there a real person (not a screenshot, text or interface) in `photo`?"),
    "people_count": Choice(instructions="How many people are in `photo`?", criteria={
        "one": "Exactly one person.", "two_or_more": "Two or more people.", "none": "No person (screenshot, text, object)."}),
    # direct evidence, twins
    "nipple_visible_a": N("Can you see a bare nipple or areola in `photo`, even a small slip at the edge of her top? A nipple under a bra, lace or fabric does not count."),
    "nipple_visible_b": N("Is any part of a nipple or areola uncovered (no fabric over it) and visible in `photo`, including in a mirror reflection?"),
    "nipple_through_fabric": N("Can you see a nipple or areola through sheer, lace, mesh or wet fabric in `photo`?"),
    "vulva_visible_a": N("Can you see bare labia or a bare vulva in `photo`?"),
    "vulva_visible_b": N("Is her genital area (labia / vulva) uncovered and visible in `photo`?"),
    "butt_cheeks_bare": N("Can you see bare butt cheeks in `photo`? A thong string between them still counts as bare."),
    "penetration": N("Is a toy, finger or other object inserted into her vagina or anus in `photo`?"),
    "penetration_b": N("Look at her vagina and anus in `photo`: is something (a finger, dildo, toy or object) inside either of them, not just touching or resting on it?"),
}
for r, name in REG.items():
    ins = f"In `photo`, what best describes the woman's {name}?"
    Q[f"{r}_state_a"] = Choice(instructions=ins, criteria=state_opts(r))
    if r in ("breasts", "crotch"):
        Q[f"{r}_state_b"] = Choice(instructions=f"Looking at `photo`, how is the woman's {name} shown?", criteria=rev(state_opts(r)))
Q.update({
    "added_text": Choice(instructions="Besides any small website address or username watermark, what has been added on top of `photo` in editing?", criteria={
        "caption_text": "Words or a sentence typed over the photo, a caption box, or a question/poll sticker.",
        "emoji_or_sticker_only": "Only emoji or stickers, no words.",
        "nothing_added": "Nothing added. A small 'OnlyFans.com/name' or username watermark alone counts as nothing."}),
    "watermark": N("Is there a small website address or username watermark in `photo`?"),
    "clothing_print_text": N("Is there writing printed on her clothing in `photo`?"),
    "censor_edit": N("Has part of her body in `photo` been blurred, pixelated or covered with an emoji or sticker?"),
    "toy": Choice(instructions="Is there a sex toy (dildo, vibrator, wand, butt plug) in `photo`? Everyday objects such as a phone, bottle, remote, hairbrush, makeup or stuffed animal are not sex toys.", criteria={
        "no_toy": "No sex toy.", "toy_visible_not_in_use": "A sex toy is visible but not touching her genitals or anus.",
        "toy_touching_or_inserted": "A sex toy is touching or inserted into her genitals or anus."}),
    "feet_detail_a": Choice(instructions="What is on the woman's feet in `photo`?", criteria=FEET),
    "feet_detail_b": Choice(instructions="Looking at her feet in `photo`, what are they wearing?", criteria=rev(FEET)),
    "feet_focus": N("Are her feet or soles the main subject of `photo`?"),
    "outfit": Choice(instructions="What is she wearing in `photo`?", criteria={
        "nude": "Nothing at all / fully nude.", "topless_with_bottoms": "No top: only panties, a thong, shorts, pants or a skirt.",
        "lingerie_or_bodysuit": "Lingerie: bra and panties, lace set, babydoll, bodysuit or teddy.", "swimwear": "A bikini or swimsuit.",
        "everyday_clothes": "Everyday clothes, gym clothes or a costume: top, dress, jeans, hoodie, leggings.",
        "sheet_or_towel": "Only a sheet or towel."}),
    "setting": Choice(instructions="Where was `photo` taken?", criteria={k: None for k in
        ["bedroom", "bathroom", "living_room", "kitchen", "outdoors", "car", "gym", "other"]}),
    "mirror_selfie": N("Is `photo` a mirror selfie (she photographs herself in a mirror)?"),
    "hair": Choice(instructions="How is her hair in `photo`?", criteria={
        "down": "Worn down / loose.", "ponytail_or_bun": "Ponytail or bun.", "braids": "Braided.",
        "covered_or_not_visible": "Covered or not visible."}),
    "self_touch": N("Is she touching her own breasts, crotch or butt in a sexy way in `photo`?"),
    "legs_spread": N("Are her legs spread open toward the camera in `photo`?"),
    "mouth_tease": N("Is she teasing with her mouth in `photo` (tongue out, biting lip, finger at mouth)?"),
    # --- v7 adds: owner-approved v4 keeps
    "topless": N("Is the woman in `photo` wearing nothing on her upper body (no bra, no top), even if her hands or hair cover her breasts?"),
    "see_through": N("Is she wearing sheer, lace, mesh, fishnet or wet fabric that clearly shows her skin underneath in `photo`?"),
    "pulling_clothes": N("In `photo`, is she pulling, lifting or moving a garment (strap, waistband, top, panties) to reveal more skin?"),
    "tongue_out": N("In `photo`, is her tongue out?"),
    "smiling": N("Is the woman smiling in `photo`?"),
    "jewelry": N("Is she wearing visible jewelry (necklace, earrings, rings, bracelet, piercing) in `photo`?"),
    "phone_visible": N("Is a phone visible in `photo`?"),
    "pose": Choice(instructions="What is her pose in `photo`?", criteria={
        "standing": "Standing.", "sitting": "Sitting.", "kneeling": "Kneeling.", "lying_on_back": "Lying on her back.",
        "lying_on_stomach": "Lying on her stomach.", "lying_on_side": "Lying on her side.",
        "all_fours_or_bent_over": "On all fours or bent over.", "close_up_no_pose": "A close-up; the pose cannot be told."}),
    "framing": Choice(instructions="How much of her body does `photo` show?", criteria={
        "face_close_up": "Mostly her face.", "face_and_chest": "Face down to the chest.", "upper_body": "Head to waist.",
        "most_of_body": "Head to thighs or knees.", "full_body": "Head to feet.",
        "body_part_close_up": "A close-up of one body part, face out of shot.",
        "body_no_face": "Torso and/or legs with the face cropped out, wider than one body part."}),
    # face (from extras6)
    "face_visible": Choice(instructions="How much of the woman's face can you see in `photo`?", criteria={
        "full_face": "Her face is clearly visible: both eyes and her mouth.",
        "partial_face": "Only part of her face: cropped, side profile edge, or covered by a phone, hair or hand.",
        "no_face": "Her face is not in the picture or is completely hidden."}),
    "facing": Choice(instructions="Which way is the front of her body turned relative to the camera in `photo`?", criteria={
        "toward_camera": "The front of her body faces the camera.", "side": "Her body is side-on to the camera.",
        "away": "Her back is to the camera."}),
    "looking_at_camera": N("Is she looking straight into the camera in `photo`?"),
    # body focus: one Noul each (several may be yes)
    "breasts_focus": N("Are her breasts a main subject of `photo`?"),
    "butt_focus": N("Is her butt a main subject of `photo`?"),
    "crotch_focus": N("Is her crotch / pussy area a main subject of `photo`?"),
    # footwear as separate yes/no (fixes heels vs other_shoes confusion, stockings under heels)
    "wears_heels": N("Is she wearing high heels in `photo`?"),
    "wears_stockings_or_fishnets": N("Is she wearing stockings, thigh-highs, fishnets, nylons or pantyhose on her legs in `photo`?"),
    "wears_socks": N("Is she wearing ankle or knee socks in `photo`?"),
    "bare_toes_visible": N("Can you see her bare toes in `photo`?"),
    "soles_visible": N("Are the soles of her feet (bare or in socks) turned toward the camera in `photo`?"),
    "feet_in_water": N("Are her feet in water (bath, pool, sea) in `photo`?"),
    # untested asks
    "multi_panel": N("Is `photo` a collage: several photos combined into one image or a split screen?"),
})

LANE_Q = ["nipple_visible_a", "nipple_visible_b", "vulva_visible_a", "vulva_visible_b", "breasts_state_a", "breasts_state_b",
          "crotch_state_a", "crotch_state_b", "penetration", "penetration_b", "topless", "nipple_through_fabric"]
Q2 = {k: Q[k] for k in LANE_Q}


# ── Pass L (jev_crop8.py, MODE "lower") ─────────────────────────────

def names(st): return ", ".join(f"`{k}`" for k in st)


def crop_questions(st, mode="lower"):
    n = names(st); any_ = "in `photo`" if list(st) == ["photo"] else f"in any of the images {n} (the crops are zoomed parts of `full_photo`)"
    q = {"vulva_visible_a": N(f"Can you see bare labia or a bare vulva {any_}?"),
         "vulva_visible_b": N(f"Is her genital area (labia / vulva) uncovered and visible {any_}?")}
    if not mode.startswith("lower"):
        raise ValueError("only pass L 'lower' is ported")
    return q


def _open_rgb(data: bytes):
    from PIL import Image as PImage
    return PImage.open(io.BytesIO(data)).convert("RGB")


def shrink(data: bytes, edge: int = EDGE) -> bytes:
    """jev_flags8.shrink on bytes: long edge to `edge`, short edge ≥ 280, never past 1568, no upscale
    once the short edge is ≥ 280."""
    from PIL import Image as PImage
    im = _open_rgb(data); w, h = im.size
    k = max(edge / max(w, h), 280 / min(w, h)); k = min(k, 1568 / max(w, h), 1.0 if min(w, h) >= 280 else 9)
    b = io.BytesIO(); im.resize((round(w * k), round(h * k)), PImage.LANCZOS).save(b, "JPEG", quality=JPEG_QUALITY); return b.getvalue()


def enc(im, edge: int = EDGE_L) -> bytes:
    """jev_crop8.enc (no UPSCALE): long edge to at most `edge`."""
    from PIL import Image as PImage
    w, h = im.size; k = min(edge / max(w, h), 1.0)
    b = io.BytesIO(); im.resize((max(1, round(w * k)), max(1, round(h * k))), PImage.LANCZOS).save(b, "JPEG", quality=JPEG_QUALITY); return b.getvalue()


def crops(data: bytes, mode: str = "lower"):
    """jev_crop8.crops, MODE "lower": portrait → full + bottom 60%; landscape → full + both 60% halves."""
    im = _open_rgb(data); w, h = im.size; port = h >= w; L = h if port else w
    def cut(a, b): return im.crop((0, round(a * L), w, round(b * L))) if port else im.crop((round(a * L), 0, round(b * L), h))
    if mode != "lower":
        raise ValueError("only pass L 'lower' is ported")
    parts = {"lower_part": cut(.4, 1.0)} if port else {"left_part": cut(0, .6), "right_part": cut(.4, 1.0)}
    return {"full_photo": im, **parts}


def spec() -> dict[str, Any]:
    """The exported question spec (golden-tested against the bench)."""
    def one(q):
        c = q.get("criteria")
        return {"type": q["type"], "instructions": q["instructions"],
                "criteria": None if c is None else [[k, v] for k, v in c.items()]}
    port = {"full_photo": 0, "lower_part": 0}
    land = {"full_photo": 0, "left_part": 0, "right_part": 0}
    return {"model": MODEL, "edge": EDGE, "edge2": EDGE2, "edge_l": EDGE_L, "quality": JPEG_QUALITY,
            "headers": HEADERS,
            "Q": [[k, one(v)] for k, v in Q.items()], "Q2": [[k, one(v)] for k, v in Q2.items()],
            "L_portrait": [[k, one(v)] for k, v in crop_questions(port).items()],
            "L_landscape": [[k, one(v)] for k, v in crop_questions(land).items()]}


# ── NudeNet (bench nn/nn_detect.py: 640m, full image, native res) ───

NUDENET_PATH_ENV = "NUDENET_640M_PATH"
NUDENET_MD5 = "d04bbbd55428dc307b379ae1dfa55314"   # 640m.onnx the bench measured (NudeNet 3.4.2)
NUDENET_RES = 640

_nn_load_lock = threading.Lock()   # the one-time load only; never taken once loaded (or failed)
# One inference at a time (CPU-bound, 1 thread). Waiters queue HERE, on the event loop, not inside
# `to_thread`: a sweep of 8 photos blocked on a thread lock would park 8 default-pool threads and
# starve every other `to_thread` user in the relay.
_nn_gate: "asyncio.Semaphore | None" = None
_nn_det: Any = None
_nn_err: str | None = None


class NudeNetUnavailable(Exception):
    """NudeNet cannot run here (package, weights or checksum). The Jev pass refuses."""


def _load_detector() -> Any:
    """The process's one NudeDetector (lazy, single onnxruntime session, 1 intra-op thread). A load
    failure is remembered: weights do not appear without a restart."""
    global _nn_det, _nn_err
    if _nn_det is not None:   # fast path, no lock: both are written once, under the load lock
        return _nn_det
    if _nn_err is not None:
        raise NudeNetUnavailable(_nn_err)
    with _nn_load_lock:
        if _nn_det is not None:
            return _nn_det
        if _nn_err is not None:
            raise NudeNetUnavailable(_nn_err)
        try:
            path = (os.environ.get(NUDENET_PATH_ENV) or "").strip()
            if not path:
                raise NudeNetUnavailable(f"{NUDENET_PATH_ENV} is not set")
            if not os.path.isfile(path):
                raise NudeNetUnavailable(f"NudeNet weights not found at {path}")
            md5 = hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    md5.update(chunk)
            if md5.hexdigest() != NUDENET_MD5:
                raise NudeNetUnavailable(f"NudeNet weights md5 {md5.hexdigest()} != {NUDENET_MD5}")
            import onnxruntime
            from nudenet import NudeDetector
            so = onnxruntime.SessionOptions()
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            det = NudeDetector.__new__(NudeDetector)   # its __init__ takes no session options
            det.onnx_session = onnxruntime.InferenceSession(path, sess_options=so,
                                                            providers=["CPUExecutionProvider"])
            det.input_width = det.input_height = NUDENET_RES
            det.input_name = det.onnx_session.get_inputs()[0].name
            _nn_det = det
            return det
        except NudeNetUnavailable as e:
            _nn_err = str(e)
        except Exception as e:  # noqa: BLE001 — ImportError, a bad onnx file
            _nn_err = f"NudeNet failed to load: {type(e).__name__}: {e}"[:300]
        log.warning("vault_jev: %s", _nn_err)
        raise NudeNetUnavailable(_nn_err)


def nudenet_status() -> tuple[bool, str]:
    """(ready, reason) — loads the detector if it is not loaded yet."""
    try:
        _load_detector()
        return True, ""
    except NudeNetUnavailable as e:
        return False, str(e)


async def nudenet_ready() -> tuple[bool, str]:
    """`nudenet_status` for the event loop: answers loaded / failed without a thread; only the
    first (loading) call goes to `to_thread`."""
    if _nn_det is not None:
        return True, ""
    if _nn_err is not None:
        return False, _nn_err
    return await asyncio.to_thread(nudenet_status)


def _detect_sync(data: bytes) -> dict[str, float]:
    import cv2
    import numpy as np
    det = _load_detector()
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)   # = cv2.imread (BGR, 3 channels)
    if im is None:
        raise ValueError("NudeNet could not decode the still")
    acc: dict[str, float] = {}
    for d in det.detect(im):   # serialized by `_nn_gate` (the only caller)
        acc[d["class"]] = max(acc.get(d["class"], 0), round(float(d["score"]), 3))
    return acc


async def nudenet_scores(data: bytes) -> dict[str, float]:
    """NudeNet {class: max score} for one still at native resolution (off the event loop, ≤1 core)."""
    global _nn_gate
    if _nn_gate is None:   # lazy: binds to the running loop; check→set has no await in between
        _nn_gate = asyncio.Semaphore(1)
    async with _nn_gate:
        return await asyncio.to_thread(_detect_sync, data)


# ── TypeSafe ────────────────────────────────────────────────────────

_clients: dict[tuple[int, str], Any] = {}


def _client(key: str) -> Any:
    """One async client per event loop and key (as `_fm_relevance._client`)."""
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
    loop = asyncio.get_running_loop()
    k = (id(loop), key)
    c = _clients.get(k)
    if c is None:
        if len(_clients) > 8:
            _clients.clear()
        c = _clients[k] = AsyncTypeSafeClient(
            api_key=key, model=MODEL, retry=RetryPolicy(max_retries=MAX_RETRIES, timeout=TIMEOUT_S))
    return c


def _sdk_questions(qs: dict[str, dict]) -> dict[str, Any]:
    from typesafe_sdk import Choice as SChoice, Noul
    out: dict[str, Any] = {}
    for k, q in qs.items():
        out[k] = (Noul(instructions=q["instructions"]) if q["type"] == "noul"
                  else SChoice(instructions=q["instructions"], criteria=q["criteria"]))
    return out


async def _ask(key: str, state: dict[str, bytes], qs: dict[str, dict]) -> dict[str, Any]:
    """One System One call; the response as the bench stored it (`model_dump(mode="json")`)."""
    from typesafe_sdk import Image
    r = await _client(key).system_one(state={k: Image(v) for k, v in state.items()},
                                      questions=_sdk_questions(qs), model=MODEL, extra_headers=HEADERS)
    out = r.model_dump(mode="json")
    missing = [q for q in qs if q not in (out.get("answers") or {})]
    if missing:
        raise ValueError(f"Jev answered without {missing[:3]}")
    return out


def _tokens(resp: dict[str, Any]) -> int:
    return int(((resp.get("usage") or {}).get("input_tokens")) or 0)


def cost_millicents(tokens_in: int) -> int:
    """Rounded UP: the rollup columns are whole millicents and one image is only ~2 mc."""
    return math.ceil(tokens_in * MILLICENTS_PER_INPUT_TOKEN - 1e-9) if tokens_in > 0 else 0


class JevResult(TypedDict, total=False):
    ok: bool
    status: str        # ok | no_nudenet | no_key | capped | error
    blob: dict[str, Any]
    detail: str
    cost_millicents: int
    tok: int


async def preflight() -> JevResult | None:
    """None when the pass can run here, else its refusal (`no_nudenet` / `no_key`). Cheap: no
    thread once NudeNet is loaded, no network — callers check it BEFORE fetching the still."""
    from llm_providers import typesafe_key

    ready, why = await nudenet_ready()
    if not ready:
        return JevResult(ok=False, status="no_nudenet", detail=why, cost_millicents=0, tok=0)
    if not typesafe_key():
        return JevResult(ok=False, status="no_key", detail="no TYPESAFE_API_KEY", cost_millicents=0, tok=0)
    return None


async def run(account_id: str, data: bytes) -> JevResult:
    """The whole pass over one still's bytes. Never raises for a model/NudeNet failure: the result's
    `status` says what happened (`ok` | `no_nudenet` | `no_key` | `capped` | `error`)."""
    import llm_client
    from llm_providers import typesafe_key
    from PIL import Image as PImage

    refusal = await preflight()
    if refusal is not None:
        return refusal
    key = typesafe_key()
    try:
        px = list(PImage.open(io.BytesIO(data)).size)   # header only: no decode on the event loop
    except Exception as e:  # noqa: BLE001
        return JevResult(ok=False, status="error", detail=f"unreadable still: {type(e).__name__}: {e}"[:300],
                         cost_millicents=0, tok=0)

    try:
        hold = await llm_client.reserve_external(
            account_id, PROVIDER, MODEL, cost_millicents(RESERVE_TOKENS), purpose=PURPOSE,
            request={"questions": len(Q), "edges": [EDGE, EDGE2, EDGE_L], "px": px})
    except llm_client.LLMCapExceeded as e:
        return JevResult(ok=False, status="capped", detail=str(e), cost_millicents=0, tok=0)

    rec: dict[str, Any] = {}
    passes: list[str] = []
    tok = 0
    t0 = time.monotonic()
    try:
        p1, scores = await asyncio.gather(
            _ask(key, {"photo": await asyncio.to_thread(shrink, data, EDGE)}, Q), nudenet_scores(data))
        rec["resp"] = p1; passes.append("1"); tok += _tokens(p1)
        d = rules.derive8(rec)
        if d["need2"]:
            p2 = await _ask(key, {"photo": await asyncio.to_thread(shrink, data, EDGE2)}, Q2)
            rec["resp2"] = p2; passes.append("2"); tok += _tokens(p2)
            d = rules.derive8(rec)
        if d["needL"]:
            def _crop_state() -> dict[str, bytes]:
                return {k: enc(v, EDGE_L) for k, v in crops(data, "lower").items()}
            st = await asyncio.to_thread(_crop_state)
            pl = await _ask(key, st, crop_questions(st, "lower"))
            rec["respL"] = pl; passes.append("L"); tok += _tokens(pl)
        d = rules.final(rec, scores)
    except Exception as e:  # noqa: BLE001 — SDK, HTTP, timeout, NudeNet decode, a missing answer
        actual = cost_millicents(tok)
        await hold.done(actual, tokens_in=tok, ok=False, error=f"{type(e).__name__}: {e}"[:300],
                        latency_ms=int((time.monotonic() - t0) * 1000))
        log.warning("vault_jev failed account=%s passes=%s: %s", account_id, passes, type(e).__name__)
        return JevResult(ok=False, status="error", detail=f"{type(e).__name__}: {e}"[:300],
                         cost_millicents=actual, tok=tok)
    actual = cost_millicents(tok)
    await hold.done(actual, tokens_in=tok, ok=True, latency_ms=int((time.monotonic() - t0) * 1000),
                    response=f"lane5={d['lane5']} passes={','.join(passes)}")
    b = rules.blob(d, scores, passes=passes, tok=tok, px=px, at=datetime.utcnow().isoformat(),
                   answers=rules.overlay(rec, d))
    return JevResult(ok=True, status="ok", blob=b, cost_millicents=actual, tok=tok)


def merge(prev: dict[str, Any], res: JevResult, now: datetime) -> dict[str, Any]:
    """`prev`'s `ai_fields_json` with `res` written as `_jev`. A failure keeps the last answer's
    fields and stamps `status`/`error`/`failed_at` on them; `capped` writes nothing (retry later)."""
    out = dict(prev)
    if res.get("ok"):
        out["_jev"] = res["blob"]
    elif res.get("status") != "capped":
        old = prev.get("_jev") if isinstance(prev.get("_jev"), dict) else {}
        out["_jev"] = {**old, "v": old.get("v", rules.VERSION), "status": res.get("status"),
                       "error": str(res.get("detail") or "")[:200], "failed_at": now.isoformat()}
    return out
