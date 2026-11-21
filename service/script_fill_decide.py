"""script_fill_decide.py — what a Fill would do to one Sequence (spec phase 01, sub-phase 1b). Pure: no I/O,
no rng, no clock. `script_fill_api` loads, calls `plan`, and writes; this module only decides.

Public functions:

  roles(rows) -> {id: Role}       Role = {role: chat|free_media|paid_media, wants: clip|photo|any|None,
                                  count, flags}. First match wins: `notes` "no content" -> chat + flag
                                  `lock_no_content` (beats a saved price); saved price > 0 -> paid; `notes`
                                  "ppv" -> paid; "freebie" -> free; "bridge" -> chat; the text quotes an
                                  amount (`full_ai_sell.price_ok`'s pattern) -> paid; a format / count promise
                                  (`claims_clip`, clip / photo nouns, `asked_count`) -> paid, or free when the
                                  text says "free"; else chat. Rows without `script_step` are not in the run.
  effective(row) -> row           `operator_overrides_json` laid over `fields` by key (`vault_ai_effective`
                                  precedence), except `_jev`: its override holds Jev picks `vault_jev_manual`
                                  already materialised into the stored `_jev`, so the stored `_jev` stays whole.
  fillable(item, *, account_id, standard_folders) -> reason | None   the Fillable item check over an
                                  `effective` row; an item whose `account_id` is missing or another
                                  Creator's is `not_mine`.
  fillable_rows(items, *, account_id, standard_folders) -> [row]   the Fillable ones, input order, each
                                  with a `why` derived from its fields (a carried one is never read). The
                                  one filter: `plan` gates with it itself, always; `plan_over_vault` before
                                  building Shoots.
  build_shoots(items, dupe_groups, kept_ids, prints) -> [Shoot]   `fillable_rows` -> `collapse_dupes` (a kept
                                  id is its dupe set's keeper) -> `vault_scripts.collect_outfit_scripts`
                                  (min_items=1, min_videos=0, require_escalation=False). That coroutine
                                  awaits nothing when given rows and prints, so it is driven synchronously.
  plan(rows, shoots, items, used_ids, dupe_groups, coverage, blocked_reason, *, account_id,
       template_prices=None, ...) -> FillPlan
  plan_over_vault(rows, items, used_ids, dupe_groups, prints, coverage, blocked_reason, *, account_id,
       standard_folders=True, live_ids=None, template_prices=None) -> FillPlan   `fillable_rows` ->
                                  `build_shoots` -> `plan` in one `vault_ai_brief.reading_memo()` (the second
                                  gate costs memo hits): the one pipeline, called by the route loader and
                                  `plan_from_vault`.
  plan_from_vault(sequence_rows, vault_rows, folder_prices, *, account_id, ...) -> FillPlan   offline entry.
  sequence_media_ids(rows) -> {id}  media and preview ids on Sequence rows (`used_ids` from other Sequences).
  asks(text) -> {ask}              what a step text asks to see (Assignment, D4); answers(fields) -> {ask}
                                  the asks an item's reading answers.
  writes(options) -> [write]       the write set of a plan's Options (below); `plan` and `fill/apply` use it.
  fingerprint(rows, writes) -> str; undo_check(row, entry, sequence) -> ok | edited | moved | missing.
  DESCRIBE_TARGET                 re-exported from `vault_ai_vision_decide`.

Input shapes (plain dicts):

  Sequence row   `saved_replies` columns: id, script_id, script_step, text, notes, price_cents, media_json
                 (JSON text or a list of `{id, ...}` / ints), previews_json (JSON text or a list of ids).
  Vault item     `full_ai_sell.load_rows` row (media_id, kind, created_at, duration_seconds, fields — the
                 settled reading —, describe_status, score, refs, folder_cents) plus review_state and
                 operator_overrides_json and account_id (must equal the `account_id` passed); optional
                 removed_at (non-None = not live), needs_review (in the standard Needs Review folder).
  Shoot          a `vault_scripts.collect_outfit_scripts` dict (`items`, `overflow`, `near_dupes`, ranks).
  coverage       `vault_ai_vision_decide.coverage(...)` dict (described, goal, remaining, ...).

`plan_from_vault(sequence_rows, vault_rows, folder_prices, *, account_id, used_ids=(), dupe_groups=(),
prints=None, standard_folders=True, blocked_reason=None, target=DESCRIBE_TARGET, template_prices=None)` —
for an offline fit check over a DB copy, no relay:

  sequence_rows  the Sequence rows above (one `script_id`).
  vault_rows     every `vault_items` row of the Creator: media_id, account_id, kind, created_at (datetime or ISO text),
                 duration_seconds, describe_status, review_state, removed_at, operator_overrides_json, and
                 either `fields` (already settled) or `ai_fields_json` (settled here, as `_load_rows` does);
                 `refs` (iterable of "vf:<folder id>" / "of:<OF list id>", standard folders already dropped
                 when the switch is off) or a ready `folder_cents`; optional `needs_review`.
  folder_prices  {ref: cents} (`vault_folder_prices.load`); a row's folder_cents = the highest of its refs.
  used_ids       media ids on the Creator's other Sequences; dupe_groups = `vault_dupes` sets (ids, original
                 first; disjoint, as `vault_dupes.cluster` claims each id once); prints = stored thumb hashes
                 by media id ({} = no near-dupe collapse).
  Coverage is computed from the live photo / video rows with `target`.

`plan` writes (fingerprinted, and what `fill/apply` writes) are `{id, media, previews, price_cents}` per empty
media-Role Option that got a Slice; `price_cents` is None unless Fill set it (the Undo list's `price_set`).

Assignment (issue 16 + its review amendments A1-A5). Empty media Options sharing (Step, Role, wants) share a
Slice. Kept media (and their dupe sets) are reserved.
  Pool     every Fillable item of the Creator on a Rung, one per dupe set (the copy a Shoot lists) and near-dupes
           dropped, in `vault_scripts._script_sort_key` order. Shoots are only a coherence signal.
  Paid     photos (the asked count 1-4, one Rung, one Shoot) then one clip, both locked, clip last in `media`; a
           clip ask gets the clip alone. Photos are placed first, then clips. No clip left -> photos only and
           Option flag `no_video`; with too few clips the earliest Steps go without. A Step's price never limits
           its clip (A4 withdrawn).
  Escalate Per kind, the last Step's Slice takes the top of the pool, and earlier Slices ascend below it, each
           from its even share under a forward lookahead (every later Slice must still fit).
  Asks     `asks(text)` (word lexicon; an ask word within 4 words after not / no / don't / won't / never / yet /
           later / soon / without is dropped). Inside a Step's window the pick answering the most asks wins:
           preference only, never a floor lift (D4 lift withdrawn). A Slice whose locked media answer none of its
           asks gets Option flag `ask_unmet`.
  Ties     window order = (clips: not the photos' Shoot, A2b) > asks answered > not the previous Step's
           Shoot (A2c) > send order. The last Step's top pick is never moved by a tie.
  Others   items on the Creator's other Sequences (`used_ids`) are tried last per kind: placement runs on the
           rest first and over everything only if that fails (D6, soft; A5).
  Free     a free Slice takes the lowest free-safe photo (others' items last); unfilled -> `free_unfilled`.
  Previews every paid Slice holding photos, clip or not, gets one leftover free-safe photo first, preferring
           the photos' Shoot (A1); a clip-only Slice gets none.
ASSUMPTION (issue 16 D8): a word lexicon reads AE's sexting captions well enough; no LLM. Overturned by a re-fill
showing `ask_unmet` or wrong picks on steps a person would match.

Price of a paid Option Fill fills, first that applies:
  (a) saved price > 0 on the row: Fixed, never changed;
  (b) the one amount its text quotes: unclamped, a bound like a Fixed price;
  (c) `template_prices[script_step]` ({step: cents}, what the same Agency saved on the same-named Sequence
      of another Creator; the route loader supplies it) when within $3-$200: unclamped, a bound like a quote
      (a conflict names it `quote_unholdable`), Option flag `template_price`; out of range it is ignored;
  (d) its Slice's List price, clamped into [lo, hi] by the Escalation rule; when that List price would not
      climb above lo (the highest earlier paid price), it is first raised to the ladder price
      ceil_dollar(lo x 1.5), capped at $200 (and at hi), so successive List-priced Steps never sit flat:
      $10 / $10 / $10 / $10 List -> $10, $15, $23, $35.
ASSUMPTION: the ladder lifts only a List price that would sit at or under lo, and from any earlier paid
price (Fixed, quoted, template or set); a List price already above lo is kept (coordinator requirement
2026-11-21, live data: an unpriced 8-paid-Step Sequence planned flat at $10). Overturned by the owner naming
a different ladder (step factor, rounding, or "always x 1.5").
ASSUMPTION: a template price that descends against a Fixed or quoted one refuses with `price_conflict`
(`quote_unholdable`), as a quote would, rather than being dropped for the List price (coordinator: "treated
as a bound like a quoted amount"). Overturned if the owner wants template prices to yield to a conflict.

ASSUMPTION: price range and Escalation checks read `paid_media` Options only; a priced `no content` lock (Role
chat) is neither checked nor a bound (rung 5: Fill validates what it writes, ADR-0046). Overturned if the owner
wants a $2 `no content` lock to refuse the Fill.
ASSUMPTION: a photo Slice holds exactly its asked count (1-4) of one Rung, never fewer (rung 3: `claim_ok`
refuses a text whose count the media does not match). Overturned if the fit check shows count asks refusing.
ASSUMPTION: `gap` is a missing step number between two present ones; a Sequence starting above 1 is not one
(rung 5). Overturned if chat suggestions also need step 1.
"""
from __future__ import annotations

import bisect
import functools
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

import vault_ai_brief
import vault_folder_prices
import vault_jev_rules
import vault_scripts
import vault_topic_folders as vtf
from automations import full_ai_sell as fs
from automations._reserved_scripts import is_reserved_name
from jsonsafe import load_json
from vault_ai_vision_decide import DESCRIBE_TARGET, coverage as _coverage

__all__ = ["DESCRIBE_TARGET", "roles", "effective", "fillable", "fillable_rows", "build_shoots", "plan",
           "plan_over_vault", "plan_from_vault", "sequence_media_ids", "writes", "fingerprint", "undo_check"]

CHAT, FREE, PAID = "chat", "free_media", "paid_media"
MAX_PHOTOS = 4
MIN_PRICE_CENTS = 300        # OnlyFans' $3 floor (`app/lib/sendGuards.ts`)
MAX_PRICE_CENTS = 20000      # $200

_NO_CONTENT = re.compile(r"\bno\s+content\b", re.I)
_PPV = re.compile(r"\bppv\b", re.I)
_FREEBIE = re.compile(r"\bfreebie\b", re.I)
_BRIDGE = re.compile(r"\bbridge\b", re.I)
_JEV_HELD = vault_jev_rules.HELD
_STANDARD_TIER = "explicitness_tier"   # the editor's override key (`vault_ai_api._EDITABLE_FIELDS`)


# ── Roles ─────────────────────────────────────────────────────────────

def _amounts(text: str) -> set[int]:
    """Every positive amount the text names, in cents (`price_ok`'s pattern)."""
    return {c for a, b in fs._AMOUNT.findall(text or "") if (c := round(float(a or b) * 100)) > 0}


def quote_cents(text: str) -> int | None:
    """The one amount the text quotes, or None (none, or several different ones).
    ASSUMPTION: several different amounts quote nothing (the Option is priced at List price). Overturned if
    AE step texts name two amounts and the owner wants one of them read."""
    got = _amounts(text)
    return next(iter(got)) if len(got) == 1 else None


def _cues(text: str) -> tuple[str, int | None, bool]:
    """(wants, asked count, a format / count promise) from the step text."""
    words = set(fs._words(text or ""))
    clip = fs.claims_clip(text or "") or bool(words & fs._VID_NOUNS)
    photo = bool(words & fs._PIC_NOUNS)
    count = fs.asked_count(text or "")
    wants = "any" if clip == photo else "clip" if clip else "photo"
    return wants, count, clip or photo or count is not None


def _role(row: Mapping[str, Any]) -> dict[str, Any]:
    notes, text = str(row.get("notes") or ""), str(row.get("text") or "")
    price = int(row.get("price_cents") or 0)
    wants, count, promise = _cues(text)

    def paid() -> dict[str, Any]:
        n = 1 if wants == "clip" else min(MAX_PHOTOS, count or 1)
        return {"role": PAID, "wants": wants, "count": n, "flags": []}

    free = {"role": FREE, "wants": "photo", "count": 1, "flags": []}
    chat = {"role": CHAT, "wants": None, "count": 0, "flags": []}
    if _NO_CONTENT.search(notes):
        return {**chat, "flags": ["lock_no_content"]}
    if price > 0 or _PPV.search(notes):
        return paid()
    if _FREEBIE.search(notes):
        return free
    if _BRIDGE.search(notes):
        return chat
    if _amounts(text):
        return paid()
    if promise:
        return free if fs._FREE.search(text) else paid()
    return chat


def _in_run(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted((r for r in rows if r.get("script_step") is not None),
                  key=lambda r: (int(r["script_step"]), int(r["id"])))


def roles(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """{id: Role} over the Sequence rows that carry a `script_step`."""
    return {int(r["id"]): _role(r) for r in _in_run(rows)}


# ── Fillable items ────────────────────────────────────────────────────

def effective(row: Mapping[str, Any]) -> dict[str, Any]:
    """`row` with its operator overrides laid over `fields` by key, `_jev` excepted (module docstring).
    ASSUMPTION: an `explicitness_tier` override (the editor's tier key) also sets `explicitness`, the key
    `sellability` reads the Rung from, so an operator's tier edit moves the Rung. Overturned if the tier
    override is meant to touch only the column."""
    ov = row.get("operator_overrides_json")
    ov = load_json(ov, {}) if isinstance(ov, (str, bytes)) else ov
    fields = dict(row.get("fields") or {})
    for k, v in (ov if isinstance(ov, dict) else {}).items():
        if k == vault_jev_rules.JEV_KEY:
            continue
        fields[k] = v
        if k == _STANDARD_TIER and v:
            fields["explicitness"] = v
    out = {k: v for k, v in row.items() if k != "why"}
    return {**out, "fields": fields, "score": vault_scripts.escalation_score(fields)}


def fillable(item: Mapping[str, Any], *, account_id: str, standard_folders: bool = True) -> str | None:
    """None when a Fill may use `item` (an `effective` row), else the first reason it may not:
    not_live, not_described, not_mine (`account_id` missing or another Creator's), not_solo, no_rung, held,
    jev_review, rejected, review_folder, unpriced_dispute. `review_folder` only while the Creator's
    `standard_folders` switch is on (off, Needs Review keeps nothing from sale, `vault_settings`)."""
    return _gate(item, account_id, standard_folders)[0]


def _gate(item: Mapping[str, Any], account_id: str, standard_folders: bool
          ) -> tuple[str | None, Mapping[str, Any] | None]:
    """(`fillable` reason, the row with its script `why`, or None when a reason came before it). The `why`
    is always derived here from the row's fields (one an item carries in is replaced, never read); it holds
    `sellability(fields)["solo"]` (`send_order_reason`). Inside `reading_memo` a second gate over the same
    fields costs memo hits."""
    if item.get("removed_at") is not None:
        return "not_live", None
    if item.get("describe_status") != "described":
        return "not_described", None
    if not account_id or item.get("account_id") != account_id:
        return "not_mine", None
    r = vault_scripts._with_script_why(item)     # {**item, "why": fresh}
    why = r["why"]
    jev = (item.get("fields") or {}).get(vault_jev_rules.JEV_KEY)
    jev = jev if isinstance(jev, dict) else {}
    if why["solo"] is not True:
        reason = "not_solo"
    elif why["rung"] is None:
        reason = "no_rung"
    elif jev.get("review") == _JEV_HELD:
        reason = "held"
    elif jev.get("lane5") == "review":
        reason = "jev_review"
    elif item.get("review_state") == "rejected":
        reason = "rejected"
    elif standard_folders and item.get("needs_review"):
        reason = "review_folder"
    elif vault_scripts._unpriced_dispute(r):
        reason = "unpriced_dispute"
    else:
        reason = None
    return reason, r


def fillable_rows(items: Iterable[Mapping[str, Any]], *, account_id: str,
                  standard_folders: bool = True) -> list[dict[str, Any]]:
    """The Fillable rows of `items` (`effective` rows), input order, each with its script `why`."""
    out = []
    for item in items:
        reason, r = _gate(item, account_id, standard_folders)
        if reason is None:
            out.append(r)
    return out


def _run_sync(coro: Any) -> Any:
    """Drive a coroutine that awaits nothing (`collect_outfit_scripts` given rows and prints)."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError("collect_outfit_scripts suspended: rows and prints must be passed")


def build_shoots(items: Iterable[Mapping[str, Any]], dupe_groups: Iterable[Iterable[int]] = (),
                 kept_ids: Iterable[int] = (), prints: Mapping[int, Any] | None = None) -> list[dict[str, Any]]:
    """The Shoots of these Fillable rows, best first (`shoot_rank_key`). A kept id stands for its dupe set,
    so the Shoot holding it can still be found; kept ids are marked used later, in `plan`."""
    kept = {int(m) for m in kept_ids}
    groups = [sorted((int(m) for m in g), key=lambda m: (m not in kept, list(g).index(m)))
              for g in (list(g) for g in dupe_groups)]
    rows = [{k: v for k, v in r.items() if k != "why"} for r in items]
    rows, _ = vault_scripts.collapse_dupes(rows, groups)
    return _run_sync(vault_scripts.collect_outfit_scripts(
        "", rows=rows, prints=dict(prints or {}), min_items=1, min_videos=0, require_escalation=False))


# ── Sequence rows ─────────────────────────────────────────────────────

def _ids(raw: Any) -> list[int]:
    """Media ids from a `media_json` / `previews_json` value (JSON text or list; entries `{id}` or ids)."""
    got = load_json(raw, []) if isinstance(raw, (str, bytes)) else (raw or [])
    out = []
    for m in got if isinstance(got, list) else []:
        mid = m.get("id") if isinstance(m, dict) else m
        try:
            out.append(int(mid))
        except (TypeError, ValueError):
            continue
    return out


def _media(row: Mapping[str, Any]) -> list[int]:
    return _ids(row.get("media_json", row.get("media")))


def _previews(row: Mapping[str, Any]) -> list[int]:
    return _ids(row.get("previews_json", row.get("previews")))


def _gap(run: list[Mapping[str, Any]]) -> bool:
    steps = sorted({int(r["script_step"]) for r in run})
    return any(b - a > 1 for a, b in zip(steps, steps[1:]))


# ── Fingerprint and undo ──────────────────────────────────────────────

def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(rows: Iterable[Mapping[str, Any]], writes: Iterable[Mapping[str, Any]]) -> str:
    """SHA-256 over each Sequence row's (id, step, text, notes, price_cents, media ids, previews) and the
    plan's writes ({id, media, previews, price_cents | None})."""
    read = sorted(([int(r["id"]), r.get("script_step"), r.get("text") or "", r.get("notes") or "",
                    int(r.get("price_cents") or 0), _media(r), _previews(r)] for r in rows),
                  key=lambda x: x[0])
    wrote = sorted((dict(w) for w in writes), key=lambda w: int(w["id"]))
    return hashlib.sha256(_canon({"rows": read, "writes": wrote}).encode()).hexdigest()


def undo_check(row: Mapping[str, Any] | None, entry: Mapping[str, Any], sequence: str) -> str:
    """One Undo list entry against the row as it is now (None: not this account's, or gone): `missing`,
    `moved` (another Sequence), `edited` (media ids, previews or price differ from the entry; a Fixed
    price edited after the Fill counts), else `ok`."""
    if row is None:
        return "missing"
    if row.get("script_id") != sequence:
        return "moved"
    if (_media(row) != [int(m) for m in entry.get("media_ids") or []]
            or _previews(row) != [int(m) for m in entry.get("previews") or []]
            or int(row.get("price_cents") or 0) != int(entry.get("price_cents") or 0)):
        return "edited"
    return "ok"


# ── Assignment ────────────────────────────────────────────────────────

class _Dupes:
    """`fs.expand_owned` over disjoint dupe sets (`vault_dupes.cluster` claims each id once), by an
    {id: set} lookup: `expand(ids)` = the ids plus every copy in their sets."""

    def __init__(self, groups: list[list[int]]):
        self.of = {int(m): g for g in groups for m in g}

    def expand(self, owned: Iterable[int]) -> set[int]:
        out: set[int] = set()
        for m in owned:
            out.update(self.of.get(int(m), (int(m),)))
        return out


def _list_cents(item: Mapping[str, Any]) -> int | None:
    fields = item.get("fields") or {}
    return fs.list_price_cents(vtf.jev_of(fields), fields, item["kind"], item.get("folder_cents"))


def _free_safe(item: Mapping[str, Any], cents: int | None) -> bool:
    jev = vtf.jev_of(item.get("fields") or {})
    return item["kind"] == "photo" and cents == 0 and jev is not None and vtf.free_ok(jev)


_ASK_PHRASES = {   # ask -> words / phrases of the step text (D4); matched on lowercase word tokens
    "genitals": ("pussy", "pussies", "cunt", "clit", "clitoris", "vagina", "slit", "spread", "spreading",
                 "spreads", "hole", "holes"),
    "nude": ("naked", "nude", "nudes", "nothing on", "take it all off", "taking it all off", "everything off",
             "panties off", "strip", "stripping"),
    "breasts": ("tits", "titties", "boobs", "boob", "breasts", "nipples", "nipple", "bra off"),
    "ass": ("ass", "booty", "butt", "cheeks", "bent over", "bend over", "twerk", "twerking"),
    "act": ("finger", "fingers", "fingering", "toy", "toys", "dildo", "vibrator", "ride", "riding", "bounce",
            "bouncing", "cum", "cumming", "squirt", "squirting"),
}
_ASK_TOKENS = [(ask, tuple(phrase.split())) for ask, phrases in _ASK_PHRASES.items() for phrase in phrases]
_NEGATORS = frozenset({"not", "no", "dont", "wont", "never", "yet", "later", "soon", "without"})
_NEGATION_REACH = 4


def asks(text: str) -> set[str]:
    """What the step text asks to see: a subset of genitals / nude / breasts / ass / act (`_ASK_PHRASES`).
    An ask word within 4 words after a negation or deferral word (`_NEGATORS`) is dropped."""
    toks = [t.replace("'", "") for t in re.findall(r"[a-z]+(?:'[a-z]+)?",
                                                    str(text or "").lower().replace("\u2019", "'"))]
    out: set[str] = set()
    for i in range(len(toks)):
        if _NEGATORS & set(toks[max(0, i - _NEGATION_REACH):i]):
            continue
        for ask, phrase in _ASK_TOKENS:
            if tuple(toks[i:i + len(phrase)]) == phrase:
                out.add(ask)
    return out


def _shows_ass(fields: Mapping[str, Any]) -> bool:
    if vault_scripts._focus(dict(fields)) & {"ass", "butt"}:
        return True
    if vault_scripts._norm(fields.get("primary_folder")).startswith(("ass", "butt")):
        return True
    tags = [vault_scripts._norm(t) for t in fields.get("tags") or [] if isinstance(t, str)]
    return any(t.startswith(("ass", "butt")) for t in tags)


def answers(fields: Mapping[str, Any]) -> frozenset[str]:
    """The asks an item answers, read by `vault_scripts`' readers (ass: body focus / tags / primary folder)."""
    f = dict(fields or {})
    return frozenset(ask for ask, hit in (
        ("genitals", vault_scripts._shows_genitals(f)), ("nude", vault_scripts._is_nude(f)),
        ("breasts", vault_scripts._shows_breasts_bare(f)), ("ass", _shows_ass(f)),
        ("act", vault_scripts._has_payoff_act(f))) if hit)


def _slices(opts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(paid Slices, free Slices) to place: one per (Step, Role, wants) over empty media Options. A Slice's
    `asks` = its Options' texts' asks."""
    by: dict[tuple, dict[str, Any]] = {}
    for o in opts:
        if o["keep"] or o["role"] not in (FREE, PAID):
            continue
        key = (o["step"], o["role"], o["wants"])
        s = by.setdefault(key, {"step": o["step"], "role": o["role"], "wants": o["wants"], "count": 0,
                                "options": [], "asks": set()})
        s["count"] = max(s["count"], o["count"])
        s["options"].append(o["id"])
        s["asks"] |= asks(o["text"])
    ordered = sorted(by.values(), key=lambda s: (s["step"], s["options"][0]))
    return [s for s in ordered if s["role"] == PAID], [s for s in ordered if s["role"] == FREE]


def _track(cands: list[int], slices: list[dict[str, Any]], ks: list[int], taken: set[int], dx: _Dupes, *,
           count: Callable[[int], int], group: Callable[[int], Any],
           must: Callable[[int], bool], shoot: Callable[[int], Any], answers: Callable[[int], frozenset],
           first_pref: Callable[[int, int], bool]) -> dict[int, list[int]] | None:
    """One kind's picks: {slice index: media ids} for the Slices `ks` (indices into `slices`, step order) over
    `cands` (one kind's ids, send order), or None when a `must` Slice cannot be placed. A pick is `count(k)`
    items of one `group` (photos: one Rung of one Shoot). The last Step's Slices take the top; earlier Slices
    ascend below it, each from its even share, preferring (first_pref, asks answered, the previous Step's
    Shoot, send order), under a forward lookahead. A non-`must` Slice that leaves the rest no room is
    dropped, earliest first (absent from the result). `taken` is read, never changed."""
    n_of = {k: count(k) for k in ks}
    groups: dict[Any, list[int]] = {}
    for p, m in enumerate(cands):
        groups.setdefault(group(m), []).append(p)

    def free(k: int, q: int, used: set[int]) -> bool:
        return cands[q] not in used

    def at(k: int, p: int, used: set[int], hi: int) -> list[int] | None:
        if not free(k, p, used):
            return None
        g = groups[group(cands[p])]
        got = []
        for q in g[bisect.bisect_left(g, p):]:
            if q >= hi:
                break
            if free(k, q, used):
                got.append(q)
                if len(got) == n_of[k]:
                    return got
        return None

    def first(k: int, start: int, used: set[int], hi: int) -> list[int] | None:
        return next((g for p in range(start, hi) if (g := at(k, p, used, hi)) is not None), None)

    def fits(ks: list[int], start: int, used: set[int], hi: int) -> bool:
        used = set(used)
        for k in ks:
            g = first(k, start, used, hi)
            if g is None:
                return False
            used |= dx.expand(cands[q] for q in g)
            start = max(g) + 1
        return True

    def asked(k: int, g: list[int]) -> set[str]:
        got: set[str] = set()
        for q in g:
            got |= answers(cands[q])
        return slices[k]["asks"] & got

    taken = set(taken)
    out: dict[int, list[int]] = {}
    last_step = max((slices[k]["step"] for k in ks), default=None)
    bound = len(cands)
    for k in [k for k in ks if slices[k]["step"] == last_step]:
        got = None
        for p in range(len(cands) - 1, -1, -1):   # the top: the group whose highest free item sorts last
            if not free(k, p, taken):
                continue
            g = [q for q in groups[group(cands[p])] if q <= p and free(k, q, taken)][-n_of[k]:]
            if len(g) == n_of[k]:
                got = g
                break
        if got is None:
            if must(k):
                return None
            continue
        taken |= dx.expand(cands[q] for q in got)
        out[k] = [cands[q] for q in got]
        bound = min(bound, min(got))
    need = [k for k in ks if slices[k]["step"] != last_step]
    while not fits(need, 0, taken, bound):
        drop = next((k for k in need if not must(k)), None)
        if drop is None:
            return None
        need.remove(drop)
    cursor, prev = 0, None
    for idx, k in enumerate(need):
        rest = need[idx + 1:]
        target, nxt = idx * bound // len(need), (idx + 1) * bound // len(need)
        floor = max(cursor, target)
        end = max(nxt, floor + 1)

        def passes(g: list[int]) -> bool:
            return fits(rest, max(g) + 1, taken | dx.expand(cands[q] for q in g), bound)

        window = sorted(((first_pref(k, cands[g[0]]), -len(asked(k, g)), shoot(cands[g[0]]) != prev, g[0]), g)
                        for p in range(floor, min(end, bound)) if (g := at(k, p, taken, bound)) is not None)
        got = next((g for _, g in window if passes(g)), None)
        for start in dict.fromkeys((floor, cursor)):
            if got is None and (g := first(k, start, taken, bound)) is not None and passes(g):
                got = g
        if got is None:
            return None
        taken |= dx.expand(cands[q] for q in got)
        out[k] = [cands[q] for q in got]
        cursor, prev = max(got) + 1, shoot(cands[got[0]])
    return out


def _assign(pool: list[dict[str, Any]], paid_slices: list[dict[str, Any]], free_slices: list[dict[str, Any]],
            reserved: set[int], elsewhere: set[int], dx: _Dupes, cents: Callable[[int], int | None],
            shoot_of: Mapping[int, int], answers: Callable[[int], frozenset], need_free: bool
            ) -> dict[int, dict[str, Any]] | None:
    """{slice index: {media, previews, no_video}} over the pool (Fillable, one per dupe set, send order), or
    None when a paid Slice cannot be placed (or, `need_free`, a free one). Paid Slices are indexed 0.., free
    ones after them; a free Slice left empty (second pass) is absent. Each kind runs on the items not on other
    Sequences first, then on all (module docstring › Assignment)."""
    taken = set(reserved)

    def take(ids: Iterable[int]) -> None:
        taken.update(dx.expand(ids))

    def shoot(m: int) -> Any:
        return shoot_of.get(m, ("item", m))

    rung = {r["media_id"]: r["why"]["rung"] for r in pool}
    paid = [r["media_id"] for r in pool if (cents(r["media_id"]) or 0) > 0]
    kind = {r["media_id"]: r["kind"] for r in pool}
    photos = [m for m in paid if kind[m] == "photo"]
    videos = [m for m in paid if kind[m] == "video"]

    def runs(cands: list[int], ks: list[int], **kw: Any) -> list[dict[int, list[int]] | None]:
        fresh = [m for m in cands if m not in elsewhere]
        return [_track(c, paid_slices, ks, taken, dx, shoot=shoot, answers=answers, **kw)
                for c in ([fresh, cands] if len(fresh) < len(cands) else [cands])]

    with_photos = [k for k, s in enumerate(paid_slices) if s["wants"] != "clip"]
    pic = next((g for g in runs(photos, with_photos, count=lambda k: paid_slices[k]["count"],
                                group=lambda m: (rung[m], shoot(m)),
                                must=lambda k: True, first_pref=lambda k, m: False) if g is not None), None)
    if pic is None:
        return None
    for ids in pic.values():
        take(ids)
    vid = None
    for g in runs(videos, list(range(len(paid_slices))), count=lambda k: 1, group=lambda m: m,
                  must=lambda k: paid_slices[k]["wants"] == "clip",
                  first_pref=lambda k, m: k in pic and shoot(m) != shoot(pic[k][0])):
        if g is not None and (vid is None or len(g) > len(vid)):
            vid = g
    if vid is None:
        return None
    for ids in vid.values():
        take(ids)
    out: dict[int, dict[str, Any]] = {
        i: {"media": [*pic.get(i, []), *vid.get(i, [])], "previews": [],
            "no_video": i not in vid} for i in range(len(paid_slices))}
    pos = {r["media_id"]: i for i, r in enumerate(pool)}
    free = sorted((r["media_id"] for r in pool if _free_safe(r, cents(r["media_id"]))),
                  key=lambda m: (m in elsewhere, pos[m]))
    for k, s in enumerate(free_slices):
        m = next((m for m in free if m not in taken), None)
        if m is None:
            if need_free:
                return None
            continue
        take([m])
        out[len(paid_slices) + k] = {"media": [m], "previews": [], "no_video": False}
    for i, ids in sorted(pic.items()):   # A1: a Slice holding photos gets a free-safe preview, video or not
        own = shoot(ids[0])
        m = min((m for m in free if m not in taken), key=lambda m: (m in elsewhere, shoot(m) != own, pos[m]),
                default=None)
        if m is None:
            break
        take([m])
        out[i] = {**out[i], "media": [m, *out[i]["media"]], "previews": [m]}
    return out


# ── Pricing ───────────────────────────────────────────────────────────

def _range_rule(cents: int) -> str | None:
    if 0 < cents < MIN_PRICE_CENTS:
        return "under_min"
    if cents > MAX_PRICE_CENTS:
        return "over_max"
    return None


def _bounds(opts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Paid Options carrying a bound: a Fixed price, or a quote on an Option Fill would price."""
    return [o for o in opts if o["role"] == PAID and o["bound"] is not None]


def _price_precheck(opts: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    bounds = _bounds(opts)
    for o in bounds:
        if (rule := _range_rule(o["bound"])) is not None:
            return "price_out_of_range", {"step": o["step"], "rule": rule, "price_cents": o["bound"]}
    for b in bounds:
        for a in bounds:
            if a["step"] < b["step"] and a["bound"] > b["bound"]:
                if b["quoted"]:
                    return "price_conflict", {"step": b["step"], "rule": "quote_unholdable", "price_cents": b["bound"]}
                if a["quoted"]:
                    return "price_conflict", {"step": a["step"], "rule": "quote_unholdable", "price_cents": a["bound"]}
                return "price_conflict", {"step": b["step"], "rule": "below_earlier", "price_cents": b["bound"]}
    return None


def _ladder(lo: int) -> int:
    """lo x 1.5 rounded up to the next whole dollar, capped at $200 (module docstring, price (d))."""
    return min(MAX_PRICE_CENTS, -(-lo * 3 // 200) * 100)


def _set_prices(opts: list[dict[str, Any]], slice_cents: Mapping[int, int]
                ) -> tuple[dict[int, int], dict[str, Any] | None]:
    """({option id: cents}, None) for every new paid Option (`slice_cents`: its Slice's List price by option
    id) under the Escalation rule and the ladder, walking Steps upward; ({}, conflict) when lo > hi."""
    paid = [o for o in opts if o["role"] == PAID]
    price = {o["id"]: o["price_cents"] for o in paid}
    out: dict[int, int] = {}
    for step in sorted({o["step"] for o in paid}):
        lo = max((price[o["id"]] for o in paid if o["step"] < step and price[o["id"]] > 0), default=0)
        hi = min((o["bound"] for o in paid if o["step"] > step and o["bound"] is not None),
                 default=MAX_PRICE_CENTS)
        for o in paid:
            if o["step"] != step or o["id"] not in slice_cents:
                continue
            if o["bound"] is not None:
                cents = o["bound"]
            elif lo > hi:
                return {}, {"step": step, "rule": "below_earlier", "price_cents": slice_cents[o["id"]]}
            else:
                cents = slice_cents[o["id"]]
                if lo and cents <= lo:
                    cents = _ladder(lo)
                cents = min(max(cents, lo), hi)
            price[o["id"]] = out[o["id"]] = cents
    return out, None


# ── Plan ──────────────────────────────────────────────────────────────

def _option_list(run: list[Mapping[str, Any]], rl: Mapping[int, dict[str, Any]],
                 live: set[int], template: Mapping[int, int]) -> list[dict[str, Any]]:
    seen: dict[int, int] = {}
    out = []
    for r in run:
        rid, step = int(r["id"]), int(r["script_step"])
        seen[step] = seen.get(step, 0) + 1
        role = rl[rid]
        media, previews = _media(r), _previews(r)
        price = int(r.get("price_cents") or 0)
        keep = bool(media)
        flags = list(role["flags"])
        if keep:
            flags.append("kept_existing")
            if role["role"] == PAID and price == 0:
                flags.append("kept_unpriced")
            if any(m not in live for m in media):
                flags.append("removed_media")
        new_unpriced = role["role"] == PAID and price == 0 and not keep
        bound = quote_cents(str(r.get("text") or "")) if new_unpriced else None
        if new_unpriced and bound is None and MIN_PRICE_CENTS <= template.get(step, 0) <= MAX_PRICE_CENTS:
            bound = template[step]
            flags.append("template_price")
        # `quoted`: a quote or template bound (Fill sets it; a conflict over it is `quote_unholdable`)
        out.append({"id": rid, "step": step, "option": seen[step], "role": role["role"], "wants": role["wants"],
                    "text": str(r.get("text") or ""),
                    "count": role["count"], "keep": keep, "media": media, "previews": previews,
                    "price_cents": price, "price_fixed": price > 0, "flags": flags,
                    "bound": price if price > 0 else bound, "quoted": price == 0 and bound is not None})
    return out


_PUBLIC = ("id", "step", "option", "role", "wants", "keep", "media", "previews", "price_cents", "price_fixed",
           "flags")


def plan(rows: Iterable[Mapping[str, Any]], shoots: Iterable[Mapping[str, Any]],
         items: Iterable[Mapping[str, Any]], used_ids: Iterable[int] = (),
         dupe_groups: Iterable[Iterable[int]] = (), coverage: Mapping[str, Any] | None = None,
         blocked_reason: str | None = None, *, account_id: str, standard_folders: bool = True,
         live_ids: Iterable[int] | None = None, template_prices: Mapping[int, int] | None = None
         ) -> dict[str, Any]:
    """The Fill plan for one Sequence (`rows`). `items`: the Creator's live vault rows (or their
    `fillable_rows`, then with `live_ids`), `effective` already; Fill gates each with `fillable_rows` itself,
    whatever `shoots` and `items` hold; `shoots` from `build_shoots`;
    `used_ids`: media on the Creator's other Sequences; `live_ids`: every live media id (default: `items`'
    ids), for `removed_media`; `template_prices`: {script_step: cents} (module docstring, price (c)).
    FillPlan = {status, options, flags, conflict, describe, fingerprint} (spec › Contracts)."""
    rows = list(rows)
    groups = [[int(m) for m in g] for g in dupe_groups]
    items = list(items)
    live = {int(m) for m in live_ids} if live_ids is not None else {int(r["media_id"]) for r in items}
    run = _in_run(rows)
    template = {int(k): int(v) for k, v in (template_prices or {}).items()}
    opts = _option_list(run, roles(run), live, template)
    cov = dict(coverage or {})
    remaining = int(cov.get("remaining") or 0)
    describe = {"described": int(cov.get("described") or 0), "target": int(cov.get("goal") or 0),
                "remaining": remaining, "can_describe": remaining > 0 and not blocked_reason,
                "blocked_reason": blocked_reason}
    flags = ["gap"] if _gap(run) else []

    def done(status: str, conflict: dict[str, Any] | None = None,
             writes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        writes = writes or []
        return {"status": status, "options": [{k: o[k] for k in _PUBLIC} for o in opts], "flags": flags,
                "conflict": conflict, "describe": describe, "fingerprint": fingerprint(rows, writes)}

    script_id = next((r.get("script_id") for r in run if r.get("script_id")), None)
    if script_id and is_reserved_name(str(script_id)):
        return done("reserved")
    if not any(o["role"] == PAID for o in opts):
        return done("no_paid_steps")
    if all(o["keep"] for o in opts if o["role"] in (FREE, PAID)):
        return done("already_filled")
    if (pre := _price_precheck(opts)) is not None:
        return done(*pre)

    pool = {int(r["media_id"]): r for r in fillable_rows(items, account_id=account_id,
                                                          standard_folders=standard_folders)}
    cents = functools.cache(lambda m: _list_cents(pool[m]))   # {media id: List price}, each derived once
    kept = [m for o in opts if o["keep"] for m in (*o["media"], *o["previews"])]
    dx = _Dupes(groups)
    reserved = dx.expand(kept)
    elsewhere = dx.expand(used_ids)
    paid_slices, free_slices = _slices(opts)
    shoot_of: dict[int, int] = {}
    near: set[int] = set()
    for n, sh in enumerate(shoots):
        for m in [int(r["media_id"]) for r in sh.get("items") or []] + [int(m) for m in sh.get("overflow") or []]:
            shoot_of.setdefault(m, n)
        near.update(int(m) for m in sh.get("near_dupes") or [])
    seen: set[int] = set()
    rows_in = []
    for r in sorted((r for m, r in pool.items() if m not in near and r["why"]["rung"] is not None),
                    key=lambda r: (int(r["media_id"]) not in shoot_of, vault_scripts._script_sort_key(r))):
        if int(r["media_id"]) not in seen:   # one per dupe set: the copy a Shoot lists, else the first sent
            seen |= dx.expand([r["media_id"]])
            rows_in.append(r)
    ordered = sorted(rows_in, key=vault_scripts._script_sort_key)
    reads = functools.cache(lambda m: answers(pool[m]["fields"]))

    got = None
    for need_free in (True, False):
        got = _assign(ordered, paid_slices, free_slices, reserved, elsewhere, dx, cents, shoot_of, reads,
                      need_free)
        if got is not None:
            break
    if got is None:
        if paid_slices:
            return done("not_enough_content" if remaining > 0 else "no_fit")
        got = {}   # nothing paid to place and no free-safe photo: every free Slice unfilled

    by_opt = {o["id"]: o for o in opts}
    picks: dict[int, dict[str, Any]] = {}
    slice_cents: dict[int, int] = {}
    for i, s in enumerate([*paid_slices, *free_slices]):
        picked = got.get(i)
        for oid in s["options"]:
            if picked is None:
                by_opt[oid]["flags"].append("free_unfilled")
                continue
            picks[oid] = picked
            if s["role"] == PAID:
                locked = [m for m in picked["media"] if m not in picked["previews"]]
                slice_cents[oid] = min(MAX_PRICE_CENTS, max(cents(m) or 0 for m in locked))
                if picked["no_video"]:
                    by_opt[oid]["flags"].append("no_video")
                if s["asks"] and not s["asks"] & set().union(*(reads(m) for m in locked)):
                    by_opt[oid]["flags"].append("ask_unmet")
    prices, conflict = _set_prices(opts, slice_cents)
    if conflict is not None:
        return done("price_conflict", conflict)
    for oid, picked in picks.items():
        o = by_opt[oid]
        o["media"], o["previews"] = list(picked["media"]), list(picked["previews"])
        o["price_cents"] = prices.get(oid, o["price_cents"])
    wrote = writes(opts)
    if not wrote:
        return done("already_filled")
    return done("ok", writes=wrote)


def writes(options: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The write set of a plan's Options (`plan`'s internal ones or a FillPlan's `options`): one
    `{id, media, previews, price_cents}` per empty media-Role Option that got media; `price_cents` is None
    unless Fill set it (paid, no Fixed price)."""
    return [{"id": o["id"], "media": o["media"], "previews": o["previews"],
             "price_cents": o["price_cents"] if o["role"] == PAID and not o["price_fixed"] else None}
            for o in options if not o["keep"] and o["role"] in (FREE, PAID) and o["media"]]


def plan_over_vault(rows: Iterable[Mapping[str, Any]], items: Iterable[Mapping[str, Any]],
                    used_ids: Iterable[int] = (), dupe_groups: Iterable[Iterable[int]] = (),
                    prints: Mapping[int, Any] | None = None, coverage: Mapping[str, Any] | None = None,
                    blocked_reason: str | None = None, *, account_id: str, standard_folders: bool = True,
                    live_ids: Iterable[int] | None = None, template_prices: Mapping[int, int] | None = None
                    ) -> dict[str, Any]:
    """`plan` over the Creator's live vault (`items`: `effective` rows): `fillable_rows`, then `build_shoots`
    (the Sequence's kept media standing for their dupe sets), then `plan` over the Fillable rows, inside one
    `reading_memo`. `live_ids` defaults to every item's id (not only the Fillable ones), for `removed_media`.
    Both entries run a plan through here: the route loader and `plan_from_vault`."""
    rows = list(rows)
    items = list(items)
    groups = [[int(m) for m in g] for g in dupe_groups]
    live = [int(r["media_id"]) for r in items] if live_ids is None else live_ids
    kept = [m for r in _in_run(rows) for m in _media(r)]
    with vault_ai_brief.reading_memo():   # each item's reading derived once across gate, Shoots and plan
        fill = fillable_rows(items, account_id=account_id, standard_folders=standard_folders)
        shoots = build_shoots(fill, groups, kept, prints or {})
        return plan(rows, shoots, fill, used_ids, groups, coverage, blocked_reason, account_id=account_id,
                    standard_folders=standard_folders, live_ids=live, template_prices=template_prices)


def sequence_media_ids(rows: Iterable[Mapping[str, Any]]) -> set[int]:
    """Every media and preview id on these Sequence rows (`media_json` / `previews_json`, or `media` /
    `previews`): the `used_ids` `plan` takes, from the Creator's other Sequences."""
    return {m for r in rows for m in (*_media(r), *_previews(r))}


# ── Offline entry ─────────────────────────────────────────────────────

def _vault_row(r: Mapping[str, Any], folder_prices: Mapping[str, int]) -> dict[str, Any]:
    fields = r["fields"] if "fields" in r else vault_ai_brief.settled_reading(
        vault_ai_brief.load_fields(r.get("ai_fields_json")))
    created = r.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    refs = tuple(sorted(r.get("refs") or ()))
    folder = r["folder_cents"] if "folder_cents" in r else vault_folder_prices.highest(refs, dict(folder_prices))
    return {**r, "media_id": int(r["media_id"]), "created_at": created, "fields": fields or {},
            "refs": refs, "folder_cents": folder, "score": vault_scripts.escalation_score(fields or {})}


def plan_from_vault(sequence_rows: Iterable[Mapping[str, Any]], vault_rows: Iterable[Mapping[str, Any]],
                    folder_prices: Mapping[str, int], *, account_id: str, used_ids: Iterable[int] = (),
                    dupe_groups: Iterable[Iterable[int]] = (), prints: Mapping[int, Any] | None = None,
                    standard_folders: bool = True, blocked_reason: str | None = None,
                    target: int = DESCRIBE_TARGET, template_prices: Mapping[int, int] | None = None
                    ) -> dict[str, Any]:
    """`plan` from raw rows, for an offline fit check (inputs: module docstring)."""
    rows = list(sequence_rows)
    live = [_vault_row(r, folder_prices) for r in vault_rows if r.get("removed_at") is None]
    items = [effective(r) for r in live]
    cov = _coverage([(r.get("describe_status"), r["fields"]) for r in live if r.get("kind") in ("photo", "video")],
                    target)
    return plan_over_vault(rows, items, used_ids, dupe_groups, prints, cov, blocked_reason,
                           account_id=account_id, standard_folders=standard_folders,
                           template_prices=template_prices)
