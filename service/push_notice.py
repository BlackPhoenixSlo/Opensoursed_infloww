"""
One relay frame -> the OS notices the app would show for it (pure; push_send's input).

Ports the app's three arrival lanes (app/components/toastStore.ts `dmArrival` with the
tip fix, `purchaseArrival`, `toastArrival`) and what `pingNotification` pings with:
title = name || username || BRAND_NAME, body = text || rawType || "New activity",
href = app/lib/notificationLink.ts `notificationHref`. Helpers mirror
app/lib/notifSettings.ts `mapOfTypeToKey`, app/lib/notifText.ts `renderText`,
app/lib/format.ts `fmtPrice`. Shared cases: tests/fixtures/notice_cases.json (B3).

Differences from the page, on purpose: no `["of-user"]` cache (a purchase's title is
its payload name or the brand), no username -> id lookup, body capped at BODY_MAX (payload():
title, body and href capped too).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from brand import BRAND_ICON as ICON, BRAND_NAME

BODY_MAX = 180
TITLE_MAX = 120
HREF_MAX = 512
MONEY = frozenset({"purchases", "tip"})
TYPES = frozenset({"api2_chat_message", "purchase_notified", "toasts"})


@dataclass(frozen=True, slots=True)
class Notice:
    id: str                     # the lane's claimUnseen id ("m<msg id>" for a DM)
    account_id: str
    type_key: str | None        # NotifTypeKey; None = an OF toast type the app can't name
    title: str
    body: str
    href: str | None
    raw_type: str = ""          # Arrival.rawType: the payload's `type` (the app maps it with mapOfTypeToKey)

    @property
    def tag(self) -> str:
        return f"{self.account_id}:{self.id}" if self.account_id else self.id


# ── app helpers, ported ──

def type_key_of(raw: Any) -> str | None:
    """notifSettings.mapOfTypeToKey."""
    if not raw or not isinstance(raw, str):
        return None
    t = raw.lower()
    if t in ("message", "messages", "chatmessage"):
        return "message"
    if t in ("tip", "tips"):
        return "tip"
    if t in ("purchase", "purchases", "paided_message"):
        return "purchases"
    if t in ("subscribed", "subscriber", "subscription"):
        return "subscribed"
    if t in ("commented", "comment"):
        return "commented"
    if t in ("mentioned", "mention"):
        return "mentioned"
    if t in ("favorited", "favorite", "like", "liked"):
        return "favorited"
    return None


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def render_text(raw: Any, replace_pairs: Any = None) -> str:
    """notifText.renderText with tagSep " "."""
    s = raw if isinstance(raw, str) else ""
    if isinstance(replace_pairs, Mapping):
        for k, v in replace_pairs.items():
            s = s.replace(str(k), _js_str(v))
    return _WS.sub(" ", _TAG.sub(" ", s)).strip()


def _round_half_up(x: float) -> int:
    """JS Math.round."""
    return math.floor(x + 0.5)


def fmt_price(cents: Any) -> str:
    """format.fmtPrice: "$7", "$7.50", "$1,234.56"; None / NaN -> "—"."""
    n = _js_number(cents)
    if n is None:
        return "—"
    c = int(math.copysign(_round_half_up(abs(n)), n))
    a = abs(c)
    s = f"{a // 100:,}" if a % 100 == 0 else f"{a / 100:,.2f}"
    return f"{'-' if c < 0 else ''}${s}"


_COMPONENT_SAFE = "!~*'()"    # encodeURIComponent's unescaped marks (plus alnum -_.)


def _enc_component(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe=_COMPONENT_SAFE)


def _form_enc(s: str) -> str:
    """URLSearchParams' application/x-www-form-urlencoded byte serializer."""
    out = []
    for b in s.encode("utf-8"):
        c = chr(b)
        if c.isascii() and (c.isalnum() or c in "*-._"):
            out.append(c)
        elif c == " ":
            out.append("+")
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


def notification_href(account_id: str, user: Mapping[str, Any], *, refresh: bool = False) -> str | None:
    """notificationLink.notificationHref: the Fan's Deep link + `?refresh=media` (money) + `fanTab`."""
    acc = _enc_component(account_id)
    uid, name, username = user.get("id"), user.get("name"), user.get("username")
    if uid:
        path = f"/messages-pro/{acc}/{_js_str(uid)}"
    elif username:
        path = f"/messages-pro/{acc}/u/{_enc_component(_js_str(username))}"
    else:
        return None
    q = [("refresh", "media")] if refresh else []
    q.append(("fanTab", _js_str(name or username or f"fan {_js_str(uid)}")))
    return path + "?" + "&".join(f"{_form_enc(k)}={_form_enc(v)}" for k, v in q)


# ── JS value semantics the parsers lean on ──

def _js_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return "" if v is None else str(v)


def _js_number(v: Any) -> float | None:
    """`Number(v)` when finite, else None (Number(undefined) is NaN; null and "" are 0)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            n = float(s)
        except ValueError:
            return None
        return n if math.isfinite(n) and s.lower() not in ("nan", "inf", "-inf", "+inf", "infinity") else None
    return None


def _first(*vals: Any) -> Any:
    """JS `a || b || ...`: the first truthy value, else the last."""
    for v in vals:
        if v:
            return v
    return vals[-1] if vals else None


def is_fan_id(v: Any) -> bool:
    """fanId.isValidFanId: a positive integer, as a number or a digit string."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return False
    if isinstance(v, float):
        if not v.is_integer() or abs(v) > 2 ** 53 - 1:
            return False
        v = int(v)
    if isinstance(v, int) and abs(v) > 2 ** 53 - 1:
        return False
    s = str(v)
    return bool(re.fullmatch(r"\d+", s)) and not re.fullmatch(r"0+", s)


def _cap(s: str, n: int = BODY_MAX) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _notice(aid: str, nid: str, type_key: str | None, raw_type: str, user: Mapping[str, Any],
            text: str, href: str | None) -> Notice:
    title = _js_str(_first(user.get("name"), user.get("username"), BRAND_NAME))
    body = _js_str(_first(text, raw_type, "New activity"))
    return Notice(nid, aid, type_key, title, _cap(body), href, raw_type)


# ── the three lanes ──

def _dm(aid: str, frame: Mapping[str, Any]) -> list[Notice]:
    """toastStore.dmArrival (+ resolveChatTarget's inbound gate), with the tip fix."""
    msg = frame.get("api2_chat_message")
    if not isinstance(msg, Mapping) or msg.get("id") is None:
        return []
    fu = msg.get("fromUser")
    if not isinstance(fu, Mapping) or not is_fan_id(fu.get("id")):
        return []
    from_id = fu.get("id")
    if _js_str(from_id) == aid:
        return []                                   # our own send never pings
    user = {"id": from_id, "name": _first(fu.get("name"), fu.get("username")), "username": fu.get("username")}
    if msg.get("isTip"):
        amt = next((n for n in (_js_number(msg.get("tipAmount")), _js_number(msg.get("price")))
                    if n is not None and n > 0), None)
        text = f"Tipped you {fmt_price(_round_half_up(amt * 100))}" if amt is not None else "Sent you a tip"
        type_key = "tip"
    else:
        text = render_text(msg.get("text").strip() if isinstance(msg.get("text"), str) else "")
        if not text:
            media = _js_number(msg.get("mediaCount"))
            text = "Sent you media" if media is not None and media > 0 else "Sent you a message"
        type_key = "message"
    href = notification_href(aid, user, refresh=type_key in MONEY)
    return [_notice(aid, "m" + _js_str(msg.get("id")), type_key, type_key, user, text, href)]


def _purchase(aid: str, frame: Mapping[str, Any]) -> list[Notice]:
    """toastStore.purchaseArrival with no cached user."""
    p = frame.get("purchase_notified")
    if not isinstance(p, Mapping) or not p.get("notif_id") or not is_fan_id(p.get("fan_id")):
        return []
    user = {"id": p.get("fan_id"), "name": p.get("name") or None, "username": None}
    cents = _js_number(p.get("amount_cents"))
    text = f"Unlocked your PPV — {fmt_price(cents)}" if cents is not None and cents > 0 else "Unlocked your PPV"
    href = notification_href(aid, user, refresh=True)
    return [_notice(aid, _js_str(p.get("notif_id")), "purchases", "purchases", user, text, href)]


_HTML_AVATAR_USER = re.compile(r"""href=["']https?://(?:www\.)?onlyfans\.com/([A-Za-z0-9._-]+)["']""", re.I)


def _toast(aid: str, t: Any) -> Notice | None:
    """toastStore.toastArrival."""
    if not isinstance(t, Mapping) or t.get("id") is None:
        return None
    raw_type = t.get("type") if isinstance(t.get("type"), str) else ""
    type_key = type_key_of(raw_type)
    raw_text = _first(*(t.get(k) if isinstance(t.get(k), str) else "" for k in ("text", "description", "title")))
    data = t.get("data") if isinstance(t.get("data"), Mapping) else {}
    related = data.get("relatedUser") if isinstance(data.get("relatedUser"), Mapping) else {}
    repl = data.get("replacements") if isinstance(data.get("replacements"), Mapping) else None
    repl_get = repl.get if repl is not None else (lambda _k: None)
    from_user = t.get("fromUser") if isinstance(t.get("fromUser"), Mapping) else {}
    recipient = t.get("user") if isinstance(t.get("user"), Mapping) else {}
    m = _HTML_AVATAR_USER.search(raw_text) if raw_text else None

    rel_raw = related.get("id")
    if rel_raw is None:
        rel_raw = _js_number(repl_get("{RELATED_USER_ID}")) if repl_get("{RELATED_USER_ID}") else None
    rel_id = rel_raw if isinstance(rel_raw, (int, float)) and not isinstance(rel_raw, bool) \
        and math.isfinite(rel_raw) else None
    if isinstance(rel_id, float) and rel_id.is_integer():
        rel_id = int(rel_id)
    user = {
        "id": rel_id if rel_id is not None else from_user.get("id"),
        "name": _first(related.get("name") if isinstance(related.get("name"), str) else None,
                       repl_get("{RELATED_USER_NAME}"), from_user.get("name"), recipient.get("name")),
        "username": _first(related.get("username") if isinstance(related.get("username"), str) else None,
                           repl_get("{RELATED_USER_LOGIN}"), from_user.get("username"),
                           m.group(1) if m else None, recipient.get("username")),
    }
    pairs = repl if repl is not None else t.get("replacePairs")
    text = render_text(raw_text, pairs)
    href = notification_href(aid, user, refresh=type_key in MONEY)
    return _notice(aid, _js_str(t.get("id")), type_key, raw_type, user, text, href)


def notices_for(frame: Mapping[str, Any]) -> list[Notice]:
    """The notices one SSE frame earns (any type; [] for the rest, an Agency-wide one,
    or one with no account)."""
    if not isinstance(frame, Mapping) or frame.get("__agency") is not None:
        return []
    aid = frame.get("__account_id")
    if not aid:
        return []
    aid = str(aid)
    if "api2_chat_message" in frame:
        return _dm(aid, frame)
    if "purchase_notified" in frame:
        return _purchase(aid, frame)
    toasts = frame.get("toasts")
    if isinstance(toasts, list):
        return [n for n in (_toast(aid, t) for t in toasts) if n is not None]
    return []


def payload(n: Notice) -> dict[str, Any]:
    """The push body (JSON, encrypted by push_send) the service worker shows. No `account_id`
    for a notice without a Creator (the test): the worker always shows that one. Capped so it
    always fits the push service's 4 KB (UTF-8, push_send.wire): title TITLE_MAX, body BODY_MAX
    chars; an href over HREF_MAX is dropped (the worker opens "/"), never cut mid-escape."""
    href = n.href if n.href is None or len(n.href) <= HREF_MAX else None
    out = {"v": 1, "tag": n.tag, "title": _cap(n.title, TITLE_MAX), "body": _cap(n.body), "href": href,
           "type": n.raw_type, "account_id": n.account_id, "icon": ICON}
    if not n.account_id:
        del out["account_id"]
    return out


def urgency(n: Notice) -> str:
    return "high" if n.type_key in MONEY else "normal"
