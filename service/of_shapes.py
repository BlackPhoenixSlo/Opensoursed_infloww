from __future__ import annotations

# thumb is excluded from DIM_KEYS: OF thumbs are 300x300 squares, not real dims.
DIM_KEYS = ("full", "source", "preview")

# Audio belongs here: voice notes arrive as files.full .mp3 with no poster and would reach a vision model as a picture.
NON_IMAGE_EXTS = (".mp4", ".m3u8", ".mov", ".webm", ".m4v",
                  ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus")


def media_urls(media: dict) -> tuple[str | None, str | None]:
    thumb_url = source_url = None
    files = media.get("files") if isinstance(media, dict) else None
    if isinstance(files, dict):
        thumb = files.get("thumb")
        if isinstance(thumb, dict):
            thumb_url = thumb.get("url")
        for k in DIM_KEYS:
            sub = files.get(k)
            if isinstance(sub, dict) and sub.get("url"):
                source_url = sub.get("url")
                break
    if not source_url and isinstance(media, dict):
        source_url = media.get("url")
    return (thumb_url, source_url)


# thumb is a 300x300 centre-crop of 3:4 stills (top and bottom gone): last resort only.
_VISION_VARIANTS = ("preview", "full", "source", "squarePreview", "thumb")


def _is_non_image_url(url: str | None) -> bool:
    return bool(url) and url.split("?", 1)[0].lower().endswith(NON_IMAGE_EXTS)


def still_url(media: dict) -> str | None:
    # OF stores a gif as .mp4 (an image decoder rejects it); a video resolves to OF's poster frame when it ships one.
    files = media.get("files") if isinstance(media, dict) else None
    if isinstance(files, dict):
        for key in _VISION_VARIANTS:
            f = files.get(key)
            url = f.get("url") if isinstance(f, dict) else None
            if url and not _is_non_image_url(url):
                return url
    loose = media.get("url") if isinstance(media, dict) else None
    return loose if loose and not _is_non_image_url(loose) else None


def has_video(media: list | None) -> bool:
    # Read the parsed `type`, never a substring of the stored frame: a quoted reply embeds the original clip.
    return isinstance(media, list) and any(
        isinstance(m, dict) and m.get("type") == "video" for m in media)


def giphy_dm_id(frame: dict) -> str | None:
    if not isinstance(frame, dict):
        return None
    media = frame.get("media")
    if isinstance(media, list) and media:
        return None
    gid = str(frame.get("giphyId") or "").strip()
    return gid or None


def _as_id(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def queue_id(frame: dict) -> int | None:
    qid = frame.get("queueId") if isinstance(frame, dict) else None
    if isinstance(qid, bool) or qid is None:
        return None
    try:
        return int(qid)
    except (TypeError, ValueError):
        return None


def reply_to_id(frame: dict) -> int | None:
    if not isinstance(frame, dict):
        return None
    quoted = frame.get("replyToMessage")
    got = _as_id(quoted.get("id")) if isinstance(quoted, dict) else None
    return got if got is not None else _as_id(frame.get("replyToMessageId"))


