"""service/toolbox_sends.py — the Toolbox send tools' args and echo checks, pure (ultra step 4).

Send tools run only from an owner-approved Ultra plan (`toolbox.call(..., plan_step=...)`, that step `started` in the DB); never in
MCP tools/list nor on the token allowlist. Each schema is narrower than its route's body: only the fields the
plan card shows (Creator, audience, price, media, text). The text arg is `model_text`: `propose_plan` runs it
through send_chain before the plan is stored, and the executor sends it byte-for-byte. auto_mass / auto_story
make a switched-on automation rule instead (mass_premade / auto_stories from a vault folder).
"""
from __future__ import annotations

import math
from typing import Annotated, Any, Mapping

from pydantic import AfterValidator, Field, StrictInt, StringConstraints, field_validator, model_validator

from toolbox_args import CREATOR as _CREATOR, Args

_MediaId = Annotated[StrictInt, Field(gt=0)]
_ListRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
_Text = Annotated[str, StringConstraints(min_length=1, max_length=5000)]
_ISO = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$"
MAX_MEDIA = 50


def _whole_cents(v: float) -> float:
    """The card shows cents; a price with finer decimals would OK one figure and send another."""
    if not math.isfinite(v) or abs(v * 100 - round(v * 100)) > 1e-6:
        raise ValueError("price must be whole cents (e.g. 9.99)")
    return v


_Price = Annotated[float, AfterValidator(_whole_cents)]
_TEXT = "The exact text OnlyFans shows. The plan stores it after the send chain; the owner approves it verbatim."
_MEDIA = "Vault media ids to attach (ids from vault_search)."
_PRICE = "Price in dollars; 0 = free, else $3-$200. A paid one locks the media (previews stay free)."
_PREVIEWS = "Media ids (a subset of media_files) shown free on a paid one."


class _Paid(Args):
    media_files: list[_MediaId] = Field(default_factory=list, max_length=MAX_MEDIA, description=_MEDIA)
    price: _Price = Field(0, ge=0, description=_PRICE)
    previews: list[_MediaId] = Field(default_factory=list, max_length=MAX_MEDIA, description=_PREVIEWS)

    @field_validator("price")
    @classmethod
    def _price_band(cls, v: float) -> float:  # OnlyFans' own band; the same one the composer holds
        if v and not 3 <= v <= 200:
            raise ValueError("a price is 0 (free) or between $3 and $200")
        return v

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


# Automation-rule sends: an ON rule from a vault folder, over POST /admin/automation-rules (`rule_body`); the
# rule fires on the next executor tick, then every `every_hours`, until switched off.
_FOLDER = "Vault folder id to pull random photos from (of_folders_list)."
_EVERY = "Hours between runs; the first runs within a minute of this step starting. Runs until switched off."


class _Rule(Args):
    account_id: str = Field(description=_CREATOR)
    every_hours: int = Field(ge=1, le=720, description=_EVERY)


class AutoMassArgs(_Rule):
    text: _Text = Field(description=_TEXT)
    media_folder_id: int = Field(ge=1, description=_FOLDER)
    media_count: int = Field(1, ge=1, le=MAX_MEDIA, description="Photos per mass, picked at random each run.")
    price: _Price = Field(0, ge=0, description="Price in dollars; 0 = free. A paid one locks the photos.")
    user_lists: list[_ListRef] = Field(min_length=1, max_length=20, description=MassSendArgs.model_fields[
        "user_lists"].description)
    excluded_user_lists: list[_ListRef] = Field(default_factory=list, max_length=20,
                                                description="OnlyFans list ids whose fans are left out.")
    online_only: bool = Field(False, description="Only fans online when it runs.")
    unsend_after_hours: int | None = Field(None, ge=1, le=720, description="Unsend each mass after this many hours.")


class AutoStoryArgs(_Rule):
    folder_id: int = Field(ge=1, description=_FOLDER)
    per_run: int = Field(1, ge=1, le=10, description="Stories posted per run.")
    hours_to_live: int = Field(24, ge=0, le=720, description="Delete each story after this many hours (0 = keep).")


RULE_KIND = {"auto_mass": "mass_premade", "auto_story": "auto_stories"}
FOLDER_ARG = {"auto_mass": "media_folder_id", "auto_story": "folder_id"}  # an OF vault folder (of_folder_create)


def rule_body(kind: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """The validated args → create_rule's body: one ON rule of `RULE_KIND[kind]` on an interval."""
    knobs = {k: v for k, v in args.items()  # an unset knob (None / [] / False) is left out; 0 is a value
             if k not in ("account_id", "every_hours") and v is not None and v is not False and v != []}
    payload = {"messages": [knobs]} if kind == "auto_mass" else knobs
    return {"account_id": args["account_id"], "kind": RULE_KIND[kind], "every_seconds": args["every_hours"] * 3600,
            "payload": payload, "is_enabled": True}


def check_rule(args: Mapping[str, Any], body: Any) -> str | None:
    if isinstance(body, Mapping) and body.get("id") is not None and body.get("is_enabled") is True:
        return None
    return "the app answered with no switched-on rule; it may have been made; do not retry; open open_url to check"


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


# ── the plan card's send rows (ultra_card.card) ───────────────────────────

def _money(v: Any) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "free" if v == 0 else f"${v:,.2f}"
    return str(v)


def _ids(xs: list[Any]) -> str:
    """Every literal id a send uses, for the card: the owner's OK covers exactly these (bounded by the args'
    max_length: ≤1000 fan ids, ≤MAX_MEDIA media)."""
    return ", ".join(map(str, xs))


def _audience(args: Mapping[str, Any]) -> str:
    parts = [f"lists {', '.join(map(str, args['user_lists']))}"] if args.get("user_lists") else []
    if args.get("user_ids"):
        parts.append(f"{len(args['user_ids'])} fan(s) by id: {_ids(args['user_ids'])}")
    out = " + ".join(parts) or "nobody"
    if args.get("excluded_user_lists"):
        out += f", minus lists {', '.join(map(str, args['excluded_user_lists']))}"
    return out


def _rule_rows(kind: str, args: Mapping[str, Any], shown: Mapping[str, Any]) -> list[list[str]]:
    folder = shown.get(FOLDER_ARG[kind]) or f"vault folder {args[FOLDER_ARG[kind]]}"
    when = ["When", f"within a minute of this step starting, then every {args['every_hours']} h until switched off"]
    if kind == "auto_story":
        ttl = args.get("hours_to_live")
        return [["Audience", "her stories (every subscriber)"],
                ["Media", f"{args.get('per_run', 1)} random photo(s) per run from {folder}"],
                when, ["Deleted after", f"{ttl} h" if ttl else "not deleted by the app (OnlyFans expires stories "
                                                               "on its own)"]]
    aud = _audience(args) + (", online now only" if args.get("online_only") else "")
    return [["Audience", aud], ["Price", _money(args.get("price", 0))],
            ["Media", f"{args.get('media_count', 1)} random photo(s) per run from {folder}"],
            when, ["Unsend after", f"{args['unsend_after_hours']} h" if args.get("unsend_after_hours") else "never"]]


def card_rows(kind: str, args: Mapping[str, Any], shown: Mapping[str, Any] | None = None) -> list[list[str]]:
    """A send step's card rows after its Creator (`kind`: the tool's text_kind): audience with the fan ids,
    price, media ids, schedule, free previews, expiry; a rule's folder, interval and unsend / delete. Literal
    args; `shown`: arg name → what the card shows for a reference in it (ultra_card): media_files → rows in place
    of the Media row (a judge's picks), a rule's FOLDER_ARG → its words (a folder an earlier step makes)."""
    shown = shown or {}
    return _rule_rows(kind, args, shown) if kind in RULE_KIND else _send_rows(kind, args, shown)


def _send_rows(kind: str, args: Mapping[str, Any], shown: Mapping[str, Any]) -> list[list[str]]:
    media = args.get("media_files") or []
    rows = [["Audience", _audience(args) if kind == "mass" else "her feed (every subscriber)"],
            ["Price", _money(args.get("price", 0))],
            *(shown.get("media_files") or [["Media", f"{len(media)}: {_ids(media)}" if media else "none"]]),
            ["When", str(args.get("scheduled_date") or args.get("posted_at") or "now")]]
    if args.get("previews"):
        rows.append(["Free previews", f"{len(args['previews'])}: {_ids(args['previews'])}"])
    if args.get("expire_days"):
        rows.append(["Expires after", f"{args['expire_days']} day(s)"])
    return rows
