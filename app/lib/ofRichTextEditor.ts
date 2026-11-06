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
import { hasFormatting, normalize, ofHtml, restoreOffsets, textOffsets } from "@/lib/ofMirrorFormat";
import { decodeEntities, foldBlankParagraphs, isOfHtml, ofPlainText, plainToOfHtml } from "@/lib/ofRichText";
import { COLORS, SIZES } from "@/lib/ofMirrorFormat";

/** What the editor loads for a value (plain or markup). */
export const editorHtmlOf = (value: string): string => (isOfHtml(value) ? value : plainToOfHtml(value));

/** `ofHtml`'s output (`<p>` per line, `<br>`, escaped text) as the plain text typed: untrimmed, U+00A0 as a space. */
export const editorPlain = (html: string): string =>
  decodeEntities(html.replace(/^<p>|<\/p>$/g, "").replace(/<\/p><p>|<br>/g, "\n").replace(/<[^>]*>/g, ""))
    .replace(/\u00a0/g, " ");

/** The editor's value: OF markup while it has formatting, else its plain text. */
export function editorValue(root: Element): string {
  const html = ofHtml(root);
  return hasFormatting(root) ? foldBlankParagraphs(html) : editorPlain(html);
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
