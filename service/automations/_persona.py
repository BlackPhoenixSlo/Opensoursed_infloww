from __future__ import annotations

import logging
import re

import run_slot
from db.models import Fan
from jsonsafe import load_dict, load_json
from llm_client import LLMCapExceeded

from . import _voice
from ._common import nonempty
from ._model_wait import freed_chat
from .rhythm import INLINE_MAX_S

log = logging.getLogger("of-relay.persona")


DEFAULT_REGISTER_AGE = 22
_PERSONA_AGE_LINE_RE = re.compile(r"^[ \t]*age[ \t]*:[ \t]*(\d{1,3})\b", re.I | re.M)
_PERSONA_AGE_PROSE_RE = re.compile(r"\b(\d{1,3})[\s-]*(?:year[\s-]*old|yo)\b", re.I)


def persona_register_age(persona: str | None) -> int:
    for rx in (_PERSONA_AGE_LINE_RE, _PERSONA_AGE_PROSE_RE):
        m = rx.search(persona or "")
        if not m:
            continue
        try:
            age = int(m.group(1))
        except ValueError:
            continue
        # under-18 must never reach a prompt, whatever an operator typed
        if 18 <= age <= 99:
            return age
    return DEFAULT_REGISTER_AGE


def _persona_location_line(location: str | None) -> str:
    loc = (location or "").strip()
    return f"You are based in {loc}.\n\n" if loc else ""


PERSONA_FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("age", "Age"),
    ("job", "Work"),
    ("home_city", "Lives in"),
    ("relationship", "Relationship"),
    ("kids", "Kids"),
    ("family", "Family"),
    ("tattoos", "Tattoos"),
    ("kinks", "What she's into"),
    ("limits", "What she won't do"),
)

# enrich pass must never propose these: kinks/limits are business decisions, tattoos are visible in vault photos so a wrong answer is checkable
PERSONA_FACTS_OPERATOR_ONLY: frozenset[str] = frozenset({"kinks", "limits", "tattoos"})

_voice.assert_canon_parity(PERSONA_FACT_FIELDS)

_FACT_VALUE_CLIP = 240


def _pinned_block(header: str, lines: list[str]) -> str:
    return f"{header}\n" + "\n".join(lines) + "\n\n" if lines else ""


def _parse_persona_facts(raw) -> dict:
    return {k: v for k, v in load_dict(raw).items() if k in dict(PERSONA_FACT_FIELDS)}


def _persona_facts_block(raw, voice=None) -> str:
    facts = _parse_persona_facts(raw)
    overrides = _voice.fact_labels(voice)
    lines = []
    for key, declared in PERSONA_FACT_FIELDS:
        label = overrides.get(key, declared)
        val = facts.get(key)
        if isinstance(val, (list, tuple)):
            val = ", ".join(str(v).strip() for v in val if str(v).strip())
        val = str(val).strip() if val is not None else ""
        if val:
            lines.append(f"- {label}: {val[:_FACT_VALUE_CLIP]}")
    return _pinned_block(
        "THESE ARE THE FACTS ABOUT YOU. They are true, they never change, and "
        "you must never say anything that contradicts them:", lines)


MODEL_NOTES_LABELS: tuple[str, ...] = (
    "Name", "Age", "From", "Personality", "Likes", "Won't do (hard limits)")
MODEL_NOTES_TEMPLATE = "\n".join(f"{label}: " for label in MODEL_NOTES_LABELS)
MODEL_NOTES_MAX = 1000
_BLANK_LABEL_LINES = frozenset(f"{label.lower()}:" for label in MODEL_NOTES_LABELS)


def _model_notes_block(raw) -> str:
    lines = [ln.rstrip() for ln in str(raw or "")[:MODEL_NOTES_MAX].splitlines()]
    lines = [ln for ln in lines if ln.strip() and ln.strip().lower() not in _BLANK_LABEL_LINES]
    return _pinned_block(
        "MODEL INFO (written by your team; it is true about you, never "
        "contradict it):", lines)


_CLAIMS_MAX = 20
_CLAIM_TEXT_CLIP = 180


_SELF_CLAIM_RE = re.compile(
    r"\b("
    r"i'?m\s+\d{2}\b|i\s+am\s+\d{2}\b|\d{2}\s*years?\s*old|"
    r"i\s+live\s|i\s+grew\s+up|i\s+was\s+born|born\s+in\s|i'?m\s+from|i\s+am\s+from|"
    r"my\s+(job|work|boyfriend|ex|husband|mom|mum|dad|brother|sister|family|"
    r"dog|cat|tattoo|birthday|name)\b|"
    r"i\s+(work|studied|study|speak)\s|i\s+don'?t\s+have\s+(kids|children)|"
    r"i\s+have\s+(a\s+)?(kid|kids|children|tattoo)|"
    r"tengo\s+\d{2}\s*a[ñn]os|vivo\s+en\s|estoy\s+(en|ac[áa]\s+en)\s|"
    r"crec[íi]\s|nac[íi]\s|soy\s+(de|argentina|chilena|colombiana|mexicana)\b|"
    r"me\s+llamo\s|"
    r"mi\s+(trabajo|novio|ex|esposo|mam[áa]|pap[áa]|hermano|hermana|familia|"
    r"perro|gato|tatuaje|cumplea[ñn]os|nombre)\b|"
    r"trabajo\s+en\s|estudi[ée]\s|hablo\s"
    r")",
    re.I,
)


_ASKS_ABOUT_HER_RE = re.compile(
    r"\b("
    r"how old (are|r) (you|u)|your age|what'?s your name|your real name|"
    r"where (do|are) (you|u) (live|from)|where (you|u) (live|from)|what city|"
    r"live alone|who do (you|u) live with|"
    r"do (you|u) have (a )?(boyfriend|kids|children|tattoos?)|are (you|u) (single|married)|"
    r"what do (you|u) do for|your job|do (you|u) work|did (you|u) grow up|"
    r"your family|your (mom|mum|dad|brother|sister)|"
    r"cu[áa]ntos a[ñn]os ten[ée]s|cuantos a[ñn]os tienes|tu edad|tu nombre|"
    r"d[óo]nde viv[íi]s|donde vives|en qu[ée] parte viv[íi]s|de d[óo]nde (eres|sos)|"
    r"viv[íi]s sola|vives sola|con qui[ée]n viv[íi]s|"
    r"ten[ée]s novio|tienes novio|sos soltera|eres soltera|tienes hijos|ten[ée]s hijos|"
    r"en qu[ée] trabaj[áa]s|tu trabajo|tu familia|d[óo]nde creciste|tu infancia"
    r")",
    re.I,
)


def asks_about_her(text: str | None) -> bool:
    return bool(_ASKS_ABOUT_HER_RE.search(text or ""))


def mentions_self_claim(text: str | None) -> bool:
    return bool(_SELF_CLAIM_RE.search(text or ""))


def parse_persona_claims(raw) -> list[dict]:
    data = load_json(raw, [])
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or "").strip()[:40]
        claim = str(row.get("claim") or "").strip()[:_CLAIM_TEXT_CLIP]
        if topic and claim:
            out.append({"topic": topic, "claim": claim,
                        "at": str(row.get("at") or "")[:32]})
    return out


# Latest-wins per topic and idempotent: a job retry re-recording the same claim must not grow the list.
def merge_persona_claims(prior, new_claims, *, now_iso: str = "") -> list[dict]:
    merged = {c["topic"]: c for c in parse_persona_claims(prior)}
    for row in parse_persona_claims(new_claims):
        merged[row["topic"]] = {**row, "at": row.get("at") or now_iso}
    ordered = sorted(merged.values(), key=lambda c: c.get("at") or "")
    return ordered[-_CLAIMS_MAX:]


def resolved_claims(raw, *, age_claimed: str | None = None,
                    location_claimed: str | None = None,
                    job_claimed: str | None = None) -> list[dict]:
    # A set scalar (operator PATCH) wins over list rows by topic, not text: text-matching let both render or silenced the PATCH.
    rows = parse_persona_claims(raw)
    overrides = (("persona_age_claimed", "your age", age_claimed),
                 ("persona_location_claimed", "where you are", location_claimed),
                 ("persona_job_claimed", "your work", job_claimed))
    overridden = {col for col, _label, val in overrides if nonempty(val)}
    out: list[dict] = [
        {"label": label, "value": str(val).strip()[:_CLAIM_TEXT_CLIP],
         "column": col, "at": None}
        for col, label, val in overrides if col in overridden
    ]
    out += [
        {"label": row["topic"], "value": row["claim"],
         "column": _column_for_topic(row["topic"]), "at": row.get("at")}
        for row in rows if _column_for_topic(row["topic"]) not in overridden
    ]
    return out


def persona_claims_block(raw, *, age_claimed: str | None = None,
                         location_claimed: str | None = None,
                         job_claimed: str | None = None) -> str:
    rows = parse_persona_claims(raw)
    lines = [f"- {r['label']}: {r['value']}" for r in resolved_claims(
        raw, age_claimed=age_claimed, location_claimed=location_claimed,
        job_claimed=job_claimed)]
    return _pinned_block(
        "YOU HAVE ALREADY TOLD HIM THE FOLLOWING ABOUT YOURSELF. It is true for "
        "him now, whatever else you might say to anyone else — repeat it "
        "consistently and NEVER give him a different version:", lines)




_CLAIM_TOPIC_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("persona_age_claimed", ("age", "edad")),
    ("persona_location_claimed", ("location", "hometown", "city", "lives",
                                  "country", "ciudad", "pais", "país")),
    ("persona_job_claimed", ("job", "work", "trabajo", "occupation")),
)


def _column_for_topic(topic: str) -> str | None:
    t = (topic or "").lower()
    for col, keys in _CLAIM_TOPIC_COLUMNS:
        if any(k in t for k in keys):
            return col
    return None


def claims_to_scalars(merged: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in merged:
        col = _column_for_topic(row["topic"])
        if col:
            out[col] = row["claim"][:200]
    return out


def compose_persona(cfg, *, fallback: str) -> str:
    persona = (getattr(cfg, "persona", None) or "").strip() or fallback
    location = _persona_location_line(getattr(cfg, "location", None)).rstrip()
    if location:
        persona = f"{persona}\n{location}"
    notes = _model_notes_block(getattr(cfg, "model_notes", None)).rstrip()
    if notes:
        persona = f"{persona}\n\n{notes}"
    facts = _persona_facts_block(getattr(cfg, "persona_facts_json", None),
                                 getattr(cfg, "voice", None))
    return f"{persona}\n\n{facts}".rstrip() if facts else persona


_CONSISTENCY_SYSTEM = (
    "Check one outgoing creator message against HER PROFILE and, when present, "
    "WHAT SHE ALREADY TOLD THIS FAN (fan-told wins). Respond with ONLY:\n"
    '{"contradicts": true|false, "which": "", "fix": ""}\n'
    "true ONLY when a fact about HERSELF clashes outright — age, city, job, "
    "living/relationship, family, pet. rewording, flirting, fantasy, anything "
    "about HIM, or a NEW fact never count. when in doubt: false.\n"
    "which: the clash in a few words. fix: her message minimally rewritten to "
    "agree — same voice, length, LANGUAGE; never apologise or mention a "
    "mistake. both empty when false."
)


def consistency_messages(draft: str, persona: str, claims_block: str) -> list[dict]:
    told = claims_block.strip()
    user = (f"HER PROFILE:\n{persona.strip()}\n\n"
            + (f"{told}\n\n" if told else "")
            + f"HER OUTGOING MESSAGE:\n{draft.strip()}\n\n"
            "Does this message contradict anything above about HER?")
    return [{"role": "system", "content": _CONSISTENCY_SYSTEM},
            {"role": "user", "content": user}]


def parse_consistency_verdict(raw) -> tuple[bool, str, str]:
    # Fails open: an unusable verdict reads clean, a verifier must never swallow a reply.
    data = load_dict(raw)
    if not bool(data.get("contradicts")):
        return (False, "", "")
    fix = str(data.get("fix") or "").strip()
    if not fix:
        return (False, "", "")
    return (True, str(data.get("which") or "").strip()[:120], fix)


def fan_claims_block(f: Fan) -> str:
    return persona_claims_block(
        getattr(f, "persona_claims_json", None),
        age_claimed=getattr(f, "persona_age_claimed", None),
        location_claimed=getattr(f, "persona_location_claimed", None),
        job_claimed=getattr(f, "persona_job_claimed", None))


async def verify_self_consistency(account_id: str, fan_id: int, f: Fan,
                                  draft: str, persona: str, model: str,
                                  purpose: str,
                                  last_inbound: str = "") -> str:
    if not draft.strip():
        return draft
    # Gated: only a draft about herself (or his question about her) can contradict a claim; never on every reply.
    if not (mentions_self_claim(draft) or asks_about_her(last_inbound)):
        return draft
    claims_block = fan_claims_block(f)
    if not persona.strip() and not claims_block:
        return draft
    try:
        res = await freed_chat(
            budget_s=INLINE_MAX_S,
            model=model,
            messages=consistency_messages(draft, persona, claims_block),
            # calling engine's purpose, not a new one: purpose keys account_ai_config.model_by_purpose overrides
            purpose=purpose, account_id=account_id, fan_id=fan_id,
            temperature=0.0, response_format={"type": "json_object"},
        )
        verdict = getattr(res, "parsed", None)
        contradicts, which, fix = parse_consistency_verdict(
            verdict if verdict is not None else res.content)
    except run_slot.SlotLost:
        raise
    except LLMCapExceeded:
        return draft
    except Exception:
        log.warning("consistency check failed account=%s fan=%s", account_id, fan_id,
                    exc_info=True)
        return draft
    if not contradicts:
        return draft
    log.info("consistency fix account=%s fan=%s which=%s", account_id, fan_id, which)
    return fix
