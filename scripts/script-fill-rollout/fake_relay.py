from __future__ import annotations

import hashlib
import itertools
import json
import re
import threading
import time

import rollout

BASE = {"platform": "onlyfans", "has_session": True, "session_dead_at": None, "is_active": True}

SESSION = "s3cret-cookie"
ITEM_MC_REAL = 10
_ROW_IDS = itertools.count(9001)


def srow(step, role="chat", price=0, media=(), previews=(), fill=None):
    return {"id": next(_ROW_IDS), "step": step, "role": role, "price": price, "media": list(media),
            "previews": list(previews), "fill": fill}


class Cr:
    def __init__(self, cid, username, *, describable=600, terminal=0, described=0, complete=True, cap=100000,
                 spent=0, key_missing=False, jev_ready=True, per_poll=60, zero=False, collect_pauses=0,
                 collect_complete=True, collect_items=0, running_target=None, collect_stuck=False):
        self.id, self.username = cid, username
        self.describable, self.terminal, self.described = describable, terminal, described
        self.complete, self.cap, self.spent = complete, cap, spent
        self.key_missing, self.jev_ready, self.per_poll, self.zero = key_missing, jev_ready, per_poll, zero
        self.running_target = running_target
        self.progress = None
        self.collect_pauses, self.collect_complete, self.collect_items = collect_pauses, collect_complete, collect_items
        self.collect = None
        self.collect_stuck = collect_stuck
        self.forbidden = False
        self.items = set()
        self.seqs = {"S1": [srow(1), srow(2)], "S2": [srow(1)]}
        self.fill_status = {}
        self.version = {}

    def goal(self, target):
        return max(0, min(target, self.describable - self.terminal))


class Fake:
    def __init__(self, creators, extra_accounts=(), watchers=()):
        self.lock = threading.Lock()
        self.cr = {c.id: c for c in creators}
        self.accounts = [{**BASE, "id": c.id, "username": c.username, "nickname": c.username.title()}
                         for c in creators] + list(extra_accounts)
        self.watchers = list(watchers)
        self.is_admin = True
        self.phase1a = True
        self.posts = []
        self.events = []
        self.max_running = 0
        self.status_polls = 0
        self.fail = {}
        self.hits = {}
        self.seen = []
        self.redirect_me = None
        self.applies = []
        self.undos = []
        self.last_undo = {}
        self.undo_short = False
        self.bump_on_apply = {}
        self.fingerprint = True
        self.livez_status = 200

    def fill_plan(self, c, name):
        rows = c.seqs[name]
        paid = any(r["role"] == "paid_media" for r in rows)
        fills = [r for r in rows if not r["media"] and r["fill"]]
        if re.fullmatch(r"FM\d+", name):
            status = "reserved"
        elif name in c.fill_status:
            status = c.fill_status[name]
        elif not paid:
            status = "no_paid_steps"
        else:
            status = "ok" if fills else "already_filled"
        opts, writes, seen = [], [], {}
        for r in rows:
            seen[r["step"]] = seen.get(r["step"], 0) + 1
            keep = bool(r["media"])
            media, previews, price, flags = list(r["media"]), list(r["previews"]), r["price"], []
            if keep:
                flags.append("kept_existing")
            elif r["fill"] and status == "ok":
                media, previews = list(r["fill"][0]), list(r["fill"][1])
                sets = r["role"] == "paid_media" and r["price"] == 0
                price = r["fill"][2] if sets else r["price"]
                writes.append([r["id"], media, previews, price if sets else None])
            elif r["role"] == "free_media":
                flags.append("free_unfilled")
            opts.append({"id": r["id"], "step": r["step"], "option": seen[r["step"]], "role": r["role"],
                         "wants": "any", "keep": keep, "media": media, "previews": previews, "price_cents": price,
                         "price_fixed": r["price"] > 0, "flags": flags})
        snap = [[r["id"], r["step"], r["media"], r["previews"], r["price"]] for r in rows]
        fp = hashlib.sha256(json.dumps([snap, writes, c.version.get(name, 0)]).encode()).hexdigest()
        return {"status": status, "options": opts, "flags": [], "conflict": None, "describe": {},
                **({"fingerprint": fp} if self.fingerprint else {})}

    def fill_apply(self, c, body):
        name = body.get("sequence")
        if name not in c.seqs:
            return 404, {"detail": {"error": "sequence_not_found"}}
        if self.bump_on_apply.get(name, 0) > 0:
            self.bump_on_apply[name] -= 1
            c.version[name] = c.version.get(name, 0) + 1
        p = self.fill_plan(c, name)
        if body.get("fingerprint") and body["fingerprint"] != p.get("fingerprint"):
            return 409, {"detail": {"error": "stale", "plan": p}}
        if p["status"] != "ok":
            return 200, {"status": p["status"], "plan": p, "applied": [], "undo": []}
        undo = []
        for r in c.seqs[name]:
            if not r["media"] and r["fill"]:
                sets = r["role"] == "paid_media" and r["price"] == 0
                r["media"], r["previews"] = list(r["fill"][0]), list(r["fill"][1])
                if sets:
                    r["price"] = r["fill"][2]
                undo.append({"id": r["id"], "media_ids": list(r["media"]), "previews": list(r["previews"]),
                             "price_cents": r["price"], "price_set": sets})
        self.applies.append((c.id, name))
        self.last_undo[(c.id, name)] = [dict(u) for u in undo]
        written = {u["id"] for u in undo}
        if self.undo_short:
            undo = undo[:-1]
        return 200, {"status": "ok", "plan": p, "applied": [o for o in p["options"] if o["id"] in written],
                     "undo": undo}

    def fill_undo(self, c, body):
        name = body.get("sequence")
        if name not in c.seqs:
            return 404, {"detail": {"error": "sequence_not_found"}}
        self.undos.append((c.id, name))
        if re.fullmatch(r"FM\d+", name):
            return 200, {"undone": [], "kept": [{"id": e["id"], "reason": "reserved"} for e in body.get("undo") or []]}
        rows = {r["id"]: r for r in c.seqs[name]}
        undone, kept = [], []
        for e in body.get("undo") or []:
            r = rows.get(e["id"])
            if r is None:
                kept.append({"id": e["id"], "reason": "missing"})
            elif (r["media"], r["previews"], r["price"]) != (e["media_ids"], e["previews"], e["price_cents"]):
                kept.append({"id": e["id"], "reason": "edited"})
            else:
                r["media"], r["previews"] = [], []
                if e["price_set"]:
                    r["price"] = 0
                undone.append(e["id"])
        return 200, {"undone": undone, "kept": kept}

    def scripts_list(self, c):
        out = [{"id": r["id"], "script_id": name, "script_step": r["step"],
                "media": [{"id": m, "type": "photo"} for m in r["media"]], "previews": list(r["previews"]),
                "price": r["price"] / 100, "removed_media_ids": [m for m in r["media"] if m not in c.items]}
               for name, rows in c.seqs.items() for r in rows]
        return out + [{"id": 1, "script_id": None, "media": [], "previews": [], "price": 0}]

    def plan(self, c, target):
        g = c.goal(target)
        cov = {"target": target, "describable": c.describable, "described": c.described, "terminal": c.terminal,
               "goal": g, "remaining": max(0, g - c.described)}
        out = {"account_id": c.id, "total": c.describable, "undescribed": c.describable - c.described,
               "cap": {"spent_millicents": c.spent, "cap_millicents": c.cap, "capped": c.spent >= c.cap,
                       "key_missing": c.key_missing, "blocked_reason": ""},
               "jev": {"ready": c.jev_ready, "reason": "" if c.jev_ready else "NudeNet missing"}}
        if self.phase1a:
            out["target_remaining"] = cov["remaining"]
            out["coverage"] = cov
        return out

    def start(self, c, target):
        if c.running_target is not None:
            return 409, {"detail": {"error": "describe_already_running"}}
        if c.key_missing:
            return 424, {"detail": {"error": "llm_key_missing"}}
        if c.spent >= c.cap:
            return 429, {"detail": {"error": "daily_cap_reached"}}
        if c.goal(target) - c.described <= 0:
            return 200, {"status": "done", "target": target, "target_remaining": 0}
        c.running_target = target
        c.progress = {"total": c.goal(target) - c.described, "done": 0, "failed": 0, "capped": False,
                      "error": "", "key_error": None, "stop": None}
        self.events.append(("start", c.id, target))
        self.max_running = max(self.max_running, sum(1 for x in self.cr.values() if x.running_target is not None))
        return 200, {"status": "running", "target": target}

    def tick(self, c):
        if c.running_target is None:
            return
        g = c.goal(c.running_target)
        if c.zero:
            c.progress.update(failed=c.progress["total"], error="Stopped: 5 items in a row failed.")
            c.running_target = None
        else:
            room = (c.cap - c.spent) // ITEM_MC_REAL
            add = max(0, min(c.per_poll, g - c.described, room))
            c.described += add
            c.spent += add * ITEM_MC_REAL
            c.progress["done"] += add
            if c.spent >= c.cap and c.described < g:
                c.progress["capped"] = True
                c.running_target = None
            elif c.described >= g:
                c.running_target = None
        if c.running_target is None:
            self.events.append(("end", c.id, g))

    def collect_tick(self, c):
        k = c.collect
        if k is None or not k["running"]:
            return
        k["polls"] += 1
        if k["status"] == "paused":
            return
        if k["pauses_left"] > 0 and k["polls"] >= 1:
            k["status"] = "paused"
            return
        c.count = getattr(c, "count", 0) + c.collect_items
        k.update(status="done", running=False)
        c.complete = c.collect_complete

    def handle(self, method, path, q, body, cookie):
        with self.lock:
            aid = (q.get("account_id") or [None])[0] or (body or {}).get("account_id")
            if method == "POST":
                self.posts.append((path, aid, body))
            self.seen.append((method, path))
            if path == "/auth/me" and self.redirect_me:
                return 302, {}, {"Location": self.redirect_me}
            if path == "/livez":
                return self.livez_status, {"ok": self.livez_status == 200}
            if path == "/auth/login" and method == "POST":
                return 200, {"user_id": "u1", "is_admin": True}, {"Set-Cookie": f"chatterly_session={SESSION}; Path=/"}
            authed = cookie == SESSION
            if path == "/auth/me":
                return 200, ({"user_id": "u1", "username": "m", "is_admin": self.is_admin} if authed else None)
            if not authed:
                return 401, {"detail": "auth required"}
            c = self.cr.get(aid) if aid else None
            if path == "/admin/accounts":
                return 200, {"accounts": self.accounts, "watchers": self.watchers}
            if c is None:
                return 404, {"detail": "no such account"}
            if c.forbidden:
                return 403, {"detail": {"error": "folder_not_allowed"}}
            hits = self.hits.setdefault((path, aid), [])
            hits.append(time.monotonic())
            f = self.fail.get((path, aid))
            f = f(c) if callable(f) else f
            if f and len(hits) <= 50:
                return f, {"detail": {"error": "boom"}}
            if path == "/admin/vault-ai/cache/summary":
                return 200, {"account_id": aid, "count": getattr(c, "count", c.describable), "complete": c.complete,
                             "running": bool(c.collect and c.collect["running"]), "last_run": None}
            if path == "/admin/vault-ai/describe-all/plan":
                return 200, self.plan(c, int((q.get("target") or ["1000"])[0]))
            if path == "/admin/vault-ai/describe-all" and method == "POST":
                return self.start(c, int(body.get("target")))
            if path == "/admin/vault-ai/describe-all/status":
                self.status_polls += 1
                self.tick(c)
                return 200, {"account_id": aid, "running": c.running_target is not None, "progress": c.progress}
            if path == "/admin/vault-ai/collect" and method == "POST":
                if c.collect and c.collect["running"]:
                    return 409, {"detail": {"error": "collect_already_running"}}
                c.collect = {"status": "running", "running": True, "pauses_left": c.collect_pauses, "polls": 0}
                return 200, {"account_id": aid, "run_id": 7, "status": "running"}
            if path == "/admin/vault-ai/collect/status":
                self.collect_tick(c)
                k = c.collect or {}
                return 200, {"account_id": aid, "run": {"id": 7, "status": k.get("status"),
                                                        "running": k.get("running", False), "total_seen": 10}}
            if path == "/admin/vault-ai/collect/continue" and method == "POST":
                k = c.collect or {}
                if k.get("status") != "paused":
                    return 409, {"detail": {"error": "collect_not_paused"}}
                if c.collect_stuck and len(hits) <= 50:
                    return 200, {"account_id": aid, "status": "continue"}
                k["pauses_left"] -= 1
                k["status"] = "running"
                return 200, {"account_id": aid, "status": "continue"}
            if path == "/admin/saved-replies":
                return 200, {"list": self.scripts_list(c)}
            if path == "/admin/saved-replies/fill/plan" and method == "POST":
                if body.get("sequence") not in c.seqs:
                    return 404, {"detail": {"error": "sequence_not_found"}}
                return 200, self.fill_plan(c, body["sequence"])
            if path == "/admin/saved-replies/fill/apply" and method == "POST":
                return self.fill_apply(c, body)
            if path == "/admin/saved-replies/fill/undo" and method == "POST":
                return self.fill_undo(c, body)
            if path == "/admin/vault-ai/items":
                lim, off = int(q["limit"][0]), int(q["offset"][0])
                got = sorted(c.items)
                return 200, {"list": [{"id": m, "type": "photo"} for m in got[off:off + lim]],
                             "hasMore": off + lim < len(got), "source": "mirror"}
            if path == "/admin/vault-ai/thumb":
                return 200, b"\x89PNG-fake-" + q["media_id"][0].encode(), {"Content-Type": "image/png"}
            if path == "/admin/stats/grok-calls":
                return 200, {"rows": [
                    {"purpose": "describe_media", "provider": "deepinfra", "cost_millicents": c.spent},
                    {"purpose": "vault_jev_flags", "provider": "typesafe", "cost_millicents": 50},
                    {"purpose": "chat_reply", "provider": "deepseek", "cost_millicents": 99999}]}
            return 404, {"detail": "not found"}



def run(url, tmp_path, *args):
    return rollout.main([args[0], "--relay", url, "--journal", str(tmp_path / "j.jsonl"),
                         "--out", str(tmp_path / "report.md"), *args[1:]])


def journal(tmp_path):
    p = tmp_path / "j.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def kinds(tmp_path, kind):
    return [ln for ln in journal(tmp_path) if ln["kind"] == kind]
