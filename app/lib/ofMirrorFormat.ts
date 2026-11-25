"use client";


export const COLORS = [
  { cls: "m-editor-fc__gray", css: "#8a96a3", label: "Grey" },
  { cls: "m-editor-fc__blue-1", css: "#00aff0", label: "Light blue" },
  { cls: "m-editor-fc__blue-2", css: "#1b98e0", label: "Medium blue" },
  { cls: "m-editor-fc__default", css: "", label: "Default" },
] as const;
export const SIZES = [
  { cls: "m-editor-fs__lg", font: "7", label: "Largest" },
  { cls: "m-editor-fs__l", font: "6", label: "Large" },
  { cls: "m-editor-fs__default", font: "3", label: "Default" },
  { cls: "m-editor-fs__s", font: "2", label: "Small" },
  { cls: "m-editor-fs__sm", font: "1", label: "Smallest" },
] as const;
export const COLOR_CLASSES: ReadonlySet<string> = new Set(COLORS.map((c) => c.cls));
export const SIZE_CLASSES: ReadonlySet<string> = new Set(SIZES.map((s) => s.cls));
const COLOR_RE = { test: (c: string) => COLOR_CLASSES.has(c) };
const SIZE_RE = { test: (c: string) => SIZE_CLASSES.has(c) };

const hex = (c: string): string => {
  const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c.trim());
  if (!m) return c.trim().toLowerCase();
  return `#${[m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
};
const DEFAULT_CSS = "#000001";
export const colorClass = (c: string | null | undefined): string | null => {
  if (!c) return null;
  const h = hex(c);
  return h === DEFAULT_CSS ? "m-editor-fc__default" : COLORS.find((x) => x.css && x.css === h)?.cls ?? null;
};
const sizeClass = (n: string | null) => SIZES.find((s) => s.font === n)?.cls ?? null;

function classesOf(el: Element): string[] {
  const out = [...el.classList].filter((c) => COLOR_RE.test(c) || SIZE_RE.test(c));
  if (el.tagName === "FONT") {
    const c = colorClass(el.getAttribute("color"));
    const s = sizeClass(el.getAttribute("size"));
    if (c) out.push(c);
    if (s) out.push(s);
  }
  const styled = colorClass((el as HTMLElement).style?.color);
  if (styled && !out.some((c) => COLOR_RE.test(c))) out.push(styled);
  return out;
}

export function normalize(root: Element): void {
  const doc = root.ownerDocument;
  const swap = (el: Element, tag: string, cls?: string[]) => {
    const n = doc.createElement(tag);
    if (cls?.length) n.className = cls.join(" ");
    while (el.firstChild) n.append(el.firstChild);
    el.replaceWith(n);
    return n;
  };
  const unwrap = (el: Element) => el.replaceWith(...el.childNodes);
  for (const el of [...root.querySelectorAll("*")].reverse()) {
    const tag = el.tagName;
    if (tag === "P" || tag === "BR" || tag === "DIV") continue;
    if (tag === "B") swap(el, "strong");
    else if (tag === "I") swap(el, "em");
    else if (tag === "STRONG" || tag === "EM") el.removeAttribute("style");
    else if (tag === "FONT" || tag === "SPAN") {
      const cls = [...new Set(classesOf(el))];
      if (!cls.length) unwrap(el);
      else if (tag === "FONT") swap(el, "span", cls);
      else {
        el.className = cls.join(" ");
        el.removeAttribute("style");
      }
    } else unwrap(el);
  }
  for (const div of [...root.querySelectorAll(":scope > div")]) swap(div, "p");
}

export interface Run {
  text: string;
  bold: boolean;
  italic: boolean;
  classes: string;
  br?: boolean;
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;");
const escapeAttr = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function runsOf(p: Node): Run[] {
  const runs: Run[] = [];
  const walk = (n: Node, bold: boolean, italic: boolean, color: string | null, size: string | null) => {
    if (n.nodeType === 3) {
      const text = n.textContent ?? "";
      if (text) runs.push({ text, bold, italic, classes: [size, color].filter(Boolean).join(" ") });
      return;
    }
    if (n.nodeType !== 1) return;
    const el = n as Element;
    if (el.tagName === "BR") return void runs.push({ text: "", bold, italic, classes: "", br: true });
    const cls = classesOf(el);
    const c = cls.find((x) => COLOR_RE.test(x)) ?? color;
    const s = cls.find((x) => SIZE_RE.test(x)) ?? size;
    const b = bold || el.tagName === "STRONG" || el.tagName === "B";
    const i = italic || el.tagName === "EM" || el.tagName === "I";
    for (const child of el.childNodes) walk(child, b, i, c, s);
  };
  for (const child of p.childNodes) walk(child, false, false, null, null);
  return runs;
}

const sameMarks = (a: Run, b: Run) => !a.br && !b.br && a.bold === b.bold && a.italic === b.italic && a.classes === b.classes;

export function runsHtml(runs: readonly Run[]): string {
  let out = "";
  const open: string[] = [];
  for (const r of runs) {
    // OF's measured wire nesting: span outermost, size class before colour, em inside strong.
    const want = r.br ? [] : [r.classes ? `span ${r.classes}` : "", r.bold ? "strong" : "", r.italic ? "em" : ""].filter(Boolean);
    let keep = 0;
    while (keep < open.length && keep < want.length && open[keep] === want[keep]) keep++;
    while (open.length > keep) out += `</${open.pop()!.split(" ")[0]}>`;
    for (const m of want.slice(keep)) {
      out += m.startsWith("span ") ? `<span class="${escapeAttr(m.slice(5))}">` : `<${m}>`;
      open.push(m);
    }
    out += r.br ? "<br>" : escape(r.text);
  }
  while (open.length) out += `</${open.pop()!.split(" ")[0]}>`;
  return out;
}

function paragraphs(root: Element): Node[] {
  const out: Node[] = [];
  let loose: Node[] = [];
  const flush = () => {
    if (!loose.length) return;
    const p = root.ownerDocument.createElement("p");
    for (const n of loose) p.append(n.cloneNode(true));
    out.push(p);
    loose = [];
  };
  for (const n of root.childNodes) {
    if (n.nodeType === 1 && ((n as Element).tagName === "P" || (n as Element).tagName === "DIV")) {
      flush();
      out.push(n);
    } else if (n.nodeType === 3 || n.nodeType === 1) loose.push(n);
  }
  flush();
  return out;
}

export function ofHtml(root: Element): string {
  return paragraphs(root)
    .map((p) => {
      const runs = runsOf(p);
      if (runs.length === 1 && runs[0].br) runs.length = 0;
      const merged: Run[] = [];
      for (const r of runs) {
        const last = merged.at(-1);
        if (last && sameMarks(last, r)) last.text += r.text;
        else merged.push({ ...r });
      }
      return `<p>${runsHtml(merged)}</p>`;
    })
    .join("");
}

export const hasFormatting = (root: Element): boolean => paragraphs(root).some((p) => runsOf(p).some((r) => !r.br && (r.bold || r.italic || !!r.classes)));

export const DROP_CONTENT = /^(script|style|template|noscript|iframe|object|textarea|title|head)$/i;

export function setOfHtml(root: Element, html: string): void {
  const doc = root.ownerDocument;
  const tpl = doc.createElement("template");
  tpl.innerHTML = html;
  const clean = (from: Node, to: Node) => {
    for (const n of from.childNodes) {
      if (n.nodeType === 3) {
        to.appendChild(doc.createTextNode(n.textContent ?? ""));
        continue;
      }
      if (n.nodeType !== 1) continue;
      const el = n as Element;
      // Never text (a script's code): dropped whole, as OF's sanitizer and the relay do.
      if (DROP_CONTENT.test(el.tagName)) continue;
      const tag = { P: "p", BR: "br", STRONG: "strong", B: "strong", EM: "em", I: "em", SPAN: "span" }[el.tagName];
      if (!tag) {
        clean(el, to);
        continue;
      }
      const out = doc.createElement(tag);
      if (tag === "span") {
        const cls = [...el.classList].filter((c) => COLOR_RE.test(c) || SIZE_RE.test(c));
        if (!cls.length) {
          clean(el, to);
          continue;
        }
        out.className = cls.join(" ");
      }
      to.appendChild(out);
      if (tag !== "br") clean(el, out);
    }
  };
  const frag = doc.createDocumentFragment();
  clean(tpl.content, frag);
  root.replaceChildren(frag);
  for (const p of root.querySelectorAll("p")) if (!p.childNodes.length) p.append(doc.createElement("br"));
}


export type FormatCommand = { kind: "bold" } | { kind: "italic" } | { kind: "clear" } | { kind: "color"; cls: string } | { kind: "size"; cls: string };

export const execCommand = (doc: Document | undefined, name: string, value?: string): boolean =>
  typeof doc?.execCommand === "function" ? doc.execCommand(name, false, value) : false;
export const commandState = (doc: Document | undefined, name: string): boolean => {
  try { return typeof doc?.queryCommandState === "function" && doc.queryCommandState(name); } catch { return false; }
};

export function execFormat(doc: Document, cmd: Exclude<FormatCommand, { kind: "clear" }>): boolean {
  execCommand(doc, "styleWithCSS", "false");
  if (cmd.kind === "bold" || cmd.kind === "italic") return execCommand(doc, cmd.kind);
  if (cmd.kind === "color") return execCommand(doc, "foreColor", COLORS.find((c) => c.cls === cmd.cls)?.css || DEFAULT_CSS);
  return execCommand(doc, "fontSize", SIZES.find((s) => s.cls === cmd.cls)?.font ?? "3");
}

export function applyFormat(editor: HTMLElement, cmd: FormatCommand): boolean {
  const doc = editor.ownerDocument;
  const sel = doc.getSelection();
  if (!sel || !sel.rangeCount || sel.isCollapsed || !editor.contains(sel.getRangeAt(0).commonAncestorContainer)) return false;
  let ok = false;
  if (cmd.kind !== "clear") ok = execFormat(doc, cmd);
  else {
    const range = sel.getRangeAt(0);
    execCommand(doc, "styleWithCSS", "false");
    ok = execCommand(doc, "removeFormat");
    for (const span of [...editor.querySelectorAll("span, strong, em")]) {
      if (range.intersectsNode(span) && sel.containsNode(span, false)) span.replaceWith(...span.childNodes);
    }
  }
  const at = textOffsets(editor, sel);
  normalize(editor);
  if (at) restoreOffsets(editor, sel, at);
  return ok;
}

export function textOffsets(root: Element, sel: Selection): [number, number] | null {
  if (!sel.rangeCount) return null;
  const r = sel.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return null;
  const upTo = (node: Node, offset: number) => {
    const pre = root.ownerDocument.createRange();
    pre.selectNodeContents(root);
    pre.setEnd(node, offset);
    return pre.toString().length;
  };
  return [upTo(r.startContainer, r.startOffset), upTo(r.endContainer, r.endOffset)];
}

export function restoreOffsets(root: Element, sel: Selection, [start, end]: [number, number]): void {
  const doc = root.ownerDocument;
  const walk = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = doc.createRange();
  let seen = 0;
  let began = false;
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const len = n.textContent?.length ?? 0;
    if (!began && start <= seen + len) {
      range.setStart(n, start - seen);
      began = true;
    }
    if (began && end <= seen + len) {
      range.setEnd(n, end - seen);
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
    seen += len;
  }
}
