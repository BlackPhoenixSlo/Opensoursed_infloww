from __future__ import annotations

import asyncio
import time

CRASH_WAIT = 5.0
BLANK_PASSES = 3
WORKER_TYPES = frozenset({"worker", "service_worker", "shared_worker"})
TARGET_END = {"Target.targetCrashed": "crashed", "Target.targetDestroyed": "destroyed",
              "Target.detachedFromTarget": "detached"}


def _is_web(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _ended(conn, tid: str, kind: str, mark: int) -> bool:
    return conn.ended[kind].get(tid, 0) > mark


async def _attach(conn, sessions: dict, tid: str):
    try:
        if not sessions.get(tid):
            sessions[tid] = (await conn.send("Target.attachToTarget",
                                             {"targetId": tid, "flatten": True}))["sessionId"]
        return sessions[tid]
    except Exception:
        sessions.pop(tid, None)
        return None


async def crash_renderers(conn, tids: list, sessions: dict, mark: int) -> set:
    crashed: set = set()
    settled: set = set()

    async def one(tid: str) -> None:
        try:
            sid = await _attach(conn, sessions, tid)
            if not sid:
                raise RuntimeError("no session")
            await conn.send("Page.crash", {}, sid, timeout=CRASH_WAIT)
        except Exception as e:
            if "crashed" in str(e):
                crashed.add(tid)
        settled.add(tid)

    sends = [asyncio.create_task(one(tid)) for tid in tids]
    end = time.monotonic() + CRASH_WAIT
    while time.monotonic() < end and not all(
            tid in settled or any(_ended(conn, tid, k, mark) for k in TARGET_END.values()) for tid in tids):
        await asyncio.sleep(0.02)
    for t in sends:
        t.cancel()
    await asyncio.gather(*sends, return_exceptions=True)
    return {tid for tid in tids if tid not in crashed
            and not _ended(conn, tid, "crashed", mark) and not _ended(conn, tid, "destroyed", mark)}


async def crash_confirmed(conn, tids: list, sessions: dict) -> set:
    mark = conn.seq
    left = await crash_renderers(conn, tids, sessions, mark)
    if not left:
        return left
    for tid in left:
        if _ended(conn, tid, "detached", mark):
            sessions.pop(tid, None)
    return await crash_renderers(conn, sorted(left), sessions, mark)


async def blank_web_pages(conn, sessions: dict, close_others: bool = False) -> tuple[int, list]:
    # Crash before navigating: pagehide beacons escape Fetch and offline; SWs stop first or their scope hangs.
    mark = conn.seq
    seen, tried, unconfirmed = set(), set(), set()
    for _ in range(BLANK_PASSES):
        infos = (await conn.send("Target.getTargets"))["targetInfos"]
        web = [t for t in infos if _is_web(t.get("url", ""))]
        pages = [t["targetId"] for t in web if t["type"] == "page"]
        frames = [t["targetId"] for t in infos if t["type"] == "iframe" and t["targetId"] not in tried]
        workers = [t["targetId"] for t in infos if close_others and t["type"] in WORKER_TYPES]
        if not pages and not frames and not workers:
            break
        seen |= set(pages)
        for tid in pages:
            await _attach(conn, sessions, tid)
        sid = next((sessions[tid] for tid in pages if sessions.get(tid)), None)
        if sid:
            for method in ("ServiceWorker.enable", "ServiceWorker.stopAllWorkers"):
                try:
                    await conn.send(method, {}, sid, timeout=3)
                except Exception:
                    pass
        for tid in workers:
            try:
                await conn.send("Target.closeTarget", {"targetId": tid}, timeout=3)
            except Exception:
                pass
        tried |= set(frames)
        unconfirmed |= await crash_confirmed(conn, frames, sessions)
        unconfirmed |= await crash_confirmed(conn, pages, sessions)
        collateral = [t["targetId"] for t in (await conn.send("Target.getTargets"))["targetInfos"]
                      if t["type"] == "page" and _ended(conn, t["targetId"], "crashed", mark)]
        for tid in dict.fromkeys(pages + collateral):
            try:
                sid = await _attach(conn, sessions, tid)
                if not sid:
                    raise RuntimeError("no session")
                await conn.send("Page.navigate", {"url": "about:blank"}, session_id=sid, timeout=5)
            except Exception:
                sessions.pop(tid, None)
                try:
                    await conn.send("Target.closeTarget", {"targetId": tid}, timeout=3)
                except Exception:
                    pass
    else:
        infos = (await conn.send("Target.getTargets"))["targetInfos"]
        unconfirmed |= {t["targetId"] for t in infos
                        if (t["type"] == "page" and _is_web(t.get("url", "")))
                        or (t["type"] == "iframe" and t["targetId"] not in tried)
                        or (close_others and t["type"] in WORKER_TYPES)}
    return len(seen), sorted(unconfirmed)
