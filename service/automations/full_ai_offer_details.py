"""automations/full_ai_offer_details.py — the Offer resolver (spec phase-01-full-ai-offer-details › B,
ADR-0038): which Offer an Offer-details question is about, a pure read-only lookup shared by live
and test.

  LOOKBACK_S / LOOKBACK_N          the look-back: the newest 10 Offer rows created within 7 days of
                                   the Anchor (kept apart from `full_ai_owned.OFFER_OPEN_S`)
  OfferAsk                         what a Turn's loader hands the resolver (`TurnFacts.offer_ask`)
  build_ask(rows, now, open_ids, tease, text, *, live=False, ...)   pure: the ask from the Fan's
                                   Decision rows (oldest first) at his Anchor `now`
  resolve_offer(ask) -> Resolved   pure, first match wins: quote_reply, price, media, open_offer,
                                   none
  live_ask(rows, now, tease, turn) the live loader's ask (`full_ai_live.load`): open by
                                   `live_open_ids`, Quote-reply id by `quote_message_id_of`
  session_ask(rows, now, tease_row, turn, reply_to_n)   the Test chat loader's (`full_ai_test.fetch`)
  OfferFacts / offer_facts(row, vault, earlier)   pure (spec C): what the Writer may state about the
                                   resolved Offer
  load_offer_vault(account_id, media_ids)   its vault kinds, lengths and descriptions
  offer_answer_ok(text, of) -> rules   pure (spec D): the Offer answer check, the failed rule names
  offer_fallback(of) -> str            pure (spec D): the plain fact clause (NEW-169), "which one?",
                                       "can't confirm what's in it"
  diagnostics(got, of) -> dict         pure (spec D): `reply_json.offer_details` before the check

Writes nothing. `run_turn` resolves on row `offer_details` (spec C) and checks her answer (spec D,
`full_ai_offer_turn.offer_check`).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select

import vault_ai_brief
from automations.full_ai_owned import OFFER_OPEN_S
from automations.full_ai_sell import (
    _AMOUNT, _KIND_NOUNS, _NOT_A_COUNT, _NUMBER_WORDS, _PIC_NOUNS, _TOKEN, _VID_NOUNS, MOVING_KINDS, _buckets,
    _count_word, _media_phrase, _money, _words, claims_clip, quoted_cents,
)
from automations.full_ai_test import _loads, _media, _n, _offers, open_offers_of
from db.engine import get_session
from db.models import VaultItem
from of_shapes import reply_to_id

LOOKBACK_S = 7 * 86400
LOOKBACK_N = 10

Step = Literal["quote_reply", "price", "media", "open_offer", "none"]


@dataclass(frozen=True)
class OfferAsk:
    """`candidates`: the Fan's Offer rows inside the look-back, oldest first (sent only; live drops a
    priced row OF never confirmed), plus a standing Pending tease. `open_ids`: those that are open
    (the 24 h open-offer rule selling uses, plus the Pending tease). `quote_message_id` (live: the OF
    message he quote-replied to), `quote_row_id` (test: the marked Turn's row), `text`: his Turn's
    lines joined. `reply_to_n`: the Test chat's mark as sent (`reply_json.reply_to_n`), else None."""
    candidates: tuple = ()
    open_ids: frozenset = frozenset()
    quote_message_id: int | None = None
    quote_row_id: int | None = None
    text: str = ""
    reply_to_n: int | None = None


@dataclass(frozen=True)
class Resolved:
    row: Any
    step: Step


NONE = Resolved(None, "none")


def build_ask(rows, now: datetime, open_ids: frozenset, tease, text: str, *, live: bool = False,
              quote_message_id: int | None = None, quote_row_id: int | None = None,
              reply_to_n: int | None = None) -> OfferAsk:
    """The Offer ask over the Fan's rows (oldest first) at `now` (his Anchor). Pure."""
    sent = [r for r in _offers(rows) if r.status == "sent"
            and (now - r.created_at).total_seconds() <= LOOKBACK_S
            and not (live and r.offer_price_cents and getattr(r, "offer_message_id", None) is None)]
    cands = sent[-LOOKBACK_N:]
    opened = set(open_ids)
    if tease is not None:
        cands = [r for r in cands if r.id != tease.id] + [tease]
        opened.add(tease.id)
    ids = {r.id for r in cands}
    return OfferAsk(tuple(cands), frozenset(opened & ids), quote_message_id, quote_row_id, text, reply_to_n)


def live_open_ids(rows, now: datetime) -> frozenset:
    """Live open Offers: `open_offers_of` filtered as `full_ai_owned.open_offer_live` filters its
    newest one (at most `OFFER_OPEN_S` old; a priced one only with its OF message id)."""
    return frozenset(r.id for r in open_offers_of(rows)
                     if (now - r.created_at).total_seconds() <= OFFER_OPEN_S
                     and not (r.offer_price_cents and r.offer_message_id is None))


def quote_message_id_of(turn) -> int | None:
    """The newest OF Quote-reply id over his Turn's inbound messages (their stored `raw_json`)."""
    for m in reversed(list(turn)):
        try:
            got = reply_to_id(json.loads(m.raw_json or "null"))
        except (TypeError, ValueError):
            got = None
        if got is not None:
            return got
    return None


def turn_text(turn) -> str:
    """His Turn's lines joined."""
    return " ".join(m.body.strip() for m in turn if (m.body or "").strip())


def live_ask(rows, now: datetime, tease, turn) -> OfferAsk:
    """The live loader's ask: his live rows on this account (`full_ai_live.load`), the Pending
    tease `_folds` kept (a `Teased`, its row looked up by id), his Turn's inbound messages."""
    tease_row = next((r for r in rows if r.id == tease.row_id), None) if tease is not None else None
    return build_ask(rows, now, live_open_ids(rows, now), tease_row, turn_text(turn), live=True,
                     quote_message_id=quote_message_id_of(turn))


def session_ask(rows, now: datetime, tease_row, turn, reply_to_n: int | None) -> OfferAsk:
    """The Test chat loader's ask: the side's session rows (`full_ai_test.fetch`); `reply_to_n`
    names the Turn whose row he marked (that side's row with that Turn number)."""
    quoted = next((r.id for r in rows if reply_to_n is not None
                   and _n(r.trigger_key) == reply_to_n), None)
    return build_ask(rows, now, frozenset(r.id for r in open_offers_of(rows)), tease_row, turn_text(turn),
                     quote_row_id=quoted, reply_to_n=reply_to_n)


def media_cue(text: str) -> str | None:
    """"video" / "photo" when his text names exactly one of the two kinds (`_VID_NOUNS` xor
    `_PIC_NOUNS`), else None. Pure."""
    words = set(_words(text))
    vid, pic = bool(words & _VID_NOUNS), bool(words & _PIC_NOUNS)
    return ("video" if vid else "photo") if vid != pic else None


def _items(r) -> dict[int, dict]:
    """Row `r`'s `offer_media_json.items` by media id (each {id, kind, seconds})."""
    return {int(it["id"]): it for it in _loads(r.offer_media_json).get("items") or [] if "id" in it}


def _kinds(ids: Iterable[int], items: dict[int, dict], vault: dict[int, dict]) -> dict[str, int]:
    """Kind -> count over `ids`: the row's item kind, else the vault's; an id with neither is left out."""
    kinds: dict[str, int] = {}
    for i in ids:
        k = (items.get(i) or {}).get("kind") or (vault.get(i) or {}).get("kind")
        if k:
            kinds[str(k)] = kinds.get(str(k), 0) + 1
    return kinds


def _holds(r, cue: str) -> bool:
    """Row `r`'s locked media hold that kind (`_buckets`: moving kinds are videos, anything but
    audio a photo).
    ASSUMPTION: only locked items count, not free previews (rung 3: the PPV line `_priced` and
    `claim_ok` read locked kinds). Overturned if a free preview's kind should name an Offer."""
    pics, vids, _ = _buckets(_kinds(_media(r, "locked"), _items(r), {}))
    return bool(vids if cue == "video" else pics)


# A word that points his question at an earlier Offer ("the one i bought", "like before").
_PAST_WORDS = frozenset({"bought", "before", "earlier", "yesterday", "old", "older", "other", "previous",
                         "ago", "unlocked", "already", "paid", "spent"})
_DEFINITE = frozenset({"the", "that", "those"})
_NOT_DEFINITE = frozenset({"a", "an", "it", "its", "is", "this", "these"})


def _names_one(toks: list[str], i: int) -> bool:
    """The price at `toks[i]` names a row: "one" or a media noun follows it, past currency words
    ("the $20 one", "that 20 dollar vid"); a bare price ("is that $20?") is the question."""
    j = i + 1
    while j < len(toks) and toks[j] in _CURRENCY:
        j += 1
    return j < len(toks) and (toks[j] in ("one", "ones") or toks[j] in _KIND_NOUNS)


def _refers(text: str) -> bool:
    """His text names an Offer rather than asking what the open one is (rwl3 A5): a past-Offer word
    (`_PAST_WORDS`, incl. "paid" / "spent"), "the one" with a price after it, or "the" / "that" / "those" within the 3 words before a media noun or a price
    that names one (`_names_one`), with no "a" / "it" / "is" / "this" between ("the video", "the $20
    one"; not "is it a video?", "is this $20?", "is that $20?"). Pure."""
    toks = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    if _PAST_WORDS & set(toks):
        return True
    if any(a == "the" and b in ("one", "ones") and any(t[0].isdigit() for t in toks[i + 2:])
           for i, (a, b) in enumerate(zip(toks, toks[1:]))):
        return True  # "the one ... $20" (rwl3 final check)
    for i, tok in enumerate(toks):
        if not ((tok[0].isdigit() and _names_one(toks, i)) or tok in _KIND_NOUNS):
            continue
        for back in reversed(toks[max(0, i - 3):i]):
            if back in _DEFINITE:
                return True
            if back in _NOT_DEFINITE:
                break
    return False


def resolve_offer(ask: OfferAsk) -> Resolved:
    """The Offer his question names, first match wins. Pure.
    rwl3 A5: with an Offer open, a price / media match on a row that is not open counts only when
    his text refers to it (`_refers`); else the newest open Offer (step open_offer). A kind or price
    he merely asks about ("is it a video?") is the question, not a reference. A price tie with
    exactly one open row among the matches is that row unless he refers to an older one."""
    cands = ask.candidates
    for r in cands:
        if ask.quote_message_id is not None and getattr(r, "offer_message_id", None) == ask.quote_message_id:
            return Resolved(r, "quote_reply")
        if ask.quote_row_id is not None and r.id == ask.quote_row_id:
            return Resolved(r, "quote_reply")
    opened = [r for r in cands if r.id in ask.open_ids]
    got = _by_cue(ask, cands, opened)
    if got.row is not None and got.row.id not in ask.open_ids and opened and not _refers(ask.text):
        return Resolved(opened[-1], "open_offer")
    return got


def _by_cue(ask: OfferAsk, cands: list, opened: list) -> Resolved:
    """Steps price, media, open_offer, none of `resolve_offer`."""
    cue = media_cue(ask.text)
    p = quoted_cents(ask.text)
    if p is not None:
        hit = [r for r in cands if r.offer_price_cents == p]
        if len(hit) > 1:
            narrowed = [r for r in hit if cue and _holds(r, cue)]
            if len(narrowed) == 1:
                return Resolved(narrowed[0], "price")
            open_hit = [r for r in hit if r.id in ask.open_ids]
            return Resolved(open_hit[0], "price") if len(open_hit) == 1 and not _refers(ask.text) else NONE
        if hit:
            return Resolved(hit[0], "price")
        if len(opened) >= 2:
            return NONE
    if cue:
        held = [r for r in cands if _holds(r, cue)]
        if len(held) == 1:
            return Resolved(held[0], "media")
        if held:
            newest = [r for r in held if r.id in ask.open_ids]
            return Resolved(newest[-1], "media") if newest else NONE
    return Resolved(opened[-1], "open_offer") if opened else NONE


@dataclass(frozen=True)
class OfferFacts:
    """What the Writer may state about the resolved Offer (spec C; `full_ai_writers.offer_facts_block`).
    `locked_kinds` / `preview_kinds`: kind -> count (the row's items, else the vault); `seconds`: each
    locked clip's length; `descriptions`: the locked items' vault descriptions (else the scene row's
    `offer_item_ref.desc`); `quoted_cents`: `offer_price_cents` (None: a tease, no price named yet; 0:
    free); `same_as_first`: (the 1st Offer's sent time, same locked media) when this is not the 1st;
    `missing`: a subset of {"description", "media"}; `captions`: her text that carried this Offer
    (the row's `ppv` bubble, else its text bubbles: a tease), fair to reuse (rwl3 N3)."""
    locked_kinds: dict[str, int]
    locked: int
    preview_kinds: dict[str, int]
    previews: int
    seconds: tuple[int, ...]
    descriptions: tuple[str, ...]
    quoted_cents: int | None
    sent_at: datetime
    bought: bool
    same_as_first: tuple[datetime, bool] | None
    missing: frozenset[str]
    captions: tuple[str, ...] = ()


def offer_facts(row, vault: dict[int, dict], earlier: Sequence) -> OfferFacts:
    """Offer row `row`'s facts over `vault` (`load_offer_vault`) and `earlier`, the Offer ask's
    candidates before it, oldest first (the 1st is the one "same as the first" means). Pure.
    ASSUMPTION: "description" is missing only when no locked item has one (rung 5). Overturned if a
    set with some items undescribed should count as missing."""
    items, locked, previews = _items(row), sorted(_media(row, "locked")), sorted(_media(row, "previews"))
    locked_kinds = _kinds(locked, items, vault)
    seconds = []
    for i in locked:
        it, v = items.get(i) or {}, vault.get(i) or {}
        secs = it.get("seconds") or v.get("seconds")
        if str(it.get("kind") or v.get("kind")) in MOVING_KINDS and secs:
            seconds.append(int(secs))
    descs = tuple(dict.fromkeys(d for i in locked if (d := (vault.get(i) or {}).get("description"))))
    if not descs and (ref_desc := _loads(row.offer_item_ref).get("desc")):
        descs = (str(ref_desc),)
    missing = {"description"} if not descs else set()
    if not locked or sum(locked_kinds.values()) < len(locked):
        missing.add("media")
    first = earlier[0] if earlier else None
    same = (first.created_at, _media(first, "locked") == set(locked)) if first is not None else None
    texts = [p for p in _loads(getattr(row, "reply_json", None)).get("parts") or [] if p.get("text")]
    caps = tuple(str(p["text"]) for p in ([p for p in texts if p.get("ppv")] or texts))
    return OfferFacts(locked_kinds, len(locked), _kinds(previews, items, vault), len(previews),
                      tuple(seconds), descs, row.offer_price_cents, row.created_at,
                      row.outcome == "bought", same, frozenset(missing), caps)


async def load_offer_vault(account_id: str, media_ids: Iterable[int]) -> dict[int, dict]:
    """Media id -> {kind, seconds, description} from the vault, removed items included, each read
    through `vault_ai_brief.settled_reading` (precedent `vault_scripts._load_rows`)."""
    ids = sorted(set(media_ids))
    if not ids:
        return {}
    async with get_session() as s:
        recs = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.duration_seconds, VaultItem.ai_fields_json)
            .where(VaultItem.account_id == str(account_id), VaultItem.media_id.in_(ids)))).all()
    out: dict[int, dict] = {}
    for mid, kind, dur, raw in recs:
        fields = vault_ai_brief.settled_reading(vault_ai_brief.load_fields(raw))
        out[int(mid)] = {"kind": kind, "seconds": dur,
                         "description": str(fields.get("description") or "").strip()}
    return out


# ── Offer answer check + fallback (spec D) ────────────────────────────

Rule = Literal["media", "count", "duration", "dollars", "free", "none"]
RULES: tuple[Rule, ...] = ("media", "count", "duration", "dollars", "free", "none")
# A word that marks a count or a "free" as the free previews' ("1 free pic", "1 pic as a preview").
_PREVIEW_WORDS = frozenset({"free", "preview", "previews"})
_ORDINAL = frozenset({"st", "nd", "rd", "th"})     # a digit's suffix: "2nd" is no count
_SECS = frozenset({"sec", "secs", "second", "seconds"})
_MINS = frozenset({"min", "mins", "minute", "minutes"})
SECS_SLACK = 5      # a seconds claim may be this far off a locked clip's length
# A spelled dollar amount ("twenty five bucks"): number words before a currency word.
_CURRENCY = frozenset({"dollar", "dollars", "buck", "bucks", "usd"})
_SPELLED = {**{w: n for w, n in _NUMBER_WORDS.items() if w not in ("a", "an")}, "zero": 0,
            **dict(zip(("thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"),
                       range(13, 20))),
            **dict(zip(("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"),
                       range(20, 100, 10)))}
WHICH_ONE = "which one?"    # NEW-169: the fallback with no Offer named
NO_FACTS = "can't confirm what's in it"   # NEW-169: an Offer named, media missing, no price


@dataclass(frozen=True)
class _Said:
    """What her text claims, read off its tokens: the media kinds named ("photo" / "video"), each
    count before a media noun (n, kind, beside a preview word), each length (n, "sec" | "min"),
    every dollar amount in cents, and for each "free" whether a media noun or "preview" follows
    within two words."""
    kinds: frozenset[str]
    counts: tuple[tuple[int, str, bool], ...]
    lengths: tuple[tuple[int, str], ...]
    cents: frozenset[int]
    frees: tuple[bool, ...]


def _kind(noun: str) -> str:
    return "video" if noun in _VID_NOUNS else "photo"


def _spelled_cents(words: list[str]) -> int | None:
    """The amount the number words ending `words` spell ("twenty five", "a hundred", "zero": 0), in
    cents; None when they spell nothing."""
    j = len(words)
    while j and (words[j - 1] in _SPELLED or words[j - 1] in ("hundred", "and")
                 or (words[j - 1] in ("a", "an") and j < len(words) and words[j] == "hundred")):
        j -= 1
    spelled, total = words[j:], 0
    for w in spelled:
        total = max(total, 1) * 100 if w == "hundred" else total + _SPELLED.get(w, int(w in ("a", "an")))
    return total * 100 if total or "zero" in spelled else None


def _after_noun(words: list[str]) -> bool:
    """A preview word in `words` (the reach after a media noun) before the next count or media
    noun, so "1 pic + 1 free preview" never lends the 2nd count's "free" to the 1st."""
    for w in words:
        if _count_word(w) is not None or w in _KIND_NOUNS:
            return False
        if w in _PREVIEW_WORDS:
            return True
    return False


def _said(text: str) -> _Said:
    toks = _TOKEN.findall(text.lower())
    counts, lengths, frees = [], [], []
    for i, tok in enumerate(toks):
        if tok == "free":
            frees.append(bool(set(toks[i + 1:i + 3]) & (_KIND_NOUNS | _PREVIEW_WORDS)))
        n = _count_word(tok)
        if n is None or i + 1 >= len(toks):
            continue
        nxt = toks[i + 1]
        if tok.isdigit() and nxt in _ORDINAL:       # "the 2nd pic": `_TOKEN` splits "2" from "nd"
            continue
        if nxt in _SECS or nxt in _MINS:
            lengths.append((n, "sec" if nxt in _SECS else "min"))
        elif nxt in _KIND_NOUNS:
            counts.append((n, _kind(nxt), _after_noun(toks[i + 2:i + 5])))
        elif (i + 2 < len(toks) and toks[i + 2] in _KIND_NOUNS and nxt.isalpha()     # "1 paid pic"
              and nxt not in _NOT_A_COUNT and nxt not in _NUMBER_WORDS):
            counts.append((n, _kind(toks[i + 2]), nxt in _PREVIEW_WORDS or _after_noun(toks[i + 3:i + 6])))
    cents = {round(float(a or b) * 100) for a, b in _AMOUNT.findall(text)}
    cents |= {c for i, w in enumerate(toks) if w in _CURRENCY and (c := _spelled_cents(toks[:i])) is not None}
    kinds = {_kind(w) for w in toks if w in _KIND_NOUNS} | ({"video"} if claims_clip(text) else set())
    return _Said(frozenset(kinds), tuple(counts), tuple(lengths), frozenset(cents), tuple(frees))


def _length_ok(n: int, unit: str, seconds: tuple[int, ...]) -> bool:
    """A seconds claim within `SECS_SLACK` of a locked clip; a minutes claim only for a clip of a
    minute or more, its floor or ceil."""
    if unit == "sec":
        return any(abs(n - s) <= SECS_SLACK for s in seconds)
    return any(s >= 60 and n in (s // 60, -(-s // 60)) for s in seconds)


def offer_answer_ok(text: str, of: OfferFacts | None) -> tuple[Rule, ...]:
    """The Offer answer check: the rules (`RULES` order) her text fails against the resolved
    Offer's facts; () passes. Pure.
      media     a video word needs a locked or preview clip, a photo word a photo; a clip word
                ("filmed", "press play": `full_ai_sell.claims_clip`) reads as a video word
      count     a number before a media noun ("3 pics", "1 paid pic") equals that kind's locked
                count; the preview count only with "free" / "preview" between them or within two
                words after the noun, stopping at the next count or media noun ("1 free pic", "1 pic
                as a preview"; "1 pic + 1 free preview" is 1 paid pic); "2nd" is no count
      duration  "N sec" within `SECS_SLACK` of a locked clip; "N min" only over a clip >= 60 s, its
                floor or ceil
      dollars   every amount ($25, 25 bucks, "twenty five bucks", "zero dollars") equals the Quoted
                price; none on a tease (NULL) or a Free item (0)
      free      "free" on a priced Offer or a tease only right before a media noun or "preview",
                with free previews to name
      none      no Offer resolved, or its media missing: no count, length, media word or amount;
                with media missing the Quoted price is still allowed
    ASSUMPTION: "within two words after it" counts up to two words between the noun and the
    preview word, so the spec's own "1 pic as a preview" passes (rung 1, its worked example).
    Overturned if a preview count slips through on a longer reach.
    ASSUMPTION: with media missing the Quoted price is an allowed amount: it is a fact of the row,
    not of the media ids, and C's facts block and `offer_fallback` both state it (rung 3,
    full_ai_writers.offer_facts_block). Overturned if the owner wants no price on such an Offer."""
    said = _said(text)
    failed: set[Rule] = set()
    if of is None or "media" in of.missing:
        price = {of.quoted_cents} if of is not None and of.quoted_cents else set()
        if said.kinds or said.counts or said.lengths or said.cents - price:
            failed.add("none")
    else:
        pics, vids, _ = _buckets(of.locked_kinds)
        free_pics, free_vids, _ = _buckets(of.preview_kinds)
        locked, previews = {"photo": pics, "video": vids}, {"photo": free_pics, "video": free_vids}
        if any(not (locked[k] or previews[k]) for k in said.kinds):
            failed.add("media")
        if any(n != locked[k] and not (beside and n == previews[k]) for n, k, beside in said.counts):
            failed.add("count")
        if not all(_length_ok(n, unit, of.seconds) for n, unit in said.lengths):
            failed.add("duration")
        if said.cents - ({of.quoted_cents} if of.quoted_cents else set()):
            failed.add("dollars")
    if of is not None and of.quoted_cents != 0 and not all(beside and of.previews for beside in said.frees):
        failed.add("free")
    return tuple(r for r in RULES if r in failed)


def offer_fallback(of: OfferFacts | None) -> str:
    """NEW-169: the plain answer a twice-failed (or empty, or too late) Offer-details reply sends,
    built from the facts as `full_ai_sell.fallback_caption` is: the locked media phrase, its free
    previews, each clip's length and the Quoted price ("3 pics + 1 free preview, $25"); a tease
    names no price and never "free" ("3 pics + 1 preview"); a Free item ends ", free"; media
    missing: no counts or kinds, and with no price either `NO_FACTS`. No Offer named: `WHICH_ONE`.
    Pure.
    ASSUMPTION: a resolved Offer with nothing to state (media missing, a tease) says `NO_FACTS`,
    OFFER_GOAL's "say you can't confirm" as a clause (rung 3, NEW-166), never "which one?", which
    the spec keeps for no Offer named. Overturned if the owner wants other wording."""
    if of is None:
        return WHICH_ONE
    clauses = []
    if "media" not in of.missing:
        what = _media_phrase(of.locked_kinds)
        if of.previews:
            what += f" + {of.previews} {'free ' * bool(of.quoted_cents)}preview{'s' * (of.previews > 1)}"
        clauses.append(what)
        if of.seconds:
            clauses.append(" + ".join(f"{s} sec" for s in of.seconds))
    if of.quoted_cents:
        clauses.append(_money(of.quoted_cents))
    elif of.quoted_cents == 0:
        clauses.append("free")
    return ", ".join(clauses) or NO_FACTS


def diagnostics(got: Resolved, of: OfferFacts | None) -> dict[str, Any]:
    """`reply_json.offer_details` before the check (spec D): the row, the resolved Offer row (id,
    OF message id, media ids) and the resolver step, `check` "ok" with no `failed` rule yet, and the
    facts `missing`. `run_turn` records it and `full_ai_offer_turn.offer_check` fills in `check` /
    `failed`; none of it reaches parts. Pure."""
    r = got.row
    return {"row": "offer_details", "offer_row_id": r.id if r is not None else None,
            "message_id": r.offer_message_id if r is not None else None,
            "media_ids": {k: sorted(_media(r, k)) if r is not None else [] for k in ("locked", "previews")},
            "step": got.step, "check": "ok", "failed": [], "missing": sorted(of.missing) if of else []}
