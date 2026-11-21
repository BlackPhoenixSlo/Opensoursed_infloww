"""Phase 2's Mirror check (docs/spec/ofm-not-yet/phase-02-content-chat-writes.md, Testing Decisions): Home, New post,
My profile, Messages Basic, Vault, Queue, Collections/Bookmarks and Release forms controls, relay mocked, on
phase_check.py's harness (its docstring: mocks, table rows, checks, --plant, --captures).

Its control list is the Phase 2 proof list (scripts/of-live-proof/proofs/phase2.py PROOFS: page, control as the Not-yet
sweep labels it), each control's capture record found as `phase2.py --check-sweep` finds it (check 1, runtime state,
D18/D1). Each Phase 2 control ticket adds its Proof there and its rows here: REQUESTS (its request with X-Account-Id 1,
from its proof's capture record), RED_NOTES (a mocked 502 shows the red note and keeps the last saved state, story 38), and READS/AFTER (the mocked reads
a write changes, so its read-back shows it). Empty until the first Phase 2 control ticket: the check then loads
home/index and checks no console errors.
Screenshots: /tmp/of-mirror-shots/inapp-content-writes-*.png. Exit 1 on a failed check.

    PORT=3091 python3 -I scripts/of-mirror-check/content_writes.py [--plant rows.json] [--captures dir]
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_check  # noqa: E402  (puts scripts/of-live-proof on the path)
from proofs import phase2  # noqa: E402

REQUESTS=[]       # {"proof", "steps", "fill"} or {"page", "steps", "want": [[method, path, body]]}
RED_NOTES=[]      # {"page", "steps", "fail": [method, path], "kept": js, "note": text}
READS={}          # GET /api/of/v2/<path> -> JSON
AFTER=[]          # (method, path regex, fn(reads, match, body))

INIT=""           # a script run in every page and frame before its own (phase_check.py docstring)

# ticket 30
# Record video and Record voice (Home, its State pages, New post): getUserMedia and MediaRecorder stubbed by the init
# script (spec Testing Decisions, Mirror check 2): a synthetic stream (a canvas's, a real MediaStream, so video-js can
# show it) and a recorder whose Blob has the asked type; it records video/mp4 and audio/webm (Chrome's: neither of OF's
# voice types, audio/mpeg nor audio/ogg), so a video goes up as mp4 and a voice note is re-encoded to WAV on upload
# (ticket 53v, ofMirrorComposer voiceFile): the voice Blob's bytes are a real 16 kHz WAV (Web Audio decodes by content,
# whatever the label), so the re-encode runs and the upload is audio/wav .wav. The upload is answered with
# post_upload.py's claim, so the next Post carries it.
# ASSUMPTION: a Single-Creator row per control on every Home and New post page whose composer takes a mouse click
# (index, and the State pages that open in the composer: Format text, poll, quiz); every other State page lays its
# dialog and backdrop over the composer, so a click there goes to the dialog, as on OF, and vitest (ofMirrorPost.test.ts)
# covers the binding on those pages. Post's body is vitest's (empty text, the claim, price 0); the refused
# camera/microphone are red-note rows on home/index and new-post/index only (rung 5); overturned by a reviewer wanting
# the rows on every page, or by a State page whose composer is reachable.
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
# The voice panel asks for the microphone on its own record button (OF's order), the video recorder on opening.
RED_NOTES+=[{"page": page, "steps": [label] + ([_RECORD_BUTTON[label]] if label == "Record voice" else []), "prep": _REFUSE, "sent": [],
             "note": {"Record video": "Allow camera access to record a video message",
                      "Record voice": "Allow microphone access to record a voice message"}[label]}
            for page in ("home/index", "new-post/index") for label in ("Record video", "Record voice")]
# The 502 rows seed the draft with one earlier media item, so "kept" ([62] before and after, in the log) shows the failure drops nothing.
_SEED="void top.sessionStorage.setItem('oi:new-post:%s', JSON.stringify({text: '', media_files: [62], thumbs: ['data:image/gif;base64,R0lGODlhAQABAAAAACw=']}))"
RED_NOTES+=[{"page": page, "steps": _record_steps(label)[:3], "fail": ["POST", "/api/of/v2/upload"], "note": "Could not upload: synthetic failure",
             "prep": _SEED % draft, "kept": f"({_MEDIA})('oi:new-post:{draft}')", "sent": [_record_want(label, False)[0]]}
            for page, draft in (("home/index", "home:1"), ("new-post/index", "1")) for label in ("Record video", "Record voice")]
AFTER+=[("POST", r"/api/of/v2/upload", lambda reads, m, body: {"ready": True, "deduped": False, "vault_id": None, "send_with": [RECORD_CLAIM]})]
# ticket 31: the chat list header's More, the chat header's More and each message's More on the messages list, its
# dropdown and folders dialog, the chat page and every State page over it (gallery draws neither the header's nor a
# message's More; pinned's header button is its own Unpin all). Where a More is reachable, a mouse click opens the chat
# page's menu (the generator's State link over the list's and the header's More; the message menu over the thread) and
# one write item per menu sends what it sends on the chat page: Mark all as read, Restrict and Like. Where a State page's
# dialog or menu backdrop lies over a More, the row checks what a click there lands on (the backdrop's link back to the
# base page, or the dialog): no mouse reaches the More, as on OF; dead.py and the proof sweep check it Wired. No item
# here sends to a fan. Mocks as messages.py's, plus a
# fan message (11, Like on it) and an unread chat (Mark all as read on).
# ASSUMPTION: where a State page's dialog or backdrop covers a More (the bubble's on all five chat State pages; the
# list's on folders, price, schedule, tag-people, vault; the header's on price, schedule, tag-people, vault), criterion 1
# is met by Wired (dead.py) plus the click landing on OF's backdrop link or dialog (rung 1 the measured cover, rung 3
# "as on OF"); the bubble's More is enabled at bind (no State link over it, so disabled would be Wired in name only)
# while the list and header Mores stay disabled under their State link. Overturned if the owner wants those menus
# reachable over the dialog.
# ASSUMPTION: Restrict's ?ack=false&hide=false is not checked here (the harness records the path only; chatToolWrites'
# vitest holds the query, and both pages call that one builder) (rung 3); overturned if the recorder is widened.
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
# What a mouse click at each More's centre lands on ("reachable": the More itself; else the link's href, or "dialog"),
# message 11's drawn ⋮ ([tagged for the message menu, disabled]: as the chat page's), and the header tools a mouse
# reaches (ofMirrorChatTools wires the pencil, star and notes on every State page; a dialog covers them on most).
_COVER=("(() => { const at = (s) => { const el = [...document.querySelectorAll(s)].find(e => e.checkVisibility()); if (!el) return null;"
        " const r = el.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);"
        " return h === el || el.contains(h) ? 'reachable' : h?.closest('a[href]')?.getAttribute('href') ?? (h?.closest('.modal, .vdatetime') ? 'dialog' : h?.className ?? null); };"
        " const b = document.querySelector(\"%s\");"
        " const tools = [...document.querySelectorAll('[data-oi-tool]')].filter(t => t.checkVisibility() && at(`[data-oi-tool='${t.dataset.oiTool}']`) === 'reachable').map(t => t.dataset.oiTool);"
        " return [at(\"%s\"), at(\"%s\"), at(\"%s\"), b && [b.hasAttribute('data-oi-msg-menu'), b.disabled], tools]; })()") % (_MSG_MORE, _LIST_MORE, _HEAD_MORE, _MSG_MORE)
# The chat page's items, as it shows them (measured on messages/chat?chat=9001; no Pin: message 11 has no canBePinned).
_MSG_WANT=[["Copy message text", False], ["Like", False], ["Reply", False], ["Bookmark", False], ["Hide", False], ["Report", True]]
# Message 11's menu Like label (the thread draws no like state; the menu reads it) and #oi-note right after its bubble
# when there is a note.
_LIKE_STATE=("(() => { const b = document.querySelector(\"%s\"); b?.click(); const l = document.querySelector(\"%s\")?.textContent.trim() ?? null;"
             " b?.click(); const n = document.getElementById('oi-note');"
             " return [l, !n || n.previousElementSibling === document.querySelector(\"[data-oi-msg='11']\")]; })()") % (_MSG_MORE, _LIKE)
_MARK=["POST","/api/of/v2/chats/mark-as-read",None]
_RESTRICT=["POST","/api/of/v2/users/9001/restrict",None]
_LIKED=["POST","/api/of/v2/messages/11/like",None]
REQUESTS+=[
    # The list header's More: its State link opens the sort dropdown (with the open chat); on the dropdown it closes it.
    {"page":"messages/index", "steps":[_LIST_LINK], "want":[], "opens":_DROPDOWN},
    {"page":"messages/state-filter-dropdown", "steps":[_LIST_LINK], "want":[], "opens":"/of-manager/messages"},
    *({"page":f"messages/{p}?chat=9001", "steps":[_LIST_LINK], "want":[], "opens":f"{_DROPDOWN}?chat=9001"}
      for p in ("chat","chat/gallery","chat/pinned","chat/state-header-menu")),
    # The dropdown's items (measured; Unread with tips hides while the Creator has no tipsEnabled), and its write.
    {"page":"messages/state-filter-dropdown?chat=9001", "steps":[], "want":[], "after":[_DROP_ITEMS, ["All","Priority","Unread","Newest First","Oldest First","Mark all as read"]]},
    {"page":"messages/state-filter-dropdown", "steps":["Mark all as read"], "want":[_MARK]},
    # The chat header's More: its State link opens the chat's menu; on the menu it closes it. The menu's items (measured).
    {"page":"messages/chat?chat=9001", "steps":[_HEAD_LINK], "want":[], "opens":f"{_MENU}?chat=9001"},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":[_HEAD_LINK], "want":[], "opens":_CHAT},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":[], "want":[], "after":[_MENU_ITEMS,
     ["Copy link to profile","Rename user","Add to / remove from lists","View user's comments","Hide chat","Mute notifications","Restrict","Block","Report"]]},
    {"page":"messages/chat/state-header-menu?chat=9001", "steps":["Restrict"], "want":[_RESTRICT]},
    # Each message's More opens the chat page's message menu; Like sends the chat page's like.
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE], "want":[], "after":[_MSG_ITEMS, _MSG_WANT]},
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE, "css="+_LIKE], "want":[_LIKED]},
    # Covered: a click at each More lands on the backdrop's link to the base page or in the dialog, and no header tool is
    # reachable under a dialog (measured); the header menu page's tools are (its own menu page, bound before ticket 31).
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
    # Like undone (the menu still says Like), the note under message 11 after the undo's redraw.
    {"page":"messages/chat?chat=9001", "steps":["css="+_MSG_MORE, "css="+_LIKE], "fail":_LIKED[:2],
     "kept":_LIKE_STATE, "note":"Could not like: synthetic failure"},
]

# ticket 34: the vault folder page's header More (vault/list?list=<id>, the one header More there, ofMirrorVault
# bindFolderMore) opens the folder menu: Rename opens the folder's Rename category modal (state-add-list?edit=1, as the
# action row's RENAME; its Save sends the rename and opens the Vault on the folder) and Delete (confirmed; the harness
# accepts the confirm) goes back to the bare Vault. The vault list's own routes: POST
# /admin/vault-ai/of-folders/<id>/rename {account_id, name} and DELETE /admin/vault-ai/of-folders/<id>?account_id=
# (the recorder keeps the path only; useVaultCache's deleteOfFolder adds the query, its X-Account-Id is checked here).
# Mocks: one synthetic custom folder (701), no media.
_FOLDER, _FOLDER_PAGE="701", "vault/list?list=701"
_RENAME_PAGE=f"vault/state-add-list?list={_FOLDER}&edit=1"
_FOLDER_MORE="css=.l-main-content.m-r-side [at-attr='list_dropdown'] > button"
def _rename_steps(name): return [["css=.modal input[at-attr='input']", name], "css=.modal-footer button[type='submit']"]
_DELETE_STEPS=[_FOLDER_MORE, "css=#oi-menu [data-oi-value='delete']"]
_RENAME=["POST", f"/admin/vault-ai/of-folders/{_FOLDER}/rename"]
_DELETE=["DELETE", f"/admin/vault-ai/of-folders/{_FOLDER}"]
READS.update({
    "/api/of/v2/vault/lists": {"list":[{"id":int(_FOLDER),"type":"custom","name":"Synthetic folder","hasMedia":True,"photosCount":1,"videosCount":0}],"hasMore":False},
    "/api/of/v2/vault/media": {"list":[],"hasMore":False},   # no tile: a tile's picture goes through the Relay's /img
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
# ticket 32: New message's list page (its list menu open, messages/send/state-list-dropdown): the nine composer tools,
# on the Mass draft (`oi:mass:<accountId>`) only; its Send is never clicked here. Add media's picker is stubbed on that
# page by the init script (one synthetic PNG); Record as ticket 30's. In place: Add media, Add GIF, Record video and
# voice, Scheduled messages (the draft's fields after the click). The vault, price and tag buttons open New message's
# dialogs and Format Text New message with its panel open (`opens`, `?format=1`; a click outside OF's list menu closes
# it; the landing page's row then applies Bold and reads the draft's html): those
# dialogs keep their picks on the same Mass draft (vitest, ofMirrorComposer.test.ts), and the summary row shows the list
# page names such picks (seeded) with its own schedule.
# ASSUMPTION: the navigating tools' draft effect is checked by `opens` plus the seeded summary row, not by a pick in
# the dialog (rung 5: the harness's frame detaches on the app's navigation, and the dialogs' picks are vitest's and
# their own tickets'); overturned by a harness that follows the frame across a navigation, which then adds the picks.
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
# New message's editor holds "hi", selected (Bold then formats it).
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
    # Where Format Text lands: New message with its Format text panel open; Bold on the selected text reaches the draft.
    {"page":"messages/send?format=1", "prep":_FORMAT_PREP, "steps":["css=[data-oi-format-panel] [aria-label='Bold']"], "want":[],
     "after":["[document.querySelector('[data-oi-format-panel]')?.classList.contains('b-form-editor') ?? null, %s]" % (_DRAFT % "'html'"),
              [True, "<p><strong>hi</strong></p>"]]},
    # The dialogs' picks (vault media, price, a co-tagged creator) on the draft: the list page's line names them.
    {"page":_LIST, "prep":_MASS_SEED % json.dumps({**_MASS_ONE, "price":5, "tags":[{"id":7,"name":"Co Creator","type":"user"}]}),
     "steps":["Scheduled messages", "Save for Later"], "want":[],
     "after":["document.getElementById('oi-chat-summary')?.textContent ?? null", "1 media · Tagged: Co Creator · Price: $5 · Saved for later · Clear"]},
]
RED_NOTES+=[{"page":_LIST, "steps":steps, "fail":["POST","/api/of/v2/upload"], "note":"Could not upload: synthetic failure",
             "prep":_MASS_SEED % json.dumps(_MASS_ONE), "kept":_DRAFT % "'media_files'", "sent":[want]}
            for steps, want in ((["Add media"], _PNG_UP),
                                *(([label, _RECORD_BUTTON[label], _RECORD_BUTTON[label]], _record_want(label, False)[0])
                                  for label in ("Record video", "Record voice")))]

if __name__=="__main__":
    phase_check.run("content-writes", phase2.PROOFS, REQUESTS, RED_NOTES, READS, AFTER, init=INIT)
