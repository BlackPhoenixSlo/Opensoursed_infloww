from __future__ import annotations

import asyncio
import base64
import io
import logging
from typing import Any

log = logging.getLogger("of-relay.vision")

# Longest edge in px for vault flag/describe runs; the inbound-chat path overrides it upward (a fan's photo is read once and detail matters).
MAX_EDGE_DEFAULT = 448


def shrink_data_url(data_url: str, max_edge: int = MAX_EDGE_DEFAULT) -> str:
    # Returns the input unchanged if Pillow can't read it: a cheap pass must never take down the caller.
    try:
        from PIL import Image

        _, _, b64 = data_url.partition(",")
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        log.warning("vision shrink failed; sending full-size", exc_info=True)
        return data_url


# A declining vision model shapes its refusal like prose, so length is half the test: a real description of an explicit picture is long, a refusal a short apology ("i'm sorry" appears inside real descriptions).
_REFUSAL_MARKERS = ("i can't", "i cannot", "i'm unable", "cannot assist", "content policy",
                    "i'm sorry", "not able to", "against my")


def is_refusal(text: str) -> bool:
    low = (text or "").strip().lower()
    return not low or (len(low) < 40 and any(m in low for m in _REFUSAL_MARKERS))


def img_data_url(b: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(b).decode()


async def download_frames(client: Any, urls: list[str]) -> list[str]:
    out: list[str] = []
    for u in urls:
        try:
            resp = await asyncio.to_thread(lambda u=u: client.http.get(u, timeout=client.timeout_s))
            if resp.status_code == 200 and resp.content:
                out.append(img_data_url(resp.content))
        except Exception:  # noqa: BLE001
            log.warning("poster frame fetch failed", exc_info=True)
    return out

