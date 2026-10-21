"use client";

/**
 * New post's Format text panel (new-post/state-format-text, OF's TextEditorToolbar) and the markup it leaves in the post
 * text. OF's composer is a tiptap editor whose getHTML() is the post's `text` (MakeFeedPost onUpdate; build
 * 202610091632): one `<p>` per paragraph, `<br>` inside one, Bold as `<strong>`, Italic as `<em>`, and Text Color and
 * Text Size as one `textStyle` mark, a `<span>` whose class holds OF's classes (`m-editor-fc__gray | __blue-1 |
 * __blue-2 | __default`, `m-editor-fs__lg | __l | __default | __s | __sm`); its sanitizer allows only strong, span, em, br
 * and p, and the class attribute. The marks' nesting order (strong, then em, then span) is ASSUMED from tiptap's schema
 * order (StarterKit's bold and italic before textStyle); OF's server reads the same tags either way.
 *
 * In the mirror's editor the browser's own editing commands do the work (bold, italic, foreColor, fontSize,
 * removeFormat), and `normalize` turns what they leave (b, i, font) into OF's markup at once, so the editor always holds
 * OF's tags and classes (the mirrored stylesheet draws them). `ofHtml` serializes the editor the way tiptap does.
 */

/** OF's text colours (TEXT_EDITOR Yc.LIST: its cssValue -> class; the divider dropped) and sizes (Aw.LIST). */
export const COLORS = [
  { cls: "m-editor-fc__gray", css: "#8a96a3", label: "Grey" },
  { cls: "m-editor-fc__blue-1", css: "#00aff0", label: "Light blue" },
  { cls: "m-editor-fc__blue-2", css: "#1b98e0", label: "Medium blue" },
  { cls: "m-editor-fc__default", css: "", label: "Default" },
] as const;
/** OF's sizes, largest first; `font` is the legacy <font size> the browser's fontSize command writes for each. */
export const SIZES = [
  { cls: "m-editor-fs__lg", font: "7", label: "Largest" },
  { cls: "m-editor-fs__l", font: "6", label: "Large" },
  { cls: "m-editor-fs__default", font: "3", label: "Default" },
  { cls: "m-editor-fs__s", font: "2", label: "Small" },
  { cls: "m-editor-fs__sm", font: "1", label: "Smallest" },
] as const;
/** Only OF's own class names count: a pasted class like `m-editor-fc__x"onclick="…` is not one, so it never reaches the markup. */
const COLOR_CLASSES: ReadonlySet<string> = new Set(COLORS.map((c) => c.cls));
const SIZE_CLASSES: ReadonlySet<string> = new Set(SIZES.map((s) => s.cls));
const COLOR_RE = { test: (c: string) => COLOR_CLASSES.has(c) };
const SIZE_RE = { test: (c: string) => SIZE_CLASSES.has(c) };

const hex = (c: string): string => {
  const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c.trim());
  if (!m) return c.trim().toLowerCase();
  return `#${[m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
};
/** A colour (hex or rgb) as OF's class (its PASTE_CONVERT_MATRIX), or null. */
export const colorClass = (c: string | null | undefined): string | null => (c ? (COLORS.find((x) => x.css && x.css === hex(c))?.cls ?? null) : null);
const sizeClass = (n: string | null) => SIZES.find((s) => s.font === n)?.cls ?? null;

/** The OF classes an element carries (a span's own, a <font>'s colour and size, an inline style colour). */
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

/**
 * Rewrite the browser's editing leftovers in `root` into OF's markup: b -> strong, i -> em, font and styled spans -> a
 * span with OF's classes (none: unwrapped), any other inline element unwrapped. Paragraphs and line breaks stay.
 */
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
  // Deepest first, so a replaced parent never strands a child.
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
  // A browser's <div> line in a contenteditable is OF's <p>.
  for (const div of [...root.querySelectorAll(":scope > div")]) swap(div, "p");
}

interface Run {
  text: string;
  bold: boolean;
  italic: boolean;
  classes: string;
  br?: boolean;
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;");
/** An attribute value: the whitelisted classes need none of this, but a quote can never close the attribute. */
const escapeAttr = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** A paragraph's text runs, each with the marks its ancestors (up to `p`) give it. */
function runsOf(p: Node): Run[] {
  const runs: Run[] = [];
  const walk = (n: Node, bold: boolean, italic: boolean, color: string | null, size: string | null) => {
    if (n.nodeType === 3) {
      const text = n.textContent ?? "";
      if (text) runs.push({ text, bold, italic, classes: [color, size].filter(Boolean).join(" ") });
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

function runHtml(r: Run): string {
  if (r.br) return "<br>";
  let h = escape(r.text);
  if (r.classes) h = `<span class="${escapeAttr(r.classes)}">${h}</span>`;
  if (r.italic) h = `<em>${h}</em>`;
  if (r.bold) h = `<strong>${h}</strong>`;
  return h;
}

/** The editor's paragraphs (a bare text or inline child is one paragraph, as tiptap parses it). */
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

/**
 * The editor as OF's post text (tiptap's getHTML): `<p>` per paragraph, an empty one `<p></p>`, each run of equally
 * marked text as `<strong><em><span class="...">text</span></em></strong>` (the marks it has). A trailing <br> that a
 * browser keeps in an empty paragraph is dropped.
 */
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
      return `<p>${merged.map(runHtml).join("")}</p>`;
    })
    .join("");
}

/** Whether the editor holds any of OF's formatting (else the post goes as plain text, as before formatting existed). */
export const hasFormatting = (root: Element): boolean => paragraphs(root).some((p) => runsOf(p).some((r) => !r.br && (r.bold || r.italic || !!r.classes)));

/**
 * OF's markup (a saved draft's) back into `root`: only p, br, strong, em and span with OF's classes are kept (b and i as
 * strong and em); anything else is unwrapped to its text, so a draft can never inject markup into the frame.
 */
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
  // An empty paragraph keeps a <br>, so the caret has a line to sit on.
  for (const p of root.querySelectorAll("p")) if (!p.childNodes.length) p.append(doc.createElement("br"));
}

// ---------------------------------------------------------------- the panel

export type FormatCommand = { kind: "bold" } | { kind: "italic" } | { kind: "clear" } | { kind: "color"; cls: string } | { kind: "size"; cls: string };

/**
 * Apply `cmd` to the editor's selection with the browser's editing commands, then `normalize`. Text Color "Default" and
 * Text Size "Default" set OF's own default classes, as OF's toggleClass does. Clear Formatting also unwraps OF's spans
 * inside the selection. Returns whether the browser ran it (a collapsed or outside selection: nothing to format).
 */
export function applyFormat(editor: HTMLElement, cmd: FormatCommand): boolean {
  const doc = editor.ownerDocument;
  const sel = doc.getSelection();
  if (!sel || !sel.rangeCount || sel.isCollapsed || !editor.contains(sel.getRangeAt(0).commonAncestorContainer)) return false;
  const run = (name: string, value?: string) => doc.execCommand(name, false, value);
  run("styleWithCSS", "false");
  let ok = false;
  if (cmd.kind === "bold") ok = run("bold");
  else if (cmd.kind === "italic") ok = run("italic");
  else if (cmd.kind === "color") ok = run("foreColor", COLORS.find((c) => c.cls === cmd.cls)?.css || "#000001");
  else if (cmd.kind === "size") ok = run("fontSize", SIZES.find((s) => s.cls === cmd.cls)?.font ?? "3");
  else {
    const range = sel.getRangeAt(0);
    ok = run("removeFormat");
    for (const span of [...editor.querySelectorAll("span, strong, em")]) {
      if (range.intersectsNode(span) && sel.containsNode(span, false)) span.replaceWith(...span.childNodes);
    }
  }
  // The default colour: the browser wrote OF's placeholder #000001; it is OF's m-editor-fc__default.
  if (cmd.kind === "color" && !COLORS.find((c) => c.cls === cmd.cls)?.css) {
    for (const f of editor.querySelectorAll("font[color='#000001']")) {
      f.removeAttribute("color");
      f.classList.add("m-editor-fc__default");
    }
  }
  // normalize rebuilds the nodes; keep the selection (by text offsets), so a second tool formats the same words.
  const at = textOffsets(editor, sel);
  normalize(editor);
  if (at) restoreOffsets(editor, sel, at);
  return ok;
}

function textOffsets(root: Element, sel: Selection): [number, number] | null {
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

function restoreOffsets(root: Element, sel: Selection, [start, end]: [number, number]): void {
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
