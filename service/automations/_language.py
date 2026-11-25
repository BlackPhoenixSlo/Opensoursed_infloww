from __future__ import annotations

import re

from sqlalchemy import select

from . import _common
from db.engine import get_session
from db.models import AccountAiConfig

KNOWN_LANGS = ("en", "es", "sl", "pt", "fr", "de", "it")
LANG_DISPLAY = {
    "en": "English", "es": "Español", "sl": "Slovenščina",
    "pt": "Português", "fr": "Français", "de": "Deutsch", "it": "Italiano",
}
GUARD_LANGS = frozenset({"es"})


def norm_lang(raw) -> str:
    s = (raw or "")
    s = s.strip().lower() if isinstance(s, str) else ""
    if not s:
        return ""
    code = s.split("-")[0].split("_")[0]
    return code if code in KNOWN_LANGS else ""


async def load_account_language(account_id: str) -> str:
    async with get_session() as s:
        raw = (await s.execute(
            select(AccountAiConfig.language).where(AccountAiConfig.account_id == str(account_id))
        )).scalar_one_or_none()
    return norm_lang(raw) or "en"


def resolve_language(account_lang=None, fan_lang=None) -> str:
    return norm_lang(fan_lang) or norm_lang(account_lang) or "en"


def output_language_directive(lang: str) -> str:
    code = norm_lang(lang)
    if not code or code == "en":
        return ""
    name = LANG_DISPLAY.get(code, code)
    return (
        f"\n\nOUTPUT LANGUAGE: {name} ({code}) only, casual native texting — but "
        f"protocol markers like 'STICKER:' stay in English, verbatim."
    )


_ES_CONTENT_ASK = re.compile(
    r"(?<!\w)("
    r"m[aá]ndame|env[ií]ame|mu[eé]strame|ens[eé][nñ]ame|"
    r"quiero ver|d[eé]jame ver|me ense[nñ]as|puedo ver|"
    r"cu[aá]nto (cuesta|vale|por)|"
    r"tienes (fotos?|v[ií]deos?|algo)|"
    r"(manda|mandame|quiero|dame|tienes) (fotos?|nudes?|desnuda|contenido|v[ií]deos?)|"
    r"m[aá]s (fotos?|contenido|v[ií]deos?)|"
    r"desnud[ao]s?|nudes?"
    r")(?!\w)", re.IGNORECASE)

_ES_ESCALATION = re.compile(
    r"(?<!\w)("
    r"estoy (muy )?(caliente|cachond[ao]|duro)|me pones (caliente|cachond[ao])|"
    r"quiero (cogerte|follarte|chuparte|comerte|lamerte|penetrarte|tocarte)|"
    r"me quiero (correr|venir)|c[oó]rrete|hazme (acabar|correr)|"
    r"est[aá]s buen[ao]|qu[eé] rica|te deseo|te necesito dentro"
    r")(?!\w)", re.IGNORECASE)

_ES_BOT = re.compile(
    r"(?<!\w)("
    r"eres (un[ao]? )?(bot|robot|m[aá]quina|ia|inteligencia artificial)|"
    r"eres real|de verdad eres|hablo con (una?|un) (bot|robot|m[aá]quina|ia|persona real)|"
    r"esto es (un[ao]? )?(bot|ia|autom[aá]tico)"
    r")(?!\w)", re.IGNORECASE)

_ES_RESTRICTED = (
    "menor", "menores", "violaci[oó]n", "violar", "sangre", "orina", "esclav[ao]",
    "secuestr[oa]", "incesto", "embarazada", "borracha", "dormida", "inconsciente",
    "prostitut[ao]", "drogad[ao]", "menor de edad",
)
_ES_RESTRICTED_RE = re.compile(
    r"(?<!\w)(" + "|".join(_ES_RESTRICTED) + r")(?!\w)", re.IGNORECASE)


_SL_CONTENT_ASK = re.compile(
    r"(?<!\w)("
    r"pošlji|pokaži|send( me)?|show me|"
    r"(koliko|kolk[oa]) (stane|stanejo|za)|how much|"
    r"(hočem|želim|rad bi|bi rad|daj|daj mi|imaš|maš|want|i want|wanna see|gimme|give me) "
    r"(te |to )?(videt|videl|vidim|see|slik[eio]|fotk[eio]|foto|photos?|pics?|"
    r"video|posnetek|golo|nud(es?|i|ce)|kaj lepega)|"
    r"(gole slike|gola slika|nud(es?|i|ce)|pics?|več slik|več fotk|več golega)"
    r")(?!\w)", re.IGNORECASE)

_SL_ESCALATION = re.compile(
    r"(?<!\w)("
    r"(zelo |tako |čist |cist )?(vroč|napaljen|nabrit|horni|horny|hard) sem|"
    r"vroče mi je|trd sem|imam (ga )?trd(ega)?|so (horny|hard)|"
    r"(hočem te|te hočem|hočem|želim te) (pofukat|fukat|polizat|lizat|čutit|začutit)|"
    r"(pofukal|polizal|lizal|nategnil) bi te|bi te (rad )?(pofukal|polizal|nategnil)|"
    r"hočem (biti |bit )?v tebi|drkam|drka mi|"
    r"si (tako |čist )?(seksi|sexy|vroča|mokra|hot|wet)|"
    r"tako si (seksi|sexy|vroča|mokra|hot|wet)|so (hot|sexy|wet)|"
    r"hočem te|želim te|rabim te"
    r")(?!\w)", re.IGNORECASE)

_CONTENT_ASK_BY_LANG = {"es": _ES_CONTENT_ASK, "sl": _SL_CONTENT_ASK}
_ESCALATION_BY_LANG = {"es": _ES_ESCALATION, "sl": _SL_ESCALATION}



def _es(lang: str) -> bool:
    return norm_lang(lang) in GUARD_LANGS


def is_content_ask(text, lang="en") -> bool:
    rx = _CONTENT_ASK_BY_LANG.get(norm_lang(lang))
    if rx is not None:
        return bool(text) and bool(rx.search(text or ""))
    return _common.is_content_ask(text)


def is_escalation(text, lang="en") -> bool:
    rx = _ESCALATION_BY_LANG.get(norm_lang(lang))
    if rx is not None:
        return bool(text) and bool(rx.search(text or ""))
    return _common.is_escalation(text)


def thread_heat(messages, lang="en") -> bool:
    ca = _CONTENT_ASK_BY_LANG.get(norm_lang(lang))
    esc = _ESCALATION_BY_LANG.get(norm_lang(lang))
    if ca is None or esc is None:
        return _common.thread_heat(messages)
    for m in messages or []:
        body = m[1] if isinstance(m, (tuple, list)) and len(m) > 1 else getattr(m, "body", "")
        direction = m[0] if isinstance(m, (tuple, list)) else getattr(m, "direction", "in")
        if direction == "in" and (ca.search(body or "") or esc.search(body or "")):
            return True
    return False


def detect_bot_accusation(text, lang="en") -> bool:
    if _es(lang):
        return bool(text) and bool(_ES_BOT.search(text or ""))
    return bool(_common.detect_bot_accusation(text))


def apply_word_restriction(text, lang="en") -> str:
    if not text:
        return text
    text = _common.strip_inverted_punct(text)
    if _es(lang):
        return _ES_RESTRICTED_RE.sub(lambda m: _common._double_first_vowel(m), text)
    return _common.apply_word_restriction(text)


_WORD = re.compile(r"[^\W\d_]+")
_STOPWORDS = {
    "en": frozenset(
        "the you your and to my i is it for with this that are be have just what of on at all but can "
        "get if want we me in u ur im new babe baby wanna gonna tonight now vid pic pics dm dms".split()),
    "de": frozenset(
        "und ich du nicht für mein meine meinen meinem meiner dich dir ist bist bin mit auf heute schon "
        "noch willst kannst der ein eine einen einem wir uns sind habe hab hast mich mir wie auch aber oder "
        "nur jetzt sehr wenn dass ganz gerade gleich doch kein keine nichts etwas dein deine deinen deinem "
        "euch nach vom zum zur beim über mehr viel gerne endlich nochmal".split()),
    "es": frozenset(
        "que por para mi tu te lo una pero muy más estoy eres quiero tengo hoy qué cómo aquí ahora del "
        "mis tus está esta este eso también todo".split()),
}


def detect_text_lang(text) -> str:
    words = _WORD.findall((text or "").lower())
    hits = {k: sum(w in v for w in words) for k, v in _STOPWORDS.items()}
    de, es = hits["de"], hits["es"]
    best, n, other = ("de", de, es) if de >= es else ("es", es, de)
    return best if n >= 3 and 4 * n >= len(words) and n > hits["en"] and n > other else "en"
