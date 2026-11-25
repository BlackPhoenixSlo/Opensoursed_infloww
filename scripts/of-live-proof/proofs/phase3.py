import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from expects import Expect  # noqa: E402
from proof_core import OFM_NEW_WRITES, Proof, RelayUpload, Write  # noqa: E402,F401
from proofs.phase2 import UPLOAD_ARMS  # noqa: E402

ZW = "\u200b"
TOAST = ("text", "#oi-toast", "Changes were saved")
_ME, _SETTINGS = "/api2/v2/users/me", "/api2/v2/users/me/settings"
_NOTIF, _EMAIL = "/api2/v2/users/settings/notifications", "/api2/v2/users/settings/notifications/email"
_DIGEST = "new_likes_digest"


def changed(before, after):
    return before is not None and after != before


def read_tip(get, fan):
    return get(_SETTINGS, {}).get("canAcceptMessageOnlyFromFriends")


def read_private(get, fan):
    return get(_SETTINGS, {}).get("isPrivate")


def read_digest(get, fan=None):
    # bare, OF answers a flat list (measured live).
    for g in get(_EMAIL, {"group": "1"}) or []:
        for it in g.get("items") or []:
            if it.get("code") == _DIGEST:
                return {"isEnabled": it["isEnabled"], "value": it["value"],
                        "email": get(_SETTINGS, {})["isEmailNotificationsEnabled"]}
    return None


FREQUENCY_PARK = "parked — needs capture (ticket 12 sitting): "


def frequency_ready(before):
    off = [name for name, on in (("Email notifications", before["email"]),
                                 ("New Likes Summary", before["isEnabled"])) if not on]
    if off:
        return FREQUENCY_PARK + ", ".join(f"{n} switch body" for n in off)
    if (before["value"] or 24) == 24:
        return "parked — New Likes Summary is at 24 hours: the menu offers no other choice until OnlyFans's list is " \
               "captured (ticket 12 sitting)"
    return None


TIP = Proof(
    id="settings--tip-from-free-followers", phase=3, page="settings/messaging", control="[b-checkbox-switcher]",
    kind="live",
    arm=(Write("PATCH", _ME),),
    trigger=(("click", "label[for=messageOnlyFromFriends]"),),
    settled=TOAST,
    of_read=read_tip,
    effect=changed,
    undo=(Write("PATCH", _ME, relay="/api/of/v2/users/me",
                relay_body=lambda before: {"canAcceptMessageOnlyFromFriends": before}),),
)

FREQUENCY = Proof(
    id="settings--email-update-frequency", phase=3, page="settings/notifications/email",
    control=ZW + "Update frequencyEvery 24 Hours", kind="live", tags=frozenset({OFM_NEW_WRITES}),
    reads=(_EMAIL,),
    arm=(Write("PATCH", _NOTIF),),
    trigger=(("click", "label[for=input-189]"), ("click", "#oi-menu [data-oi-value='24']")),
    settled=TOAST,
    of_read=read_digest,
    ready=frequency_ready,
    effect=changed,
    undo=(Write("PATCH", _NOTIF, relay="/api/of/v2/users/settings/notifications",
                relay_body=lambda before: {"notifications": {"email": [{"code": _DIGEST, "value": before["value"]}]}}),),
)

FULLY_PRIVATE = Proof(
    id="settings--fully-private", phase=3, page="settings/security", control="Fully private profile", kind="live",
    arm=(Write("PATCH", "/api2/v2/users/me/settings/security"),),
    trigger=(("click", "label[for=setting_isPrivate]"),),
    settled=TOAST,
    of_read=read_private,
    effect=changed,
    undo=(Write("PATCH", "/api2/v2/users/me/settings/security", relay="/api/of/v2/users/me/settings/security",
                relay_body=lambda before: {"isPrivate": before}),),
)

CLOSE_ALL = Proof(
    id="settings--close-all-sessions", phase=3, page="settings/account/sessions", control="Close all sessions",
    kind="mocked", tags=frozenset({"irreversible", "lockout"}),
    arm=(Write("DELETE", "/api2/v2/sessions"),),
    trigger=(("click", "#content .b-sessions-list button.g-btn"),
             ("click", "#ModalConfirm .modal-footer button:last-child")),
    settled=("text", "#oi-note", "Could not close sessions: Not available in"),
    refused_as="backstop",
)

PROOFS = (FREQUENCY, CLOSE_ALL)

_SPOTIFY, _CONNECTED = "https://onlyfans.com/my/settings/spotify", "https://onlyfans.com/my/settings/account/connected"
CONNECTED_FIELD = "#settings_connect_account"
HANDOFFS = (
    ("settings", "ethwallet-metamask", "settings/ethwallet", "https://metamask.io/download.html", "https://metamask.io/download.html", "link"),
    ("settings", "streaming-obs", "settings/streaming", "OBS", "https://obsproject.com/download", "link"),
    ("settings", "streaming-chat-link", "settings/streaming", "https://onlyfans.com/my/streaming/chat", "https://onlyfans.com/my/streaming/chat", "link"),
    ("settings", "streaming-obs-widgets", "settings/streaming", "https://obs-settings.onlyfans.com/", "https://obs-settings.onlyfans.com/", "link"),
    ("settings", "account-google-sign-in", "settings/account/google", "Sign in with google", "https://onlyfans.com/my/settings/account/google", "link"),
    ("settings", "account-x-sign-in", "settings/account/x", "Sign in with X", "https://onlyfans.com/my/settings/account/x", "link"),
    ("settings", "account-connected-connect", "settings/account/connected", "Connect", _CONNECTED, "link"),
    ("settings", "account-connected-username", "settings/account/connected", "[INPUT]", _CONNECTED, "field"),
    ("settings", "spotify-sign-in", "settings/spotify", "Sign in with spotify", _SPOTIFY, "link"),
    ("profile", "spotify-sign-in", "profile/index", "Sign in with spotify", _SPOTIFY, "link"),
    ("profile", "media-spotify-sign-in", "profile/media", "Sign in with spotify", _SPOTIFY, "link"),
    ("profile", "state-more-menu-spotify-sign-in", "profile/state-more-menu", "Sign in with spotify", _SPOTIFY, "press"),
)


def _handoff(section, slug, page, control, url, how):
    if how == "field":
        sel, text = f"#content .v-input:has({CONNECTED_FIELD}[data-oi-wired][readonly])", "Onlyfans username"
    else:
        sel, text = f"#content a[data-oi-wired][target=_blank][rel='noopener noreferrer'][href='{url}']", control
    return Proof(id=f"{section}--{slug}", phase=3, page=page, control=control, kind="live",
                 trigger=(("text", sel, text),), settled=("text", sel, text))


PROOFS += tuple(_handoff(*h) for h in HANDOFFS)

_COPY_SERVER = "#content button[data-oi-wired][data-oi-stream-copy='server']"
PROOFS += (
    Proof(id="settings--streaming-copy-link", phase=3, page="settings/streaming", control="Copy link", kind="live",
          trigger=(("text", _COPY_SERVER, "Copy link"),), settled=("text", _COPY_SERVER, "Copy link")),
)

_TRIALS = "/api2/v2/trials"
_TRIAL_INPUT = ".modal.show input[at-attr='input']"
_PICK_ONE = "#oi-menu [data-oi-value='1']"


def read_trials(get, fan):
    rows, off = [], 0
    while True:
        page = get(_TRIALS, {"offset": off, "limit": 100}) or []
        rows += [(str(t["id"]), str(t.get("trialLinkName") or ""), t.get("subscribeCounts"), t.get("subscribeDays"))
                 for t in page if isinstance(t, dict) and "id" in t]
        if len(page) < 100:
            return sorted(rows)
        off += len(page)


def _new_trials(before, after):
    return set(map(tuple, after or [])) - set(map(tuple, before or []))


def one_new_marked_trial(before, after):
    new = _new_trials(before, after)
    return len(new) == 1 and next(iter(new))[1].startswith("oi-proof-") and next(iter(new))[2:] == (1, 1)


def find_marked_trial(before, after, marker):
    new = [r for r in _new_trials(before, after) if r[1] == marker]
    return new[0][0] if len(new) == 1 else None


TRIAL_CREATE = Proof(
    id="settings--trial-create-link", phase=3, page="settings/subscription/trial-links/modal-1", control="Create link",
    kind="live",
    arm=(Write("POST", _TRIALS),),
    trigger=(("fill", _TRIAL_INPUT, "{marker}"),
             ("click", "#input-154"), ("click", _PICK_ONE),
             ("click", "#input-174"), ("click", _PICK_ONE),
             ("click", "#input-201"), ("click", _PICK_ONE),
             ("click", ".modal-footer button[type='submit']")),
    settled=("text", "body", "{marker}", "settings/subscription/trial-links"),
    of_read=read_trials,
    effect=one_new_marked_trial,
    undo=(Write("DELETE", _TRIALS + "/{id}", relay="/api/of/v2/trials/{id}"),),
    find=find_marked_trial,
)

WIRED_PROOFS = (TRIAL_CREATE,)

_T61, _T61_TRIAL = "settings/subscription/tracking-links", "settings/subscription/trial-links"
_T61_ROW, _T61_SORT = "[data-oi-row] .b-offer-join__details", "button[aria-label='Sort']"
_CAMPAIGNS = "/api2/v2/campaigns"


def _t61_radio(radio):
    return ("click", f"[role=menuitem]:has(#{radio}) > a.of-state-link")


def _t61_query(field, sort):
    return {"limit": 100, "offset": 0, "pagination": 1, "field": field, "sort": sort}


def _t61_read(path, field, sort):
    return lambda get, fan=None: get(path, _t61_query(field, sort))


def _names(key):
    return lambda r: [x.get(key) for x in ((r.get("list") if isinstance(r, dict) else r) or []) if isinstance(x, dict)]


def _t61_first(path, field, sort):
    return Expect(path, _t61_query(field, sort), _names("trialLinkName" if path == _TRIALS else "campaignName"))


PROOFS += (
    Proof(id="settings--tracking-links-sort", phase=3, page=_T61, control="Sort", kind="live",
          trigger=(("click", _T61_SORT), ("click", "#oi-menu [data-oi-value='name']"),
                   ("text", _T61_ROW, _t61_first(_CAMPAIGNS, "name", "desc")),
                   ("click", _T61_SORT), ("click", "#oi-menu [data-oi-value='asc']")),
          settled=("text", _T61_ROW, _t61_first(_CAMPAIGNS, "name", "asc")),
          of_read=_t61_read(_CAMPAIGNS, "name", "asc")),
    Proof(id="settings--tracking-links-sort-modal", phase=3, page=f"{_T61}/modal-1", control="Sort", kind="live",
          trigger=(("press", _T61_SORT, "Enter"), ("click", "#oi-menu [data-oi-value='name']")),
          settled=("text", _T61_ROW, _t61_first(_CAMPAIGNS, "name", "desc"), _T61),
          of_read=_t61_read(_CAMPAIGNS, "name", "desc")),
    Proof(id="settings--tracking-links-sort-radios", phase=3, page=f"{_T61}/state-kebab", control="[b-input-radio]",
          kind="live", trigger=(_t61_radio("campaign-field-name"),),
          settled=("text", _T61_ROW, _t61_first(_CAMPAIGNS, "name", "desc"), _T61),
          of_read=_t61_read(_CAMPAIGNS, "name", "desc")),
    Proof(id="settings--trial-links-sort-radios", phase=3, page=f"{_T61_TRIAL}/state-kebab", control="[b-input-radio]",
          kind="live", trigger=(_t61_radio("filter-claims_count"),),
          settled=("text", _T61_ROW, _t61_first(_TRIALS, "claims_count", "desc"), _T61_TRIAL),
          of_read=_t61_read(_TRIALS, "claims_count", "desc")),
)

_T62 = "settings/subscription"
_T62_OPENER, _T62_TITLE = "a.g-btn[data-oi-ny]", ".modal.show .modal-title"


def _t62(id, at, control, to, title):
    return Proof(id=f"settings--{id}", phase=3, page=f"{_T62}/{at}", control=control, kind="live",
                 trigger=(("press", f"{_T62_OPENER}[href$='/{to}']", "Enter"),),
                 settled=("text", _T62_TITLE, title, f"{_T62}/{to}"))


PROOFS += (_t62("tracking-links-create-new", "tracking-links/state-kebab", "Create new tracking link",
                "tracking-links/modal-1", "Create new tracking link"),)
PROOFS += (
    _t62("trial-links-create-new", "trial-links/state-kebab", "Create new free trial link", "trial-links/modal-1",
         "Free trial link"),
    _t62("promotion-start", "promotion-campaign/modal-2", "Start promotion campaign", "promotion-campaign/modal-1",
         "Promotion campaign for"),
)
T62_PARKED = (
    _t62("promotion-add-bundle", "promotion-campaign/modal-1", "Add bundle", "promotion-campaign/modal-2",
         "ADD SUBSCRIPTION BUNDLE"),
)

_T74, _T74_PEER, _T74_PEER_ID = "settings/subscription/tracking-links", "synthpeer", 7401
_T74_SHARED = "/api2/v2/campaigns/share-access"
_T74_BODY = {"campaignId": 6102, "userId": _T74_PEER_ID}
_T74_SHARED_READ = {"limit": 100, "offset": 0, "pagination": 1, "with_deleted": 1, "sorting_deleted": 1, "stats": "true"}


def read_shared_with_you(get, fan):
    return [(str(c.get("id")), (c.get("user") or {}).get("username"))
            for c in (get(_T74_SHARED, _T74_SHARED_READ) or {}).get("list") or [] if isinstance(c, dict)]


def read_own_links(get, fan):
    r = get("/api2/v2/campaigns", {}) or {}
    rows = r.get("list") if isinstance(r, dict) else r
    return [(int(c["id"]), (c.get("sharedWith") or {}).get("username"))
            for c in rows or [] if isinstance(c, dict) and "id" in c]


def shared_first_with_peer(before, after):
    return bool(before) and before[0][1] != _T74_PEER and after == [(before[0][0], _T74_PEER), *before[1:]]


def _t74_tab(id, at, step):
    return Proof(id=f"settings--{id}", phase=3, page=f"{_T74}{at}", control="Shared with you", kind="live",
                 trigger=(step,), settled=("text", _T61_ROW, "Peer link", *((_T74,) if at else ())),
                 of_read=read_shared_with_you)


PROOFS += (
    Proof(id="settings--tracking-shared-with-you", phase=3, page=_T74, control="Shared with you", kind="live",
          fake_only=True,
          arm=(Write("POST", _T74_SHARED, body_must=_T74_BODY),),
          trigger=(("click", "[data-oi-row] [data-oi-share]"), ("fill", "#oi-share input", _T74_PEER),
                   ("click", "#oi-share [data-oi-performer]"), ("click", "#oi-share [data-oi-send]")),
          settled=("text", "#oi-toast", f"Link's statistics shared with @{_T74_PEER}"),
          of_read=read_own_links,
          effect=shared_first_with_peer,
          undo=(Write("DELETE", _T74_SHARED, body_must=_T74_BODY, relay="/api/of/v2/campaigns/share-access",
                      relay_body=_T74_BODY),)),
    _t74_tab("tracking-shared-with-you-tab", "", ("click", "#Shared-with-you")),
    _t74_tab("tracking-shared-with-you-tab-modal", "/modal-1", ("press", "#Shared-with-you", "Enter")),
    _t74_tab("tracking-shared-with-you-tab-kebab", "/state-kebab", ("press", "#Shared-with-you", "Enter")),
)

_SECURITY = "/api2/v2/users/me/settings/security"
_T66_COUNTRIES = {"blockedCountries": ["TV"], "blockedStates": []}
_T66_NO_COUNTRIES = {"blockedCountries": [], "blockedStates": []}
_T66_IPS, _T66_NO_IPS = {"blockedIps": ["192.0.2.1"]}, {"blockedIps": []}
_CONFIRM_OK = ("click", "#ModalConfirm .modal-footer button:last-child")


def read_blocked_countries(get, fan):
    s = get(_SETTINGS, {}) or {}
    return {"blockedCountries": s.get("blockedCountries"), "blockedStates": s.get("blockedStates")}


def read_blocked_ips(get, fan):
    return {"blockedIps": (get(_SETTINGS, {}) or {}).get("blockedIps")}


PROOFS += (
    Proof(id="settings--block-by-country", phase=3, page="settings/security/block_by_country", control="[INPUT]",
          kind="live", tags=frozenset({"lockout", OFM_NEW_WRITES}),
          arm=(Write("PUT", _SECURITY, body_must=_T66_COUNTRIES),),
          trigger=(("click", "#input-298"), ("click", "#oi-menu [data-oi-value='TV']"),
                   ("click", "#content .g-page__header .g-btn__wrapper button[type='submit']"), _CONFIRM_OK),
          settled=TOAST,
          of_read=read_blocked_countries,
          effect=lambda before, after: before == _T66_NO_COUNTRIES and after == _T66_COUNTRIES,
          undo=(Write("PUT", _SECURITY, body_must=_T66_NO_COUNTRIES,
                      relay="/api/of/v2/users/me/settings/security/blocked-countries",
                      relay_body=lambda before: dict(before)),)),
    Proof(id="settings--block-by-ip", phase=3, page="settings/security/block_by_ip", control="[TEXTAREA]",
          kind="live", tags=frozenset({"lockout", OFM_NEW_WRITES}),
          arm=(Write("PUT", _SECURITY, body_must=_T66_IPS),),
          trigger=(("fill", "#input-blocked-ips", "192.0.2.1"),
                   ("click", "#content .b-settings__row.g-btn__wrapper button:last-child"), _CONFIRM_OK),
          settled=TOAST,
          of_read=read_blocked_ips,
          effect=lambda before, after: before == _T66_NO_IPS and after == _T66_IPS,
          undo=(Write("PUT", _SECURITY, body_must=_T66_NO_IPS,
                      relay="/api/of/v2/users/me/settings/security/blocked-ips",
                      relay_body=lambda before: dict(before)),)),
)
_PROFILE_CAMERA = ".b-profile__header > .b-profile__header__cover__btns button.dropdown-toggle"


def read_cover(get, fan=None):
    me = get(_ME, {})
    return {"header": me.get("header"), "headerSize": me.get("headerSize")}


def cover_set(before, after):
    return (before is not None and bool(before["header"]) and bool((after or {}).get("header"))
            and after["header"] != before["header"])


def cover_back(before, after_undo):
    return bool((before or {}).get("header")) and bool((after_undo or {}).get("header"))


COVER = Proof(
    id="settings--profile-cover-avatar", phase=3, page="settings/profile", control="[btn.dropdown-toggle]", kind="live",
    tags=frozenset({OFM_NEW_WRITES}),
    arm=(*UPLOAD_ARMS, Write("PATCH", _ME)),
    trigger=(("file", _PROFILE_CAMERA, "oi-proof-cover.png"),
             ("click", ".g-btn__wrapper button[type='submit']")),
    settled=TOAST,
    of_read=read_cover,
    effect=cover_set,
    same=cover_back,
    undo=(*(replace(w, reverses=()) for w in UPLOAD_ARMS),
          Write("PATCH", _ME, relay="/api/of/v2/users/me", relay_body={"header": "{upload}"},
                relay_upload=RelayUpload("/api/of/v2/users/me/profile-image", {"kind": "header"},
                                         lambda read: read.get("header")))),
)
PROOFS += (COVER,)

_BIO = "[data-placeholder='Bio']"


def read_about(get, fan):
    me = get(_ME, {})
    about = me.get("rawAbout") if isinstance(me.get("rawAbout"), str) else me.get("about")
    return {"about": about.replace("<br />", "<br>").replace("<br/>", "<br>") if isinstance(about, str) else about}


def about_bolded(before, after):
    return (before is not None and "<strong>" not in str(before["about"] or "")
            and "<strong>" in str((after or {}).get("about") or ""))


ABOUT_FORMAT = Proof(
    id="settings--profile-about-format", phase=3, page="settings/profile", control="[g-btn.m-with-round-hover]",
    kind="live", tags=frozenset({OFM_NEW_WRITES}),
    arm=(Write("PATCH", _ME),),
    trigger=(("press", _BIO, "ControlOrMeta+a"),
             ("click", ".b-input-contenteditable .b-icon-text-container > button"),
             ("click", "[data-oi-about-format] [aria-label='Bold']"),
             ("click", ".g-btn__wrapper button[type='submit']")),
    settled=TOAST,
    of_read=read_about,
    effect=about_bolded,
    undo=(Write("PATCH", _ME, relay="/api/of/v2/users/me", relay_body=lambda before: {"about": before["about"] or ""}),),
)
PROOFS += (ABOUT_FORMAT,)

_SOCIAL = "/api2/v2/users/social/buttons"


def read_social(get, fan=None):
    return sorted((str(b["id"]), str(b.get("label") or ""), str(b.get("link") or ""), str(b.get("username") or ""))
                  for b in (get(_SOCIAL, {}) or []) if isinstance(b, dict) and "id" in b)


def _new_buttons(before, after):
    return set(map(tuple, after or [])) - set(map(tuple, before or []))


def one_new_marked_button(before, after):
    new = _new_buttons(before, after)
    return before is not None and len(new) == 1 and next(iter(new))[1].startswith("oi-proof-")


def find_marked_button(before, after, marker):
    new = [r for r in _new_buttons(before, after) if r[1] == marker]
    return new[0][0] if len(new) == 1 else None


SOCIAL_BUTTON = Proof(
    id="settings--social-media-buttons", phase=3, page="settings/social-media", control="Add button", kind="live",
    arm=(Write("PUT", _SOCIAL),),
    trigger=(("click", ".b-settings__row.g-btn__wrapper > button.g-btn"),
             ("select", "#oi-link-provider", "instagram"),
             ("fill", "#oi-link-label", "{marker}"),
             ("fill", "#oi-link-url", "instagram"),
             ("click", "[data-oi-link-save]")),
    settled=TOAST,
    of_read=read_social,
    effect=one_new_marked_button,
    undo=(Write("DELETE", _SOCIAL + "/{id}", relay="/api/of/v2/users/social/buttons/{id}"),),
    find=find_marked_button,
)
PROOFS += (SOCIAL_BUTTON,)

_LIKED = "/api2/v2/users/links"
_LIKED_URL = "https://www.youtube.com/watch?v="


def read_liked(get, fan):
    return sorted((str(x["id"]), str(x.get("url") or ""))
                  for x in (get(_LIKED, {}) or []) if isinstance(x, dict) and "id" in x)


def one_new_marked_link(before, after):
    new = _new_buttons(before, after)
    return before is not None and len(new) == 1 and next(iter(new))[1].startswith(_LIKED_URL + "oi-proof-")


def find_marked_link(before, after, marker):
    new = [r for r in _new_buttons(before, after) if r[1] == _LIKED_URL + marker]
    return new[0][0] if len(new) == 1 else None


THINGS_I_LIKE_LINK = Proof(
    id="settings--things-i-like-links", phase=3, page="settings/links", control="Create link", kind="live",
    tags=frozenset({OFM_NEW_WRITES}),
    arm=(Write("PUT", _LIKED),),
    trigger=(("click", ".b-settings__things-like__add > button.g-btn"),
             ("fill", "#oi-link-url", _LIKED_URL + "{marker}"),
             ("click", "[data-oi-link-save]")),
    settled=TOAST,
    of_read=read_liked,
    effect=one_new_marked_link,
    undo=(Write("DELETE", _LIKED + "/{id}", relay="/api/of/v2/users/links/{id}"),),
    find=find_marked_link,
)
PROOFS += (THINGS_I_LIKE_LINK,)

_OBS_SHOWN = "#content .v-select__selection"
_OBS_SERVER_SHOWN = "#content .v-text-field__slot:has(input[data-oi-obs-shown='mux_direct']) label.v-label"
PROOFS += (
    Proof(id="settings--streaming-obs-server-dropdown", phase=3, page="settings/streaming", control="[INPUT]", kind="live",
          trigger=(("click", "label[for=input-677]"), ("click", "#oi-menu [data-oi-value='mux_direct']"),
                   ("text", _OBS_SHOWN, "OBS Server")),
          settled=("text", _OBS_SERVER_SHOWN, "Server")),
)

_STREAM_BLOCKED = "/api2/v2/streams/users/blocked"


def read_stream_blocked(get, fan):
    rows, off = [], 0
    while True:
        page = get(_STREAM_BLOCKED, {"limit": 50, **({"offset": off} if off else {})}) or {}
        got = [u for u in page.get("list") or [] if isinstance(u, dict) and "id" in u]
        rows += [(str(u["id"]), str(u.get("username") or "")) for u in got]
        if not page.get("hasMore") or not got:
            return sorted(rows)
        off += len(got)


def _new_blocks(before, after):
    return set(map(tuple, after or [])) - set(map(tuple, before or []))


def one_new_block(before, after):
    return len(_new_blocks(before, after)) == 1 and set(map(tuple, before or [])) <= set(map(tuple, after or []))


def find_new_block(before, after, marker):
    new = sorted(_new_blocks(before, after))
    return new[0][0] if len(new) == 1 else None


PROOFS += (
    Proof(id="settings--streaming-block-username", phase=3, page="settings/streaming/blocked", control="Block",
          kind="live",
          arm=(Write("POST", "/api2/v2/streams/users/{fan}/block"),),
          trigger=(("fill", "#input-365", "u{fan}"), ("click", "#content .b-settings__content form button[type=submit]")),
          settled=TOAST,
          of_read=read_stream_blocked,
          effect=one_new_block,
          undo=(Write("DELETE", "/api2/v2/streams/users/{id}/block", relay="/api/of/v2/streams/users/{id}/block"),),
          find=find_new_block),
)

PROOFS += (
    Proof(id="settings--streaming-reset-stream-key", phase=3, page="settings/streaming", control="Reset",
          kind="mocked", tags=frozenset({"irreversible", "lockout"}),
          arm=(Write("DELETE", "/api2/v2/streams/obs/key"),),
          trigger=(("click", "#content button.g-btn.m-danger.m-flat"),
                   ("click", "#ModalConfirm .modal-footer button:last-child")),
          settled=("text", "#oi-note", "Could not reset the stream key: Not available in"),
          refused_as="no_undo"),
)


if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase3.py"))
