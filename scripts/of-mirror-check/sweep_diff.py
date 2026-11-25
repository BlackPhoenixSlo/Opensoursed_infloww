"""Not-yet sweep diff: what changed between two Not-yet sweep files (`dead.py --sweep-out`, or the 2026-11-20 one).

A sweep file is [[page, {"ny": [...], "dis": [...], "ro": [...]}], ...]; the 2026-11-20 file has no `ro`. Per section
(a page's first path part) it prints one {"section", "removed", "added", "kept"} line, each entry [page, list, label]
with list `ny` (the Not-yet title) or `ro` (the Read-only note; compared only where both files list it). `dis` (Empty-form
disables) is not compared. A page in one file only is listed under "pages only in old"/"pages only in new", not diffed.
Labels are compared with every date "Mon D, YYYY" read as "{date}" (dead.py writes it so; the 2026-11-20 file has the
run day).
    --expect-ny-unchanged     fail when a page of OLD is missing from NEW or its `ny` differs (order aside)
    --expect-ro-counts <log>  fail when a page's `ro` length in NEW differs from the `readonly` count dead.py printed
                              for it in the Single-Creator pass (<log>, the same run's output), or the total `ro` is 0
Exit 1 on a failed expect check, after printing the diff and one FAIL line per problem.

    python3 -I scripts/of-mirror-check/sweep_diff.py [--expect-ny-unchanged] [--expect-ro-counts <log>] OLD NEW
"""
import json
import re
import sys
from collections import Counter

DATE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}\b")
LABEL_JS = r"""(e) => {
    const t = (e.getAttribute('aria-label') || e.textContent.trim() || e.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ')
      .replace(/\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}\b/g, '{date}').slice(0, 60);
    const cls = (e.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return t || (cls ? `[${cls}]` : `[${e.tagName}]`);
  }"""


def normal(label):
    """A label with its dates as "{date}" (dead.py's own label does the same)."""
    return DATE.sub("{date}", label)


def _multi_diff(old, new):
    """(removed, added, kept) of two label lists, dates normalised, repeats counted, each in its list's order."""
    old, new = [normal(x) for x in old], [normal(x) for x in new]

    def take(labels, counts):
        out = []
        for label in labels:
            if counts[label] > 0:
                out.append(label)
                counts[label] -= 1
        return out

    o, n = Counter(old), Counter(new)
    return take(old, o - n), take(new, n - o), take(old, o & n)


def sweep_diff(old, new):
    """{section: {"removed", "added", "kept": [[page, list, label]], and "pages only in old"/"new" when any}}."""
    old_d, new_d = dict(old), dict(new)
    out = {}
    for page in [p for p, _ in old] + [p for p, _ in new if p not in old_d]:
        sec = out.setdefault(page.split("/")[0], {"removed": [], "added": [], "kept": []})
        if page not in new_d:
            sec.setdefault("pages only in old", []).append(page)
            continue
        if page not in old_d:
            sec.setdefault("pages only in new", []).append(page)
            continue
        for key in ("ny", "ro"):
            if key not in old_d[page] or key not in new_d[page]:
                continue
            for name, labels in zip(("removed", "added", "kept"), _multi_diff(old_d[page][key], new_d[page][key])):
                sec[name] += [[page, key, label] for label in labels]
    return out


def ny_unchanged(old, new):
    """Problems: a page of OLD missing from NEW, or one whose `ny` labels differ (order aside)."""
    new_d = dict(new)
    problems = []
    for page, v in old:
        if page not in new_d:
            problems.append(f"{page}: not in the new sweep")
            continue
        removed, added, _ = _multi_diff(v["ny"], new_d[page]["ny"])
        if removed or added:
            problems.append(f"{page}: ny removed {removed}, added {added}")
    return problems


def ro_counts(new, log_lines):
    """Problems: a page of NEW whose `ro` length is not the `readonly` count dead.py printed for it (scope model:1), a page
    with no printed count, or a total `ro` of 0."""
    printed = {}
    for line in log_lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("scope") == "model:1" and "page" in row and "readonly" in row:
            printed[row["page"]] = row["readonly"]
    problems = []
    for page, v in new:
        if page not in printed:
            problems.append(f"{page}: no readonly count printed")
        elif len(v["ro"]) != printed[page]:
            problems.append(f"{page}: ro has {len(v['ro'])}, readonly printed {printed[page]}")
    if not sum(len(v["ro"]) for _, v in new):
        problems.append("ro total is 0")
    return problems


def main(argv):
    args = list(argv)
    expect_ny = "--expect-ny-unchanged" in args
    if expect_ny:
        args.remove("--expect-ny-unchanged")
    log = None
    if "--expect-ro-counts" in args:
        i = args.index("--expect-ro-counts")
        log = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    old, new = (json.load(open(f)) for f in args)
    for name, d in sweep_diff(old, new).items():
        print(json.dumps({"section": name, **d}))
    problems = ny_unchanged(old, new) if expect_ny else []
    if log:
        problems += ro_counts(new, open(log).read().splitlines())
    if problems:
        print("FAIL:", *problems, sep="\n  ")
        return 1
    print("sweep diff ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
