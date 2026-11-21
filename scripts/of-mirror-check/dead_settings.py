"""dead.py's Settings rows (ticket 57's Phase 3 hooks, tickets 58 to 63 and 66 to 76; dead.py's MODULES): writes
(ALLOWED, ALLOWED_RE), Wired controls (MARKED) and hand-off URLs (HANDOFF)."""
import os, re, sys
from collections import Counter
from pathlib import Path
# ticket 58: the hand-off table is proofs/phase3.py HANDOFFS (stdlib + of-live-proof's proof_core/proof_list only, no
# cycle). of-live-proof is appended to sys.path as in phase_check.py; proofs/phase3.py then inserts it at the front, so
# a same-named of-mirror-check module would be shadowed: keep names distinct.
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "of-live-proof"))
from proofs.phase3 import CONNECTED_FIELD, HANDOFFS as _HANDOFFS  # noqa: E402
from proof_list import live_passed as _live_passed, load_records as _load_records  # noqa: E402
MARKED=[]; ALLOWED=set(); ALLOWED_RE=[]; HANDOFF=[]; PHASE1=[]
# ticket 57: Phase 3 (docs/spec/ofm-not-yet/phase-03-settings-privacy-links.md, Testing Decisions, dead.py). Its control
# tickets append here, each in its `# ticket NN` block. Swept by `dead.py settings profile` (settings, its subscription
# pages and My profile; the sections were already in SECTIONS).
# - ALLOWED / ALLOWED_RE: each new settings/privacy write; MARKED: Phase 3's Wired controls.
# - HANDOFF: the hand-off table's URLs (app/lib/ofMirrorHandoffs.ts, exact). A visible a[data-oi-wired][target=_blank]
#   with one of these hrefs joins the swept controls (after the page's own, so their order holds), and a click that
#   opens a popup to one is a Wired control's or link's outcome: the request is recorded and aborted (no non-localhost
#   load); a popup to any other URL still fails as a non-localhost request.
# ticket 60: the drawn Tip-from-free-followers switch and Update frequency's select (ofMirrorSettingsWrites).
MARKED+=[
    (lambda p: p=="settings/messaging", "#messageOnlyFromFriends", False, 1),
    (lambda p: p=="settings/notifications/email", "#input-189", False, 1),
]
# ticket 63: Login sessions' Close all sessions (the Relay's backstop still refuses it).
ALLOWED|={("DELETE","/api/of/v2/sessions")}
MARKED+=[(lambda p: p=="settings/account/sessions", "#content .b-sessions-list button.g-btn", False, 1)]
# ticket 58: the hand-off table's wired links (app/lib/ofMirrorHandoffs.ts HANDOFFS; Python's: proofs/phase3.py HANDOFFS),
# Wired on their pages: each page's links (r10: Google, X, Connected accounts' Connect, Sign in with
# spotify on Settings › Spotify, My profile index, media, More) and Connected accounts' readonly field.
HANDOFF+=list(dict.fromkeys(u for *_, u, _how in _HANDOFFS))
_LINKS=Counter(page for _, _, page, _, _, how in _HANDOFFS if how!="field")
MARKED+=[(lambda p, page=page: p==page, "#content a[data-oi-wired][target=_blank]", False, n) for page, n in _LINKS.items()]
MARKED+=[(lambda p, page=page: p==page, f"{CONNECTED_FIELD}[readonly]", False, 1) for _, _, page, _, _, how in _HANDOFFS if how=="field"]
# ticket 59: Streaming's four Copy buttons (app/lib/ofMirrorStreamCopy.ts).
MARKED+=[(lambda p: p=="settings/streaming", "button[data-oi-stream-copy]", False, 4)]
# ticket 61: the tracking links Sort (base, modal-1, kebab) and the kebab State pages' sort radios.
MARKED+=[
    (lambda p: p.startswith("settings/subscription/tracking-links"), "button[aria-label='Sort']", False, 1),
    (lambda p: p=="settings/subscription/tracking-links/state-kebab", "input[name='campaign-field'], input[name='campaign-sort']", False, 7),
    (lambda p: p=="settings/subscription/trial-links/state-kebab", "input[name='trial-filter-field'], input[name='trial-order-dir']", False, 9),
]
# ticket 62: the base page's openers rebuilt behind the link and promotion modals and kebab State pages.
MARKED+=[
    (lambda p: p in ("settings/subscription/tracking-links/modal-1", "settings/subscription/tracking-links/state-kebab",
                     "settings/subscription/trial-links/modal-1", "settings/subscription/trial-links/state-kebab"), "a.g-btn[data-oi-ny]", False, 1),
    (lambda p: re.fullmatch(r"settings/subscription/promotion-campaign/modal-[123]", p), "a.g-btn[data-oi-ny]", False, 2),
]
# ticket 74: the tracking links "Shared with you" tab (base, modal-1, kebab) and the share hint's Share (ofMirrorSubscription).
ALLOWED|={("POST","/api/of/v2/campaigns/share-access")}
MARKED+=[(lambda p: p in ("settings/subscription/tracking-links", "settings/subscription/tracking-links/modal-1",
                          "settings/subscription/tracking-links/state-kebab"), "#Shared-with-you", False, 1)]
# ticket 75: none: modal-3's ⋮ stays disabled with the Not-yet title (capture-checklist rows 11, 23; ofMirrorOffers CLAIMS_TO_LIST).
# ticket 66: Block by country's picker and Save, Block by IP's field, Cancel and Save (ofMirrorSettingsWrites), on their
# own Relay routes.
ALLOWED|={("PUT","/api/of/v2/users/me/settings/security/blocked-countries"), ("PUT","/api/of/v2/users/me/settings/security/blocked-ips")}
MARKED+=[
    (lambda p: p=="settings/security/block_by_country", "#content .g-select__wrapper .v-input, #input-298, #content .g-page__header .g-btn__wrapper button[type='submit']", False, 3),
    (lambda p: p=="settings/security/block_by_ip", "#input-blocked-ips, #content .b-settings__row.g-btn__wrapper button", False, 3),
]
# ticket 67: Edit profile's cover and avatar cameras and the cover's remove (app/lib/ofMirrorProfileImages.ts); a picked
# image goes up through the Relay's profile image route before Save's PATCH /users/me.
ALLOWED|={("POST","/api/of/v2/users/me/profile-image")}
MARKED+=[
    (lambda p: p=="settings/profile", ".b-profile__header > .b-profile__header__cover__btns button", False, 2),
    (lambda p: p=="settings/profile", ".b-profile__user .g-avatar .b-profile__header__cover__btns button.dropdown-toggle", False, 1),
]
# ticket 68: Edit profile's About format button (app/lib/ofMirrorProfileFormat.ts): opens OF's text toolbar over the Bio
# (its own aria-expanded turns true: a change to its own markup), sends nothing.
MARKED+=[(lambda p: p=="settings/profile", ".b-input-contenteditable .b-icon-text-container > button", False, 1)]
# ticket 69: Social media's Add button (app/lib/ofMirrorProfileLinks.ts): opens its form (its own aria-expanded turns
# true); the form's Save PUTs /users/social/buttons, a drawn button's remove DELETEs it.
ALLOWED|={("PUT","/api/of/v2/users/social/buttons")}
ALLOWED_RE.append(("DELETE", re.compile(r"/api/of/v2/users/social/buttons/\d+")))
MARKED+=[(lambda p: p=="settings/social-media", ".b-settings__row.g-btn__wrapper > button.g-btn", False, 1)]
# ticket 70: Things I Like's Create link (app/lib/ofMirrorProfileLinks.ts): opens its form (its own aria-expanded turns
# true); the form's Save PUTs /users/links, a drawn link's delete DELETEs it.
ALLOWED|={("PUT","/api/of/v2/users/links")}
ALLOWED_RE.append(("DELETE", re.compile(r"/api/of/v2/users/links/\d+")))
MARKED+=[(lambda p: p=="settings/links", ".b-settings__things-like__add > button.g-btn", False, 1)]
# ticket 72: Streaming's OBS server dropdown (app/lib/ofMirrorObsServer.ts, bound in ofMirrorStreamCopy), a display switch.
MARKED+=[(lambda p: p=="settings/streaming", "#input-677", False, 1)]
# ticket 73: Blocked users' Block form (app/lib/ofMirrorStreamBlocked.ts bindStreamBlock). Rows' removes are drawn only when the list has rows (dead.py serves none).
ALLOWED_RE+=[("POST", re.compile(r"/api/of/v2/streams/users/[A-Za-z0-9._-]{1,24}/block")),
             ("DELETE", re.compile(r"/api/of/v2/streams/users/\d+/block"))]
MARKED+=[(lambda p: p=="settings/streaming/blocked", "#input-365, #content .b-settings__content form button[type=submit]", False, 2)]
# ticket 76: Streaming's Reset stream key (ofMirrorSettingsWrites), a Lockout control.
ALLOWED|={("DELETE","/api/of/v2/streams/obs/key")}
MARKED+=[(lambda p: p=="settings/streaming", "#content button.g-btn.m-danger.m-flat", False, 1)]
# ticket 110: Phase 5's browser-only controls (app/lib/ofMirrorBrowserOnly.ts), Wired, nothing sent:
# Reveal password flips its field (its aria-checked: a markup change), phone Cancel navigates to Account. The support
# mailto links are attribute-checked, not click-probed (settings_privacy.py checks their href). No HANDOFF row: row 10
# measured 2026-11-21 did not record Add card / Add a payment card / Add funds; parked — needs capture (re-sitting of row 10).
MARKED+=[
    (lambda p: p=="settings/account/password", "button[data-oi-browser-only='reveal']", False, 3),
    (lambda p: p=="settings/account/phone", "button[data-oi-browser-only='cancel']", False, 1),
    (lambda p: p in ("bank/dac7/edit", "settings/account/delete"), "#content a[href^='mailto:'][data-oi-wired]", False, 1),
]
# D1: the controls whose Live proof passed (2026-11-21, docs/of-manager/captures/<section>--<slug>.json, proof.verdict
# pass) are "proven" PHASE1 rows (dead.py: found, Wired, no Not-yet title): every hand-off and Connected's username
# field (account-connected-username) whose record passed, read from the records (_PASSED; the rest, e.g. MetaMask and
# Connected's Connect, are "not-yet" rows: Wired, title kept),
# Streaming's server Copy link (sweep label "Copy link", settings--streaming-copy-link; Copy key and the stream chat and
# OBS widgets Copy links keep their title: "not-yet" rows) and its OBS server dropdown (settings--streaming-obs-server-
# dropdown), the Create new tracking link and free trial link openers on modal-1 and the kebab State page and Start
# promotion campaign on the promotion modals (settings--{tracking,trial}-links-create-new, settings--promotion-start;
# gated, an opener shows OF's reason), Edit profile's About format button (settings--profile-about-format), Things I
# like's Create link (settings--things-i-like-links), the tracking links Sort and radios and email's Update frequency.
_CAPTURES=Path(__file__).resolve().parents[2]/"docs"/"of-manager"/"captures"
_PASSED={r.get("id") for _, r in _load_records(_CAPTURES)[0] if _live_passed(r)}
PHASE1+=[(page, f"css:{CONNECTED_FIELD}[data-oi-wired]" if how=="field" else f"css:#content a[data-oi-wired][href='{url}']",
           "proven" if f"{sec}--{slug}" in _PASSED else "not-yet")
         for sec, slug, page, _, url, how in _HANDOFFS]
_SUB="settings/subscription"
_opener=lambda dialog: f"css:a.g-btn[data-oi-ny][href$='/{dialog}'], a.g-btn[data-oi-ny][data-oi-href$='/{dialog}']"
PHASE1+=[
    ("settings/streaming", "css:button[data-oi-stream-copy='server']", "proven"),
    ("settings/streaming", "css:button[data-oi-stream-copy='chat'], button[data-oi-stream-copy='widgets']", "not-yet"),
    ("settings/streaming", "css:#content .v-select input[data-oi-wired]:not([type='hidden'])", "proven"),
    # ticket 72: while the dropdown is bound its Server and Stream Key fields are named (sweep labels of their own), no
    # Live proof: disabled, title kept.
    ("settings/streaming", "css:#content input[aria-label='Stream server address'], #content input[aria-label='Stream key']", "not-yet"),
    *((f"{_SUB}/{kind}-links/{page}", _opener(f"{kind}-links/modal-1"), "proven") for kind in ("tracking", "trial") for page in ("modal-1", "state-kebab")),
    *((f"{_SUB}/promotion-campaign/modal-{n}", _opener("promotion-campaign/modal-1"), "proven") for n in (1, 2, 3)),
    ("settings/profile", "css:.b-input-contenteditable .b-icon-text-container > button", "proven"),
    ("settings/links", "css:.b-settings__things-like__add > button.g-btn[data-oi-wired]", "proven"),
    # tickets 61, 60: the tracking links Sort on its three pages and the kebab page's radios (settings--tracking-links-
    # sort, -sort-modal: record settings--tracking-links-sort.json; -sort-radios), reads; email's Update frequency
    # select and its field (settings--email-update-frequency), one control, a write: its title drops only with
    # OFM_NEW_WRITES_ENABLED on (the dead.py mock answers it on).
    *((f"{_SUB}/tracking-links{at}", "css:button[aria-label='Sort'][data-oi-wired]", "proven") for at in ("", "/modal-1", "/state-kebab")),
    (f"{_SUB}/tracking-links/state-kebab", "css:input[name='campaign-field'][data-oi-wired], input[name='campaign-sort'][data-oi-wired]", "proven"),
    ("settings/notifications/email", "css:#content .v-select[data-oi-wired]:has(#input-189)", "proven"),
    # ticket 66: Block by country's picker (box and field, one control) and Block by IP's field (settings--block-by-
    # country, -ip), writes: their titles drop only with OFM_NEW_WRITES_ENABLED on.
    ("settings/security/block_by_country", "css:#content .g-select__wrapper .v-input[data-oi-wired], #input-298[data-oi-wired]", "proven"),
    ("settings/security/block_by_ip", "css:#input-blocked-ips[data-oi-wired]", "proven"),
    # ticket 67: Edit profile's cover camera passed Live (settings--profile-cover-avatar), a write: its title drops only
    # with OFM_NEW_WRITES_ENABLED on. The avatar's camera (own name "Change avatar") has no proof and keeps it.
    ("settings/profile", "css:.b-profile__header > .b-profile__header__cover__btns button.dropdown-toggle[data-oi-wired]", "proven"),
    ("settings/profile", "css:.b-profile__user .g-avatar button.dropdown-toggle[aria-label='Change avatar']", "not-yet"),
]
