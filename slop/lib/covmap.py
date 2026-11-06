"""slop/map.json: what each scenario reaches (README "Which scenarios to run"). `slop/run ... --map`
builds a scenario's entry from its run's coverage data (the relay under coverage.py, the harness
too) and the pages its browsers navigated to; `slop/run --changed` diffs the tree against each
entry's sha and lib/selection.py picks. This module does the git, file and coverage I/O."""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from slop.lib import selection

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "slop" / "map.json"
DIFF_ROOTS = ("service", "slop", "scripts/demo-shots", "app", "deploy/fleet", "desktop")
DIFF = ("--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")
APP_SRC = (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs")


def git(*a: str, check: bool = True) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout


def dirty_for_map() -> str:
    """`git status --porcelain` of what a map entry describes (the map file itself aside)."""
    return git("status", "--porcelain", "--", "service", "slop", "scripts", "app", "deploy/fleet", "desktop",
               ":!slop/map.json").strip()


def load_map() -> dict:
    try:
        doc = json.loads(MAP.read_text())
    except (OSError, ValueError):
        return {"scenarios": {}, "version": 1}
    doc.setdefault("scenarios", {})
    return doc


def dump(doc: dict) -> str:
    """Sorted keys; one line per scenario field and per file's function list."""
    out = ["{", ' "scenarios": {']
    items = sorted(doc.get("scenarios", {}).items())
    for i, (name, e) in enumerate(items):
        out.append(f"  {json.dumps(name)}: {{")
        keys = sorted(e)
        for j, k in enumerate(keys):
            comma = "," if j < len(keys) - 1 else ""
            if k == "py":
                files = sorted(e["py"].items())
                out.append('   "py": {')
                out += [f"    {json.dumps(f)}: {json.dumps(sorted(fs))}{',' if n < len(files) - 1 else ''}"
                        for n, (f, fs) in enumerate(files)]
                out.append("   }" + comma)
            else:
                out.append(f"   {json.dumps(k)}: {json.dumps(e[k])}{comma}")
        out.append("  }" + ("," if i < len(items) - 1 else ""))
    out += [" },", f' "version": {int(doc.get("version", 1))}', "}"]
    return "\n".join(out) + "\n"


def py_reach(cov_dir: Path) -> dict[str, list[str]]:
    """{repo-relative .py: [functions whose body ran]} from every coverage data file in `cov_dir`
    (the relays' and the harness'). A file is listed when any of its lines ran."""
    from coverage import CoverageData
    lines: dict[str, set[int]] = {}
    for f in sorted(cov_dir.glob(".coverage*")):
        d = CoverageData(str(f))
        d.read()
        for path in d.measured_files():
            try:
                rel = Path(path).resolve().relative_to(ROOT).as_posix()
            except ValueError:
                continue
            ls = d.lines(path) or []
            if ls and rel.startswith(selection.PY_ROOTS) and not rel.startswith("slop/evidence/"):
                lines.setdefault(rel, set()).update(ls)
    out = {}
    for rel, ls in sorted(lines.items()):
        try:
            out[rel] = selection.funcs_of_lines((ROOT / rel).read_text(), ls)[0]
        except (OSError, SyntaxError, ValueError):
            out[rel] = []
    return out


def update(name: str, cov_dir: Path, *, sha: str, seconds: float, scale: str, ui: bool, pages: list[str],
           volume: bool, names: set[str], http_pages=(), modules=(), keep_pages: bool = False) -> dict:
    """Replace `name`'s entry, drop entries of scenarios that no longer exist, write the map.
    `http_pages`: app paths actors reached over plain HTTP (in `pages` too). `modules`: repo-relative
    files of the slop modules loaded by then (an earlier scenario in this process may have imported
    them, so their module level ran outside this run's coverage): listed, with no functions, when
    coverage has not. `keep_pages`: a run without its UI keeps the old entry's browser pages."""
    doc = load_map()
    py = py_reach(cov_dir)
    for f in modules:
        py.setdefault(f, [])
    old = doc["scenarios"].get(name) or {}
    http = set(http_pages)
    if keep_pages:
        http |= set(old.get("http_pages", ()))
        pages = set(pages) | set(old.get("pages", ()))
    entry = {"sha": sha, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "seconds": seconds, "scale": scale, "ui": ui, "py": dict(sorted(py.items())),
             "pages": sorted(set(pages) | http), "http_pages": sorted(http), "volume": volume}
    doc["scenarios"][name] = entry
    doc["scenarios"] = {k: v for k, v in doc["scenarios"].items() if k in names}
    doc["version"] = 1
    MAP.write_text(dump(doc))
    return entry


# ---------- --changed inputs ----------

_BLOCK = re.compile(r"^[ \t]*\{?/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\}?[ \t]*$", re.M)
_LINE = re.compile(r"(?<![:\w])//.*$", re.M)
_SPECS = (re.compile(r"""from\s+["']([^"']+)["']"""), re.compile(r"""import\(\s*["']([^"']+)["']\s*\)"""),
          re.compile(r"""require\(\s*["']([^"']+)["']\s*\)"""),
          re.compile(r"""(?<![\w.$])import\s+["']([^"']+)["']"""))  # the last: a side-effect `import "./x.css"`


def _strip(src: str) -> str:
    """app/test-import-graph.ts stripComments: block comments that open a line, trailing //."""
    return _LINE.sub("", _BLOCK.sub(lambda m: re.sub(r"[^\n]", "", m.group(0)), src))


def _resolve(spec: str, from_rel: str, app: Path) -> str | None:
    """test-import-graph.ts resolveSpec, repo-relative; None for a package or a name no file has.
    A `.js`/`.jsx`/`.mjs` specifier also names its TypeScript source (ESM style)."""
    if spec.startswith("@/"):
        base = spec[2:]
    elif spec.startswith(("./", "../")):
        base = os.path.normpath(os.path.join(os.path.dirname(from_rel), spec))
    else:
        return None
    stem, ext = os.path.splitext(base)
    ts = (stem + ".ts", stem + ".tsx") if ext in (".js", ".jsx", ".mjs") else ()
    for cand in (base + ".tsx", base + ".ts", base + ".jsx", base + ".js",
                 f"{base}/index.tsx", f"{base}/index.ts", f"{base}/index.jsx", f"{base}/index.js", base, *ts):
        if (app / cand).is_file():
            return "app/" + cand
    return None


def app_edges(app: Path = ROOT / "app") -> dict[str, list[str]]:
    """{app file: [app files it imports]} over app/ now (node_modules, .next, public aside)."""
    edges: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(app):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "public") and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(APP_SRC):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), app)
            try:
                src = _strip((app / rel).read_text(errors="replace"))
            except OSError:
                continue
            tgts = {t for rx in _SPECS for s in rx.findall(src) if (t := _resolve(s, rel, app))}
            edges["app/" + rel] = sorted(tgts)
    return edges


def _rev(ref: str) -> str | None:
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], cwd=ROOT, capture_output=True,
                       text=True)
    return r.stdout.strip() or None


def base_of(since: str | None) -> tuple[str | None, str]:
    """(base sha, how it was chosen) for --changed: `git merge-base HEAD origin/main` (else `main`) by
    default, `--since=<ref>` when given; (None, "--since=map") diffs each entry against its own sha."""
    if since == "map":
        return None, "--since=map"
    if since:
        sha = _rev(since)
        if not sha:
            raise SystemExit(f"slop: --since={since}: not a commit")
        return sha, f"--since={since}"
    for ref in ("origin/main", "main"):
        if _rev(ref):
            mb = git("merge-base", "HEAD", ref, check=False).strip()
            if mb:
                return mb, f"merge-base with {ref}"
    raise SystemExit("slop: --changed: no origin/main or main to diff against; pass --since=<ref>")


def _diff(base: str) -> tuple[list[str], dict]:
    """(changed files, {file.py: {"hunks", "old" at base, "new" now}}): the tree now (uncommitted and
    staged edits too) against `base`. --no-renames: a rename is its old path deleted (every line
    touched) and its new path added."""
    changed = [f for f in git("diff", "--name-only", "-z", *DIFF, base, "--", *DIFF_ROOTS).split("\0") if f]
    out = {}
    for f, hs in selection.parse_hunks(git("diff", "-U0", *DIFF, base, "--", *DIFF_ROOTS)).items():
        if f.endswith(".py"):
            new = ROOT / f
            out[f] = {"hunks": hs, "old": _show(base, f),
                      "new": new.read_text(errors="replace") if new.is_file() else None}
    return changed, out


def _show(sha: str, f: str) -> str | None:
    r = subprocess.run(["git", "show", f"{sha}:{f}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _names(src: str | None) -> set[str] | None:
    """Qualified function names of `src` (None: no file, or it does not parse)."""
    try:
        return {q for q, *_ in selection.defs(src)} if src is not None else None
    except SyntaxError:
        return None


def gather(doc: dict, since: str | None = None) -> dict:
    """Everything selection.pick needs, keyed by map sha: the diff of the tree now against the base
    (base_of), and per entry sha the function names its files had then ("map_known": a function the
    sweep could not have seen is module level). --since=map: each sha is its own base."""
    shas = sorted({e.get("sha") for e in doc.get("scenarios", {}).values() if e.get("sha")})
    base, how = base_of(since)
    hunks, changed, ages = {}, {}, {}
    shared = _diff(base) if base else None
    for sha in shas:
        if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True).returncode:
            raise SystemExit(f"slop: map sha {sha[:7]} is not in this repo; rebuild: slop/run all --map")
        changed[sha], per = shared or _diff(sha)
        hunks[sha] = {f: ({**fd, "map_known": _names(_show(sha, f))} if base and base != sha else fd)
                      for f, fd in per.items()}
        ages[sha] = int(git("rev-list", "--count", f"{sha}..HEAD").strip() or 0)
    untracked = [f for f in git("ls-files", "-z", "--others", "--exclude-standard", "--", *DIFF_ROOTS).split("\0") if f]
    deleted = {f for fs in changed.values() for f in fs if not (ROOT / f).exists()}
    return {"hunks": hunks, "changed": changed, "untracked": untracked, "map_age": ages, "app_edges": app_edges(),
            "deleted": deleted, "base": base, "base_how": how}
