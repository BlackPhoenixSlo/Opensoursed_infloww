import os, re, sys
from collections import Counter
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "of-live-proof"))
from proofs.phase3 import CONNECTED_FIELD, HANDOFFS as _HANDOFFS  # noqa: E402
from proof_list import live_passed as _live_passed, load_records as _load_records  # noqa: E402
MARKED=[]; ALLOWED=set(); ALLOWED_RE=[]; HANDOFF=[]; PHASE1=[]
MARKED+=[
    (lambda p: p=="settings/messaging", "#messageOnlyFromFriends", False, 1),
    (lambda p: p=="settings/notifications/email", "#input-189", False, 1),
]
ALLOWED|={("DELETE","/api/of/v2/sessions")}
MARKED+=[(lambda p: p=="settings/account/sessions", "#content .b-sessions-list button.g-btn", False, 1)]
HANDOFF+=list(dict.fromkeys(u for *_, u, _how in _HANDOFFS))
_LINKS=Counter(page for _, _, page, _, _, how in _HANDOFFS if how!="field")
MARKED+=[(lambda p, page=page: p==page, "#content a[data-oi-wired][target=_blank]", False, n) for page, n in _LINKS.items()]
MARKED+=[(lambda p, page=page: p==page, f"{CONNECTED_FIELD}[readonly]", False, 1) for _, _, page, _, _, how in _HANDOFFS if how=="field"]
MARKED+=[(lambda p: p=="settings/streaming", "button[data-oi-stream-copy]", False, 4)]
MARKED+=[
    (lambda p: p.startswith("settings/subscription/tracking-links"), "button[aria-label='Sort']", False, 1),
    (lambda p: p=="settings/subscription/tracking-links/state-kebab", "input[name='campaign-field'], input[name='campaign-sort']", False, 7),
    (lambda p: p=="settings/subscription/trial-links/state-kebab", "input[name='trial-filter-field'], input[name='trial-order-dir']", False, 9),
]
MARKED+=[
    (lambda p: p in ("settings/subscription/tracking-links/modal-1", "settings/subscription/tracking-links/state-kebab",
                     "settings/subscription/trial-links/modal-1", "settings/subscription/trial-links/state-kebab"), "a.g-btn[data-oi-ny]", False, 1),
    (lambda p: re.fullmatch(r"settings/subscription/promotion-campaign/modal-[123]", p), "a.g-btn[data-oi-ny]", False, 2),
]
ALLOWED|={("POST","/api/of/v2/campaigns/share-access")}
MARKED+=[(lambda p: p in ("settings/subscription/tracking-links", "settings/subscription/tracking-links/modal-1",
                          "settings/subscription/tracking-links/state-kebab"), "#Shared-with-you", False, 1)]
ALLOWED|={("PUT","/api/of/v2/users/me/settings/security/blocked-countries"), ("PUT","/api/of/v2/users/me/settings/security/blocked-ips")}
MARKED+=[
    (lambda p: p=="settings/security/block_by_country", "#content .g-select__wrapper .v-input, #input-298, #content .g-page__header .g-btn__wrapper button[type='submit']", False, 3),
    (lambda p: p=="settings/security/block_by_ip", "#input-blocked-ips, #content .b-settings__row.g-btn__wrapper button", False, 3),
]
ALLOWED|={("POST","/api/of/v2/users/me/profile-image")}
MARKED+=[
    (lambda p: p=="settings/profile", ".b-profile__header > .b-profile__header__cover__btns button", False, 2),
    (lambda p: p=="settings/profile", ".b-profile__user .g-avatar .b-profile__header__cover__btns button.dropdown-toggle", False, 1),
]
MARKED+=[(lambda p: p=="settings/profile", ".b-input-contenteditable .b-icon-text-container > button", False, 1)]
ALLOWED|={("PUT","/api/of/v2/users/social/buttons")}
ALLOWED_RE.append(("DELETE", re.compile(r"/api/of/v2/users/social/buttons/\d+")))
MARKED+=[(lambda p: p=="settings/social-media", ".b-settings__row.g-btn__wrapper > button.g-btn", False, 1)]
ALLOWED|={("PUT","/api/of/v2/users/links")}
ALLOWED_RE.append(("DELETE", re.compile(r"/api/of/v2/users/links/\d+")))
MARKED+=[(lambda p: p=="settings/links", ".b-settings__things-like__add > button.g-btn", False, 1)]
MARKED+=[(lambda p: p=="settings/streaming", "#input-677", False, 1)]
ALLOWED_RE+=[("POST", re.compile(r"/api/of/v2/streams/users/[A-Za-z0-9._-]{1,24}/block")),
             ("DELETE", re.compile(r"/api/of/v2/streams/users/\d+/block"))]
MARKED+=[(lambda p: p=="settings/streaming/blocked", "#input-365, #content .b-settings__content form button[type=submit]", False, 2)]
ALLOWED|={("DELETE","/api/of/v2/streams/obs/key")}
MARKED+=[(lambda p: p=="settings/streaming", "#content button.g-btn.m-danger.m-flat", False, 1)]
MARKED+=[
    (lambda p: p=="settings/account/password", "button[data-oi-browser-only='reveal']", False, 3),
    (lambda p: p=="settings/account/phone", "button[data-oi-browser-only='cancel']", False, 1),
    (lambda p: p in ("bank/dac7/edit", "settings/account/delete"), "#content a[href^='mailto:'][data-oi-wired]", False, 1),
]
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
    ("settings/streaming", "css:#content input[aria-label='Stream server address'], #content input[aria-label='Stream key']", "not-yet"),
    *((f"{_SUB}/{kind}-links/{page}", _opener(f"{kind}-links/modal-1"), "proven") for kind in ("tracking", "trial") for page in ("modal-1", "state-kebab")),
    *((f"{_SUB}/promotion-campaign/modal-{n}", _opener("promotion-campaign/modal-1"), "proven") for n in (1, 2, 3)),
    ("settings/profile", "css:.b-input-contenteditable .b-icon-text-container > button", "proven"),
    ("settings/links", "css:.b-settings__things-like__add > button.g-btn[data-oi-wired]", "proven"),
    *((f"{_SUB}/tracking-links{at}", "css:button[aria-label='Sort'][data-oi-wired]", "proven") for at in ("", "/modal-1", "/state-kebab")),
    (f"{_SUB}/tracking-links/state-kebab", "css:input[name='campaign-field'][data-oi-wired], input[name='campaign-sort'][data-oi-wired]", "proven"),
    ("settings/notifications/email", "css:#content .v-select[data-oi-wired]:has(#input-189)", "proven"),
    ("settings/security/block_by_country", "css:#content .g-select__wrapper .v-input[data-oi-wired], #input-298[data-oi-wired]", "proven"),
    ("settings/security/block_by_ip", "css:#input-blocked-ips[data-oi-wired]", "proven"),
    ("settings/profile", "css:.b-profile__header > .b-profile__header__cover__btns button.dropdown-toggle[data-oi-wired]", "proven"),
    ("settings/profile", "css:.b-profile__user .g-avatar button.dropdown-toggle[aria-label='Change avatar']", "not-yet"),
]
