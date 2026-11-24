"""Per-file comment + docstring spans for py/sh/js, shared by comment_budget, comment_equality and
comment_strip. Offsets are code points into the text as read (newline="", BOM kept)."""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import tokenize
from bisect import bisect_left
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "scripts" / "comment_tools.mjs"
JS_EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
EXTS = (".py", ".sh") + JS_EXTS
EXCLUDE = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.next)/|\.min\.js$|\.d\.[mc]?ts$")
MARK = "\x00"

PY_ALLOW = re.compile(
    r"^#!|coding[:=][ \t]*[-\w.]+|(?i:\bnoqa\b)|type:\s*ignore\b|^#\s*type:|pyright:\s*\w|mypy:\s*\w"
    r"|pylint:\s*(disable|enable)|ruff:\s*(noqa|isort)|pragma:\s|\bnosec\b|^#\s*fmt:\s*(on|off|skip)\b"
    r"|^#\s*isort:\s*\w|pyre-(ignore|fixme|strict|unsafe)|pytype:\s*(disable|enable)"
    r"|SPDX-License-Identifier|^#\s*Copyright"
)
PY_PLACED = re.compile(r"^#!|coding[:=]")
SH_ALLOW = re.compile(r"^!|shellcheck|SPDX-License-Identifier|^\s*Copyright")
ROUTE_ATTRS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route", "route",
               "websocket", "command", "callback"}
ENDPOINT_CALLS = {"add_api_route", "add_route", "add_api_websocket_route", "add_websocket_route",
                  "APIRoute", "Route", "APIWebSocketRoute", "WebSocketRoute"}
RUNTIME_DOC = re.compile(r"__doc__|getdoc\(|\bdoctest\b|^\s*(import|from)\s+(typer|click)\b", re.M)
TOOL_DECORATORS = {"tool", "function_tool"}
MODEL_BASES = {"BaseModel", "RootModel", "BaseSettings", "TypedDict"}
_SKIP_TOK = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
             tokenize.ENCODING, tokenize.ENDMARKER}


@dataclass
class Comment:
    start: int
    end: int
    line: int
    end_line: int
    text: str
    allowed: bool
    anchor: int
    own_line: bool
    placed: int = 0


@dataclass
class Doc:
    start: int
    end: int
    line: int
    end_line: int
    key: str
    protected: bool
    strippable: bool
    sole: bool


@dataclass
class Scan:
    comments: list[Comment] = field(default_factory=list)
    docs: list[Doc] = field(default_factory=list)
    prunable: list[tuple[int, int, str]] = field(default_factory=list)
    protected: set[str] | None = field(default_factory=set)
    dump: dict = field(default_factory=dict)

    @property
    def lines(self) -> list[int]:
        out: set[int] = set()
        for c in self.comments:
            if not c.allowed:
                out.update(range(c.line, c.end_line + 1))
        for d in self.docs:
            if not d.protected:
                out.update(range(d.line, d.end_line + 1))
        return sorted(out)

    @property
    def allowed_keys(self) -> Counter:
        return Counter((c.text, c.anchor, c.own_line, c.placed) for c in self.comments if c.allowed)

    @property
    def partial(self) -> int:
        return sum(1 for d in self.docs if not d.protected and not d.strippable)


def decode(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


def encode(s: str) -> bytes:
    return s.encode("utf-8", "surrogateescape")


def git_bytes(*args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, input=stdin, capture_output=True, check=True).stdout


def git(*args: str) -> str:
    return decode(git_bytes(*args))


def read_text(path: str) -> str:
    with open(ROOT / path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    with open(ROOT / path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)


def is_source(p: str) -> bool:
    return p.endswith(EXTS) and not EXCLUDE.search(p)


def tracked(paths: list[str] | None = None) -> list[str]:
    out = git("ls-files", "-z", "--", *(paths or ["."])).split("\0")
    return sorted(p for p in out if p and is_source(p) and (ROOT / p).is_file())


def texts_at(rev: str | None, only_py: bool = False) -> dict[str, str]:
    if rev is None:
        paths = [p for p in tracked() if not only_py or p.endswith(".py")]
        return {p: read_text(p) for p in paths}
    paths = [p for p in git("ls-tree", "-r", "-z", "--name-only", rev).split("\0")
             if p and is_source(p) and (not only_py or p.endswith(".py"))]
    return blobs(rev, paths)


def blobs(rev: str, paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    raw = git_bytes("cat-file", "--batch", stdin=b"".join(encode(f"{rev}:{p}\n") for p in paths))
    out, i = {}, 0
    for p in paths:
        nl = raw.index(b"\n", i)
        head = raw[i:nl].split()
        if len(head) != 3 or head[1] != b"blob":
            raise FileNotFoundError(f"{rev}:{p}")
        n = int(head[2])
        out[p] = decode(raw[nl + 1:nl + 1 + n])
        i = nl + 1 + n + 1
    return out


def line_kinds(text: str) -> frozenset[str]:
    crlf = text.count("\r\n")
    return frozenset(k for k, n in (("crlf", crlf), ("lf", text.count("\n") - crlf),
                                    ("cr", text.count("\r") - crlf)) if n)


def need_shfmt() -> None:
    if not shutil.which("shfmt"):
        raise SystemExit("shfmt not installed (brew install shfmt)")


def _split_bom(text: str) -> tuple[int, str]:
    return (1, text[1:]) if text.startswith("\ufeff") else (0, text)


def _line_offsets(text: str) -> list[int]:
    offs, n = [0], 0
    for line in text.split("\n"):
        n += len(line) + 1
        offs.append(n)
    return offs


def _byte_col(line: str, col: int) -> int:
    return len(decode(encode(line)[:col]))


def _name(e: ast.expr) -> str | None:
    while isinstance(e, (ast.Subscript, ast.Call)):
        e = e.value if isinstance(e, ast.Subscript) else e.func
    if isinstance(e, ast.Attribute):
        return e.attr
    return e.id if isinstance(e, ast.Name) else None


def owners(tree: ast.Module):
    yield "<module>", tree

    def walk(node, prefix):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{prefix}{n.name}"
                yield key, n
                yield from walk(n, key + ".")
            else:
                yield from walk(n, prefix)

    yield from walk(tree, "")


def docstring_node(body: list[ast.stmt]) -> ast.Expr | None:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[0]
    return None


@dataclass
class PyContext:
    doc_names: set[str] = field(default_factory=set)
    model_names: set[str] = field(default_factory=set)
    endpoint_names: set[str] = field(default_factory=set)
    all_docs: bool = False

    def __or__(self, o: "PyContext") -> "PyContext":
        return PyContext(self.doc_names | o.doc_names, self.model_names | o.model_names,
                         self.endpoint_names | o.endpoint_names, self.all_docs or o.all_docs)


_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*\(([^)]*)\)", re.M)


def _bindings(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1] if a.asname else a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                out[a.asname or a.name] = a.name
        elif isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, n.name)
    return out


def _doc_refs(tree: ast.Module) -> tuple[set[str], bool, bool]:
    binds = _bindings(tree)
    names: set[str] = set()
    self_doc = unresolved = False
    receivers: list[ast.expr] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr == "__doc__" and not isinstance(n.ctx, ast.Store):
            receivers.append(n.value)
        elif isinstance(n, ast.Call) and _name(n.func) == "getdoc" and n.args:
            receivers.append(n.args[0])
        elif isinstance(n, ast.Call) and _name(n.func) == "getattr" and len(n.args) > 1 \
                and isinstance(n.args[1], ast.Constant) and n.args[1].value == "__doc__":
            unresolved = True
    for r in receivers:
        parts: list[str] = []
        while isinstance(r, ast.Attribute):
            parts.append(r.attr)
            r = r.value
        if isinstance(r, ast.Call) and _name(r.func) == "type" or isinstance(r, ast.Name) and r.id in ("self", "cls"):
            self_doc = True
            names.update(parts)
        elif isinstance(r, ast.Name) and r.id in binds:
            names.update([binds[r.id], r.id, *parts])
        else:
            unresolved = True
    return names, self_doc, unresolved


def _facts(text: str) -> dict:
    classes: list[tuple[str, list[str]]] = []
    aliases: list[tuple[str, str]] = []
    endpoints: set[str] = set()
    try:
        tree = ast.parse(_split_bom(text)[1])
    except (SyntaxError, ValueError):
        for m in _CLASS_RE.finditer(text):
            classes.append((m.group(1), re.findall(r"(\w+)\s*(?:\[[^\]]*\])?\s*(?:,|$)", m.group(2))))
        endpoints |= set(re.findall(r"\b(\w+)\b", " ".join(
            re.findall(r"(?:add_api_route|add_route|add_api_websocket_route|add_websocket_route)\(([^)]*)",
                       text))))
        return {"doc": set(), "self_doc": False, "unresolved": bool(re.search(r"__doc__|getdoc", text)),
                "classes": classes, "aliases": aliases, "endpoints": endpoints}
    doc, self_doc, unresolved = _doc_refs(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            classes.append((n.name, [b for b in map(_name, n.bases) if b]))
        elif isinstance(n, (ast.ImportFrom, ast.Import)):
            aliases += [(a.name.split(".")[-1], a.asname) for a in n.names if a.asname]
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and isinstance(n.value, (ast.Name, ast.Attribute)):
            src = _name(n.value)
            if src:
                aliases.append((src, n.targets[0].id))
        elif isinstance(n, ast.Call) and _name(n.func) in ENDPOINT_CALLS:
            for a in [*n.args[1:], *(k.value for k in n.keywords)]:
                for sub in ast.walk(a):
                    if isinstance(sub, (ast.Name, ast.Attribute)):
                        endpoints.add(_name(sub))
    return {"doc": doc, "self_doc": self_doc, "unresolved": unresolved, "classes": classes,
            "aliases": aliases, "endpoints": endpoints}


def py_context(texts: list[str]) -> PyContext:
    facts = pmap(_facts, texts)
    names = set(MODEL_BASES)
    for f in facts:
        if f["self_doc"]:
            names.update(c for c, _ in f["classes"])
    classes = [c for f in facts for c in f["classes"]]
    aliases = [a for f in facts for a in f["aliases"]]
    changed = True
    while changed:
        changed = False
        for name, bases in classes:
            if name not in names and names.intersection(bases):
                names.add(name)
                changed = True
        for src, dst in aliases:
            if src in names and dst not in names:
                names.add(dst)
                changed = True
    return PyContext({n for f in facts for n in f["doc"]}, names,
                     {n for f in facts for n in f["endpoints"]}, any(f["unresolved"] for f in facts))


def _module_name(path: str) -> str:
    p = Path(path)
    return p.parent.name if p.stem == "__init__" else p.stem


def _decorator_attr(d: ast.expr) -> str | None:
    if isinstance(d, ast.Call):
        d = d.func
    return d.attr if isinstance(d, ast.Attribute) else None


def _keeps_doc(d: ast.expr) -> bool:
    return _decorator_attr(d) in ROUTE_ATTRS or _name(d) in TOOL_DECORATORS


def protected_keys(path: str, tree: ast.Module, body: str, ctx: PyContext) -> set[str] | None:
    """None = every docstring in the file is runtime behaviour."""
    if ctx.all_docs or RUNTIME_DOC.search(body) or _module_name(path) in ctx.doc_names:
        return None
    keep: set[str] = set()
    for key, n in owners(tree):
        if isinstance(n, ast.ClassDef):
            if n.name in ctx.model_names or n.name in ctx.doc_names or n.name in ctx.endpoint_names:
                keep.add(key)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name in ctx.endpoint_names or n.name in ctx.doc_names or any(
                    _keeps_doc(d) for d in n.decorator_list):
                keep.add(key)
    return keep


def py_scan(path: str, text: str, ctx: PyContext) -> Scan:
    off, body = _split_bom(text)
    if "\r" in body.replace("\r\n", ""):
        raise ValueError("bare CR line endings")
    tree = ast.parse(body)
    prot = protected_keys(path, tree, body, ctx)
    offs = _line_offsets(body)
    lines = body.split("\n")
    scan = Scan(protected=prot)
    for key, owner in owners(tree):
        doc = docstring_node(owner.body)
        if doc is None:
            continue
        first, last = lines[doc.lineno - 1], lines[doc.end_lineno - 1]
        col, end_col = _byte_col(first, doc.col_offset), _byte_col(last, doc.end_col_offset)
        after = last[end_col:].strip()
        strippable = not first[:col].strip() and (not after or after.startswith("#"))
        scan.docs.append(Doc(off + offs[doc.lineno - 1] + col, off + offs[doc.end_lineno - 1] + end_col,
                             doc.lineno, doc.end_lineno, key, prot is None or key in prot, strippable,
                             len(owner.body) == 1 and not isinstance(owner, ast.Module)))
    doc_ranges = sorted((d.start - off, d.end - off, d.sole) for d in scan.docs)
    code: list[int] = []
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
        (l, c), (el, ec) = tok.start, tok.end
        a = offs[l - 1] + c
        if tok.type == tokenize.COMMENT:
            s = tok.string
            allowed = bool(PY_ALLOW.search(s))
            scan.comments.append(Comment(off + a, off + offs[el - 1] + ec, l, el, s, allowed,
                                         bisect_left(code, a), not lines[l - 1][:c].strip(),
                                         min(l, 3) if allowed and PY_PLACED.search(s) else 0))
            continue
        if tok.type in _SKIP_TOK:
            continue
        i = bisect_left(doc_ranges, (a + 1,)) - 1
        if i >= 0 and doc_ranges[i][0] <= a < doc_ranges[i][1] and not (doc_ranges[i][2] and a == doc_ranges[i][0]):
            continue
        code.append(a)
    spans = [(c.start, c.end, MARK) for c in scan.comments if not c.allowed]
    spans += [(d.start, d.end, "pass" if d.sole else MARK) for d in scan.docs
              if not d.protected and d.strippable]
    merged: list[tuple[int, int, str]] = []
    for s in sorted(spans):
        if not merged or s[0] >= merged[-1][1]:
            merged.append(s)
    scan.prunable = merged
    return scan


def py_code(text: str, keep: set[str] | None) -> str:
    tree = ast.parse(_split_bom(text)[1])
    for key, owner in owners(tree):
        if keep is not None and key not in keep and docstring_node(owner.body) is not None:
            owner.body = owner.body[1:]
    for _, owner in owners(tree):
        if not owner.body and not isinstance(owner, ast.Module):
            owner.body = [ast.Pass()]
        if len(owner.body) == 1 and isinstance(owner.body[0], ast.Expr) \
                and isinstance(owner.body[0].value, ast.Constant) and owner.body[0].value.value is Ellipsis:
            owner.body = [ast.Pass()]
    return ast.dump(tree, include_attributes=False)


def _shfmt_json(path: str, text: str):
    need_shfmt()
    r = subprocess.run(["shfmt", "--to-json", "--filename", path], input=encode(text), capture_output=True)
    if r.returncode != 0:
        raise ValueError(f"shfmt cannot parse: {decode(r.stderr).strip()[:200]}")
    return json.loads(r.stdout)


def _is_comment(o) -> bool:
    return isinstance(o, dict) and "Hash" in o and "Text" in o


def _is_pos(o) -> bool:
    return isinstance(o, dict) and bool(o) and set(o) <= {"Offset", "Line", "Col"}


def sh_scan(path: str, text: str) -> Scan:
    if "\ufeff" in text[:1]:
        raise ValueError("BOM in shell script")
    tree = _shfmt_json(path, text)
    raw = encode(text)
    b2c = None if len(raw) == len(text) else _byte_to_char(text)
    found: list[dict] = []

    def walk(o):
        if _is_comment(o):
            found.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)

    walk(tree)
    lines = text.split("\n")
    own = {c["Pos"]["Line"] for c in found
           if not decode(encode(lines[c["Pos"]["Line"] - 1])[:c["Pos"]["Col"] - 1]).strip()}
    code_lines = [i + 1 for i, ln in enumerate(lines) if ln.strip() and i + 1 not in own]
    scan = Scan()
    seen = set()
    for c in sorted(found, key=lambda c: c["Pos"]["Offset"]):
        a, b = c["Pos"]["Offset"], c["End"]["Offset"]
        if a in seen:
            continue
        seen.add(a)
        if b2c is not None:
            a, b = b2c[a], b2c[b]
        line = c["Pos"]["Line"]
        allowed = bool(SH_ALLOW.search(c["Text"]))
        scan.comments.append(Comment(a, b, line, c["End"]["Line"], "#" + c["Text"], allowed,
                                     bisect_left(code_lines, line), line in own,
                                     min(line, 2) if allowed and c["Text"].startswith("!") else 0))
    scan.prunable = [(c.start, c.end, MARK) for c in scan.comments if not c.allowed]
    return scan


def _byte_to_char(text: str) -> list[int]:
    m: list[int] = []
    for i, ch in enumerate(text):
        m.extend([i] * len(encode(ch)))
    m.append(len(text))
    return m


def sh_ast(path: str, text: str) -> str:
    def clean(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if _is_pos(v):
                    continue
                v = clean(v)
                if v != []:
                    out[k] = v
            return out
        if isinstance(o, list):
            return [clean(i) for i in o if not _is_comment(i)]
        return o

    return json.dumps(clean(_shfmt_json(path, text)), sort_keys=True)


def js_run(files: dict[str, str], mode: str) -> dict[str, dict]:
    if not files:
        return {}
    payload = json.dumps([{"path": p, "text": t} for p, t in files.items()]).encode()
    r = subprocess.run(["node", str(TOOLS), mode], input=payload, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"comment_tools.mjs failed: {decode(r.stderr)[:2000]}")
    return json.loads(r.stdout)


def js_scan_entry(e: dict) -> Scan:
    scan = Scan(dump=e)
    for s, t, l, el, allowed, anchor, own, body, gap in e["comments"]:
        scan.comments.append(Comment(s, t, l, el, body, allowed, anchor, own, gap))
    scan.prunable = [(a, b, MARK) for a, b in e.get("ranges", [])]
    return scan


_STATE = None


def _init(state) -> None:
    global _STATE
    _STATE = state


def state():
    return _STATE


def _workers() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def pmap(fn, items: list, st=None) -> list:
    if len(items) <= 50:
        _init(st)
        return [fn(x) for x in items]
    with ProcessPoolExecutor(_workers(), initializer=_init, initargs=(st,)) as pp:
        return list(pp.map(fn, items, chunksize=16))


def _native(item: tuple[str, str]):
    p, text = item
    try:
        return p, (py_scan(p, text, _STATE) if p.endswith(".py") else sh_scan(p, text)), None
    except Exception as e:
        return p, None, f"{type(e).__name__}: {e}"


def scan_files(files: dict[str, str], ctx: PyContext, mode: str = "count"
               ) -> tuple[dict[str, Scan], dict[str, str]]:
    scans: dict[str, Scan] = {}
    errors: dict[str, str] = {}
    native = [(p, t) for p, t in files.items() if p.endswith((".py", ".sh"))]
    js = [(p, t) for p, t in files.items() if not p.endswith((".py", ".sh"))]
    if any(p.endswith(".sh") for p, _ in native):
        need_shfmt()
    with ThreadPoolExecutor(_workers()) as tp:
        batches = [dict(js[i:i + 300]) for i in range(0, len(js), 300)]
        futs = [tp.submit(js_run, b, mode) for b in batches]
        results = pmap(_native, native, ctx)
        for b, f in zip(batches, futs):
            try:
                out = f.result()
            except Exception as ex:
                out = {p: {"error": f"{type(ex).__name__}: {str(ex)[:300]}"} for p in b}
            for p in b:
                out.setdefault(p, {"error": "no result from comment_tools.mjs"})
            for p, e in out.items():
                if e.get("error"):
                    errors[p] = e["error"]
                else:
                    scans[p] = js_scan_entry(e)
    for p, s, e in results:
        if e:
            errors[p] = e
        else:
            scans[p] = s
    return scans, errors
