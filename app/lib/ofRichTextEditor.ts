/**
 * The script editor's value contract (components/ui/OfRichTextEditor), on top of ofMirrorFormat's contenteditable
 * model (normalize, ofHtml, setOfHtml, hasFormatting):
 *   • the value is OF markup only while the editor holds formatting (`foldBlankParagraphs` as Infloww saves it),
 *     else the plain text, one line per paragraph or `<br>`: an unformatted script stays the plain text it always was.
 *     The plain text is what was typed: never trimmed, leading/trailing empty lines kept; the one rewrite is the
 *     no-break space a contenteditable puts in for runs of spaces, which reads back as a plain space;
 *   • plain text loads as one paragraph per line; markup loads through `setOfHtml`'s allow-list;
 *   • the caret's marks light the toolbar (`marksAt`).
 */
import {
  colorClass, hasFormatting, normalize, ofHtml, restoreOffsets, textOffsets, type FormatCommand,
} from "@/lib/ofMirrorFormat";
import {
  decodeEntities, foldBlankParagraphs, hasOfFormatting, isOfHtml, ofPlainText, plainToOfHtml, sanitizeOfHtml,
} from "@/lib/ofRichText";
import { COLORS, SIZES } from "@/lib/ofMirrorFormat";

/** What the editor loads for a value (plain or markup; markup through the allow-list, li / div / h1-h6 as lines). */
export const editorHtmlOf = (value: string): string => (isOfHtml(value) ? sanitizeOfHtml(value) : plainToOfHtml(value));

/** The caret's gap `clearAtCaret` leaves: never part of the value. */
const GAP = "\u200b";

/** `ofHtml`'s output (`<p>` per line, `<br>`, escaped text) as the plain text typed: untrimmed, U+00A0 as a space. */
export const editorPlain = (html: string): string =>
  decodeEntities(html.replace(/^<p>|<\/p>$/g, "").replace(/<\/p><p>|<br>/g, "\n").replace(/<[^>]*>/g, ""))
    .replace(/\u00a0/g, " ");

/** The editor's value: OF markup while it has formatting, else its plain text. Plain text that would read back as
 *  markup (a typed `<p>Use <VIP20></p>`) stays escaped markup, so it loads and sends as the text it is. */
export function editorValue(root: Element): string {
  const html = ofHtml(root).replaceAll(GAP, "");
  if (hasFormatting(root)) return foldBlankParagraphs(html);
  const plain = editorPlain(html);
  return isOfHtml(plain) ? foldBlankParagraphs(html) : plain;
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
  const exec = (name: string, value?: string) => typeof doc.execCommand === "function" && doc.execCommand(name, false, value);
  const armed = (c: string) => {
    try { return typeof doc.queryCommandState === "function" && doc.queryCommandState(c); } catch { return false; }
  };
  exec("styleWithCSS", "false");
  if (cmd.kind === "bold" || cmd.kind === "italic") return exec(cmd.kind);
  if (cmd.kind === "color") return exec("foreColor", COLORS.find((c) => c.cls === cmd.cls)?.css || "#000001");
  if (cmd.kind === "size") return exec("fontSize", SIZES.find((s) => s.cls === cmd.cls)?.font ?? "3");
  if (clearAtCaret(root, sel)) return true;
  const b = armed("bold") && exec("bold");
  const i = armed("italic") && exec("italic");
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

/** A value's plain length (the 6500 limit and the counter count what the fan reads). */
export const plainLength = (value: string): number => (isOfHtml(value) ? ofPlainText(value) : value).length;

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

const COLOR_SET: ReadonlySet<string> = new Set(COLORS.map((c) => c.cls));
const SIZE_SET: ReadonlySet<string> = new Set(SIZES.map((s) => s.cls));

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
      if (!m.color && COLOR_SET.has(c)) m.color = c;
      if (!m.size && SIZE_SET.has(c)) m.size = c;
    }
  }
  return m;
}
