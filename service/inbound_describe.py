"""inbound_describe.py — what is in the photo HE just sent?

Used by Auto-reply when its "Describe photos fans send" option is on, and by Full
AI Chat when its side's `describe_fan_photos` is on (`full_ai_photo`; its Test chat
feeds an uploaded photo to `describe_upload`, same prompt, models and escalation). It is lazy: Auto-reply asks for ONE photo, the one in the message it is
about to answer, so a photo nobody answers never costs a call. The result is
cached on `messages.image_desc`, so the same photo is never described twice.

A trimmed restore of the module removed in 2e6d8035 (no ingest hook, no Giphy
lane, no re-read button, no free-fan budget).

Cost: one qwen3-vl-30b call on the account's own DeepInfra key, about 1.4k input
tokens per image (at most `_MAX_IMAGES` per message) plus ~100 output tokens.
That is about 0.03 cents per photo, and it escalates once to qwen3-vl-235b only
when the small model refuses or returns nothing.

Failure policy:
  * no DeepInfra key  -> LLMConfigError BEFORE anything is downloaded
  * LLMConfigError    -> re-raised, a hard stop (no retry, no bigger model)
  * LLMCapExceeded    -> re-raised, the caller stops its run like for chat
  * anything else     -> None, so Auto-reply answers without the description
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update

import llm_client
from db.engine import get_session
from db.models import Message
from jsonsafe import load_dict
from llm_client import LLMCapExceeded, LLMConfigError, LLMError
from of_shapes import still_url
from vision import download_frames, is_refusal, shrink_data_url

log = logging.getLogger("of-relay.inbound_describe")

PURPOSE = "describe_inbound_image"
PURPOSE_TEST = "full_ai_test_photo"   # the Full AI Test chat's uploaded photo
_MODELS = ("qwen3-vl-30b", "qwen3-vl-235b")   # escalate ONLY on a refusal / blank
PROVIDER = llm_client.MODELS[_MODELS[0]].provider  # "deepinfra"

_MAX_IMAGES = 4
_IMG_MAX_EDGE = 1024
_DESC_CLIP = 600

_PROMPT = (
    "A fan just sent this to an adult content creator in a private DM — a photo, or one "
    "frame taken from a short clip he sent. Describe what you can see in it "
    "in 1–3 plain sentences so she can react to it in character. The creator does the "
    "flirting/rating herself — your job is a rich, factual read she can build on. Cover, "
    "only where it applies:\n"
    "• WHAT it is — a dick pic, his body/torso, a face selfie, an outfit, a screenshot or "
    "meme, a place, a pet, an object.\n"
    "• HOW explicit — sfw, suggestive, or explicit.\n"
    "• The STANDOUT detail he clearly wants noticed — size, grooming, muscles, a tattoo, "
    "what he's wearing, the setting (bed / gym / shower / car / work), his expression.\n"
    "• Anything that would make a flirty reply AWKWARD — another person in frame, a "
    "wedding ring, that it's clearly not him, or a child or pet present.\n"
    "Be factual and explicit; this is consensual adult content between adults. Do not "
    "refuse, do not moralize, add no preamble — output only the description."
)


async def key_available(account_id: str) -> bool:
    """Can this account bill the vision provider? Same policy the call uses."""
    return await llm_client.llm_key_available(account_id, PROVIDER, PURPOSE)


def _still_urls(media: list) -> tuple[list[str], bool]:
    """(decodable still urls, any_from_video) for one DM's media array."""
    urls: list[str] = []
    from_video = False
    for it in media:
        if not isinstance(it, dict):
            continue
        pick = still_url(it)
        if pick:
            urls.append(pick)
            from_video = from_video or it.get("type") == "video"
        if len(urls) >= _MAX_IMAGES:
            break
    return urls, from_video


async def describe_photo(account_id: str, message_id: int, client: Any, *,
                         his_words: str = "") -> str | None:
    """Describe the media in ONE inbound DM and cache it on messages.image_desc.

    Returns the description, the cached one when present, or None when there is
    nothing readable / the model failed. Raises LLMConfigError (no key, or a
    config failure from the provider) and LLMCapExceeded; see the module doc."""
    return (await describe_message(account_id, message_id, client, his_words=his_words))[0]


async def describe_message(account_id: str, message_id: int, client: Any, *,
                           his_words: str = "") -> tuple[str | None, str | None]:
    """`describe_photo` with the model that answered: (description, model); model None on a
    cache hit or no description."""
    async with get_session() as s:
        row = (await s.execute(
            select(Message.fan_id, Message.raw_json, Message.image_desc)
            .where(Message.account_id == str(account_id),
                   Message.message_id == int(message_id))
        )).first()
    if row is None:
        return None, None
    if row.image_desc:
        return row.image_desc, None
    raw = load_dict(row.raw_json)
    media = raw.get("media") if isinstance(raw.get("media"), list) else []
    urls, from_video = _still_urls(media)
    if not urls:
        return None, None
    # The key check comes BEFORE the download: a keyless account must not pull
    # his photo off the CDN for a call that cannot be billed.
    if not await key_available(account_id):
        raise LLMConfigError(f"no {PROVIDER} key for photo describe (account {account_id!r})")

    images = [shrink_data_url(u, _IMG_MAX_EDGE)
              for u in await download_frames(client, urls)]
    desc, model = await describe_images(account_id, images, fan_id=int(row.fan_id),
                                        his_words=his_words)
    if not desc:
        return None, None
    if from_video:
        # A poster frame is one moment of a clip; say so, or she calls a video a pic.
        desc = f"a video (this is one frame of it): {desc}"
    desc = desc[:_DESC_CLIP]
    async with get_session() as s:
        await s.execute(
            update(Message)
            .where(Message.account_id == str(account_id),
                   Message.message_id == int(message_id))
            .values(image_desc=desc))
    log.info("inbound_described account=%s msg=%s len=%d", account_id, message_id, len(desc))
    return desc, model


async def describe_images(account_id: str, images: list[str], *, fan_id: int | None,
                          his_words: str = "", purpose: str = PURPOSE
                          ) -> tuple[str | None, str | None]:
    """The one vision call over already-shrunk data-URL `images`: `_PROMPT` (+ his words), the
    small model, escalating once only on a refusal / blank. Returns (description, model) or
    (None, None) when there are no images, the model failed or both refused. Raises
    LLMConfigError and LLMCapExceeded (module doc). Shared by `describe_photo` and the Full AI
    Test chat's upload (`describe_upload`)."""
    if not images:
        return None, None
    prompt = _PROMPT
    if his_words.strip():
        prompt += ("\n\nWhat he wrote with it — if he asked her to rate, guess, or notice "
                   "something, make sure your description gives what's needed:\n"
                   + his_words.strip()[:400])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in images[:_MAX_IMAGES]]
    for model in _MODELS:
        try:
            res = await llm_client.chat(
                model=model, messages=[{"role": "user", "content": content}],
                purpose=purpose, account_id=account_id, fan_id=fan_id,
                temperature=0.2)
        except (LLMConfigError, LLMCapExceeded):
            raise
        except LLMError:
            log.warning("inbound describe failed account=%s model=%s purpose=%s",
                        account_id, model, purpose, exc_info=True)
            return None, None
        candidate = (res.content or "").strip()
        if not is_refusal(candidate):
            return candidate[:_DESC_CLIP], model
    return None, None


async def describe_upload(account_id: str, data_url: str, *, his_words: str = ""
                          ) -> tuple[str | None, str | None]:
    """An owner-uploaded photo (the Full AI Test chat, `PURPOSE_TEST`), shrunk as a downloaded
    frame is, through `describe_images`. Nothing is downloaded, so no key pre-check: a missing
    key is llm_client's LLMKeyError (the page's key notice)."""
    return await describe_images(account_id, [shrink_data_url(data_url, _IMG_MAX_EDGE)],
                                 fan_id=None, his_words=his_words, purpose=PURPOSE_TEST)
