import {
  COLOR_CLASSES, colorClass, commandState, execCommand, execFormat, hasFormatting, normalize, ofHtml, restoreOffsets,
  SIZE_CLASSES, textOffsets, type FormatCommand,
} from "@/lib/ofMirrorFormat";
import {
  decodeEntities, foldBlankParagraphs, hasHtml, hasOfFormatting, ofPlain, ofText, plainToOfHtml, sanitizeOfHtml,
} from "@/lib/ofRichText";

export const editorHtmlOf = (value: string): string => (hasHtml(value) ? ofText(value) : plainToOfHtml(value));

const GAP = "\u200b";

export const editorPlain = (html: string): string =>
  decodeEntities(html.replace(/^<p>|<\/p>$/g, "").replace(/<\/p><p>|<br>/g, "\n").replace(/<[^>]*>/g, ""))
    .replace(/\u00a0/g, " ");

export function editorValue(root: Element): string {
  const html = ofHtml(root).replaceAll(GAP, "");
  if (hasFormatting(root)) return foldBlankParagraphs(html);
  const plain = editorPlain(html);
  return hasHtml(plain) ? foldBlankParagraphs(html) : plain;
}

export function clearAtCaret(root: Element, sel: Selection): boolean {
  if (!sel.rangeCount || !sel.isCollapsed) return false;
  const r = sel.getRangeAt(0);
  if (!root.contains(r.startContainer)) return false;
  let top: Element | null = null;
  for (let n: Node | null = r.startContainer; n && n !== root; n = n.parentNode) {
    if (n.nodeType !== 1) continue;
    if (/^(P|DIV)$/.test((n as Element).tagName)) break;
    top = n as Element;
  }
  if (!top) return false;
  const doc = root.ownerDocument;
  const right = doc.createRange();
  right.setStart(r.startContainer, r.startOffset);
  right.setEndAfter(top);
  const tail = right.extractContents();
  const gap = doc.createTextNode(GAP);
  top.after(gap);
  if (tail.textContent) gap.after(tail);
  if (!top.textContent) top.remove();
  const at = doc.createRange();
  at.setStart(gap, 1);
  at.collapse(true);
  sel.removeAllRanges();
  sel.addRange(at);
  return true;
}

export function formatAtCaret(root: Element, sel: Selection, cmd: FormatCommand): boolean {
  const doc = root.ownerDocument;
  if (cmd.kind !== "clear") return execFormat(doc, cmd);
  if (clearAtCaret(root, sel)) return true;
  const b = commandState(doc, "bold") && execCommand(doc, "bold");
  const i = commandState(doc, "italic") && execCommand(doc, "italic");
  return b || i;
}

const PX_SIZE: Record<string, string> = {
  "26px": "m-editor-fs__lg", "20px": "m-editor-fs__l", "14px": "m-editor-fs__s", "12px": "m-editor-fs__sm",
};

export function pastedOfHtml(html: string, doc: Document): string | null {
  const tpl = doc.createElement("template");
  tpl.innerHTML = html;
  for (const el of tpl.content.querySelectorAll<HTMLElement>("[style], font")) {
    const add = [colorClass(el.style?.color || el.getAttribute("color")), PX_SIZE[el.style?.fontSize ?? ""]]
      .filter(Boolean) as string[];
    if (!add.length) continue;
    const span = doc.createElement("span");
    span.className = add.join(" ");
    span.append(...el.childNodes);
    el.append(span);
  }
  const out = sanitizeOfHtml(tpl.innerHTML);
  return hasOfFormatting(out) ? out : null;
}

export const cutTo = (text: string, n: number): string => {
  let end = Math.max(0, n);
  const c = text.charCodeAt(end);
  if (end > 0 && c >= 0xdc00 && c <= 0xdfff) end -= 1;
  return text.slice(0, end);
};

export const plainLength = (value: string): number => ofPlain(value).length;

const LEFTOVERS = "b, i, font, div, span[style], strong[style], em[style], span:not([class])";

export function tidy(root: HTMLElement): void {
  if (!root.querySelector(LEFTOVERS)) return;
  const sel = root.ownerDocument.getSelection();
  const at = sel ? textOffsets(root, sel) : null;
  normalize(root);
  if (sel && at) restoreOffsets(root, sel, at);
}

export interface Marks {
  bold: boolean;
  italic: boolean;
  color: string | null;
  size: string | null;
}
export const NO_MARKS: Marks = { bold: false, italic: false, color: null, size: null };

export function marksAt(root: Element, node: Node | null): Marks {
  if (!node || !root.contains(node)) return NO_MARKS;
  const m: Marks = { ...NO_MARKS };
  for (let n: Node | null = node; n && n !== root; n = n.parentNode) {
    if (n.nodeType !== 1) continue;
    const el = n as Element;
    const tag = el.tagName;
    if (tag === "STRONG" || tag === "B") m.bold = true;
    if (tag === "EM" || tag === "I") m.italic = true;
    for (const c of el.classList) {
      if (!m.color && COLOR_CLASSES.has(c)) m.color = c;
      if (!m.size && SIZE_CLASSES.has(c)) m.size = c;
    }
  }
  return m;
}
