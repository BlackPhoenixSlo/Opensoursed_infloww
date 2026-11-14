"""automations/full_ai_photo.py — Full AI Chat reads the photo he sends (side key `describe_fan_photos`).

Off by default: with the key off nothing here runs and every line reads as before.

  describe_turn(account_id, turn, client) -> record | None
      The real-messages step (Auto-reply's lazy rule): the newest inbound media row of his Turn with
      no `image_desc` is described once (`inbound_describe.describe_message`, cached on
      `messages.image_desc`, so never twice) and the row object gets the description. The record
      lands on the Decision row as `photo`: `{outcome, model, ms}`, outcome
      described | cached | none | no_key | cap | failed | no_client; None when the Turn has no photo.
      Every failure leaves the line `MEDIA_ONLY` and the Turn still answers (a cap is an attempt
      outcome, as the Writers record it). `client` is the OF client the CDN download needs; Shadow
      has none by construction (ADR-0033: no OF client), so it reads only descriptions already
      cached and records `no_client` for a photo nobody described.
  upload_still(data_url) -> (still, thumb)
      The Test chat's upload: one JPG / PNG / GIF / WebP image (bio pages' limits and wording), its
      first frame as the still the vision call gets and a small JPEG thumbnail stored on the session.

Which text a row reads as (`[he sent: <desc>]`) is `_router_jev.line_text` alone, switched per
Turn by `_router_jev.read_photos`.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import re
import time
from typing import Any

import inbound_describe
from automations import _jev
from bio_pages.images import MAX_PIXELS, REFUSED, Refused  # noqa: F401 — Refused re-exported
from llm_client import LLMCapExceeded, LLMConfigError

log = logging.getLogger(__name__)

KEY = "describe_fan_photos"
MAX_UPLOAD = 20 * 1024 * 1024       # bio pages' upload cap
THUMB_EDGE = 320
_DATA_URL = re.compile(r"data:image/(?:jpeg|jpg|png|gif|webp);base64,(.+)", re.S | re.I)


def _todo(turn: list) -> Any:
    """The newest inbound media row of the Turn with no description yet, else None."""
    return next((m for m in reversed(turn) if m.direction == "in" and m.media_count
                 and not getattr(m, "image_desc", None)), None)


async def describe_turn(account_id: str, turn: list, client: Any) -> dict | None:
    """Describe the Turn's newest undescribed photo once; the record (module doc). Run it with no DB
    session open: it calls the vision model."""
    todo = _todo(turn)
    if todo is None:
        seen = any(m.direction == "in" and m.media_count and getattr(m, "image_desc", None) for m in turn)
        return {"outcome": "cached", "model": None, "ms": None} if seen else None
    if client is None:
        return {"outcome": "no_client", "model": None, "ms": None}
    his_words = " ".join(t for t in (_jev.text(m.body) for m in turn if m.direction == "in") if t)
    t0 = time.perf_counter()
    model = None
    try:
        desc, model = await inbound_describe.describe_message(account_id, todo.message_id, client,
                                                              his_words=his_words)
        outcome = "described" if desc else "none"
    except LLMCapExceeded:
        desc, outcome = None, "cap"
    except LLMConfigError:
        desc, outcome = None, "no_key"
    except Exception:  # noqa: BLE001 — the Turn answers without the photo
        log.warning("full_ai photo describe failed account=%s msg=%s", account_id,
                    todo.message_id, exc_info=True)
        desc, outcome = None, "failed"
    if desc:
        # The value describe_message just stored: the row object reads as the DB now does.
        todo.image_desc = desc
    return {"outcome": outcome, "model": model, "ms": int((time.perf_counter() - t0) * 1000)}


def upload_still(data_url: str) -> tuple[str, str]:
    """(still, thumb) data-URLs of one uploaded image. Raises `Refused` (415 not a JPG / PNG /
    GIF / WebP image or over `MAX_PIXELS`, 413 over `MAX_UPLOAD`)."""
    from PIL import Image, ImageOps

    m = _DATA_URL.fullmatch(data_url.strip())
    if m is None:
        raise Refused(415)
    if len(m.group(1)) > MAX_UPLOAD * 4 // 3 + 4:
        raise Refused(413, "The image is larger than 20 MB.")
    try:
        raw = base64.b64decode(m.group(1), validate=True)
    except (binascii.Error, ValueError):
        raise Refused(415) from None
    if len(raw) > MAX_UPLOAD:
        raise Refused(413, "The image is larger than 20 MB.")
    try:
        with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG", "GIF", "WEBP")) as im:
            if im.width * im.height > MAX_PIXELS:
                raise Refused(415)
            im.seek(0)
            frame = ImageOps.exif_transpose(im).convert("RGB")
    except Refused:
        raise
    except Exception:  # noqa: BLE001 — anything Pillow refuses is the owner's file
        raise Refused(415, REFUSED) from None

    def jpeg(edge: int, quality: int) -> str:
        im = frame.copy()
        im.thumbnail((edge, edge), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    # The still is shrunk again by `inbound_describe.describe_upload`, as a downloaded frame is.
    return jpeg(inbound_describe._IMG_MAX_EDGE, 90), jpeg(THUMB_EDGE, 75)
