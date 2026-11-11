"""Growth > Scripts holds an Infloww library: sequences (~17 steps each) + tags on one Creator, bulk-imported.

Flow (agency_inbox stack): a deterministic dump in the real capture's shape (`--seed`; `--sequences=` overrides the
scale's `scripts_library_sequences`; the real library is 44 sequences / 764 scripts) is written to
`<tmp>/infloww-dump/`: steps carry `script_name` (two ambiguous pairs only `script_name_candidates`), notes (some
empty), emoji, day-only dates ("Oct 13, 2026"), a description on some; the deep (middle) sequence also has "N.M"
options with a condition and prices. tags.json holds Infloww's fixed views "All scripts" and "Uncategorized" plus
one real tag over a few steps (an ambiguous one included) and LOOSE scripts in no sequence. It is imported into the
first session-backed Creator by the real CLI (`scripts/import_infloww_scripts.py`, a subprocess signed in as the
owner over `POST /auth/login`) through `POST /admin/saved-replies/bulk`: a `--dry-run` first, the import, then
again (a no-op). Nothing is seeded by SQL here: the import is the act under test. Each CLI run leaves
`import-<k>.txt` + its `--report` JSON; the independent read-back leaves `read-back-diff.json`.

Real-data proof: `--dump=<dir>` imports a captured dump instead (client content: keep the run folder out of git,
slop/evidence/* is ignored) and opens EVERY sequence in the UI, not only the deep one.

Checks (names in lib/scripts_library_faults.py):
  IMPORT_COUNTS  the dry run counts every step and writes nothing; the CLI's counts == the dump (one row per script:
                 steps + LOOSE); nothing failed; its own field-by-field read-back exits 0.
  REIMPORT_NOOP  the second run creates nothing.
  READ_BACK      GET /admin/saved-replies: every script once; each sequence's rows in (step, id) order == the dump's
                 steps in (N, M) order, name (candidates resolved first-free) / text / notes / condition / price /
                 tags equal; All scripts / per tag / untagged == the dump's views; /sequences has each meta
                 (position, by, day, description).
  LIST_P95       serial GET /admin/saved-replies p95 under the scale's budget (LIST_P95_MS).
  LIST_LOAD      --users owners each read the whole list at once: all 200, each the full row count.
  UI_SIDEBAR     /growth/scripts, Sequence tab: rendered + "Show more (k)" == sequences, in dump order, each count ==
                 its stored rows; the sidebar search finds the last one.
  UI_STEPS       the deep sequence (`--dump`: each) opened from the sidebar: its cards' label / name / text / notes
                 == the dump in step order, header "Created by：<by>" and "Created on：<day>".
  UI_EXPAND      the last opened sequence: a card's arrow shows iff its two-line clamp cuts text (synthetic: every LONG
                 step has one and some short card has none; an 8-word text may wrap past two lines in the narrow
                 column); clicking one lifts the clamp and turns it "Collapse script".
  UI_TAGS        Tag tab: All scripts / the tag / Uncategorized counts == the dump's; the script search finds the
                 last sequence's step 1.
  UI_SEND        /messages-pro chat: picker search for a sequence's step 1, pick, Enter -> the send goes out,
                 "Next in “<seq>” · step 2" shows, and that row's sent_count is 1 (API).
  SHARE_ALL      POST /admin/saved-replies/copy {from:[aid], all_creators:true} resolves the owner's whole Creator
                 roster SERVER-SIDE and copies the library to every other owned Creator (each then holds >= the
                 source's coverage), carrying each new sequence's header (position / created_by); 4-key response.
  SHARE_ALL_NOOP a second identical share copies 0 (per-target dedup is a true no-op); coverage unchanged.
  ALL_MODELS_VIEW GET /admin/saved-replies/overview lists every owned Creator and, per sequence / tag name, each
                 Creator's count == that Creator's own stored rows (an independent per-account read-back of the lean
                 projection).
  UI_ALL_MODELS  /growth/scripts, the Creator column's "All models" pick: the matrix's columns == the overview's
                 accounts == the whole roster, its Sequence and Tag rows (rendered + "Show more (k)") == the overview
                 in order, each cell's count (missing = 0) == per_account; the header's write actions (Learn, Share,
                 More and its Add script / Create new / Add tag / From Excel / From other creators), shown on a
                 Creator first, are gone; every Creator's GET /admin/saved-replies row count unchanged across it.
p95 vs the last green run on the serial and concurrent list reads (volume tag).

FAULT `scripts-bulk-drops-last-step`: the import loses each sequence's last step (`_parse_sequence`'s steps trimmed):
IMPORT_COUNTS, READ_BACK, UI_STEPS and UI_TAGS go red; the re-import, sidebar, load, send and all-models (UI vs the
overview) checks stay green.
A second fault `scripts-share-drops-a-creator` (`--fault=`): `owned_account_ids` loses its last Creator, so
SHARE_ALL, ALL_MODELS_VIEW and UI_ALL_MODELS go red while SHARE_ALL_NOOP stays green.
A client fault `scripts-expand-arrow-always` (`--fault=`): the row's arrow drops its overflow guard, so UI_EXPAND
goes red (an arrow on short steps that does nothing) and every other check stays green.
Bypass, declared: OF's own /me is held by the slop browser, so the chat's creator id is preset in localStorage
(`of-owner:<account>`), as fm-auto-reply-walk does.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.procmon import pct
from slop.lib.scripts_library_faults import (ALL_MODELS_VIEW, IMPORT_COUNTS, LIST_LOAD, LIST_P95, READ_BACK,
                                             REIMPORT_NOOP, SHARE_ALL, SHARE_ALL_NOOP, UI_ALL_MODELS, UI_EXPAND,
                                             UI_SEND, UI_SIDEBAR, UI_STEPS, UI_TAGS)
from slop.seed.agency import PASSWORD

PROFILE = "agency_inbox"
UI = True
FAULT = "scripts-bulk-drops-last-step"
P95_VS_LAST = (1.5, 100)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "import_infloww_scripts.py"
LIST = "/admin/saved-replies"
SERIAL_READS = 10
READS_PER_USER = 1  # each owner opens the page once, all at once
# Serial GET /admin/saved-replies p95 budget (ms) by scale, measured on the owner's laptop 2026-11-06:
# small (24 sequences, 434 rows) 9-11 ms -> 100 (headroom for the machine's other slop runs); medium
# (100, 1,809 rows; ~2.3x the real 764-script library) 75-82 ms -> 250; huge (300) not measured, ~3x medium.
LIST_P95_MS = {"small": 100, "medium": 250, "huge": 750}
VIEWPORT = (1440, 900)
TAG = "Slop NS"
LOOSE = 5  # tag scripts in no sequence: standalone rows
WORDS = ("hey", "babe", "miss", "you", "so", "much", "today", "special", "just", "for", "you", "unlock", "now",
         "tell", "me", "what", "you", "like", "naughty", "surprise", "weekend", "pics", "video", "custom")
EMOJI = ("😭", "💖", "⭐", "❤️", "👆", "")
# The deep sequence's steps whose text runs past the row's two-line clamp (UI_EXPAND); never its last (the
# drops-last-step fault must leave UI_EXPAND green), nor step 1 / 2 (the chat's picker).
LONG = (7, 13, 19)
DAYS = ("Sep 16, 2026", "Sep 22, 2026", "Oct 1, 2026", "Oct 13, 2026")


def _dump(w, n: int) -> tuple[list[dict], list[dict], dict, dict]:
    """(sequences.json, tags.json, truth {(sequence, label): (name, tags)}, expected view counts)."""
    rng = w.rng("scripts-library")
    seqs: list[dict] = []
    names: dict[tuple[str, str], str] = {}
    for i in range(n):
        qname = f"{600 + i}/Slop seq {i:04d} {rng.choice(WORDS)}"
        deep = i == n // 2
        steps: list[dict] = []
        for k in range(1, (22 if deep else rng.randint(10, 26)) + 1):
            # Options only in the deep one (the real library has none); never on step 1 / 2 (the chat names step 2).
            opts = rng.choice((2, 3)) if deep and k >= 3 and k % 4 == 0 else 1
            for m in range(1, opts + 1):
                label = f"{k}.{m}" if opts > 1 else str(k)
                st = {"step": label, "text": f"slopkey{i:04d}s{label} " + " ".join(rng.choices(WORDS, k=70 if deep and k in LONG else 8))
                      + " " + rng.choice(EMOJI),
                      "notes": f"{1 + k % 2}/2, {rng.choice(('bridge', 'ppv'))}" if rng.random() < 0.85 else "",
                      "sent": 0, "script_name": f"s{i:04d}{label}{rng.choice(WORDS)}"}
                if opts > 1:
                    st["conditional"] = f"fan says {rng.choice(WORDS)}"
                if deep and k % 5 == 0:
                    st["price"] = rng.choice((5, 9.99, 15))
                names[(qname, label)] = st["script_name"]
                steps.append(st)
        day = DAYS[i % len(DAYS)]
        q = {"order": i, "name": qname, "script_count": len(steps), "created_by": f"0{i % 3}{i % 7}",
             "created_on": day, "modified_on": day, "steps": steps}
        if i % 7 == 3:
            q["description"] = f"Slop description {i}"
        seqs.append(q)
    # Two ambiguous pairs, as the real capture had: step 4 of two sequences with identical text + notes, the
    # name recovered only as candidates. The importer gives the first sequence's the first candidate.
    ambiguous = []
    for a, b in ((1, 2), (3, 4)) if n >= 10 else ():
        sa, sb = seqs[a]["steps"][3], seqs[b]["steps"][3]
        sb["text"], sb["notes"] = sa["text"], sa["notes"]
        cands = [sa.pop("script_name"), sb.pop("script_name")]
        sa["script_name_candidates"] = sb["script_name_candidates"] = cands
        ambiguous.append(sb)
    every = [{"name": names[(q["name"], st["step"])], "text": st["text"], "notes": st["notes"], "sent": 0}
             for q in seqs for st in q["steps"]]
    tagged = {s["name"] for s in every if rng.random() < 0.02} | {every[1]["name"]}
    if ambiguous:
        tagged.add(names[(seqs[2]["name"], "4")])
    loose = [{"name": f"loose{j}", "text": f"slop loose script {j} " + " ".join(rng.choices(WORDS, k=6)),
              "notes": "", "sent": 0} for j in range(LOOSE)]
    tags = [{"order": 0, "name": "All scripts", "scripts": every + loose},
            {"order": 1, "name": TAG, "scripts": [s for s in every if s["name"] in tagged] + loose},
            {"order": 2, "name": "Uncategorized", "scripts": [s for s in every if s["name"] not in tagged]}]
    truth = {k: (v, [TAG] if v in tagged else []) for k, v in names.items()}
    views = {"All scripts": len(every) + LOOSE, TAG: len(tagged) + LOOSE, "Uncategorized": len(every) - len(tagged)}
    return seqs, tags, truth, views


def _real(path: Path) -> tuple[list[dict], list[dict], dict, dict, int]:
    """`--dump=<dir>`: a captured Infloww dump instead of the synthetic one (the real-data proof; its content never
    enters the repo, the run folder holds it). Truth is worked out here, apart from the CLI: a step's name is its
    `script_name`, else the first of its `script_name_candidates` no step uses yet (dump order); real tags join by
    name; the views' own lengths are the counts. -> (sequences, tags, truth, views, loose)."""
    seqs = json.loads((path / "sequences.json").read_text(encoding="utf-8"))
    tags = json.loads((path / "tags.json").read_text(encoding="utf-8"))
    used = {st.get("script_name") for q in seqs for st in q["steps"]} - {None}
    names: dict[tuple[str, str], str] = {}
    for q in seqs:
        for st in q["steps"]:
            nm = st.get("script_name") or next((c for c in st.get("script_name_candidates", []) if c not in used), "")
            used.add(nm)
            names[(q["name"].strip(), st["step"])] = nm
    real = [t for t in tags if t["name"] not in ("All scripts", "Uncategorized")]
    tag_of: dict[str, list[str]] = {}
    for t in real:
        for sc in t["scripts"]:
            tag_of.setdefault(sc["name"], []).append(t["name"])
    loose = {sc["name"] for t in real for sc in t["scripts"]} - set(names.values())
    views = {t["name"]: len(t["scripts"]) for t in tags}
    return seqs, tags, {k: (v, tag_of.get(v, [])) for k, v in names.items()}, views, len(loose)


def _order(label: str) -> tuple[int, int]:
    n, _, m = label.partition(".")
    return int(n), int(m or 0)


async def _cli(ctx, aid: str, dump: Path, username: str, run: str, *extra: str) -> tuple[int, str]:
    """The real CLI as a subprocess; its output -> `<run>.txt`, its JSON reconciliation -> `<run>.json`."""
    env = {**os.environ, "RELAY_USER": username, "RELAY_PASS": PASSWORD}
    env.pop("SHARE_TOKEN", None)
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(CLI), "--base-url", ctx.relay, "--account-id", aid, "--dump", str(dump),
        "--report", str(ctx.out / f"{run}.json"), *extra,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
    out, _ = await asyncio.wait_for(p.communicate(), timeout=600)
    (ctx.out / f"{run}.txt").write_text(out.decode())
    return p.returncode or 0, out.decode()


def _counts(out: str) -> dict[str, int]:
    """The CLI's reconciliation lines as numbers."""
    c: dict[str, int] = {}
    for key, rx in (("seq", r"sequences in dump (\d+): created (\d+), replaced (\d+), already there (\d+), "
                            r"failed (\d+)"),
                    ("steps", r"steps in dump (\d+): created (\d+)"),
                    ("tags", r"tag scripts in dump (\d+): created (\d+), tag added (\d+), already there (\d+), "
                             r"failed (\d+)"),
                    ("rows", r"read-back: (\d+) scripts \(want (\d+)\)")):
        m = re.search(rx, out)
        for j, v in enumerate(m.groups() if m else ()):
            c[f"{key}{j}"] = int(v)
    return c


def _day(v: str) -> str:
    return datetime.strptime(v, "%b %d, %Y").strftime("%Y-%m-%d")


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    accounts = (await ctx.owner.get("/admin/accounts")).json()["accounts"]
    active = [a for a in accounts if a.get("has_session") and a.get("is_active")] or accounts
    aid = str(active[0]["id"])
    real = ctx.param("dump", "")
    if real:
        dump = Path(real).expanduser()
        seqs, tags, truth, views, loose = _real(dump)
        n = len(seqs)
    else:
        n = ctx.param("sequences", w.size["scripts_library_sequences"])
        seqs, tags, truth, views = _dump(w, n)
        loose = LOOSE
        dump = ctx.stack.tmp / "infloww-dump"
        dump.mkdir(parents=True, exist_ok=True)
        (dump / "sequences.json").write_text(json.dumps(seqs, ensure_ascii=False), encoding="utf-8")
        (dump / "tags.json").write_text(json.dumps(tags, ensure_ascii=False), encoding="utf-8")
    n_steps = sum(len(q["steps"]) for q in seqs)
    want_rows = n_steps + loose
    ctx.note(f"Creator {aid}: dump {n} sequences, {n_steps} steps, {loose} loose tag scripts; views {views}")
    user = w.data["agency"]["username"]

    # 1. Import with the real CLI: a dry run (writes nothing), the import, then again (a no-op).
    code0, out0 = await _cli(ctx, aid, dump, user, "import-0-dry-run", "--dry-run")
    c0 = _counts(out0)
    after_dry = len((await ctx.owner.get(LIST, params={"account_id": aid})).json().get("list", []))
    t = time.perf_counter()
    code1, out1 = await _cli(ctx, aid, dump, user, "import-1")
    import_s = round(time.perf_counter() - t, 2)
    c1 = _counts(out1)
    ctx.check(IMPORT_COUNTS, code0 == 0 and c0.get("steps1") == n_steps and after_dry == 0
              and code1 == 0 and c1.get("seq0") == n and c1.get("seq1") == n
              and c1.get("seq4") == 0 and c1.get("steps0") == n_steps and c1.get("steps1") == n_steps
              and c1.get("tags1") == loose and c1.get("tags4") == 0 and c1.get("rows0") == c1.get("rows1") == want_rows,
              dry_run_exit=code0, dry_run_steps=c0.get("steps1"), rows_after_dry_run=after_dry,
              exit=code1, counts=c1, dump_sequences=n, dump_steps=n_steps, seconds=import_s,
              tail=out1.strip().splitlines()[-6:])
    code2, out2 = await _cli(ctx, aid, dump, user, "import-2")
    c2 = _counts(out2)
    ctx.check(REIMPORT_NOOP, c2.get("seq1") == 0 and c2.get("seq3") == n and c2.get("steps1") == 0
              and c2.get("tags1") == 0 and c2.get("tags2") == 0 and c2.get("tags3") == loose,
              exit=code2, counts=c2)

    # 2. Read-back: serial reads (latency) and the dump's every field.
    serial: list[float] = []
    body: dict = {}
    for _ in range(SERIAL_READS):
        t = time.perf_counter()
        r = await ctx.owner.get(LIST, params={"account_id": aid})
        serial.append((time.perf_counter() - t) * 1000)
        body = r.json() if r.status_code == 200 else {}
    rows = body.get("list", [])
    by_seq: dict[str, list[dict]] = {}
    for x in rows:
        if x.get("script_id"):
            by_seq.setdefault(x["script_id"], []).append(x)
    # Field by field: (sequence, step N, text, notes, condition, price, name, tags) per row vs the dump.
    diffs: list[dict] = []
    fields = ("step", "text", "notes", "conditional", "price", "name", "tags")
    for q in seqs:
        qn = q["name"].strip()
        got = sorted(by_seq.get(qn, []), key=lambda x: (x["script_step"], x["id"]))
        want = sorted(q["steps"], key=lambda s: _order(s["step"]))
        if len(got) != len(want):
            diffs.append({"sequence": qn, "field": "rows", "got": len(got), "want": len(want)})
        for x, s in zip(got, want):
            g = (x["script_step"], x["text"], x["notes"], x["conditional"], x["price"], x["title"], x["tags"])
            e = (_order(s["step"])[0], s["text"], (s.get("notes") or "").strip() or None, s.get("conditional"),
                 float(s.get("price") or 0), *truth[(qn, s["step"])])
            diffs += [{"sequence": qn, "step": s["step"], "field": f, "got": a, "want": b}
                      for f, a, b in zip(fields, g, e) if a != b]
    loose_rows = [x for x in rows if not x.get("script_id")]
    metas = {m["name"]: m for m in (await ctx.owner.get(
        f"{LIST}/sequences", params={"account_id": aid})).json().get("list", [])}
    meta_bad = [q["name"] for q in seqs if (metas.get(q["name"].strip()) or {}).get("position") != q["order"]
                or metas[q["name"].strip()].get("created_by") != q["created_by"].strip()
                or (metas[q["name"].strip()].get("created_at") or "")[:10] != _day(q["created_on"])
                or metas[q["name"].strip()].get("description") != ((q.get("description") or "").strip() or None)]
    per_tag = {}
    for x in rows:
        for tg in x["tags"]:
            per_tag[tg] = per_tag.get(tg, 0) + 1
    got_views = {"All scripts": len(rows), **per_tag, "Uncategorized": sum(1 for x in rows if not x["tags"])}
    (ctx.out / "read-back-diff.json").write_text(json.dumps(
        {"rows": len(rows), "want_rows": want_rows, "views": got_views, "want_views": views, "metas": len(metas),
         "meta_bad": meta_bad, "field_diffs": len(diffs), "diffs": diffs[:200]}, ensure_ascii=False, indent=1))
    ctx.check(READ_BACK, not diffs and not meta_bad and len(loose_rows) == loose and len(rows) == want_rows
              and got_views == views, rows=len(rows), want_rows=want_rows, field_diffs=len(diffs),
              first_diffs=diffs[:3], loose=len(loose_rows), metas=len(metas), meta_bad=meta_bad[:5],
              views=got_views)
    p95_serial = pct(serial)
    budget = LIST_P95_MS[ctx.scale]
    ctx.check(LIST_P95, p95_serial is not None and p95_serial <= budget, budget=True, p95_ms=p95_serial, budget_ms=budget, rows=len(rows),
              reads=SERIAL_READS)

    # 3. --users owners read the whole list at once.
    clients = [ctx.owner.share(limits=2) for _ in range(ctx.users)]
    lat: list[float] = []
    seen: list[tuple[int, int]] = []

    async def reader(h) -> None:
        for _ in range(READS_PER_USER):
            t0 = time.perf_counter()
            r = await h.get(LIST, params={"account_id": aid})
            lat.append((time.perf_counter() - t0) * 1000)
            seen.append((r.status_code, len(r.json().get("list", [])) if r.status_code == 200 else -1))

    try:
        await asyncio.gather(*(reader(h) for h in clients))
    finally:
        await asyncio.gather(*(h.aclose() for h in clients))
    p95_load = pct(lat)
    ctx.check(LIST_LOAD, len(seen) == ctx.users * READS_PER_USER and all(s == (200, len(rows)) for s in seen),
              users=ctx.users, reads=len(seen), wrong=[s for s in seen if s != (200, len(rows))][:5],
              p95_ms=p95_load)
    ctx.metric("p95_vs_last_green", {"GET saved-replies serial": p95_serial,
                                     f"GET saved-replies x{ctx.users}": p95_load})
    ctx.metric("scripts_library", {"rows": len(rows), "sequences": n, "import_s": import_s,
                                   "list_bytes": len(json.dumps(body))})

    # 4. Share-to-all + the all-models overview (API; the library lives only on `aid` so far).
    ov = await _share_and_overview(ctx, aid, accounts, by_seq, metas, len(rows))

    if not ctx.app:
        for c in (UI_SIDEBAR, UI_STEPS, UI_EXPAND, UI_TAGS, UI_ALL_MODELS, UI_SEND):
            ctx.skip(c, "--no-ui")
        return
    # Synthetic: the deep sequence's cards; a real dump: every sequence's.
    await _ui_page(ctx, seqs, seqs if real else [seqs[n // 2]], truth, {k: len(v) for k, v in by_seq.items()}, views,
                   accounts, ov, bool(real))
    fans = [t["fan_id"] for t in w.data["threads"] if str(t["account_id"]) == aid]
    await _ui_send(ctx, aid, fans[0] if fans else None, seqs[0], by_seq)


COPY = f"{LIST}/copy"
OVERVIEW = f"{LIST}/overview"


async def _coverage(client, aid: str) -> tuple[dict[str, int], dict[str, int]]:
    """A Creator's own coverage straight off GET /admin/saved-replies: {sequence script_id: step rows} and
    {tag: scripts carrying it} — the lean overview's counts worked out independently (the library is FM-free, so
    every row counts, matching the endpoint's FM filter)."""
    rows = (await client.get(LIST, params={"account_id": aid})).json().get("list", [])
    seqs: dict[str, int] = {}
    tags: dict[str, int] = {}
    for x in rows:
        if x.get("script_id"):
            seqs[x["script_id"]] = seqs.get(x["script_id"], 0) + 1
        for t in x.get("tags") or []:
            tags[t] = tags.get(t, 0) + 1
    return seqs, tags


def _expect(roster: list[str], cov: dict[str, tuple[dict[str, int], dict[str, int]]]) -> tuple[dict, dict]:
    """The overview's expected per-account maps (name -> {account: count}) from each Creator's own coverage."""
    seqs: dict[str, dict[str, int]] = {}
    tags: dict[str, dict[str, int]] = {}
    for t in roster:
        sq, tg = cov[t]
        for name, c in sq.items():
            seqs.setdefault(name, {})[t] = c
        for name, c in tg.items():
            tags.setdefault(name, {})[t] = c
    return seqs, tags


async def _share_and_overview(ctx, aid: str, accounts: list[dict], by_seq: dict[str, list[dict]],
                              src_metas: dict[str, dict], src_rows: int) -> dict:
    """SHARE_ALL, ALL_MODELS_VIEW, SHARE_ALL_NOOP -> the overview as last read (UI_ALL_MODELS's expectation)."""
    roster = [str(a["id"]) for a in accounts]
    others = [t for t in roster if t != aid]
    # A shared sequence arrives whole: every row, a step's "N.M" options included (they share a `script_step`), so
    # the coverage is the source's row count per sequence.
    aid_seqs = {k: len(v) for k, v in by_seq.items()}
    aid_tags = (await _coverage(ctx.owner, aid))[1]

    # SHARE_ALL: resolve the roster server-side (to=[] with all_creators) and copy to every other Creator.
    share = (await ctx.owner.post(COPY, json={"from_account_ids": [aid], "all_creators": True})).json()
    keys_ok = set(share) == {"copied", "skipped", "media_dropped"}
    cov = {t: await _coverage(ctx.owner, t) for t in roster}
    # Every other Creator now holds at least the source's coverage (they began without these run-unique names).
    spread_bad = [t for t in others
                  if any(cov[t][0].get(nm, 0) < c for nm, c in aid_seqs.items())
                  or any(cov[t][1].get(nm, 0) < c for nm, c in aid_tags.items())]
    # A new sequence's header rode along: a sampled sequence's meta on an other Creator == the source's.
    sample = next(iter(aid_seqs), None)
    src_meta = src_metas.get(sample) if sample else None
    meta_ok = False
    if sample and src_meta and others:
        tmetas = {m["name"]: m for m in (await ctx.owner.get(
            f"{LIST}/sequences", params={"account_id": others[0]})).json().get("list", [])}
        tm = tmetas.get(sample)
        meta_ok = bool(tm and tm.get("position") == src_meta.get("position")
                       and tm.get("created_by") == src_meta.get("created_by")
                       and tm.get("description") == src_meta.get("description"))
    # The source's stored rows (as read back, FM-free), not the dump's: an import fault is READ_BACK's, not this.
    ctx.check(SHARE_ALL, keys_ok and share.get("copied") == src_rows * len(others) and share.get("skipped") == 0
              and not spread_bad and meta_ok,
              response=share, roster=len(roster), others=len(others), src_rows=src_rows,
              spread_bad=spread_bad[:5], meta_sequence=sample, meta_ok=meta_ok)

    # ALL_MODELS_VIEW: the lean overview == an independent per-account read-back over the whole roster.
    exp_seq, exp_tag = _expect(roster, cov)
    ov = (await ctx.owner.get(OVERVIEW)).json()
    ov_acc = {a["id"] for a in ov.get("accounts", [])}
    ov_seq = {s["name"]: s["per_account"] for s in ov.get("sequences", [])}
    ov_tag = {s["name"]: s["per_account"] for s in ov.get("tags", [])}
    ctx.check(ALL_MODELS_VIEW, ov_acc == set(roster) and ov_seq == exp_seq and ov_tag == exp_tag,
              accounts=len(ov_acc), roster=len(roster),
              missing_accounts=sorted(set(roster) - ov_acc), extra_accounts=sorted(ov_acc - set(roster)),
              seq_match=ov_seq == exp_seq, tag_match=ov_tag == exp_tag, sequences=len(ov_seq), tags=len(ov_tag))

    # SHARE_ALL_NOOP: a second identical share copies nothing and leaves the overview unchanged.
    reshare = (await ctx.owner.post(COPY, json={"from_account_ids": [aid], "all_creators": True})).json()
    ov2 = (await ctx.owner.get(OVERVIEW)).json()
    ov2_seq = {s["name"]: s["per_account"] for s in ov2.get("sequences", [])}
    ctx.check(SHARE_ALL_NOOP, reshare.get("copied") == 0 and ov2_seq == ov_seq,
              response=reshare, coverage_unchanged=ov2_seq == ov_seq)
    return ov2


_SIDEBAR = """(label) => { const a = document.querySelector(`aside[aria-label="${label}"]`);
  if (!a) return null;
  const items = [...a.querySelectorAll('li div[role="button"]')].map((e) => ({
    name: e.querySelector('span.truncate')?.textContent,
    count: Number((e.querySelector('div.text-xs')?.textContent || '').split(' ')[0]) }));
  const more = [...a.querySelectorAll('button')].map((b) => b.textContent.match(/^Show more \\((\\d+)\\)$/))
    .find(Boolean);
  return { items, more: more ? Number(more[1]) : 0 }; }"""
_CARDS = r"""() => [...document.querySelectorAll('[aria-label^="Step "]')].map((e) => { const li = e.closest('li');
  return { label: e.textContent.trim(), name: li.querySelector('div.mb-0\\.5')?.textContent ?? null,
    text: (li.querySelector('p')?.textContent ?? '').replace(/\s+/g, ' ').trim(),
    notes: li.querySelector('[aria-label="Internal notes"]')?.getAttribute('title') ?? null }; })"""


def _cards_want(q: dict, truth: dict) -> list[dict]:
    return [{"label": s["step"], "name": truth[(q["name"].strip(), s["step"])][0] or None,
             "text": " ".join(s["text"].split()), "notes": (s.get("notes") or "").strip() or None}
            for s in sorted(q["steps"], key=lambda s: _order(s["step"]))]


async def _open_sequence(page, q: dict, want: list[dict]) -> tuple[list[dict], list[str]]:
    """Open `q` from the sidebar (searched by name, the exact row clicked): its cards and the header lines shown."""
    name = q["name"].strip()
    await page.get_by_label("Search sequences").fill(name)
    row = page.locator('aside[aria-label="Sequences"] li div[role="button"]').filter(
        has=page.locator("span.truncate", has_text=re.compile(f"^{re.escape(name)}$")))
    await row.first.click()
    await page.wait_for_function(f"([k, n]) => {{ const c = ({_CARDS})(); return c.length === k && c[0].name === n; }}",
                                 arg=[len(want), want[0]["name"]], timeout=30_000)
    header = [t for t in (f"Created by：{q['created_by'].strip()}", f"Created on：{q['created_on']}")
              if await page.get_by_text(t, exact=True).count()]
    return await page.evaluate(_CARDS), header


_ARROWS = r"""() => [...document.querySelectorAll('[aria-label^="Step "]')].map((e) => { const li = e.closest('li');
  const p = li.querySelector('p');
  return { label: e.textContent.trim(), cut: p.scrollHeight > p.clientHeight + 1, clamped: p.classList.contains('line-clamp-2'),
    h: p.clientHeight, arrow: li.querySelector('button[aria-label="Expand script"], button[aria-label="Collapse script"]')
      ?.getAttribute('aria-label') ?? null }; })"""


async def _ui_expand(ctx, page, long: set[str] | None) -> None:
    """The open sequence's arrows (#42): one iff the clamp cuts text; `long` (synthetic) are steps that must have one,
    and some card must have none (so a dead arrow on every card is red).
    The first arrow clicked lifts its clamp and reads "Collapse script"."""
    got: list[dict] = []
    after: dict = {}
    try:
        got = await page.evaluate(_ARROWS)
        first = next((c for c in got if c["arrow"]), None)
        if first:
            card = page.locator("li").filter(has=page.get_by_label(f"Step {first['label']}", exact=True))
            await card.scroll_into_view_if_needed()
            await ui.shot(ctx, page, "scripts-expand-trigger")
            await card.get_by_role("button", name="Expand script").click()
            await card.get_by_role("button", name="Collapse script").wait_for(timeout=10_000)
            after = next(c for c in await page.evaluate(_ARROWS) if c["label"] == first["label"])
            await ui.shot(ctx, page, "scripts-expand-settled")
            await card.get_by_role("button", name="Collapse script").click()
    except Exception as e:  # noqa: BLE001 — the check reports it
        ctx.note(f"expand: {type(e).__name__}: {str(e)[:160]}")
    wrong = [c["label"] for c in got if bool(c["arrow"]) != c["cut"] or c["arrow"] == "Collapse script"]
    arrows = {c["label"] for c in got if c["arrow"]}
    first_h = next((c["h"] for c in got if c["arrow"]), 0)
    opened_ok = bool(after) and not after["clamped"] and after["h"] > first_h
    ctx.check(UI_EXPAND, bool(got) and not wrong and (long is None or (long <= arrows and len(arrows) < len(got))) and (not arrows or opened_ok),
              cards=len(got), arrows=sorted(arrows), want=sorted(long) if long is not None else "cut ones",
              wrong=wrong[:6], opened=after or None)


async def _ui_page(ctx, seqs: list[dict], opened: list[dict], truth: dict, stored: dict[str, int],
                   views: dict[str, int], accounts: list[dict], ov: dict, real: bool = False) -> None:
    n = len(seqs)
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.goto(f"{ctx.app}/growth/scripts", wait_until="domcontentloaded")
        tab = page.get_by_role("tab", name="Sequence")
        side: dict | None = None
        try:
            await tab.wait_for(timeout=60_000)
            await tab.click()
            await page.wait_for_function(f"() => ({_SIDEBAR})('Sequences')?.items.length > 0", timeout=60_000)
            side = await page.evaluate(_SIDEBAR, "Sequences")
        except Exception as e:  # noqa: BLE001 — the check reports it
            ctx.note(f"sidebar: {type(e).__name__}: {str(e)[:160]}")
        await ui.shot(ctx, page, "scripts-sequences-trigger")
        search = page.get_by_label("Search sequences")
        last = seqs[-1]["name"]
        found: list[str] = []
        try:
            await search.fill(last)
            await page.wait_for_function(f"() => ({_SIDEBAR})('Sequences')?.items.length === 1", timeout=15_000)
            found = [i["name"] for i in (await page.evaluate(_SIDEBAR, "Sequences"))["items"]]
        except Exception:  # noqa: BLE001
            pass
        items = side["items"] if side else []
        order_ok = [i["name"] for i in items] == [q["name"].strip() for q in seqs][:len(items)]
        count_bad = [i for i in items if i["count"] != stored.get(i["name"])]
        ctx.check(UI_SIDEBAR, side is not None and len(items) + side["more"] == n and order_ok and not count_bad
                  and found == [last.strip()], sequences=n, rendered=len(items), show_more=side and side["more"],
                  dump_order=order_ok, first=[(i["name"], i["count"]) for i in items[:6]], count_bad=count_bad[:3],
                  search=found)

        # Each opened sequence: its cards (label, name, text, notes) and header == the dump.
        bad: list[dict] = []
        shoot = {0, 5, len(opened) // 2, len(opened) - 1}
        for j, q in enumerate(opened):
            want = _cards_want(q, truth)
            cards: list[dict] = []
            header: list[str] = []
            try:
                cards, header = await _open_sequence(page, q, want)
            except Exception as e:  # noqa: BLE001 — the check reports it
                cards = await page.evaluate(_CARDS)
                ctx.note(f"sequence {q['name']!r}: {type(e).__name__}: {str(e)[:160]}")
            if j in shoot:
                await ui.shot(ctx, page, "scripts-sequence-settled" if len(opened) == 1 else f"scripts-sequence-{j:02d}")
            if cards != want or len(header) != 2:
                diff = next(({"step": w_["label"], "got": c, "want": w_} for c, w_ in zip(cards, want) if c != w_),
                            {"cards": len(cards), "want": len(want)})
                bad.append({"sequence": q["name"], "header": header, **diff})
        ctx.check(UI_STEPS, not bad, sequences=len(opened), cards=sum(len(q["steps"]) for q in opened),
                  bad=len(bad), first_bad=bad[:2])
        await _ui_expand(ctx, page, None if real else {str(k) for k in LONG})

        tag_counts: dict = {}
        hit = 0
        probe = " ".join(next(s for s in seqs[-1]["steps"] if s["step"] == "1")["text"].split())[:40]
        try:
            await page.get_by_role("tab", name="Tag").click()
            await page.get_by_label("Search tags").fill("")  # the sidebar search carries over from Sequence
            await page.wait_for_function(f"() => ({_SIDEBAR})('Tags')?.items.length >= 3", timeout=30_000)
            tag_counts = {i["name"]: i["count"] for i in (await page.evaluate(_SIDEBAR, "Tags"))["items"]}
            await page.get_by_role("button", name="Search", exact=True).click()
            await page.get_by_label("Search scripts").fill(probe)
            await page.wait_for_function("(t) => [...document.querySelectorAll('li p')].some((p) => "
                                         "p.textContent.replace(/\\s+/g, ' ').includes(t))", arg=probe, timeout=15_000)
            hit = await page.evaluate("(t) => [...document.querySelectorAll('li p')].filter((p) => "
                                      "p.textContent.replace(/\\s+/g, ' ').includes(t)).length", probe)
        except Exception as e:  # noqa: BLE001
            ctx.note(f"tag tab: {type(e).__name__}: {str(e)[:160]}")
        await ui.shot(ctx, page, "scripts-tags-settled")
        ctx.check(UI_TAGS, tag_counts == views and hit >= 1, got=tag_counts, want=views, search=probe,
                  search_hits=hit)
        await _ui_all_models(ctx, page, accounts, ov)


# The header's write actions, hidden while All models is on: (role, accessible name). Shown on a Creator first;
# the menu items only exist with More open.
HEADER_WRITES = (("button", "Learn"), ("button", "Share"), ("button", "More"))
MORE_ITEMS = ("Add script", "Create new", "Add tag", "From Excel", "From other creators")
_MATRIX = r"""() => { const t = document.querySelector('table'); if (!t) return null;
  const cols = [...t.querySelectorAll('thead th')].slice(1, -1).map((th) => th.getAttribute('title'));
  const rows = [...t.querySelectorAll('tbody tr')].map((tr) => { const td = [...tr.children];
    return { name: td[0].getAttribute('title'), cells: td.slice(1, -1).map((c) =>
      c.querySelector('[aria-label="missing"]') ? 0 : Number(c.textContent.trim())) }; });
  const more = [...document.querySelectorAll('button')].map((b) => b.textContent.match(/^Show more \((\d+)\)$/))
    .find(Boolean);
  const head = [...document.querySelectorAll('span')].map((s) => s.textContent).find((x) => / creators · /.test(x));
  return { cols, rows, more: more ? Number(more[1]) : 0, head: head ?? null }; }"""


async def _present(page) -> dict[str, int]:
    """How many of each header write action the page shows (the More menu's items as menuitems)."""
    got = {name: await page.get_by_role(role, name=name, exact=True).count() for role, name in HEADER_WRITES}
    for name in MORE_ITEMS:
        got[name] = await page.get_by_role("menuitem", name=name, exact=True).count()
    return got


async def _ui_all_models(ctx, page, accounts: list[dict], ov: dict) -> None:
    """UI_ALL_MODELS: the Creator column's All models pick -> the matrix == the overview, no write action, no write."""
    roster = [str(a["id"]) for a in accounts]
    rows_of = {t: len((await ctx.owner.get(LIST, params={"account_id": t})).json().get("list", [])) for t in roster}
    cols = [str(a["id"]) for a in ov.get("accounts", [])]
    # A column's title is creatorName: nickname, else name, else id (roster meta first, then the overview's own).
    meta = {str(a["id"]): a for a in accounts}
    names_ok = lambda i, title: title in {meta.get(cols[i], {}).get("nickname"), meta.get(cols[i], {}).get("name"),  # noqa: E731
                                          (ov["accounts"][i] or {}).get("nickname"), cols[i]} - {None, ""}
    before: dict[str, int] = {}
    got: dict[str, dict] = {}
    after: dict[str, int] = {}
    err = None
    try:
        # On a Creator the actions are there (so their absence below is not vacuous): More opened for its items.
        await page.get_by_role("button", name="More", exact=True).click()
        await page.get_by_role("menuitem", name="Add script", exact=True).wait_for(timeout=10_000)
        before = await _present(page)
        await page.keyboard.press("Escape")
        col = page.locator('aside[aria-label="Creators"]')
        await col.locator("button[aria-expanded]", has_text="All models").click()  # the menu, not Collapse
        pick = col.locator("button:not([aria-expanded])", has_text=re.compile(r"^All models$"))
        await pick.wait_for(timeout=10_000)
        await ui.shot(ctx, page, "scripts-all-models-trigger")
        await pick.click()
        for kind, label in (("sequences", "Sequence"), ("tags", "Tag")):
            want = ov.get(kind, [])
            await page.get_by_role("tab", name=label, exact=True).click()
            await page.wait_for_function(
                f"([n, h]) => {{ const m = ({_MATRIX})(); return !!m && m.head === h && m.rows.length + m.more === n; }}",
                arg=[len(want), f"{len(cols)} creators · {len(want)} {kind}"], timeout=30_000)
            got[kind] = await page.evaluate(_MATRIX)
        after = await _present(page)
        await page.get_by_role("tab", name="Sequence", exact=True).click()
        await page.wait_for_function(f"() => ({_MATRIX})()?.head?.endsWith(' sequences')", timeout=10_000)
    except Exception as e:  # noqa: BLE001 — the check reports it
        err = f"{type(e).__name__}: {str(e)[:160]}"
    await ui.shot(ctx, page, "scripts-all-models-settled")
    bad: list[dict] = []
    for kind in ("sequences", "tags"):
        m = got.get(kind) or {"cols": [], "rows": [], "more": -1}
        want = ov.get(kind, [])
        if len(m["cols"]) != len(cols) or not all(names_ok(i, c) for i, c in enumerate(m["cols"])):
            bad.append({"kind": kind, "cols": m["cols"]})
        if len(m["rows"]) + m["more"] != len(want):
            bad.append({"kind": kind, "rows": len(m["rows"]), "more": m["more"], "want": len(want)})
        for r, w_ in zip(m["rows"], want):
            exp = [w_["per_account"].get(c, 0) for c in cols]
            if r["name"] != w_["name"] or r["cells"] != exp:
                bad.append({"kind": kind, "got": r, "want": {"name": w_["name"], "cells": exp}})
    rows_after = {t: len((await ctx.owner.get(LIST, params={"account_id": t})).json().get("list", [])) for t in roster}
    shown = {k: v for k, v in after.items() if v}
    ctx.check(UI_ALL_MODELS, bool(err is None and set(cols) == set(roster) and len(cols) == len(roster) and not bad
                                  and before and all(before.values()) and not shown and rows_after == rows_of),
              roster=len(roster), columns=len(cols), sequences=len(ov.get("sequences", [])),
              tags=len(ov.get("tags", [])), rendered={k: len(v["rows"]) for k, v in got.items()},
              bad=len(bad), first_bad=bad[:3], actions_on_creator=before, actions_on_all_models=after,
              rows_unchanged=rows_after == rows_of, rows=sum(rows_of.values()), error=err)


async def _ui_send(ctx, aid: str, fan, q: dict, by_seq: dict[str, list[dict]]) -> None:
    if fan is None:
        ctx.check(UI_SEND, False, reason=f"no thread on Creator {aid}")
        return
    step1 = next(s for s in q["steps"] if s["step"] == "1")
    key = " ".join(step1["text"].split())[:30]  # the picker search, and the hit's visible start
    row = next((x for x in by_seq.get(q["name"].strip(), []) if x["script_step"] == 1), None)
    status, bubble, err = None, False, None
    want = f"Next in “{q['name'].strip()}” · step 2"
    async with ui.owner_browser(ctx, viewport=VIEWPORT, send=True) as page:
        await page.add_init_script(f"try {{ localStorage.setItem('of-owner:{aid}', '{int(aid)}'); }} catch (e) {{}}")
        await page.goto(f"{ctx.app}/messages-pro/{aid}/{fan}", wait_until="domcontentloaded")
        try:
            composer = page.get_by_placeholder('Press "/" + keyword').first
            await composer.wait_for(timeout=60_000)
            await page.get_by_title("Insert saved template").first.click()
            await page.get_by_placeholder("Search templates…").fill(key)
            hit = page.get_by_text(key).first
            await hit.wait_for(timeout=30_000)
            await ui.shot(ctx, page, "chat-picker-trigger")
            await hit.click()
            await page.wait_for_function("(t) => [...document.querySelectorAll('textarea')]"
                                         ".some((e) => e.value.includes(t))", arg=key, timeout=15_000)
            await composer.focus()
            async with page.expect_response(lambda r: r.request.method == "POST" and bool(
                    ui.SEND_PATH.fullmatch(urlsplit(r.url).path)), timeout=30_000) as info:
                await page.keyboard.press("Enter")
            status = (await info.value).status
            await page.get_by_text(want).first.wait_for(timeout=30_000)
            bubble = True
        except Exception as e:  # noqa: BLE001 — the check reports it
            err = f"{type(e).__name__}: {str(e)[:160]}"
        await page.wait_for_timeout(500)
        await ui.shot(ctx, page, "chat-next-step-settled")
    sent = None
    for _ in range(30):
        rows = (await ctx.owner.get(LIST, params={"account_id": aid})).json().get("list", [])
        sent = next((x["sent_count"] for x in rows if row and x["id"] == row["id"]), None)
        if sent:
            break
        await asyncio.sleep(0.5)
    ctx.check(UI_SEND, status is not None and status < 300 and bubble and sent == 1, sequence=q["name"], fan=fan,
              send_status=status, bubble=bubble, want=want, sent_count=sent, row=row and row["id"], error=err)
