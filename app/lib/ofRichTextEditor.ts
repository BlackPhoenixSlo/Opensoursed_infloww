/**
 * The script editor's value contract (components/ui/OfRichTextEditor), on top of ofMirrorFormat's contenteditable
 * model (normalize, ofHtml, setOfHtml, hasFormatting):
 *   • the value is OF markup only while the editor holds formatting (`foldBlankParagraphs` as Infloww saves it),
 *     else the plain text, one line per paragraph or `<br>`: an unformatted script stays the plain text it always was.
 *     The plain text is what was typed: never trimmed, leading/trailing empty lines kept; the one rewrite is the
 *     no-break space a contenteditable puts in for runs of spaces, which reads back as a plain space;
 *   • plain text loads as one paragraph per line; anything the relay rewrites (`hasHtml`: markup, bare tags in an
 *     imported cell, a text it escapes whole) loads as the relay will send it (`ofText`);
 *   • the caret's marks light the toolbar (`marksAt`).
 */
import {
  COLOR_CLASSES, colorClass, commandState, execCommand, execFormat, hasFormatting, normalize, ofHtml, restoreOffsets,
  SIZE_CLASSES, textOffsets, type FormatCommand,
} from "@/lib/ofMirrorFormat";
import {
  decodeEntities, foldBlankParagraphs, hasHtml, hasOfFormatting, ofPlain, ofText, plainToOfHtml, sanitizeOfHtml,
} from "@/lib/ofRichText";

/** What the editor loads for a value: what the relay rewrites as it sends it (allow-list, blocks as lines, a text that
 *  fails closed as its literal text), plain text as lines. */
export const editorHtmlOf = (value: string): string => (hasHtml(value) ? ofText(value) : plainToOfHtml(value));

/** The caret's gap `clearAtCaret` leaves: never part of the value. */
const GAP = "\u200b";

/** `ofHtml`'s output (`<p>` per line, `<br>`, escaped text) as the plain text typed: untrimmed, U+00A0 as a space. */
export const editorPlain = (html: string): string =>
  decodeEntities(html.replace(/^<p>|<\/p>$/g, "").replace(/<\/p><p>|<br>/g, "\n").replace(/<[^>]*>/g, ""))
    .replace(/\u00a0/g, " ");

/** The editor's value: OF markup while it has formatting, else its plain text. Plain text the relay would read as
 *  markup (`hasHtml`: a typed `<p>Use <VIP20></p>` or `Use <b>bold</b> literally`) stays escaped markup, so it loads
 *  and sends as the text it is. */
export function editorValue(root: Element): string {
  const html = ofHtml(root).replaceAll(GAP, "");
  if (hasFormatting(root)) return foldBlankParagraphs(html);
  const plain = editorPlain(html);
  return hasHtml(plain) ? foldBlankParagraphs(html) : plain;
}

/**
 * Clear formatting at a caret (no selection) inside formatted text: the marks around it (bold, italic, a colour or size
 * span) are split at the caret and the caret goes between them, in a gap of its own, so the next letters are plain
 * (OF's clearFormatting on an empty selection). False when the caret is in no mark (nothing to split).
 */
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
  const tail = right.extractContents(); // the formatted rest, under its own copy of the marks
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

/**
 * A tool on a caret (no selection), as OF's editor sets a stored mark: B, I, a colour or a size arms the browser's
 * typing style, so the next letters carry it; Clear splits the marks around the caret (`clearAtCaret`) or, with none,
 * drops an armed bold / italic. False where the browser has no editing commands (jsdom) or nothing changed.
 */
export function formatAtCaret(root: Element, sel: Selection, cmd: FormatCommand): boolean {
  const doc = root.ownerDocument;
  if (cmd.kind !== "clear") return execFormat(doc, cmd);
  if (clearAtCaret(root, sel)) return true;
  const b = commandState(doc, "bold") && execCommand(doc, "bold");
  const i = commandState(doc, "italic") && execCommand(doc, "italic");
  return b || i;
}

/** Inline font sizes OF's paste filter maps to its classes (docs/infloww-rich-text-rea.md §1, Paste). */
const PX_SIZE: Record<string, string> = {
  "26px": "m-editor-fs__lg", "20px": "m-editor-fs__l", "14px": "m-editor-fs__s", "12px": "m-editor-fs__sm",
};

/**
 * A clipboard's text/html as OF markup, as OF's paste filter keeps it: inline colours and sizes OF knows become its
 * classes, then the allow-list (strong, em, span with OF's classes, p, br; li / div / h1-h6 as paragraphs) drops the
 * rest. Null when nothing formatted is left (the paste goes in as plain text).
 */
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

/** `text` cut to `n` UTF-16 units (what the limit counts), never between a surrogate pair's halves (an emoji). */
export const cutTo = (text: string, n: number): string => {
  let end = Math.max(0, n);
  const c = text.charCodeAt(end);
  if (end > 0 && c >= 0xdc00 && c <= 0xdfff) end -= 1;
  return text.slice(0, end);
};

/** A value's plain length (the 6500 limit and the counter count what the fan reads). */
export const plainLength = (value: string): number => ofPlain(value).length;

/** What the browser's editing leaves that is not OF's markup yet (a typed run after B on an empty selection, a
 *  pasted or Enter-made div). */
const LEFTOVERS = "b, i, font, div, span[style], strong[style], em[style], span:not([class])";

/** `normalize` when the browser left something of its own, keeping the caret (by text offsets). */
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
  /** OF's colour / size class, or null (none set: the default). */
  color: string | null;
  size: string | null;
}
export const NO_MARKS: Marks = { bold: false, italic: false, color: null, size: null };

/** The marks at `node` (the caret's), from its ancestors up to `root`; outside `root`: none. */
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
