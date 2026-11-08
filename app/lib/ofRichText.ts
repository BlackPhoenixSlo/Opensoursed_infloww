/**
 * OnlyFans message text as data: OF's rich text (the tiptap markup its composer and Infloww's script editor write:
 * `<p>`, `<br>`, `<strong>`, `<em>`, `<span class="m-editor-fc__… m-editor-fs__…">`, docs/infloww-rich-text-rea.md)
 * parsed through an allow-list into runs, and the plain text of any OF body for previews. Pure and DOM-free (a
 * string tokenizer, not DOMParser), so it runs in SSR, node and vitest alike. The editor side (contenteditable ->
 * markup) is `ofMirrorFormat`; this is the reading side. The relay's send boundary keeps the same allow-list, block
 * list, tokenizer and four-way read of a text (service/of_rich_text.py's module doc; `hasHtml` / `ofText` / `ofPlain`
 * mirror `has_html` / `of_text` / `of_plain`, one case table pins both: service/tests/fixtures/of_rich_text_cases.json).
 */
import { COLOR_CLASSES, DROP_CONTENT, SIZE_CLASSES, runsHtml } from "@/lib/ofMirrorFormat";

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

/** A tag (its name up to HTML whitespace, `/` or `>`; no `<` or NUL in it: `<x.y>` is one, `<x\0y>` is text), whose
 *  attributes may quote a `>` (`<span title="a>b">`), or what holds no text: a comment, a doctype or `<![CDATA[…]>`
 *  (the browser's bogus comment), a `<?…>`. Any other `<` is text. service/of_rich_text.py `_TOKEN`, the same regex.
 *  Linear: no part of a token crosses a `<` (a quoted value holds none, a comment no `<!--`). */
const TAG = /<(\/?)([a-zA-Z][^\t\n\r\f />\0<]*)(?=[\t\n\r\f />])((?:[^<>"']|"[^"<]*"|'[^'<]*')*)>|<!--(?:(?!<!--)[\s\S])*?-->|<!(?!--)[^<>]*>|<\?[^<>]*>/g;
/** Blocks OF has no tag for (pasted lists, divs, headings, tables): each ends the paragraph, so their texts never
 *  glue (service/of_rich_text.py `_BLOCK`, the same list). */
export const BLOCK: ReadonlySet<string> = new Set(("div li ul ol dl dt dd h1 h2 h3 h4 h5 h6 blockquote pre section article header "
  + "footer aside nav main figure figcaption address table tr td th hr").split(" "));
const CLASS_ATTR = /(?:^|[\t\n\f\r /"'])class[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))/i;
/** A self-closed tag's attributes (`<br/>`, `<p />`). */
const SELF_CLOSED = /\/[\t\n\f\r ]*$/;
/** HTML's whitespace, the tokenizer's (not \v, not U+00A0; JS's `\s` is wider): service/of_rich_text.py `_WS`. */
const WS = "[\\t\\n\\f\\r ]";

/** Whether `s` is OF markup rather than plain text: it starts with a paragraph (OF's and our editor's output; the
 *  relay's `_wrap_text_as_p` uses the same test). */
const IS_OF_HTML = new RegExp(`^${WS}*<p[\\t\\n\\f\\r >]`, "i");
export const isOfHtml = (s: string): boolean => IS_OF_HTML.test(s);

// service/of_rich_text.py `_kind`, rule for rule; service/tests/fixtures/of_rich_text_cases.json pins both.
export const KNOWN: ReadonlySet<string> = new Set(("a abbr address article aside audio b base big blockquote body br button center code "
  + "dd del details div dl dt em embed figcaption figure font footer form h1 h2 h3 h4 h5 h6 head header hr html i iframe "
  + "img input ins label li link main mark math meta nav noscript object ol option p pre s script section select small "
  + "source span strike strong style sub summary sup svg table tbody td template textarea th thead title tr u ul "
  + "video").split(" "));
/** Names that fail closed whatever follows (the text is escaped, `failsClosed`): what runs code, styles the page or
 *  loads a document, what the allow-list drops whole (ofMirrorFormat `DROP_CONTENT`), and the foreign-content roots
 *  whose children set handlers and links through attribute values (`<svg x><set attributeName=onclick …>`). */
export const ACTIVE: ReadonlySet<string> = new Set(("embed head iframe math noscript object script style svg template "
  + "textarea title").split(" "));
/** A tag-shaped run, its name as the browser reads it: `<name` / `</name` up to its `>`, the next `<` or the end. */
const RUN = /<(\/?)([A-Za-z][^\t\n\f\r /<>]*)([^<>]*)(>?)/g;
const ATTR_EQ = /(?:^|[\t\n\f\r /"'])[^\t\n\f\r /<>="']+[\t\n\f\r ]*=/;
/** An event handler, on any name, quote-blind: scanned from the first tag opener to the end of the text. */
const HANDLER = /[\t\n\f\r /"']on[A-Za-z0-9_]+[\t\n\f\r ]*=/i;
const LEAD_WS = new RegExp(`^${WS}+`);
const isWs = (c: string): boolean => c === " " || c === "\t" || c === "\n" || c === "\f" || c === "\r";
/** `s` without leading/trailing HTML whitespace; a loop, as `WS+$` backtracks quadratically on a mid-text run. */
const trimWs = (s: string): string => {
  let a = 0, b = s.length;
  while (a < b && isWs(s[a])) a++;
  while (b > a && isWs(s[b - 1])) b--;
  return s.slice(a, b);
};

/** A tag that may be hostile whatever its syntax: an `ACTIVE` name, whatever follows, a name `KNOWN` lacks given an
 *  `attr=` (`<x style=…>`), or, quote-blind, an `on…=` handler anywhere after the first `<letter`, on any name.
 *  `ofText` escapes such a text whole. */
function failsClosed(s: string): boolean {
  for (const m of s.matchAll(RUN)) {
    const name = m[2].toLowerCase();
    if (ACTIVE.has(name) || (!KNOWN.has(name) && ATTR_EQ.test(m[3]))) return true;
  }
  const open = s.search(/<[A-Za-z]/);
  return open >= 0 && HANDLER.test(s.slice(open));
}

/** How the relay reads a text (service/of_rich_text.py `_kind` and its module doc): OF markup ("of"), a text that
 *  fails closed ("escape"), bare formatting: a known HTML name closed as written or given an `attr=` ("bare"), or
 *  plain text (null). */
function kindOf(s: string): "of" | "escape" | "bare" | null {
  if (isOfHtml(s)) return "of";
  if (failsClosed(s)) return "escape";
  for (const m of s.matchAll(RUN)) if (isTag(m[2], m[3], m[4])) return "bare";
  return null;
}

/** A known HTML name closed as written (`</b>`, `<br/>`) or given an `attr=` (`<a href=x>`): service/of_rich_text.py
 *  `_is_tag`. */
const isTag = (name: string, rest: string, end: string): boolean =>
  KNOWN.has(name.toLowerCase()) && (ATTR_EQ.test(rest) || (!!end && /^\/?$/.test(trimWs(rest))));

/** Bare formatting with each tag-shaped run that is no tag (`isTag`) escaped, so the parse keeps the prose around the
 *  tags as written (`<b>SALE</b> use <code VIP20>`): service/of_rich_text.py `_only_tags`. */
const onlyTags = (s: string): string =>
  s.replace(RUN, (run: string, _close: string, name: string, rest: string, end: string) =>
    (isTag(name, rest, end) ? run : `&lt;${run.slice(1)}`));

/** Whether the relay rewrites `s` before it leaves (`ofText`; service/of_rich_text.py `has_html`): OF markup, a text
 *  escaped whole, or bare formatting. Prose in angles is plain and goes as written: "<3 u", "code <VIP20>",
 *  "<i love you>", "<link in bio>", "<video coming soon>". */
export const hasHtml = (s: string): boolean => kindOf(s) !== null;

/** An open tag and the marks of the text inside it (its own and every frame's under it). */
type Frame = { tag: string; bold: boolean; italic: boolean; color: string | null; size: string | null };

/**
 * OF markup -> paragraphs of runs. Kept: p, br, strong/b, em/i and span's OF classes (one colour, one size; the
 * innermost wins). Every other tag is dropped, its text kept (script/style and the like: dropped whole). Text
 * outside a `<p>` is a paragraph of its own, as tiptap parses it. Plain text (no tags) is one paragraph per line.
 */
export function parseOfHtml(html: string): OfDoc {
  if (!/<[a-zA-Z/!?]/.test(html)) {
    return html.split("\n").map((line) => (line ? [{ text: line, bold: false, italic: false, color: null, size: null }] : []));
  }
  const doc: OfDoc = [];
  let para: OfRun[] | null = null;
  const stack: Frame[] = [];
  const opened = new Map<string, number>(); // tag -> how many are on the stack: a stray end tag costs nothing
  let dropDepth = 0;
  let dropTag = "";
  const NONE = { bold: false, italic: false, color: null, size: null };
  const marks = (): Omit<Frame, "tag"> => {
    const { bold, italic, color, size } = stack[stack.length - 1] ?? NONE;
    return { bold, italic, color, size };
  };
  const push = (tag: string, own: Partial<Omit<Frame, "tag">> = {}) => {
    const m = marks();
    stack.push({ tag, bold: m.bold || !!own.bold, italic: m.italic || !!own.italic, color: own.color || m.color,
      size: own.size || m.size });
    opened.set(tag, (opened.get(tag) ?? 0) + 1);
  };
  const cut = (i: number) => {
    for (let j = i; j < stack.length; j++) opened.set(stack[j].tag, opened.get(stack[j].tag)! - 1);
    stack.length = i;
  };
  const open = () => (para ??= (doc.push([]), doc[doc.length - 1]));
  const pushText = (raw: string) => {
    // `&nbsp;` stays U+00A0 (written back as `&nbsp;`, never stripped as layout whitespace), as `&#160;` does
    let text = decodeEntities(raw.replace(/&nbsp;/g, "\u00a0"));
    if (!para) text = text.replace(LEAD_WS, ""); // between blocks: layout whitespace, never a paragraph of its own
    if (!text) return;
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
    if (!m[2]) continue; // a comment, doctype, `<?…>`: no text
    const closing = m[1] === "/";
    const tag = m[2].toLowerCase();
    if (dropDepth) {
      if (tag === dropTag) dropDepth += closing ? -1 : 1;
      continue;
    }
    if (DROP_CONTENT.test(tag)) {
      if (!closing && !SELF_CLOSED.test(m[3])) {
        dropDepth = 1;
        dropTag = tag;
      }
      continue;
    }
    if (tag === "br") {
      open().push({ br: true }); // `</br>` reads as a line break in every browser
      continue;
    }
    // A paragraph closes every mark left open in the last one; a block ends it (its text opens the next one).
    if (BLOCK.has(tag) || (tag === "p" && closing)) {
      cut(0);
      para = null;
      continue;
    }
    if (tag === "p") {
      if (SELF_CLOSED.test(m[3])) continue;
      cut(0);
      para = (doc.push([]), doc[doc.length - 1]);
      continue;
    }
    if (closing) {
      if (opened.get(tag)) {
        let i = stack.length - 1;
        while (stack[i].tag !== tag) i--;
        cut(i); // what it passes closes with it: linear overall
      }
      continue;
    }
    if (SELF_CLOSED.test(m[3])) continue; // a self-closed inline tag holds nothing
    if (tag === "strong" || tag === "b") push(tag, { bold: true });
    else if (tag === "em" || tag === "i") push(tag, { italic: true });
    else if (tag === "span") {
      const c = CLASS_ATTR.exec(m[3]);
      const classes = (c ? c[1] ?? c[2] ?? c[3] ?? "" : "").split(/\s+/);
      push(tag, {
        color: classes.find((x) => COLOR_CLASSES.has(x)) ?? null,
        size: classes.find((x) => SIZE_CLASSES.has(x)) ?? null,
      });
    } else push(tag); // any other element: its text, no mark
  }
  if (!dropDepth && at < html.length) pushText(html.slice(at));
  return doc;
}

/** Whether any run carries bold, italic, a colour or a size (`m-editor-fc__default` / `fs__default` count: the
 *  sender chose them). */
export const docHasFormatting = (doc: OfDoc): boolean =>
  doc.some((p) => p.some((r) => !("br" in r) && (r.bold || r.italic || !!r.color || !!r.size)));

/** `s` as one OF paragraph a fan reads exactly as written (service/of_rich_text.py `escape_as_of_html`): trimmed of
 *  HTML whitespace, escaped, each line break a `<br>`. */
const escapeAsOfHtml = (s: string): string =>
  `<p>${esc(trimWs(s).replace(/\r\n/g, "\n")).replace(/\n/g, "<br>")}</p>`;

/** Markup (`hasHtml`) as the parser reads it: a text that fails closed escaped whole, bare tags (`onlyTags`) with
 *  their line breaks as `<br>` (the relay's `of_text`). */
function markupOf(s: string, kind = kindOf(s)): string {
  return kind === "escape" ? escapeAsOfHtml(s)
    : kind === "bare" ? onlyTags(s).replace(/\r\n/g, "\n").replace(/\n/g, "<br>") : s;
}

/** A message text as it may leave for OF (service/of_rich_text.py `of_text`): OF markup and bare formatting through
 *  the allow-list, a text that fails closed escaped whole, plain text unchanged. What the editor loads, so it shows
 *  what the fan will get. */
export function ofText(s: string): string {
  const kind = kindOf(s);
  return kind === "escape" ? escapeAsOfHtml(s) : kind ? sanitizeOfHtml(markupOf(s, kind)) : s;
}

/** Whether `s` sends with formatting (`ofText`: OF markup, or bare tags such as `hey <b>babe</b>` the relay reads as
 *  markup; a text escaped whole has none); else it renders, and sends, as plain text. */
export function hasOfFormatting(s: string): boolean {
  const kind = kindOf(s);
  return !!kind && kind !== "escape" && docHasFormatting(parseOfHtml(markupOf(s, kind)));
}

/** The text a fan reads (service/of_rich_text.py `of_plain`): markup as one line per paragraph or `<br>`, entities
 *  decoded, `&nbsp;` as a space; plain text as is. Untrimmed: the 6500 limit counts it (`plainLength`). */
export function ofPlain(s: string): string {
  const kind = s ? kindOf(s) : null;
  if (!kind) return s || "";
  return parseOfHtml(markupOf(s, kind)).map((p) => p.map((r) => ("br" in r ? "\n" : r.text)).join("")).join("\n")
    .replace(/\u00a0/g, " ");
}

/**
 * Any OF body (markup or plain) for display: `ofPlain` (lines kept, script/style dropped with their content), trimmed;
 * a plain body's entities decoded once too (OF's API escapes plain text).
 */
export function ofPlainText(s: string): string {
  if (!s) return "";
  return (hasHtml(s) ? ofPlain(s) : decodeEntities(s)).trim();
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

/** OF's text limit (its composer's CharacterCount, UTF-16 code units: docs/infloww-rich-text-rea.md): counted on the
 *  plain text the fan reads, in every editor and by the relay (`plain_length`). A paragraph boundary counts 1 here,
 *  0 in OF's count: never more lenient than OF. */
export const OF_TEXT_MAX = 6500;
export const TEXT_TOO_LONG = `Text is over ${OF_TEXT_MAX} characters`;

/** Paragraphs of runs as OF markup, in OF's wire nesting (span > strong > em, size class first: `runsHtml`). */
export const ofDocToHtml = (doc: OfDoc): string =>
  doc.map((p) => `<p>${runsHtml(p.map((r) => ("br" in r ? { text: "", bold: false, italic: false, classes: "", br: true }
    : { text: r.text, bold: r.bold, italic: r.italic, classes: [r.size, r.color].filter(Boolean).join(" ") })))}</p>`).join("");

/** Any markup through the allow-list (`parseOfHtml`): OF's tags and classes kept, every other tag dropped to its text,
 *  blocks (li, div, h1-h6, table cells, …) as paragraphs (as the relay's send boundary does). */
export const sanitizeOfHtml = (html: string): string => ofDocToHtml(parseOfHtml(html));
