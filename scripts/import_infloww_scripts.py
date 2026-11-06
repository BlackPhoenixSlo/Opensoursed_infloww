#!/usr/bin/env python3
"""Import an Infloww script library (sequences + tags) into one Creator through the relay's real
`POST /admin/saved-replies/bulk` (service/scripts_import_api.py), in chunks, then reconcile.

    python3 -I scripts/import_infloww_scripts.py --base-url http://127.0.0.1:8797 \
        --account-id <creator id> --dump <dir> [--mode skip|replace] [--dry-run] [--chunk 1000] [--report out.json]

<dir> holds an Infloww dump: `sequences.json` (a list, or {"sequences": [...]}) and/or `tags.json` (a list, or
{"tags": [...]}):
    sequences: [{"name", "order", "created_by"?, "created_on"? ("Oct 13, 2026", ISO or epoch), "modified_on"?,
                 "description"?, "steps": [{"step": "1" | "2.1", "text", "notes"?, "conditional"?, "price"?,
                 "script_name" | "name" | "script_name_candidates": [...]}]}]
    tags:      [{"name", "order", "scripts": [{"name", "text", "notes"?, "price"?}]}]

In Infloww a sequence step IS a script, and that script may also sit in tags: each becomes ONE row. `plan()` maps
the dump that way: a step's script name is its `script_name` (or `name`); a step whose name was ambiguous at capture
(`script_name_candidates`) gets the first candidate no other step uses, in dump order, so each name is used once.
A tag's scripts are joined to steps by script name and go on the step as its `tags`; only tag scripts in no
sequence are sent as tag scripts (standalone rows). "All scripts" and "Uncategorized" are Infloww's fixed views,
not tags: never created, used only to reconcile (All scripts == every row, Uncategorized == the untagged ones).

Sign-in is the owner's, as scripts/lane-stats.sh does: `POST /auth/login` with RELAY_USER / RELAY_PASS (prompted
on a terminal when unset), the session cookie kept for the run; SHARE_TOKEN is appended as ?t= when set.
A chunk holds whole sequences only (one bigger than --chunk goes alone), then tag scripts. Re-running is a no-op
(`skip`: an existing sequence is left and reported; a tag script already there is skipped). `--dry-run` sends each
chunk with `dry_run: true`: the relay counts and rolls back. Media is not in the payload (not importable).

Prints the per-chunk answers, then the reconciliation: the dump's own views vs the plan, the endpoint's counts, and
(not on a dry run) a read-back: rows (FM follow-up scripts aside), per-tag and untagged counts, the sequence metas
in dump order, and every step field by field (sequence, step, text, notes, name, tags, condition, price) against the
plan. `--report` writes all of it as JSON. Exit 0 when everything matches; 1 otherwise; 2 usage / sign-in.
Standard library only.
"""
from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VIEWS = ("all scripts", "uncategorized")  # Infloww's fixed Tag-sidebar entries
_FM = re.compile(r"^FM\d+$")


def _load(path: Path, key: str) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get(key, []) if isinstance(data, dict) else data


def _view(tags: list[dict], name: str) -> list[dict] | None:
    return next((t.get("scripts") or [] for t in tags if t["name"].strip().lower() == name), None)


def _order(label) -> tuple[int, int]:
    n, _, m = str(label).strip().partition(".")
    return int(n), int(m or 0)


def plan(sequences: list[dict], tags: list[dict]) -> dict:
    """The dump as the endpoint's payload, one row per script: {"sequences", "tags" (scripts in no sequence
    only), "expected" (rows, per tag, untagged, steps, sequences), "problems" (unmappable bits)}."""
    real = [t for t in tags if t["name"].strip().lower() not in VIEWS]
    tags_of: dict[str, list[str]] = {}
    for t in real:
        for sc in t.get("scripts") or []:
            got = tags_of.setdefault((sc.get("name") or "").strip(), [])
            if t["name"].strip() not in got:
                got.append(t["name"].strip())
    tags_of.pop("", None)
    used = {(st.get("script_name") or st.get("name") or "").strip() for q in sequences for st in q.get("steps") or []}
    used.discard("")
    problems: list[str] = []
    out: list[dict] = []
    for q in sequences:
        steps = []
        for st in q.get("steps") or []:
            name = (st.get("script_name") or st.get("name") or "").strip()
            if not name and st.get("script_name_candidates"):
                free = [c.strip() for c in st["script_name_candidates"] if c.strip() not in used]
                if free:
                    name = free[0]
                    used.add(name)
                else:
                    problems.append(f"{q['name'].strip()!r} step {st['step']}: every candidate name taken")
            row = {k: st[k] for k in ("step", "text", "notes", "conditional", "price") if st.get(k) is not None}
            steps.append({**row, "name": name or None, "tags": tags_of.get(name, []) if name else []})
        out.append({**{k: v for k, v in q.items() if k not in ("steps", "script_count")}, "steps": steps})
    in_seq = {st["name"] for q in out for st in q["steps"] if st["name"]}
    loose: list[dict] = []
    for t in real:
        scripts = [sc for sc in t.get("scripts") or [] if (sc.get("name") or "").strip() not in in_seq]
        if scripts:
            loose.append({**{k: v for k, v in t.items() if k != "scripts"}, "scripts": scripts})
    standalone = {((sc.get("name") or "").strip().lower(), sc.get("text") or ""): tags_of.get(
        (sc.get("name") or "").strip(), [t["name"].strip()]) for t in loose for sc in t["scripts"]}
    tagged_names = set(tags_of)
    for v in VIEWS:
        for sc in _view(tags, v) or []:
            name = (sc.get("name") or "").strip()
            if name not in in_seq and name not in tagged_names:
                problems.append(f"{name!r}: in no sequence and no tag (an untagged loose script is not importable)")
    n_steps = sum(len(q["steps"]) for q in out)
    per_tag: Counter = Counter()
    for q in out:
        for st in q["steps"]:
            per_tag.update(st["tags"])
    for tl in standalone.values():
        per_tag.update(tl)
    untagged = sum(1 for q in out for st in q["steps"] if not st["tags"])
    expected = {"sequences": len(out), "steps": n_steps, "standalone": len(standalone),
                "rows": n_steps + len(standalone), "per_tag": dict(per_tag), "untagged": untagged}
    # The dump's own views must agree with the plan (All scripts == every row, Uncategorized == untagged).
    views = {"all_scripts": len(_view(tags, "all scripts") or []) if _view(tags, "all scripts") is not None else None,
             "uncategorized": len(_view(tags, "uncategorized") or [])
             if _view(tags, "uncategorized") is not None else None,
             "per_tag": {t["name"].strip(): len(t.get("scripts") or []) for t in real}}
    if views["all_scripts"] is not None and views["all_scripts"] != expected["rows"]:
        problems.append(f"dump 'All scripts' {views['all_scripts']} != planned rows {expected['rows']}")
    if views["uncategorized"] is not None and views["uncategorized"] != untagged:
        problems.append(f"dump 'Uncategorized' {views['uncategorized']} != planned untagged {untagged}")
    for tag, k in views["per_tag"].items():
        if per_tag.get(tag, 0) != k:
            problems.append(f"dump tag {tag!r} {k} != planned {per_tag.get(tag, 0)}")
    return {"sequences": out, "tags": loose, "expected": expected, "dump_views": views, "problems": problems}


def chunks(sequences: list[dict], tags: list[dict], size: int) -> list[dict]:
    """Request bodies of at most `size` scripts each; a sequence is never split, a tag's scripts may be."""
    out: list[dict] = []
    cur: list[dict] = []
    n = 0
    for q in sequences:
        k = len(q.get("steps") or [])
        if cur and n + k > size:
            out.append({"sequences": cur, "tags": []})
            cur, n = [], 0
        cur.append(q)
        n += k
    if cur:
        out.append({"sequences": cur, "tags": []})
    part: list[dict] = []
    n = 0
    for t in tags:
        scripts = t.get("scripts") or []
        for at in range(0, max(len(scripts), 1), size):
            piece = scripts[at:at + size]
            if part and n + len(piece) > size:
                out.append({"sequences": [], "tags": part})
                part, n = [], 0
            part.append({**t, "scripts": piece})
            n += len(piece)
    if part:
        out.append({"sequences": [], "tags": part})
    return out


def _day(v) -> str | None:
    """A dump date as YYYY-MM-DD (what the relay keeps of a day-only date), None when unreadable."""
    if v in (None, ""):
        return None
    try:
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.strptime(str(v).strip(), "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return str(v)[:10]


def read_back(rows: list[dict], metas: list[dict], p: dict) -> dict:
    """The Creator's scripts (FM aside) and sequence metas vs the plan, field by field."""
    rows = [r for r in rows if not _FM.match(r.get("script_id") or "")]
    exp = p["expected"]
    per_tag: Counter = Counter()
    for r in rows:
        per_tag.update(r.get("tags") or [])
    by_seq: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("script_id"):
            by_seq.setdefault(r["script_id"], []).append(r)
    diffs: list[dict] = []
    for q in p["sequences"]:
        name = q["name"].strip()
        got = sorted(by_seq.get(name, []), key=lambda r: (r["script_step"], r["id"]))
        want = [st for _, st in sorted(enumerate(q["steps"]), key=lambda e: (_order(e[1]["step"]), e[0]))]
        if len(got) != len(want):
            diffs.append({"sequence": name, "field": "steps", "want": len(want), "got": len(got)})
        for g, st in zip(got, want):
            for field, w, h in (("step", _order(st["step"])[0], g["script_step"]),
                                ("text", st.get("text") or "", g["text"]),
                                ("notes", (st.get("notes") or "").strip() or None, g["notes"]),
                                ("name", st["name"], g["title"]),
                                ("tags", sorted(st["tags"]), sorted(g.get("tags") or [])),
                                ("conditional", (st.get("conditional") or "").strip() or None, g.get("conditional")),
                                ("price", float(st.get("price") or 0), float(g.get("price") or 0))):
                if w != h:
                    diffs.append({"sequence": name, "step": st["step"], "field": field, "want": w, "got": h})
    loose = {((r.get("title") or "").strip().lower(), r["text"]): r for r in rows if not r.get("script_id")}
    for t in p["tags"]:
        for sc in t["scripts"]:
            r = loose.get(((sc.get("name") or "").strip().lower(), sc.get("text") or ""))
            if r is None or t["name"].strip() not in (r.get("tags") or []):
                diffs.append({"tag": t["name"].strip(), "script": sc.get("name"), "field": "standalone",
                              "want": "present + tagged", "got": r and r.get("tags")})
    by_name = {m["name"]: m for m in metas}
    want_order = [q["name"].strip() for q in sorted(p["sequences"], key=lambda q: q.get("order") or 0)]
    order = [m["name"] for m in sorted((m for m in metas if m["name"] in set(want_order)),
                                       key=lambda m: (m.get("position") is None, m.get("position") or 0, m["name"]))]
    meta_diffs = []
    for q in p["sequences"]:
        m = by_name.get(q["name"].strip()) or {}
        for field, w, h in (("created_by", (q.get("created_by") or "").strip() or None, m.get("created_by")),
                            ("description", (q.get("description") or "").strip() or None, m.get("description")),
                            ("created_on", _day(q.get("created_on")), (m.get("created_at") or "")[:10] or None),
                            ("modified_on", _day(q.get("modified_on") or q.get("created_on")),
                             (m.get("updated_at") or "")[:10] or None)):
            if w != h:
                meta_diffs.append({"sequence": q["name"].strip(), "field": field, "want": w, "got": h})
    got = {"rows": len(rows), "sequences": len(by_seq), "metas": len(metas), "per_tag": dict(per_tag),
           "untagged": sum(1 for r in rows if not r.get("tags")), "metas_in_dump_order": order == want_order}
    mism = [k for k in ("rows", "untagged") if got[k] != exp[k]]
    if got["sequences"] != exp["sequences"] or got["metas"] != exp["sequences"]:
        mism.append("sequences")
    if got["per_tag"] != exp["per_tag"]:
        mism.append("per_tag")
    if not got["metas_in_dump_order"]:
        mism.append("metas order")
    return {"got": got, "mismatches": mism, "step_diffs": diffs, "meta_diffs": meta_diffs}


class Relay:
    def __init__(self, base: str, share_token: str | None) -> None:
        self.base = base.rstrip("/")
        self.token = share_token
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def url(self, path: str, **q: str) -> str:
        if self.token:
            q["t"] = self.token
        return f"{self.base}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")

    def call(self, method: str, path: str, body: dict | None = None, **q: str) -> tuple[int, dict]:
        req = urllib.request.Request(self.url(path, **q), method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=300) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}


def _sign_in(relay: Relay) -> None:
    user = os.environ.get("RELAY_USER") or (input("username: ") if sys.stdin.isatty() else "")
    pw = os.environ.get("RELAY_PASS") or (getpass.getpass("password: ") if sys.stdin.isatty() else "")
    if not user or not pw:
        sys.exit("relay needs a sign-in; set RELAY_USER and RELAY_PASS")
    code, _ = relay.call("POST", "/auth/login", {"username": user, "password": pw})
    if code != 200:
        sys.exit(f"sign-in failed (HTTP {code})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--account-id", required=True)
    ap.add_argument("--dump", required=True, type=Path)
    ap.add_argument("--mode", choices=("skip", "replace"), default="skip")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chunk", type=int, default=1000, help="scripts per request (max 5000)")
    ap.add_argument("--report", type=Path, help="write the reconciliation as JSON here")
    a = ap.parse_args(argv)
    p = plan(_load(a.dump / "sequences.json", "sequences"), _load(a.dump / "tags.json", "tags"))
    if not p["sequences"] and not p["tags"]:
        print(f"nothing to import in {a.dump}", file=sys.stderr)
        return 2
    exp = p["expected"]
    print(f"plan: {exp['sequences']} sequences, {exp['steps']} steps + {exp['standalone']} standalone tag scripts "
          f"= {exp['rows']} scripts; per tag {exp['per_tag']}, untagged {exp['untagged']}; dump views "
          f"{p['dump_views']}")
    for msg in p["problems"]:
        print(f"  PLAN PROBLEM {msg}")
    relay = Relay(a.base_url, os.environ.get("SHARE_TOKEN"))
    code, _ = relay.call("GET", "/admin/saved-replies/sequences", account_id=a.account_id)
    if code == 401:
        _sign_in(relay)
    total: Counter = Counter()
    failed: list[dict] = []
    skipped: list[str] = []
    bodies = chunks(p["sequences"], p["tags"], max(1, min(a.chunk, 5000)))
    for i, body in enumerate(bodies, start=1):
        code, ans = relay.call("POST", "/admin/saved-replies/bulk",
                               {**body, "mode": a.mode, "dry_run": a.dry_run}, account_id=a.account_id)
        if code != 200:
            print(f"chunk {i}/{len(bodies)}: HTTP {code} {ans}", file=sys.stderr)
            failed.append({"kind": "chunk", "name": f"chunk {i}", "reason": f"HTTP {code}: {ans.get('detail')}"})
            continue
        for part in ("sequences", "steps", "tag_scripts"):
            for k, v in ans[part].items():
                total[f"{part}.{k}"] += v
        failed += ans["failed"]
        skipped += ans["skipped"]
        print(f"chunk {i}/{len(bodies)}: sequences {ans['sequences']} steps {ans['steps']} "
              f"tag_scripts {ans['tag_scripts']}")

    tag_scripts = sum(len(t["scripts"]) for t in p["tags"])
    print("\nreconciliation" + (" (dry run: nothing written)" if a.dry_run else ""))
    print(f"  sequences in dump {exp['sequences']}: created {total['sequences.created']}, "
          f"replaced {total['sequences.replaced']}, already there {total['sequences.skipped']}, "
          f"failed {total['sequences.failed']}")
    print(f"  steps in dump {exp['steps']}: created {total['steps.created']}, "
          f"deleted by replace {total['steps.deleted']}")
    print(f"  tag scripts in dump {tag_scripts}: created {total['tag_scripts.created']}, "
          f"tag added {total['tag_scripts.tagged']}, already there {total['tag_scripts.skipped']}, "
          f"failed {total['tag_scripts.failed']}")
    for f in failed:
        print(f"  FAILED {f.get('kind')} {f.get('tag', '') + ' / ' if f.get('tag') else ''}{f.get('name')!r}: "
              f"{f.get('reason')}")
    report = {"plan": {"expected": exp, "dump_views": p["dump_views"], "problems": p["problems"]},
              "counts": dict(total), "failed": failed, "skipped": skipped, "dry_run": a.dry_run}
    ok = not failed and not p["problems"]
    if not a.dry_run:
        code, ans = relay.call("GET", "/admin/saved-replies", account_id=a.account_id)
        code2, metas = relay.call("GET", "/admin/saved-replies/sequences", account_id=a.account_id)
        if code != 200 or code2 != 200:
            print(f"  read-back: HTTP {code} / {code2}", file=sys.stderr)
            return 1
        rb = read_back(ans["list"], metas["list"], p)
        g = rb["got"]
        print(f"  read-back: {g['rows']} scripts (want {exp['rows']}), {g['sequences']} sequences with "
              f"{g['metas']} metas (want {exp['sequences']}, dump order {g['metas_in_dump_order']}), per tag "
              f"{g['per_tag']} (want {exp['per_tag']}), untagged {g['untagged']} (want {exp['untagged']})")
        print(f"  field-by-field: {len(rb['step_diffs'])} step differences, {len(rb['meta_diffs'])} meta "
              f"differences; mismatches {rb['mismatches'] or 'none'}")
        for d in (rb["step_diffs"] + rb["meta_diffs"])[:20]:
            print(f"    {d}")
        report["read_back"] = rb
        ok = ok and not rb["mismatches"] and not rb["step_diffs"] and not rb["meta_diffs"]
    report["ok"] = ok
    if a.report:
        a.report.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("OK" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
