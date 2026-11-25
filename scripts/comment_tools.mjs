import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function loadTs() {
  if (process.env.COMMENT_TOOLS_TS) return require(process.env.COMMENT_TOOLS_TS);
  try {
    return require(join(root, "app/node_modules/typescript"));
  } catch {
    return require("typescript");
  }
}
const ts = loadTs();

const DIRECTIVE = /^(eslint-(disable|enable|env)|@ts-|prettier-ignore|(istanbul|c8|v8) ignore|biome-ignore|oxlint-(disable|enable)|deno-(lint|fmt)-ignore|webpack[A-Z]|turbopack[A-Z]|@vite-ignore|[#@]__PURE__|@__NO_SIDE_EFFECTS__|@jsx|@refresh|@(vitest|jest)-environment|@license|@preserve|SPDX-License-Identifier)/;
const BLOCK_DIRECTIVE = /^(eslint|globals?|exported)(\s|$)/;
const ALLOW_RE = [
  /^\/\/\/\s*<(reference|amd-)/,
  /^\/\/[#@]\s*source(Mapping)?URL=/,
  /^\/[*/]![^]*(@license|@preserve|Copyright|SPDX-License-Identifier|\(c\))/i,
];
const FILE_SCOPED = /^(@ts-(nocheck|check)\b|@license|@preserve|SPDX-License-Identifier|@jsx|@refresh|@(vitest|jest)-environment|(eslint|oxlint)-(disable|enable)(?![-\w])|deno-lint-ignore-file)/;
const JSDOC_TYPES = /@(type|typedef|template|callback|satisfies|enum|implements|extends|augments|import)\b|@(param|returns?|property|prop|this)\s*\{/;
const isPlainJs = (path) => /\.(m?js|cjs|jsx)$/.test(path);

function kindOf(path) {
  if (path.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (/\.[mc]?ts$/.test(path)) return ts.ScriptKind.TS;
  return ts.ScriptKind.JSX;
}

function contentLines(body) {
  return body.startsWith("/*")
    ? body.slice(2, -2).split(/\r\n|\n|\r/).map((l) => l.replace(/^\s*\*+/, "").trimStart())
    : [body.replace(/^\/+/, "").trimStart()];
}

function scopeOf(path, body) {
  if (ALLOW_RE.some((r) => r.test(body))) return "file";
  const lines = contentLines(body);
  if (body.startsWith("/*") && BLOCK_DIRECTIVE.test(lines.find((l) => l.trim()) ?? "")) return "file";
  if (lines.some((l) => DIRECTIVE.test(l))) return lines.some((l) => FILE_SCOPED.test(l)) ? "file" : "line";
  return isPlainJs(path) && body.startsWith("/**") && JSDOC_TYPES.test(body) ? "line" : null;
}
const isAllowed = (path, body) => scopeOf(path, body) !== null;

const K = ts.SyntaxKind;
const isJsDoc = (n) => n.kind >= K.FirstJSDocNode && n.kind <= K.LastJSDocNode;
const kidsOf = (n, sf) => n.getChildren(sf).filter((c) => !isJsDoc(c));
const isJsxParent = (n) => n && (n.kind === K.JsxElement || n.kind === K.JsxFragment);
const isEmptyExpr = (n) => n.kind === K.JsxExpression && !n.expression && !n.dotDotDotToken;

// A JsxText starting with // or /* is text, yet the trivia scanners read it as a comment.
function jsxTextStarts(sf) {
  const out = [];
  const visit = (n) => {
    if (n.kind === K.JsxText) out.push([n.pos, n.end]);
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

function hasJsx(sf) {
  const visit = (n) => n.kind === K.JsxElement || n.kind === K.JsxSelfClosingElement || n.kind === K.JsxFragment
    || ts.forEachChild(n, visit);
  return !!visit(sf);
}

function lastAtOrBefore(sorted, x, key = (v) => v) {
  let lo = 0, hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (key(sorted[mid]) <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo - 1;
}

function collectComments(sf) {
  const text = sf.text;
  const jsxTexts = jsxTextStarts(sf);
  const inJsxText = (pos) => {
    const i = lastAtOrBefore(jsxTexts, pos, (r) => r[0]);
    return i >= 0 && pos < jsxTexts[i][1];
  };
  const seen = new Map();
  const add = (ranges) => {
    for (const r of ranges || []) if (!seen.has(r.pos) && !inJsxText(r.pos)) seen.set(r.pos, r);
  };
  const visit = (node) => {
    if (node.kind !== K.JsxText) add(ts.getLeadingCommentRanges(text, node.pos));
    add(ts.getTrailingCommentRanges(text, node.end));
    for (const c of kidsOf(node, sf)) visit(c);
  };
  visit(sf);
  return [...seen.values()].sort((a, b) => a.pos - b.pos);
}

function cleanJsxText(raw) {
  const lines = raw.split(/\r\n|\n|\r/);
  let out = "";
  lines.forEach((line, i) => {
    let l = line;
    if (i !== 0) l = l.replace(/^[ \t]+/, "");
    if (i !== lines.length - 1) l = l.replace(/[ \t]+$/, "");
    if (l) out += (out && i !== 0 ? " " : "") + l;
  });
  return out;
}

function jsxKids(node) {
  return node.kind === K.JsxElement
    ? [node.openingElement, ...node.children, node.closingElement]
    : [node.openingFragment, ...node.children, node.closingFragment];
}

function signature(sf) {
  const out = [];
  const visit = (node) => {
    if (isJsxParent(node)) {
      out.push("(" + K[node.kind]);
      for (const k of jsxKids(node)) {
        if (k.kind === K.JsxText) {
          const t = cleanJsxText(k.text);
          if (t) out.push("JsxText:" + JSON.stringify(t));
        } else if (!isEmptyExpr(k)) visit(k);
      }
      out.push(")");
      return;
    }
    const kids = kidsOf(node, sf);
    if (kids.length === 0) {
      out.push(K[node.kind] + ":" + node.getText(sf));
      return;
    }
    out.push("(" + K[node.kind]);
    for (const k of kids) visit(k);
    out.push(")");
  };
  visit(sf);
  return out.join(" ");
}

function leafStarts(sf) {
  const out = [];
  const visit = (node, parent) => {
    if (node.kind === K.JsxText) return;
    if (parent && isEmptyExpr(parent)) return;
    const kids = kidsOf(node, sf);
    if (kids.length === 0) out.push(node.getStart(sf));
    for (const k of kids) visit(k, node);
  };
  visit(sf, null);
  return out;
}

// Python slices by code point; TS positions are UTF-16 units.
function codePointMap(text) {
  if (!/[\uD800-\uDFFF]/.test(text)) return (x) => x;
  const map = new Int32Array(text.length + 1);
  let cp = 0;
  for (let i = 0; i < text.length; i++) {
    map[i] = cp;
    const c = text.charCodeAt(i);
    if (!(c >= 0xd800 && c <= 0xdbff && i + 1 < text.length)) cp++;
    else { map[i + 1] = cp; i++; cp++; }
  }
  map[text.length] = cp;
  return (x) => map[x];
}

function prunableRanges(sf, path, comments, leaves) {
  const text = sf.text;
  const wrapped = new Map();
  const keep = new Set();
  for (const r of comments) {
    if (scopeOf(path, text.slice(r.pos, r.end)) !== "line") continue;
    const next = leaves[lastAtOrBefore(leaves, r.end - 1) + 1] ?? Infinity;
    for (const o of comments) if (o.pos >= r.end && o.pos < next) keep.add(o.pos);
  }
  const visit = (node) => {
    const parent = node.parent;
    if (isEmptyExpr(node) && isJsxParent(parent)) {
      const at = node.getStart(sf) + 1;
      const rs = [...(ts.getTrailingCommentRanges(text, at) || []), ...(ts.getLeadingCommentRanges(text, at) || [])]
        .filter((r, i, all) => all.findIndex((o) => o.pos === r.pos) === i);
      const kids = jsxKids(parent);
      let a = kids.indexOf(node), b = a;
      while (a > 0 && isEmptyExpr(kids[a - 1])) a--;
      while (b < kids.length - 1 && isEmptyExpr(kids[b + 1])) b++;
      const prev = kids[a - 1], next = kids[b + 1];
      const textual = (k) => k && k.kind === K.JsxText && cleanJsxText(k.text) !== "";
      if (textual(prev) && textual(next)) {
        for (const r of rs) keep.add(r.pos);
      } else {
        const inner = text.slice(node.getStart(sf) + 1, node.end - 1);
        const covered = rs.reduce((s, r) => s.replace(text.slice(r.pos, r.end), ""), inner);
        if (rs.length && !covered.trim() && rs.every((r) => !isAllowed(path, text.slice(r.pos, r.end)))) {
          for (const r of rs) wrapped.set(r.pos, [node.getStart(sf), node.end]);
        }
      }
    }
    for (const c of kidsOf(node, sf)) visit(c);
  };
  visit(sf);
  const out = [];
  const done = new Set();
  for (const r of comments) {
    if (isAllowed(path, text.slice(r.pos, r.end)) || keep.has(r.pos)) continue;
    const w = wrapped.get(r.pos);
    if (w) {
      if (!done.has(w[0])) out.push(w);
      done.add(w[0]);
    } else out.push([r.pos, r.end]);
  }
  return out;
}

const EMIT = { removeComments: true, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext };
const transpile = (path, text) => ts.transpileModule(text, { fileName: path, compilerOptions: EMIT, reportDiagnostics: true });
const diagText = (ds) => ds.slice(0, 2).map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n")).join("; ");
const input = JSON.parse(readFileSync(0, "utf8"));
const mode = process.argv[2] || "count";
const result = {};
function scanFile(path, text) {
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kindOf(path));
  const diags = (sf.parseDiagnostics || []).map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
  if (diags.length) return { error: `TS parse: ${diags.slice(0, 2).join("; ")}` };
  if (/\.[mc]js$/.test(path) && hasJsx(sf)) return { error: "JSX in .mjs/.cjs: node cannot parse it" };
  const emits = !/\.d\.[mc]?ts$/.test(path);
  const out = (mode === "dump" && emits) || isPlainJs(path) ? transpile(path, text) : null;
  if (out && out.diagnostics.length) return { error: `TS parse: ${diagText(out.diagnostics)}` };
  const cp = codePointMap(text);
  const lineOf = (pos) => sf.getLineAndCharacterOfPosition(pos).line + 1;
  const leaves = leafStarts(sf);
  const comments = collectComments(sf);
  const rows = [];
  const shebang = ts.getShebang(text);
  if (shebang) rows.push([0, cp(shebang.length), 1, 1, true, 0, true, shebang, 0]);
  for (const r of comments) {
    const body = text.slice(r.pos, r.end);
    const allowed = isAllowed(path, body);
    const own = /^[ \t]*$/.test(text.slice(text.lastIndexOf("\n", r.pos - 1) + 1, r.pos));
    const anchor = lastAtOrBefore(leaves, r.pos - 1) + 1;
    const gap = scopeOf(path, body) === "line" ? (anchor < leaves.length ? lineOf(leaves[anchor]) - lineOf(r.end) : -1) : 0;
    rows.push([cp(r.pos), cp(r.end), lineOf(r.pos), lineOf(r.end), allowed, anchor, own, allowed ? body : "", gap]);
  }
  const entry = { comments: rows };
  if (mode === "ranges") entry.ranges = prunableRanges(sf, path, comments, leaves).map(([a, b]) => [cp(a), cp(b)]);
  if (mode === "dump") {
    entry.sig = signature(sf);
    entry.emit = out ? out.outputText : "";
  }
  return entry;
}

for (const { path, text } of input) {
  try {
    result[path] = scanFile(path, text);
  } catch (e) {
    result[path] = { error: `comment_tools: ${e && e.message ? e.message : e}` };
  }
}
process.stdout.write(JSON.stringify(result));
