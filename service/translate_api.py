from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import Counter
from typing import TypedDict

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import TranslationCache
from employees import agency_contexts
from english_text import is_english, words
from permissions import agency_chatter
from settings_api import translation_allowed

log = logging.getLogger("uvicorn.error")

router = APIRouter()


class Translation(TypedDict):
    """One answer, in the ONE shape all three tiers speak.

    Every tier used to hand around a bare `dict` with these two keys — gtx's
    parser, the memory cache, the table reader and the HTTP response — so a typo
    in any of them would have surfaced as a silently missing translation rather
    than as an error. Naming the shape once costs four lines and makes every
    signature below say what it means."""
    text: str
    lang: str

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MAX_TEXTS = 100
MAX_CHARS = 3000
_CONCURRENCY = 8
_google_permits = asyncio.Semaphore(_CONCURRENCY)
_CACHE_CAP = 8000
_COOLDOWN_S = 600.0
_cooldown_until = 0.0

_DB_CAP = 50_000
_DB_PRUNE_TO = 40_000
_PRUNE_EVERY = 500
_rows_since_prune = 0

# Successes only: a transient failure must not pin "untranslatable" until restart.
_cache: dict[str, Translation] = {}

# Serializes the cap sweep: concurrent batches would each delete a slice and over-prune.
_prune_lock = asyncio.Lock()


def _cache_key(text: str, target: str, source: str = "auto") -> str:
    raw = f"{target}\x00{text}" if source == "auto" else f"{target}\x00{source}\x00{text}"
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()


_SHORT_WORDS = 2
_LANG = re.compile(r"^[a-z]{2,3}$")


def _is_short(text: str) -> bool:
    return 0 < len(words(text)) <= _SHORT_WORDS


def _mem_put(key: str, value: Translation) -> None:
    if len(_cache) >= _CACHE_CAP:
        for k in list(_cache)[: _CACHE_CAP // 4]:
            _cache.pop(k, None)
    _cache[key] = value


def _parse_gtx(data) -> Translation | None:
    try:
        segments = data[0] or []
        translated = "".join(seg[0] for seg in segments if seg and seg[0])
        lang = (data[2] or "").lower().split("-")[0]
        if not translated:
            return None
        return Translation(text=translated, lang=lang or "und")
    except (IndexError, TypeError):
        return None


def _cooling_down() -> bool:
    return time.monotonic() < _cooldown_until


async def _fetch_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, text: str, target: str,
    source: str = "auto",
) -> Translation | None:
    global _cooldown_until
    async with sem:
        if _cooling_down():
            return None
        try:
            r = await client.get(GOOGLE_URL, params={
                "client": "gtx", "sl": source, "tl": target, "dt": "t",
                "ie": "UTF-8", "oe": "UTF-8", "q": text,
            })
            if r.status_code == 429:
                if not _cooling_down():
                    log.warning("translate: google gtx 429, pausing translations %ds", _COOLDOWN_S)
                _cooldown_until = time.monotonic() + _COOLDOWN_S
                return None
            r.raise_for_status()
            return _parse_gtx(r.json())
        except (httpx.HTTPError, ValueError):
            return None



async def _db_get(hashes: list[str]) -> dict[str, Translation]:
    if not hashes:
        return {}
    try:
        async with get_session() as s:
            rows = (await s.execute(
                select(TranslationCache.text_hash,
                       TranslationCache.translated,
                       TranslationCache.src_lang)
                .where(TranslationCache.text_hash.in_(hashes))
            )).all()
        return {r.text_hash: Translation(text=r.translated, lang=r.src_lang)
                for r in rows}
    except Exception:  # noqa: BLE001 — see module note: degrade, never fail
        log.warning("translate: durable cache read failed", exc_info=True)
        return {}


async def _db_put(
    target: str, fresh: dict[str, tuple[str, Translation]], *, stale: dict[str, Translation] | None = None,
) -> None:
    # ON CONFLICT DO NOTHING: two chatters opening one thread race here with identical answers, and the first write keeps created_at honest.
    if not fresh:
        return
    try:
        async with get_session() as s:
            replaced = [(key, value["text"], value["lang"])
                        for key, value in (stale or {}).items() if key in fresh]
            if replaced:
                await s.execute(delete(TranslationCache).where(tuple_(
                    TranslationCache.text_hash, TranslationCache.translated, TranslationCache.src_lang,
                ).in_(replaced)))
            await s.execute(
                sqlite_insert(TranslationCache).values([
                    {"text_hash": h, "target": target, "src_lang": v["lang"] or "und",
                     "source_text": src, "translated": v["text"]}
                    for h, (src, v) in fresh.items()
                ]).on_conflict_do_nothing(index_elements=["text_hash"]),
            )
            await s.commit()
    except Exception:  # noqa: BLE001
        log.warning("translate: durable cache write failed", exc_info=True)
        return

    global _rows_since_prune
    _rows_since_prune += len(fresh)
    if _rows_since_prune >= _PRUNE_EVERY:
        _rows_since_prune = 0
        await _prune()


async def _prune() -> None:
    async with _prune_lock:
        try:
            async with get_session() as s:
                total = (await s.execute(
                    select(func.count()).select_from(TranslationCache)
                )).scalar_one()
                if total <= _DB_CAP:
                    return
                doomed = (await s.execute(
                    select(TranslationCache.text_hash)
                    .order_by(TranslationCache.created_at.asc())
                    .limit(total - _DB_PRUNE_TO)
                )).scalars().all()
                await s.execute(
                    delete(TranslationCache)
                    .where(TranslationCache.text_hash.in_(doomed)))
                await s.commit()
            log.info("translate: pruned %d cached translations", len(doomed))
        except Exception:  # noqa: BLE001
            log.warning("translate: cache prune failed", exc_info=True)


class TranslateBody(BaseModel):
    texts: list[str] = Field(..., max_length=MAX_TEXTS)
    target: str = "en"
    hint: str | None = None


TURNED_OFF = "Turned off by your organization"


async def require_translation_allowed(request: Request) -> None:
    if agency_chatter() is None:
        return
    contexts = await agency_contexts(account_id=request.headers.get("x-account-id") or None)
    async with get_session() as s:
        allowed = await translation_allowed(s, contexts)
    if not allowed:
        raise HTTPException(status_code=403, detail=TURNED_OFF)


def _echo(text: str, value: Translation) -> bool:
    return " ".join(text.casefold().split()) == " ".join(value["text"].casefold().split())


def _usable(text: str, value: Translation, forced: bool) -> bool:
    return not forced or not _echo(text, value)


async def _fetch_translation(
    client: httpx.AsyncClient, text: str, target: str, source: str,
) -> Translation | None:
    value = await _fetch_one(client, _google_permits, text, target, source)
    if value is not None and not _usable(text, value, source != "auto"):
        return await _fetch_one(client, _google_permits, text, target)
    return value

async def _resolve(
    need: dict[str, str], target: str, source: str, *, english_shortcut: bool = False,
) -> dict[str, Translation]:
    resolved: dict[str, Translation] = {}
    need = dict(need)

    for key in list(need):
        hit = _cache.get(key)
        if hit is not None:
            resolved[key] = hit
            del need[key]

    forced = source != "auto"
    echo_keys = {key: _cache_key(text, target, f"auto-after:{source}")
                 for key, text in need.items()} if forced else {}
    stale: dict[str, Translation] = {}
    if need:
        cached = await _db_get([*need, *echo_keys.values()])
        for key, text in list(need.items()):
            value = cached.get(key)
            if value is not None and not _usable(text, value, forced):
                stale[key] = value
                value = cached.get(echo_keys[key])
            elif value is None and forced:
                value = cached.get(echo_keys[key])
            if value is not None:
                _mem_put(key, value)
                resolved[key] = value
                del need[key]

    if english_shortcut:
        for key, text in list(need.items()):
            if is_english(text):
                resolved[key] = Translation(text=text, lang="en")
                del need[key]

    if need and not _cooling_down():
        pending = list(need.items())
        async with httpx.AsyncClient(timeout=8.0) as client:
            fetched = await asyncio.gather(
                *(_fetch_translation(client, text, target, source) for _, text in pending),
            )
        fresh: dict[str, tuple[str, Translation]] = {}
        for (key, text), value in zip(pending, fetched):
            if value is None:
                continue
            _mem_put(key, value)
            resolved[key] = value
            storage_key = key if _usable(text, value, forced) else echo_keys[key]
            fresh[storage_key] = (text, value)
        await _db_put(target, fresh, stale=stale)
    return resolved


def _thread_language(results: list[Translation], target: str) -> str | None:
    langs = Counter(r["lang"] for r in results if r["lang"] not in (target, "und"))
    return langs.most_common(1)[0][0] if langs else None


@router.post("/admin/translate", dependencies=[Depends(require_translation_allowed)])
async def translate_batch(body: TranslateBody = Body(...)):
    target = (body.target or "en").lower().split("-")[0]
    texts = [(t or "").strip()[:MAX_CHARS] for t in body.texts]
    hint = (body.hint or "").lower().split("-")[0]
    hint = hint if _LANG.match(hint) and hint != target else None

    # Per-request map, deliberately not the module cache: that one evicts, so reading results back from it would depend on an unwritten invariant.
    resolved: dict[str, Translation] = {}
    keys: list[str] = [""] * len(texts)
    need: dict[str, str] = {}
    short: list[int] = []

    for i, text in enumerate(texts):
        if not text:
            continue
        if _is_short(text):
            short.append(i)
        else:
            keys[i] = _cache_key(text, target)
            need[keys[i]] = text

    english_shortcut = target == "en" and hint is None
    resolved.update(await _resolve(need, target, "auto", english_shortcut=english_shortcut))

    source = hint or _thread_language([resolved[k] for k in need if k in resolved], target)
    need = {}
    for i in short:
        keys[i] = _cache_key(texts[i], target, source or "auto")
        need[keys[i]] = texts[i]
    resolved.update(await _resolve(need, target, source or "auto", english_shortcut=english_shortcut))

    results = [resolved.get(key) if text else None for text, key in zip(texts, keys)]
    failed = sum(1 for t, r in zip(texts, results) if t and r is None)
    if failed:
        log.warning("translate: %d/%d texts failed (google gtx)", failed, len(texts))
    return {"results": results}
