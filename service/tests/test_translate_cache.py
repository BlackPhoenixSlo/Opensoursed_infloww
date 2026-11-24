#!/usr/bin/env python3
"""
POST /admin/translate — the three cache tiers behind the 🌐 chat-translate
toggle. Durable regression suite (plain-assert, no pytest — repo convention).

Google's gtx endpoint is faked.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_translate_cache.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

import time  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import translate_api  # noqa: E402 — module under test

_real_fetch = translate_api._fetch_one
_RealClient = httpx.AsyncClient
from db.engine import get_session  # noqa: E402
from db.models import TranslationCache  # noqa: E402


# ── Fake gtx ─────────────────────────────────────────────────────────

_calls: list[str] = []
_fail_for: set[str] = set()


class _FakeClient:
    """Stands in for httpx.AsyncClient as an async context manager."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


_sources: list[str] = []


async def _fake_fetch(client, sem, text: str, target: str, source: str = "auto"):
    _calls.append(text)
    _sources.append(source)
    if text in _fail_for:
        return None                       # what a 429 / timeout looks like here
    if source != "auto":
        return {"text": f"{source.upper()}:{text}", "lang": source}
    return {"text": f"EN:{text}", "lang": "es"}


def _install_fakes() -> None:
    translate_api.httpx.AsyncClient = lambda *a, **k: _FakeClient()  # type: ignore[assignment]
    translate_api._fetch_one = _fake_fetch                            # type: ignore[assignment]


async def _reset() -> None:
    """Fresh process memory, call log AND durable tier — each case starts cold."""
    _calls.clear()
    _sources.clear()
    _fail_for.clear()
    translate_api._cache.clear()
    translate_api._rows_since_prune = 0
    translate_api._cooldown_until = 0.0
    async with get_session() as s:
        await s.execute(TranslationCache.__table__.delete())
        await s.commit()


async def _post(texts: list[str], target: str = "en", hint: str | None = None) -> list[dict | None]:
    body = translate_api.TranslateBody(texts=texts, target=target, hint=hint)
    return (await translate_api.translate_batch(body))["results"]


# ── Cases ────────────────────────────────────────────────────────────

async def case_first_batch_calls_google_once_per_distinct_text():
    _install_fakes()
    await _reset()

    out = await _post(["hola", "hallo", "hallo", "hallo", "adios"])

    # 5 bubbles, 3 distinct — and first-seen order, so the batch is stable.
    assert _calls == ["hola", "hallo", "adios"], f"not deduped: {_calls}"
    assert [r["text"] for r in out] == [
        "EN:hola", "EN:hallo", "EN:hallo", "EN:hallo", "EN:adios"
    ], f"wrong order/content: {out}"
    assert out[0]["lang"] == "es", f"detected language dropped: {out[0]}"

    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(TranslationCache))).scalar_one()
    assert n == 3, f"durable tier should hold 3 distinct rows, holds {n}"


async def case_second_batch_is_free():
    _install_fakes()
    await _reset()
    await _post(["hola", "adios"])
    _calls.clear()

    out = await _post(["hola", "adios", "hola"])

    assert _calls == [], f"warm batch still called google: {_calls}"
    assert [r["text"] for r in out] == ["EN:hola", "EN:adios", "EN:hola"], out


async def case_survives_a_relay_restart():
    _install_fakes()
    await _reset()
    await _post(["hola", "adios"])

    # A deploy restarts the relay: process memory is gone, the table is not.
    translate_api._cache.clear()
    _calls.clear()

    out = await _post(["hola", "adios"])

    assert _calls == [], f"a restart re-bought cached translations: {_calls}"
    assert [r["text"] for r in out] == ["EN:hola", "EN:adios"], out
    assert [r["lang"] for r in out] == ["es", "es"], f"lang lost across the DB: {out}"
    # …and the round trip warmed process memory again, so the NEXT batch is free
    # without touching SQLite either.
    assert len(translate_api._cache) == 2, translate_api._cache


async def case_failure_is_not_cached():
    _install_fakes()
    await _reset()
    _fail_for.add("hola")

    out = await _post(["hola", "adios"])
    assert out[0] is None, f"a failed translation must be null, got {out[0]}"
    assert out[1]["text"] == "EN:adios", out[1]

    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(TranslationCache))).scalar_one()
    assert n == 1, f"only the SUCCESS may persist, table holds {n}"

    # Google recovers → the retry must actually go out.
    _fail_for.clear()
    _calls.clear()
    out2 = await _post(["hola", "adios"])
    assert _calls == ["hola"], f"retried the wrong set: {_calls}"
    assert out2[0]["text"] == "EN:hola", out2[0]


async def case_blank_texts_never_call_out():
    _install_fakes()
    await _reset()

    out = await _post(["", "   ", "hola"])

    assert _calls == ["hola"], f"blank bubbles hit the network: {_calls}"
    assert out[0] is None and out[1] is None, out
    assert out[2]["text"] == "EN:hola", out[2]


async def case_results_survive_a_mid_batch_eviction():
    """The response is built from a per-request map, NOT re-read out of the
    module cache — which evicts.

    Before this, assembly looked its own answers back up in `_cache` after
    `_mem_put` had already shed the oldest quarter at the cap. That happened to
    be safe only because a batch (MAX_TEXTS=100) is smaller than the slice the
    shed drops (_CACHE_CAP//4 = 2000), an invariant nothing stated or enforced —
    so raising the batch size would have silently turned successful translations
    into blank bubbles. Shrink the cache so eviction fires MID-BATCH and assert
    every text still comes back."""
    _install_fakes()
    await _reset()
    cap = translate_api._CACHE_CAP
    translate_api._CACHE_CAP = 4          # sheds 1 entry once 4 are held
    try:
        texts = [f"frase numero {i}" for i in range(12)]
        out = await _post(texts)
        assert all(r is not None for r in out), \
            f"eviction ate {sum(1 for r in out if r is None)}/12 answers: {out}"
        assert [r["text"] for r in out] == [f"EN:{t}" for t in texts], out
        # The cache really did evict — otherwise this case proves nothing.
        assert len(translate_api._cache) < len(texts), \
            f"no eviction happened, cache holds {len(translate_api._cache)}"
    finally:
        translate_api._CACHE_CAP = cap


async def case_prune_holds_the_cap():
    _install_fakes()
    await _reset()

    # Shrink the cap so the sweep is testable without 50k rows. The prune is
    # age-ordered, so seed with explicit, staggered created_at values.
    cap, prune_to = translate_api._DB_CAP, translate_api._DB_PRUNE_TO
    translate_api._DB_CAP, translate_api._DB_PRUNE_TO = 10, 6
    try:
        base = datetime(2026, 7, 1, 12, 0, 0)
        async with get_session() as s:
            for i in range(12):
                s.add(TranslationCache(
                    text_hash=f"h{i:02d}", target="en", src_lang="es",
                    source_text=f"t{i}", translated=f"EN:t{i}",
                    created_at=base + timedelta(minutes=i)))
            await s.commit()

        await translate_api._prune()

        async with get_session() as s:
            left = sorted((await s.execute(select(TranslationCache.text_hash))).scalars().all())
        assert len(left) == 6, f"prune should land on _DB_PRUNE_TO, left {len(left)}"
        assert left == [f"h{i:02d}" for i in range(6, 12)], \
            f"prune must evict OLDEST first, kept {left}"

        # Under the cap it is a no-op, not a slow drip downward.
        await translate_api._prune()
        async with get_session() as s:
            still = (await s.execute(select(func.count()).select_from(TranslationCache))).scalar_one()
        assert still == 6, f"prune under the cap deleted rows: {still}"
    finally:
        translate_api._DB_CAP, translate_api._DB_PRUNE_TO = cap, prune_to


async def case_429_pauses_google():
    import asyncio
    await _reset()
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(req.url.params["q"])
        return httpx.Response(429)

    sem = asyncio.Semaphore(1)
    async with _RealClient(transport=httpx.MockTransport(handler)) as client:
        assert await _real_fetch(client, sem, "hola", "en") is None
        assert translate_api._cooling_down(), "a 429 must start the cooldown"
        assert await _real_fetch(client, sem, "adios", "en") is None
    assert hits == ["hola"], f"called Google during the cooldown: {hits}"


async def case_cooldown_skips_google_keeps_cache():
    _install_fakes()
    await _reset()
    await _post(["hola"])
    translate_api._cache.clear()
    _calls.clear()

    translate_api._cooldown_until = time.monotonic() + 60
    out = await _post(["hola", "adios"])
    assert _calls == [], f"called Google during the cooldown: {_calls}"
    assert out[0]["text"] == "EN:hola", f"cached answer must still serve: {out[0]}"
    assert out[1] is None, out[1]

    translate_api._cooldown_until = 0.0
    out = await _post(["adios"])
    assert _calls == ["adios"], f"after the cooldown Google must be tried again: {_calls}"
    assert out[0]["text"] == "EN:adios", out[0]


async def case_english_skips_google():
    _install_fakes()
    await _reset()

    out = await _post(["hey babe how are you", "hallo wie geht es dir", "Turn um"])
    assert _calls == ["hallo wie geht es dir", "Turn um"], f"wrong gtx calls: {_calls}"
    assert out[0] == {"text": "hey babe how are you", "lang": "en"}, out[0]
    assert out[1]["text"] == "EN:hallo wie geht es dir", out[1]

    _calls.clear()
    out = await _post(["hey babe how are you"], target="de")
    assert _calls == ["hey babe how are you"], f"outbound en→de skipped gtx: {_calls}"


async def case_short_text_uses_thread_language():
    _install_fakes()
    await _reset()

    out = await _post(["Ja", "hast du noch was anderes", "Ne"])
    assert _calls == ["hast du noch was anderes", "Ja", "Ne"], _calls
    assert _sources == ["auto", "es", "es"], f"short texts not sent from the thread's language: {_sources}"
    assert out[0] == {"text": "ES:Ja", "lang": "es"}, out[0]
    assert out[2]["text"] == "ES:Ne", out[2]

    _calls.clear()
    _sources.clear()
    out = await _post(["Ja"])
    assert _sources == ["auto"], f"a lone short text with no context must auto-detect: {_sources}"
    assert out[0]["text"] == "EN:Ja", "an auto answer must not reuse the hinted cache row"


async def case_hint_wins_for_short_text():
    _install_fakes()
    await _reset()

    assert translate_api._is_short("t'as faim")
    out = await _post(["Ja"], hint="de")
    assert _sources == ["de"], _sources
    assert out[0] == {"text": "DE:Ja", "lang": "de"}, out[0]

    _calls.clear()
    await _post(["Ja", "frase larga aqui"], hint="de-AT")
    assert _calls == ["frase larga aqui"], f"hinted short text not cached: {_calls}"

    _calls.clear()
    _sources.clear()
    await _post(["Ja"], hint="en")
    assert _sources == ["auto"], f"a hint equal to the target must be ignored: {_sources}"

    _sources.clear()
    await _post(["Ja"], hint="x'; drop")
    assert _sources == [], f"a malformed hint must fall back to the cached auto answer: {_sources}"


async def case_batches_share_google_permits():
    import asyncio

    await _reset()
    saturated = asyncio.Event()
    release = asyncio.Event()
    hits = 0

    async def handler(_req):
        nonlocal hits
        hits += 1
        if hits >= translate_api._CONCURRENCY:
            saturated.set()
        await release.wait()
        return httpx.Response(429)

    translate_api._fetch_one = _real_fetch
    translate_api.httpx.AsyncClient = lambda *a, **kw: _RealClient(transport=httpx.MockTransport(handler))
    batches = asyncio.gather(*(_post([f"bonjour mes amis numéro {i}"]) for i in range(12)))
    try:
        await asyncio.wait_for(saturated.wait(), 5)
        await asyncio.sleep(0.05)
    finally:
        release.set()
        await batches
    assert hits == translate_api._CONCURRENCY, hits


async def case_english_shortcut_respects_hint_and_cache():
    _install_fakes()
    await _reset()
    for text, hint in [("Bad", "de"), ("I love you auch", None), ("Ya", None),
                       ("Hey babe, how are you? Danke", None)]:
        assert (await _post([text], hint=hint))[0]["text"] != text, text

    text = "hey babe how are you"
    key = translate_api._cache_key(text, "en")
    await translate_api._db_put("en", {key: (text, {"text": "cached answer", "lang": "es"})})
    assert (await _post([text]))[0]["text"] == "cached answer"


async def case_forced_echo_retries_auto_and_never_persists_echo():
    await _reset()
    key = translate_api._cache_key("Salut", "en", "de")
    await translate_api._db_put("en", {key: ("Salut", {"text": "SALUT ", "lang": "de"})})
    calls = []

    def handler(req):
        source, text = req.url.params["sl"], req.url.params["q"]
        calls.append((source, text))
        result = "Hello" if source == "auto" and text == "Salut" else text.upper() + " "
        return httpx.Response(200, json=[[[result]], None, "fr" if source == "auto" else source])

    translate_api._fetch_one = _real_fetch
    translate_api.httpx.AsyncClient = lambda *a, **kw: _RealClient(transport=httpx.MockTransport(handler))
    assert (await _post(["Salut"], hint="de")) == [{"text": "Hello", "lang": "fr"}]
    assert calls == [("de", "Salut"), ("auto", "Salut")]
    echo = [{"text": "MACHIN ", "lang": "fr"}]
    assert (await _post(["Machin"], hint="de")) == echo
    assert calls[-2:] == [("de", "Machin"), ("auto", "Machin")]
    assert (await _post(["visit my URL"], hint="de")) == [{"text": "VISIT MY URL ", "lang": "fr"}]
    assert calls[-1] == ("auto", "visit my URL")
    assert (await _post(["Machin"], hint="de")) == echo
    assert len(calls) == 5
    async with get_session() as session:
        rows = (await session.execute(select(TranslationCache.source_text, TranslationCache.src_lang))).all()
    assert sorted(rows) == [("Machin", "fr"), ("Salut", "fr"), ("visit my URL", "fr")]
    translate_api._cache.clear()
    calls.clear()
    assert (await _post(["Salut"], hint="de")) == [{"text": "Hello", "lang": "fr"}]
    assert (await _post(["Machin"], hint="de")) == echo
    assert (await _post(["visit my URL"], hint="de")) == [{"text": "VISIT MY URL ", "lang": "fr"}]
    assert calls == []


_harness.run(
    case_batches_share_google_permits,
    case_english_shortcut_respects_hint_and_cache,
    case_forced_echo_retries_auto_and_never_persists_echo,
    case_short_text_uses_thread_language,
    case_hint_wins_for_short_text,
    case_english_skips_google,
    case_429_pauses_google,
    case_cooldown_skips_google_keeps_cache,
    case_first_batch_calls_google_once_per_distinct_text,
    case_second_batch_is_free,
    case_survives_a_relay_restart,
    case_failure_is_not_cached,
    case_blank_texts_never_call_out,
    case_results_survive_a_mid_batch_eviction,
    case_prune_holds_the_cap,
)
