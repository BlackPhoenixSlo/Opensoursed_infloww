"""Owner uploads → WebP: pure bytes in, bytes out (Pillow; run it off the event loop).

v2 parity ($V2/app/src/image.js TARGETS): avatar 512, background 1080 max side, never enlarged; frame 0; EXIF
orientation applied, then no EXIF/ICC kept; alpha kept only when the image has some.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageMath, ImageOps

MAX_PIXELS = 50_000_000
MAX_OUT = 5 * 1024 * 1024
AVATAR_SIDE, BACKGROUND_SIDE = 512, 1080
REFUSED = "Pick a JPG, PNG, GIF or WebP image."


class Refused(Exception):
    """Not an image we take: `status` 415 (format/size) or 413 (output too big)."""

    def __init__(self, status: int, msg: str = REFUSED):
        super().__init__(msg)
        self.status = status
        self.msg = msg


def encode(data: bytes, side: int) -> bytes:
    try:
        im = Image.open(BytesIO(data), formats=("JPEG", "PNG", "GIF", "WEBP"))
        if im.width * im.height > MAX_PIXELS:
            raise Refused(415)
        im.seek(0)
        im.load()
        im = ImageOps.exif_transpose(im)
        alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        mask = None
        if im.mode == "RGB" and isinstance(im.info.get("transparency"), tuple):
            key = im.info["transparency"]
            if any(v > 255 for v in key):
                im.info["transparency"] = tuple(v >> 8 for v in key)
        if im.mode == "I;16":
            if "transparency" in im.info:
                key = im.info["transparency"]
                mask = ImageMath.lambda_eval(lambda a: (a["x"] != key) * 255, x=im.convert("I")).convert("L")
            im = im.convert("I").point(lambda value: value / 257).convert("L")
        im = im.convert("RGBA" if alpha else "RGB")
        if mask is not None:
            im.putalpha(mask)
        im.thumbnail((side, side), Image.Resampling.LANCZOS)
        out = BytesIO()
        im.save(out, "WEBP", quality=80, method=4)
    except Refused:
        raise
    except Exception:  # noqa: BLE001 — anything Pillow refuses (HEIC, truncated, bombs) is the user's file
        raise Refused(415) from None
    if out.tell() > MAX_OUT:
        raise Refused(413, "The image is too large after conversion.")
    return out.getvalue()
