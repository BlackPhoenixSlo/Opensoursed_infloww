from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proof_core import KINDS, NOT_REVERSIBLE, fill  # noqa: E402,F401  (fill re-exported for callers)

PLACEHOLDERS = ("{creator}", "{fan}", "{id}", "oi-proof-{run}")
SOURCES = frozenset({"live", "aborted", "of-js"})
VERDICTS = frozenset({"pass", "fail", "parked"})
UNDO_STATES = frozenset({"undone", "none", "FAILED", NOT_REVERSIBLE})
_RESPONSE_KEYS = frozenset({"status", "keys"})

_DIGITS = re.compile(r"\d{5,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_AUTH_NAMES = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization", "sign", "user-id", "x-bc",
                         "x-hash", "app-token", "bctokensha"})
_HEADER_LINE = re.compile(r"(?i)(?<![\w-])(cookie|set-cookie|authorization|proxy-authorization|user-id|x-bc|x-hash|"
                          r"app-token|bctokensha)[\"']?\s*:|(?<![\w-])(sess|auth_id)=\S")
_OF_REV = re.compile(r"^\d{12}-[0-9a-f]{10}$")
_EVIDENCE = re.compile(r"^slop/evidence/\d{8}T\d{6}Z-ofm-(live|fake)-[0-9a-f]{7,40}/?$")
_JS_FILE = re.compile(r"^[\w.-]+\.js$")
_FREE_TEXT = frozenset({"symbol", "evidence"})





def scrub(raw: dict, ids: dict) -> dict:
    creator, fan, run = (str(ids.get(k) or "") for k in ("creator", "fan", "run"))
    known = "|".join(re.escape(i) for i in (creator, fan) if i)
    number = re.compile(rf"(?<!\d)(?:{known + '|' if known else ''}\d{{5,}})(?!\d)")

    def text(s: str) -> str:
        if run:
            s = s.replace(f"oi-proof-{run}", "oi-proof-{run}")
        return number.sub(lambda m: "{creator}" if m[0] == creator else "{fan}" if m[0] == fan else "{id}", s)

    def clean(v):
        if isinstance(v, dict):
            return {text(str(k)): clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, (int, float)):
            s = text(str(v))
            return v if s == str(v) else s
        return text(str(v))

    def keep(chain, v):
        if not _exempt(chain, v):
            return clean(v)
        if chain[-1] in _FREE_TEXT and known:
            return re.sub(rf"(?<!\d)(?:{known})(?!\d)", lambda m: "{creator}" if m[0] == creator else "{fan}", v)
        return v

    req = raw.get("request") or {}
    headers = {str(k).lower(): v for k, v in (req.get("headers") or {}).items()}
    url = urlsplit(req.get("url") or req.get("path") or "")
    query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(url.query, keep_blank_values=True).items()}
    query.update(req.get("query") or {})
    ctype = headers.get("content-type")
    rec = {k: clean(raw[k]) for k in ("id", "section", "label", "pages", "phase") if k in raw}
    rec["source"] = raw.get("source")
    of_rev = raw.get("of_rev") or headers.get("x-of-rev")
    if of_rev:
        rec["of_rev"] = keep(("of_rev",), str(of_rev))
    if "captured" in raw:
        rec["captured"] = raw["captured"]
    if raw.get("of_js"):
        rec["of_js"] = {k: keep(("of_js", k), raw["of_js"][k]) for k in ("bundle", "symbol", "offset")
                        if k in raw["of_js"]}
    rec["request"] = {"method": str(req.get("method") or "").upper(), "path": text(url.path), "query": clean(query),
                      "content_type": ctype.split(";")[0].strip() if ctype else None,
                      "body": clean(_json_or_text(req.get("body")))}
    resp = raw.get("response") or {}
    rec["response"] = {"status": resp.get("status"), "keys": sorted({text(str(k)) for k in _keys(resp.get("body"))})}
    if "proof" in raw:
        proof = dict(raw["proof"])
        ev = proof.pop("evidence", None)
        rec["proof"] = clean(proof)
        if ev is not None:
            rec["proof"]["evidence"] = keep(("proof", "evidence"), ev)
    return rec


def _json_or_text(body):
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return body
    return body


def _keys(body) -> set:
    body = _json_or_text(body)
    if isinstance(body, dict):
        return set(body)
    if isinstance(body, list):
        return {k for item in body if isinstance(item, dict) for k in item}
    return set()



def _mask(part) -> str:
    return _EMAIL.sub("<email>", _DIGITS.sub("<digits>", str(part)))


def _path(chain) -> str:
    out = ""
    for p in chain:
        out += f"[{p}]" if isinstance(p, int) else (f".{_mask(p)}" if out else _mask(p))
    return out or "<record>"


def _block(chain) -> bool:
    c = tuple("#" if isinstance(p, int) else p for p in chain)
    return c in (("of_js",), ("requests", "#", "source"), ("room_source", "sources", "#"))


def _exempt(chain, value) -> bool:
    if chain in (("of_rev",), ("bundle_build",)):
        return isinstance(value, str) and bool(_OF_REV.match(value))
    if chain == ("proof", "evidence"):
        return isinstance(value, str) and bool(_EVIDENCE.match(value))
    if len(chain) >= 2 and _block(chain[:-1]):
        k = chain[-1]
        if k in ("file", "bundle"):
            return isinstance(value, str) and bool(_JS_FILE.match(value))
        if k == "offset":
            return isinstance(value, int) and not isinstance(value, bool)
        return k in _FREE_TEXT and isinstance(value, str)
    return False


def _response_ok(r) -> bool:
    return (isinstance(r, dict) and set(r) <= _RESPONSE_KEYS
            and (r.get("status") is None or (isinstance(r["status"], int) and not isinstance(r["status"], bool)))
            and isinstance(r.get("keys", []), list) and all(isinstance(k, str) for k in r.get("keys", [])))


def _walk(v, chain, out):
    if isinstance(v, dict):
        for k, x in v.items():
            here = chain + (k,)
            ks = str(k)
            if ks.lower() in _AUTH_NAMES:
                out.append(f"{_path(here)}: cookie or auth header name {ks!r}")
            if _DIGITS.search(ks):
                out.append(f"{_path(here)}: key holds a digit run of 5+ outside the placeholders")
            if _EMAIL.search(ks):
                out.append(f"{_path(here)}: key holds an email")
            if ks == "response" and not _response_ok(x):
                out.append(f"{_path(here)}: holds more than status and key names (response rows)")
            if ks.lower() == "headers" and isinstance(x, dict):
                extra = [h for h in x if str(h).lower() != "content-type"]
                if extra:
                    out.append(f"{_path(here)}: header kept beyond the content type ({len(extra)})")
            _walk(x, here, out)
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            _walk(x, chain + (i,), out)
    elif v is not None and not isinstance(v, bool):
        s = str(v)
        if _DIGITS.search(s) and not _exempt(chain, v):
            out.append(f"{_path(chain)}: digit run of 5+ outside the placeholders")
        if isinstance(v, str) and _EMAIL.search(s):
            out.append(f"{_path(chain)}: email")
        if isinstance(v, str) and _HEADER_LINE.search(s):
            out.append(f"{_path(chain)}: cookie or auth header line")


def check_record(record) -> list:
    if not isinstance(record, dict):
        return ["<record>: not a JSON object"]
    out: list = []
    _walk(record, (), out)
    src = record.get("source")
    if isinstance(src, str):
        if src not in SOURCES:
            out.append("source: must be live, aborted or of-js")
        elif src == "of-js":
            js = record.get("of_js")
            if not (isinstance(js, dict) and js.get("bundle") and js.get("symbol")):
                out.append("of_js: an of-js record must name the OnlyFans bundle and symbol")
    if record.get("mode") == "js":
        for i, q in enumerate(record.get("requests") or []):
            s = q.get("source") if isinstance(q, dict) else None
            if not (isinstance(s, dict) and s.get("file") and s.get("symbol")):
                out.append(f"requests[{i}].source: a js-mode request must name the bundle file and symbol")
    if "proof" in record:
        out += _proof_problems(record["proof"])
    return out


def _proof_problems(p) -> list:
    if not isinstance(p, dict):
        return ["proof: not an object"]
    out = []
    if p.get("kind") not in KINDS:
        out.append("proof.kind: must be live, mocked or oauth")
    if p.get("verdict") not in VERDICTS:
        out.append("proof.verdict: must be pass, fail or parked")
    elif p["verdict"] == "parked" and not str(p.get("reason") or "").strip():
        out.append("proof.reason: a parked proof must give the reason")
    if "undo" in p and p["undo"] not in UNDO_STATES:
        out.append("proof.undo: must be undone, none, FAILED or 'not reversible, owner go'")
    branches = p.get("branches") or {}
    if not isinstance(branches, dict):
        return out + ["proof.branches: must map a branch name to its verdict"]
    for name, v in branches.items():
        if not (v == "pass" or (isinstance(v, str) and re.match(r"^parked: \S", v))):
            out.append(f"proof.branches.{_mask(name)}: branch verdict must be pass or 'parked: <reason>'")
    return out


def check_records(folder: Path) -> tuple[int, list]:
    lines, files = [], sorted(folder.glob("*.json"))
    for f in files:
        try:
            rec = json.loads(f.read_text())
        except (ValueError, UnicodeDecodeError):
            lines.append(f"{f.name}: not valid JSON")
            continue
        lines += [f"{f.name}: {p}" for p in check_record(rec)]
    return len(files), lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="capture_record.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-records", help="check a capture record directory; exit 0 when clean")
    c.add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    if not a.dir.is_dir():
        print(f"check-records: {a.dir} is not a directory", file=sys.stderr)
        return 2
    n, lines = check_records(a.dir)
    for line in lines:
        print(line)
    bad = len({line.split(":", 1)[0] for line in lines})
    print(f"check-records: {n} records, {bad} with problems")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
