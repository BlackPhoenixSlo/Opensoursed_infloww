#!/usr/bin/env node

import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { isFont, makeAssets } from "./fansly-mirror/assets.mjs";
import { codePoint, cssNormalize, cssTokens, hoverRules } from "./fansly-mirror/css.mjs";
import { iconHides } from "./fansly-mirror/icons.mjs";
import { THEME_MARKER, OPENER_FORM, addChrome, addWires, chartPlaceholders, isBoot, siblingWires, stateWires, tagHooks } from "./fansly-mirror/wire.mjs";
import { menuWires, openDropdowns } from "./fansly-mirror/menus.mjs";
import { dropNotCaptured } from "./fansly-mirror/not-captured.mjs";
import { STATIC_URL, baseOf, needlesOf, pathOfUrl, peopleOf, textKinds } from "./fansly-mirror/kinds.mjs";
import { install, printSummary } from "./fansly-mirror/output.mjs";
import { CUSTOM_ELEMENT, MONEY, PROSE_ATTRS, clearFields, dropIds, esc, fakeEmails, fakeMoney, fanslyPath, makeSwap, ruleOf, scrubText, words } from "./fansly-mirror/scrub.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANAGER = "/fansly-manager";
const BLANK_PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=", "base64");

const SECTIONS = ["home", "profile", "vault", "messages", "creator", "statistics", "tracking-links", "subscriptions", "bookmarks", "settings", "scheduled", "lists", "notifications"];
const SECTION_INDEX = { statistics: "overview", settings: "account" };
const BUILT_PATHS = new Set(["/fansly-manager/scheduled", "/fansly-manager/lists", "/fansly-manager/notifications", "/fansly-manager/earning-statistics"]);
const STRUCTURAL_KINDS = ["fansly-host", "remote", "sink", "data-uri", "email", "ipv4", "ipv6", "digit-run", "handle", "amount", "script", "handler", "dead-node", "ng-reflect", "comment", "attribute", "entity", "css-content"];

const fail = (msg) => {
  console.error(`fansly-mirror: ${msg}`);
  process.exit(1);
};

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = createRequire(path.join(REPO, "app/package.json"))("jsdom"));
} catch {
  fail("jsdom is not installed; run pnpm install in app/");
}

const args = process.argv.slice(2);
const flag = (name) => {
  const i = args.indexOf(name);
  if (i < 0) return undefined;
  const v = args.splice(i, 2)[1];
  if (!v) fail(`${name} needs a path`);
  return path.resolve(v);
};
const CHECK = args.includes("--check") && args.splice(args.indexOf("--check"), 1).length > 0;
const CAPTURE = flag("--capture") || path.join(os.homedir(), "Downloads/fansly-live-capture");
const PLAN = flag("--plan") || path.join(REPO, "fansly/capture/mirror_plan.json");
const OUT = flag("--out") || path.join(REPO, "app/public/fansly-mirror");
const LIB = flag("--lib") || path.join(REPO, "app/lib");
if (args.length) fail(`unknown argument ${args[0]}`);
const STAGE = `${OUT}.tmp`;
const OLD = `${OUT}.old`;
const LIST = path.join(LIB, "fansly-mirror-pages.ts");
const BUILD_TS = path.join(LIB, "fansly-mirror-build.ts");

const cssUnescape = (v) => v.replace(/\\(?:([0-9a-f]{1,6})[ \t\n\r\f]?|(\r\n|[\n\r\f])|([\s\S]))/gi, (_, hex, nl, ch) => (hex ? codePoint(parseInt(hex, 16)) : nl ? "" : ch));
const sentence = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
const labelOf = (slug) => sentence(slug.replace(/[-/]+/g, " "));
const SAFE_NAME = /^[\w-][\w.-]*$/;

const SNOWFLAKE = /^\d{15,20}$/;
const PROFILE_SUBS = new Set(["media", "media/pictures", "followers", "following"]);
const OWN_SECTIONS = new Set(["scheduled", "lists", "bookmarks", "subscriptions"]);

const LIST_SUBS = { blocked_accounts: "blocked", muted_accounts: "muted", vip_accounts: "vip", dm_permission_bypass: "dm-allow" };
function routeOfPath(p, username) {
  const s = p.toLowerCase().split("/").filter(Boolean);
  if (!s.length || s.some((x) => !/^[\w.-]+$/.test(x))) return null;
  const rest = (n) => s.slice(n).join("/");
  const [a, b, c] = s;
  if (a === "home" && s.length === 1) return { section: "home", sub: "" };
  if (a === username) {
    if (s.length === 1 || (s.length === 2 && b === "posts")) return { section: "profile", sub: "" };
    return PROFILE_SUBS.has(rest(1)) ? { section: "profile", sub: rest(1) } : null;
  }
  if (a === "post") return s.length === 2 && SNOWFLAKE.test(b) ? { section: "profile", sub: "post" } : null;
  if (a === "messages") {
    if (s.length === 1) return { section: "messages", sub: "" };
    return s.length === 2 && SNOWFLAKE.test(b) ? { section: "messages", sub: "thread" } : null;
  }
  if (a === "notifications") return { section: "notifications", sub: rest(1) };
  if (a === "creator") {
    if (b === "vault") {
      if (s.length === 2) return { section: "vault", sub: "" };
      return s.length === 3 && SNOWFLAKE.test(c) ? { section: "vault", sub: "album" } : null;
    }
    if (b === "stats" && s.length > 2) return { section: "statistics", sub: rest(2) };
    if (b === "trackinglinks" && s.length === 2) return { section: "tracking-links", sub: "" };
    if (b === "coperformers" && s.length === 3 && SNOWFLAKE.test(c)) return { section: "creator", sub: "coperformers/detail" };
    return s.slice(1).some((x) => SNOWFLAKE.test(x)) ? null : { section: "creator", sub: rest(1) };
  }
  if (OWN_SECTIONS.has(a)) {
    if (s.length === 1) return { section: a, sub: "" };
    if (s.length !== 2) return null;
    if (a === "lists") return SNOWFLAKE.test(b) ? { section: a, sub: "list" } : LIST_SUBS[b] ? { section: a, sub: LIST_SUBS[b] } : null;
    return a === "bookmarks" && !SNOWFLAKE.test(b) ? { section: a, sub: b } : null;
  }
  if (a === "settings") return s.length <= 2 ? { section: "settings", sub: b || "" } : null;
  return null;
}

const subOf = ({ section, sub }) => sub || SECTION_INDEX[section] || "";
const keyOf = (route) => `${route.section}/${subOf(route)}`;
const fileOf = (section, sub) => `${section}/${sub || "index"}.html`;
const hrefOf = (section, sub) => (sub ? `${MANAGER}/${section}/${sub}` : `${MANAGER}/${section}`);
const titleOf = (section, sub) => {
  const state = sub.match(/^(?:(.*)\/)?state-([^/]+)$/);
  if (state) return `${titleOf(section, state[1] || "")}: ${labelOf(state[2])}`;
  return sub ? `${labelOf(section)}: ${labelOf(sub)}` : labelOf(section);
};

const HTML_NS = "http://www.w3.org/1999/xhtml";
const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";
const HTML_ELEMENTS = words("html head body title style meta link div span p a h1 h2 h3 h4 h5 h6 ul ol li dl dt dd img button form input label select option optgroup textarea fieldset legend section article header footer nav main aside figure figcaption table thead tbody tfoot tr td th caption colgroup col strong em b i u s small sub sup br hr pre code blockquote q cite abbr time mark kbd samp var del ins wbr details summary dialog progress meter output canvas");
const SVG_ELEMENTS = words("svg g defs symbol use path circle ellipse line polyline polygon rect text tspan title desc linearGradient radialGradient stop clipPath mask pattern marker filter feGaussianBlur feOffset feColorMatrix feFlood feComposite feMerge feMergeNode feBlend feDropShadow image animate animateTransform");
const VOID = words("area base br col embed hr img input link meta source track wbr basefont bgsound frame keygen param");
const THIRD_PARTY = /intercom|awswaf|aws-waf|googletagmanager|\bgtm\b|gm-style|google-map|live-video|live-player/i;
const SMIL_SAFE = words("opacity fill fill-opacity stroke stroke-opacity stroke-width stroke-dasharray stroke-dashoffset r rx ry cx cy x y width height offset stop-color stop-opacity");

const GLOBAL_ATTRS = words("class id title lang dir role tabindex hidden style translate draggable spellcheck contenteditable slot part inert autocapitalize enterkeyhint inputmode");
const NG_PREFIX = /^_ng(?:content|host)-[a-z]+-c\d{1,10}(?!\d)/;
const NG_ATTR = new RegExp(`${NG_PREFIX.source}$`);
const PATTERN_ATTR = /^(?:aria-[a-z-]+|data-[a-z0-9._-]+)$/;
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
const CSS_ATTRS = words("style fill stroke clip-path mask filter marker-start marker-mid marker-end");
const SMIL_VALUES = words("from to by values");
const isCssValueAttr = (el, name) => name !== "style" && (CSS_ATTRS.has(name) || (el.namespaceURI === SVG_NS && SMIL_VALUES.has(name)));
const URL_ATTR = /^(?:href|xlink:href|src|action|formaction|data|poster|background|srcset|imagesrcset|ping|cite|longdesc|usemap|manifest|codebase|archive|lowsrc|dynsrc|xml:base|itemtype|profile|icon)$/i;
const FRAGMENT = /^#[\w.:-]*$/;
const MANAGER_HREF = /^\/fansly-manager(?:\/[a-z0-9-]+)*$/;
const GEOMETRY = (el, name) => /^(?:viewBox|transform|gradientTransform|patternTransform)$/.test(name) || (name === "d" && el.localName === "path") || (name === "points" && /^poly(?:gon|line)$/.test(el.localName));
const NON_TEXT_ATTRS = words("class style xmlns xmlns:xlink width height x y cx cy r fill stroke");
const isNameAttr = (el, name) => GLOBAL_ATTRS.has(name) || PATTERN_ATTR.test(name) || NG_ATTR.test(name) || (el.namespaceURI === SVG_NS && SVG_ATTRS.has(name)) || elementAttrs(el).has(name);
const isReadableAttr = (name) => !NG_ATTR.test(name) && !URL_ATTR.test(name) && !NON_TEXT_ATTRS.has(name.toLowerCase());

const isAsset = (v, ctx) => ctx.assets?.has(v) === true;

function assetSet(root, build) {
  const set = new Set();
  if (!build || !SAFE_NAME.test(build)) return set;
  const walk = (d, rel) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      if (!SAFE_NAME.test(e.name)) continue;
      if (e.isDirectory()) walk(path.join(d, e.name), `${rel}${e.name}/`);
      else if (e.isFile()) set.add(`${STATIC_URL}/${build}/${rel}${e.name}`);
    }
  };
  walk(path.join(root, "static", build), "");
  return set;
}

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

function cssAnalyze(raw, ctx) {
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

function cssKinds(text, ctx, kinds) {
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

const cssTextViews = (css) => [cssExempt(css), cssExempt(cssUnescape(css))];

function elementKinds(el, kinds, ctx) {
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

function attrKinds(el, name, value, ctx, kinds) {
  if (/^on/i.test(name) || /^srcdoc$/i.test(name)) return kinds.add("handler");
  if (/^ng-reflect-/i.test(name)) return kinds.add("ng-reflect");
  if (!isNameAttr(el, name)) return kinds.add(URL_ATTR.test(name) ? sinkKind(value) : "attribute");
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

const isStyle = (el) => el.localName === "style" && el.namespaceURI === HTML_NS;
const isMedia = (el, name) => (el.localName === "img" && name === "src") || (el.localName === "image" && /^(?:xlink:)?href$/.test(name));
const parse = (raw, opts = {}) => new JSDOM(raw, { virtualConsole: new VirtualConsole(), ...opts });

function cssScrub(raw, ctx) {
  const { text, cuts, fatal } = cssAnalyze(raw, ctx);
  if (fatal) return null;
  let out = "";
  let at = 0;
  for (const [start, end, fill] of cuts.sort((a, b) => a[0] - b[0])) {
    if (start >= at) out += text.slice(at, start) + fill;
    at = Math.max(at, end);
  }
  out = hoverRules(out + text.slice(at));
  const kinds = new Set();
  cssKinds(out, ctx, kinds);
  return kinds.size ? null : out;
}

function scrubAttr(el, attr, ctx, rule) {
  const { name } = attr;
  const kept = URL_ATTR.test(name) || GEOMETRY(el, name) ? attr.value : dropIds(name, attr.value);
  if (!kept && attr.value) return void el.removeAttributeNode(attr);
  const swapped = () => fakeEmails(ctx.swap(kept));
  const value = URL_ATTR.test(name) ? kept
    : PROSE_ATTRS.has(name) ? scrubText(kept, rule, ctx, el, name)
    : isReadableAttr(name) ? swapped().replace(MONEY, fakeMoney)
    : swapped();
  const kinds = new Set();
  attrKinds(el, name, value, ctx, kinds);
  if (!kinds.size) {
    if (value !== attr.value) attr.value = value;
    return;
  }
  if (isMedia(el, name)) return void (attr.value = ctx.blank);
  const css = name === "style" ? cssScrub(value, ctx) : null;
  if (css !== null) attr.value = css;
  else el.removeAttributeNode(attr);
}

function scrubTree(node, ctx, rule) {
  for (const n of [...node.childNodes]) {
    if (n.nodeType === n.TEXT_NODE) {
      if (!isStyle(node)) n.data = scrubText(n.data, rule, ctx, node);
    } else if (n.nodeType === n.ELEMENT_NODE) {
      const kinds = new Set();
      elementKinds(n, kinds, ctx);
      if (kinds.size) {
        n.remove();
        continue;
      }
      clearFields(n);
      const own = ruleOf(n) || rule;
      for (const a of [...n.attributes]) scrubAttr(n, a, ctx, own);
      if (!isStyle(n)) scrubTree(n, ctx, own);
      else {
        const css = cssScrub(n.textContent, ctx);
        if (css === null) n.remove();
        else n.textContent = css;
      }
    } else if (n.nodeType !== n.DOCUMENT_TYPE_NODE) n.remove();
  }
}

const docBaseOf = (entry, doc) => {
  try {
    return new URL(doc.querySelector("base[href]")?.getAttribute("href") || "", baseOf(entry)).href;
  } catch {
    return baseOf(entry);
  }
};
function buildPage(dom, ctx, base, wires, page) {
  const linkOf = (v) => {
    const p = fanslyPath(v, base);
    if (!p) return null;
    const route = ctx.aliases.get(p) || routeOfPath(p, ctx.username);
    const page = route && ctx.pages.get(keyOf(route));
    return page ? hrefOf(page.section, page.sub) : null;
  };
  const doc = dom.window.document;
  for (const a of doc.getElementsByTagNameNS(HTML_NS, "a")) {
    a.removeAttribute("target");
    if (!a.hasAttribute("href")) continue;
    const target = linkOf(a.getAttribute("href"));
    a.setAttribute("href", target || "#");
    if (target) a.setAttribute("target", "_top");
  }
  const taken = wires.filter(([, cls]) => cls !== "oi-state-backdrop").map(([el]) => el);
  const go = (p) => linkOf(p.replace("{username}", ctx.username));
  addWires([...wires, ...menuWires(doc, { page, here: hrefOf(page.section, page.sub), go, taken, missed: ctx.unwired })]);
  openDropdowns(doc);
  scrubTree(doc, ctx);
  const canvases = chartPlaceholders(doc);
  addChrome(doc);
  return { html: dom.serialize(), canvases };
}

const ENTITY = /&(?!(?:amp|lt|gt|quot|nbsp);)/;
const startTagOf = (el) => {
  const html = el.cloneNode(false).outerHTML;
  const close = `</${el.localName}>`;
  return el.namespaceURI === HTML_NS && VOID.has(el.localName) ? html : html.endsWith(close) ? html.slice(0, -close.length) : html;
};

function markupKinds(raw, ctx, needles, xml = false) {
  const kinds = new Set();
  let dom;
  try {
    dom = parse(raw, xml ? { contentType: "image/svg+xml" } : { includeNodeLocations: true });
  } catch {
    kinds.add("attribute");
    return kinds;
  }
  const doc = dom.window.document;
  const covered = new Uint8Array(raw.length + 1);
  const where = (n) => (xml ? null : dom.nodeLocation(n));
  const mark = (loc) => loc && covered.fill(1, loc.startOffset, loc.endOffset);
  const styles = [];
  const text = (v, opts = {}) => textKinds(v, kinds, { build: ctx.build, needles, people: ctx.people, ...opts });
  const joined = [];
  let boots = 0;
  const visit = (node) => {
    for (const n of node.childNodes) {
      if (n.nodeType === n.ELEMENT_NODE) visitElement(n);
      else if (n.nodeType === n.TEXT_NODE || n.nodeType === n.CDATA_SECTION_NODE) {
        if (node.localName !== "style") {
          text(n.data, { readable: true });
          joined.push(n.data);
        }
      } else if (n.nodeType === n.COMMENT_NODE) {
        kinds.add("comment");
        mark(where(n));
      } else if (n.nodeType === n.DOCUMENT_TYPE_NODE) {
        mark(where(n));
        text(`${n.name} ${n.publicId} ${n.systemId}`);
      } else kinds.add("dead-node");
    }
  };
  const visitElement = (el) => {
    if (!isBoot(el) || boots++) elementKinds(el, kinds, ctx);
    const loc = where(el);
    if (loc?.startTag) {
      mark(loc.startTag);
      if (raw.slice(loc.startTag.startOffset, loc.startTag.endOffset) !== startTagOf(el)) kinds.add("attribute");
    }
    if (loc?.endTag) mark(loc.endTag);
    for (const { name, value } of el.attributes) {
      attrKinds(el, name, value, ctx, kinds);
      text(name, { numeric: !NG_ATTR.test(name) });
      if ((name === "xmlns" && value === SVG_NS) || (name === "xmlns:xlink" && value === XLINK_NS)) continue;
      for (const v of CSS_ATTRS.has(name) ? cssTextViews(value) : [value]) text(v, { numeric: !GEOMETRY(el, name), readable: isReadableAttr(name) });
    }
    if (isStyle(el)) {
      const css = el.textContent;
      cssKinds(css, ctx, kinds);
      for (const v of cssTextViews(css)) text(v);
      if (loc?.startTag) {
        const range = { startOffset: loc.startTag.endOffset, endOffset: loc.endTag?.startOffset ?? raw.length };
        mark(range);
        styles.push(range);
      }
    }
    visit(el);
  };
  visit(doc);
  if (xml) {
    if (/<!DOCTYPE|<!ENTITY/i.test(raw)) kinds.add("entity");
    const decl = raw.match(/^<\?xml\b[^>]*?\bencoding\s*=\s*["']([^"']*)/i);
    if (decl && decl[1].toLowerCase() !== "utf-8") kinds.add("encoding");
  } else
    for (const m of raw.matchAll(/<[a-zA-Z/!?]/g))
      if (!covered[m.index]) {
        kinds.add("dead-node");
        break;
      }
  let outside = raw;
  for (const r of styles.reverse()) outside = outside.slice(0, r.startOffset) + outside.slice(r.endOffset);
  if (ENTITY.test(outside)) kinds.add("entity");
  text(joined.join(""), { readable: true });
  return kinds;
}

function scan(raw, type, ctx, needles) {
  if (type === "markup" || type === "svg") return markupKinds(raw, ctx, needles, type === "svg");
  const kinds = new Set();
  if (type === "css") {
    cssKinds(raw, ctx, kinds);
    for (const v of cssTextViews(raw)) textKinds(v, kinds, { build: ctx.build, needles, people: ctx.people });
  } else textKinds(raw, kinds, { build: ctx.build, needles, people: ctx.people, readable: true });
  return kinds;
}

const isBadEncoding = (buf) => {
  const s = buf.toString("utf8");
  return s.charCodeAt(0) === 0xfeff || !Buffer.from(s, "utf8").equals(buf) || /[\0-\x08\x0b\x0c\x0e-\x1f]/.test(s);
};

const be16 = (buf) => Buffer.from(buf.subarray(0, buf.length & ~1)).swap16().toString("utf16le");
const fontViews = (buf) => [buf.toString("latin1"), be16(buf), be16(buf.subarray(1))].map((v) => v.toLowerCase());

function guard(root, build, extra, needles = [], people = null) {
  const ctx = { root, build, assets: assetSet(root, build), people };
  const leaks = [];
  const pathKinds = new Set();
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const p = path.join(d, e.name);
      const rel = path.relative(root, p).split(path.sep).join("/");
      const own = scan(`/fansly-mirror/${rel}`, "path", ctx, needles);
      if (!SAFE_NAME.test(e.name)) own.add("path-name");
      for (const k of own) pathKinds.add(k);
      const where = own.size ? "an output path" : rel;
      const type = e.name.endsWith(".html") ? "markup" : e.name.endsWith(".svg") ? "svg" : e.name.endsWith(".css") ? "css" : null;
      if (e.isDirectory()) walk(p);
      else if (!e.isFile()) leaks.push(`${where}: special-file`);
      else {
        const buf = fs.readFileSync(p);
        const built = build && rel.startsWith(`static/${build}/`);
        if (type && isBadEncoding(buf)) leaks.push(`${where}: encoding`);
        else if (type) for (const k of scan(buf.toString("utf8"), type, ctx, needles)) leaks.push(`${where}: ${k}`);
        else if (built && isFont(e.name, buf)) {
          if (fontViews(buf).some((v) => needles.some((n) => v.includes(n)))) leaks.push(`${where}: identity`);
        } else if (rel !== "NOTICE.md" && !(built && rel === `static/${build}/oi-blank.png` && buf.equals(BLANK_PNG))) leaks.push(`${where}: file-type`);
      }
    }
  };
  walk(root);
  for (const { where, text } of extra) for (const k of scan(text, "text", ctx, needles)) leaks.push(`${where}: ${k}`);
  for (const k of pathKinds) leaks.push(`an output path: ${k}`);
  return leaks;
}

const PLANTED = `<!DOCTYPE html><html><head><meta charset="latin1"><title>t</title><style>.a::after{content:"abc"}</style></head><body><p onclick="x">fansly.com https://example.org/x leak@example.com 192.0.2.1 2001:db8::1 900000000001 @someone $987.65 plantedneedle &period;</p><script></script><object></object><div ng-reflect-x="y" title='z'></div><a href="/elsewhere">x</a><img src="data:image/png;base64,AAAA"><!-- c --></body></html>`;

function selfTest() {
  const got = scan(PLANTED, "markup", { root: os.tmpdir(), build: null }, ["plantedneedle"]);
  if (isBadEncoding(Buffer.from(PLANTED)) || !isBadEncoding(Buffer.from(`\ufeff${PLANTED}`))) got.delete("encoding");
  const missed = [...STRUCTURAL_KINDS, "identity", "encoding"].filter((k) => !got.has(k));
  if (missed.length) fail(`self-test: the leak guard missed ${missed.join(", ")} on the planted page`);
}

function readTable(text) {
  const sections = [];
  for (const line of text.split("\n")) {
    const s = line.match(/^  ("(?:[^"\\]|\\.)*"): \{$/);
    if (s) sections.push({ section: JSON.parse(s[1]), index: null, subs: [] });
    const i = line.match(/^    index: ("(?:[^"\\]|\\.)*"),$/);
    if (i && sections.length) sections.at(-1).index = JSON.parse(i[1]);
    const p = line.match(/^      ("(?:[^"\\]|\\.)*"): "(?:[^"\\]|\\.)*",$/);
    if (p && sections.length) sections.at(-1).subs.push(JSON.parse(p[1]));
  }
  return sections;
}

function treeProblems(root, listText, buildText, { siblings }) {
  const problems = [];
  const listName = path.basename(LIST);
  const sections = readTable(listText);
  const listed = new Set();
  const hrefs = new Set(BUILT_PATHS);
  for (const { section, index, subs } of sections) {
    if (!subs.includes(index)) problems.push(`${listName}: ${section} index is not a listed page`);
    for (const sub of subs) {
      listed.add(fileOf(section, sub));
      hrefs.add(hrefOf(section, sub));
      if (sub === index) hrefs.add(hrefOf(section, ""));
    }
  }
  const pagesDir = path.join(root, "pages");
  const files = new Set();
  const walk = (d, prefix) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      if (e.isDirectory()) walk(path.join(d, e.name), `${prefix}${e.name}/`);
      else if (e.name.endsWith(".html")) files.add(`${prefix}${e.name}`);
    }
  };
  walk(pagesDir, "");
  for (const f of [...listed].sort()) if (!files.has(f)) problems.push(`${listName}: pages/${f} is listed but has no file`);
  for (const f of [...files].sort()) {
    if (!listed.has(f)) {
      problems.push(`pages/${f}: not listed in ${listName}`);
      continue;
    }
    const doc = parse(fs.readFileSync(path.join(pagesDir, f), "utf8")).window.document;
    for (const a of doc.querySelectorAll("a[href]")) if (a.getAttribute("href").startsWith(MANAGER) && !hrefs.has(a.getAttribute("href"))) problems.push(`pages/${f}: a Fansly Manager link resolves to no listed page`);
    if ([...doc.querySelectorAll("head > script")].filter(isBoot).length !== 1) problems.push(`pages/${f}: the dark boot script is missing`);
  }
  const notice = path.join(root, "NOTICE.md");
  if (!fs.statSync(notice, { throwIfNoEntry: false })?.isFile()) problems.push("NOTICE.md is missing");
  else if (fs.readFileSync(notice, "utf8") !== NOTICE) problems.push("NOTICE.md is not the generated notice");
  const build = buildText.match(BUILD_RE)?.[1];
  if (!build || !fs.statSync(path.join(root, "static", build), { throwIfNoEntry: false })?.isDirectory()) problems.push(`${path.basename(BUILD_TS)}: the build is not a dir under static/`);
  if (siblings) for (const s of [STAGE, OLD]) if (fs.existsSync(s)) problems.push(`${path.basename(s)} exists beside the mirror`);
  return [...new Set(problems)];
}

const HEADER = "// Generated by scripts/fansly-mirror.mjs; do not edit by hand.\n";

function tableText(pages) {
  const bySection = SECTIONS.map((s) => [s, [...pages.values()].filter((p) => p.section === s).sort((a, b) => a.sub.localeCompare(b.sub))]).filter(([, ps]) => ps.length);
  const body = bySection
    .map(
      ([section, ps]) => `  ${JSON.stringify(section)}: {
    index: ${JSON.stringify(SECTION_INDEX[section] || "")},
    pages: {
${ps.map((p) => `      ${JSON.stringify(p.sub)}: ${JSON.stringify(titleOf(section, p.sub))},`).join("\n")}
    },
  },
`,
    )
    .join("");
  return `${HEADER}
export interface FanslyMirrorSection {
  index: string;
  pages: Record<string, string>;
}

export const FANSLY_MIRROR_SECTIONS: Record<string, FanslyMirrorSection> = {
${body}};
`;
}

const BUILD_RE = /FANSLY_MIRROR_BUILD: string \| null = "([\w-][\w.-]*)";/;
const buildText = (build) => `${HEADER}
export const FANSLY_MIRROR_BUILD: string | null = ${JSON.stringify(build)};
`;

const NOTICE = `# fansly-mirror

Contains Fansly's CSS, fonts and markup, mirrored for an internal look-alike of its creator UI (Fansly Manager).
A Never-public path (ADR-0067): it ships to AE only, never to public, demo or Twin. Generated by scripts/fansly-mirror.mjs.
`;

function generatedProblems(root, list, buildTs) {
  const pages = new Map();
  const walk = (d, prefix) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      if (e.isDirectory()) walk(path.join(d, e.name), `${prefix}${e.name}/`);
      else if (e.name.endsWith(".html")) {
        const [section, ...rest] = `${prefix}${e.name.slice(0, -5)}`.split("/");
        const sub = rest.join("/") === "index" ? "" : rest.join("/");
        pages.set(`${section}/${sub}`, { section, sub });
      }
    }
  };
  walk(path.join(root, "pages"), "");
  const builds = fs.existsSync(path.join(root, "static")) ? fs.readdirSync(path.join(root, "static")) : [];
  const problems = [];
  if (list !== tableText(pages)) problems.push(`${path.basename(LIST)} is not what the generator writes for this tree`);
  if (builds.length !== 1 || buildTs !== buildText(builds[0])) problems.push(`${path.basename(BUILD_TS)} is not what the generator writes for this tree`);
  return problems;
}

function check() {
  if (!fs.existsSync(OUT)) {
    console.log(`fansly-mirror --check: no mirror in this tree (${path.basename(OUT)} absent)`);
    return;
  }
  const read = (f) => (fs.existsSync(f) ? fs.readFileSync(f, "utf8") : "");
  const list = read(LIST);
  const buildTs = read(BUILD_TS);
  const leaks = guard(OUT, buildTs.match(BUILD_RE)?.[1], [
    { where: path.basename(LIST), text: list },
    { where: path.basename(BUILD_TS), text: buildTs },
  ]);
  const problems = leaks.length ? leaks : [...treeProblems(OUT, list, buildTs, { siblings: true }), ...generatedProblems(OUT, list, buildTs)];
  if (problems.length) fail(`check failed (${problems.length}):\n  ${problems.join("\n  ")}`);
  console.log(`fansly-mirror --check: ${readTable(list).reduce((n, s) => n + s.subs.length, 0)} pages match the table; no leak found`);
}

const readJson = (file, what) => {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fail(`${what} is missing or not JSON`);
  }
};

function main() {
  if (fs.existsSync(OLD)) fail(`${path.basename(OLD)} exists from a killed swap; restore or remove it first`);
  const manifest = readJson(path.join(CAPTURE, "manifest.json"), "capture manifest.json");
  const plan = readJson(PLAN, "mirror plan");
  if (manifest?.audit?.passed !== true) fail("capture audit did not pass");
  if (manifest.complete !== true) fail("capture is not complete");
  if (!Array.isArray(plan)) fail("mirror plan is not a list");
  for (const k of ["entries", "skipped", "identities"]) if (!Array.isArray(manifest[k])) fail(`manifest ${k} is not a list`);
  const { entries: allEntries, skipped, identities } = manifest;
  const planById = new Map(plan.map((p) => [p.id, p]));
  const captured = new Set(allEntries.map((e) => e.id));
  const skippedIds = new Set(skipped.map((s) => s.id));
  for (const id of planById.keys()) if (!captured.has(id) && !skippedIds.has(id)) fail(`plan id ${id} is neither captured nor skipped`);
  for (const id of skippedIds) if (!planById.get(id)?.optional) fail(`skipped id ${id} is not optional in the plan`);
  const [creator, fan] = ["creator", "fan"].map((role) => {
    const found = identities.filter((i) => i?.role === role);
    if (!found[0]?.username) fail(`manifest has no ${role} identity`);
    if (found.length > 1) fail(`manifest holds the ${role} role twice`);
    if (typeof found[0].accountId !== "string" || !/^\d+$/.test(found[0].accountId)) fail(`manifest ${role} accountId is not a string of digits`);
    return { ...found[0], displayName: found[0].displayName || found[0].username };
  });
  const username = creator.username.toLowerCase();
  const { entries, dropped } = dropNotCaptured(allEntries, (id) => planById.get(id)?.parent, (e) => pathOfUrl(e.url) === pathOfUrl(e.final_url || e.url) && !!routeOfPath(pathOfUrl(e.url) || "", username), fail);
  const needles = needlesOf(identities);
  const build = manifest.bundle_hash;
  if (typeof build !== "string" || !SAFE_NAME.test(build)) fail("manifest bundle_hash is not a plain name");
  const hashes = new Set([build, ...entries.map((e) => e.bundle_hash)]);
  if (hashes.size > 1) fail(`entries carry ${hashes.size} bundle hashes; re-capture on one Fansly build`);

  const pages = new Map();
  const aliases = new Map();
  const root = path.resolve(CAPTURE);
  const fileIn = (f) => {
    const file = typeof f === "string" ? path.resolve(root, f) : null;
    return file && file.startsWith(root + path.sep) && fs.statSync(file, { throwIfNoEntry: false })?.isFile() ? file : null;
  };
  if (!entries.some((e) => fileIn(e.file) && fs.readFileSync(fileIn(e.file), "utf8").toLowerCase().includes(username))) fail("creator username appears in no captured document");
  const docs = [];
  for (const e of entries) {
    if (e.kind === "state") continue;
    if (e.kind !== "page") fail(`entry ${e.id}: kind is neither page nor state`);
    const file = fileIn(e.file);
    if (!file) fail(`entry ${e.id}: file missing`);
    const landing = pathOfUrl(e.final_url || e.url);
    const route = landing && routeOfPath(landing, username);
    if (!route) fail(`entry ${e.id}: route not mapped`);
    const key = keyOf(route);
    if (pages.has(key)) fail(`entries ${pages.get(key).id} and ${e.id} both map to ${key}`);
    pages.set(key, { id: e.id, section: route.section, sub: subOf(route) });
    const from = pathOfUrl(e.url);
    if (from && from !== landing) aliases.set(from, route);
    docs.push({ entry: e, key, file });
  }
  const keyById = new Map(docs.map((d) => [d.entry.id, d.key]));
  for (const e of entries.filter((x) => x.kind === "state")) {
    const file = fileIn(e.file);
    if (!file) fail(`entry ${e.id}: file missing`);
    const name = e.id.split("/").at(-1).match(/^state-([a-z0-9]+(?:-[a-z0-9]+)*)$/)?.[1];
    if (!name) fail(`entry ${e.id}: a State id must end in state-<name>`);
    const parentKey = keyById.get(planById.get(e.id)?.parent);
    if (!parentKey) fail(`entry ${e.id}: its plan parent is not a captured page`);
    if (typeof e.opener !== "string" || !e.opener) fail(`entry ${e.id}: no opener`);
    if (!OPENER_FORM.test(e.opener)) fail(`entry ${e.id}: opener syntax outside opener_forms`);
    const { section, sub } = pages.get(parentKey);
    const stateSub = sub ? `${sub}/state-${name}` : `state-${name}`;
    const key = `${section}/${stateSub}`;
    if (pages.has(key)) fail(`entries ${pages.get(key).id} and ${e.id} both map to ${key}`);
    pages.set(key, { id: e.id, section, sub: stateSub, parentKey });
    docs.push({ entry: e, key, file });
  }
  for (const s of SECTIONS) if (![...pages.values()].some((p) => p.section === s && p.sub === (SECTION_INDEX[s] || ""))) fail(`section ${s} has no root page`);

  process.on("exit", () => {
    if (!process.env.FANSLY_MIRROR_KEEP_STAGE) fs.rmSync(STAGE, { recursive: true, force: true });
    for (const f of [LIST, BUILD_TS]) fs.rmSync(`${f}.tmp`, { force: true });
  });
  fs.rmSync(STAGE, { recursive: true, force: true });
  const parsed = [];
  const unreadable = [];
  for (const { entry, key, file } of docs) {
    const buf = fs.readFileSync(file);
    if (isBadEncoding(buf)) unreadable.push(`pages/${fileOf(pages.get(key).section, pages.get(key).sub)}: encoding`);
    else {
      const dom = parse(buf.toString("utf8"));
      if (!dom.window.document.documentElement.classList.contains(THEME_MARKER)) fail(`entry ${entry.id}: captured dark; re-capture in the light theme`);
      parsed.push({ entry, key, dom });
    }
  }
  if (unreadable.length) fail(`leak guard failed, nothing written:\n  ${unreadable.join("\n  ")}`);
  const wires = new Map();
  const domOf = new Map(parsed.map((p) => [p.key, p.dom]));
  const states = [];
  for (const { entry, key, dom } of parsed) {
    const { section, sub, parentKey } = pages.get(key);
    if (!parentKey) continue;
    const parent = pages.get(parentKey);
    const w = stateWires(domOf.get(parentKey).window.document, dom.window.document, entry.opener, hrefOf(section, sub), hrefOf(parent.section, parent.sub));
    if (!w) fail(`entry ${entry.id}: opener matches nothing in its parent`);
    wires.set(domOf.get(parentKey), [...(wires.get(domOf.get(parentKey)) || []), ...w.parent]);
    wires.set(dom, w.state);
    states.push({ doc: dom.window.document, parent: parentKey, opener: entry.opener, href: hrefOf(section, sub), wires: w.state });
  }
  siblingWires(states);
  const creatorNames = [creator.username, creator.displayName, creator.accountId].map((v) => v.toLowerCase());
  let rails = 0;
  for (const { key, dom } of parsed) {
    const hooks = tagHooks(dom.window.document, { profileRoot: key === "profile/", names: creatorNames });
    if (key === "profile/" && !hooks.avatar && !hooks.banner) fail("the profile root page has no avatar or banner tag");
    rails += hooks.rail;
  }
  if (!rails) fail("no page has a tagged rail");
  const people = peopleOf(parsed, needles);
  const { swap, peopleRe } = makeSwap(creator, fan, people);
  fs.mkdirSync(path.join(STAGE, "static", build), { recursive: true });
  fs.writeFileSync(path.join(STAGE, "static", build, "oi-blank.png"), BLANK_PNG);
  const blank = `${STATIC_URL}/${build}/oi-blank.png`;
  const ctx = { username, pages, aliases, root: STAGE, build, blank, assets: new Set([blank]), swap, unwired: new Set() };
  const { rewriteDoc, stats } = makeAssets({
    capture: root,
    list: manifest.assets,
    stage: STAGE,
    build,
    staticUrl: STATIC_URL,
    blank,
    needles,
    noteAsset: (u) => ctx.assets.add(u),
    scrubCss: (t) => cssScrub(t, ctx),
    parseSvg: (t) => {
      try {
        return parse(t, { contentType: "image/svg+xml" });
      } catch {
        return null;
      }
    },
    scrubSvg: (dom) => {
      const doc = dom.window.document;
      if (doc.doctype) return null;
      scrubTree(doc, ctx);
      return doc.documentElement?.localName === "svg" && doc.documentElement.namespaceURI === SVG_NS ? dom.serialize() : null;
    },
  });
  const unreviewed = [];
  const inline = [];
  let canvases = 0;
  const rewritten = [];
  for (const { entry, key, dom } of parsed) {
    const { section, sub } = pages.get(key);
    const base = docBaseOf(entry, dom.window.document);
    ctx.unreviewed = new Set();
    rewriteDoc(dom.window.document, base, `pages/${fileOf(section, sub)}`);
    rewritten.push({ key, dom, base, seen: ctx.unreviewed });
  }
  const hides = iconHides(stats.faces);
  for (const { key, dom, base, seen } of rewritten) {
    const { section, sub } = pages.get(key);
    const dest = path.join(STAGE, "pages", fileOf(section, sub));
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    hides.inject(dom.window.document);
    ctx.unreviewed = seen;
    const built = buildPage(dom, ctx, base, wires.get(dom) || [], pages.get(key));
    canvases += built.canvases;
    fs.writeFileSync(dest, built.html);
    for (const st of dom.window.document.getElementsByTagName("style")) inline.push(st.textContent);
    for (const where of ctx.unreviewed) unreviewed.push(`pages/${fileOf(section, sub)}: ${where}`);
  }
  const marker = new RegExp(`\\.${esc(THEME_MARKER)}(?![\\w-])`);
  if (![...stats.css, ...inline].some((css) => marker.test(css))) fail(`no copied or inline stylesheet uses the theme marker .${THEME_MARKER}`);
  fs.writeFileSync(path.join(STAGE, "NOTICE.md"), NOTICE);

  const list = tableText(pages);
  const buildTs = buildText(build);
  const leaks = guard(
    STAGE,
    build,
    [
      { where: path.basename(LIST), text: list },
      { where: path.basename(BUILD_TS), text: buildTs },
    ],
    needles,
    peopleRe,
  );
  if (leaks.length) fail(`leak guard failed, nothing written:\n  ${leaks.join("\n  ")}`);
  const problems = treeProblems(STAGE, list, buildTs, { siblings: false });
  if (problems.length) fail(`completeness check failed, nothing written:\n  ${problems.join("\n  ")}`);
  if (unreviewed.length) fail(`unreviewed text (extend the text rules or UI_TEXT), nothing written:\n  ${unreviewed.join("\n  ")}`);

  install({ stage: STAGE, out: OUT, old: OLD, files: [[LIST, list], [BUILD_TS, buildTs]] });

  printSummary({ pages: [...pages.values()], build, people: people.size, sections: SECTIONS, stats, hidden: hides.lines, canvases, dropped, entries, unwired: [...ctx.unwired].sort() });
}

try {
  selfTest();
  if (CHECK) check();
  else main();
} catch (e) {
  fail(`cannot parse or classify the tree (${e?.name || "error"})`);
}
