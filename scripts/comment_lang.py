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
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "scripts" / "comment_tools.mjs"
JS_EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
EXTS = (".py", ".sh") + JS_EXTS
EXCLUDE = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.next)/|\.min\.js$")
MARK = "\x00"

PY_DIRECTIVE = re.compile(
    r"#[ \t]*(?:(?i:noqa)\b|flake8:\s*noqa|type:|pyright:\s*\w|mypy:\s*\w|pylint:\s*(?:disable|enable|skip-file)"
    r"|ruff:\s*(?:noqa|isort)|pragma:\s|nosec\b|fmt:\s*(?:on|off|skip)\b|isort:\s*\w|noinspection\b"
    r"|pyre-(?:ignore|fixme|strict|unsafe)|cadence-ok:|pytype:\s*(?:disable|enable)|SPDX-License-Identifier|Copyright)"
)
PY_CODING = re.compile(r"coding[:=][ \t]*[-\w.]+")
PY_PLACED = re.compile(r"^#!|coding[:=]")
SH_ALLOW = re.compile(r"^\s*(?:shellcheck\s|SPDX-License-Identifier|Copyright)")
SH_READER = re.compile(r"\b(sed|grep|awk|head|tail|cat|cut|perl|less|more)\b|<\s*\"?\$")
SRC_READERS = {"getsource", "getsourcelines", "getcomments"}
FILE_READS = {"open", "read_text", "read_bytes", "getlines"}
REGULAR_MODES = {"100644", "100755"}
ROUTE_ATTRS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route", "route",
               "websocket", "command", "callback"}
ENDPOINT_CALLS = {"add_api_route", "add_route", "add_api_websocket_route", "add_websocket_route",
                  "APIRoute", "Route", "APIWebSocketRoute", "WebSocketRoute"}
DOC_READERS = {"getdoc", "render_doc", "help"}
DOC_MODULES = {"inspect", "pydoc", "builtins"}
DOC_IMPORTS = {"doctest", "typer", "click"}
DOC_FALLBACK = re.compile("|".join(sorted(DOC_READERS)) + "|__doc__")
SELF_PATH_FNS = {"Path", "PurePath", "PosixPath", "abspath", "realpath", "normpath", "fspath", "str"}
PATH_METHODS = {"resolve", "absolute", "expanduser"}
TOOL_DECORATORS = {"tool", "function_tool"}
MODEL_BASES = {"BaseModel", "RootModel", "BaseSettings", "TypedDict", "SQLModel", "Enum", "IntEnum", "StrEnum",
               "Flag", "IntFlag", "dataclass"}
POOL_MIN = 50
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
    frozen: bool = False

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
    def allowed_keys(self) -> list[tuple]:
        return [(c.text, c.anchor, c.own_line, c.placed) for c in self.comments if c.allowed]

    @property
    def partial(self) -> int:
        return sum(1 for d in self.docs if not d.protected and not d.strippable)


def decode(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


def has_bom(s: str) -> bool:
    return s.startswith("\ufeff")


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


def shebang_lang(text: str) -> str | None:
    m = re.match(r"#![ \t]*(\S+)(?:[ \t]+(?:-S[ \t]+)?(\S+))?", text)
    if not m:
        return None
    prog = m.group(1).rsplit("/", 1)[-1]
    if prog == "env":
        prog = m.group(2) or ""
    if prog in ("bash", "sh"):
        return "sh"
    return "py" if re.fullmatch(r"python[\d.]*", prog) else None


def _extensionless(p: str) -> bool:
    return "." not in p.rsplit("/", 1)[-1]


def lang_of(path: str, text: str | None = None) -> str | None:
    if path.endswith(".py"):
        return "py"
    if path.endswith(".sh"):
        return "sh"
    if path.endswith(JS_EXTS):
        return "js"
    return shebang_lang(text) if text is not None and _extensionless(path) else None


def is_candidate(p: str) -> bool:
    return not EXCLUDE.search(p) and (p.endswith(EXTS) or _extensionless(p))


def _first_line(p: str) -> str:
    with open(ROOT / p, "rb") as f:
        return decode(f.readline(256))


def tracked(paths: list[str] | None = None, *, untracked: bool = False) -> list[str]:
    flags = ("-co", "--exclude-standard") if untracked else ()
    out = git("ls-files", "-z", *flags, "--", *(paths or ["."])).split("\0")
    return sorted(p for p in set(out) if p and is_candidate(p) and (ROOT / p).is_file()
                  and (p.endswith(EXTS) or lang_of(p, _first_line(p))))


def _maybe_py(p: str) -> bool:
    return p.endswith(".py") or not p.endswith(EXTS)


def py_context_at(rev: str | None, *, untracked: bool = False) -> "PyContext":
    if rev is None:
        texts = {p: read_text(p) for p in tracked(untracked=untracked) if _maybe_py(p) and "\n" not in p}
    else:
        paths = []
        for row in git("ls-tree", "-r", "-z", rev).split("\0"):
            meta, _, p = row.partition("\t")
            if p and "\n" not in p and meta.split()[0] in REGULAR_MODES and is_candidate(p) and _maybe_py(p):
                paths.append(p)
        texts = blobs(rev, paths)
    return py_context([t for p, t in texts.items() if lang_of(p, t) == "py"])


def blobs(rev: str, paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    if any("\n" in p for p in paths):
        raise ValueError("newline in path")
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
        raise RuntimeError("shfmt not installed (brew install shfmt)")


def _split_bom(text: str) -> tuple[int, str]:
    return (1, text[1:]) if has_bom(text) else (0, text)


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
    src_names: set[str] = field(default_factory=set)
    all_src: bool = False
    doc_modules: set[str] = field(default_factory=set)

    def __or__(self, o: "PyContext") -> "PyContext":
        return PyContext(self.doc_names | o.doc_names, self.model_names | o.model_names,
                         self.endpoint_names | o.endpoint_names, self.all_docs or o.all_docs,
                         self.src_names | o.src_names, self.all_src or o.all_src, self.doc_modules | o.doc_modules)


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


def _method_self_ids(tree: ast.Module) -> set[int]:
    out: set[int] = set()
    for c in ast.walk(tree):
        if not isinstance(c, ast.ClassDef):
            continue
        for f in c.body:
            params = [*f.args.posonlyargs, *f.args.args] if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            if params and params[0].arg in ("self", "cls"):
                out.update(id(n) for n in ast.walk(f) if isinstance(n, ast.Name) and n.id == params[0].arg)
    return out


def _ref_name(n: ast.AST) -> str | None:
    return n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else None


@dataclass
class TreeFacts:
    doc_names: set[str] = field(default_factory=set)
    doc_modules: set[str] = field(default_factory=set)
    self_doc: bool = False
    unresolved: bool = False
    reads_docs: bool = False
    src_names: set[str] = field(default_factory=set)
    self_read: bool = False
    src_unresolved: bool = False


def _module_stmts(body: list[ast.stmt]):
    for n in body:
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for block in (getattr(n, "body", []), getattr(n, "orelse", []), getattr(n, "finalbody", []),
                      *(h.body for h in getattr(n, "handlers", [])), *(c.body for c in getattr(n, "cases", []))):
            yield from _module_stmts(block)


def _readers(tree: ast.Module, base: set[str], modules: set[str]):
    readers = set(base)
    calls = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assigned = {id(n.value): n.targets[0].id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    qualified = {"pydoc", "builtins"} & modules
    aliases = {a.asname or a.name: a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
               for a in n.names if a.name in qualified}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in modules:
            readers.update(a.asname or a.name for a in n.names if a.name in base or n.module == "pydoc")

    def is_reader(n: ast.AST) -> bool:
        if isinstance(n, ast.Name):
            return n.id in readers or "*" in readers and id(n) in calls
        if isinstance(n, ast.Attribute):
            module = aliases.get(_ref_name(n.value)) if isinstance(n.value, ast.Name) else None
            return module == "pydoc" or (module == "builtins" if n.attr == "help" else n.attr in base)
        return False

    grew = True
    while grew:
        grew = False
        for n in ast.walk(tree):
            target = assigned.get(id(n))
            if target and target not in readers and is_reader(n):
                readers.add(target)
                grew = True
    top = list(_module_stmts(tree.body))
    exported = {a.asname for n in top if isinstance(n, ast.ImportFrom) for a in n.names if a.asname}
    exported |= {t.id for n in top if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    loose = any(is_reader(n) and not isinstance(getattr(n, "ctx", None), ast.Store)
                and id(n) not in calls and id(n) not in assigned for n in ast.walk(tree))
    return is_reader, loose or bool(exported & (readers - base))


def _doc_key(n: ast.AST, parents: dict[int, ast.AST]) -> bool:
    if not (isinstance(n, ast.Constant) and n.value == "__doc__"):
        return False
    p = parents.get(id(n))
    if isinstance(p, (ast.Tuple, ast.List, ast.Set)):
        p = parents.get(id(p))
    return not isinstance(p, ast.Compare)


def _doc_refs(tree: ast.Module, f: TreeFacts) -> None:
    binds = _bindings(tree)
    is_reader, unresolved = _readers(tree, DOC_READERS, DOC_MODULES)
    f.unresolved |= unresolved
    nodes = list(ast.walk(tree))
    parents = {id(c): n for n in nodes for c in ast.iter_child_nodes(n)}
    for n in nodes:
        if isinstance(n, ast.ImportFrom):
            f.reads_docs |= (n.module or "").split(".")[0] in DOC_IMPORTS
        elif isinstance(n, ast.Import):
            f.reads_docs |= any(a.name.split(".")[0] in DOC_IMPORTS for a in n.names)
    method_self = _method_self_ids(tree)
    receivers: list[ast.expr] = []
    for n in nodes:
        name = _ref_name(n)
        if isinstance(n, ast.Call) and is_reader(n.func):
            f.reads_docs = True
            args = n.args[:1] or [k.value for k in n.keywords if k.arg in ("thing", "request", "path")]
            if not args:
                f.unresolved = True
            for arg in args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if all(p.isidentifier() for p in arg.value.split(".")):
                        f.doc_modules.add(arg.value.replace(".", "/"))
                else:
                    receivers.append(arg)
        elif name == "__doc__":
            f.reads_docs = True
            if isinstance(n, ast.Attribute) and not isinstance(n.ctx, ast.Store):
                receivers.append(n.value)
        elif _doc_key(n, parents):
            f.reads_docs = f.unresolved = True
    for r in receivers:
        parts: list[str] = []
        while isinstance(r, ast.Attribute):
            parts.append(r.attr)
            r = r.value
        if isinstance(r, ast.Call) and _name(r.func) == "type" and len(r.args) == 1:
            r = r.args[0]
        if id(r) in method_self:
            f.self_doc = True
            f.doc_names.update(parts)
        elif isinstance(r, ast.Name) and r.id in binds:
            f.doc_names.update([binds[r.id], r.id, *parts])
        else:
            f.unresolved = True


def _dir_use(n: ast.AST, parents: dict[int, ast.AST]) -> bool:
    while True:
        p = parents.get(id(n))
        if isinstance(p, ast.Call) and n in p.args and _name(p.func) == "dirname" \
                or isinstance(p, ast.Attribute) and p.value is n and p.attr in ("parent", "parents"):
            return True
        if isinstance(p, ast.Call) and p.args[:1] == [n] and _name(p.func) in SELF_PATH_FNS:
            n = p
        elif isinstance(p, ast.Attribute) and p.value is n and p.attr in PATH_METHODS \
                and isinstance(parents.get(id(p)), ast.Call) and parents[id(p)].func is p:
            n = parents[id(p)]
        else:
            return False


def _src_refs(tree: ast.Module, f: TreeFacts) -> None:
    binds = _bindings(tree)
    is_reader, f.src_unresolved = _readers(tree, SRC_READERS, {"inspect"})
    parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    f.self_read = any(isinstance(n, ast.Name) and n.id == "__file__" and not _dir_use(n, parents)
                      for n in ast.walk(tree))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = _name(n.func)
        if is_reader(n.func) and n.args:
            r = n.args[0]
        elif name in FILE_READS:
            v = n.func.value if isinstance(n.func, ast.Attribute) else None
            t = v.args[0] if isinstance(v, ast.Call) and _name(v.func) in ("Path", "PurePath") and v.args \
                else n.args[0] if n.args else None
            if not isinstance(t, ast.Attribute) or t.attr != "__file__":
                continue
            r = t.value
        else:
            continue
        first = None
        while isinstance(r, ast.Attribute):
            r, first = r.value, r.attr
        if isinstance(r, ast.Name) and r.id in binds:
            f.src_names.update(filter(None, [binds[r.id], first]))


def tree_facts(tree: ast.Module) -> TreeFacts:
    f = TreeFacts()
    _doc_refs(tree, f)
    _src_refs(tree, f)
    return f


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
            re.findall(rf"(?:{'|'.join(sorted(ENDPOINT_CALLS))})\(([^)]*)", text))))
        return {"doc": set(), "self_doc": False, "unresolved": bool(DOC_FALLBACK.search(text)),
                "classes": classes, "aliases": aliases, "endpoints": endpoints, "src": set(),
                "src_unresolved": False, "doc_modules": set()}
    tf = tree_facts(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef):
            classes.append((n.name, [b for b in map(_name, n.bases) if b]
                            + [d for d in map(_name, n.decorator_list) if d == "dataclass"]))
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
    return {"doc": tf.doc_names, "self_doc": tf.self_doc, "unresolved": tf.unresolved, "classes": classes,
            "aliases": aliases, "endpoints": endpoints, "src": tf.src_names, "src_unresolved": tf.src_unresolved,
            "doc_modules": tf.doc_modules}


_PY_FACTS: dict[str, dict] = {}


def py_context(texts: list[str]) -> PyContext:
    missing = [t for t in dict.fromkeys(texts) if t not in _PY_FACTS]
    cached = {t: _PY_FACTS[t] for t in texts if t in _PY_FACTS}
    cached.update(zip(missing, pmap(_facts, missing)))
    _PY_FACTS.clear()
    _PY_FACTS.update(cached)
    facts = [cached[t] for t in texts]
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
                     {n for f in facts for n in f["endpoints"]}, any(f["unresolved"] for f in facts),
                     {n for f in facts for n in f["src"]}, any(f["src_unresolved"] for f in facts),
                     {m for f in facts for m in f["doc_modules"]})


def _module_name(path: str) -> str:
    p = Path(path)
    return p.parent.name if p.stem == "__init__" else p.stem


def _decorator_attr(d: ast.expr) -> str | None:
    if isinstance(d, ast.Call):
        d = d.func
    return d.attr if isinstance(d, ast.Attribute) else None


def _keeps_doc(d: ast.expr) -> bool:
    return _decorator_attr(d) in ROUTE_ATTRS or _name(d) in TOOL_DECORATORS


def protected_keys(path: str, tree: ast.Module, ctx: PyContext, tf: TreeFacts) -> set[str] | None:
    if ctx.all_docs or tf.reads_docs or _module_name(path) in ctx.doc_names:
        return None
    if ctx.doc_modules and path.endswith(".py"):
        module = "/" + path.removesuffix(".py").removesuffix("/__init__")
        if any(module.endswith("/" + name) for name in ctx.doc_modules):
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
    tf = tree_facts(tree)
    frozen = ctx.all_src or tf.self_read or bool(ctx.src_names & ({_module_name(path)} | {
        n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}))
    prot = protected_keys(path, tree, ctx, tf)
    offs = _line_offsets(body)
    lines = body.split("\n")
    scan = Scan(protected=prot, frozen=frozen)
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
            allowed = bool(l == 1 and s.startswith("#!") or l <= 2 and PY_CODING.search(s) or PY_DIRECTIVE.search(s))
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
    scan.prunable = [] if frozen else merged
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
    if has_bom(text):
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
        allowed = bool(line == 1 and c["Text"].startswith("!") or SH_ALLOW.match(c["Text"]))
        scan.comments.append(Comment(a, b, line, c["End"]["Line"], "#" + c["Text"], allowed,
                                     bisect_left(code_lines, line), line in own,
                                     min(line, 2) if allowed and c["Text"].startswith("!") else 0))
    code = text
    for c in reversed(scan.comments):
        code = code[:c.start] + code[c.end:]
    kinds: set[str] = set()
    scan.frozen = "LINENO" in code or _sh_self_use(tree, kinds) \
        or kinds == {"dir", "base"} and bool(SH_READER.search(code))
    scan.prunable = [] if scan.frozen else [(c.start, c.end, MARK) for c in scan.comments if not c.allowed]
    return scan


def _sh_self_use(o, kinds: set[str], call: dict | None = None) -> bool:
    if isinstance(o, list):
        return any(_sh_self_use(i, kinds, call) for i in o)
    if not isinstance(o, dict):
        return False
    if o.get("Type") == "CallExpr":
        call = o
    if o.get("Type") == "ParamExp" and o.get("Param", {}).get("Value") in ("0", "BASH_SOURCE"):
        exp = o.get("Exp") or {}
        op, word = exp.get("Op"), [x.get("Value") for x in (exp.get("Word") or {}).get("Parts", [])]
        head = [x.get("Value") for x in call["Args"][0].get("Parts", [])] if call and call.get("Args") else []
        kind = "base" if head == ["basename"] or op in ("#", "##") and word == ["*/"] else \
            "dir" if head == ["dirname"] or op in ("%", "%%") and word == ["/*"] else None
        if kind is None:
            return True
        kinds.add(kind)
    return any(_sh_self_use(v, kinds, call) for v in o.values())


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


def _workers() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def pmap(fn, items: list) -> list:
    if len(items) <= POOL_MIN:
        return [fn(x) for x in items]
    with ProcessPoolExecutor(_workers()) as pp:
        return list(pp.map(fn, items, chunksize=16))


def native_scan(path: str, lang: str, text: str, ctx: PyContext) -> Scan:
    if lang == "py":
        return py_scan(path, text, ctx)
    if lang == "sh":
        return sh_scan(path, text)
    raise ValueError(f"not a py/sh source ({lang})")


def _native(ctx: PyContext, item: tuple[str, str, str]):
    p, lang, text = item
    try:
        return p, native_scan(p, lang, text, ctx), None
    except Exception as e:
        return p, None, f"{type(e).__name__}: {e}"


def source_langs(texts: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    langs: dict[str, str] = {}
    errors: dict[str, str] = {}
    for p, t in texts.items():
        lang = None if "\n" in p else lang_of(p, t)
        if lang:
            langs[p] = lang
        else:
            errors[p] = "newline in path" if "\n" in p else "not a py/sh/js source"
    return langs, errors


def scan_files(files: dict[str, tuple[str, str]], ctx: PyContext, mode: str = "count"
               ) -> tuple[dict[str, Scan], dict[str, str]]:
    scans: dict[str, Scan] = {}
    errors: dict[str, str] = {}
    native = [(p, lang, t) for p, (lang, t) in files.items() if lang != "js"]
    js = [(p, t) for p, (lang, t) in files.items() if lang == "js"]
    with ThreadPoolExecutor(_workers()) as tp:
        batches = [dict(js[i:i + 300]) for i in range(0, len(js), 300)]
        futs = [tp.submit(js_run, b, mode) for b in batches]
        results = pmap(partial(_native, ctx), native)
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
