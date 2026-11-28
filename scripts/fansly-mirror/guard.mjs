import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { isFont } from "./assets.mjs";
import { parse } from "./dom.mjs";
import { STATIC_URL, textKinds } from "./kinds.mjs";
import { PLACEHOLDER, esc } from "./scrub.mjs";
import { CSS_ATTRS, NG_ATTR, HTML_NS, SVG_NS, XLINK_NS, SAFE_NAME, GEOMETRY, attrKinds, cssKinds, cssTextViews, elementKinds, isReadableAttr, isStyle, words } from "./markup-policy.mjs";
import { isBoot } from "./wire.mjs";

const STRUCTURAL_KINDS = ["fansly-host", "remote", "sink", "data-uri", "email", "ipv4", "ipv6", "digit-run", "handle", "amount", "script", "handler", "dead-node", "ng-reflect", "comment", "attribute", "entity", "css-content", "credential"];

const VOID = words("area base br col embed hr img input link meta source track wbr basefont bgsound frame keygen param");

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

export function attributeTextKinds(el, name, value, ctx, kinds) {
  if ((name === "xmlns" && value === SVG_NS) || (name === "xmlns:xlink" && value === XLINK_NS)) return;
  for (const v of CSS_ATTRS.has(name) ? cssTextViews(value) : [value]) {
    textKinds(v, kinds, { build: ctx.build, needles: ctx.needles, people: ctx.people, numeric: !GEOMETRY(el, name), readable: isReadableAttr(name) });
  }
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
          joined.push(n.data.trim() === PLACEHOLDER.email ? " " : n.data);
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
      attributeTextKinds(el, name, value, { ...ctx, needles }, kinds);
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
  text(joined.join(""), { readable: true, opaqueCredentials: false });
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

export const isBadEncoding = (buf) => {
  const s = buf.toString("utf8");
  return s.charCodeAt(0) === 0xfeff || !Buffer.from(s, "utf8").equals(buf) || /[\0-\x08\x0b\x0c\x0e-\x1f]/.test(s);
};

const be16 = (buf) => Buffer.from(buf.subarray(0, buf.length & ~1)).swap16().toString("utf16le");
const fontViews = (buf) => [buf.toString("latin1"), be16(buf), be16(buf.subarray(1))].map((v) => v.toLowerCase());

export function guard(root, build, extra, blankPng, needles = [], people = null) {
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
        } else if (rel !== "NOTICE.md" && !(built && rel === `static/${build}/oi-blank.png` && buf.equals(blankPng))) leaks.push(`${where}: file-type`);
      }
    }
  };
  walk(root);
  for (const { where, text } of extra) for (const k of scan(text, "text", ctx, needles)) leaks.push(`${where}: ${k}`);
  for (const k of pathKinds) leaks.push(`an output path: ${k}`);
  return leaks;
}

const PLANTED = `<!DOCTYPE html><html><head><meta charset="latin1"><title>t</title><style>.a::after{content:"abc"}</style></head><body><p onclick="x">fansly.com https://example.org/x leak@example.com 192.0.2.1 2001:db8::1 900000000001 @someone $987.65 plantedneedle &period; Bearer synthetic_secret</p><script></script><object></object><div ng-reflect-x="y" title='z'></div><a href="/elsewhere">x</a><img src="data:image/png;base64,AAAA"><!-- c --></body></html>`;

export function selfTest(fail) {
  const got = scan(PLANTED, "markup", { root: os.tmpdir(), build: null }, ["plantedneedle"]);
  if (isBadEncoding(Buffer.from(PLANTED)) || !isBadEncoding(Buffer.from(`\ufeff${PLANTED}`))) got.delete("encoding");
  const missed = [...STRUCTURAL_KINDS, "identity", "encoding"].filter((k) => !got.has(k));
  if (missed.length) fail(`self-test: the leak guard missed ${missed.join(", ")} on the planted page`);
}

