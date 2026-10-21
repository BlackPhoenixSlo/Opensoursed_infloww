#!/usr/bin/env python3
"""
drive.py — steer the recording Chrome from the CLI.

  ../../venv/bin/python drive.py list
  ../../venv/bin/python drive.py nav https://fansly.com/messages
  ../../venv/bin/python drive.py shot /tmp/page.png
  ../../venv/bin/python drive.py click 'a[href*="statements"]'
  ../../venv/bin/python drive.py eval 'document.title'
  ../../venv/bin/python drive.py links            # every visible link+button

Attaches straight to a PAGE target's own debugger socket, so it does not touch
the browser-level auto-attach that record.py is holding — the two run side by
side and driving the page is itself captured.

`shot` matters more than it looks: it lets the agent LOOK at the page instead of
guessing selectors, which is how you find a view (a creator sales/statements
page) whose URL nobody has written down.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

# PORT is read from the environment so a second browser (a second account, on a
# second profile) can be driven with `PORT=9223 drive.py ...`. This was
# hardcoded until 2026-09-02, which silently sent every `PORT=9223` invocation
# to :9222 instead — two windows read as one account and looked like a login
# bug in the browser rather than a bug here.
PORT = int(os.environ.get("PORT", "9222"))


def page_targets() -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


_dlg_id = [9000]


async def call(ws, mid: int, method: str, params: dict | None = None) -> dict:
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))

        # A native JS dialog blocks the page until answered, so `Page.navigate`
        # never returns and the caller just hangs. Fansly raises `beforeunload`
        # when you navigate away from a composer holding unsent text. Answer it
        # inline, here, so EVERY command is dialog-safe rather than only nav.
        #
        # beforeunload/alert: accept. confirm/prompt: DISMISS — auto-confirming
        # an unknown native dialog could commit something destructive, and
        # Fansly's own confirms are DOM modals, so a native one is unexpected.
        if msg.get("method") == "Page.javascriptDialogOpening":
            dtype = (msg.get("params") or {}).get("type", "")
            accept = dtype in ("beforeunload", "alert")
            _dlg_id[0] += 1
            await ws.send(json.dumps({"id": _dlg_id[0],
                                      "method": "Page.handleJavaScriptDialog",
                                      "params": {"accept": accept}}))
            print(f"[js dialog {dtype} -> {'accept' if accept else 'dismiss'}]",
                  file=sys.stderr)
            continue

        if msg.get("id") == mid:
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


async def evaluate(ws, mid: int, expr: str):
    res = await call(ws, mid, "Runtime.evaluate", {
        "expression": expr, "returnByValue": True, "awaitPromise": True,
        "userGesture": True,
    })
    if res.get("exceptionDetails"):
        return {"error": str(res["exceptionDetails"])[:400]}
    return res.get("result", {}).get("value")


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")

    targets = page_targets()
    if not targets:
        print("no page targets — is Chrome running with start_chrome.sh?", file=sys.stderr)
        return 2

    if cmd == "list":
        for i, t in enumerate(targets):
            print(f"[{i}] {t.get('title','')[:60]!r}\n     {t.get('url','')[:140]}")
        return 0

    # Prefer a fansly tab if one is open, else the first page.
    tgt = next((t for t in targets if "fansly.com" in (t.get("url") or "")), targets[0])

    async with websockets.connect(tgt["webSocketDebuggerUrl"],
                                  max_size=100 * 1024 * 1024) as ws:
        # Page domain on for EVERY command, not just nav: a click can trigger a
        # navigation, and without Page.enable the beforeunload dialog event
        # never arrives — the page would sit blocked and the command time out.
        await call(ws, 900, "Page.enable")

        if cmd == "nav":
            await call(ws, 2, "Page.navigate", {"url": arg})
            await asyncio.sleep(3.0)
            print(await evaluate(ws, 3, "location.href"))

        elif cmd == "shot":
            res = await call(ws, 1, "Page.captureScreenshot", {"format": "png"})
            path = arg or "/tmp/page.png"
            open(path, "wb").write(base64.b64decode(res["data"]))
            print(path)

        elif cmd == "eval":
            print(json.dumps(await evaluate(ws, 1, arg), indent=2, ensure_ascii=False)[:6000])

        elif cmd == "click":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "if(!e)return 'NOT FOUND';e.scrollIntoView({block:'center'});"
                  "e.click();return 'clicked: '+(e.innerText||e.getAttribute('href')||e.tagName);})()")
            print(await evaluate(ws, 1, js))
            await asyncio.sleep(2.5)


        elif cmd == "type":
            # REAL key events. Angular's composer listens for keydown/input from
            # a trusted-looking sequence; setting .value directly fires nothing,
            # so a synthetic assignment produces no typing frame at all.
            sel = sys.argv[3] if len(sys.argv) > 3 else None
            if sel:
                await evaluate(ws, 1, f"(()=>{{const e=document.querySelector({json.dumps(sel)});"
                                      "if(e){e.focus();return 'focused';}return 'NOT FOUND';})()")
            mid = 10
            for ch in arg:
                for typ in ("keyDown", "char", "keyUp"):
                    mid += 1
                    p = {"type": typ, "text": ch, "key": ch}
                    if typ != "char":
                        p = {"type": typ, "key": ch, "text": ch,
                             "unmodifiedText": ch}
                    await call(ws, mid, "Input.dispatchKeyEvent", p)
                await asyncio.sleep(0.12)
            print(f"typed {len(arg)} chars")

        elif cmd == "focus":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "if(!e)return 'NOT FOUND';e.focus();e.click();return 'focused '+e.tagName;})()")
            print(await evaluate(ws, 1, js))


        elif cmd == "insert":
            # Input.insertText goes through the browser's real editing pipeline,
            # so ngModel/valueChanges fire. dispatchKeyEvent alone left the
            # textarea empty (verified: .value === "") — Chrome will not
            # synthesize the edit from a bare keyDown.
            sel = sys.argv[3] if len(sys.argv) > 3 else "textarea.message-input"
            print(await evaluate(ws, 1,
                f"(()=>{{const e=document.querySelector({json.dumps(sel)});"
                "if(!e)return 'NOT FOUND';e.focus();e.click();return 'focused';})()"))
            mid = 20
            for ch in arg:
                mid += 1
                await call(ws, mid, "Input.insertText", {"text": ch})
                await asyncio.sleep(0.15)
            print("value now:", await evaluate(ws, 99,
                f"document.querySelector({json.dumps(sel)}).value"))

        elif cmd == "links":
            js = """(()=>{const seen=new Set();const out=[];
              document.querySelectorAll('a,button,[role="button"],[role="tab"]').forEach(e=>{
                const r=e.getBoundingClientRect(); if(r.width<2||r.height<2) return;
                const t=(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,50);
                const h=e.getAttribute('href')||'';
                const k=t+'|'+h; if(!t&&!h) return; if(seen.has(k))return; seen.add(k);
                out.push({t,h,tag:e.tagName.toLowerCase()});});
              return out;})()"""
            for it in (await evaluate(ws, 1, js)) or []:
                print(f"  {it['tag']:7s} {it['t'][:45]:45s} {it['h'][:60]}")

        elif cmd == "text":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "return e?e.innerText.slice(0,4000):'NOT FOUND';})()")
            print(await evaluate(ws, 1, js))

        else:
            print(f"unknown command {cmd!r}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
