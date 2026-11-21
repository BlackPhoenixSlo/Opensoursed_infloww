"""dead.py's Messages rows (tickets 16 and 31; dead.py's MODULES): chat Find, select mode and the folders dialog's Sort
(PHASE1, READS and their mocks, in dead.py's shapes), the folders' pin write (ALLOWED_RE) and the chat Mores (MARKED)."""
import re
from dead_lib import READ_ONLY
PHASE1=[]; READS=[]; SOURCES={}; V2={}; ALLOWED_RE=[]
# ticket 16: chat Find, select mode, the folders dialog's Sort (story 29, 30). Its PHASE1 rows are "not-yet" (AC6: the
# title stays until the Live pass, D1). Its READS rows use dead.py's "query" (a chat State page needs its ?chat=) and
# "get": None (a client-side control); Select's snapshot reads the list it opens (frame_now). Their bodies:
# chat 2001 has two messages with "needle"; its search answers only the second for "needle" (anything else: none), so a
# dropped query shows no hit and a client-side text match marks the first one too.
CHAT16="2001"
def msg16(i, text, day):
    return {"responseType":"message","id":i,"text":f"<p>{text}</p>","fromUser":{"id":int(CHAT16)},"isFree":True,"price":0,
            "mediaCount":0,"media":[],"previews":[],"isTip":False,"createdAt":f"2026-10-{day}T10:00:00+00:00","chatUserId":int(CHAT16)}
SOURCES[f"/api/of/v2/chats/{CHAT16}/messages"]={"list":[msg16(11002,"Synthetic needle two",18), msg16(11001,"Synthetic needle one",17)],"hasMore":False}
V2[f"/api/of/v2/chats/{CHAT16}/messages/search"]=("query", [], {"needle":[11002]})
# The find bar's count and its marks (bubble id: marked text).
FIND16="() => ({ count: document.querySelector('.b-chat__search__results-count')?.textContent.trim() ?? null, marks: [...document.querySelectorAll('.b-chat__message__text-highlighted')].map(e => `${e.closest('[data-oi-msg]')?.getAttribute('data-oi-msg')}:${e.textContent}`) })"
FIND16_BTN="css:button[at-attr='search_btn']"
# Find: read on the header menu's State page, the one chat State page where the operator's click reaches it (the
# coordinator's carve-out, 2026-11-21: price, schedule, tag people and vault lay a backdrop over the chat header).
PHASE1.append(("messages/chat/state-header-menu", FIND16_BTN, "not-yet"))
READS.append({"page":"messages/chat/state-header-menu", "query":f"chat={CHAT16}",
              "steps":[("click", FIND16_BTN), ("fill", "css:.b-chat__header form.b-chat__search-form input[name='query']", "needle")],
              "get":[(f"/api/of/v2/chats/{CHAT16}/messages/search", {"query":"needle"})],
              "settled":FIND16, "shows":['"count": "1/1"', '"marks": ["11002:needle"]'], "hides":["11001:"]})
# Select (client-side select mode, story 29): the dropdown's Select opens the list in select mode (?select=1) with its
# selection bar; the bar's Cancel leaves it; its Delete (a write, Phase 2 story 50) gives the Read-only note. No GET at
# all during any. The snapshot: the bar's buttons' labels (null: no bar), the note and whether the URL has ?select=1;
# SELECT16_BAR throws until the bar is drawn, so a click that opens no select mode never settles.
SELECT16_JS="""const bar = document.querySelector('[data-oi-select-bar]');
  const on = !!bar && bar.checkVisibility();
  %s
  return { bar: on ? [...bar.querySelectorAll('button')].filter(b => b.checkVisibility()).map(b => b.getAttribute('aria-label') || b.textContent.trim()) : null,
    note: document.getElementById('oi-note')?.textContent ?? null,
    select: new URLSearchParams(parent.location.search).get('select') === '1' };"""
SELECT16="() => {\n  %s\n}" % (SELECT16_JS % "")
SELECT16_BAR="() => {\n  %s\n}" % (SELECT16_JS % "if (!on) throw new Error('no bar yet');")
SELECT16_ITEM="css:[data-oi-select]"
PHASE1.append(("messages/state-filter-dropdown", SELECT16_ITEM, "not-yet"))
# Picking in select mode (the list's capture-phase click hijack): two synthetic chats, answered only for folder 916's
# list (V2 keyed on `list_id`; no folder the sweep can open has that id, so no swept page draws them). A row's click
# ticks its box and opens no chat (the URL stays); Select all then ticks every row and turns into Deselect. Each with
# no GET at all.
# ASSUMPTION: the chats stay off the bare list: there every row's Clear messages is Silent (its confirm()
# is dismissed by session() and the button is unmarked), a gap of the Clear wiring (issue 128), not of ticket 16.
# Overturned once Clear is swept.
def chat16(i):
    return {"withUser":{"id":i,"_view":"m"},"canSendMessage":True,"canGoToProfile":True,"unreadMessagesCount":0,"hasUnreadTips":False,
            "isMutedNotifications":False,"lastMessage":{"id":i*10,"isOpened":True,"createdAt":f"2026-10-{i-1983}T10:00:00+00:00",
            "text":f"<p>Synthetic last message {i}</p>","isFree":True,"mediaCount":0,"isTip":False,"fromUser":{"id":i}},
            "lastReadMessageId":i*10,"countPinnedMessages":0}
V2["/api/of/v2/chats"]=("list_id", [], {"916":{"list":[chat16(2002), chat16(2001)], "hasMore":False}})
SOURCES["/api/of/v2/users/list"]={str(i): {"id":i, "view":"m", "name":f"Synthetic Fan {i}", "username":f"u_synthetic_{i}"} for i in (2001, 2002)}
PICK16="() => ({ url: parent.location.pathname + parent.location.search, ticked: [...document.querySelectorAll('.b-chats__item[data-oi-chat]')].filter(r => r.querySelector('[data-oi-select-box]')?.checked).map(r => r.dataset.oiChat), all: [...document.querySelectorAll('[data-oi-select-bar] button')].map(b => b.textContent.trim()).find(t => t === 'Select all' || t === 'Deselect') ?? null })"
ROW16="css:.b-chats__item[data-oi-chat='2001'] .b-chats__item__link"
SELECT_ALL16="css:[data-oi-select-bar] .b-btns-group button:not([data-oi-select-delete])"
READS+=[
    {"page":"messages/index", "query":"folder=916&select=1", "steps":[("click", ROW16)], "get":None, "settled":PICK16,
     "shows":['"url": "/of-manager/messages?folder=916&select=1"', '"ticked": ["2001"]', '"all": "Select all"']},
    {"page":"messages/index", "query":"folder=916&select=1", "steps":[("click", ROW16), ("click", SELECT_ALL16)], "get":None, "settled":PICK16,
     "shows":['"url": "/of-manager/messages?folder=916&select=1"', '"ticked": ["2002", "2001"]', '"all": "Deselect"']},
]
READS+=[
    {"page":"messages/state-filter-dropdown", "steps":[("click", SELECT16_ITEM)], "get":None, "settled":SELECT16_BAR,
     "shows":['"bar": ["Cancel", "Select all", "Delete"]', '"select": true']},
    {"page":"messages/index", "query":"select=1", "steps":[("click", "css:[data-oi-select-bar] button[aria-label='Cancel']")],
     "get":None, "settled":SELECT16, "shows":['"bar": null', '"select": false']},
    {"page":"messages/index", "query":"select=1", "steps":[("click", "css:[data-oi-select-bar] [data-oi-select-delete]")],
     "get":None, "settled":SELECT16, "shows":[f'"note": "{READ_ONLY}"', '"select": true']},
]
# Folders Sort (story 30): OF's lists sort menu orders the dialog's lists client-side, over /chats/folders as read; each
# pick a navigation to the dialog in that sort (?fsort=&forder=), no GET, no write. The folders: as read they show
# pinned first, then by name (Custom); Recent, Name and People (each Descending, the menu's default) all differ.
def folder16(i, name, users, pinned=False):
    return {"id":str(i), "type":"custom", "name":name, "usersCount":users, "canPinnedToChat":True, "isPinnedToChat":pinned}
SOURCES["/api/of/v2/chats/folders"]={"list":[folder16(100,"Synthetic folder Alpha",3), folder16(300,"Synthetic folder Delta",9),
    folder16(400,"Synthetic folder Bravo",1,True), folder16(200,"Synthetic folder Charlie",5)], "hasMore":False}
# The dialog's boxes pin a list (PATCH /lists/{id}/pin-chat, an existing Wired write: ofMirrorChats pinFolder): with
# these folders the sweep's clicks send it, so it joins the allow-list (decisions.md D-rule).
ALLOWED_RE.append(("PATCH", re.compile(r"/api/of/v2/lists/[^/]+/pin-chat")))
FOLDERS16="() => [...document.querySelectorAll('.modal label.b-rows-lists__item[data-oi-list]')].filter(r => r.checkVisibility()).map(r => r.querySelector('.b-rows-lists__item__name').textContent.trim().replace('Synthetic folder ', '')).join(' > ')"
SORT16="css:.modal button[aria-label='Sort']"
PHASE1.append(("messages/state-folders", SORT16, "not-yet"))
READS+=[{"page":"messages/state-folders", "query":query, "steps":[("click", SORT16), ("click", f"css:#oi-menu [data-oi-value='{pick}']")],
         "get":None, "settled":FOLDERS16, "shows":[want], "hides":[was]}
        for query, pick, want, was in [
            ("", "recent", "Bravo > Delta > Charlie > Alpha", "Bravo > Alpha > Charlie > Delta"),
            ("", "name", "Delta > Charlie > Bravo > Alpha", "Bravo > Alpha > Charlie > Delta"),
            ("", "people", "Delta > Charlie > Alpha > Bravo", "Bravo > Alpha > Charlie > Delta"),
            ("fsort=name&forder=asc", "custom", "Bravo > Alpha > Charlie > Delta", "Alpha > Bravo > Charlie > Delta")]]
MARKED=[
    # ticket 31: the chat list header's More (ofMirrorChats) on every page with the list, the chat header's More
    # (ofMirrorChatTools) on the chat page and its State pages, and each message's More (ofMirrorMessageMenu) on those
    # State pages (the generator's nine template bubbles: dead.py opens no chat).
    (lambda p: p=="messages/index" or p.startswith("messages/state-") or p=="messages/chat" or p.startswith("messages/chat/"),
     "[at-attr='sort_dropdown'] > button", False, 1),
    (lambda p: p=="messages/chat" or p.startswith("messages/chat/state-"),
     ".b-chat__header .b-dropdown-wrapper > button.m-btn-vertical-dots:not(.m-size-sm)", False, 1),
    (lambda p: p.startswith("messages/chat/state-"), ".b-chat__message button.m-size-sm.m-btn-vertical-dots", False, 9),
]
