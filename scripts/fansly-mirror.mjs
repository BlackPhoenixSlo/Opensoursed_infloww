#!/usr/bin/env node

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { makeAssets } from "./fansly-mirror/assets.mjs";
import { hoverRules } from "./fansly-mirror/css.mjs";
import { iconHides } from "./fansly-mirror/icons.mjs";
import { THEME_MARKER, OPENER_FORM, addChrome, addWires, chartPlaceholders, isBoot, siblingWires, stateWires, tagHooks } from "./fansly-mirror/wire.mjs";
import { menuWires, openDropdowns } from "./fansly-mirror/menus.mjs";
import { dropNotCaptured } from "./fansly-mirror/not-captured.mjs";
import { STATIC_URL, baseOf, needlesOf, pathOfUrl, peopleOf } from "./fansly-mirror/kinds.mjs";
import { install, printSummary } from "./fansly-mirror/output.mjs";
import { MONEY, PROSE_ATTRS, clearFields, dropIds, esc, fakeMoney, hasCredential, scrubIdentity, fanslyPath, makeSwap, ruleOf, scrubText } from "./fansly-mirror/scrub.mjs";

import { parse } from "./fansly-mirror/dom.mjs";
import { HTML_NS, SVG_NS, SAFE_NAME, URL_ATTR, GEOMETRY, attrKinds, elementKinds, isReadableAttr, isStyle, cssAnalyze, cssKinds } from "./fansly-mirror/markup-policy.mjs";
import { attributeTextKinds, guard, isBadEncoding, selfTest } from "./fansly-mirror/guard.mjs";

const BLANK_PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=", "base64");

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANAGER = "/fansly-manager";
const SECTIONS = ["home", "profile", "vault", "messages", "creator", "statistics", "tracking-links", "subscriptions", "bookmarks", "settings", "scheduled", "lists", "notifications"];
const SECTION_INDEX = { statistics: "overview", settings: "account" };
const BUILT_PATHS = new Set(["/fansly-manager/scheduled", "/fansly-manager/lists", "/fansly-manager/notifications", "/fansly-manager/earning-statistics"]);
const fail = (msg) => {
  console.error(`fansly-mirror: ${msg}`);
  process.exit(1);
};

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

const sentence = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
const labelOf = (slug) => sentence(slug.replace(/[-/]+/g, " "));
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

const isMedia = (el, name) => (el.localName === "img" && name === "src") || (el.localName === "image" && /^(?:xlink:)?href$/.test(name));
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
  if (hasCredential(attr.value)) return void el.removeAttributeNode(attr);
  const kept = URL_ATTR.test(name) || GEOMETRY(el, name) ? attr.value : dropIds(name, attr.value);
  if (!kept && attr.value) return void el.removeAttributeNode(attr);
  const swapped = () => scrubIdentity(kept, ctx.swap);
  const value = URL_ATTR.test(name) ? kept
    : PROSE_ATTRS.has(name) ? scrubText(kept, rule, ctx, el, name)
    : isReadableAttr(name) ? swapped().replace(MONEY, fakeMoney)
    : swapped();
  const kinds = new Set();
  attrKinds(el, name, value, ctx, kinds);
  if (name !== "style") attributeTextKinds(el, name, value, ctx, kinds);
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

export const FANSLY_MIRROR_BUILT: ReadonlySet<string> = new Set(${JSON.stringify([...BUILT_PATHS])});

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
  ], BLANK_PNG);
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
  const readAudited = (entry, file) => {
    const buf = fs.readFileSync(file);
    if (createHash("sha256").update(buf).digest("hex") !== entry.sha256?.file) fail(`entry ${entry.id}: capture digest mismatch`);
    return buf;
  };
  if (!entries.some((entry) => {
    const file = fileIn(entry.file);
    return file && readAudited(entry, file).toString("utf8").toLowerCase().includes(username);
  })) fail("creator username appears in no captured document");
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
    const buf = readAudited(entry, file);
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
  const ctx = { username, pages, aliases, root: STAGE, build, blank, assets: new Set([blank]), swap, needles, people: peopleRe, unwired: new Set() };
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
    BLANK_PNG,
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
  selfTest(fail);
  if (CHECK) check();
  else main();
} catch (e) {
  fail(`cannot parse or classify the tree (${e?.name || "error"})`);
}
