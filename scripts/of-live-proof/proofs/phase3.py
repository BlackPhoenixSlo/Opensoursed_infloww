"""Phase 3's proofs (docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md): one `Proof` per OF settings, privacy
and link control, naming its sweep `page` and `control` label; kind `live` (undone, Lockout controls tagged `lockout`
and run last), `mocked` for Close all sessions and Reset stream key (D3/D12), `oauth` for a hand-off (Phase 0's
format, data only). Each Phase 3 control ticket adds its own; empty until then (ticket 57). Its capture record is
`docs/of-manager/captures/<section>--<control-slug>.json` with the same label and page.

    ./venv/bin/python -I scripts/of-live-proof/proofs/phase3.py --ids | --check-records <dir> | --check-sweep <sweep> <dir>

The same command line as Phase 2's `proofs/phase2.py` (proof_list.py says what each does).
"""
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
    """The declared effect of a switch or setting: the read value moved (a no-op write cannot pass)."""
    return before is not None and after != before


# ticket 60: the Tip-from-free-followers switch, Fully private and the email Update frequency (ofMirrorSettingsWrites).
# Each undo is the same PATCH with the before read's value (`Write.relay_body`), the app's own Known body.
def read_tip(get, fan):
    """settings' canAcceptMessageOnlyFromFriends (GET /users/me/settings)."""
    return get(_SETTINGS, {}).get("canAcceptMessageOnlyFromFriends")


def read_private(get, fan):
    return get(_SETTINGS, {}).get("isPrivate")


def read_digest(get, fan=None):
    """New Likes Summary's {isEnabled, value} (hours) in the email transport's groups, and the master Email
    notifications switch (`email`, GET /users/me/settings). A missing key raises: a shape change fails the proof."""
    for g in get(_EMAIL, {"group": "1"}) or []:   # bare, OF answers a flat list (measured live 2026-11-21)
        for it in g.get("items") or []:
            if it.get("code") == _DIGEST:
                return {"isEnabled": it["isEnabled"], "value": it["value"],
                        "email": get(_SETTINGS, {})["isEmailNotificationsEnabled"]}
    return None


FREQUENCY_PARK = "parked — needs capture (ticket 12 sitting): "


def frequency_ready(before):
    """ticket 60: OnlyFans greys Update frequency unless Email notifications and New Likes Summary are both on
    (sitting 2026-11-21, settings-email.js: the list needs the master switch, the row needs the item), and the live
    account has both off. No capture record holds either switch's PATCH body (the sitting fired no write), so the
    proof sets nothing up: it parks naming the bodies it needs. On at 24 hours the menu offers only 24: nothing to
    change. No digest item (`before` None) or a missing key raises, so the proof fails, never parks green."""
    off = [name for name, on in (("Email notifications", before["email"]),
                                 ("New Likes Summary", before["isEnabled"])) if not on]
    if off:
        return FREQUENCY_PARK + ", ".join(f"{n} switch body" for n in off)
    if (before["value"] or 24) == 24:
        return "parked — New Likes Summary is at 24 hours: the menu offers no other choice until OnlyFans's list is " \
               "captured (ticket 12 sitting)"
    return None


# Not in PROOFS (parked): free-page-only (tipRow hides it when subscribePrice > 0); the Proof Creator is priced (capture
# 2026-11-21), and so is FakeOF's proof account (ticket 62); needs a free account.
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

# Needs Email notifications and New Likes Summary on, at hours other than 24: the menu offers the stored hours and 24
# until OF's list is captured (ticket 12 sitting); FakeOF's account has both on, at 12 (soak/fake_of/settings.py
# DIGEST_HOURS); `--fault email-off` starts it as the live account's, and the proof parks (frequency_ready).
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

# Not in PROOFS: the switch is drawn only for a non-adult performer, so it is not in the sweep (proof_list
# --check-sweep), and its Live proof is parked in ticket 78 until the owner names such an account (owner sheet item 10).
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

# ticket 63: Close all sessions cannot be undone, so its proof is Mocked (D3/D12): never started under --of live
# (`mocked: not run live`), title kept. In fake mode the app sends OF's DELETE /sessions (settings-sessions.js module
# 205489) and the Relay's own `_denied` backstop answers 403 before the Live guard, so FakeOF never sees it (a backstop
# drill); the app shows the red note. The live path is tickets 81 (the backstop lift) and 82 (the owner-go run).
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

# ticket 58: the wired hand-offs (app/lib/ofMirrorHandoffs.ts HANDOFFS), kind `live`: plain new-tab links, not OAuth
# (kind `oauth` needs a click that opens OnlyFans's page, of_browser.hand_off_problems). A read proof: its trigger waits
# for the Wired link with its URL (the page opens) and never clicks it, so no live link is made and no request leaves
# for OnlyFans or the provider. Spring's "here" stays parked (absent from OF's build, ticket 71).
# HANDOFFS is the one Python copy of the table: these proofs, settings_privacy.py's _HANDOFFS rows and dead_settings.py's
# HANDOFF/MARKED are built from it. Each row: (section, slug, page, control, url, how), the control as the sweep labels
# it; how: "link" (a Wired a[target=_blank], clicked), "press" (the same, pressed: More's State page backdrop takes the
# mouse, ticket 61's rule) or "field" (CONNECTED_FIELD, readonly and Wired, its click opens the page's link).
# r10 (record settings--handoff-pages, measured 2026-11-21): Google, X and Connected accounts hand off to OF's own
# measured pages (never OF's /trust call, never a csrf); Sign in with spotify to OF's Spotify settings page (inferred:
# the page is measured, its button doing the OAuth is the record's), on every page it shows.
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
    """A link: the Wired a[target=_blank] with its URL and text. The field: its own box (`.v-input`), found only when
    the field is Wired and readonly, by its label on the committed page ("Onlyfans username")."""
    if how == "field":
        sel, text = f"#content .v-input:has({CONNECTED_FIELD}[data-oi-wired][readonly])", "Onlyfans username"
    else:
        sel, text = f"#content a[data-oi-wired][target=_blank][rel='noopener noreferrer'][href='{url}']", control
    return Proof(id=f"{section}--{slug}", phase=3, page=page, control=control, kind="live",
                 trigger=(("text", sel, text),), settled=("text", sel, text))


PROOFS += tuple(_handoff(*h) for h in HANDOFFS)

# ticket 59: Streaming's Copy link (the server; ticket 78 runs it live). A read proof, no write: the trigger waits for
# the Wired button, never clicks it (the harness reads no clipboard; FakeOF serves /users/me/settings,
# soak/fake_of/settings.py, so a click would copy its synthetic server unseen). The copied value itself is the Mirror
# check's clipboard row (scripts/of-mirror-check/settings_privacy.py); comparing it with OnlyFans's settings live needs a
# clipboard step.
_COPY_SERVER = "#content button[data-oi-wired][data-oi-stream-copy='server']"
PROOFS += (
    Proof(id="settings--streaming-copy-link", phase=3, page="settings/streaming", control="Copy link", kind="live",
          trigger=(("text", _COPY_SERVER, "Copy link"),), settled=("text", _COPY_SERVER, "Copy link")),
)

# ticket 64: trial links' Create link (connector tickets 38/46: binder ofMirrorWrites TRIAL_SUBMIT and the Relay's POST
# /api/of/v2/trials already exist), handed by Phase 6 (spec Other decisions). One link named with the run's marker and
# the smallest bounded offer (1 subscriber, 1 day's expiration, 1 day free), read back from OnlyFans's /trials, undone
# with the Relay's existing Delete. Already Wired with no Not-yet title, so not in PROOFS (the sweep and check 1 are for
# Not-yet controls): WIRED_PROOFS joins proofs.ALL, and its record is checked by test_phase3_proof_list.py.
_TRIALS = "/api2/v2/trials"
_TRIAL_INPUT = ".modal.show input[at-attr='input']"
_PICK_ONE = "#oi-menu [data-oi-value='1']"


def read_trials(get, fan):
    """Every free trial link as (id, name, offer limit, free days), sorted: OnlyFans's GET /trials (a list), paged."""
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
    """The declared effect: exactly one link more, named with the run's marker, with the smallest offer picked."""
    new = _new_trials(before, after)
    return len(new) == 1 and next(iter(new))[1].startswith("oi-proof-") and next(iter(new))[2:] == (1, 1)


def find_marked_trial(before, after, marker):
    """A lost reply's finder (story 53): the one link new since `before` named exactly `marker`, else None."""
    new = [r for r in _new_trials(before, after) if r[1] == marker]
    return new[0][0] if len(new) == 1 else None


TRIAL_CREATE = Proof(
    id="settings--trial-create-link", phase=3, page="settings/subscription/trial-links/modal-1", control="Create link",
    kind="live",
    arm=(Write("POST", _TRIALS),),
    trigger=(("fill", _TRIAL_INPUT, "{marker}"),
             ("click", "#input-154"), ("click", _PICK_ONE),    # Offer limit: 1 subscriber
             ("click", "#input-174"), ("click", _PICK_ONE),    # Offer expiration: 1 day
             ("click", "#input-201"), ("click", _PICK_ONE),    # Free trial duration: 1 day
             ("click", ".modal-footer button[type='submit']")),
    # OF goes on to the links tab (the frame is replaced), which lists the new link by its name, the run's marker. The
    # earlier "(1 day free trial)" was already on the page (FakeOF's Alpha trial): in a batch, a POST the guard's pace
    # held reached the Relay after the driver had disarmed (measured, fake run 20261121T113630Z wire seq 36).
    settled=("text", "body", "{marker}", "settings/subscription/trial-links"),
    of_read=read_trials,
    effect=one_new_marked_trial,
    undo=(Write("DELETE", _TRIALS + "/{id}", relay="/api/of/v2/trials/{id}"),),
    find=find_marked_trial,
)

WIRED_PROOFS = (TRIAL_CREATE,)

# ticket 61: the tracking links Sort (base page, behind modal-1) and both kebab State pages' sort radios, read proofs.
# OnlyFans sorts (the field/sort pairing is `inferred`, D29); the mirror shows the served order, so the first row's
# name moves only when the sort reached OnlyFans. Behind the open modal Sort takes a key, not a click (the modal
# covers it); a modal's or State page's pick lands on the base page, where it settles. Each wait's name is OnlyFans's own
# sorted read's first row (`Expect`, live 2026-11-21: FakeOF's names were unfit), and the proof parks unless that row
# differs from OnlyFans's unsorted first row (the previous wait's for the next), never judged from the app's page
# (expects.py `resolve_expects`); the wire check needs the app's GET with each field and sort (`expect_problems`).
_T61, _T61_TRIAL = "settings/subscription/tracking-links", "settings/subscription/trial-links"
_T61_ROW, _T61_SORT = "[data-oi-row] .b-offer-join__details", "button[aria-label='Sort']"
_CAMPAIGNS = "/api2/v2/campaigns"


def _t61_radio(radio):
    return ("click", f"[role=menuitem]:has(#{radio}) > a.of-state-link")


def _t61_query(field, sort):
    """The Relay's sorted read (service/of_reads.py tracking_links_sorted / trial_links_sorted)."""
    return {"limit": 100, "offset": 0, "pagination": 1, "field": field, "sort": sort}


def _t61_read(path, field, sort):
    return lambda get, fan=None: get(path, _t61_query(field, sort))


def _names(key):
    """A {list} or bare-list read's row names, in OnlyFans's order."""
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

# ticket 62: the base page's openers rebuilt behind the link and promotion modals and kebab State pages, read proofs.
# Pressed on the page they sit on (the modal or backdrop takes a click), they land on the base page's modal, which
# shows. One proof per opener that changes page (a same-page one lands where it is).
_T62 = "settings/subscription"
_T62_OPENER, _T62_TITLE = "a.g-btn[data-oi-ny]", ".modal.show .modal-title"


def _t62(id, at, control, to, title):
    return Proof(id=f"settings--{id}", phase=3, page=f"{_T62}/{at}", control=control, kind="live",
                 trigger=(("press", f"{_T62_OPENER}[href$='/{to}']", "Enter"),),
                 settled=("text", _T62_TITLE, title, f"{_T62}/{to}"))


PROOFS += (_t62("tracking-links-create-new", "tracking-links/state-kebab", "Create new tracking link",
                "tracking-links/modal-1", "Create new tracking link"),)
# The trial and promotion openers need a priced performer (users/me canCreateTrial, canCreatePromotion, a price):
# FakeOF's proof account answers as the one measured on 2026-11-21 (soak/fake_of/automations.py PRICED_ME, record
# settings--priced-performer-openers.json), so they run in fake mode. Both passed live on 2026-11-21 (their records,
# docs/of-manager/captures/settings--{trial-links-create-new,promotion-start}.json).
PROOFS += (
    _t62("trial-links-create-new", "trial-links/state-kebab", "Create new free trial link", "trial-links/modal-1",
         "Free trial link"),
    _t62("promotion-start", "promotion-campaign/modal-2", "Start promotion campaign", "promotion-campaign/modal-1",
         "Promotion campaign for"),
)
# Not in PROOFS: Add bundle is disabled with all three bundle durations (capture 2026-11-21), so its modal opens only
# after removing a bundle (a write). Parked in ticket 62.
T62_PARKED = (
    _t62("promotion-add-bundle", "promotion-campaign/modal-1", "Add bundle", "promotion-campaign/modal-2",
         "ADD SUBSCRIPTION BUNDLE"),
)

# ticket 74: tracking links' "Shared with you" tab and share hint (record settings--tracking-shared-with-you, measured-
# in-js; one record, its label the tab's). The tab is a read proof on each page (pressed behind modal-1 and the kebab
# State page, landing on the base page's tab). The hint's Share is one Narrowed write: POST /campaigns/share-access
# {campaignId, userId} for the first own link, read back from OnlyFans's own list (its `sharedWith`, `inferred`: the
# record names the field on the shared list), undone with OF's DELETE carrying the same body. Fake-only: the pick is
# FakeOF's synthetic peer (soak/fake_of/links.py PERFORMERS), never a real creator; its Live proof needs the owner to name
# a peer creator (ticket 79). Both bodies pinned to FakeOF's first served link (6102): the harness tells a callable
# put-back undo from its write by body (ticket 60), and this undo's body is the write's own.
_T74, _T74_PEER, _T74_PEER_ID = "settings/subscription/tracking-links", "synthpeer", 7401
_T74_SHARED = "/api2/v2/campaigns/share-access"
_T74_BODY = {"campaignId": 6102, "userId": _T74_PEER_ID}   # FakeOF's first served link (soak/fake_of/links.py)
_T74_SHARED_READ = {"limit": 100, "offset": 0, "pagination": 1, "with_deleted": 1, "sorting_deleted": 1, "stats": "true"}


def read_shared_with_you(get, fan):
    """Shared with you's links as (id, owner's username), OnlyFans's GET /campaigns/share-access as the tab reads it."""
    return [(str(c.get("id")), (c.get("user") or {}).get("username"))
            for c in (get(_T74_SHARED, _T74_SHARED_READ) or {}).get("list") or [] if isinstance(c, dict)]


def read_own_links(get, fan):
    """The model's own links in OnlyFans's served order as (id, shared with), GET /campaigns as the page reads it."""
    r = get("/api2/v2/campaigns", {}) or {}
    rows = r.get("list") if isinstance(r, dict) else r
    return [(int(c["id"]), (c.get("sharedWith") or {}).get("username"))
            for c in rows or [] if isinstance(c, dict) and "id" in c]


def shared_first_with_peer(before, after):
    """The declared effect: the first link (the hint clicked) now shared with the peer, every other link as it was."""
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

# ticket 66: Block by country and Block by IP, Lockout controls (tag `lockout`, run last, `--lockout` only). The picks
# are harmless pinned values: Tuvalu (TV) and 192.0.2.1 (TEST-NET-1, RFC 5737). OF's live GET /countries?all=1 has no
# Antarctica but has {code: "TV", name: "Tuvalu"} (measured live 2026-11-21); panel D30 picked a country matching no
# proxy exit, host, Browserbase region or the Proof fan. The app's Save goes through its own
# Relay route (BLOCKED_COUNTRIES / BLOCKED_IPS), which PUTs OF's /users/me/settings/security with the whole list
# (records settings--block-by-country / settings--block-by-ip, measured-in-js). The undo puts the before read's list
# back (`relay_body` a function of it, ticket 60's put-back on the write's own path), pinned to the empty list the
# effect requires, so it can never send anything else.
_SECURITY = "/api2/v2/users/me/settings/security"
_T66_COUNTRIES = {"blockedCountries": ["TV"], "blockedStates": []}
_T66_NO_COUNTRIES = {"blockedCountries": [], "blockedStates": []}
_T66_IPS, _T66_NO_IPS = {"blockedIps": ["192.0.2.1"]}, {"blockedIps": []}
_CONFIRM_OK = ("click", "#ModalConfirm .modal-footer button:last-child")


def read_blocked_countries(get, fan):
    """settings' blockedCountries and blockedStates (GET /users/me/settings), the body Block by country puts back."""
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
# ticket 67: Edit profile's cover upload (ofMirrorProfileImages; capture record settings--profile-cover-avatar). The camera
# picks a 1x1 PNG, Save sends it up through the Relay's POST /users/me/profile-image (signed create, the storage PUT,
# the convert claim, `inferred`: the record says "params to verify"), then PATCH /users/me {header: <the item>}. OF's
# own Save sends only a new upload's item or "" (60518.js `Ye`: `e.header=ve.value.header`, the item `processFiles`
# answered in `Qe`, or `e.header=""` on remove), never a picture OF already has, so the undo puts the prior cover back
# the way the app sets one (`Write.relay_upload`): the before read's `header` picture, downloaded through the Relay's
# /img before the trigger and kept in the evidence folder, goes up again on the same Relay route and the same PATCH
# carries its new item. A Creator with no cover (or one /img cannot fetch) has nothing to put back: the proof stops
# before any write. Before the undo the app's page is left and its writes land (prove.py); the re-upload always goes
# out (one after-write read cannot prove an upload never saved stays unsaved). The upload gets a new
# URL, so the reads need only show a cover (`cover_back`); the undo holds when the cover read back after it is the kept
# picture (undo_driver.restored): OF re-encodes the re-upload and applies it late (measured live 2026-11-21: sha256
# differed, the URL changed again after the after-undo read, pixels within 1.45-4.47 of the kept original vs 61-64 for
# the grey test picture), so the after-undo read is retaken, up to 60 s, until it names a cover URL other than the
# before and after-write ones that has the kept picture's size and a mean absolute pixel difference under 12
# (undo_driver.picture_match; the kept bytes unchanged are not OF's re-encode, so they fail); a new URL that is not the
# kept picture (the late test write) waits on, and the last one decides at 60 s. Both sha256 stay in the report. `reverify --evidence <folder>` re-checks a past run's
# kept cover against the one served now, read only. FakeOF starts with a seeded cover and serves each upload late and
# re-encoded (soak/fake_of/settings.py).
# Avatar upload and the removes use the same route and write (Relay and vitest tests).
# The upload writes are Record video's (phase2 UPLOAD_ARMS, ticket 53): the same upload_media, so the storage PUT goes to
# S3_HOST alone (`facts.upload_host`, inferred: same code, this route's PUT not measured live yet). The undo's upload
# sends them again: undo Writes reversing no row (`reverses=()`), so the guard takes each once more as a reversal.
_PROFILE_CAMERA = ".b-profile__header > .b-profile__header__cover__btns button.dropdown-toggle"


def read_cover(get, fan=None):
    """users/me's `header` (the cover's URL, or None) and `headerSize` (evidence only; the picture decides)."""
    me = get(_ME, {})
    return {"header": me.get("header"), "headerSize": me.get("headerSize")}


def cover_set(before, after):
    """There was a cover and now another one shows (the upload)."""
    return (before is not None and bool(before["header"]) and bool((after or {}).get("header"))
            and after["header"] != before["header"])


def cover_back(before, after_undo):
    """A cover shows where there was one (its URL is new after an upload; its picture decides, undo_driver.restored)."""
    return bool((before or {}).get("header")) and bool((after_undo or {}).get("header"))


COVER = Proof(
    id="settings--profile-cover-avatar", phase=3, page="settings/profile", control="[btn.dropdown-toggle]", kind="live",
    tags=frozenset({OFM_NEW_WRITES}),   # a write bound only with the switch on (ofMirrorWrites `save && newWrites`)
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

# ticket 68: Edit profile's About format button (ofMirrorProfileFormat; capture record settings--profile-about-format,
# measured in OF's JS). The button opens the toolbar and sends nothing; the proof selects the whole Bio, Bolds it and
# Saves: PATCH /users/me {about: OF's HTML}. The undo re-sends the before read's bio (the record's re-PATCH, `inferred`),
# so it puts back exactly that text; OF's `rawAbout` (when it sends one) is read before `about`, which may be OF's
# rendering of it (an ASSUMPTION until ticket 79's live read). `<br />` and `<br>` read the same (the Relay's
# sanitizer writes `<br>`).
_BIO = "[data-placeholder='Bio']"


def read_about(get, fan):
    """users/me's bio as OF stores it (`rawAbout` first), `<br />` read as `<br>`."""
    me = get(_ME, {})
    about = me.get("rawAbout") if isinstance(me.get("rawAbout"), str) else me.get("about")
    return {"about": about.replace("<br />", "<br>").replace("<br/>", "<br>") if isinstance(about, str) else about}


def about_bolded(before, after):
    """The bio had no bold and now holds OF's `<strong>`."""
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

# ticket 69: Social media's Add button (ofMirrorProfileLinks; capture record settings--social-media-buttons, measured in
# OF's JS). The form picks a provider from GET /init's socialMediaProviders (Instagram, a username provider: OF's form
# sends `{socialMedia: "instagram", label, link: "", username}`); Label is the run's marker, Username `instagram`
# (Instagram's own public account). Measured live 2026-11-21: a made-up handle (`oi_proof_<run>`) got OF's 400 "Invalid
# username or link." after ~8 s (ASSUMPTION, inferred: OF checks the handle exists on Instagram). OF answers the full list, so the new button's id comes from the read (`find`): the one
# button new since `before` labelled with the run's marker. Measured live 2026-11-21: the old host-inferred body
# (`socialMedia: "example"`) got OF's 400 "SocialMedia contains invalid value". Undone with the record's DELETE
# /users/social/buttons/{id}.
_SOCIAL = "/api2/v2/users/social/buttons"


def read_social(get, fan=None):
    """Every social media button as (id, label, link, username), sorted: OnlyFans's GET /users/social/buttons (a list)."""
    return sorted((str(b["id"]), str(b.get("label") or ""), str(b.get("link") or ""), str(b.get("username") or ""))
                  for b in (get(_SOCIAL, {}) or []) if isinstance(b, dict) and "id" in b)


def _new_buttons(before, after):
    return set(map(tuple, after or [])) - set(map(tuple, before or []))


def one_new_marked_button(before, after):
    """The declared effect: exactly one button more, labelled with the run's marker."""
    new = _new_buttons(before, after)
    return before is not None and len(new) == 1 and next(iter(new))[1].startswith("oi-proof-")


def find_marked_button(before, after, marker):
    """The new button's id (OF's reply is the list, no id): the one button new since `before` labelled `marker`."""
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

# ticket 70: Things I Like's Create link (capture record settings--things-i-like-links).
_LIKED = "/api2/v2/users/links"
_LIKED_URL = "https://www.youtube.com/watch?v="


def read_liked(get, fan):
    """Every Things I Like link as (id, url), sorted: OnlyFans's GET /users/links (a list of {id, sort, url, title,
    description, image}, measured live 2026-11-21: the link is `url`, there is no `link` key)."""
    return sorted((str(x["id"]), str(x.get("url") or ""))
                  for x in (get(_LIKED, {}) or []) if isinstance(x, dict) and "id" in x)


def one_new_marked_link(before, after):
    """The declared effect: exactly one link more, carrying the run's marker."""
    new = _new_buttons(before, after)
    return before is not None and len(new) == 1 and next(iter(new))[1].startswith(_LIKED_URL + "oi-proof-")


def find_marked_link(before, after, marker):
    """The new link's id (OF's reply is the list, no id): the one link new since `before` carrying `marker`."""
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

# ticket 72: Streaming's OBS server dropdown, a display switch (its capture record: OF's local `selectedServer`, no
# request). A read proof: picking OBS Server (mux_direct) shows that choice, and the Server field shows that choice's
# server from the settings read (drawObsServer marks the field `data-oi-obs-shown` once it has drawn that choice from
# the read, its server empty or not: OF may hold none (live 2026-11-21: empty for both choices on the Proof Creator); the settled wait
# reads text, so it waits for the marked field's own label). Nothing armed, so any write fails it.
_OBS_SHOWN = "#content .v-select__selection"
_OBS_SERVER_SHOWN = "#content .v-text-field__slot:has(input[data-oi-obs-shown='mux_direct']) label.v-label"
PROOFS += (
    Proof(id="settings--streaming-obs-server-dropdown", phase=3, page="settings/streaming", control="[INPUT]", kind="live",
          trigger=(("click", "label[for=input-677]"), ("click", "#oi-menu [data-oi-value='mux_direct']"),
                   ("text", _OBS_SHOWN, "OBS Server")),
          settled=("text", _OBS_SERVER_SHOWN, "Server")),
)

# ticket 73: Streaming > Blocked users' Block a username and a row's remove (its capture record: POST
# /streams/users/{username}/block and DELETE /streams/users/{userId}/block, no body). Blocks the Proof fan by OF's
# default handle `u<id>` (ASSUMPTION: OF resolves it for any account, as its profile links do; overturned if the Proof
# fan's block needs its chosen username), reads OnlyFans's blocked list, and unblocks the new row as the undo. The
# fill types `{fan}`, so the proof parks while the Proof fan is unset (proof_core.fan_trigger); fake mode types
# FakeOF's synthetic fan. The block answers no id, so the row's id comes from the finder.
_STREAM_BLOCKED = "/api2/v2/streams/users/blocked"


def read_stream_blocked(get, fan):
    """Every stream-blocked user as (id, username), sorted: OnlyFans's GET /streams/users/blocked, paged."""
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
    """The declared effect: exactly one stream-blocked user more, none gone."""
    return len(_new_blocks(before, after)) == 1 and set(map(tuple, before or [])) <= set(map(tuple, after or []))


def find_new_block(before, after, marker):
    """The block's row id (its reply has none): the one user new in the list since `before`, else None."""
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

# ticket 76: Reset stream key, a Mocked proof (D12: irreversible, the old key dies; a Lockout control). Its request is
# the sitting's aborted capture (DELETE /streams/obs/key?type=<shown server>, no body). In fake mode it is a drill: it
# declares no undo and no run names it in an owner go, so the Live guard refuses it (class `no_undo`) before FakeOF and
# the app shows the red note; under --of live it is recorded `mocked: not run live`. The live run is ticket 82.
PROOFS += (
    Proof(id="settings--streaming-reset-stream-key", phase=3, page="settings/streaming", control="Reset",
          kind="mocked", tags=frozenset({"irreversible", "lockout"}),
          arm=(Write("DELETE", "/api2/v2/streams/obs/key"),),
          trigger=(("click", "#content button.g-btn.m-danger.m-flat"),
                   ("click", "#ModalConfirm .modal-footer button:last-child")),
          settled=("text", "#oi-note", "Could not reset the stream key: Not available in"),
          refused_as="no_undo"),
)

# ticket 71: Spring Store connect/disconnect, blocked: absent from OnlyFans's current build, so no request to capture
# (record docs/of-manager/captures/settings--spring-store-connect.json, parked "blocked: ..."). No proof until OnlyFans
# brings it back and the sitting captures it; its controls keep their Not-yet notes.

if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase3.py"))
