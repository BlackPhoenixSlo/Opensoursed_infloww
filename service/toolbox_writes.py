"""service/toolbox_writes.py — the Toolbox write tools' args and echo checks, pure (step 3).

`toolbox_decide.TOOLS` names them; this module imports only the leaf `toolbox_args` of the
Toolbox, so either side loads first. A `check(args, answer)` exists only where the route can answer 2xx without
doing all that was asked (toolbox_decide module doc); None = the answer shows it, else why not.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping

from pydantic import Field, StrictBool, StrictInt, StringConstraints

from bio_pages.decide import RECORD_ID
from toolbox_args import CREATOR as _CREATOR, Args

MAX_MEDIA = 500  # media ids per folder write (a vault manager selection, not a whole vault)
_MediaId = Annotated[StrictInt, Field(gt=0)]
_FolderName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
_ID = f"^{RECORD_ID.pattern}$"
_PAGE_ID = "The bio page's id (an id from bio_pages_list or bio_page_create)."


class FolderCreateArgs(Args):
    account_id: str = Field(description=_CREATOR)
    name: _FolderName = Field(description="The new folder's name as it shows on OnlyFans (≤120 characters).")
    media_ids: list[_MediaId] = Field(default_factory=list, max_length=MAX_MEDIA,
                                      description="Vault media ids to put in it (ids from vault_search); may be empty.")


class FolderAddArgs(Args):
    account_id: str = Field(description=_CREATOR)
    list_id: int = Field(gt=0, description="The OnlyFans folder's id (an id from of_folders_list or of_folder_create).")
    media_ids: list[_MediaId] = Field(min_length=1, max_length=MAX_MEDIA,
                                      description="Vault media ids to add (ids from vault_search).")


class BioPageCreateArgs(Args):
    username: str = Field(pattern=r"^[a-z0-9_]{3,30}$",
                          description="The page's address name (3-30 lowercase letters, digits or _); "
                                      "the page lives at its public URL ending /<username>.")
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = \
        Field(None, description="Name shown on the page; omit to use the Creator's OnlyFans name.")
    account_id: str | None = Field(None, description="The Creator the page is for (an id from creators_list): "
                                   "the page starts with a link to her OnlyFans and can use her vault photos.")


class BioPageArgs(Args):  # bio_page_get's
    pid: str = Field(pattern=_ID, description=_PAGE_ID)


class BioVaultImageArgs(Args):
    pid: str = Field(pattern=_ID, description=_PAGE_ID)
    media_id: _MediaId = Field(description="A photo's media id from the page's Creator's vault (vault_search).")


class BioLinkAddArgs(Args):
    pid: str = Field(pattern=_ID, description=_PAGE_ID)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(
        description="The button's text.")
    destination: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] = Field(
        description="Where the button goes: a URL starting https:// or http://.")
    icon: Literal["onlyicon", "linkicon", "twitchicon", "igicon"] | None = Field(
        None, description="A stock icon: onlyicon (OnlyFans), linkicon, twitchicon, igicon (Instagram); omit for none.")
    is_adult: StrictBool = Field(False, description="Put an 18+ age gate in front of the link.")
    tracking: StrictBool = Field(False, description="OnlyFans tracking: adds a tracking code so OnlyFans credits "
                                 "each subscriber to its source (for a link to the Creator's OnlyFans).")


class BioLinkBgArgs(Args):
    pid: str = Field(pattern=_ID, description=_PAGE_ID)
    lid: str = Field(pattern=_ID, description="The link's id (a links[].id of that bio page).")
    media_id: _MediaId = Field(description="A photo's media id from the page's Creator's vault (vault_search).")


def check_folder_create(args: Mapping[str, Any], body: Any) -> str | None:
    """The route swallows a failed media add (added 0) and echoes OnlyFans' own folder name."""
    if not isinstance(body, Mapping) or body.get("id") is None:
        # Not "check of_folders_list": it hides empty folders, so a retry makes a second folder.
        return "OnlyFans answered with no folder id; the folder may already exist; do not retry; open open_url to check"
    fid, want, added = body["id"], len(args["media_ids"]), body.get("added")
    if added != want:
        return f"folder {fid}: {added} of {want} media added; add the rest with of_folder_add"
    if body.get("name") != args["name"]:
        return f"folder {fid} was created named {body.get('name')!r}, not {args['name']!r}"
    return None


def _profile(page: Any) -> Mapping[str, Any]:
    p = page.get("profile") if isinstance(page, Mapping) else None
    return p if isinstance(p, Mapping) else {}


def _links(page: Any) -> list[Mapping[str, Any]]:
    links = page.get("links") if isinstance(page, Mapping) else None
    return [lk for lk in links if isinstance(lk, Mapping)] if isinstance(links, list) else []


def check_bio_page_create(args: Mapping[str, Any], body: Any) -> str | None:
    p = _profile(body)
    if not p.get("id"):
        return "the answer carries no bio page id; check bio_pages_list before retrying"
    for key in ("username", "account_id", *(("display_name",) if args.get("display_name") else ())):
        if p.get(key) != args.get(key):
            return f"bio page {p['id']}: {key} is {p.get(key)!r}, not {args.get(key)!r}"
    # The route swallows a failed OnlyFans profile read and still creates the page, without her link.
    if args.get("account_id") and not any(str(lk.get("destination") or "").startswith("https://onlyfans.com/")
                                          for lk in _links(body)):
        return f"page {p['id']} was created without the OnlyFans link; do not retry create; add it with bio_link_add"
    return None


def check_bio_link_add(args: Mapping[str, Any], body: Any) -> str | None:
    """The created link (the route's `link`) has the asked fields."""
    lk = body.get("link") if isinstance(body, Mapping) else None
    if not isinstance(lk, Mapping) or not lk.get("id"):
        return f"bio page {args['pid']}: the answer has no new link"
    want = {"title": args["title"], "destination": args["destination"], "icon_stock": args.get("icon"),
            "is_adult": args["is_adult"], "tracking": args["tracking"]}
    key = next((k for k, v in want.items() if lk.get(k) != v), None)
    if key is None:
        return None
    return f"bio page {args['pid']}: new link {lk['id']} has {key} {lk.get(key)!r}, not {want[key]!r}"
