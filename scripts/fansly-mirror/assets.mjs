import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { cssNormalize, cssTokens } from "./css.mjs";
import { fontFaces } from "./icons.mjs";

const MAX_ASSET_BYTES = 2 * 1024 * 1024;
const RASTER = /\.(?:png|jpe?g|gif|webp|avif|bmp|ico|apng)$/i;
const MEDIA_HOST = /(?:^|\.)(?:cdn\d*|media\w*)\.fansly\.com$/i;
const DATA_TYPES = { "image/svg+xml": "svg", "font/woff2": "woff2", "application/font-woff2": "woff2", "font/woff": "woff", "application/font-woff": "woff", "font/ttf": "ttf", "application/x-font-ttf": "ttf", "font/otf": "otf", "application/x-font-otf": "otf" };
const FONT_MAGIC = { woff2: ["wOF2"], woff: ["wOFF"], ttf: ["\0\x01\0\0", "true"], otf: ["OTTO"] };
const SAFE_SEG = /^[\w-][\w.-]*$/;
const URL_FUNCS = new Set(["url", "src", "image-set", "-webkit-image-set"]);
const SVG_NS = "http://www.w3.org/2000/svg";

export const isFont = (name, buf) => FONT_MAGIC[path.extname(name).slice(1).toLowerCase()]?.includes(buf.subarray(0, 4).toString("latin1")) === true;
const nameOf = (buf) => [...crypto.createHash("sha256").update(buf).digest("hex").slice(0, 12)].map((c) => "abcdefghijklmnop"[parseInt(c, 16)]).join("");
const decode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

export function rewriteCss(raw, resolve) {
  const text = cssNormalize(raw);
  const edits = [];
  const stack = [];
  for (const t of cssTokens(text).tokens) {
    if (t.type === "function") stack.push(t.value.toLowerCase());
    else if (t.type === "(" || t.type === "[") stack.push("(");
    else if (t.type === ")" || t.type === "]") stack.pop();
    else if (t.type === "url" || (t.type === "string" && URL_FUNCS.has(stack.at(-1)))) {
      const v = resolve(t.value);
      if (v !== null) edits.push([t.start, t.end, t.type === "url" ? `url("${v}")` : `"${v}"`]);
    }
  }
  let out = text;
  for (const [start, end, fill] of edits.reverse()) out = out.slice(0, start) + fill + out.slice(end);
  return out;
}

export function makeAssets({ capture, list, stage, build, staticUrl, blank, needles, noteAsset, scrubCss, parseSvg, scrubSvg }) {
  const keyOf = (u) => `${u.origin}${u.pathname}`;
  const byUrl = new Map();
  for (const a of Array.isArray(list) ? list : []) {
    let u;
    try {
      u = new URL(a?.url);
    } catch {
      continue;
    }
    const file = typeof a.file === "string" ? path.resolve(capture, a.file) : null;
    if (file?.startsWith(capture + path.sep)) byUrl.set(keyOf(u), file);
  }
  const stats = { copied: 0, bytes: 0, blanked: [], css: [], faces: [] };
  const missing = new Set();
  const isMissing = (ref, base) => {
    try {
      return missing.has(keyOf(new URL(ref.trim(), base)));
    } catch {
      return false;
    }
  };
  const trackFaces = (text, base) => {
    for (const f of fontFaces(text)) stats.faces.push({ family: f.family, local: f.local, key: f.urls.join(" "), urls: f.urls.length, missing: f.urls.filter((u) => isMissing(u, base)).length });
  };
  const done = new Map();
  const written = new Set();
  const write = (dir, ext, buf) => {
    const rel = `${dir}${nameOf(buf)}.${ext}`;
    if (!written.has(rel)) {
      written.add(rel);
      const dest = path.join(stage, "static", build, ...rel.split("/"));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, buf);
      stats.copied++;
      stats.bytes += buf.length;
      noteAsset(`${staticUrl}/${build}/${rel}`);
    }
    return `${staticUrl}/${build}/${rel}`;
  };
  const blanked = (why, where, shown) => {
    stats.blanked.push(`blanked asset ref (${why}) in ${where}: ${shown}`);
    return blank;
  };

  const body = (ext, buf, base, where) => {
    if (ext === "css") {
      const text = buf.toString("utf8");
      const css = scrubCss(rewriteCss(text, (v) => resolve(v, base, where)));
      if (css !== null) {
        stats.css.push(css);
        trackFaces(text, base);
      }
      return css === null ? null : Buffer.from(css);
    }
    if (ext === "svg") {
      const dom = parseSvg(buf.toString("utf8"));
      if (!dom) return null;
      rewriteDoc(dom.window.document, base, where);
      const svg = scrubSvg(dom);
      return svg === null ? null : Buffer.from(svg);
    }
    return FONT_MAGIC[ext] && isFont(`x.${ext}`, buf) ? buf : null;
  };

  function resolve(ref, base, where) {
    const v = ref.trim();
    if (!v || v.startsWith("#")) return null;
    if (/^data:/i.test(v)) {
      const m = v.match(/^data:([^,;]*)((?:;[^,;]*)*),([\s\S]*)$/i);
      const ext = m && DATA_TYPES[m[1].trim().toLowerCase()];
      if (!ext) return blank;
      const buf = /;base64/i.test(m[2]) ? Buffer.from(m[3], "base64") : Buffer.from(decode(m[3]), "utf8");
      if (buf.length > MAX_ASSET_BYTES) return blanked("too large", where, "a data: URI");
      const out = body(ext, buf, base, `a data: file from ${where}`);
      return out ? write("data/", ext, out) : blanked("unusable", where, "a data: URI");
    }
    let u;
    try {
      u = new URL(v, base);
    } catch {
      return blank;
    }
    if (!/^https?:$/.test(u.protocol) || MEDIA_HOST.test(u.hostname) || RASTER.test(u.pathname)) return blank;
    const key = keyOf(u);
    if (done.has(key)) return done.get(key) ?? blank;
    done.set(key, null);
    const segs = u.pathname.split("/").filter(Boolean);
    const lower = u.pathname.toLowerCase();
    const safe = segs.length > 0 && segs.every((s) => SAFE_SEG.test(s)) && !/\d{6,}/.test(lower) && !needles.some((n) => lower.includes(n));
    const shown = safe ? u.pathname : "a withheld ref";
    const file = byUrl.get(key);
    const stat = file ? fs.statSync(file, { throwIfNoEntry: false }) : null;
    if (!stat?.isFile()) {
      missing.add(key);
      return blanked("missing", where, shown);
    }
    if (stat.size > MAX_ASSET_BYTES) return blanked("too large", where, shown);
    const ext = path.extname(u.pathname).slice(1).toLowerCase();
    const out = body(ext, fs.readFileSync(file), u.href, `asset ${shown}`);
    if (!out) return blanked("unusable", where, shown);
    done.set(key, write("", ext, out));
    return done.get(key);
  }

  function rewriteDoc(doc, base, where) {
    const css = (v) => rewriteCss(v, (r) => resolve(r, base, where));
    for (const l of [...doc.querySelectorAll("link")]) {
      if (!/(?:^|\s)stylesheet(?:\s|$)/i.test(l.getAttribute("rel") || "") || !l.getAttribute("href")) continue;
      const v = resolve(l.getAttribute("href"), base, where);
      if (!v?.endsWith(".css")) {
        l.remove();
        continue;
      }
      for (const a of [...l.attributes]) l.removeAttribute(a.name);
      l.setAttribute("rel", "stylesheet");
      l.setAttribute("href", v);
    }
    const media = [...doc.querySelectorAll("img[src]")].map((el) => [el, "src"]);
    for (const el of doc.getElementsByTagNameNS(SVG_NS, "image")) for (const n of ["href", "xlink:href"]) if (el.hasAttribute(n)) media.push([el, n]);
    for (const [el, n] of media) {
      const v = resolve(el.getAttribute(n), base, where);
      if (v !== null) el.setAttribute(n, v);
    }
    for (const el of doc.querySelectorAll("[style]")) el.setAttribute("style", css(el.getAttribute("style")));
    for (const el of doc.querySelectorAll("style")) {
      const raw = el.textContent;
      el.textContent = css(raw);
      trackFaces(raw, base);
    }
  }

  return { rewriteDoc, stats };
}
