import json, re, shutil, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
src = REPO / "app/lib/__fixtures__/fansly-mirror/capture"
dst = REPO / ".scratch/fansly-mirror-check/fixture-capture"
shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
TOP = '<div class="top-bar"><button class="btn avatar-menu">Me</button> <button class="btn balance-menu">Balance</button></div>'
LINKS = '<p class="oi-check-links"><a href="/messages">Open messages</a> <a href="/scheduled">Scheduled posts</a></p>'
home = dst / "pages/home.html"
h = home.read_text()
h = h.replace('<div class="middle-side" _ngcontent-ng-c4012345678="">', '<div class="middle-side" _ngcontent-ng-c4012345678="">' + TOP + LINKS, 1)
home.write_text(h)
STATE = '<!DOCTYPE html><html lang="en" class="bright-theme"><head><meta charset="utf-8"><title>Fansly</title></head><body><app-root _nghost-ng-c4012345678=""><div class="side-bar-wrapper left-side" _ngcontent-ng-c4012345678=""><a href="/home" _ngcontent-ng-c4012345678="">Home</a></div><div class="middle-side" _ngcontent-ng-c4012345678="">' + TOP + '<h1>Home</h1></div></app-root><div class="cdk-overlay-container"><div class="cdk-overlay-backdrop"></div><div class="cdk-overlay-pane"><div class="menu"><h2>{title}</h2><button class="btn">Close</button></div></div></div></body></html>'
(dst / "pages/home").mkdir(exist_ok=True)
m = json.loads((dst / "manifest.json").read_text())
plan = json.loads((dst / "mirror_plan.json").read_text())
base = next(e for e in m["entries"] if e["id"] == "home")
for name, title, opener in [("avatar-menu", "Account", "[class*=top] button.avatar-menu"), ("balance-menu", "Wallet", "[class*=top] button.balance-menu")]:
    rel = f"pages/home/state-{name}.html"
    (dst / rel).write_text(STATE.replace("{title}", title))
    e = dict(base, id=f"home/state-{name}", kind="state", state=name, file=rel, meta=rel.replace(".html", ".meta.json"), png=rel.replace(".html", ".png"), opener=opener)
    m["entries"].append(e)
    plan.append({"id": f"home/state-{name}", "kind": "state", "url": "/home", "parent": "home", "opener": opener})
THREAD_CSS = "<style>.dropdown-list{display:none}.dropdown-list.open{display:block}.hover-visible[_ngcontent-ng-c4012345679]{opacity:0;pointer-events:none}.hover-zone[_nghost-ng-c4012345679] .hover-visible[_ngcontent-ng-c4012345679]{opacity:1;pointer-events:all}.cycle{display:none}.cycle.open{display:block}.back-drop{position:fixed;top:0;right:0;bottom:0;left:0;z-index:50;display:flex;align-items:flex-end;justify-content:flex-end;background:rgba(0,0,0,.4)}.modal-content{background:#fff;padding:24px;min-height:200px;position:relative}</style>"
CYCLE = '<div class="cycle"><div class="cycle-a">Left</div> <div class="cycle-b">Right</div></div>' if "--sibling-cycle" in sys.argv else ""
MORE = '<div class="feed-item-actions dropdown-trigger more-dropdown"><div class="navigation-icon">More</div><div class="dropdown-list"><div class="dropdown-item item-edit">Edit</div></div></div><div class="row-line" _nghost-ng-c4012345679=""><span>Row</span> <div class="transparent-dropdown hover-visible" _ngcontent-ng-c4012345679="">React</div></div>' + CYCLE
MODAL = '<div class="xdModal back-drop"><div class="modal-content"><div class="modal-body"><button class="btn v2 text creator-modal-close">Close</button><h2>Edit</h2></div></div></div>'
thread = dst / "pages/messages/thread.html"
t = thread.read_text().replace('<meta charset="utf-8">', '<meta charset="utf-8">' + THREAD_CSS, 1)
thread.write_text(t.replace("<h1>Chat</h1>", "<h1>Chat</h1>" + MORE, 1))
base = next(e for e in m["entries"] if e["id"] == "messages/thread")
url = next(x["url"] for x in plan if x["id"] == "messages/thread")
(dst / "pages/messages/thread").mkdir(exist_ok=True)
for name, opener, doc in [
    ("menu", "div.more-dropdown div.navigation-icon", t.replace("<h1>Chat</h1>", "<h1>Chat</h1>" + MORE.replace('"dropdown-list"', '"dropdown-list open"'), 1)),
    ("item-edit", "div.dropdown-item.item-edit", t.replace("<h1>Chat</h1>", "<h1>Chat</h1>" + MORE, 1).replace("</body>", MODAL + "</body>", 1)),
    ("reaction", "div.transparent-dropdown.hover-visible", t.replace("<h1>Chat</h1>", "<h1>Chat</h1>" + MORE.replace("React</div>", 'React</div><div class="picker">Pick</div>'), 1)),
] + [(n, f"div.cycle-{n[-1]}", t.replace("<h1>Chat</h1>", "<h1>Chat</h1>" + MORE.replace('"cycle"', '"cycle open"'), 1)) for n in (["cycle-a", "cycle-b"] if CYCLE else [])]:
    rel = f"pages/messages/thread/state-{name}.html"
    (dst / rel).write_text(doc)
    m["entries"].append(dict(base, id=f"messages/thread/state-{name}", kind="state", state=name, file=rel, meta=rel.replace(".html", ".meta.json"), png=rel.replace(".html", ".png"), opener=opener))
    plan.append({"id": f"messages/thread/state-{name}", "kind": "state", "url": url, "parent": "messages/thread", "opener": opener})
profile = dst / "pages/profile.html"
pr = profile.read_text()
assert '<div class="avatar-container"><img class="user-avatar"' in pr
profile.write_text(re.sub(r'<div class="avatar-container"><img class="user-avatar"[^>]*></div>', '<div class="avatar default-avatar"></div>', pr, count=1))
(dst / "manifest.json").write_text(json.dumps(m, indent=1))
(dst / "mirror_plan.json").write_text(json.dumps(plan))
CSS = '<link rel="stylesheet" href="https://assets.fansly.com/styles.css">'
for f in (dst / "pages").rglob("*.html"):
    t = f.read_text()
    if 'rel="stylesheet"' not in t: f.write_text(t.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + CSS, 1))
print("derived", dst.relative_to(REPO))
