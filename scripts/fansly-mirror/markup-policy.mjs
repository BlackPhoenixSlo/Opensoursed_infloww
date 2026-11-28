import { codePoint, cssNormalize, cssTokens } from "./css.mjs";

export const words = (s) => new Set(s.split(" "));
export const CUSTOM_ELEMENT = /^[a-z][a-z0-9._]*-[a-z0-9._-]*$/;

const cssUnescape = (v) => v.replace(/\\(?:([0-9a-f]{1,6})[ \t\n\r\f]?|(\r\n|[\n\r\f])|([\s\S]))/gi, (_, hex, nl, ch) => (hex ? codePoint(parseInt(hex, 16)) : nl ? "" : ch));
export const SAFE_NAME = /^[\w-][\w.-]*$/;

export const HTML_NS = "http://www.w3.org/1999/xhtml";
export const SVG_NS = "http://www.w3.org/2000/svg";
export const XLINK_NS = "http://www.w3.org/1999/xlink";
const HTML_ELEMENTS = words("html head body title style meta link div span p a h1 h2 h3 h4 h5 h6 ul ol li dl dt dd img button form input label select option optgroup textarea fieldset legend section article header footer nav main aside figure figcaption table thead tbody tfoot tr td th caption colgroup col strong em b i u s small sub sup br hr pre code blockquote q cite abbr time mark kbd samp var del ins wbr details summary dialog progress meter output canvas");
const SVG_ELEMENTS = words("svg g defs symbol use path circle ellipse line polyline polygon rect text tspan title desc linearGradient radialGradient stop clipPath mask pattern marker filter feGaussianBlur feOffset feColorMatrix feFlood feComposite feMerge feMergeNode feBlend feDropShadow image animate animateTransform");
const THIRD_PARTY = /intercom|awswaf|aws-waf|googletagmanager|\bgtm\b|gm-style|google-map|live-video|live-player/i;
const SMIL_SAFE = words("opacity fill fill-opacity stroke stroke-opacity stroke-width stroke-dasharray stroke-dashoffset r rx ry cx cy x y width height offset stop-color stop-opacity");

const GLOBAL_ATTRS = words("class id title lang dir role tabindex hidden style translate draggable spellcheck contenteditable slot part inert autocapitalize enterkeyhint inputmode");
const NG_PREFIX = /^_ng(?:content|host)-[a-z]+-c\d{1,10}(?!\d)/;
export const NG_ATTR = new RegExp(`${NG_PREFIX.source}$`);
const PATTERN_ATTR = /^aria-[a-z-]+$/;
const MARKER_ATTRS = words("data-oi-avatar data-oi-banner data-oi-nav data-oi-chart-placeholder");
const FONT_AWESOME_PREFIXES = words("fa fal far fas fab fad");
const dataAllowed = (el, name, value) => {
  const svg = el.namespaceURI === SVG_NS && el.localName === "svg";
  if (name === "data-prefix") return svg && FONT_AWESOME_PREFIXES.has(value);
  if (name === "data-icon") return svg && /^[a-z0-9-]{1,40}$/.test(value);
  if (name === "data-beasties-container") return el.localName === "html" && value === "";
  if (name === "data-dropdown-value") return el.localName === "div" && value === "xDD";
  if (name === "data-menu-item") return /^[a-z][a-z0-9-]{0,63}$/.test(value);
  if (name === "data-index") return /^\d{1,5}$/.test(value);
  return MARKER_ATTRS.has(name) && value === "";
};
const HTML_ATTRS = {
  meta: "charset name content",
  link: "rel href",
  a: "href target",
  img: "src alt width height loading decoding",
  input: "type name value placeholder checked disabled readonly maxlength minlength min max step autocomplete required size multiple",
  button: "type name value disabled",
  form: "method novalidate autocomplete name",
  label: "for",
  select: "name multiple disabled size required autocomplete",
  option: "value selected disabled label",
  optgroup: "label disabled",
  textarea: "name rows cols placeholder disabled readonly maxlength minlength required wrap autocomplete",
  fieldset: "disabled name",
  td: "colspan rowspan headers",
  th: "colspan rowspan headers scope abbr",
  col: "span",
  colgroup: "span",
  ol: "start reversed type",
  li: "value",
  time: "datetime",
  del: "datetime",
  ins: "datetime",
  details: "open",
  dialog: "open",
  progress: "value max",
  meter: "value min max low high optimum",
  canvas: "width height",
  output: "for name",
  style: "media",
};
const SVG_ATTRS = words("fill fill-opacity fill-rule stroke stroke-width stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray stroke-dashoffset stroke-opacity opacity clip-path clip-rule mask filter color display visibility transform transform-origin x y x1 y1 x2 y2 cx cy r rx ry fx fy fr width height offset stop-color stop-opacity gradientUnits gradientTransform patternUnits patternContentUnits patternTransform spreadMethod font-size font-family font-weight font-style text-anchor dominant-baseline alignment-baseline letter-spacing dx dy rotate textLength lengthAdjust vector-effect shape-rendering paint-order marker-start marker-mid marker-end markerWidth markerHeight markerUnits refX refY orient maskUnits maskContentUnits clipPathUnits preserveAspectRatio pathLength focusable overflow version");
const FE = "in in2 result stdDeviation values type operator k1 k2 k3 k4 mode flood-color flood-opacity color-interpolation-filters";
const SMIL = "attributeName attributeType type from to by values dur begin end repeatCount repeatDur calcMode keyTimes keySplines additive accumulate";
const SVG_ELEMENT_ATTRS = {
  svg: "viewBox xmlns xmlns:xlink",
  symbol: "viewBox",
  marker: "viewBox",
  pattern: "viewBox",
  path: "d",
  polygon: "points",
  polyline: "points",
  use: "href xlink:href",
  image: "href xlink:href",
  filter: "filterUnits primitiveUnits color-interpolation-filters",
  animate: SMIL,
  animateTransform: SMIL,
};
const attrMap = (o) => new Map(Object.entries(o).map(([tag, names]) => [tag, words(names)]));
const HTML_ATTR_MAP = attrMap(HTML_ATTRS);
const SVG_ATTR_MAP = attrMap({ ...SVG_ELEMENT_ATTRS, fe: FE });
const NO_ATTRS = new Set();
const elementAttrs = (el) => (el.namespaceURI === SVG_NS ? SVG_ATTR_MAP.get(/^fe[A-Z]/.test(el.localName) ? "fe" : el.localName) : HTML_ATTR_MAP.get(el.localName)) || NO_ATTRS;
export const CSS_ATTRS = words("style fill stroke clip-path mask filter marker-start marker-mid marker-end");
const SMIL_VALUES = words("from to by values");
const isCssValueAttr = (el, name) => name !== "style" && (CSS_ATTRS.has(name) || (el.namespaceURI === SVG_NS && SMIL_VALUES.has(name)));
export const URL_ATTR = /^(?:href|xlink:href|src|action|formaction|data|poster|background|srcset|imagesrcset|ping|cite|longdesc|usemap|manifest|codebase|archive|lowsrc|dynsrc|xml:base|itemtype|profile|icon)$/i;
const FRAGMENT = /^#[\w.:-]*$/;
const MANAGER_HREF = /^\/fansly-manager(?:\/[a-z0-9-]+)*$/;
export const GEOMETRY = (el, name) => /^(?:viewBox|transform|gradientTransform|patternTransform)$/.test(name) || (name === "d" && el.localName === "path") || (name === "points" && /^poly(?:gon|line)$/.test(el.localName));
const NON_TEXT_ATTRS = words("class style xmlns xmlns:xlink width height x y cx cy r fill stroke");
const isNameAttr = (el, name) => GLOBAL_ATTRS.has(name) || PATTERN_ATTR.test(name) || NG_ATTR.test(name) || (el.namespaceURI === SVG_NS && SVG_ATTRS.has(name)) || elementAttrs(el).has(name);
export const isReadableAttr = (name) => !NG_ATTR.test(name) && !URL_ATTR.test(name) && !NON_TEXT_ATTRS.has(name.toLowerCase());

export const isAsset = (v, ctx) => ctx.assets?.has(v) === true;

function sinkKind(value) {
  const v = value.replace(/[\t\n\r]/g, "").replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, "");
  if (/^data:/i.test(v)) return "data-uri";
  if (/^(?:javascript|vbscript):/i.test(v)) return "handler";
  if (/^(?:[a-z][a-z0-9+.-]*:|[\\/]{2})/i.test(v)) return "remote";
  return "sink";
}

function schemeKinds(v, kinds) {
  for (const [, scheme] of v.matchAll(/(?<![\w+.-])([a-z][a-z0-9+.-]*):/gi)) {
    const s = scheme.toLowerCase();
    kinds.add(s === "javascript" ? "handler" : s === "data" ? "data-uri" : "remote");
  }
}

const CSS_COMMENT = /\/\*[\s\S]*?\*\//g;

function cssSegments(raw) {
  const text = cssNormalize(raw);
  const { tokens, bad } = cssTokens(text);
  const segments = [];
  const comments = [];
  let depth = 0;
  let nest = 0;
  let broken = bad;
  let seg = [];
  let start = 0;
  const end = (prelude, stop) => {
    segments.push({ prelude, toks: seg.filter((t) => t.type !== "ws"), start, end: stop });
    seg = [];
  };
  for (const t of tokens) {
    if (t.type === "comment") comments.push(t);
    else if (nest === 0 && (t.type === "{" || t.type === ";" || t.type === "}")) {
      end(t.type === "{", t.type === "}" ? t.start : t.end);
      start = t.end;
      if (t.type === "{") depth++;
      else if (t.type === "}" && --depth < 0) broken = true;
    } else {
      if (t.type === "(" || t.type === "[" || t.type === "function") nest++;
      else if ((t.type === ")" || t.type === "]") && --nest < 0) broken = true;
      seg.push(t);
    }
  }
  end(false, text.length);
  return { text, segments, comments, broken: broken || depth !== 0 || nest !== 0 };
}

const TEXT_PROPS = words("content quotes");
const NAME_PROPS = words("font-family font font-feature-settings font-variation-settings grid-template-areas grid-template grid");
const NAME_FUNCS = words("format tech local");
const TRANSPARENT_FUNCS = words("var env attr counter counters symbols");
const CONTENT_FUNCS = words("attr counter counters");
const ICON_TEXT = /^[\u{e000}-\u{f8ff}\u{f0000}-\u{10ffff}]*$/u;
const FAMILY_VAR = /^--(?:[\w-]*-)?family(?:-[\w-]*)?$/;
const FONT_NAME = /^[^/:\\]+$/;
const FONT_FILE = /\.[a-z\d]{2,5}$/i;

function valueKinds(toks, prop, ctx) {
  const kinds = new Set();
  const fetched = (v) => {
    if (!FRAGMENT.test(v) && !isAsset(v, ctx)) kinds.add(sinkKind(v));
  };
  const stack = [];
  for (const t of toks) {
    if (t.type === "function") {
      stack.push(t.value.toLowerCase());
      if (TEXT_PROPS.has(prop) && CONTENT_FUNCS.has(stack.at(-1))) kinds.add("css-content");
    } else if (t.type === "(" || t.type === "[") stack.push("(");
    else if (t.type === ")" || t.type === "]") stack.pop();
    else if (t.type === "url") fetched(t.value);
    else if (t.type === "string") {
      const fn = stack.findLast((f) => f !== "(" && !TRANSPARENT_FUNCS.has(f));
      const nameVar = prop.startsWith("--") && ((FAMILY_VAR.test(prop) && FONT_NAME.test(t.value) && !FONT_FILE.test(t.value)) || ICON_TEXT.test(t.value));
      if (fn ? !NAME_FUNCS.has(fn) : !TEXT_PROPS.has(prop) && !NAME_PROPS.has(prop) && !nameVar) fetched(t.value);
      else if (!fn && TEXT_PROPS.has(prop) && !ICON_TEXT.test(t.value)) kinds.add("css-content");
    }
  }
  return kinds;
}

function declKinds(toks, ctx) {
  if (!toks.length) return new Set();
  if (toks[0].type === "at") {
    const at = toks[0].value.toLowerCase();
    if (at === "import") return new Set(["sink"]);
    if (at === "charset") return new Set(toks.length === 2 && toks[1].type === "string" && toks[1].value.toLowerCase() === "utf-8" ? [] : ["encoding"]);
    return valueKinds(toks.slice(1), "@", ctx);
  }
  const prop = toks[0].type === "ident" && toks[1]?.type === ":" ? toks[0].value.toLowerCase() : "";
  return valueKinds(prop ? toks.slice(2) : toks, prop, ctx);
}

export function cssAnalyze(raw, ctx) {
  const { text, segments, comments, broken } = cssSegments(raw);
  const kinds = new Set(broken ? ["sink"] : []);
  const cuts = comments.map((t) => [t.start, t.end, " "]);
  let fatal = broken;
  for (const s of segments) {
    if (s.prelude) {
      if (s.toks[0]?.type === "at" && s.toks[0].value.toLowerCase() === "import") {
        kinds.add("sink");
        fatal = true;
      }
      continue;
    }
    const k = declKinds(s.toks, ctx);
    for (const x of k) kinds.add(x);
    if (k.size) cuts.push([s.start, s.end, ""]);
  }
  return { text, kinds, cuts, fatal };
}

function cssExempt(raw) {
  const { text, segments } = cssSegments(raw);
  const blanks = [];
  for (const { prelude, toks } of segments) {
    for (const t of toks) {
      const ng = t.type === "ident" && text.slice(t.start, t.end).match(NG_PREFIX);
      if (ng) blanks.push({ start: t.start, end: t.start + ng[0].length });
    }
    const important = toks.length === 5 && toks[3].value === "!" && toks[4].type === "ident" && toks[4].value.toLowerCase() === "important";
    if (!prelude && toks[0]?.type === "ident" && toks[0].value.toLowerCase() === "z-index" && toks[1]?.type === ":" && toks[2]?.type === "number" && (toks.length === 3 || important)) blanks.push(toks[2]);
  }
  let out = text;
  for (const t of blanks.sort((a, b) => b.start - a.start)) out = out.slice(0, t.start) + out.slice(t.end);
  return out;
}

export function cssKinds(text, ctx, kinds) {
  for (const k of cssAnalyze(text, ctx).kinds) kinds.add(k);
  for (const t of new Set([text, text.replace(CSS_COMMENT, "")])) {
    const u = cssUnescape(t).normalize("NFKC");
    if (/@import\b/i.test(u)) kinds.add("sink");
    if (u.replace(/\\/g, "/").includes("//")) kinds.add("remote");
    for (const m of u.matchAll(/"([^"]*)"|'([^']*)'/g)) schemeKinds(m[1] ?? m[2], kinds);
    for (const [, chunk, end] of u.matchAll(/([^{};]*)([{};]|$)/g)) {
      const colon = chunk.indexOf(":");
      if (end !== "{" && colon >= 0) schemeKinds(chunk.slice(colon + 1), kinds);
    }
  }
}

export const cssTextViews = (css) => [cssExempt(css), cssExempt(cssUnescape(css))];

export function elementKinds(el, kinds, ctx) {
  const tag = el.localName;
  if (tag === "script") return kinds.add("script");
  const ok = el.namespaceURI === HTML_NS ? HTML_ELEMENTS.has(tag) || CUSTOM_ELEMENT.test(tag) : el.namespaceURI === SVG_NS && SVG_ELEMENTS.has(tag);
  const names = el.getAttributeNames();
  const attr = (n) => el.getAttribute(n);
  if (
    !ok ||
    THIRD_PARTY.test(`${attr("id") || ""} ${attr("class") || ""}`) ||
    (tag === "link" && !(names.join() === "rel,href" && attr("rel") === "stylesheet" && attr("href").endsWith(".css") && isAsset(attr("href"), ctx))) ||
    (tag === "meta" && !names.every((n) => n === "charset" || (attr("name") === "viewport" && (n === "name" || n === "content")))) ||
    (tag === "animate" && !SMIL_SAFE.has(attr("attributeName"))) ||
    (tag === "animateTransform" && attr("attributeName") !== "transform")
  )
    kinds.add("dead-node");
  if (tag === "meta" && el.namespaceURI === HTML_NS && el.hasAttribute("charset") && attr("charset").toLowerCase() !== "utf-8") kinds.add("encoding");
}

export function attrKinds(el, name, value, ctx, kinds) {
  if (/^on/i.test(name) || /^srcdoc$/i.test(name)) return kinds.add("handler");
  if (/^ng-reflect-/i.test(name)) return kinds.add("ng-reflect");
  if (!(name.startsWith("data-") ? dataAllowed(el, name, value) : isNameAttr(el, name))) return kinds.add(URL_ATTR.test(name) ? sinkKind(value) : "attribute");
  if (name === "href" || name === "xlink:href" || name === "src") {
    const tag = el.localName;
    const ok = tag === "a" ? FRAGMENT.test(value) || MANAGER_HREF.test(value) : tag === "use" ? FRAGMENT.test(value) : isAsset(value, ctx);
    if (!ok) kinds.add(sinkKind(value));
  } else if (name === "target") {
    if (value !== "_top") kinds.add("attribute");
  } else if (name === "xmlns" || name === "xmlns:xlink") {
    if (value !== (name === "xmlns" ? SVG_NS : XLINK_NS)) kinds.add("attribute");
  } else if (name === "style") cssKinds(value, ctx, kinds);
  else if (isCssValueAttr(el, name)) cssKinds(`${name}:${value}`, ctx, kinds);
}

export const isStyle = (el) => el.localName === "style" && el.namespaceURI === HTML_NS;

