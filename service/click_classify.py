"""Bounded labels for redirect click provenance."""
from __future__ import annotations
import re
from typing import NamedTuple
from urllib.parse import urlsplit

class ClickClass(NamedTuple):
    in_app: str | None
    ref: str | None

# ── classifiers (labels only: a miss never changes a count) ──────────

# Link previews and scripts, as whole tokens: no bare "bot" (Cubot phones carry it).
_BOT = re.compile(
    r"(?<![A-Za-z0-9])(?:facebookexternalhit|Facebot|Twitterbot|TelegramBot|WhatsApp|Slackbot|Discordbot|"
    r"LinkedInBot|Googlebot|bingbot|Applebot|curl|Wget|python-requests|python-httpx|Go-http-client|"
    r"HeadlessChrome)(?![A-Za-z0-9])", re.I | re.A)
# bio_pages/decide.py's in-app table (same regexes, same order; dedupe once both land).
_IN_APP = ((re.compile(r"Threads", re.I | re.A), "threads"), (re.compile(r"Instagram", re.I | re.A), "instagram"),
           (re.compile(r"FBAN|FBAV", re.I | re.A), "facebook"),
           (re.compile(r"musical_ly|Bytedance|TikTok", re.I | re.A), "tiktok"))
# Referer host suffix → bounded family label.
_REF = (("instagram.com", "instagram"), ("tiktok.com", "tiktok"), ("facebook.com", "facebook"),
        ("fb.com", "facebook"), ("t.co", "x"), ("x.com", "x"), ("twitter.com", "x"), ("reddit.com", "reddit"),
        ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("t.me", "telegram"), ("telegram.org", "telegram"),
        ("snapchat.com", "snapchat"))
_GOOGLE = re.compile(r"(?:^|\.)google(?:\.[a-z]{2,3}){1,2}$")
REF_FAMILIES = frozenset({family for _, family in _REF} | {"google", "other", ""})


def in_app(ua: str | None) -> str:
    """'bot' (link previews / scripts), else the in-app browser (threads|instagram|facebook|tiktok), else ''."""
    ua = ua or ""
    if _BOT.search(ua):
        return "bot"
    return next((name for rx, name in _IN_APP if rx.search(ua)), "")


def ref_family(referer: str | None) -> str:
    """The referer's site family by host suffix; 'other' when unknown or unparseable; '' when none."""
    if not referer or not referer.strip():
        return ""
    try:
        host = (urlsplit(referer.strip()).hostname or "").rstrip(".").lower()
    except ValueError:
        return "other"
    if not host:
        return "other"
    for suffix, family in _REF:
        if host == suffix or host.endswith("." + suffix):
            return family
    return "google" if _GOOGLE.search(host) else "other"


def classify(ua: str | None, referer: str | None) -> ClickClass:
    """Classify one click from its user agent and referer."""
    return ClickClass(in_app(ua), ref_family(referer))
