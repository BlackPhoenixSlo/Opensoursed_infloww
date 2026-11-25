from __future__ import annotations

import ast
import json
import fcntl
import os
import re
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from slop.lib import selection
from slop.lib.report import write_atomic

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "slop" / "map.json"
DIFF_ROOTS = tuple(r.rstrip("/") for r in selection.ROOTS)
MAP_LOCK = MAP.parent / "evidence/.map.lock"
DIFF = ("--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")
APP_SRC = (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs")
MAP_STALE = 200
VOLUME_KNOBS = {"P95_VS_LAST", "CPU_BUDGET_PCT", "POOL_GATE"}
DYNAMIC_LOAD = ("service/automations/", "service/db/migrations/versions/")


class MapInvalid(RuntimeError):
    pass


def map_invalid_reason(error: MapInvalid) -> str:
    return (f"slop/map.json invalid: {error.__cause__ or error} "
            "(restore: git checkout slop/map.json, or slop/run all --map)")


def is_volume(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id in VOLUME_KNOBS for t in targets):
            return True
    return False


def map_stale(ages: dict[str, int | None]) -> tuple[bool, str]:
    odd = sorted(sha[:7] for sha, n in ages.items() if n is None)
    if odd:
        return True, "map sha(s) not ancestors of HEAD: " + ", ".join(odd)
    known = [n for n in ages.values() if n is not None]
    if not known:
        return True, "no map entry"
    behind = max(known)
    return behind > MAP_STALE, f"oldest map sha {behind} commits behind HEAD ({'>' if behind > MAP_STALE else '<='} {MAP_STALE})"


def git(*a: str, check: bool = True) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout


def dirty_for_map() -> str:
    return git("status", "--porcelain", "--", *DIFF_ROOTS,
               ":!slop/map.json").strip()


def load_map() -> dict:
    try:
        doc = json.loads(MAP.read_text())
    except FileNotFoundError:
        return {"scenarios": {}, "version": 1}
    except ValueError as e:
        raise MapInvalid(f"{MAP}: invalid JSON; refusing to discard map entries") from e
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


@contextmanager
def locked_map():
    MAP_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(MAP_LOCK, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        doc = load_map()
        yield doc
        write_atomic(MAP, dump(doc))


def py_reach(cov_dir: Path) -> dict[str, list[str]]:
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
           names: set[str], http_pages=(), modules=(), no_ui_run: bool = False) -> dict:
    py = py_reach(cov_dir)
    for f in modules:
        py.setdefault(f, [])
    with locked_map() as doc:
        old = doc["scenarios"].get(name) or {}
        http = set(http_pages)
        if no_ui_run:
            http |= set(old.get("http_pages", ()))
            pages = set(pages) | set(old.get("pages", ()))
            py = {f: sorted(set(fs) | set(old.get("py", {}).get(f, ())))
                  for f, fs in {**old.get("py", {}), **py}.items()}
        entry = {"sha": sha, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "seconds": seconds, "scale": scale, "ui": ui, "py": dict(sorted(py.items())),
                 "pages": sorted(set(pages) | http), "http_pages": sorted(http)}
        doc["scenarios"][name] = entry
        doc["scenarios"] = {k: v for k, v in doc["scenarios"].items() if k in names}
        doc["version"] = 1
    return entry



_BLOCK = re.compile(r"^[ \t]*\{?/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\}?[ \t]*$", re.M)
_LINE = re.compile(r"(?<![:\w])//.*$", re.M)
_SPECS = (re.compile(r"""from\s+["']([^"']+)["']"""), re.compile(r"""import\(\s*["']([^"']+)["']\s*\)"""),
          re.compile(r"""require\(\s*["']([^"']+)["']\s*\)"""),
          re.compile(r"""(?<![\w.$])import\s+["']([^"']+)["']"""))


def _strip(src: str) -> str:
    return _LINE.sub("", _BLOCK.sub(lambda m: re.sub(r"[^\n]", "", m.group(0)), src))


def _resolve(spec: str, from_rel: str, app: Path) -> str | None:
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
    try:
        return {q for q, *_ in selection.defs(src)} if src is not None else None
    except SyntaxError:
        return None


def _unjudgeable(sha: str, base: str | None, f: str) -> bool:
    return (f.endswith(".py") and f.startswith(selection.PY_ROOTS)
            and not f.startswith(selection.SCEN)
            and ((base is not None and _show(base, f) is not None) or f.startswith(DYNAMIC_LOAD))
            and _show(sha, f) is None)


def map_ages(doc: dict) -> dict[str, int | None]:
    ages = {}
    for sha in {e.get("sha") for e in doc.get("scenarios", {}).values() if e.get("sha")}:
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=ROOT,
                                  capture_output=True).returncode == 0
        ages[sha] = int(git("rev-list", "--count", f"{sha}..HEAD").strip()) if ancestor else None
    return ages


def gather(doc: dict, since: str | None = None) -> dict:
    shas = sorted({e.get("sha") for e in doc.get("scenarios", {}).values() if e.get("sha")})
    base, how = base_of(since)
    hunks, changed, map_missing = {}, {}, {}
    ages = map_ages(doc)
    shared = _diff(base) if base else None
    for sha in shas:
        if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT, capture_output=True).returncode:
            raise SystemExit(f"slop: map sha {sha[:7]} is not in this repo; rebuild: slop/run all --map")
        changed[sha], per = shared or _diff(sha)
        map_missing[sha] = {f for f in changed[sha] if _unjudgeable(sha, base, f)}
        hunks[sha] = {f: ({**fd, "map_known": _names(_show(sha, f))} if base and base != sha else fd)
                      for f, fd in per.items()}
    untracked = [f for f in git("ls-files", "-z", "--others", "--exclude-standard", "--", *DIFF_ROOTS).split("\0") if f]
    deleted = {f for fs in changed.values() for f in fs if not (ROOT / f).exists()}
    for sha in shas:
        map_missing[sha].update(f for f in untracked if _unjudgeable(sha, base, f))
    return {"hunks": hunks, "changed": changed, "untracked": untracked, "map_missing": map_missing,
            "map_age": ages, "app_edges": app_edges(),
            "deleted": deleted, "base": base, "base_how": how}


def pick_changed(doc: dict, since: str | None = None) -> tuple[dict, dict, list[str]]:
    g = gather(doc, since)
    picks, warns = selection.pick(doc, g["hunks"], g["app_edges"], g["changed"], g["untracked"], g["deleted"],
                                  g["map_missing"])
    return g, picks, warns
