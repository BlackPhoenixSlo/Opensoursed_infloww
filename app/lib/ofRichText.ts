/**
 * OnlyFans message text as data: OF's rich text (the tiptap markup its composer and Infloww's script editor write:
 * `<p>`, `<br>`, `<strong>`, `<em>`, `<span class="m-editor-fc__… m-editor-fs__…">`, docs/infloww-rich-text-rea.md)
 * parsed through an allow-list into runs, and the plain text of any OF body for previews. Pure and DOM-free (a
 * string tokenizer, not DOMParser), so it runs in SSR, node and vitest alike. The editor side (contenteditable ->
 * markup) is `ofMirrorFormat`; this is the reading side. The relay's send boundary keeps the same allow-list
 * (service/of_rich_text.py).
 */
import { COLORS, SIZES, runsHtml } from "@/lib/ofMirrorFormat";

const COLOR_CLASSES: ReadonlySet<string> = new Set(COLORS.map((c) => c.cls));
const SIZE_CLASSES: ReadonlySet<string> = new Set(SIZES.map((s) => s.cls));

/** A run of equally marked text, or a line break. */
export type OfRun =
  | { text: string; bold: boolean; italic: boolean; color: string | null; size: string | null }
  | { br: true };
/** Paragraphs of runs. */
export type OfDoc = OfRun[][];

const NAMED: Record<string, string> = { nbsp: " ", amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'" };
/** Where there is no DOM (SSR, node): the named entities a pasted or OF-sent body commonly holds. */
const NAMED_NO_DOM: Record<string, string> = {
  hellip: "\u2026", rsquo: "\u2019", lsquo: "\u2018", rdquo: "\u201d", ldquo: "\u201c", sbquo: "\u201a",
  bdquo: "\u201e", mdash: "\u2014", ndash: "\u2013", bull: "\u2022", middot: "\u00b7", laquo: "\u00ab",
  raquo: "\u00bb", copy: "\u00a9", reg: "\u00ae", trade: "\u2122", euro: "\u20ac", pound: "\u00a3",
  yen: "\u00a5", cent: "\u00a2", deg: "\u00b0", times: "\u00d7", divide: "\u00f7", hearts: "\u2665",
  star: "\u2606", iexcl: "\u00a1", iquest: "\u00bf", shy: "\u00ad", zwj: "\u200d", zwnj: "\u200c",
};
let decoder: HTMLTextAreaElement | null | undefined;
/** A named entity the basics lack: the browser's own table (a textarea is RCDATA: nothing in it is parsed as a
 *  tag; only the one `&name;` goes in), else the no-DOM list; unknown stays as written. */
function decodeNamed(m: string, name: string): string {
  if (decoder === undefined) decoder = typeof document !== "undefined" ? document.createElement("textarea") : null;
  if (!decoder) return NAMED_NO_DOM[name] ?? NAMED_NO_DOM[name.toLowerCase()] ?? m;
  decoder.innerHTML = m;
  // A whole entity is one or two code units; more is a legacy prefix decoded alone (`&notanentity;` -> `¬anentity;`).
  return decoder.value.length <= 2 ? decoder.value : m;
}

/** HTML entities decoded once (every named one the browser knows, decimal and hex); an unknown one stays as
 *  written. The basics (`&nbsp;` as a plain space) never depend on the DOM. */
export function decodeEntities(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]*);/gi, (m, e: string) => {
    if (e[0] === "#") {
      const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : m;
    }
    return NAMED[e.toLowerCase()] ?? decodeNamed(m, e);
  });
}

/** Whose content is never text (dropped whole). */
const DROP_CONTENT = /^(script|style|template|noscript|iframe|object|textarea|title|head)$/i;
/** A tag whose attributes may quote a `>` (`<span title="a>b">`), or a comment. */
const TAG = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>|<!--[\s\S]*?-->/g;
/** Blocks that end a line: OF's `<p>`, and what a paste or another editor leaves (the relay maps them to `<p>`). */
const BLOCK = /^(p|div|li|h[1-6])$/;
const CLASS_ATTR = /\bclass\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i;

/** Whether `s` is OF markup rather than plain text: it starts with a paragraph (OF's and our editor's output; the
 *  relay's `_wrap_text_as_p` uses the same test). */
export const isOfHtml = (s: string): boolean => /^\s*<p[\s>]/i.test(s);

type Frame = { tag: string; bold?: boolean; italic?: boolean; color?: string | null; size?: string | null };

/**
 * OF markup -> paragraphs of runs. Kept: p, br, strong/b, em/i and span's OF classes (one colour, one size; the
 * innermost wins). Every other tag is dropped, its text kept (script/style and the like: dropped whole). Text
 * outside a `<p>` is a paragraph of its own, as tiptap parses it. Plain text (no tags) is one paragraph per line.
 */
export function parseOfHtml(html: string): OfDoc {
  if (!/<[a-zA-Z/!]/.test(html)) {
    return html.split("\n").map((line) => (line ? [{ text: line, bold: false, italic: false, color: null, size: null }] : []));
  }
  const doc: OfDoc = [];
  let para: OfRun[] | null = null;
  const stack: Frame[] = [];
  let dropDepth = 0;
  let dropTag = "";
  const marks = () => {
    let bold = false, italic = false, color: string | null = null, size: string | null = null;
    for (const f of stack) {
      bold ||= !!f.bold;
      italic ||= !!f.italic;
      if (f.color) color = f.color;
      if (f.size) size = f.size;
    }
    return { bold, italic, color, size };
  };
  const open = () => (para ??= (doc.push([]), doc[doc.length - 1]));
  const pushText = (raw: string) => {
    const text = decodeEntities(raw);
    if (!text || (!para && !text.trim())) return; // whitespace between paragraphs is source layout
    const run = { text, ...marks() };
    const p = open();
    const last = p[p.length - 1];
    if (last && !("br" in last) && last.bold === run.bold && last.italic === run.italic && last.color === run.color
      && last.size === run.size) last.text += text;
    else p.push(run);
  };
  let at = 0;
  for (const m of html.matchAll(TAG)) {
    const idx = m.index ?? 0;
    if (!dropDepth && idx > at) pushText(html.slice(at, idx));
    at = idx + m[0].length;
    if (!m[2]) continue; // a comment
    const closing = m[1] === "/";
    const tag = m[2].toLowerCase();
    if (dropDepth) {
      if (tag === dropTag) dropDepth += closing ? -1 : 1;
      continue;
    }
    if (DROP_CONTENT.test(tag)) {
      if (!closing && !/\/\s*$/.test(m[3])) {
        dropDepth = 1;
        dropTag = tag;
      }
      continue;
    }
    if (tag === "br") {
      if (!closing) open().push({ br: true });
      continue;
    }
    if (BLOCK.test(tag)) {
      stack.length = 0; // a paragraph closes every mark left open in the last one
      // A block opened inside one still empty (`<div><p>`, `<li><p>`) is the same line, not a blank one before it.
      if (closing) para = null;
      else if (!para || para.length) para = (doc.push([]), doc[doc.length - 1]);
      continue;
    }
    if (closing) {
      const i = stack.map((f) => f.tag).lastIndexOf(tag);
      if (i >= 0) stack.length = i;
      continue;
    }
    if (/\/\s*$/.test(m[3])) continue; // a self-closed inline tag holds nothing
    if (tag === "strong" || tag === "b") stack.push({ tag, bold: true });
    else if (tag === "em" || tag === "i") stack.push({ tag, italic: true });
    else if (tag === "span") {
      const c = CLASS_ATTR.exec(m[3]);
      const classes = (c ? c[1] ?? c[2] ?? c[3] ?? "" : "").split(/\s+/);
      stack.push({
        tag,
        color: classes.find((x) => COLOR_CLASSES.has(x)) ?? null,
        size: classes.find((x) => SIZE_CLASSES.has(x)) ?? null,
      });
    } else stack.push({ tag }); // any other element: its text, no mark
  }
  if (!dropDepth && at < html.length) pushText(html.slice(at));
  return doc;
}

/** Whether any run carries bold, italic, a colour or a size (`m-editor-fc__default` / `fs__default` count: the
 *  sender chose them). */
export const docHasFormatting = (doc: OfDoc): boolean =>
  doc.some((p) => p.some((r) => !("br" in r) && (r.bold || r.italic || !!r.color || !!r.size)));

/** Whether `s` is OF markup with formatting in it (else it renders, and sends, as plain text). */
export const hasOfFormatting = (s: string): boolean => isOfHtml(s) && docHasFormatting(parseOfHtml(s));

/**
 * Any OF body (markup or plain) as plain text that keeps its lines: `<br>` and each paragraph end a line, every tag
 * dropped (script/style with their content), entities decoded once, `&nbsp;` as a space, trimmed.
 */
export function ofPlainText(s: string): string {
  if (!s) return "";
  return decodeEntities(
    s
      .replace(/<(script|style|template|noscript|iframe|object|textarea|title|head)\b[\s\S]*?<\/\1\s*>/gi, "")
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<br(?:\s(?:[^>"']|"[^"]*"|'[^']*')*)?\/?>/gi, "\n")
      .replace(/<\/(p|div|li|h[1-6])\s*>/gi, "\n")
      .replace(/<\/?[a-zA-Z](?:[^>"']|"[^"]*"|'[^']*')*>/g, ""),
  ).trim();
}

/** One line for a list row or a picker: `ofPlainText` with every whitespace run as one space. */
export const ofPreviewText = (s: string): string => ofPlainText(s).replace(/\s+/g, " ");

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\u00a0/g, "&nbsp;");

/** Plain text as OF markup without formatting, one paragraph per line (an empty line an empty paragraph): what an
 *  editor loads a plain script as. */
export const plainToOfHtml = (s: string): string => s.split("\n").map((l) => `<p>${esc(l)}</p>`).join("");

/** Infloww's save step (`replaceParagraphsWithBreaks`): blank paragraphs between two paragraphs fold into the first
 *  as `<br>`s, since OF's chat draws an empty `<p>` with no height. n blank lines fold into n + 1 `<br>` (the
 *  paragraph's own line end plus one per blank line), so plain -> markup -> plain keeps every blank line (Infloww
 *  writes 2n, which adds one per extra blank line). */
export const foldBlankParagraphs = (html: string): string =>
  html.replace(/<\/p>((?:<p><\/p>)+)<p>/g, (_m, blanks: string) => "<br>".repeat(blanks.length / 7 + 1));

/** OF's text limit (its composer's CharacterCount): counted on the plain text the fan reads, in every editor. */
export const OF_TEXT_MAX = 6500;

/** Paragraphs of runs as OF markup, in OF's wire nesting (span > strong > em, size class first: `runsHtml`). */
export const ofDocToHtml = (doc: OfDoc): string =>
  doc.map((p) => `<p>${runsHtml(p.map((r) => ("br" in r ? { text: "", bold: false, italic: false, classes: "", br: true }
    : { text: r.text, bold: r.bold, italic: r.italic, classes: [r.size, r.color].filter(Boolean).join(" ") })))}</p>`).join("");

/** Any markup through the allow-list (`parseOfHtml`): OF's tags and classes kept, every other tag dropped to its text,
 *  li / div / h1-h6 as paragraphs (as the relay's send boundary does). */
export const sanitizeOfHtml = (html: string): string => ofDocToHtml(parseOfHtml(html));
