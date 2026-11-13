"""vault_jev_manual.py — an operator's Jev picks (the vault item popup's "More info") laid over a `_jev`. Pure.

The picks live in `operator_overrides_json["_jev"]` ({key: value}, only the keys touched; a cleared key is removed)
and are the source of truth: `overlay` materialises them into the stored `_jev` (`vault_jev_rules.blob` shape), on
every write of it — the edit route, the Jev pass (`vault_jev_pass._stamp` / `_hold`, so a re-read keeps them) and a
duplicate's copy (`vault_ai_vision_decide.jev_for_copy`). Options are the Jev questions' own (`vault_jev.Q`).

  regions      breasts / crotch / butt: a `state_opts` answer → `state[r]`; breasts / crotch also set their verdict
               (`*_bare` y iff bare), butt only `tags.butt_bare` (never the lane)
  toggles      y / n: `tags[q]` + `P[q]` 1.0 / 0.0 (penetration: the `penetration` verdict)
  choices      `tags[q]`, one-hot `C[q]` for `FACT_CHOICES`, the collapsed tags + `*_any` lines re-derived
  feet         any feet toggle y → `feet_any` y, `feet_subject` 1.0, `feet_detail` never not_in_picture (else the
               pack picker damps the feet subject under its gate)
  lane         free / $10 / $50 / $100: wins, coerces the verdicts (free all n, $10 breasts y, $50 crotch y, $100
               penetration y) and clears a clip's `review` / `read_lane5`. Not picked: a breasts / crotch /
               penetration pick re-ranks the lane on the verdicts (pen y $100, crotch y $50, breasts y $10, an
               unsure left keeps the read lane, else free); `vault_jev_rules.lane_rule` needs probabilities.
  no reading   a lane (picked or ranked) builds a whole current blob (every FACT_CHOICES in `C`, uniform where not
               picked, so the flags / tier map it; Describe waits for the scan, `ai_read`); none: `status` "manual" (not current, the sweep still reads
               the item and its picks are laid over the reading).
  failed read  a reading whose re-read failed (status error / fetch_failed, fields kept) with a lane known after
               the picks (not a clip's review) is current again: `status` ok, so the flags map it.

Clearing a pick restores the reading: `overlay` records what it overwrote (`undo`: per path the value it wrote and
the one it replaced) and always starts from the blob with that undone, so it is idempotent and a pick removed later
gives the AI's answer back. A path some other writer changed since (a clip hold's `lane5` review) is left alone.
Stamped: `op` (the picked keys), `ai` (the reading's value of each picked key, for the popup), `made` "manual" on a
blob built without a reading.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Mapping

import vault_jev
import vault_jev_rules as rules
from jsonsafe import load_json

PICKS_KEY = rules.JEV_KEY   # where the picks live in `operator_overrides_json`
LANES = ("free", "$10", "$50", "$100")
YES_NO = ("y", "n")
REGIONS = ("breasts", "crotch", "butt")
# pick key → the Jev Choice question whose criteria are its options
CHOICE_Q = {"breasts": "breasts_state_a", "crotch": "crotch_state_a", "butt": "butt_state_a",
            "feet_detail": "feet_detail_a",
            **{q: q for q in ("outfit", "toy", "people_count", "pose", "framing", "face_visible", "setting",
                              "added_text")}}
FEET_TOGGLES = ("feet_focus", "soles_visible", "bare_toes_visible", "wears_heels", "wears_stockings_or_fishnets",
                "wears_socks", "feet_in_water")
TOGGLES = ("penetration", "censor_edit", "watermark", "see_through", "topless", "self_touch", "legs_spread",
           "mirror_selfie", "multi_panel", "breasts_focus", "butt_focus", "crotch_focus",
           *FEET_TOGGLES)
assert all(vault_jev.Q[q]["type"] == "noul" for q in TOGGLES)
KEYS = (*CHOICE_Q, *TOGGLES, "lane")
# picks the lane is ranked from; with the butt and the lane itself, the picks that decide the vis flags
LANE_PICKS = ("breasts", "crotch", "penetration")
BODY_PICKS = (*REGIONS, "penetration", "lane")
MANUAL = rules.MANUAL
_VERDICT = {"breasts": "breasts_bare", "crotch": "crotch_bare", "penetration": "penetration"}
_COERCE = {"$10": "breasts_bare", "$50": "crotch_bare", "$100": "penetration"}
# a feet toggle's footwear, for a feet_detail Jev left not_in_picture (first y wins; else bare)
_FEET_DETAIL = (("wears_heels", "heels"), ("wears_stockings_or_fishnets", "stockings_fishnets_nylons"),
                ("wears_socks", "socks"))


def options(key: str) -> tuple[str, ...] | None:
    """The values `key` may take (None: not a pick key)."""
    if key == "lane":
        return LANES
    if key in TOGGLES:
        return YES_NO
    if key in CHOICE_Q:
        return tuple(vault_jev.Q[CHOICE_Q[key]]["criteria"])
    return None


def check(patch: Any) -> dict[str, Any]:
    """A pick patch ({key: value | None}, None clears) validated; ValueError(key) on an unknown key or value."""
    if not isinstance(patch, Mapping):
        raise ValueError("jev")
    for k, v in patch.items():
        opts = options(k)
        if opts is None or (v is not None and v not in opts):
            raise ValueError(k)
    return dict(patch)


def stored(overrides: Any) -> dict[str, Any]:
    """The picks in a row's `operator_overrides_json` (text or parsed; {} when none)."""
    o = load_json(overrides, {}) if isinstance(overrides, str) else overrides
    p = o.get(PICKS_KEY) if isinstance(o, Mapping) else None
    return dict(p) if isinstance(p, Mapping) else {}


def kind_of(jev: Any, kind: Any = None) -> str:
    """photo / video for `overlay`: the row's kind, else the blob's."""
    if kind in rules.JEV_KINDS:
        return kind
    return "video" if isinstance(jev, Mapping) and jev.get("kind") == "video" else "photo"


def merged(stored: Any, patch: Mapping[str, Any]) -> dict[str, Any]:
    """The stored picks with `patch` applied (None removes a key)."""
    out = dict(stored) if isinstance(stored, Mapping) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def value(jev: Mapping[str, Any] | None, key: str) -> Any:
    """What a blob says for one pick key."""
    j = jev or {}
    if key == "lane":
        return j.get("lane5")
    if key in REGIONS:
        return (j.get("state") or {}).get(key)
    if key == "penetration":
        return j.get("penetration")
    return (j.get("tags") or {}).get(key)


# ── path writes, recorded so they can be undone ─────────────────────

_ABSENT = object()


def _get(b: Mapping[str, Any], path: str) -> Any:
    cur: Any = b
    for p in path.split("."):
        if not isinstance(cur, Mapping) or p not in cur:
            return _ABSENT
        cur = cur[p]
    return cur


def _restore(b: dict[str, Any], path: str, rec: Mapping[str, Any]) -> None:
    head, _, leaf = path.rpartition(".")
    parent = _get(b, head) if head else b
    if not isinstance(parent, dict):
        return
    if "was" in rec:
        parent[leaf] = copy.deepcopy(rec["was"])
    else:
        parent.pop(leaf, None)


def undo(jev: Any) -> dict[str, Any] | None:
    """`jev` with every pick `overlay` laid over it taken off (a path changed since stays); None for nothing left."""
    if not isinstance(jev, dict):
        return None
    b = copy.deepcopy(jev)
    rec = b.pop("undo", None)
    for k in ("op", "ai", "made"):
        b.pop(k, None)
    for path, r in (rec.items() if isinstance(rec, dict) else ()):
        if _get(b, path) == r.get("set", _ABSENT):   # nobody changed it since
            _restore(b, path, r)
    return b or None


class _Writer:
    def __init__(self, base: dict[str, Any]) -> None:
        self.base, self.b, self.paths = base, copy.deepcopy(base), set()

    def put(self, path: str, v: Any) -> None:
        parts = path.split(".")
        top = parts[0]
        # a sub-dict the reading did not have is recorded whole (undo drops it)
        self.paths.add(top if not isinstance(self.base.get(top), dict) or len(parts) == 1 else path)
        cur = self.b
        for p in parts[:-1]:
            if not isinstance(cur.get(p), dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = v

    def drop(self, path: str) -> None:
        head, _, leaf = path.rpartition(".")
        parent = _get(self.b, head) if head else self.b
        if isinstance(parent, dict) and leaf in parent:
            self.paths.add(path)
            parent.pop(leaf)

    def record(self) -> dict[str, Any]:
        out = {}
        for p in sorted(self.paths):
            was, now = _get(self.base, p), _get(self.b, p)
            if was == now:
                continue
            r = {}
            if was is not _ABSENT:
                r["was"] = copy.deepcopy(was)
            if now is not _ABSENT:
                r["set"] = copy.deepcopy(now)
            out[p] = r
        return out


# ── the overlay ─────────────────────────────────────────────────────


def _read(b: Mapping[str, Any]) -> bool:
    """`b` carries a reading to lay picks over (a lane and the region states), not just a manual skeleton."""
    return "lane5" in b and isinstance(b.get("state"), dict)


def _fine(b: Mapping[str, Any]) -> str:
    """The free lane's fine name (`lane_rule`'s last rungs, on the region states and the stored P)."""
    st = set((b.get("state") or {}).values())
    P = b.get("P") or {}
    if "hidden_not_worn" in st or (P.get("censor_edit") or 0) >= .65:
        return "implied"
    if {"sexy_covered", "sheer_covered"} & st or (P.get("nipple_through_fabric") or 0) >= .65:
        return "lingerie"
    return "mass"


def _ranked(b: Mapping[str, Any]) -> str | None:
    """The lane the verdicts give (a verdict not known reads unsure); None: an unsure decides it (keep the read lane)."""
    v = [b.get(k) or "unsure" for k in ("penetration", "crotch_bare", "breasts_bare")]
    for verdict, lane in zip(v, ("$100", "$50", "$10")):
        if verdict == "y":
            return lane
    return None if "unsure" in v else "free"


def _set_lane(w: _Writer, lane: str) -> None:
    w.put("lane5", lane)
    w.put("lane", lane if lane in rules.PAID else _fine(w.b))
    w.put("settled", False)


def overlay(jev: Any, picks: Mapping[str, Any] | None, kind: str, *, at: str | None = None) -> dict[str, Any] | None:
    """`jev` with `picks` materialised (module doc); `jev` unchanged in shape when there are none (None stays None).
    `kind` (photo / video) shapes a blob built without a reading; `at` stamps one (default: its old `at`, else now)."""
    base = undo(jev) or {}
    picks = {k: v for k, v in (picks or {}).items() if k in KEYS and v is not None}
    if not picks:
        return base or None
    read = _read(base)
    w = _Writer(base)
    if not read:
        w.put("v", rules.VERSION)
        old_at = jev.get("at") if isinstance(jev, dict) else None
        w.put("at", old_at or at or datetime.utcnow().isoformat())
        w.put("settled", False)
        for k in ("state", "tags", "P"):
            if not isinstance(w.b.get(k), dict):
                w.put(k, {})
        for q in rules.FACT_CHOICES:
            if not isinstance((w.b.get("C") or {}).get(q), dict):
                opts = options(q) or ()
                w.put(f"C.{q}", {o: round(1 / len(opts), 4) for o in opts})
        if kind == "video":
            w.put("kind", "video")
            w.put("vv", rules.VIDEO_VERSION)
            if not isinstance(w.b.get("frames"), list):
                w.put("frames", [])

    for r in REGIONS:
        if r in picks:
            w.put(f"state.{r}", picks[r])
            yn = "y" if picks[r] == "bare" else "n"
            w.put("tags.butt_bare" if r == "butt" else _VERDICT[r], yn)
    for q in TOGGLES:
        if q in picks:
            if q == "penetration":
                w.put("penetration", picks[q])
            else:
                w.put(f"tags.{q}", picks[q])
                w.put(f"P.{q}", 1.0 if picks[q] == "y" else 0.0)
    chosen = {q for q in CHOICE_Q if q in picks and q not in REGIONS}
    for q in chosen:
        w.put(f"tags.{q}", picks[q])
        if q in rules.FACT_CHOICES:
            w.put(f"C.{q}", {o: 1.0 if o == picks[q] else 0.0 for o in options(q) or ()})

    # feet: a feet answer y means feet are in the picture, whatever the detail read
    tags = w.b.get("tags") or {}
    feet_y = [q for q in FEET_TOGGLES if picks.get(q) == "y"]
    if "feet_focus" in picks:
        w.put("feet_subject", 1.0 if picks["feet_focus"] == "y" else 0.0)
    if feet_y:
        w.put("feet_subject", 1.0)
        if tags.get("feet_detail") in (None, "not_in_picture"):
            w.put("tags.feet_detail", next((d for q, d in _FEET_DETAIL if q in feet_y), "bare"))
            chosen.add("feet_detail")
    tags = w.b.get("tags") or {}
    if "added_text" in chosen:
        w.put("tags.text_any", "y" if tags["added_text"] != "nothing_added" else "n")
    if "toy" in chosen:
        w.put("tags.toy_any", "y" if tags["toy"] != "no_toy" else "n")
    if "feet_detail" in chosen:
        w.put("tags.feet_any", "y" if tags["feet_detail"] != "not_in_picture" else "n")
    col = dict(tags)
    rules.collapse(col)
    for new, (src, _) in rules.COLLAPSE.items():
        if src in chosen and new in col:
            w.put(f"tags.{new}", col[new])

    lane = picks.get("lane")
    if lane:
        for k in ("breasts_bare", "crotch_bare", "penetration"):
            if lane == "free":
                w.put(k, "n")
        if lane in _COERCE:
            w.put(_COERCE[lane], "y")
        _set_lane(w, lane)
        if w.b.get("review"):
            w.put("review", None)
        w.drop("read_lane5")
    elif any(k in picks for k in LANE_PICKS):
        ranked = _ranked(w.b)
        if ranked is not None:
            if read and w.b.get("review") and ranked != "$100":   # a clip that may read too low stays unknown-priced
                w.put("lane5", "review")
                w.put("read_lane5", ranked)
                w.put("lane", ranked if ranked in rules.PAID else _fine(w.b))
                w.put("settled", False)
            else:
                _set_lane(w, ranked)
                w.drop("read_lane5")
        lane = ranked
    if read and lane and w.b.get("status") != "ok" and w.b.get("lane5") in LANES:
        # a failed re-read keeps the last reading's fields; the operator's lane makes it a reading again
        w.put("status", "ok")
    if not read:
        for k in ("breasts_bare", "crotch_bare", "penetration"):
            if k not in w.b:
                w.put(k, "unsure")
        w.put("status", "ok" if lane else MANUAL)
        if not lane:
            for k in ("lane5", "lane"):
                w.drop(k)

    out = w.b
    out["undo"] = w.record()
    out["op"] = sorted(picks)
    out["ai"] = {k: v for k in picks if (v := value(base if read else None, k)) is not None}
    if not read:
        out["made"] = MANUAL
    return out
