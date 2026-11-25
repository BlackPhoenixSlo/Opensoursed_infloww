import { COLOR_CLASSES, DROP_CONTENT, SIZE_CLASSES, runsHtml } from "@/lib/ofMirrorFormat";

export type OfRun =
  | { text: string; bold: boolean; italic: boolean; color: string | null; size: string | null }
  | { br: true };
export type OfDoc = OfRun[][];

const NAMED: Record<string, string> = { nbsp: " ", amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'" };
const NAMED_NO_DOM: Record<string, string> = {
  hellip: "\u2026", rsquo: "\u2019", lsquo: "\u2018", rdquo: "\u201d", ldquo: "\u201c", sbquo: "\u201a",
  bdquo: "\u201e", mdash: "\u2014", ndash: "\u2013", bull: "\u2022", middot: "\u00b7", laquo: "\u00ab",
  raquo: "\u00bb", copy: "\u00a9", reg: "\u00ae", trade: "\u2122", euro: "\u20ac", pound: "\u00a3",
  yen: "\u00a5", cent: "\u00a2", deg: "\u00b0", times: "\u00d7", divide: "\u00f7", hearts: "\u2665",
  star: "\u2606", iexcl: "\u00a1", iquest: "\u00bf", shy: "\u00ad", zwj: "\u200d", zwnj: "\u200c",
};
let decoder: HTMLTextAreaElement | null | undefined;
function decodeNamed(m: string, name: string): string {
  if (decoder === undefined) decoder = typeof document !== "undefined" ? document.createElement("textarea") : null;
  if (!decoder) return NAMED_NO_DOM[name] ?? NAMED_NO_DOM[name.toLowerCase()] ?? m;
  decoder.innerHTML = m;
  return decoder.value.length <= 2 ? decoder.value : m;
}

export function decodeEntities(s: string): string {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z][a-z0-9]*);/gi, (m, e: string) => {
    if (e[0] === "#") {
      const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(n) && n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : m;
    }
    return NAMED[e.toLowerCase()] ?? decodeNamed(m, e);
  });
}

const TAG = /<(\/?)([a-zA-Z][^\t\n\r\f />\0<]*)(?=[\t\n\r\f />])((?:[^<>"']|"[^"<]*"|'[^'<]*')*)>|<!--(?:(?!<!--)[\s\S])*?-->|<!(?!--)[^<>]*>|<\?[^<>]*>/g;
export const BLOCK: ReadonlySet<string> = new Set(("div li ul ol dl dt dd h1 h2 h3 h4 h5 h6 blockquote pre section article header "
  + "footer aside nav main figure figcaption address table tr td th hr").split(" "));
const CLASS_ATTR = /(?:^|[\t\n\f\r /"'])class[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))/i;
const SELF_CLOSED = /\/[\t\n\f\r ]*$/;
// HTML's whitespace, the tokenizer's (not \v, not U+00A0; JS's `\s` is wider): service/of_rich_text.py `_WS`.
const WS = "[\\t\\n\\f\\r ]";

const IS_OF_HTML = new RegExp(`^${WS}*<p[\\t\\n\\f\\r >]`, "i");
export const isOfHtml = (s: string): boolean => IS_OF_HTML.test(s);

export const KNOWN: ReadonlySet<string> = new Set(("a abbr address article aside audio b base big blockquote body br button center code "
  + "dd del details div dl dt em embed figcaption figure font footer form h1 h2 h3 h4 h5 h6 head header hr html i iframe "
  + "img input ins label li link main mark math meta nav noscript object ol option p pre s script section select small "
  + "source span strike strong style sub summary sup svg table tbody td template textarea th thead title tr u ul "
  + "video").split(" "));
// Fail closed whatever follows: what runs code, styles the page or loads a document; mirrors service/of_rich_text.py.
export const ACTIVE: ReadonlySet<string> = new Set(("embed head iframe math noscript object script style svg template "
  + "textarea title").split(" "));
const RUN = /<(\/?)([A-Za-z][^\t\n\f\r /<>]*)([^<>]*)(>?)/g;
const ATTR_EQ = /(?:^|[\t\n\f\r /"'])[^\t\n\f\r /<>="']+[\t\n\f\r ]*=/;
const HANDLER = /[\t\n\f\r /"']on[A-Za-z0-9_]+[\t\n\f\r ]*=/i;
const LEAD_WS = new RegExp(`^${WS}+`);
const isWs = (c: string): boolean => c === " " || c === "\t" || c === "\n" || c === "\f" || c === "\r";
// A loop: `WS+$` backtracks quadratically on a mid-text run.
const trimWs = (s: string): string => {
  let a = 0, b = s.length;
  while (a < b && isWs(s[a])) a++;
  while (b > a && isWs(s[b - 1])) b--;
  return s.slice(a, b);
};

function failsClosed(s: string): boolean {
  for (const m of s.matchAll(RUN)) {
    const name = m[2].toLowerCase();
    if (ACTIVE.has(name) || (!KNOWN.has(name) && ATTR_EQ.test(m[3]))) return true;
  }
  const open = s.search(/<[A-Za-z]/);
  return open >= 0 && HANDLER.test(s.slice(open));
}

function kindOf(s: string): "of" | "escape" | "bare" | null {
  if (isOfHtml(s)) return "of";
  if (failsClosed(s)) return "escape";
  for (const m of s.matchAll(RUN)) if (isTag(m[2], m[3], m[4])) return "bare";
  return null;
}

const isTag = (name: string, rest: string, end: string): boolean =>
  KNOWN.has(name.toLowerCase()) && (ATTR_EQ.test(rest) || (!!end && /^\/?$/.test(trimWs(rest))));

const onlyTags = (s: string): string =>
  s.replace(RUN, (run: string, _close: string, name: string, rest: string, end: string) =>
    (isTag(name, rest, end) ? run : `&lt;${run.slice(1)}`));

// Prose in angles ("<3 u", "<link in bio>") is plain and goes as written; mirrors service/of_rich_text.py.
export const hasHtml = (s: string): boolean => kindOf(s) !== null;

type Frame = { tag: string; bold: boolean; italic: boolean; color: string | null; size: string | null };

export function parseOfHtml(html: string): OfDoc {
  if (!/<[a-zA-Z/!?]/.test(html)) {
    return html.split("\n").map((line) => (line ? [{ text: line, bold: false, italic: false, color: null, size: null }] : []));
  }
  const doc: OfDoc = [];
  let para: OfRun[] | null = null;
  const stack: Frame[] = [];
  const opened = new Map<string, number>();
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
    // `&nbsp;` stays U+00A0 (written back as `&nbsp;`, never stripped as layout whitespace).
    let text = decodeEntities(raw.replace(/&nbsp;/g, "\u00a0"));
    if (!para) text = text.replace(LEAD_WS, "");
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
    if (!m[2]) continue;
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
      open().push({ br: true });
      continue;
    }
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
        cut(i);
      }
      continue;
    }
    if (SELF_CLOSED.test(m[3])) continue;
    if (tag === "strong" || tag === "b") push(tag, { bold: true });
    else if (tag === "em" || tag === "i") push(tag, { italic: true });
    else if (tag === "span") {
      const c = CLASS_ATTR.exec(m[3]);
      const classes = (c ? c[1] ?? c[2] ?? c[3] ?? "" : "").split(/\s+/);
      push(tag, {
        color: classes.find((x) => COLOR_CLASSES.has(x)) ?? null,
        size: classes.find((x) => SIZE_CLASSES.has(x)) ?? null,
      });
    } else push(tag);
  }
  if (!dropDepth && at < html.length) pushText(html.slice(at));
  return doc;
}

export const docHasFormatting = (doc: OfDoc): boolean =>
  doc.some((p) => p.some((r) => !("br" in r) && (r.bold || r.italic || !!r.color || !!r.size)));

const escapeAsOfHtml = (s: string): string =>
  `<p>${esc(trimWs(s).replace(/\r\n/g, "\n")).replace(/\n/g, "<br>")}</p>`;

function markupOf(s: string, kind = kindOf(s)): string {
  return kind === "escape" ? escapeAsOfHtml(s)
    : kind === "bare" ? onlyTags(s).replace(/\r\n/g, "\n").replace(/\n/g, "<br>") : s;
}

export function ofText(s: string): string {
  const kind = kindOf(s);
  return kind === "escape" ? escapeAsOfHtml(s) : kind ? sanitizeOfHtml(markupOf(s, kind)) : s;
}

export function hasOfFormatting(s: string): boolean {
  const kind = kindOf(s);
  return !!kind && kind !== "escape" && docHasFormatting(parseOfHtml(markupOf(s, kind)));
}

export function ofPlain(s: string): string {
  const kind = s ? kindOf(s) : null;
  if (!kind) return s || "";
  return parseOfHtml(markupOf(s, kind)).map((p) => p.map((r) => ("br" in r ? "\n" : r.text)).join("")).join("\n")
    .replace(/\u00a0/g, " ");
}

export function ofPlainText(s: string): string {
  if (!s) return "";
  return (hasHtml(s) ? ofPlain(s) : decodeEntities(s)).trim();
}

export const ofPreviewText = (s: string): string => ofPlainText(s).replace(/\s+/g, " ");

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\u00a0/g, "&nbsp;");

export const plainToOfHtml = (s: string): string => s.split("\n").map((l) => `<p>${esc(l)}</p>`).join("");

// OF's chat draws an empty <p> with no height, so blank paragraphs fold into <br>s.
export const foldBlankParagraphs = (html: string): string =>
  html.replace(/<\/p>((?:<p><\/p>)+)<p>/g, (_m, blanks: string) => "<br>".repeat(blanks.length / 7 + 1));

// OF's limit counts UTF-16 units of the plain text; a paragraph boundary counts 1 here, 0 in OF's: never more lenient.
export const OF_TEXT_MAX = 6500;
export const TEXT_TOO_LONG = `Text is over ${OF_TEXT_MAX} characters`;

export const ofDocToHtml = (doc: OfDoc): string =>
  doc.map((p) => `<p>${runsHtml(p.map((r) => ("br" in r ? { text: "", bold: false, italic: false, classes: "", br: true }
    : { text: r.text, bold: r.bold, italic: r.italic, classes: [r.size, r.color].filter(Boolean).join(" ") })))}</p>`).join("");

export const sanitizeOfHtml = (html: string): string => ofDocToHtml(parseOfHtml(html));
