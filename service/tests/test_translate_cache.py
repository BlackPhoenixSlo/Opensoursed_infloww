#!/usr/bin/env python3
"""
POST /admin/translate — the three cache tiers behind the 🌐 chat-translate
toggle. Durable regression suite (plain-assert, no pytest — repo convention).

Google's gtx endpoint is faked, so there is no network; what's under test is how
many times we'd have CALLED it, which is the entire point of the feature. Before
the durable tier existed the only caches were a per-tab JS Map and this module's
dict, so every page reload and every relay deploy re-bought the same
translations (~1.5s per 40 fresh bubbles, measured from the VPS).

Cases:
  case_first_batch_calls_google_once_per_distinct_text:
      the in-batch dedupe — the UI sends whatever is on screen, so "hey" three
      times must still be ONE call, and the answer lands on all three slots in
      the right order.
  case_second_batch_is_free:
      the warm path. No gtx call at all on a repeat batch.
  case_survives_a_relay_restart:
      the whole reason the table exists: wipe process memory (what a deploy does)
      and the answers must still come back with ZERO calls.
  case_failure_is_not_cached:
      a transient Google failure must NOT pin "untranslatable" — the next batch
      retries and can succeed. Cache the null and a rate-limited minute would
      poison a thread until the next restart.
  case_blank_texts_never_call_out:
      empty/whitespace bubbles (media-only sends) map to null without a call.
  case_results_survive_a_mid_batch_eviction:
      the response is assembled from a per-request map, not re-read out of the
      evicting module cache — the invariant that made the old assembly work was
      never written down, so a bigger batch would have blanked real answers.
  case_prune_holds_the_cap:
      the age-ordered sweep keeps the table bounded and evicts OLDEST first —
      the cap is what stops a nice-to-have readability aid from becoming the
      biggest table in a DB that has been corrupted before.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_translate_cache.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod).
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import translate_api  # noqa: E402 — module under test
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


async def _fake_fetch(client, sem, text: str, target: str):
    _calls.append(text)
    if text in _fail_for:
        return None                       # what a 429 / timeout looks like here
    return {"text": f"EN:{text}", "lang": "es"}


def _install_fakes() -> None:
    translate_api.httpx.AsyncClient = lambda *a, **k: _FakeClient()  # type: ignore[assignment]
    translate_api._fetch_one = _fake_fetch                            # type: ignore[assignment]


async def _reset() -> None:
    """Fresh process memory, call log AND durable tier — each case starts cold."""
    _calls.clear()
    _fail_for.clear()
    translate_api._cache.clear()
    translate_api._rows_since_prune = 0
    async with get_session() as s:
        await s.execute(TranslationCache.__table__.delete())
        await s.commit()


async def _post(texts: list[str]) -> list[dict | None]:
    body = translate_api.TranslateBody(texts=texts, target="en")
    return (await translate_api.translate_batch(body))["results"]


# ── Cases ────────────────────────────────────────────────────────────

async def case_first_batch_calls_google_once_per_distinct_text():
    _install_fakes()
    await _reset()

    out = await _post(["hola", "hey", "hey", "hey", "adios"])

    # 5 bubbles, 3 distinct — and first-seen order, so the batch is stable.
    assert _calls == ["hola", "hey", "adios"], f"not deduped: {_calls}"
    assert [r["text"] for r in out] == [
        "EN:hola", "EN:hey", "EN:hey", "EN:hey", "EN:adios"
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


_harness.run(
    case_first_batch_calls_google_once_per_distinct_text,
    case_second_batch_is_free,
    case_survives_a_relay_restart,
    case_failure_is_not_cached,
    case_blank_texts_never_call_out,
    case_results_survive_a_mid_batch_eviction,
    case_prune_holds_the_cap,
)
