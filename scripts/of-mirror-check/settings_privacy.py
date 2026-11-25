import copy, json, os, re, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_check as pc  # noqa: E402  (puts scripts/of-live-proof on the path)
from phase_check import check, url_of, open_page, settle, FIND, STATE, M, SINGLE, SINGLE_ID  # noqa: E402
from proof_core import Proof  # noqa: E402
from proof_list import record_of, live_passed, load_records  # noqa: E402
from proofs import phase3  # noqa: E402
NAME="settings-privacy"
STREAM_KEY="oi-synthetic-stream-key-5c1e"
STREAM_KEY_MASK="•"*16

REQUESTS=[]
RED_NOTES=[]
ROWS=[]
STATEFUL=[]
LIST_READS=set()
LIST_ITEM={}
_HANDOFFS=[(p, {"press":c} if how=="press" else c, u) for _, _, p, c, u, how in phase3.HANDOFFS]
ROWS+=[{"page":p, "steps":[c], "handoff":u} for p, c, u in _HANDOFFS]
_COPY=lambda c: f"css=button[data-oi-stream-copy='{c}']"
ROWS+=[{"page":"settings/streaming", "steps":[_COPY(c)], "clipboard":t} for c, t in (
    ("server","rtmp://synthetic.invalid/live"), ("key",STREAM_KEY),
    ("chat","https://onlyfans.com/my/streaming/chat"), ("widgets","https://obs-settings.onlyfans.com/"))]
READS={
    "/api/of/v2/users/me/settings": {"isAutoFollowBack":True,"streamingRtmpServer":"rtmp://synthetic.invalid/live","streamingRtmpKey":STREAM_KEY},
}
_ME, _SETTINGS, _SECURITY="/api/of/v2/users/me", "/api/of/v2/users/me/settings", "/api/of/v2/users/me/settings/security"
_NOTIF, _EMAIL="/api/of/v2/users/settings/notifications", "/api/of/v2/users/settings/notifications/email"
_TIP_SW, _TIP_ON="css=label[for=messageOnlyFromFriends]", "document.getElementById('messageOnlyFromFriends')?.checked ?? null"
_PRIV_SW, _PRIV_ON="css=label[for=setting_isPrivate]", "document.getElementById('setting_isPrivate')?.checked ?? null"
_PRIV_READS={_ME: {"id":1,"username":"alphaone","name":"Alpha One","isPerformer":True,"isAdultContent":False},
             _SETTINGS: {**READS[_SETTINGS], "isPrivate":False}}
_FREQ_READS={_EMAIL: [{"code":"you_and_your_posts","items":[{"code":"new_likes_digest","isEnabled":True,"value":12}]}]}
_FREQ=lambda h: ["css=label[for=input-189]", f"css=#oi-menu [data-oi-value='{h}']"]
_FREQ_SHOWN="document.getElementById('input-189')?.closest('.v-select')?.querySelector('.v-select__selection')?.textContent ?? null"
_freq_write=lambda h: ["PATCH", _NOTIF, {"notifications":{"email":[{"code":"new_likes_digest","value":h}]}}]
ROWS+=[
    {"page":"settings/messaging","steps":[_TIP_SW],"write":["PATCH",_ME,{"canAcceptMessageOnlyFromFriends":True}],"after":[_TIP_ON, True],
     "undo":{"steps":[_TIP_SW],"write":["PATCH",_ME,{"canAcceptMessageOnlyFromFriends":False}],"after":[_TIP_ON, False]}},
    {"page":"settings/security","reads":_PRIV_READS,"steps":[_PRIV_SW],"write":["PATCH",_SECURITY,{"isPrivate":True}],"after":[_PRIV_ON, True],
     "undo":{"steps":[_PRIV_SW],"write":["PATCH",_SECURITY,{"isPrivate":False}],"after":[_PRIV_ON, False]}},
    {"page":"settings/notifications/email","reads":_FREQ_READS,"steps":_FREQ(24),"write":_freq_write(24),"after":[_FREQ_SHOWN, "Every 24 Hours"]},
]
STATEFUL+=[["PATCH", _ME, _SETTINGS], ["PATCH", _SECURITY, _SETTINGS], ["PATCH", _NOTIF, _EMAIL]]
RED_NOTES+=[
    {"page":"settings/messaging","steps":[_TIP_SW],"fail":["PATCH",_ME],"kept":_TIP_ON},
    {"page":"settings/security","reads":_PRIV_READS,"steps":[_PRIV_SW],"fail":["PATCH",_SECURITY],"kept":_PRIV_ON},
    {"page":"settings/notifications/email","reads":_FREQ_READS,"steps":_FREQ(24),"fail":["PATCH",_NOTIF],"kept":_FREQ_SHOWN},
]
_CLOSE="css=#content .b-sessions-list button.g-btn"
_CLOSE_OK, _CLOSE_CANCEL="css=#ModalConfirm .modal-footer button:last-child", "css=#ModalConfirm .modal-footer button:first-child"
_WRONG_USER={"detail":{"upstream_status":400,"upstream_body":'{"error":{"code":301,"message":"Wrong user."}}'}}
REQUESTS+=[
    {"page":"settings/account/sessions","steps":[_CLOSE, _CLOSE_CANCEL],"want":[]},
    {"proof":"settings--close-all-sessions","steps":[_CLOSE, _CLOSE_OK]},
]
RED_NOTES+=[
    {"page":"settings/account/sessions","steps":[_CLOSE, _CLOSE_OK],"fail":["DELETE","/api/of/v2/sessions"],"body":_WRONG_USER,
     "note":"OnlyFans rejected this login — the creator logged in elsewhere or unlinked it. Automations stay paused until it is re-linked in Manage creators."},
    {"page":"settings/account/sessions","steps":[_CLOSE, _CLOSE_OK],"fail":["DELETE","/api/of/v2/sessions"],
     "note":"Could not close sessions: synthetic failure"},
]
_T67_CAMERA="css=.b-profile__header > .b-profile__header__cover__btns button.dropdown-toggle"
_T67_REMOVE="css=.b-profile__header > .b-profile__header__cover__btns > button"
_T67_SAVE="css=.g-btn__wrapper button[type='submit']"
_T67_PIC="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxIDEiPjxyZWN0IHdpZHRoPSIxIiBoZWlnaHQ9IjEiIGZpbGw9IiNmMDAiLz48L3N2Zz4="
_T67_READS={_ME: {"id":1,"username":"alphaone","name":"Alpha One","header":_T67_PIC}}
_T67_COVER="document.querySelector('img.b-profile__header__cover-img')?.getAttribute('src') ?? null"
_T67_SHOWS_PIC=f"({_T67_COVER}) === {json.dumps(_T67_PIC)}"
_T67_PICK=("(() => {{ const real = HTMLInputElement.prototype.click; const f = new File([new Uint8Array({bytes})], '{name}', {{type: '{type}'}});"
           " HTMLInputElement.prototype.click = function () {{ if (this.type !== 'file') return real.call(this);"
           " const dt = new DataTransfer(); dt.items.add(f); this.files = dt.files; this.dispatchEvent(new Event('change', {{bubbles: true}})); }}; }})()")
_T67_PNG=_T67_PICK.format(bytes="[137,80,78,71,13,10,26,10]", name="cover.png", type="image/png")
_T67_TXT=_T67_PICK.format(bytes="[104,105]", name="notes.txt", type="text/plain")
_T67_UP=["POST","/api/of/v2/users/me/profile-image",{"file":{"type":"image/png","ext":".png"},"kind":"header"}]
_T67_CLEAR=["PATCH",_ME,{"header":""}]
REQUESTS+=[{"page":"settings/profile","prep":_T67_PNG,"steps":[_T67_CAMERA, _T67_SAVE],"want":[_T67_UP, ["PATCH",_ME,{"header":{"success":True}}]]}]
ROWS+=[{"page":"settings/profile","reads":_T67_READS,"steps":[_T67_REMOVE, _T67_SAVE],"write":_T67_CLEAR,"after":[_T67_SHOWS_PIC, False]}]
STATEFUL+=[["PATCH", _ME, _ME]]
RED_NOTES+=[
    {"page":"settings/profile","prep":_T67_PNG,"steps":[_T67_CAMERA, _T67_SAVE],"fail":["POST","/api/of/v2/users/me/profile-image"],
     "kept":_T67_COVER,"sent":[_T67_UP],"note":"Could not save: synthetic failure"},
    {"page":"settings/profile","reads":_T67_READS,"steps":[_T67_REMOVE, _T67_SAVE],"fail":["PATCH",_ME],"kept":_T67_COVER,
     "note":"Could not save: synthetic failure"},
    {"page":"settings/profile","prep":_T67_TXT,"steps":[_T67_CAMERA],"kept":_T67_COVER,"sent":[],"note":"Choose a JPEG, PNG, GIF or WebP image"},
]
_T68_FORMAT="css=.b-input-contenteditable .b-icon-text-container > button"
_T68_BOLD="css=[data-oi-about-format] [aria-label='Bold']"
_T68_SELECT=("(() => addEventListener('click', (e) => { if (!e.target.closest?.('.b-input-contenteditable .b-icon-text-container > button')) return;"
             " const t = document.querySelector(\"[data-placeholder='Bio'] p\")?.firstChild; if (!t) return; const r = document.createRange();"
             " r.setStart(t, 0); r.setEnd(t, 7); getSelection().removeAllRanges(); getSelection().addRange(r); }, true))()")
_T68_BIO="document.querySelector(\"[data-placeholder='Bio']\")?.innerHTML ?? null"
_T68_HTML="<p><strong>Welcome</strong> to my page.</p>"
_T68_READS={_ME: {"id":1,"username":"alphaone","name":"Alpha One"}}
_T68_WRITE=["PATCH",_ME,{"about":_T68_HTML}]
ROWS+=[{"page":"settings/profile","reads":_T68_READS,"prep":_T68_SELECT,"steps":[_T68_FORMAT, _T68_BOLD, _T67_SAVE],
        "write":_T68_WRITE,"after":[_T68_BIO, _T68_HTML]}]
RED_NOTES+=[{"page":"settings/profile","prep":_T68_SELECT,"steps":[_T68_FORMAT, _T68_BOLD, _T67_SAVE],"fail":["PATCH",_ME],
             "sent":[_T68_WRITE],"note":"Could not save: synthetic failure"}]
_T69="settings/social-media"
_T69_PATH="/api/of/v2/users/social/buttons"
_T69_ADD="css=.b-settings__row.g-btn__wrapper > button.g-btn"
_T69_SAVE="css=[data-oi-link-save]"
_T69_RM="css=[data-oi-link-remove='%s']"
_T69_LABELS="[...document.querySelectorAll('[data-oi-link-row] .g-semibold')].map(e => e.textContent)"
_T69_B1={"id":1,"socialMedia":"instagram","label":"My Insta","link":"https://instagram.com/a","username":"a"}
_T69_B2={"id":2,"socialMedia":"tiktok","label":"My TikTok","link":"https://tiktok.com/@b","username":"b"}
_T69_STEPS=[_T69_ADD, ["css=#oi-link-label","Proof button"], ["css=#oi-link-url","oi_proof"], _T69_SAVE]
_T69_BODY={"socialMedia":"instagram","label":"Proof button","link":"","username":"oi_proof"}
READS["/api/of/v2/init"]={"socialMediaProviders":[{"socialMedia":"instagram","label":"Instagram","isLink":False,"isShowAt":False},
                                                   {"socialMedia":"amazon","label":"Amazon","isLink":True,"isShowAt":False}]}
_T69_WRITE=["PUT",_T69_PATH,_T69_BODY]
LIST_READS.add(_T69_PATH)
STATEFUL+=[["PUT", _T69_PATH, _T69_PATH], ["DELETE", _T69_PATH+r"/(?P<id>\d+)", _T69_PATH]]
ROWS+=[
    {"page":_T69,"reads":{_T69_PATH:[]},"steps":_T69_STEPS,"write":_T69_WRITE,"after":[_T69_LABELS,["Proof button"]],
     "undo":{"steps":[_T69_RM % 1],"write":["DELETE",_T69_PATH+"/1",None],"after":[_T69_LABELS,[]]}},
    {"page":_T69,"reads":{_T69_PATH:[_T69_B1,_T69_B2]},"steps":[_T69_RM % 2],"write":["DELETE",_T69_PATH+"/2",None],
     "after":[_T69_LABELS,["My Insta"]]},
]
REQUESTS+=[{"proof":"settings--social-media-buttons","steps":_T69_STEPS,"fill":_T69_BODY}]
RED_NOTES+=[
    {"page":_T69,"reads":{_T69_PATH:[_T69_B1]},"steps":_T69_STEPS,"fail":["PUT",_T69_PATH],"kept":_T69_LABELS,
     "sent":[_T69_WRITE],"note":"Could not save: synthetic failure"},
    {"page":_T69,"reads":{_T69_PATH:[_T69_B1,_T69_B2]},"steps":[_T69_RM % 2],"fail":["DELETE",_T69_PATH+"/2"],"kept":_T69_LABELS,
     "note":"Could not remove: synthetic failure"},
]
_T70="settings/links"
_T70_PATH="/api/of/v2/users/links"
_T70_ADD="css=.b-settings__things-like__add > button.g-btn"
def _t70_item(url):
    return {"sort":0,"url":url,"title":"","description":"","image":{"src":"","thumbs":{"c50":"","c144":""},"width":0,"height":0}}
_T70_L1={"id":1,**_t70_item("https://www.youtube.com/watch?v=a")}
_T70_L2={"id":2,**_t70_item("https://www.imdb.com/title/tt1/")}
_T70_STEPS=[_T70_ADD, ["css=#oi-link-url","youtube.com/watch?v=oi-proof"], _T69_SAVE]
_T70_BODY={"link":"https://youtube.com/watch?v=oi-proof"}
_T70_WRITE=["PUT",_T70_PATH,_T70_BODY]
LIST_READS.add(_T70_PATH)
LIST_ITEM[_T70_PATH]=lambda body: _t70_item(body.get("link"))
STATEFUL+=[["PUT", _T70_PATH, _T70_PATH], ["DELETE", _T70_PATH+r"/(?P<id>\d+)", _T70_PATH]]
ROWS+=[
    {"page":_T70,"reads":{_T70_PATH:[]},"steps":_T70_STEPS,"write":_T70_WRITE,"after":[_T69_LABELS,[_T70_BODY["link"]]],
     "undo":{"steps":[_T69_RM % 1],"write":["DELETE",_T70_PATH+"/1",None],"after":[_T69_LABELS,[]]}},
    {"page":_T70,"reads":{_T70_PATH:[_T70_L1,_T70_L2]},"steps":[_T69_RM % 2],"write":["DELETE",_T70_PATH+"/2",None],
     "after":[_T69_LABELS,[_T70_L1["url"]]]},
]
REQUESTS+=[{"proof":"settings--things-i-like-links","steps":_T70_STEPS,"fill":_T70_BODY}]
RED_NOTES+=[
    {"page":_T70,"reads":{_T70_PATH:[_T70_L1]},"steps":_T70_STEPS,"fail":["PUT",_T70_PATH],"kept":_T69_LABELS,
     "sent":[_T70_WRITE],"note":"Could not save: synthetic failure"},
    {"page":_T70,"reads":{_T70_PATH:[_T70_L1,_T70_L2]},"steps":[_T69_RM % 2],"fail":["DELETE",_T70_PATH+"/2"],"kept":_T69_LABELS,
     "note":"Could not remove: synthetic failure"},
]
_OBS_MUX=["css=label[for=input-677]", "css=#oi-menu [data-oi-value='mux_direct']"]
_MUX_SERVER, _MUX_KEY="rtmp://mux.synthetic.invalid/live", STREAM_KEY+"-mux"
READS["/api/of/v2/users/me/settings"]={**READS["/api/of/v2/users/me/settings"], "streamingMuxServer":_MUX_SERVER, "streamingMuxDirectKey":_MUX_KEY}
ROWS+=[{"page":"settings/streaming", "steps":[*_OBS_MUX, _COPY("server")], "clipboard":_MUX_SERVER},
       {"page":"settings/streaming", "steps":[*_OBS_MUX, _COPY("key")], "clipboard":_MUX_KEY}]
_BLOCKED, _BLOCK_IN="/api/of/v2/streams/users/blocked", "css=#input-365"
_BLOCK="css=#content .b-settings__content form button[type=submit]"
_UNBLOCK="css=[data-oi-blocked-list] button.m-btn-remove"
_BLOCKED_N="document.querySelectorAll('[data-oi-blocked]').length"
READS[_BLOCKED]={"list":[{"id":101,"name":"Soak Fan 1","username":"soakfan1","avatar":None,"isActive":True}],"hasMore":False}
_block_write=["POST","/api/of/v2/streams/users/soakfan1/block",None]
ROWS+=[{"page":"settings/streaming/blocked","steps":[[_BLOCK_IN,"soakfan1"], _BLOCK],"write":_block_write}]
REQUESTS+=[
    {"page":"settings/streaming/blocked","steps":[_UNBLOCK, _CLOSE_CANCEL],"want":[]},
    {"page":"settings/streaming/blocked","steps":[_UNBLOCK, _CLOSE_OK],"want":[["DELETE","/api/of/v2/streams/users/101/block",None]]},
]
RED_NOTES+=[
    {"page":"settings/streaming/blocked","steps":[[_BLOCK_IN,"soakfan1"], _BLOCK],"fail":["POST","/api/of/v2/streams/users/soakfan1/block"],
     "kept":_BLOCKED_N,"note":"Could not block: synthetic failure"},
    {"page":"settings/streaming/blocked","steps":[_UNBLOCK, _CLOSE_OK],"fail":["DELETE","/api/of/v2/streams/users/101/block"],
     "kept":_BLOCKED_N,"note":"Could not unblock: synthetic failure"},
]
_RESET="css=#content button.g-btn.m-danger.m-flat"
_NEW_KEY=STREAM_KEY+"-new"
_KEY_FIELD="[...document.querySelectorAll('#content label.v-label')].filter(l => l.textContent.trim() === 'Stream Key').map(l => document.getElementById(l.htmlFor)?.value)[0] ?? null"
_COPIED_KEY="(async () => { document.querySelector(\"button[data-oi-stream-copy='key']\").click(); await new Promise(r => setTimeout(r, 300)); return window.top.navigator.clipboard.readText(); })()"
def _new_stream_key(reads, hit, body):
    reads[_SETTINGS]={**reads.get(_SETTINGS, {}), "streamingRtmpKey": _NEW_KEY}
STATEFUL+=[["DELETE", r"/api/of/v2/streams/obs/key", _new_stream_key]]
ROWS+=[{"page":"settings/streaming","steps":[_RESET, _CLOSE_OK],"write":["DELETE","/api/of/v2/streams/obs/key",None],"after":[_COPIED_KEY, _NEW_KEY]}]
REQUESTS+=[{"page":"settings/streaming","steps":[_RESET, _CLOSE_CANCEL],"want":[]}]
RED_NOTES+=[{"page":"settings/streaming","steps":[_RESET, _CLOSE_OK],"fail":["DELETE","/api/of/v2/streams/obs/key"],"kept":_KEY_FIELD,
             "note":"Could not reset the stream key: synthetic failure"}]
Z="​"  # the sweep's labels keep OF's zero-width space
TITLES=[[p, c] for p, cs in {
    "profile/index": ["Sign in with spotify"],
    "profile/media": ["Sign in with spotify"],
    "profile/state-more-menu": ["Sign in with spotify"],
    "settings/account/connected": ["[INPUT]","Connect"],
    "settings/account/google": ["Sign in with google"],
    "settings/account/sessions": ["Close all sessions"],
    "settings/account/x": ["Sign in with X"],
    "settings/ethwallet": ["https://metamask.io/download.html"],
    "settings/links": ["Create link"],
    "settings/messaging": ["[b-checkbox-switcher]","Restricted"],
    "settings/notifications": ["Restricted"],
    "settings/notifications/email": [Z+"Update frequencyEvery 24 Hours"],
    "settings/profile": ["[btn.dropdown-toggle]","[g-btn.m-icon]","[g-btn.m-with-round-hover]"],
    "settings/security": ["Restricted accounts","Blocked accounts"],
    "settings/security/block_by_country": ["[INPUT]"],
    "settings/security/block_by_country/state-country-picker": [Z+"Select from available options United States of America Unit","[INPUT]"],
    "settings/security/block_by_ip": ["[TEXTAREA]"],
    "settings/social-media": ["Add button"],
    "settings/spotify": ["Sign in with spotify"],
    "settings/spring-store": ["Paste your Spring Store URL","here"],
    "settings/streaming": ["OBS","[INPUT]","Copy link","Reset","Copy key","https://onlyfans.com/my/streaming/chat","https://obs-settings.onlyfans.com/"],
    "settings/streaming/blocked": ["[INPUT]","Block"],
    "settings/subscription/promotion-campaign/modal-1": ["Start promotion campaign","Add bundle"],
    "settings/subscription/promotion-campaign/modal-2": ["Start promotion campaign","Add bundle"],
    "settings/subscription/promotion-campaign/modal-3": ["Start promotion campaign","Add bundle","[btn.dropdown-toggle]"],
    "settings/subscription/tracking-links": ["Sort","Shared with you"],
    "settings/subscription/tracking-links/modal-1": ["Create new tracking link","Sort","Shared with you"],
    "settings/subscription/tracking-links/state-kebab": ["Create new tracking link","Sort","[b-input-radio]","Shared with you"],
    "settings/subscription/trial-links/modal-1": ["Create new free trial link"],
    "settings/subscription/trial-links/state-kebab": ["Create new free trial link","[b-input-radio]"],
}.items() for c in cs]
TITLES+=[["settings/streaming", c] for c in ("Copy stream chat link", "Copy OBS widgets link", "Stream server address", "Stream key")]
TITLES+=[["settings/profile", "Change avatar"]]

_T61="settings/subscription/tracking-links"
_T61_NAMES="[...document.querySelectorAll('[data-oi-row] .b-offer-join__details')].map(e => e.textContent.trim())"
_T61_PICK="css=#oi-menu [data-oi-value='%s']"
READS["/api/of/v2/campaigns"]=[
    {"id":61001,"campaignCode":61,"campaignName":"Zeta link","countSubscribers":2,"countTransitions":9,"createdAt":"2026-04-16T00:00:00+00:00","isDeleted":False},
    {"id":61002,"campaignCode":62,"campaignName":"Alpha link","countSubscribers":5,"countTransitions":1,"createdAt":"2026-05-16T00:00:00+00:00","isDeleted":False},
]
ROWS+=[{"page":_T61,"steps":["Sort",_T61_PICK % f,"Sort",_T61_PICK % o],"land":url_of(_T61),"get":["/api/of/v2/campaigns",{"field":f,"sort":o}],
        "rows":"[data-oi-row]","after":[_T61_NAMES,["Zeta link","Alpha link"]]}
       for f in ("created_date","name","subscribers_counts","clicks_count","shared") for o in ("asc","desc")]
ROWS+=[{"page":f"{_T61}/modal-1","steps":[{"press":"Sort"},_T61_PICK % "name"],"land":url_of(_T61),
        "get":["/api/of/v2/campaigns",{"field":"name","sort":"desc"}],"rows":"[data-oi-row]","after":[_T61_NAMES,["Zeta link","Alpha link"]]}]

_T62="settings/subscription"
_T62_READS={"/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One","subscribePrice":10,"isPerformer":True,
    "canCreatePromotion":True,"canEarn":True,"canCreateTrial":True,"promotions":[{"id":62001,"price":0,"type":"new",
    "subscribeDays":30,"subscribeCounts":0,"claimsCount":4,"isFinished":False,"canClaim":True,"message":"",
    "createdAt":"2026-03-02T12:00:00+00:00","finishedAt":None}]},
    "/api/of/v2/users/me/settings": {**READS["/api/of/v2/users/me/settings"],
    "canAddSubscriberByBundle":{"discounts":{"10":"10%"},"durations":{"3":"3 months"}}}}
_T62_CLAIMS="css=[data-oi-row] a[href$='/promotion-campaign/modal-3']"
ROWS+=[{"page":f"{_T62}/{at}","steps":[{"open":label,"page":f"{_T62}/{to}","press":True}],"land":url_of(f"{_T62}/{to}"),
        "get":None,"rows":".modal.show","reads":_T62_READS}
       for at, label, to in (
           ("tracking-links/state-kebab","Create new tracking link","tracking-links/modal-1"),
           ("trial-links/state-kebab","Create new free trial link","trial-links/modal-1"),
           ("promotion-campaign/modal-1","Add bundle","promotion-campaign/modal-2"),
           ("promotion-campaign/modal-2","Start promotion campaign","promotion-campaign/modal-1"),
           ("promotion-campaign/modal-3","Start promotion campaign","promotion-campaign/modal-1"),
           ("promotion-campaign/modal-3","Add bundle","promotion-campaign/modal-2"),
           ("promotion-campaign/modal-1",_T62_CLAIMS,"promotion-campaign/modal-3"),
           ("promotion-campaign/modal-2",_T62_CLAIMS,"promotion-campaign/modal-3"))]

_T74_SHARE="/api/of/v2/campaigns/share-access"
READS[_T74_SHARE]={"list":[{"id":7491,"campaignCode":91,"campaignName":"Peer link","countSubscribers":4,"countTransitions":12,
    "createdAt":"2026-02-15T00:00:00+00:00","isDeleted":False,"user":{"id":7402,"name":"Synthetic Owner","username":"synthowner"}}],"hasMore":False}
READS["/api/of/v2/users/performers-search"]=[{"id":7401,"name":"Synthetic Peer","username":"synthpeer"}]
_T74_HINT="css=[data-oi-row] [data-oi-share]"
_T74_DIALOG=[["css=#oi-share input","synthpeer"], "css=#oi-share input", "css=#oi-share [data-oi-performer]", "css=#oi-share [data-oi-send]"]
_T74_WRITE=["POST",_T74_SHARE,{"campaignId":61001,"userId":7401}]
ROWS+=[{"page":p,"steps":[tab],"land":url_of(_T61),"get":[_T74_SHARE,{}],"rows":"[data-oi-row]"}
       for p, tab in ((_T61,"Shared with you"), (f"{_T61}/modal-1",{"press":"Shared with you"}),
                      (f"{_T61}/state-kebab",{"press":"Shared with you"}))]
ROWS+=[{"page":_T61,"steps":[_T74_HINT,*_T74_DIALOG],"write":_T74_WRITE}]
ROWS+=[{"page":p,"steps":[{"open":_T74_HINT,"page":p,"press":True},*_T74_DIALOG],"write":_T74_WRITE}
       for p in (f"{_T61}/modal-1", f"{_T61}/state-kebab")]


_T66C, _T66I="settings/security/block_by_country", "settings/security/block_by_ip"
_T66_COUNTRIES, _T66_IPS=_SECURITY+"/blocked-countries", _SECURITY+"/blocked-ips"
READS["/api/of/v2/countries"]=[{"id":1,"code":"TV","name":"Tuvalu"},{"id":2,"code":"US","name":"United States of America"}]
_T66_BOX, _T66_FIELD="css=#content .g-select__wrapper .v-input", "css=#input-blocked-ips"
_T66_SAVE_C="css=#content .g-page__header .g-btn__wrapper button[type='submit']"
_T66_CANCEL_I, _T66_SAVE_I="css=#content .b-settings__row.g-btn__wrapper button:first-of-type", "css=#content .b-settings__row.g-btn__wrapper button:last-child"
_T66_PICK=["css=#input-298", "css=#oi-menu [data-oi-value='TV']", _T66_SAVE_C]
_T66_CHIPS="[...document.querySelectorAll('#oi-countries [data-oi-country]')].map(e => e.getAttribute('data-oi-country'))"
_T66_IPS_SHOWN="document.getElementById('input-blocked-ips')?.value ?? null"
ROWS+=[
    {"page":_T66C,"steps":[*_T66_PICK, _CLOSE_OK],"write":["PUT",_T66_COUNTRIES,{"blockedCountries":["TV"],"blockedStates":[]}],"after":[_T66_CHIPS, ["TV"]],
     "undo":{"steps":["css=#oi-countries [data-oi-country='TV']", _T66_SAVE_C, _CLOSE_OK],
             "write":["PUT",_T66_COUNTRIES,{"blockedCountries":[],"blockedStates":[]}],"after":[_T66_CHIPS, []]}},
    {"page":_T66I,"steps":[[_T66_FIELD,"192.0.2.1"], _T66_SAVE_I, _CLOSE_OK],"write":["PUT",_T66_IPS,{"blockedIps":["192.0.2.1"]}],"after":[_T66_IPS_SHOWN, "192.0.2.1"],
     "undo":{"steps":[[_T66_FIELD,""], _T66_SAVE_I, _CLOSE_OK],"write":["PUT",_T66_IPS,{"blockedIps":[]}],"after":[_T66_IPS_SHOWN, ""]}},
]
STATEFUL+=[["PUT", re.escape(_T66_COUNTRIES), _SETTINGS], ["PUT", re.escape(_T66_IPS), _SETTINGS]]
REQUESTS+=[
    {"page":_T66I,"steps":[[_T66_FIELD,"192.0.2.1"], _T66_CANCEL_I],"want":[],"after":[_T66_IPS_SHOWN, ""]},
    {"page":_T66I,"steps":[[_T66_FIELD,"192.0.2.1"], _T66_SAVE_I, _CLOSE_CANCEL],"want":[]},
    {"page":_T66C,"steps":[*_T66_PICK, _CLOSE_CANCEL],"want":[]},
]
RED_NOTES+=[
    {"page":_T66C,"steps":[*_T66_PICK, _CLOSE_OK],"fail":["PUT",_T66_COUNTRIES],"kept":_T66_CHIPS,"note":"Could not save: synthetic failure"},
    {"page":_T66I,"steps":[[_T66_FIELD,"192.0.2.1"], _T66_SAVE_I, _CLOSE_OK],"fail":["PUT",_T66_IPS],"kept":_T66_IPS_SHOWN,"note":"Could not save: synthetic failure"},
]
_PW_TYPES="[...document.querySelectorAll('#content form input')].map(e => e.type)"
_REVEAL2="css=#content .g-input__wrapper[data-vv-as='Confirm new password'] button[aria-label='Reveal password']"
_MAILTO="[...document.querySelectorAll('#content a')].filter(a => a.textContent.trim() === 'support@onlyfans.com').map(a => a.getAttribute('href'))"
_ACCOUNT_ROW="#content a[href='/of-manager/settings/account/phone']"
_T110=[
    {"page":"settings/account/password","steps":["Reveal password"],"dom":[_PW_TYPES,["text","password","password"]]},
    {"page":"settings/account/password","steps":["Reveal password","Reveal password"],"dom":[_PW_TYPES,["password","password","password"]]},
    {"page":"settings/account/password","steps":[_REVEAL2],"dom":[_PW_TYPES,["password","password","text"]]},
    {"page":"bank/dac7/edit","steps":[],"dom":[_MAILTO,["mailto:support@onlyfans.com"]]},
    {"page":"settings/account/delete","steps":[],"dom":[_MAILTO,["mailto:support@onlyfans.com"]]},
    {"page":"settings/account/phone","steps":["Cancel"],"land":url_of("settings/account"),"get":None,"rows":_ACCOUNT_ROW},
]
ROWS+=_T110
TITLES+=[[p, c] for p, cs in {
    "bank/dac7/edit": ["[INPUT]","Send","2024","support@onlyfans.com"],
    "bank/payments": ["Add card","Payments","Alternative methods","Add a payment card"],
    "bank/payout_types": ["[b-input-radio]","CONTINUE","click here"],
    "bank/support": ["[TEXTAREA]","Send"],
    "statements/support": [Z+"Select subject","[TEXTAREA]","Send"],
    "settings/account/password": ["[INPUT]","Reveal password","Forgot password?","Save"],
    "settings/account/phone": [Z,"[INPUT]","Cancel","SAVE"],
    "settings/account/delete": ["support@onlyfans.com","[INPUT]","Reload code","Delete account"],
}.items() for c in cs]

SHOWS="[...document.querySelectorAll('.modal.show, .of-state-menu')].some(e => e.checkVisibility())"
IN_OPEN="e => !!e.closest('.modal.show, .of-state-menu')"
KEY_IN_DOM="(k) => document.documentElement.outerHTML.includes(k) || [...document.querySelectorAll('input, textarea')].some(e => (e.value || '').includes(k))"
MODALISH=re.compile(r"/(modal-\d+|state-[^/]+)$")
def page_of(path):
    rest=path[len(M)+1:]
    return rest if "/" in rest else f"{rest}/index"
def merge_into(read):
    if callable(read): return read
    def hook(reads, hit, body):
        if read in LIST_READS: return list_into(reads, read, hit, body)
        if not isinstance(body, dict): return
        cur=reads.get(read, {})
        if isinstance(cur, list):
            for item in [i for items in (body.get("notifications") or {}).values() for i in items]:
                for x in (x for g in cur for x in g.get("items", []) if x.get("code")==item.get("code")):
                    x.update(value=item["value"] or 0, isEnabled=item["value"] is not False)
            return
        reads[read]={**cur, **body}
    return hook
def list_into(reads, read, hit, body):
    cur=reads.get(read) if isinstance(reads.get(read), list) else []
    if "id" in hit.groupdict():
        reads[read]=[x for x in cur if str(x.get("id"))!=hit["id"]]; return None
    if isinstance(body, dict):
        item=LIST_ITEM.get(read, lambda b: b)(body)
        cur=[*cur, {"id": max((int(x["id"]) for x in cur), default=0)+1, **item}]
    reads[read]=cur
    return cur
def session(b, scope_js, reads, state, handoffs_ok):
    """phase_check's session (its GET record as dead.py's: path, query, X-Account-Id), plus the clipboard and the rows'
    hand-offs (aborted, recorded)."""
    gets, handoffs=[], []
    pg, sent, errs=pc.session(b, scope_js, reads, [(m, rx, merge_into(read)) for m, rx, read in state], {}, gets=gets)
    pg.context.grant_permissions(["clipboard-read","clipboard-write"], origin=pc.BASE)
    def handoff(route):
        handoffs.append(route.request.url); route.abort()
    allowed=lambda url: url in handoffs_ok
    pg.context.route(allowed, handoff); pg.route(allowed, handoff)
    return pg, sent, gets, handoffs, errs
def key_scan(pg, where):
    seen, unread=[], []
    for f in pg.frames:
        try:
            if f.evaluate(KEY_IN_DOM, STREAM_KEY): seen.append(urlparse(f.url).path)
        except Exception as e: unread.append(f"{urlparse(f.url).path}: {str(e).splitlines()[0][:80]}")
    if seen: check(f"{where}: the stream key never in the DOM", seen, [])
    if unread: check(f"{where}: every frame read for the stream key", unread, [])
def load(pg, page):
    fr=open_page(pg, page)
    if fr: key_scan(pg, page)
    return fr
def frame_of(pg, page, tries=60):
    want=f"/of-mirror/pages/{page}.html"
    for _ in range(tries):
        fr=[f for f in pg.frames if urlparse(f.url).path==want]
        try:
            if fr and fr[0].evaluate("document.readyState")=="complete":
                pg.wait_for_timeout(800); return fr[0]
        except Exception: pass
        pg.wait_for_timeout(250)
    return None
def element(fr, label):
    return fr.query_selector(label[4:]) if label.startswith("css=") else fr.evaluate_handle(FIND, label).as_element()
def act(pg, fr, page, steps):
    gated=bool(MODALISH.search(page)); last=None
    for step in steps:
        label=(step["open"] if "open" in step else step["press"]) if isinstance(step, dict) else step if isinstance(step, str) else step[0]
        el=element(fr, label)
        if el is None: return fr, last, f"{label!r} not found"
        if gated and el.evaluate(IN_OPEN):
            return fr, last, f"{label!r} sits in the open modal of {page}: reached by loading the modal URL (click its opener on the page it sits on)"
        if not isinstance(step, dict):
            last=fr.evaluate(f"(e) => ({STATE})(e)", el)
            problem=pc.act(fr, [step])
            if problem: return fr, last, problem
            continue
        if "open" not in step:
            last=fr.evaluate(f"(e) => ({STATE})(e)", el)
            try: el.press("Enter", timeout=5000)
            except Exception as e: return fr, last, f"press {label!r}: {str(e).splitlines()[0][:120]}"
            pg.wait_for_timeout(300)
            continue
        try:
            if step.get("press"): el.press("Enter", timeout=5000)
            else: el.click(timeout=5000)
        except Exception as e: return fr, last, f"opener {label!r}: {str(e).splitlines()[0][:120]}"
        want=url_of(step["page"])
        for _ in range(40):
            if urlparse(pg.url).path==want: break
            pg.wait_for_timeout(250)
        if urlparse(pg.url).path!=want: return fr, last, f"opener {label!r} landed on {urlparse(pg.url).path}, not {want}"
        fr=frame_of(pg, step["page"])
        if fr is None: return fr, last, f"opener {label!r}: no frame for {step['page']}"
        if not fr.evaluate(SHOWS): return fr, last, f"opener {label!r}: {step['page']} shows no modal or State menu"
        gated=False
    return fr, last, None
def poll(pg, fr, js, value):
    got=None
    for _ in range(30):
        try: got=fr.evaluate(js)
        except Exception as e: got=f"error: {str(e).splitlines()[0][:80]}"
        if got==value: break
        pg.wait_for_timeout(100)
    return got
def outcome(pg, fr, row, what, s, n, acct):
    sent, gets, handoffs=s["sent"], s["gets"], s["handoffs"]
    if "write" in row:
        settle(pg, sent, n["sent"], 1)
        m, p, body=row["write"]
        check(f"{what}: sends exactly {m} {p} with X-Account-Id {acct}", sent[n["sent"]:], [[m, p, acct, body]])
    elif "handoff" in row:
        for _ in range(30):
            if handoffs[n["handoffs"]:]: break
            pg.wait_for_timeout(100)
        settle(pg, sent, n["sent"], 0)
        loaded=[f.url for p in pg.context.pages for f in p.frames if f.url==row["handoff"]]
        check(f"{what}: hands off to {row['handoff']} (aborted, never loaded), writes nothing",
              [handoffs[n["handoffs"]:], loaded, sent[n["sent"]:]], [[row["handoff"]], [], []])
        for p in pg.context.pages[1:]: p.close()
    elif "clipboard" in row:
        settle(pg, sent, n["sent"], 0)
        check(f"{what}: copies, writes nothing", [pg.evaluate("navigator.clipboard.readText()"), sent[n["sent"]:]], [row["clipboard"], []])
    elif "land" in row:
        for _ in range(40):
            if urlparse(pg.url).path==row["land"]: break
            pg.wait_for_timeout(250)
        landed=urlparse(pg.url).path
        fr=frame_of(pg, page_of(landed)) if landed.startswith(M+"/") else None
        shown=fr.evaluate("(s) => [...document.querySelectorAll(s)].filter(e => e.checkVisibility()).length", row["rows"]) if fr else 0
        path, params=row["get"] or (None, {})
        asked=path is None or any(g[0]==path and all(parse_qs(g[1]).get(k)==[v] for k, v in params.items()) for g in gets[n["gets"]:])
        check(f"{what}: lands on {row['land']}, GET {path} {params}, at least one row, nothing written",
              [landed, asked, shown>0, sent[n["sent"]:]], [row["land"], True, True, []])
    elif "dom" in row:
        js, value=row["dom"]
        got=poll(pg, fr, js, value)
        settle(pg, sent, n["sent"], 0)
        check(f"{what}: the frame gives {value!r}, no request sent (write, Relay GET or hand-off)",
              [got, sent[n["sent"]:], gets[n["gets"]:], handoffs[n["handoffs"]:]], [value, [], [], []])
    else:
        check(f"{what}: the row names an outcome", False, True)
    return fr
def run_row(pg, row, what, s, acct, shot):
    fr=load(pg, row["page"])
    if not fr: return
    if "dom" in row:
        for _ in range(5):
            g=len(s["gets"]); settle(pg, s["gets"], g, 0)
            if len(s["gets"])==g: break
    n={k: len(v) for k, v in s.items()}
    fr.evaluate("document.getElementById('oi-note')?.remove()")
    if row.get("prep"): fr.evaluate(row["prep"])
    fr, last, problem=act(pg, fr, row["page"], row["steps"])
    check(f"{what}: steps run", problem, None)
    if problem: return
    fr=outcome(pg, fr, row, what, s, n, acct)
    if "write" in row: check(f"{what}: the control is Wired", bool(last and last[1]), True)
    key_scan(pg, what)
    pg.screenshot(path=f"{pc.SHOTS}/inapp-{NAME}-{shot}.png")
    fresh=row.get("fresh", row["page"])
    for phase, step in (("new value", row), ("old value after undo", row.get("undo"))):
        if fr is None or not step or not step.get("after"): return
        if step is not row:
            m0=len(s["sent"])
            fr, last, problem=act(pg, fr, fresh, step["steps"])
            check(f"{what} undo: steps run", problem, None)
            if problem: return
            settle(pg, s["sent"], m0, 1)
            m, p, body=step["write"]
            check(f"{what} undo: sends exactly {m} {p} with X-Account-Id {acct}", s["sent"][m0:], [[m, p, acct, body]])
        js, value=step["after"]
        check(f"{what}: settled frame shows the {phase}", poll(pg, fr, js, value), value)
        fr=load(pg, fresh)
        if fr: check(f"{what}: a fresh read serves the {phase}", poll(pg, fr, js, value), value)
def by_reads(b, label, scope_js, rows, reads, state, handoffs_ok):
    groups={"{}": []}
    for i, row in enumerate(rows, 1): groups.setdefault(json.dumps(row.get("reads") or {}, sort_keys=True), []).append((i, row))
    for key, mine in groups.items():
        own=json.loads(key)
        pg, sent, gets, handoffs, errs=session(b, scope_js, copy.deepcopy({**reads, **own}), state, handoffs_ok)
        yield pg, {"sent":sent, "gets":gets, "handoffs":handoffs}, mine, not own
        where=label+(", rows' own reads" if own else "")
        pc.console(where, errs, set())
        print(f"{where} relay writes:", sent)
        pg.context.close()
def titles_and_rows(b, t, records, reads, state, handoffs_ok):
    for pg, s, rows, base in by_reads(b, "phase 3 single creator", f"localStorage.setItem('chatterly:scope','{SINGLE}')", t["rows"], reads, state, handoffs_ok):
        if base:
            titles(pg, t, records)
            if "settings/streaming" in {p for p, _ in t["titles"]}: stream_key_field(pg, s["gets"])
        for i, row in rows:
            run_row(pg, row, f"{row['page']} {row['steps']}", s, SINGLE_ID, f"{i:02d}-{row['page'].replace('/','-')}")
def titles(pg, t, records):
    for page in dict.fromkeys(p for p, _ in t["titles"]):
        fr=load(pg, page)
        if not fr: continue
        for _, control in [c for c in t["titles"] if c[0]==page]:
            n=sum(1 for _, r in records if r.get("label")==control and page in (r.get("pages") or []))
            check(f"{page} {control!r}: at most one capture record", n<=1, True)
            _, rec, _=record_of(Proof(id=f"title {page} {control}", phase=3, page=page, control=control, kind="live"), records)
            titled=not live_passed(rec)
            got=fr.evaluate(f"(want) => ({STATE})(({FIND})(want))", control)
            check(f"{page} {control!r}: found", got[0], True)
            if got[0]: check(f"{page} {control!r}: Not-yet title {'kept (no Live-proof pass)' if titled else 'dropped (Live-proof pass)'}", got[2], titled)
        pg.screenshot(path=f"{pc.SHOTS}/inapp-{NAME}-titles-{page.replace('/','-')}.png")
def stream_key_field(pg, gets):
    fr=load(pg, "settings/streaming")
    if fr:
        check("settings/streaming: the Stream Key field shows the mask, not the key",
              fr.evaluate("[...document.querySelectorAll('#content label.v-label')].filter(l => l.textContent.trim() === 'Stream Key').map(l => document.getElementById(l.htmlFor)?.value)"),
              [STREAM_KEY_MASK])
        check("settings/streaming: the settings read was served", any(g[0]=="/api/of/v2/users/me/settings" for g in gets), True)
def run(b, t, records, reads, state):
    reads={"/api/of/v2/users/me": {"id":1,"username":"alphaone","name":"Alpha One"}, **reads}
    if t["proofs"] or t["requests"] or t["red_notes"]:
        pc.single(b, NAME, t, records, copy.deepcopy(reads), [(m, rx, merge_into(read)) for m, rx, read in state])
    handoffs_ok={r["handoff"] for r in t["rows"] if "handoff" in r}
    titles_and_rows(b, t, records, reads, state, handoffs_ok)
def tables(plant, base=True):
    own=lambda x: x if base else []
    return {"proofs":[*own(phase3.PROOFS), *(Proof(**{"phase": 3, **p}) for p in plant.get("proofs", []))],
            "requests":[*own(REQUESTS), *plant.get("requests", [])], "red_notes":[*own(RED_NOTES), *plant.get("red_notes", [])],
            "titles":[*own(TITLES), *plant.get("titles", [])], "rows":[*own(ROWS), *plant.get("rows", [])]}
def self_test(b):
    rec=lambda page, control, verdict, reason="": {"label":control,"pages":[page],"proof":{"kind":"live","verdict":verdict,**({"reason":reason} if reason else {})}}
    toggle="css=label[for=setting_isAutoFollowBack]"
    on="document.getElementById('setting_isAutoFollowBack')?.checked ?? null"
    security="/api/of/v2/users/me/settings/security"
    flip={"page":"settings/fans","steps":[toggle],"write":["PATCH",security,{"isAutoFollowBack":False}],"after":[on, False],
          "undo":{"steps":[toggle],"write":["PATCH",security,{"isAutoFollowBack":True}],"after":[on, True]}}
    hook=["PATCH",security,"/api/of/v2/users/me/settings"]
    tab, trials="settings/subscription/tracking-links", "settings/subscription/trial-links"
    create=[{"open":"Create new tracking link","page":f"{tab}/modal-1"},["css=input[name='name']","Synthetic link"],"css=.modal-footer button[type='submit']"]
    created=["POST","/api/of/v2/campaigns",{"name":"Synthetic link"}]
    lists={"/api/of/v2/campaigns":[{"id":7,"campaignCode":3,"campaignName":"Synthetic link","countSubscribers":2,"countTransitions":9,"createdAt":"2026-04-16T00:00:00+00:00","isDeleted":False}],
           "/api/of/v2/trials":[{"id":8,"trialLinkName":"Synthetic trial","url":"https://onlyfans.com/action/trial/synthetic","subscribeDays":7,"subscribeCounts":10,"claimCounts":3,"clicksCounts":12,"createdAt":"2026-06-11T00:00:00+00:00","isFinished":False}]}
    cases=[
        ("a missing control fails", {"titles":[["settings/security","No such control"]]}, "'No such control': found"),
        ("a row reached by its modal URL fails", {"rows":[{"page":f"{tab}/modal-1","steps":create[1:],"write":created}]}, "reached by loading the modal URL"),
        ("a Live-proof pass with the Not-yet title still on fails", {"titles":[["settings/security","Blocked accounts"]],
            "records":{"settings--blocked-accounts.json":rec("settings/security","Blocked accounts","pass")}}, "'Blocked accounts': Not-yet title dropped"),
        ("a parked record whose control lost the title fails", {"titles":[[tab,"Create new tracking link"]],
            "records":{"settings--create-new-tracking-link.json":rec(tab,"Create new tracking link","parked","synthetic: owner go pending")}},
            "'Create new tracking link': Not-yet title kept"),
        ("two capture records for one control fail", {"titles":[["settings/security","Restricted accounts"]],
            "records":{f"settings--restricted-{n}.json":rec("settings/security","Restricted accounts","parked","synthetic") for n in (1, 2)}},
            "'Restricted accounts': at most one capture record"),
        ("the stream key's text in the DOM fails", {"titles":[["settings/profile","[g-btn.m-icon]"]],
            "reads":{"/api/of/v2/users/me":{"id":1,"username":"alphaone","name":STREAM_KEY}}}, "the stream key never in the DOM"),
        ("without its STATEFUL hook the fresh read fails (the check reads the mock, not the frame)", {"rows":[flip]}, "a fresh read serves the new value"),
        ("the stateful mock serves the new value, then the old one after undo", {"rows":[flip], "state":[hook]}, None),
        ("an opener clicked on its page opens its modal (a row may then click inside it)", {"rows":[{"page":tab, "steps":create, "write":created}]}, None),
        ("clipboard and land rows pass", {"reads":lists, "rows":[{"page":tab, "steps":["Copy link"], "clipboard":"https://onlyfans.com/alphaone/c3"},
            {"page":tab, "steps":["Free trial links"], "land":url_of(trials), "get":["/api/of/v2/trials", {}], "rows":"[data-oi-row]"}]}, None),
    ]
    bad=[]
    for name, plant, needle in cases:
        pc.failures.clear()
        run(b, tables(plant, base=False), list(plant.get("records", {}).items()), {**READS, **plant.get("reads", {})}, plant.get("state", []))
        ok=(not pc.failures) if needle is None else any(needle in f for f in pc.failures)
        print(json.dumps({"self_test":name,"ok":ok,"failures":pc.failures}))
        if not ok: bad.append(name)
    pc.failures[:]=[f"self-test case did not behave: {n}" for n in bad]
def main():
    args=sys.argv[1:]
    plant, captures={}, pc.CAPTURES
    if "--plant" in args:
        i=args.index("--plant"); plant=json.load(open(args[i+1])); del args[i:i+2]
    if "--captures" in args:
        i=args.index("--captures"); captures=args[i+1]; del args[i:i+2]
    mode=args.pop(0) if args and args[0]=="--self-test" else None
    if args: sys.exit(f"settings_privacy.py: unknown arguments {args}")
    if not os.path.isdir(captures): sys.exit(f"settings_privacy.py: {captures} is not a directory")
    os.makedirs(pc.SHOTS, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b=p.chromium.launch()
        if mode=="--self-test": self_test(b)
        else:
            records, bad=load_records(Path(captures))
            check("capture records are valid JSON", bad, [])
            run(b, tables(plant), records+list(plant.get("records", {}).items()), {**READS, **plant.get("reads", {})}, [*STATEFUL, *plant.get("state", [])])
    if pc.failures:
        print("FAIL:", *pc.failures, sep="\n  "); sys.exit(1)
    print(f"{NAME}{' ' + mode if mode else ''} ok")
if __name__=="__main__": main()
