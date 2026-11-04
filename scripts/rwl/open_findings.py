#!/usr/bin/env python3
r"""Collect "Open findings" bullets from PR bodies into one triage table.

Section rule: a section starts at a line matching
    ^\s*(#{1,6}\s*|\*\*)?\s*open findings      (case-insensitive)
and ends at the next markdown heading (^#{1,6}\s), a bold-only line
(^\*\*[^*]+\*\*\s*$) or a line starting with the robot emoji.  Every body
section counts.  Only top-level list lines (^([-*]|\d+[.)]) ) are findings;
indented / continuation lines belong to the parent bullet (used for tags and
flags, not for the row text).

Tags: backticked paths tracked by git (or re-pointed by unique basename);
non-proposal backticked distinctive symbols (see "gone") with a DEF in exactly
one tracked file (for `mod.sym` that file's stem must be mod); un-backticked
code paths (tag only, never "gone"); else "?".
Flags (human confirms): "gone" = the bullet names something missing (a
backticked code path absent even by basename, or a distinctive identifier:
>=6 chars, snake/camel case, not ALL_CAPS, that `git grep -wF` finds in no code
file on HEAD) not introduced as a proposal ("a/new/shared/no/needs/e.g./would `x`"),
AND nothing it names resolves or tags.
"fixed #N" = PR #N (head matches --fix-heads, default = --heads) has a line, outside its own
findings sections, citing "#<pr>" plus the id "<pr>.<n>", "open finding <n>",
the bullet's leading label (F3, O1, P-1...) or a decision id Q1-Q10/O1-O4 the
bullet names (same-line "#<pr>" keeps O1 from matching every PR's O1).
Rows with the same non-"?" tags and token Jaccard >= 0.8 merge into the
earliest one; the rest are listed in "dups".  Closed-unmerged PRs are skipped.
Usage: open_findings.py --counts | --tsv | --selftest  [--prs A[-B]|none] [--heads RE] [--fix-heads RE]
W25 (heads only): open_findings.py --counts --prs none --heads '^rwl/W(19|2[0-5])-'
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 400  # gh pr list --limit; hitting it = truncated list = hard error
START = re.compile(r"^\s*(#{1,6}\s*|\*\*)?\s*open findings", re.I)
END = re.compile("^(#{1,6}\\s|\\*\\*[^*]+\\*\\*\\s*$|\U0001F916)")
BULLET = re.compile(r"^([-*]|\d+[.)]) ")
TICKS = re.compile(r"`([^`\n]+)`")
CODE = ("tsx", "ts", "jsx", "js", "cjs", "mjs", "py", "sh")
EXT = "|".join(CODE)
CODE_SPEC = [f"*.{e}" for e in CODE] + [":!slop/evidence", ":!docs/open-findings-triage*.md"]  # git grep: code only
PATH = re.compile(rf"^([\w.@/-]+\.(?:{EXT}|md|json|sql|css|ya?ml|toml|html))(?::\d+(?:-\d+)?)?$")
BARE = re.compile(rf"(?<![\w/.-])([\w./-]+\.(?:{EXT}))\b")
SYMBOL = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\(\))?$")
PROPOSAL = re.compile(r"\b(a|an|one|new|own|shared|e\.g\.|follow-up:?|renamed? to|needs|no|would|could|become)\W*$", re.I)
LABEL = r"[A-Z]{1,2}-?\d+[a-z]?"
DECISION = re.compile(r"\b(Q(?:10|[1-9])|O[1-4])\b")
# POSIX ERE (git grep -E) + Python re; name = last word; `export`/`async` prefixes need no pattern
DEF = r"(def|class|function|const|let|type|interface) +[A-Za-z_][A-Za-z0-9_]*"
COMMON = {"return", "import", "default", "string", "number", "object", "boolean",
          "undefined", "function", "promise", "status", "false", "true"}
W09_18 = r"^rwl/W(09|1[0-8])-"     # --counts reference split inside the --prs range
HEADS = r"^rwl/W(19|2[0-3])-"      # default --heads (selected beyond --prs) and --fix-heads


# ---------- parsing (pure) ----------
def _walk(body):
    """Yield (line, in_section) with the section rule applied."""
    inside = False
    for line in (body or "").splitlines():
        if START.match(line):
            inside = True
            yield line, False
            continue
        if inside and END.match(line):
            inside = False
        yield line, inside


def bullets(body):
    """Return list of findings; each is the list of its lines (first = bullet)."""
    out, cur = [], None
    for line, inside in _walk(body):
        if not inside:
            cur = None
        elif BULLET.match(line):
            cur = [line]
            out.append(cur)
        elif cur is not None and line.strip():
            cur.append(line)
    return out


def strip_md(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", BULLET.sub("", s.strip(), count=1))  # [text](url) -> text
    return re.sub(r"\s+", " ", s.replace("**", "").replace("`", "")).strip()


def normalise(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def jaccard(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a | b else 1.0


def dedupe(rows):
    """rows earliest-first; returns new rows with 'dups' and merged status (inputs untouched)."""
    kept = []  # (normalised text, row copy)
    for r in rows:
        norm = normalise(r["text"])
        k = next((row for kn, row in kept if r["tags"] and row["tags"] == r["tags"] and jaccard(kn, norm) >= 0.8), None)
        if k is None:
            kept.append((norm, dict(r, dups=[])))
        else:
            k["dups"].append(r["id"])
            k["status"] = sorted(set(k["status"]) | set(r["status"]))
    return [k for _, k in kept]


def is_distinctive(sym):
    return (len(sym) >= 6 and sym.lower() not in COMMON and not sym.isupper()
            and ("_" in sym.strip("_") or re.search(r"[a-z][A-Z]", sym) is not None))


def norm_label(s):  # P-1 == P1
    return s.replace("-", "")


def labels(text):
    """Bullet's leading label (F3, O1, N2, W1...) plus any decision ids it names."""
    lead = re.match(rf"\W*({LABEL})\b", strip_md(text))
    return ({norm_label(lead.group(1))} if lead else set()) | set(DECISION.findall(text))


def citing(fix_bodies):
    """fix_bodies: [(number, body)] -> {pr: [(fix number, line)]} for lines outside the fix
    PR's own findings sections that cite "#<pr>" (never itself)."""
    out = {}
    for num, body in fix_bodies:
        for line, inside in _walk(body):
            if not inside:
                for pr in set(map(int, re.findall(r"#(\d+)\b", line))) - {num}:
                    out.setdefault(pr, []).append((num, line))
    return out


def fixed_by(pr, n, text, cites):
    """Fix PRs whose "#<pr>" line also cites the id "<pr>.<n>", "open finding <n>" or a label."""
    want = labels(text)
    return sorted({num for num, line in cites.get(pr, ())
                   if re.search(rf"(?<![\d.]){pr}\.{n}(?!\d)", line)
                   or want & {norm_label(x) for x in re.findall(rf"\b{LABEL}\b", line)}
                   or re.search(rf"open findings?\s+{n}\b", line, re.I)})


class Index(NamedTuple):
    files: set     # tracked files
    by_base: dict  # basename -> files
    defs: dict     # defined name -> files


def make_index(files, grep_out):
    """grep_out: `git grep -o DEF` lines "HEAD:path:match"."""
    by_base, defs = {}, {}
    for f in files:
        by_base.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    for line in grep_out.splitlines():
        _, path, match = line.split(":", 2)
        defs.setdefault(match.split()[-1], set()).add(path)
    return Index(files, by_base, defs)


def resolve_path(v, idx):
    """-> (tracked file, else the unique file with that basename, else None; basename tracked)."""
    v = v.removeprefix("./")
    base = v.rsplit("/", 1)[-1]
    hits = [v] if v in idx.files else idx.by_base.get(base, [])
    return (hits[0] if len(hits) == 1 else None), base in idx.by_base


def spans(full_text):
    """Yield (kind, value, mod, proposed) per backticked path ('path') or identifier ('sym');
    mod = the part before the last dot of `mod.sym`, else None."""
    for m in TICKS.finditer(full_text):
        span = m.group(1).strip()
        proposed = bool(PROPOSAL.search(full_text[max(0, m.start() - 30):m.start()]))
        if p := PATH.match(span):
            yield "path", p.group(1), None, proposed
        elif SYMBOL.match(span):
            *mods, sym = span.removesuffix("()").split(".")
            yield "sym", sym, (mods[-1] if mods else None), proposed


def tag_and_gone(full_text, seen, idx):
    """-> (frozenset of tag files, gone flag); one (tag, missing, alive) per thing named.
    seen: distinctive undefined symbols that exist somewhere on HEAD."""
    rs = []
    for kind, v, mod, proposed in spans(full_text):
        if kind == "path":
            tag, known = resolve_path(v, idx)
            rs.append((tag, not known and not proposed, known))
            continue
        hits, dist = sorted(idx.defs.get(v, ())), is_distinctive(v)
        ok = (len(hits) == 1 and dist and not proposed
              and (mod is None or hits[0].rsplit("/", 1)[-1].split(".")[0] == mod))
        rs.append((hits[0] if ok else None, dist and not hits and v not in seen and not proposed,
                   dist and (bool(hits) or v in seen)))
    rs += [(resolve_path(v, idx)[0], False, False)  # un-backticked code paths: tags only
           for v in BARE.findall(TICKS.sub(" ", full_text))]
    tags = frozenset(t for t, _, _ in rs if t)
    return tags, any(m for _, m, _ in rs) and not any(a for _, _, a in rs) and not tags


# ---------- git / gh ----------
def git(*args):
    """git in the repo root (any cwd); rc 1 from grep = no match, anything else non-zero = error."""
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if r.returncode and not (r.returncode == 1 and args[0] == "grep"):
        raise SystemExit(f"git {args[0]} failed (rc {r.returncode}): {r.stderr.strip()}")
    return r.stdout


def present(syms):
    """Subset of syms that occur as a whole word in a code file on HEAD (one git grep)."""
    if not syms:
        return set()
    args = [x for s in sorted(syms) for x in ("-e", s)]
    return set(git("grep", "-IhowF", *args, "HEAD", "--", *CODE_SPEC).split())


def load(json_file, lo):
    """All PRs except closed-unmerged ones; lo None (--prs none) skips the range check."""
    if json_file:
        with open(json_file) as f:
            prs = json.load(f)
    else:
        prs = json.loads(subprocess.run(["gh", "pr", "list", "--state", "all", "--limit", str(LIMIT), "--json",
                                         "number,headRefName,body,state,mergeCommit"], capture_output=True,
                                        text=True, check=True, cwd=ROOT).stdout)
        if len(prs) >= LIMIT:
            raise SystemExit(f"gh returned {len(prs)} PRs = --limit {LIMIT}: list may be truncated; raise LIMIT")
    if lo is not None and (not prs or min(p["number"] for p in prs) > lo):
        raise SystemExit(f"PR list does not reach #{lo}: truncated")
    return [p for p in prs if p.get("state") != "CLOSED"]  # gh: OPEN / MERGED / CLOSED (= not merged)


# ---------- pipeline ----------
def build(prs, lo, hi, heads, fix_heads):
    idx = make_index(set(git("ls-files").splitlines()) - {""}, git("grep", "-IowE", DEF, "HEAD", "--", *CODE_SPEC))
    sel = [(p, bullets(p["body"])) for p in sorted(prs, key=lambda p: p["number"])
           if (lo is not None and lo <= p["number"] <= hi) or re.search(heads, p["headRefName"])]
    cites = citing((p["number"], p["body"] or "") for p in prs if re.search(fix_heads, p["headRefName"]))
    cands = {v for _, found in sel for lines in found for k, v, _, _ in spans("\n".join(lines))
             if k == "sym" and is_distinctive(v) and v not in idx.defs}
    seen = present(cands)
    rows = []
    for p, found in sel:
        for n, lines in enumerate(found, 1):
            full = "\n".join(lines)
            tags, gone = tag_and_gone(full, seen, idx)
            status = (["gone"] if gone else []) + [f"fixed #{f}" for f in fixed_by(p["number"], n, full, cites)]
            rows.append(dict(id=f"{p['number']}.{n}", pr=p["number"], head=p["headRefName"],
                             text=strip_md(lines[0]), tags=tags, status=status))
    return [(p["number"], p["headRefName"], len(found)) for p, found in sel], rows


def print_counts(per_pr, rows, kept, lo, hi, heads):
    """Each selected PR lands in exactly one bucket: --heads match, else W09-W18 split / other."""
    w0918, other, hd = f"#{lo}-#{hi} W09-W18 heads", f"#{lo}-#{hi} other", f"heads {heads}"
    buckets = dict.fromkeys([w0918, other, hd] if lo is not None else [hd], 0)
    for num, head, raw in per_pr:
        print(f"#{num} {head} {raw}")
        buckets[hd if re.search(heads, head) else w0918 if re.search(W09_18, head) else other] += raw
    print("---")
    for name, n in {**buckets, "total raw": len(rows), "after dedupe": f"{len(kept)} ({len(rows) - len(kept)} merged)",
                    "flagged gone": sum("gone" in r["status"] for r in kept),
                    "flagged fixed": sum(any(s.startswith("fixed") for s in r["status"]) for r in kept),
                    "? tags": sum(not r["tags"] for r in kept)}.items():
        print(f"{name + ':':<34}{n}")


def print_tsv(kept):
    print("id\tpr\thead\ttags\tstatus\tdups\ttext")
    for r in kept:
        cells = [r["id"], r["pr"], r["head"], ",".join(sorted(r["tags"])) or "?",
                 ",".join(r["status"]), ",".join(r["dups"]), r["text"]]
        print("\t".join(re.sub(r"[\t\r\n]+", " ", str(c)) for c in cells))


# ---------- selftest (no gh/git) ----------
def selftest():
    cases = [("## heading", "## Open findings\n- a\n- b\n  - nested\n  cont\n", 2),
             ("bold heading", "**Open findings**\n- a\n* b\n", 2), ("no section", "## Fixes\n- a\n", 0),
             ("numbered", "### Open findings (3)\n1. a\n2) b\n10. c\n", 3),
             ("ended by heading", "## Open findings\n- a\n## Next\n- x\n", 1),
             ("ended by bold-only", "Open findings:\n- a\n**Evidence**\n- x\n", 1),
             ("ended by robot", "## Open findings\n- a\n\U0001F916 Generated\n- x\n", 1),
             ("two sections", "## Open findings\n- a\n## X\n- y\n**Open findings (2)**\n- b\n", 2)]
    fails = [name for name, body, want in cases if len(bullets(body)) != want]
    row = lambda i, text, tags, status=(): dict(id=i, text=text, tags=frozenset(tags), status=list(status))
    rows = [row("1.1", "cache key misses tenant id", {"a.py"}), row("2.1", "Cache key misses `tenant` id!", {"a.py"}, ["gone"]),
            row("3.1", "cache key misses tenant id", {"b.py"}), row("4.1", "same", ()), row("5.1", "same", ())]
    kept = dedupe(rows)
    fix = citing([(170, "closes #40 item 40.2"), (171, "Owner decision Q3 (#40)"), (172, "40.21 #40"),
                  (173, "Q3 decided"), (174, "## Open findings\n- Q3 of #40 still open"), (40, "#40 F2")])
    src = ["export function fooBar(x) {", "export default async function bazQux() {",
           "async def run_job(x):", "export type FooT = {", "interface BarI {", "class Baz:"]
    defs = make_index(set(), "\n".join(f"HEAD:s/m.ts:{m.group(0)}" for line in src for m in re.finditer(DEF, line))).defs
    idx = make_index({"service/a_mod.py", "app/x/b.ts", "app/y/b.ts", ".gh/c.py", "x/c.py"},
                     "HEAD:service/a_mod.py:def run_job\nHEAD:app/x/b.ts:const dup_sym\nHEAD:app/y/b.ts:let dup_sym")
    tg = lambda text, seen=(): tag_and_gone(text, set(seen), idx)
    checks = {
        "normalise": normalise("Fix `foo_bar()` -- NOW!") == "fix foo_bar now",
        "strip_md": strip_md("- **x** [link](http://a) `y`") == "x link y",
        "dedupe": ([k["id"] for k in kept] == ["1.1", "3.1", "4.1", "5.1"] and kept[0]["dups"] == ["2.1"]
                   and kept[0]["status"] == ["gone"] and "dups" not in rows[0] and not rows[0]["status"]),
        "fixed_by": fixed_by(40, 2, "F2: see Q3", fix) == [170, 171] and fixed_by(
            40, 2, "- F-2 x", citing([(175, "#40 F2 done"), (176, "#40 Open finding 2")])) == [175, 176],
        "is_distinctive": (is_distinctive("_fleet_resources") and not is_distinctive("MAX_RETRIES")
                           and not is_distinctive("return")),
        "def_index": set(defs) == {"fooBar", "bazQux", "run_job", "FooT", "BarI", "Baz"},
        "proposal": [p for *_, p in spans("add a `new_helper` next to `old_helper`; e.g. `x.py`")] == [True, False, True],
        "resolve_path": [resolve_path(v, idx) for v in ("./service/a_mod.py", "a_mod.py", "b.ts", "gone.py", ".gh/c.py")]
        == [("service/a_mod.py", True), ("service/a_mod.py", True), (None, True), (None, False), (".gh/c.py", True)],
        "mod.sym tag": tg("`a_mod.run_job()`") == ({"service/a_mod.py"}, False) and tg("`other.run_job`") == (set(), False),
        "proposed sym": tg("a `run_job`") == (set(), False) and tg("a `missing_helper`") == (set(), False),
        "gone": (tg("drop `missing_helper` in `gone.py`") == (set(), True)
                 and tg("`missing_helper`", {"missing_helper"}) == (set(), False)
                 and tg("`dup_sym` drops `missing_helper`") == (set(), False)),  # ambiguous def = alive
        "bare path": tg("`missing_helper` near service/a_mod.py") == ({"service/a_mod.py"}, False),
    }
    fails += [name for name, ok in checks.items() if not ok]
    print("selftest:", "FAIL " + ", ".join(fails) if fails else "OK")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    for m in ("--counts", "--tsv", "--selftest"):
        mode.add_argument(m, action="store_true")
    ap.add_argument("--prs", default="38-158", help="A-B, A, or none (heads only)")
    ap.add_argument("--heads", default=HEADS)
    ap.add_argument("--fix-heads", help="default: the --heads value")
    ap.add_argument("--json", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    m = re.fullmatch(r"([1-9]\d*)(?:-([1-9]\d*))?|none", a.prs)
    lo, hi = (int(m[1]), int(m[2] or m[1])) if m and m[1] else (None, None)
    if not m or (lo and hi < lo):
        ap.error(f"--prs {a.prs!r}: want A-B with 1 <= A <= B, A, or none")
    per_pr, rows = build(load(a.json, lo), lo, hi, a.heads, a.fix_heads or a.heads)
    kept = dedupe(rows)
    if a.counts:
        print_counts(per_pr, rows, kept, lo, hi, a.heads)
    else:
        print_tsv(kept)
    return 0


if __name__ == "__main__":
    sys.exit(main())
