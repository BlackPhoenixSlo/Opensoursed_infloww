import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_check  # noqa: E402  (puts scripts/of-live-proof on the path)
from proofs import phase2  # noqa: E402

REQUESTS=[]
RED_NOTES=[]
READS={}
AFTER=[]
VIEWS={}

INIT=""

RECORD_CLAIM={"processId":"p1","host":"h","name":"n"}
RECORD_INIT=r"""(() => {
  const stream = () => { const c = document.createElement('canvas'); c.width = c.height = 16; c.getContext('2d').fillRect(0, 0, 16, 16); return c.captureStream(); };
  const devices = navigator.mediaDevices || {};
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: devices });
  devices.getUserMedia = async () => stream();
  // 0.1 s of 16 kHz mono 16-bit silence as WAV bytes (decodable, so the app's WAV re-encode runs).
  const wav = () => { const n = 1600, v = new DataView(new ArrayBuffer(44 + n * 2)), a = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    a(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); a(8, 'WAVE'); a(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); a(36, 'data'); v.setUint32(40, n * 2, true); return v.buffer; };
  class Rec {
    static isTypeSupported(t) { return t === 'video/mp4' || t === 'audio/webm'; }
    constructor(_s, o) { this.mimeType = (o && o.mimeType) || ''; this.state = 'inactive'; this.ondataavailable = null; this.onstop = null; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable && this.ondataavailable({ data: new Blob([this.mimeType.startsWith('video/') ? 'synthetic' : wav()], { type: this.mimeType }) }); this.onstop && this.onstop(); }
  }
  window.MediaRecorder = Rec;
})();"""
INIT+=RECORD_INIT
_RECORD_BUTTON={"Record video": "css=.b-chat__video-message__preview .vjs-record-button",
                "Record voice": "css=.js-chat__audiorecord-panel .b-float-panel__btn-record"}
_RECORD_FILE={"Record video": {"type": "video/mp4", "ext": ".mp4"}, "Record voice": {"type": "audio/wav", "ext": ".wav"}}
_RECORD_PAGES=[f"{d}/{s}" for d in ("home", "new-post") for s in ("index", "state-format-text", "state-poll", "state-quiz")]
def _record_steps(label): return [label, _RECORD_BUTTON[label], _RECORD_BUTTON[label], "Post"]
def _record_want(label, post=True):
    return [["POST", "/api/of/v2/upload", {"file": _RECORD_FILE[label]}]] + ([["POST", "/api/of/v2/posts", {"text": "", "media_files": [RECORD_CLAIM], "price": 0}]] if post else [])
REQUESTS+=[{"page": page, "steps": _record_steps(label), "want": _record_want(label)}
           for page in _RECORD_PAGES for label in ("Record video", "Record voice")]
_REFUSE="void (navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('refused', 'NotAllowedError')))"
_MEDIA="(p) => JSON.parse(top.sessionStorage.getItem(p) || '{}').media_files || []"
RED_NOTES+=[{"page": page, "steps": [label] + ([_RECORD_BUTTON[label]] if label == "Record voice" else []), "prep": _REFUSE, "sent": [],
             "note": {"Record video": "Allow camera access to record a video message",
                      "Record voice": "Allow microphone access to record a voice message"}[label]}
            for page in ("home/index", "new-post/index") for label in ("Record video", "Record voice")]
_SEED="void top.sessionStorage.setItem('oi:new-post:%s', JSON.stringify({text: '', media_files: [62], thumbs: ['data:image/gif;base64,R0lGODlhAQABAAAAACw=']}))"
RED_NOTES+=[{"page": page, "steps": _record_steps(label)[:3], "fail": ["POST", "/api/of/v2/upload"], "note": "Could not upload: synthetic failure",
             "prep": _SEED % draft, "kept": f"({_MEDIA})('oi:new-post:{draft}')", "sent": [_record_want(label, False)[0]]}
            for page, draft in (("home/index", "home:1"), ("new-post/index", "1")) for label in ("Record video", "Record voice")]
AFTER+=[("POST", r"/api/of/v2/upload", lambda reads, m, body: {"ready": True, "deduped": False, "vault_id": None, "send_with": [RECORD_CLAIM]})]
_FAN={"id":9001,"name":"Synthetic Fan","username":"synthfan","canRestrict":True,"subscribedOn":True}
_ME={"id":1,"username":"alphaone","name":"Alpha One","chatMessagesCount":1}
_FAN_RECORD={"fan_id":9001,"of_username":"synthfan","of_display_name":"Synthetic Fan","avatar_url":None,"custom_nickname":None,
    "generated_nickname":None,"real_name":None,"his_age":None,"home_country":None,"home_city":None,"hobbies":None,"fetishes":None,
    "self_description":None,"description":None,"notes":None,"tags":[],"lifetime_spend_cents":0,"bought_amount":0,
    "subscription_status":None,"subscribed_at":None,"last_message_received_at":None,"source":"synthetic","is_followed":False,
    "language":None,"language_source":None}
READS.update({
    "/api/of/v2/users/me": _ME,
    "/api/of/v2/chats": {"list":[{"withUser":{"id":9001,"_view":"m"},"lastMessage":{"id":1,"text":"hi","createdAt":"2026-10-10T12:00:00Z","fromUser":_FAN},"unreadMessagesCount":1}],"hasMore":False},
    "/api/of/v2/users/list": {"9001":_FAN},
    "/api/of/v2/chats/9001": {"withUser":_FAN,"isMutedNotifications":False},
    "/api/of/v2/chats/9001/messages": {"list":[
        {"id":11,"text":"<p>hi from fan</p>","createdAt":"2026-10-10T12:00:00Z","fromUser":_FAN,"media":[],"canReport":True},
        {"id":12,"text":"<p>mine</p>","createdAt":"2026-10-10T12:01:00Z","fromUser":_ME,"media":[],"cancelSeconds":0}],"hasMore":False},
    "/api/of/v2/chats/9001/media": {"list":[],"hasMore":False},
    **{f"/admin/fans/{a}/9001": {"account_id":a, **_FAN_RECORD} for a in ("1","acc1")},
    **{f"/admin/fans/{a}/9001/ppv-history": {"items":[],"summary":{"max_cents":0,"avg_cents":0}} for a in ("1","acc1")},
})
_DROPDOWN, _MENU, _CHAT="/of-manager/messages/state-filter-dropdown", "/of-manager/messages/chat/state-header-menu", "/of-manager/messages/chat?chat=9001"
_LIST_LINK="css=[at-attr='sort_dropdown'] a.of-state-link"
_HEAD_LINK="css=.b-chat__header .b-dropdown-wrapper a.of-state-link"
_LIST_MORE="[at-attr='sort_dropdown'] > button"
_HEAD_MORE=".b-chat__header .b-dropdown-wrapper > button.m-btn-vertical-dots:not(.m-size-sm)"
_MSG_MORE="[data-oi-msg='11'] button.m-btn-vertical-dots"
_LIKE="#oi-msg-menu [data-oi-msg-action='like']"
_MSG_ITEMS="[...document.querySelectorAll('#oi-msg-menu [data-oi-msg-action]')].map(i => [i.textContent.trim(), i.getAttribute('aria-disabled') === 'true'])"
_MENU_ITEMS="[...document.querySelectorAll('.of-state-menu [data-oi-menu]')].filter(i => i.checkVisibility()).map(i => i.textContent.trim().replace(/\\s+/g, ' '))"
_DROP_ITEMS="[...document.querySelectorAll('[data-oi-chats]')].filter(i => i.checkVisibility()).map(i => i.textContent.trim().replace(/\\s+/g, ' '))"
_COVER=("(() => { const at = (s) => { const el = [...document.querySelectorAll(s)].find(e => e.checkVisibility()); if (!el) return null;"
        " const r = el.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
        " return h === el || el.contains(h) ? 'reachable' : h?.closest('a[href]')?.getAttribute('href') ?? (h?.closest('.modal, .vdatetime') ? 'dialog' : h?.className ?? null); };"
        " const b = document.querySelector(\"%s\");"
        " const tools = [...document.querySelectorAll('[data-oi-tool]')].filter(t => t.checkVisibility() && at(`[data-oi-tool='${t.dataset.oiTool}']`) === 'reachable').map(t => t.dataset.oiTool);"
        " return [at(\"%s\"), at(\"%s\"), at(\"%s\"), b && [b.hasAttribute('data-oi-msg-menu'), b.disabled], tools]; })()") % (_MSG_MORE, _LIST_MORE, _HEAD_MORE, _MSG_MORE)
_MSG_WANT=[["Copy message text", False], ["Like", False], ["Reply", False], ["Bookmark", False], ["Hide", False], ["Report", False]]
_LIKE_STATE=("(() => { const b = document.querySelector(\"%s\"); b?.click(); const l = document.querySelector(\"%s\")?.textContent.trim() ?? null;"
             " b?.click(); const n = document.getElementById('oi-note');"
             " return [l, !n || n.previousElementSibling === document.querySelector(\"[data-oi-msg='11']\")]; })()") % (_MSG_MORE, _LIKE)
_MARK=["POST","/api/of/v2/chats/mark-as-read",None]
_RESTRICT=["POST","/api/of/v2/users/9001/restrict",None]
_LIKED=["POST","/api/of/v2/messages/11/like",None]
REQUESTS+=[
    {"page":"messages/index", "steps":[_LIST_LINK], "want":[], "opens":_DROPDOWN},
    {"page":"messages/state-filter-dropdown", "steps":[_LIST_LINK], "want":[], "opens":"/of-manager/messages"},
    *({"page":f"messages/{p}?chat=9001", "steps":[_LIST_LINK], "want":[], "opens":f"{_DROPDOWN}?chat=9001"}
      for p in ("chat","chat/gallery","chat/pinned","chat/state-header-menu")),
    {"page":"messages/state-filter-dropdown?chat=9001", "steps":[], "want":[], "after":[_DROP_ITEMS, ["All","Priority","Unread","Newest First","Oldest First","Mark all as read"]]},
    {"page":"messages/state-filter-dropdown", "steps":["Mark all as read"], "want":[_MARK]},
    {"page":"messages/chat?chat=9001", "steps":[_HEAD_LINK], "want":[], "opens":f"{_MENU}?chat=9001"},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":[_HEAD_LINK], "want":[], "opens":_CHAT},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":[], "want":[], "after":[_MENU_ITEMS,
     ["Copy link to profile","Rename user","Add to / remove from lists","View user's comments","Hide chat","Mute notifications","Restrict","Block","Report"]]},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":["Restrict"], "want":[_RESTRICT]},
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE], "want":[], "after":[_MSG_ITEMS, _MSG_WANT]},
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE, "css="+_LIKE], "want":[_LIKED]},
    {"page":"messages/state-folders", "steps":[], "want":[], "after":[_COVER, ["/of-manager/messages", None, None, None, []]]},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":[], "want":[], "after":[_COVER, [f"{_DROPDOWN}?chat=9001", _CHAT, _CHAT, [True, False], ["rename","lists","notes"]]]},
    {"page":"messages/chat/state-price?chat=9001", "steps":[], "want":[], "after":[_COVER, [_CHAT, _CHAT, _CHAT, [True, False], []]]},
    {"page":"messages/chat/state-schedule?chat=9001", "steps":[], "want":[], "after":[_COVER, [_CHAT, _CHAT, "dialog", [True, False], []]]},
    {"page":"messages/chat/state-tag-people?chat=9001", "steps":[], "want":[], "after":[_COVER, [_CHAT, _CHAT, "dialog", [True, False], []]]},
    {"page":"messages/chat/state-vault?chat=9001", "steps":[], "want":[], "after":[_COVER, ["dialog", _CHAT, "dialog", [True, False], []]]},
]
RED_NOTES+=[
    {"page":"messages/state-filter-dropdown", "steps":["Mark all as read"], "fail":_MARK[:2],
     "kept":"location.pathname + location.search", "note":"Could not mark all as read: synthetic failure"},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":["Restrict"], "fail":_RESTRICT[:2],
     "kept":"document.querySelector(\".of-state-menu [data-oi-menu='restrict']\")?.textContent.trim()"},
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE, "css="+_LIKE], "fail":_LIKED[:2],
     "kept":_LIKE_STATE, "note":"Could not like: synthetic failure"},
]

_FOLDER, _FOLDER_PAGE="701", "vault/list?list=701"
_RENAME_PAGE=f"vault/state-add-list?list={_FOLDER}&edit=1"
_FOLDER_MORE="css=.l-main-content.m-r-side [at-attr='list_dropdown'] > button"
def _rename_steps(name): return [["css=.modal input[at-attr='input']", name], "css=.modal-footer button[type='submit']"]
_DELETE_STEPS=[_FOLDER_MORE, "css=#oi-menu [data-oi-value='delete']"]
_RENAME=["POST", f"/admin/vault-ai/of-folders/{_FOLDER}/rename"]
_DELETE=["DELETE", f"/admin/vault-ai/of-folders/{_FOLDER}"]
READS.update({
    "/api/of/v2/vault/lists": {"list":[{"id":int(_FOLDER),"type":"custom","name":"Synthetic folder","hasMedia":True,"photosCount":1,"videosCount":0}],"hasMore":False},
    "/api/of/v2/vault/media": {"list":[],"hasMore":False},
})
REQUESTS+=[
    {"page":_FOLDER_PAGE, "steps":[_FOLDER_MORE, "css=#oi-menu [data-oi-value='rename']"], "want":[], "opens":f"/of-manager/{_RENAME_PAGE}"},
    {"page":_RENAME_PAGE, "steps":_rename_steps("Renamed folder"), "want":[[*_RENAME, {"account_id":"1","name":"Renamed folder"}]], "opens":f"/of-manager/vault?list={_FOLDER}"},
    {"page":_FOLDER_PAGE, "steps":_DELETE_STEPS, "want":[[*_DELETE, None]], "opens":"/of-manager/vault"},
]
RED_NOTES+=[
    {"page":_RENAME_PAGE, "steps":_rename_steps("Unsaved folder"), "fail":_RENAME, "kept":"location.pathname + location.search", "note":"Could not rename: synthetic failure"},
    {"page":_FOLDER_PAGE, "steps":_DELETE_STEPS, "fail":_DELETE, "kept":"location.pathname + location.search", "note":"Could not delete: synthetic failure"},
]
_LIST="messages/send/state-list-dropdown"
LIST_PICK_INIT=r"""(() => {
  const click = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    // frame doc is written into about:blank, so the page is checked per call
    if (this.type !== 'file' || !location.pathname.endsWith('/messages/send/state-list-dropdown.html')) return click.call(this);
    const dt = new DataTransfer();
    dt.items.add(new File(['synthetic'], 'pick.png', { type: 'image/png' }));
    this.files = dt.files;
    this.dispatchEvent(new Event('change'));
  };
})();"""
INIT+=LIST_PICK_INIT
_GIF="data:image/gif;base64,R0lGODlhAQABAAAAACw="
READS["/api/of/v2/giphy/proxy/gifs/trending"]={"data":[{"id":"g1","title":"Wave","images":{"fixed_height":{"url":_GIF},"fixed_height_still":{"url":_GIF}}}]}
_DRAFT="(JSON.parse(sessionStorage.getItem('oi:mass:1') || '{}')[%s] ?? null)"
_PNG_UP=["POST","/api/of/v2/upload",{"file":{"type":"image/png","ext":".png"}}]
_MASS_SEED="void sessionStorage.setItem('oi:mass:1', JSON.stringify(%s))"
_FORMAT_PREP=(r"""(() => { const e = document.querySelector("[contenteditable][aria-label='Textbox field']"); e.innerHTML = '<p>hi</p>'; const r = document.createRange();"""
              r""" r.selectNodeContents(e); const s = getSelection(); s.removeAllRanges(); s.addRange(r); })()""")
_MASS_ONE={"text":"","user_lists":[],"media_files":[62],"thumbs":[_GIF]}
REQUESTS+=[
    {"page":_LIST, "steps":["Add media"], "want":[_PNG_UP], "after":[_DRAFT % "'media_files'", [RECORD_CLAIM]]},
    *({"page":_LIST, "steps":[label, _RECORD_BUTTON[label], _RECORD_BUTTON[label]], "want":_record_want(label, False),
       "after":[_DRAFT % "'media_files'", [RECORD_CLAIM]]} for label in ("Record video", "Record voice")),
    {"page":_LIST, "steps":["Add GIF", "css=[data-oi-gif='g1']"], "want":[], "after":[_DRAFT % "'giphy_id'", "g1"]},
    {"page":_LIST, "steps":["Scheduled messages", "Save for Later"], "want":[], "after":[_DRAFT % "'save_for_later'", True]},
    {"page":_LIST, "steps":["Add media from vault"], "want":[], "opens":"/of-manager/messages/send/state-vault"},
    {"page":_LIST, "steps":["Message price"], "want":[], "opens":"/of-manager/messages/send/state-price"},
    {"page":_LIST, "steps":["Tag other creators"], "want":[], "opens":"/of-manager/messages/send/state-tag-people"},
    {"page":_LIST, "steps":["Format Text"], "want":[], "opens":"/of-manager/messages/send?format=1"},
    {"page":"messages/send?format=1", "prep":_FORMAT_PREP, "steps":["css=[data-oi-format-panel] [aria-label='Bold']"], "want":[],
     "after":["[document.querySelector('[data-oi-format-panel]')?.classList.contains('b-form-editor') ?? null, %s]" % (_DRAFT % "'html'"),
              [True, "<p><strong>hi</strong></p>"]]},
    {"page":_LIST, "prep":_MASS_SEED % json.dumps({**_MASS_ONE, "price":5, "tags":[{"id":7,"name":"Co Creator","type":"user"}]}),
     "steps":["Scheduled messages", "Save for Later"], "want":[],
     "after":["document.getElementById('oi-chat-summary')?.textContent ?? null", "1 media · Tagged: Co Creator · Price: $5 · Saved for later · Clear"]},
]
RED_NOTES+=[{"page":_LIST, "steps":steps, "fail":["POST","/api/of/v2/upload"], "note":"Could not upload: synthetic failure",
             "prep":_MASS_SEED % json.dumps(_MASS_ONE), "kept":_DRAFT % "'media_files'", "sent":[want]}
            for steps, want in ((["Add media"], _PNG_UP),
                                *(([label, _RECORD_BUTTON[label], _RECORD_BUTTON[label]], _record_want(label, False)[0])
                                  for label in ("Record video", "Record voice")))]

_PPV={"text":"<p>ppv</p>","fromUser":_ME,"price":5,"media":[{"id":62,"type":"photo","canView":True}],"isFree":False}
READS["/api/of/v2/chats/9001/messages"]["list"][:0]=[
    {"id":13,"createdAt":"2026-10-10T11:58:00Z","cancelSeconds":90,**_PPV},
    {"id":14,"createdAt":"2026-10-10T11:59:00Z","cancelSeconds":0,**_PPV}]
_BUBBLE="[data-oi-msg='%s'] [data-oi-bubble='%s']"
_UNSEND_BTN="css="+_BUBBLE % (13, "unsend-ppv")
_CONFIRM_BTN="css=#oi-msg-confirm footer button:has-text('%s')"
_UNSEND=["DELETE","/api/of/v2/messages/13",{"withUserId":9001}]
_TICK=("(async () => { const c = () => document.querySelector(\"%s\")?.textContent ?? null; const a = c();"
       " await new Promise(r => setTimeout(r, 1100)); const b = c(); return [/^1:[0-5]\\d$/.test(a ?? ''), a !== b, /^1:[0-5]\\d$/.test(b ?? '')]; })()") % (_BUBBLE % (13, "countdown"))
_EXTRAS="[...document.querySelectorAll(\"[data-oi-msg='%s'] [data-oi-bubble]\")].map(e => e.dataset.oiBubble)"
_CHAT_DRAFT="(() => { const d = JSON.parse(sessionStorage.getItem('oi:chat:1:9001') || '{}'); return [d.text ?? null, d.price ?? null, d.media_files ?? null, document.querySelector(\"[contenteditable][aria-label='Textbox field']\")?.textContent ?? null]; })()"
_BUBBLE_KEPT="(() => { const b = document.querySelector(\"[data-oi-msg='13']\"); const n = document.getElementById('oi-note'); return [!!b, !n || n.previousElementSibling === b]; })()"
REQUESTS+=[
    {"page":"messages/chat?chat=9001", "steps":[], "want":[], "after":[_TICK, [True, True, True]]},
    {"page":"messages/chat?chat=9001", "steps":[], "want":[], "after":["[%s, %s]" % (_EXTRAS % 13, _EXTRAS % 14), [["countdown","copy-draft","unsend-ppv"], ["copy-draft"]]]},
    {"page":"messages/chat?chat=9001", "steps":["css="+_BUBBLE % (13, "copy-draft")], "want":[], "after":[_CHAT_DRAFT, ["ppv", 5, [62], "ppv"]]},
    {"page":"messages/chat?chat=9001", "steps":[_UNSEND_BTN, _CONFIRM_BTN % "Cancel"], "want":[], "after":[_BUBBLE_KEPT, [True, True]]},
    {"page":"messages/chat?chat=9001", "steps":[_UNSEND_BTN, _CONFIRM_BTN % "Unsend"], "want":[_UNSEND],
     "after":["[!!document.querySelector(\"[data-oi-msg='13']\"), document.getElementById('oi-note')?.textContent ?? null]", [False, "Unsent"]]},
]
def _unsent(reads, m, body):
    t=reads["/api/of/v2/chats/9001/messages"]; t["list"]=[x for x in t["list"] if str(x["id"])!=m[1]]
AFTER+=[("DELETE", r"/api/of/v2/messages/(\d+)", _unsent)]
VIEWS|={i: "messages/chat?chat=9001" for i in ("p2.bubble-countdown", "p2.bubble-copy-draft", "p2.bubble-unsend-ppv")}
RED_NOTES+=[{"page":"messages/chat?chat=9001", "steps":[_UNSEND_BTN, _CONFIRM_BTN % "Unsend"], "fail":_UNSEND[:2],
             "reads":{"/api/of/v2/chats/9001/messages": READS["/api/of/v2/chats/9001/messages"]},
             "kept":_BUBBLE_KEPT, "note":"Could not unsend: synthetic failure", "sent":[_UNSEND]}]

_CHAT_REPORT="https://onlyfans.com/my/chats/chat/9001/"
_POST_REPORT="https://onlyfans.com/77/synthcreator"
_THEIRS={"id":77,"text":"<p>theirs</p>","postedAt":"2026-10-10T10:05:00Z","author":{"id":4242,"username":"synthcreator","name":"Synth Creator"},"media":[]}
HANDOFFS=[
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":["css=.of-state-menu a[data-oi-menu='report']"], "handoff":_CHAT_REPORT, "text":"Report"},
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE, "css=#oi-msg-menu a[data-oi-msg-action='report']"], "handoff":_CHAT_REPORT, "text":"Report"},
    {"page":"home/index", "steps":["css=[data-oi-post='77'] .b-post__tools__more button", "css=[data-oi-post-menu] a[data-oi-action='report']"],
     "handoff":_POST_REPORT, "text":"Report", "reads":{"/api/of/v2/posts":[_THEIRS]}},
]

if __name__=="__main__":
    phase_check.run("content-writes", phase2.PROOFS, REQUESTS, RED_NOTES, READS, AFTER, init=INIT, views=VIEWS, handoffs=HANDOFFS)
