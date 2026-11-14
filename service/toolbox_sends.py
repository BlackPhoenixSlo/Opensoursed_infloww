"""service/toolbox_sends.py — the Toolbox send tools' args and echo checks, pure (ultra step 4).

Send tools run only from an owner-approved Ultra plan (`toolbox.call(..., plan_step=...)`, that step `started` in the DB); never in
MCP tools/list nor on the token allowlist. Each schema is narrower than its route's body: only the fields the
plan card shows (Creator, audience, price, media, text). The text arg is `model_text`: `propose_plan` runs it
through send_chain before the plan is stored, and the executor sends it byte-for-byte.
"""
from __future__ import annotations

from typing import Annotated, Any, Mapping

from pydantic import Field, StrictInt, StringConstraints, model_validator

from toolbox_args import CREATOR as _CREATOR, Args

_MediaId = Annotated[StrictInt, Field(gt=0)]
_ListRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
_Text = Annotated[str, StringConstraints(min_length=1, max_length=5000)]
_ISO = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$"
MAX_MEDIA = 50
_TEXT = "The exact text OnlyFans shows. The plan stores it after the send chain; the owner approves it verbatim."
_MEDIA = "Vault media ids to attach (ids from vault_search)."
_PRICE = "Price in dollars; 0 = free. A paid one locks the media (previews stay free)."
_PREVIEWS = "Media ids (a subset of media_files) shown free on a paid one."


class _Paid(Args):
    media_files: list[_MediaId] = Field(default_factory=list, max_length=MAX_MEDIA, description=_MEDIA)
    price: float = Field(0, ge=0, description=_PRICE)
    previews: list[_MediaId] = Field(default_factory=list, max_length=MAX_MEDIA, description=_PREVIEWS)

    @model_validator(mode="after")
    def _previews_in_media(self):
        if not set(self.previews) <= set(self.media_files):
            raise ValueError("previews must be ids from media_files")
        if self.price > 0 and not self.media_files:
            raise ValueError("a price needs media_files to lock")
        return self


class MassSendArgs(_Paid):
    account_id: str = Field(description=_CREATOR)
    text: _Text = Field(description=_TEXT)
    user_lists: list[_ListRef] = Field(
        default_factory=list, max_length=20,
        description="Lists to send to: 'fans' (active subscribers), 'following' (followers, free and expired "
                    "included), or OnlyFans list ids. Everyone = both 'fans' and 'following'.")
    user_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(
        default_factory=list, max_length=1000, description="OnlyFans fan ids to send to (added to the lists).")
    excluded_user_lists: list[_ListRef] = Field(default_factory=list, max_length=20,
                                                description="OnlyFans list ids whose fans are left out.")
    scheduled_date: str | None = Field(None, pattern=_ISO,
                                       description="ISO 8601 with offset (2026-06-01T18:00:00+00:00); omit to send now.")

    @model_validator(mode="after")
    def _has_audience(self):
        if not self.user_lists and not self.user_ids:
            raise ValueError("name an audience: user_lists or user_ids")
        return self


class PostCreateArgs(_Paid):
    account_id: str = Field(description=_CREATOR)
    text: _Text = Field(description=_TEXT)
    posted_at: str | None = Field(None, pattern=_ISO,
                                  description="Schedule for this ISO 8601 time with offset; omit to post now.")
    expire_days: int | None = Field(None, ge=1, description="Delete the post after this many days.")


def _no_id(what: str) -> str:
    return f"OnlyFans answered with no {what} id; it may have gone out; do not retry; open open_url to check"


def check_mass_send(args: Mapping[str, Any], body: Any) -> str | None:
    """OF's queue item carries its id; without one nothing proves the mass was queued (or that it was not)."""
    return None if isinstance(body, Mapping) and body.get("id") is not None else _no_id("mass message")


def check_post_create(args: Mapping[str, Any], body: Any) -> str | None:
    return None if isinstance(body, Mapping) and body.get("id") is not None else _no_id("post")


def kept_note(body: Any) -> str | None:
    """The mass route's `_user_ids_kept` ({asked, kept}: the plan's fan ids left after its opt-out / queued-send
    guards) → a plain note when fewer went out than were approved; None otherwise (a post never has one)."""
    k = body.get("_user_ids_kept") if isinstance(body, Mapping) else None
    asked, kept = (k.get("asked"), k.get("kept")) if isinstance(k, Mapping) else (None, None)
    if not (isinstance(asked, int) and isinstance(kept, int)) or kept >= asked:
        return None
    return f"sent to {kept} of {asked} fans by id: {asked - kept} skipped (opted out or already queued)"


# ── the plan card's send rows (ultra_decide.card) ───────────────────────────

SHOW_IDS = 10  # ids a card row lists before "+N more"


def _money(v: Any) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "free" if v == 0 else f"${v:,.2f}"
    return str(v)


def _ids(xs: list[Any]) -> str:
    """A list of literal ids for the card: the first SHOW_IDS, then how many more."""
    more = f" +{len(xs) - SHOW_IDS} more" if len(xs) > SHOW_IDS else ""
    return ", ".join(map(str, xs[:SHOW_IDS])) + more


def _audience(args: Mapping[str, Any]) -> str:
    parts = [f"lists {', '.join(map(str, args['user_lists']))}"] if args.get("user_lists") else []
    if args.get("user_ids"):
        parts.append(f"{len(args['user_ids'])} fan(s) by id: {_ids(args['user_ids'])}")
    out = " + ".join(parts) or "nobody"
    if args.get("excluded_user_lists"):
        out += f", minus lists {', '.join(map(str, args['excluded_user_lists']))}"
    return out


def card_rows(kind: str, args: Mapping[str, Any]) -> list[list[str]]:
    """A send step's card rows after its Creator (`kind`: the tool's text_kind, "mass" | "post"): audience with
    the fan ids, price, media ids, schedule, free previews, expiry. Literal args only (a send has no reference)."""
    media = args.get("media_files") or []
    rows = [["Audience", _audience(args) if kind == "mass" else "her feed (every subscriber)"],
            ["Price", _money(args.get("price", 0))],
            ["Media", f"{len(media)}: {_ids(media)}" if media else "none"],
            ["When", str(args.get("scheduled_date") or args.get("posted_at") or "now")]]
    if args.get("previews"):
        rows.append(["Free previews", f"{len(args['previews'])}: {_ids(args['previews'])}"])
    if args.get("expire_days"):
        rows.append(["Expires after", f"{args['expire_days']} day(s)"])
    return rows
