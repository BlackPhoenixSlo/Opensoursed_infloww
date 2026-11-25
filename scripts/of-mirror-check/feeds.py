import json, os, re, struct, sys, zlib
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/of-manager"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
ACCOUNTS={"accounts":[{"id":"1","nickname":"Model One","has_session":True},{"id":"2","nickname":"Model Two","has_session":True}],"active_account_id":None}
NOT_YET="Not available in Inflowwww yet"
def png_1x1():
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\xaf\xf0")) + chunk(b"IEND", b"")
PIXEL=png_1x1()
def pic(name): return [{"id":1,"type":"photo","files":{"preview":{"url":f"https://cdn.example.invalid/{name}.jpg"}}}]
ME={"1":{"id":1,"username":"livemodel","name":"Live Model","newTagsCount":2},"2":{"id":2,"username":"livemodel2","name":"Live Model Two"}}
POSTS={
    "1":[{"id":11,"text":"<p>Alpha One wall post</p>","postedAt":"2026-10-10T10:05:00","isPinned":True,"likesCount":7,"commentsCount":2,"media":pic("p11")},
         {"id":12,"text":"Alpha Two wall post","postedAt":"2026-10-09T21:30:00","likesCount":3,"commentsCount":0,"media":pic("p12")},
         {"id":13,"text":"Alpha Three wall post","postedAt":"2026-10-08T08:00:00","media":[]}],
    "2":[{"id":21,"text":"Beta One wall post","postedAt":"2026-10-07T12:00:00","media":pic("p21")},
         {"id":22,"text":"Beta Two wall post","postedAt":"2026-10-06T12:00:00","media":[]}],
}
WANT={"1":[["Alpha One wall post","Oct 10"],["Alpha Two wall post","Oct 9"],["Alpha Three wall post","Oct 8"]],
      "2":[["Beta One wall post","Oct 7"],["Beta Two wall post","Oct 6"]]}
PHOTOS={"1":[{"id":31,"postedAt":"2026-10-10T10:05:00","mediaCount":2,"media":pic("m31")},
             {"id":34,"postedAt":"2026-10-07T10:00:00","mediaCount":1,"media":pic("m34")},
             {"id":36,"postedAt":"2026-10-05T10:00:00","mediaCount":0,"media":pic("m36")}]}
VIDEOS={"1":[{"id":35,"postedAt":"2026-10-08T10:00:00","mediaCount":1,"media":[{"id":2,"type":"video","files":{"full":{"url":"https://cdn.example.invalid/v35.mp4"}}}]},
             {"id":33,"postedAt":"2026-10-09T10:00:00","media":pic("m33")*3},
             {"id":31,"postedAt":"2026-10-10T10:05:00","mediaCount":2,"media":pic("m31")}]}
def author(i, name, handle, avatar=True): return {"id":i,"name":name,"username":handle,**({"avatar":f"https://cdn.example.invalid/a{i}.jpg"} if avatar else {})}
BOOKMARKS={"1":[{"id":41,"text":"Alpha One bookmarked","postedAt":"2026-10-10T10:05:00","likesCount":4,"commentsCount":1,"media":pic("b41"),"author":author(61,"Alpha One","alphaone")},
                {"id":42,"text":"Alpha Two bookmarked","postedAt":"2026-10-09T21:30:00","media":[],"author":author(62,"Alpha Two","alphatwo")},
                {"id":43,"text":"Alpha Three bookmarked","postedAt":"2026-10-08T08:00:00","media":pic("b43"),"author":author(63,"Alpha Three","alphathree",False)}]}
WANT_BOOKMARKS=[["Alpha One","@alphaone","Alpha One bookmarked","Oct 10"],["Alpha Two","@alphatwo","Alpha Two bookmarked","Oct 9"],
                ["Alpha Three","@alphathree","Alpha Three bookmarked","Oct 8"]]
BROW=".l-main-content.m-r-side .g-page-content__body [data-oi-data]"
BROWS=f"""[...document.querySelectorAll('{BROW}')].filter(e => e.checkVisibility())
  .map(e => [e.querySelector('.b-username .g-user-name')?.textContent.trim() ?? '', e.querySelector('.g-user-username')?.textContent.trim() ?? '',
             e.querySelector('.b-post__text')?.textContent.trim() ?? '', e.querySelector('.b-post__date > span')?.textContent.trim() ?? ''])"""
BPICS=f"""[...document.querySelectorAll('{BROW}')].filter(e => e.checkVisibility())
  .map(e => [[...e.querySelectorAll('.b-post__avatar img, .post_media img.b-post__media__img')].map(i => {{ const s = i.getAttribute('src');
      const q = s?.startsWith('/img?') ? new URLSearchParams(s.slice(5)) : null; return [q ? q.get('u') : s, q?.get('account_id') ?? null, i.complete && i.naturalWidth > 0]; }}),
    [...e.querySelectorAll('.b-post__avatar a, a.b-username')].map(a => [a.getAttribute('href'), a.getAttribute('target')])])"""
def bpic(name): return [f"https://cdn.example.invalid/{name}.jpg", "1", True]
def profile(handle): return [[f"https://onlyfans.com/{handle}", "_blank"]]*2
WANT_BPICS=[[[bpic("a61"), bpic("b41")], profile("alphaone")], [[bpic("a62")], profile("alphatwo")], [[bpic("b43")], profile("alphathree")]]
BLEFTOVER=f"""[...document.querySelectorAll('{BROW} *')].filter(e => !e.children.length && e.checkVisibility())
  .map(e => e.textContent.trim()).filter(t => /Fan \\d|@fan\\d|Lorem|Your Model|@yourmodel/.test(t))"""
EMPTY_SHOWN="[...document.querySelectorAll('.l-main-content.m-r-side .g-page-content__body > .empty-message')].filter(e => e.checkVisibility()).map(e => e.textContent.trim())"
CREATE="button[aria-label='Create new list']"
TZ="Europe/Ljubljana"
QUEUE={
    "/api/of/v2/schedules":[{"type":"chat","publishDateTime":"2026-10-14T18:30:00","entity":{"scheduledAt":"2026-10-14T18:30:00","text":"<p>Alpha One message</p>"}},
                            {"type":"post","publishDateTime":"2026-10-12T09:05:00","entity":{"text":"Alpha Two post"}},
                            {"type":"post","publishDateTime":"2026-10-14T08:00:00","entity":{"text":"","mediaCount":2}},
                            {"type":"stream","publishDateTime":"2026-10-20T19:00:00","entity":{"description":"Alpha live stream"}},
                            {"type":"chat","publishDateTime":"2026-11-02T10:00:00","entity":{"scheduledAt":"2026-11-02T10:00:00","text":"Alpha November message"}},
                            {"type":"chat","publishDateTime":"2026-10-03T12:00:00","entity":{"scheduledAt":"2026-10-03T12:00:00","text":"","mediaCount":1}}],
    "/api/of/v2/schedules/later/post":[{"id":5,"text":"Alpha saved post"},{"id":6,"text":"","mediaCount":1}],
    "/api/of/v2/schedules/later/chat":[{"id":7,"text":"<p>Alpha saved message</p>"},{"id":8,"text":"Alpha saved message two"}],
}
NOW=datetime(2026,10,12,12,0,tzinfo=ZoneInfo(TZ))
WANT_SCHEDULES=[["Oct 3",[["chat-indicator","12:00 pm","Media"]]],
                ["Oct 12",[["post-indicator","9:05 am","Alpha Two post"]]],
                ["Oct 14",[["post-indicator","8:00 am","Media"],["chat-indicator","6:30 pm","Alpha One message"]]],
                ["Oct 20",[["stream-indicator","7:00 pm","Alpha live stream"]]]]
WANT_CHATS=[["Oct 3",[["chat-indicator","12:00 pm","Media"]]],["Oct 14",[["chat-indicator","6:30 pm","Alpha One message"]]]]
BARS_CHATS=[["2026-10-03","chat","1"],["2026-10-14","chat","1"]]
BARS_ALL=[["2026-10-03","chat","1"],["2026-10-12","post","1"],["2026-10-14","post","1"],["2026-10-14","chat","1"],["2026-10-20","stream","1"]]
QUEUE_PAGES=[("queue","queue/index","/api/of/v2/schedules",BARS_ALL,True),
             ("queue/state-list-view","queue/state-list-view","/api/of/v2/schedules",WANT_SCHEDULES,False),
             ("queue/state-tab-messages","queue/state-tab-messages","/api/of/v2/schedules",BARS_CHATS,True),
             ("queue/state-tab-streams","queue/state-tab-streams","/api/of/v2/schedules",BARS_CHATS+[["2026-10-20","stream","1"]],True),
             ("queue/saved-for-later-posts","queue/saved-for-later-posts","/api/of/v2/schedules/later/post",
              [["sfl-post","Alpha saved post"],["sfl-post","Media"]],False),
             ("queue/saved-for-later-messages","queue/saved-for-later-messages","/api/of/v2/schedules/later/chat",
              [["sfl-message","Alpha saved message"],["sfl-message","Alpha saved message two"]],False)]
SIDE_OCT12={"queue/index":[["post-indicator","9:05 am","Alpha Two post"]],"queue/state-tab-messages":[],"queue/state-tab-streams":[]}
PAINT={"post-indicator":"rgb(0, 175, 240)","stream-indicator":"rgb(236, 64, 122)","chat-indicator":"rgb(253, 160, 0)","sfl-post-indicator":"rgba(0, 175, 240, 0.5)","sfl-chat-indicator":"rgba(253, 160, 0, 0.5)"}
AGENDA="""[...document.querySelectorAll('.b-agenda__section')].filter(e => e.checkVisibility())
  .map(s => [s.querySelector('.b-agenda__section-date').textContent, [...s.querySelectorAll('a.b-agenda__area-events__item')]
    .map(a => [[...a.classList].filter(c => c.endsWith('-indicator')).join(' '), a.querySelector('.b-agenda__area-events__item-details').textContent,
               a.querySelector('.b-agenda__area-events__item-inward').textContent])])"""
PAINTED="""[...document.querySelectorAll('a.b-agenda__area-events__item')].filter(e => e.checkVisibility() && !e.closest('.l-wrapper__sidebar'))
  .map(a => [[...a.classList].filter(c => c.endsWith('-indicator')).join(' '), getComputedStyle(a, '::before').backgroundColor])"""
CARDS="""[...document.querySelectorAll('.saved-for-later > .b-post.m-queue-post')].filter(e => e.checkVisibility())
  .map(c => [['sfl-post','sfl-message'].find(k => c.classList.contains(k)), c.querySelector('.b-post__text').textContent])"""
CARD_STYLED="[...document.querySelectorAll('.saved-for-later > .b-post.m-queue-post .b-post__queue-row')].slice(0, 1).map(r => getComputedStyle(r).display)"
QEMPTY="[...document.querySelectorAll('.b-agenda > .empty-message, .saved-for-later > .empty-message')].filter(e => e.checkVisibility()).map(e => e.textContent.trim())"
SIDE="""[...document.querySelectorAll('.l-wrapper__sidebar a.b-agenda__area-events__item')].filter(e => e.checkVisibility())
  .map(a => [[...a.classList].filter(c => c.endsWith('-indicator')).join(' '), a.querySelector('.b-agenda__area-events__item-details').textContent,
             a.querySelector('.b-agenda__area-events__item-inward').textContent])"""
UNDER_CALENDAR="document.querySelector('.v-calendar')?.nextElementSibling?.outerHTML ?? null"
BARS="""[...document.querySelectorAll('.v-calendar-monthly .v-event[data-oi-data]')].filter(e => e.checkVisibility())
  .map(b => [b.dataset.date, ['post','chat','stream'].find(c => b.classList.contains(c)), b.textContent])"""
BAR_PAINT_JS="""[...document.querySelectorAll('.v-calendar-monthly .v-event[data-oi-data]')].map(b => getComputedStyle(b).backgroundColor)"""
BAR_PAINT={"post":"rgb(0, 175, 240)","chat":"rgb(253, 160, 0)","stream":"rgb(236, 64, 122)"}
QLEFTOVER="""[...document.querySelectorAll('.b-agenda *')].filter(e => !e.children.length && e.checkVisibility())
  .map(e => e.textContent.trim()).filter(t => /Fan \\d|@fan\\d|Lorem/.test(t))"""
def nfan(i, name, handle, avatar=True): return {"id":i,"name":name,"username":handle,**({"avatar":f"https://cdn.example.invalid/n{i}.jpg"} if avatar else {})}
NOTIFS={"1":[{"id":1,"type":"subscribed","isRead":False,"createdAt":"2026-10-10T10:05:00","text":"subscribed to your profile","user":nfan(71,"Alpha One","alphaone")},
             {"id":2,"type":"tip","isRead":True,"createdAt":"2026-10-09T21:30:00","text":"<p>tipped you <b>{AMOUNT}</b></p>","replacePairs":{"{AMOUNT}":"$5.00"},"fromUser":nfan(72,"Alpha Two","alphatwo")},
             {"id":3,"type":"commented","isRead":False,"createdAt":"2026-10-08T08:00:00","text":"commented: <p>nice post</p>","user":nfan(73,"Alpha Three","alphathree",False)},
             {"id":4,"type":"mentioned","createdAt":"2026-10-07T12:00:00","text":"mentioned you in a comment","user":nfan(74,"Alpha Four","alphafour")}],
        "2":[{"id":5,"type":"subscribed","isRead":False,"createdAt":"2026-10-06T09:00:00","text":"subscribed to your profile","user":nfan(81,"Beta One","betaone")},
             {"id":6,"type":"mentioned","isRead":True,"createdAt":"2026-10-05T09:00:00","text":"mentioned you","user":nfan(82,"Beta Two","betatwo")}]}
WANT_N={1:["Alpha One","@alphaone","subscribed to your profile","Oct 10",True,"icon-follow"],
        2:["Alpha Two","@alphatwo","tipped you $5.00","Oct 9",False,"icon-price"],
        3:["Alpha Three","@alphathree","commented: nice post","Oct 8",True,None],
        4:["Alpha Four","@alphafour","mentioned you in a comment","Oct 7",False,None]}
def npic(i): return [[f"https://cdn.example.invalid/n{i}.jpg","1",True]]
NOTIF_TABS=[("notifications","notifications/index",None,[WANT_N[i] for i in (1,2,3,4)],[npic(71),npic(72),[],npic(74)]),
            ("notifications/subscribed","notifications/subscribed","subscribed",[WANT_N[1]],[npic(71)]),
            ("notifications/commented","notifications/commented","commented",[WANT_N[3]],[[]]),
            ("notifications/mentioned","notifications/mentioned","mentioned",[WANT_N[4]],[npic(74)]),
            ("notifications/tip","notifications/tip","tip",[WANT_N[2]],[npic(72)])]
NCOUNT_ROUTE="/api/of/v2/users/notifications/count"
COLUMN_READS={NCOUNT_ROUTE, "/api/of/v2/users/me"}
def accts(cs): return sorted({c[3] for c in cs if c[1] not in COLUMN_READS}, key=str)
NCOUNTS={"1":{"all":120,"subscribed":3,"tip":1,"purchases":0}}
NTABS="""Object.fromEntries([...document.querySelectorAll("a.b-tabs__nav__link[href^='/of-manager/notifications']")].filter(e => e.checkVisibility())
  .map(a => [a.getAttribute('href'), [...a.querySelectorAll('.b-tabs__nav__count')].filter(c => c.checkVisibility()).map(c => c.textContent.trim())]))"""
WANT_NTABS={f"/of-manager/notifications{t}":c for t, c in [("",["99+"]),("/subscribed",["3"]),("/purchases",[]),("/tip",["1"]),("/tags",["2"]),
            ("/commented",[]),("/mentioned",[]),("/favorited",[]),("/message",[]),("/deactivated_media",[])]}
STREAMS_ROUTE="/api/of/v2/users/1/streams"
STREAMS=[{"id":1,"media":{"files":{"thumb":{"url":"https://cdn.example.invalid/s1.jpg"}}},"viewsCount":7,"startedAt":"2026-10-09T21:30:00"},
         {"id":2,"media":None,"viewsCount":1,"startedAt":"2026-10-08T10:00:00"}]
STHUMBS="""[...document.querySelectorAll('.b-s-dashboard__thumb-holder')].filter(e => e.checkVisibility()).map(t => {
  const i = t.querySelector('img'), s = i?.getAttribute('src'), q = s?.startsWith('/img?') ? new URLSearchParams(s.slice(5)) : null;
  return [[q ? q.get('u') : s, q?.get('account_id') ?? null, !!i && i.complete && i.naturalWidth > 0],
          t.querySelector('.b-s-dashboard__thumb-content__viewers')?.textContent.trim(), t.querySelector('.b-s-dashboard__thumb-content__time')?.textContent.trim()]; })"""
WANT_STHUMBS=[[["https://cdn.example.invalid/s1.jpg","1",True],"Viewers: 7","Oct 9"]]
WANT_N2=[["Beta One","@betaone","subscribed to your profile","Oct 6",True,"icon-follow"],["Beta Two","@betatwo","mentioned you","Oct 5",False,None]]
NROW=".b-notifications__list .vue-recycle-scroller__item-view"
NROWS=f"""[...document.querySelectorAll('{NROW}')].filter(e => e.checkVisibility())
  .map(e => [e.querySelector('.b-username .g-user-name')?.textContent.trim() ?? '', e.querySelector('.g-user-username')?.textContent.trim() ?? '',
             e.querySelector('.b-notifications__list__item__text')?.textContent.trim() ?? '', e.querySelector('.g-date > span')?.textContent.trim() ?? '',
             e.querySelector('.b-notifications__list__item')?.classList.contains('m-unread') ?? null,
             e.querySelector('.b-notifications__avatar__icon svg')?.getAttribute('data-icon-name') ?? null])"""
NPICS=f"""[...document.querySelectorAll('{NROW}')].filter(e => e.checkVisibility())
  .map(e => [...e.querySelectorAll('.g-avatar img')].map(i => {{ const s = i.getAttribute('src');
      const q = s?.startsWith('/img?') ? new URLSearchParams(s.slice(5)) : null; return [q ? q.get('u') : s, q?.get('account_id') ?? null, i.complete && i.naturalWidth > 0]; }}))"""
NLEFTOVER=f"""[...document.querySelectorAll('.b-notifications__list *')].filter(e => !e.children.length && e.checkVisibility())
  .map(e => e.textContent.trim()).filter(t => /Fan \\d|@fan\\d|Lorem/.test(t))"""
NNAMES=f"[...document.querySelectorAll('{NROW}')].filter(e => e.checkVisibility()).map(e => e.querySelector('.g-user-name')?.textContent.trim())"
NOTIF_ROUTE="/api/of/v2/users/notifications"
NEMPTY="""[[...document.querySelectorAll('.b-notifications__list .empty-message')].filter(e => e.checkVisibility()).map(e => e.textContent.trim()),
  !!document.querySelector('.b-notifications.m-empty-page')]"""
EMPTY_TAB=[["No notifications currently!"],True]
NOTIF_EMPTY_TABS=[(f"notifications/{t}",f"notifications/{t}",NOTIF_ROUTE,{"limit":["20"],"type":[t]}) for t in ("purchases","favorited","message","deactivated_media")]+[
                  ("notifications/tags","notifications/tags","/api/of/v2/release-forms/mentions",{"limit":["20"]})]
TXN_ROUTE="/api/of/v2/payouts/transactions"
def txn(i, day, amount, desc, status="done", deleted=False, **more):
    return {"id":f"t{i}","createdAt":day,"amount":amount,"fee":round(amount*0.2,2),"net":round(amount*0.8,2),"currency":"USD",
            "description":desc,"status":status,"user":{"id":90+i,"isDeleted":deleted,"isActive":True},**more}
TXNS={"1":[txn(1,"2026-10-10T10:05:00",5,'Subscription from <a href="https://onlyfans.com/alphaone">Alpha One</a>'),
           txn(2,"2026-10-09T21:30:00",12.5,"Tip from <span>Alpha Two</span>","loading",payoutPendingDays=5),
           txn(3,"2026-10-08T08:00:00",1234.5,"Payment for message from <span>Alpha Three</span>",deleted=True),
           *[txn(i,f"2026-09-{30-i:02d}T12:00:00",3,f"Tip from <span>Alpha {i}</span>") for i in range(4,13)]]}
TXN_PAGE=10
COMPLETE=[["Complete","icon-done"]]
WANT_TXNS=[["Oct 10, 2026","10:05 am","$5.00","$1.00","$4.00","Subscription from Alpha One",COMPLETE],
           ["Oct 9, 2026","9:30 pm","$12.50","$2.50","$10.00","Tip from Alpha Two",[["Earning will become available in 5 days","icon-loading"]]],
           ["Oct 8, 2026","8:00 am","$1,234.50","$246.90","$987.60","Payment for message from Alpha Three",COMPLETE],
           *[[f"Sep {30-i}, 2026","12:00 pm","$3.00","$0.60","$2.40",f"Tip from Alpha {i}",COMPLETE] for i in range(4,13)]]
TGREY="[...document.querySelectorAll('.b-table tbody > tr')].filter(e => e.checkVisibility() && e.querySelector('.b-table__date')).map(e => e.querySelector('.b-field-subscription').classList.contains('m-disabled-username'))"
TROWS="""[...document.querySelectorAll('.b-table tbody > tr')].filter(e => e.checkVisibility() && e.querySelector('.b-table__date'))
  .map(e => [...['.b-table__date__date > span', '.b-table__date__time > span', '.b-table__amount > span', '.b-table__fee > span',
                 '.b-table__net strong > span', '.b-table__desc .b-field-subscription'].map(s => e.querySelector(s)?.textContent.trim() ?? null),
             [...e.querySelectorAll('.b-table__status .b-table__status-tip')].map(t => [t.getAttribute('aria-label'), t.querySelector('svg')?.getAttribute('data-icon-name') ?? null])])"""
TORDER="[...document.querySelectorAll('.b-table tbody > tr')].filter(e => getComputedStyle(e).display !== 'none').map(e => !!e.querySelector('.infinite-loading-container'))"
TLEFTOVER="""[...document.querySelectorAll('.b-table tbody *')].filter(e => !e.children.length && e.checkVisibility())
  .map(e => e.textContent.trim()).filter(t => /Fan \\d|@fan\\d|Lorem/.test(t))"""
PAYOUT_ROUTE="/api/of/v2/payouts/requests"
REFERRAL_ROUTE="/api/of/v2/payouts/requests/referral"
PAYOUTS={PAYOUT_ROUTE:{"1":[{"id":"r1","createdAt":"2026-10-10T10:05:00","invoiceId":"INV-1001","amount":120,"state":"approved"},
                            {"id":"r2","createdAt":"2026-10-09T21:30:00","invoiceId":"INV-1002","amount":45.5,"state":"rejected","rejectReason":"Alpha One's bank details are wrong"},
                            {"id":"r3","createdAt":"2026-10-08T08:00:00","invoiceId":"INV-1003","amount":20,"state":"pending"}]},
         REFERRAL_ROUTE:{"1":[{"id":"f1","createdAt":"2026-10-05T12:00:00","invoiceId":"REF-2001","amount":15,"state":"approved"},
                              {"id":"f2","createdAt":"2026-10-04T09:00:00","invoiceId":"REF-2002","amount":7.25,"state":"rejected"}]}}
PROCESSED=["approved","Payout has been processed","#icon-done"]
RETURNED="Payout request could not be processed and this amount was returned to your Current Balance."
WANT_PAYOUTS={"statements/payouts":[["Oct 10, 2026","10:05 am","INV-1001","$120.00",*PROCESSED],
                                    ["Oct 9, 2026","9:30 pm","INV-1002","$45.50","rejected",f"{RETURNED}\nReason: Alpha One's bank details are wrong","#icon-alert"],
                                    ["Oct 8, 2026","8:00 am","INV-1003","$20.00","pending","","#icon-loading"]],
              "statements/referrals":[["Oct 5, 2026","12:00 pm","REF-2001","$15.00",*PROCESSED],
                                      ["Oct 4, 2026","9:00 am","REF-2002","$7.25","rejected",RETURNED,"#icon-alert"]]}
PROWS="""[...document.querySelectorAll('.b-table tbody > tr')].filter(e => e.checkVisibility() && e.querySelector('.b-table__date'))
  .map(e => { const s = e.querySelector('.b-table__desc > span');
    return [...['.b-table__date__date > span', '.b-table__date__time > span', '.b-table__invoice', '.b-table__amount strong > span']
              .map(q => e.querySelector(q)?.textContent.trim() ?? null),
            s?.className ?? null, s?.innerText.trim() ?? '', s?.querySelector('use')?.getAttribute('href') ?? null]; })"""
PEMPTY="[...document.querySelectorAll('.b-table tbody .empty-message')].filter(e => e.checkVisibility()).map(e => e.textContent.trim())"
WITHDRAW="[...document.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Request withdrawal').map(b => b.disabled)"
def tile(name, count): return [f"https://cdn.example.invalid/{name}.jpg", "1", True, count]
WANT_MEDIA=[tile("m31","2"), tile("m33","3"), [None, None, False, "1"], tile("m34","1"), tile("m36", None)]
TILES="""[...document.querySelectorAll('.b-photos.vue-recycle-scroller .b-photos__item')].filter(e => e.checkVisibility())
  .map(e => { const i = e.querySelector('img.b-photos__item__img'); const s = i?.getAttribute('src');
    const q = s?.startsWith('/img?') ? new URLSearchParams(s.slice(5)) : null;
    return [q ? q.get('u') : s ?? null, q?.get('account_id') ?? null, !!i && i.complete && i.naturalWidth > 0,
            e.querySelector('.b-purchase__list-item__count')?.textContent.trim() ?? null]; })"""
GRID=".b-photos.vue-recycle-scroller"
GRID_ROWS="""[...document.querySelectorAll('.b-photos.vue-recycle-scroller .vue-recycle-scroller__item-view')].filter(e => e.checkVisibility())
  .map(r => r.querySelectorAll('.b-photos__item').length)"""
COUNTS="""['.b-photos.vue-recycle-scroller', '.b-photos.m-recent-list']
  .map(g => [...document.querySelectorAll(`${g} .b-photos__item`)].filter(e => e.checkVisibility()).length)"""
ROWS="""[...document.querySelectorAll('.user_posts .b-post')].filter(e => e.checkVisibility())
  .map(e => [e.querySelector('.b-post__text')?.textContent.trim() ?? '', e.querySelector('.b-post__date > span')?.textContent.trim() ?? ''])"""
LEFTOVER="""[...document.querySelectorAll('.user_posts *')].filter(e => !e.children.length && e.checkVisibility())
  .map(e => e.textContent.trim()).filter(t => /Fan \\d|@fan\\d|Lorem/.test(t))"""
IMAGES="""n => [...document.querySelectorAll('.user_posts .post_media img.b-post__media__img')].filter(e => e.checkVisibility())
  .map(e => { const s = e.getAttribute('src'); return [s.startsWith('/img?') && new URLSearchParams(s.slice(5)).get('account_id') === n, e.complete && e.naturalWidth > 0]; })"""
NOTE="document.getElementById('oi-note')?.textContent ?? null"
WALL_EMPTY="[...document.querySelectorAll('.user_posts [data-oi-empty]')].filter(e => e.checkVisibility()).map(e => e.textContent.trim())"
MORE=".user_posts .b-post__tools__more button[aria-label='More']"
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def session(b, scope_js, tz=None, clock=None):
    """A fresh context and page with scope_js run before every load; returns (page, relay calls as [method, path, query
    dict, X-Account-Id], console errors, mirror pages fetched by script as [method, path])."""
    ctx=b.new_context(viewport={"width":1440,"height":900}, **({"timezone_id":tz} if tz else {}))
    ctx.add_init_script(scope_js)
    if clock: ctx.clock.set_fixed_time(clock)
    foreign=lambda url: urlparse(url).hostname not in ("localhost","127.0.0.1")
    def outside(route):
        failures.append(f"request to a non-localhost host: {route.request.url[:120]}")
        route.abort()
    ctx.route(foreign, outside)
    pg=ctx.new_page()
    calls=[]
    def mock(route):
        req=route.request; u=req.url; url=urlparse(u); path=url.path
        if foreign(u): return outside(route)
        if path=="/img": return route.fulfill(status=200, content_type="image/png", body=PIXEL)
        acct=req.headers.get("x-account-id")
        if path.startswith("/api/"): calls.append([req.method, path, parse_qs(url.query), acct])
        if path=="/api/of/v2/users/me" and acct in ME: return route.fulfill(status=200, content_type="application/json", body=json.dumps(ME[acct]))
        if path in QUEUE and acct=="1": return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":QUEUE[path],"hasMore":False}))
        if path==NCOUNT_ROUTE and acct in NCOUNTS: return route.fulfill(status=200, content_type="application/json", body=json.dumps(NCOUNTS[acct]))
        if path==STREAMS_ROUTE and acct=="1": return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":STREAMS,"hasMore":False}))
        if path==NOTIF_ROUTE and acct in NOTIFS:
            t=parse_qs(url.query).get("type",[None])[0]
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":[n for n in NOTIFS[acct] if t in (None, n["type"])],"hasMore":False}))
        if path in PAYOUTS and acct in PAYOUTS[path]: return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":PAYOUTS[path][acct],"hasMore":False}))
        if path==TXN_ROUTE and acct in TXNS:
            q=parse_qs(url.query); limit=int(q.get("limit",["10"])[0]); offset=int(q.get("offset",["0"])[0])
            page=TXNS[acct][offset:offset+limit]
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":page,"hasMore":offset+limit<len(TXNS[acct]),"nextMarker":None}))
        if path=="/api/of/v2/posts/bookmarks/all" and acct in BOOKMARKS: return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":BOOKMARKS[acct],"hasMore":False}))
        m=re.fullmatch(r"/api/of/v2/users/(\d+)/posts(/photos|/videos)?", path)
        rows={None:POSTS,"/photos":PHOTOS,"/videos":VIDEOS}[m.group(2)].get(acct) if m and acct==m.group(1) else None
        if rows is not None: return route.fulfill(status=200, content_type="application/json", body=json.dumps({"list":rows,"hasMore":False}))
        if "/auth/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps(user))
        elif "/chatter/me/accounts" in u: route.fulfill(status=200, content_type="application/json", body="[]")
        elif path=="/admin/accounts": route.fulfill(status=200, content_type="application/json", body=json.dumps(ACCOUNTS))
        elif "/admin/employees" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}))
        elif "/chatter/me" in u: route.fulfill(status=200, content_type="application/json", body=json.dumps({"chatter":None,"owners":[]}))
        else: route.fulfill(status=200, content_type="application/json", body="[]")
    for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**","**/img?**"]: pg.route(pat, mock)
    pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))
    errs=[]; pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.on("pageerror", lambda e: errs.append(f"uncaught: {e}"))
    fetched=[]
    pg.on("request", lambda r: fetched.append([r.method, urlparse(r.url).path]) if r.resource_type in ("fetch","xhr") and urlparse(r.url).path.startswith("/of-mirror/") else None)
    return pg, calls, errs, fetched
def frame(pg, page):
    for _ in range(60):
        fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{page}.html")]
        if fr and fr[0].evaluate("document.readyState")=="complete": return fr[0]
        pg.wait_for_timeout(250)
    failures.append(f"{page}: NO IFRAME (url {pg.url})"); return None
def settle(pg, fr, want, js=ROWS):
    for _ in range(60):
        got=fr.evaluate(js)
        if got==want: break
        pg.wait_for_timeout(250)
    return got
def open_page(pg, path):
    pg.goto(f"{BASE}{M}/{path}", wait_until="load", timeout=90000); pg.wait_for_timeout(1500)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(1500)
def images(pg, fr, n):
    fr.evaluate("document.querySelectorAll('.user_posts .post_media img').forEach(i => i.loading = 'eager')")
    for _ in range(20):
        got=fr.evaluate(IMAGES, n)
        if got and all(ok for _, ok in got): break
        pg.wait_for_timeout(250)
    return got
def scope_to(pg, current, label):
    pg.locator("aside[aria-label='Creators']").get_by_role("button", name=label).first.click()
    pg.wait_for_timeout(500)

with sync_playwright() as p:
    b=p.chromium.launch()

    pg, calls, errs, fetched=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    for path, page in [("profile","profile/index"),("profile/state-more-menu","profile/state-more-menu")]:
        open_page(pg, path)
        fr=frame(pg, page)
        if not fr: continue
        check(f"{page}: account 1's posts in order", settle(pg, fr, WANT["1"]), WANT["1"])
        check(f"{page}: no example text in the post list", fr.evaluate(LEFTOVER), [])
        check(f"{page}: row pictures through /img with account_id=1, loaded", images(pg, fr, "1"), [[True, True]]*2)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}.png")
        more=fr.locator(MORE).filter(visible=True).first
        more.scroll_into_view_if_needed()
        if page=="profile/index": more.click()
        else: more.dispatch_event("click")
        pg.wait_for_timeout(300)
        check(f"{page}: a post's More click opens the own-post menu", fr.evaluate("[...document.querySelectorAll('[data-oi-post-menu] [data-oi-action]')].map(e => e.dataset.oiAction)"), ["pin","edit","archive","delete"])
        check(f"{page}: a post's More click shows no note", fr.evaluate(NOTE), None)
        check(f"{page}: the More button is not marked wired", more.get_attribute("data-oi-wired"), None)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}-more.png")
    open_page(pg, "profile/media")
    fr=frame(pg, "profile/media")
    if fr:
        check("profile/media: account 1's media posts merged, newest first, pictures proxied and loaded", settle(pg, fr, WANT_MEDIA, TILES), WANT_MEDIA)
        check("profile/media: three tiles to a row", fr.evaluate(GRID_ROWS), [3, 2])
        check("profile/media: [grid, recent strip] tiles shown", fr.evaluate(COUNTS), [5, 3])
        fr.locator(GRID).evaluate("e => e.scrollIntoView({block: 'start'})")
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-profile-media.png")
    open_page(pg, "collections/bookmarks/all")
    fr=frame(pg, "collections/bookmarks/all")
    if fr:
        check("bookmarks: account 1's bookmarked posts in order, each with its own author", settle(pg, fr, WANT_BOOKMARKS, BROWS), WANT_BOOKMARKS)
        check("bookmarks: \"No bookmarks yet\" hidden while rows show", fr.evaluate(EMPTY_SHOWN), [])
        check("bookmarks: no example text in the rows", fr.evaluate(BLEFTOVER), [])
        fr.evaluate(f"document.querySelectorAll('{BROW} img').forEach(i => i.loading = 'eager')")
        check("bookmarks: pictures through /img with account_id=1, loaded; the avatar-less author none; author links their OF profile", settle(pg, fr, WANT_BPICS, BPICS), WANT_BPICS)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-bookmarks.png")
        mores=fr.locator(f"{BROW} .b-post__tools__more button[aria-label='More']")
        check("bookmarks: another creator's More is disabled with the tooltip", mores.evaluate_all("bs => bs.map(b => [b.disabled, b.title])"), [[True, NOT_YET]]*len(WANT_BOOKMARKS))
        mores.first.click(force=True); pg.wait_for_timeout(300)
        check("bookmarks: a bookmark's More click shows no note", fr.evaluate(NOTE), None)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-bookmarks-more.png")
    check("model 1: the post row is borrowed by one same-origin GET of My profile's capture", fetched, [["GET", "/of-mirror/pages/profile/index.html"]])
    marks=[c for c in calls if c[1]=="/api/of/v2/posts/bookmarks/all"]
    check("model 1: one bookmarks request, with limit=20", [c[2] for c in marks], [{"limit":["20"]}])
    open_page(pg, "collections")
    fr=frame(pg, "collections/index")
    if fr:
        create=fr.locator(CREATE).first
        create.click(); pg.wait_for_timeout(300)
        check("collections: \"Create new list\" opens its dialog", fr.evaluate("document.querySelector('[data-oi-dialog] .modal-title')?.textContent.trim() ?? null"), "Create new list")
        check("collections: \"Create new list\" shows no note", fr.evaluate(NOTE), None)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-collections-create.png")
    open_page(pg, "statements/earnings")
    fr=frame(pg, "statements/earnings")
    if fr:
        check("statements/earnings: account 1's first page", settle(pg, fr, WANT_TXNS[:TXN_PAGE], TROWS)[:TXN_PAGE], WANT_TXNS[:TXN_PAGE])
        fr.locator(".b-table .infinite-loading-container").first.evaluate("e => e.scrollIntoView({block: 'end'})")
        check("statements/earnings: its loading row in view, both pages, in order, as mapped", settle(pg, fr, WANT_TXNS, TROWS), WANT_TXNS)
        check("statements/earnings: the deleted fan's description is greyed", fr.evaluate(TGREY), [i==2 for i in range(len(WANT_TXNS))])
        check("statements/earnings: the rows sit before the loading row", fr.evaluate(TORDER), [False]*len(WANT_TXNS)+[True])
        check("statements/earnings: no example text in the table", fr.evaluate(TLEFTOVER), [])
        fr.locator(".b-table").first.evaluate("e => e.scrollIntoView({block: 'center'})")
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-statements-earnings.png")
    check("model 1: OF's pages of 10, offset 0 then 10", [c[2] for c in calls if c[1]==TXN_ROUTE], [{"limit":["10"],"offset":["0"]},{"limit":["10"],"offset":["10"]}])
    for page, route, order, borrowed in [("statements/payouts",PAYOUT_ROUTE,[False,False,False,True],[]),
                                         ("statements/referrals",REFERRAL_ROUTE,[False,False],[["GET","/of-mirror/pages/statements/payouts.html"]])]:
        before, pages_before=len(calls), len(fetched)
        open_page(pg, page)
        fr=frame(pg, page)
        if not fr: continue
        want=WANT_PAYOUTS[page]
        check(f"{page}: account 1's payout requests in order, as mapped", settle(pg, fr, want, PROWS), want)
        check(f"{page}: the rows in table order (true: the loading row)", fr.evaluate(TORDER), order)
        check(f"{page}: no empty-list message while rows show", fr.evaluate(PEMPTY), [])
        check(f"{page}: \"Request withdrawal\" stays disabled", fr.evaluate(WITHDRAW), [True])
        check(f"{page}: no example text in the table", fr.evaluate(TLEFTOVER), [])
        check(f"{page}: one request of its route, by account 1, exactly limit=20", [[c[1], c[2], c[3]] for c in calls[before:] if c[1] in PAYOUTS], [[route, {"limit":["20"]}, "1"]])
        check(f"{page}: the row borrowed by one same-origin GET of the payouts capture (none on Payouts)", fetched[pages_before:], borrowed)
        fr.locator(".b-table").first.evaluate("e => e.scrollIntoView({block: 'center'})")
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}.png")
    media=[c for c in calls if re.search(r"/posts/(photos|videos)$", c[1])]
    check("model 1: both media lists requested by account 1's OnlyFans id", sorted({c[1] for c in media}), ["/api/of/v2/users/1/posts/photos", "/api/of/v2/users/1/posts/videos"])
    check("model 1: every media list request carries limit=24", sorted({tuple(c[2].get("limit", [])) for c in media}), [("24",)])
    posts=[c for c in calls if c[1].endswith("/posts")]
    check("model 1: the posts request asks for account 1's OnlyFans id", sorted({c[1] for c in posts}), ["/api/of/v2/users/1/posts"])
    check("model 1: every posts request carries limit=20", sorted({tuple(c[2].get("limit", [])) for c in posts}), [("20",)])
    check("model 1: every relay call but the creator column's carries X-Account-Id: 1", accts(calls), ["1"])
    check("model 1: nothing but GETs sent", sorted({c[0] for c in calls}), ["GET"])
    print("model 1 console errors:", [e[:160] for e in errs][:8])
    check("model 1: no console errors", errs, [])

    pg, calls, errs, fetched=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    open_page(pg, "profile")
    fr=frame(pg, "profile/index")
    if fr:
        check("switch: account 1's posts first", settle(pg, fr, WANT["1"]), WANT["1"])
        before=len(calls)
        scope_to(pg, "Model One", "Model Two")
        fr=frame(pg, "profile/index")
        check("switch: only account 2's posts after the switch", settle(pg, fr, WANT["2"]), WANT["2"])
        check("switch: account 2's row pictures through /img with account_id=2, loaded", images(pg, fr, "2"), [[True, True]])
        check("switch: every relay call after the switch carries X-Account-Id: 2", accts(calls[before:]), ["2"])
        check("switch: account 2's posts asked for by its OnlyFans id", sorted({c[1] for c in calls[before:] if c[1].endswith("/posts")}), ["/api/of/v2/users/2/posts"])
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-switch-2.png")
    print("switch console errors:", [e[:160] for e in errs][:8])
    check("switch: no console errors", errs, [])

    pg, calls, errs, fetched=session(b, "localStorage.setItem('chatterly:scope','model:1')", TZ, NOW)
    for path, page, route, want, calendar in QUEUE_PAGES:
        before, pages_before=len(calls), len(fetched)
        open_page(pg, path)
        fr=frame(pg, page)
        if not fr: continue
        if calendar:
            check(f"{page}: each day's event bar per type, with its count", settle(pg, fr, want, BARS), want)
            check(f"{page}: each bar painted in OF's colour", fr.evaluate(BAR_PAINT_JS), [BAR_PAINT[t] for _, t, _ in want])
            check(f"{page}: nothing under the calendar", fr.evaluate(UNDER_CALENDAR), None)
            check(f"{page}: the right column lists Oct 12's items", fr.evaluate(SIDE), SIDE_OCT12[page])
        elif page.startswith("queue/saved-for-later"):
            check(f"{page}: the synthetic items as OF's cards", settle(pg, fr, want, CARDS), want)
            check(f"{page}: OF's card stylesheet applies", fr.evaluate(CARD_STYLED), ["flex"])
        else:
            check(f"{page}: the synthetic items by day, soonest first", settle(pg, fr, want, AGENDA), want)
            check(f"{page}: each colour mark painted in OF's colour", fr.evaluate(PAINTED), [[c, PAINT[c]] for _, items in want for c, _, _ in items])
        if page=="queue/state-list-view":
            check(f"{page}: the right column lists Oct 12's items", fr.evaluate(SIDE), [i for d, items in want if d=="Oct 12" for i in items])
        check(f"{page}: the captured empty state hidden", fr.evaluate(QEMPTY), [])
        check(f"{page}: no example text in the agenda", fr.evaluate(QLEFTOVER), [])
        mine=[c for c in calls[before:] if c[1] in QUEUE]
        check(f"{page}: only its own queue route, requested by account 1", sorted({(c[1], c[3]) for c in mine}), [(route, "1")])
        want_q={"publish_date":["2026-10-01"],"publish_date_end":["2026-10-31"],"time_zone":[TZ],"limit":["50"]} if route.endswith("/schedules") else {"limit":["50"]}
        check(f"{page}: every queue request's query", [json.loads(q) for q in sorted({json.dumps(c[2], sort_keys=True) for c in mine})], [want_q])
        check(f"{page}: the agenda block borrowed by one same-origin GET (none on the list view)", fetched[pages_before:],
              [] if page=="queue/state-list-view" else [["GET", "/of-mirror/pages/queue/state-list-view.html"]])
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}.png")
    check("queue: every relay call but the creator column's carries X-Account-Id: 1", accts(calls), ["1"])
    check("queue: nothing but GETs sent", sorted({c[0] for c in calls}), ["GET"])
    print("queue console errors:", [e[:160] for e in errs][:8])
    check("queue: no console errors", errs, [])

    pg, calls, errs, fetched=session(b, "localStorage.setItem('chatterly:scope','model:1')")
    for path, page, kind, want, pics in NOTIF_TABS:
        before=len(calls)
        open_page(pg, path)
        fr=frame(pg, page)
        if not fr: continue
        check(f"{page}: account 1's notifications of its type, in order", settle(pg, fr, want, NROWS), want)
        check(f"{page}: no example text in the list", fr.evaluate(NLEFTOVER), [])
        check(f"{page}: no empty-tab message or layout while rows show", fr.evaluate(NEMPTY), [[], False])
        fr.evaluate(f"document.querySelectorAll('{NROW} img').forEach(i => i.loading = 'eager')")
        check(f"{page}: avatars through /img with account_id=1, loaded; the avatar-less fan none", settle(pg, fr, pics, NPICS), pics)
        mine=[c for c in calls[before:] if c[1]==NOTIF_ROUTE]
        check(f"{page}: its notifications requests' query", [json.loads(q) for q in sorted({json.dumps(c[2], sort_keys=True) for c in mine})],
              [{"limit":["20"], **({"type":[kind]} if kind else {})}])
        if page=="notifications/index": check(f"{page}: the tab bar shows account 1's counts", settle(pg, fr, WANT_NTABS, NTABS), WANT_NTABS)
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}.png")
    before=len(calls)
    open_page(pg, "streaming/dashboard")
    fr=frame(pg, "streaming/dashboard")
    if fr:
        fr.evaluate("document.querySelectorAll('.b-s-dashboard__thumb-holder img').forEach(i => i.loading = 'eager')")
        check("streaming/dashboard: account 1's past streams with media", settle(pg, fr, WANT_STHUMBS, STHUMBS), WANT_STHUMBS)
        check("streaming/dashboard: one streams request, limit=8", [c[2] for c in calls[before:] if c[1]==STREAMS_ROUTE], [{"limit":["8"]}])
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-streaming-dashboard.png")
    check("notifications: every relay call but the creator column's carries X-Account-Id: 1", accts(calls), ["1"])
    open_page(pg, "notifications")
    fr=frame(pg, "notifications/index")
    if fr:
        check("notifications switch: account 1's notifications first", settle(pg, fr, NOTIF_TABS[0][3], NROWS), NOTIF_TABS[0][3])
        before=len(calls)
        scope_to(pg, "Model One", "Model Two")
        fr=frame(pg, "notifications/index")
        check("notifications switch: only account 2's notifications after the switch", settle(pg, fr, WANT_N2, NROWS), WANT_N2)
        check("notifications switch: every relay call after the switch carries X-Account-Id: 2", accts(calls[before:]), ["2"])
        check("notifications switch: account 2's notifications requested", [c[2] for c in calls[before:] if c[1]==NOTIF_ROUTE], [{"limit":["20"]}])
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-notifications-switch-2.png")
    for path, page, route, query in NOTIF_EMPTY_TABS:
        before=len(calls)
        open_page(pg, path)
        fr=frame(pg, page)
        if not fr: continue
        check(f"{page}: OF's empty tab", settle(pg, fr, EMPTY_TAB, NEMPTY), EMPTY_TAB)
        check(f"{page}: no row", fr.evaluate(NNAMES), [])
        check(f"{page}: no example text in the list", fr.evaluate(NLEFTOVER), [])
        check(f"{page}: its request's query", [c[2] for c in calls[before:] if c[1]==route][:1], [query])
        check(f"{page}: X-Account-Id: 1", accts(calls[before:]), ["1"])
        pg.screenshot(path=f"{SHOTS}/inapp-feeds-{page.replace('/','-')}.png")
    READ="/api/of/v2/users/notifications/read"
    check("notifications: nothing but GETs and one mark-read per All tab open", [(c[0], c[1], c[3]) for c in calls if c[0]!="GET"],
          [("POST", READ, "1"), ("POST", READ, "1"), ("POST", READ, "2")])
    print("notifications console errors:", [e[:160] for e in errs][:8])
    check("notifications: no console errors", errs, [])

    b.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("feeds ok")
