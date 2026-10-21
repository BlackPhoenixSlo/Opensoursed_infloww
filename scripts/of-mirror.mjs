#!/usr/bin/env node
/**
 * Static mirror of the OnlyFans creator UI from a SiteSucker dump, for OF
 * Manager (/of-manager/<section>/...): the pages the "sources" table maps
 * (home feed, new post, notifications, chats, vault, queue, collections,
 * statements, statistics, banking, the creator's own profile, release forms) and settings.
 *
 *   node scripts/of-mirror.mjs [dumpDir] [--live <liveDir>] [--live2 <stateDir>] [--live3 <pagesDir>] [--live4 <pagesDir>] [--allow-multiple-accounts]
 *   node scripts/of-mirror.mjs --check
 *   (default dumpDir: ~/Downloads/us.sitesucker.mac.sitesucker;
 *    default liveDir: ~/Downloads/of-live-capture, if it exists;
 *    default stateDir: ~/Downloads/of-live-capture-2, if it exists;
 *    default pagesDir: ~/Downloads/of-live-capture-3, if it exists;
 *    --live4: a second pagesDir, default ~/Downloads/of-live-capture-5, if it exists: Go live, its dashboard and schedule form)
 *
 * liveDir is a logged-in capture of settings: manifest.json plus <slug>.html files holding
 * #app.outerHTML (slug = settings path with "/" -> "__"). A live page wins over
 * the dump's page for the same slug (the dump only has SPA shells for some);
 * the dump still supplies the <head> stylesheets, CSS, fonts and icons, since
 * the live files carry no static assets. "<slug>__modal-<n>.html" files are
 * the page with a modal open (its nodes after PORTALS); each becomes the page
 * "<final_url slug>/modal-<n>", reached from the button that opened it.
 *
 * stateDir holds "<slug>__state-<name>.html" files: a full document.body with one
 * control open (a select/autocomplete menu, a sort dropdown, the focused bio
 * editor). Each becomes the page "<slug>/state-<name>", reached from that control
 * on the page (or modal page) it was opened from; there, the open menu is shown
 * under its control and the backdrop, the control and every option link back.
 * A state with no open control (a bare modal) duplicates a modal page and is skipped.
 *
 * pagesDir is a logged-in capture of any mirrored page outside settings:
 * "<slug>.html" holding the full document (slug = OF path with "/" -> "__", the
 * root "home"), its URL in "<slug>.meta.json" or in a manifest.json list
 * ({ file | slug, url, final_url, state }). A default-state capture wins over the
 * dump's page for the same route. "<slug>__state-<name>.html" is that page with a
 * dialog, dropdown or popup open: it becomes "<page>/state-<name>", reached from the
 * control that opens it (the PAGE_STATES table; a dropdown open in the capture is
 * found from its markup), closed by its backdrop, Cancel/Close or the control again.
 * One that only focuses a control is skipped. OF's left nav (header.l-header: its menu and the
 * avatar/More drawer) is taken once from the home page's input and put on every page, its current
 * section marked; the drawer open is the home page state built from the capture that shows it.
 *
 * All inputs are untrusted data: this only reads and string-processes them,
 * never executes or imports anything from them. Every <script> is dropped; each page gets only
 * the generator's own one-line theme boot script (THEME_BOOT).
 *
 * Writes (built in app/public/of-mirror.tmp, then swapped in only after the
 * leak guard passes, so a failed run leaves the previous output untouched; re-running is idempotent):
 *   app/public/of-mirror/pages/<section>/<sub>.html  one standalone document per page
 *                                            (a section root is index.html, settings'
 *                                            is profile.html): OF stylesheets + the
 *                                            left nav + rendered <main id="content"> + the icon sprite
 *   app/public/of-mirror/static/<build>/...  only the CSS those pages link, and
 *                                            the fonts/images that CSS references
 *   app/public/of-mirror/NOTICE.md           what the folder contains
 *   app/lib/of-mirror-pages.ts               the sections and pages the route serves
 *   app/lib/of-mirror-build.ts               the OF build (x-of-rev) the static dir is from,
 *                                            which the drift banner checks the live build against
 *
 * --check needs no inputs: it re-runs the guard's pattern checks (hosts, remote urls, emails, IPs,
 * handles, links, "$" amounts, digit runs) over the committed app/public/of-mirror and checks that
 * app/lib/of-mirror-pages.ts and the page files list the same pages, and that app/lib/of-mirror-build.ts
 * names a build dir under app/public/of-mirror/static. Exit 1 on any hit.
 *
 * The logged-in account is scrubbed: username, display name, email, masked
 * phone, bio, watermark text, avatar/cover/QR images, numeric user ids, login
 * session IPs/places/devices, fan names, link names, image URLs on OF hosts.
 * Every page (settings too) also gets the "scrub rules": people
 * -> "Fan N"/"@fanN", messages/posts/comments -> lorem, every image -> grey, "$"
 * amounts -> a fixed fake set, numbers outside dates and times -> fake digits,
 * bank and card details masked; outside settings also ids out of links and attributes.
 * The run fails (writing nothing) if the inputs show more than one account or
 * a name under 4 chars, or if any output file (pages, CSS, SVG; attributes and
 * inline styles included) holds a detected identity string, an OF host other
 * than the allowed text URLs, a remote CSS load, a non-placeholder email,
 * IPv4/IPv6 address, or a run of 9+ digits (SVG path/transform/points
 * numbers, decimals and base64 excluded); or if a page links anywhere but "#",
 * an /of-manager route or a mirrored asset, shows an "@handle" other than the
 * placeholders, a "$" amount outside the fake set, or a scrubbed name or text.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(REPO, "app/public/of-mirror");
const STAGE = `${OUT}.tmp`; // built here, swapped into OUT once the guard passes
const LIST = path.join(REPO, "app/lib/of-mirror-pages.ts");
const BUILD_TS = path.join(REPO, "app/lib/of-mirror-build.ts");

const MANAGER = "/of-manager";
const STATIC_URL = "/of-mirror/static";
const STATIC_PREFIX = "static2.onlyfans.com/static/prod/f/"; // + <build>/<file>

const MAX_ASSET_BYTES = 2 * 1024 * 1024;
const PLACEHOLDER = { username: "yourmodel", name: "Your Model", email: "model@example.com" };
const SUPPORT_EMAIL = "support@onlyfans.com"; // OF's own address, the only one not scrubbed
const BIO = "Welcome to my page.";
// Neutral grey square for every image we cannot (or must not) mirror.
const BLANK_IMG =
  "data:image/svg+xml;base64," +
  Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" fill="#e5e7eb"/></svg>').toString("base64");

// OF_MIRROR_KEEP_STAGE=1 leaves a failed run's pages in of-mirror.tmp to inspect;
// OF_MIRROR_DEBUG=1 logs every text the scrub rules replace (real data: for a local eyeball pass only).
const DEBUG = !!process.env.OF_MIRROR_DEBUG;
process.on("exit", () => process.env.OF_MIRROR_KEEP_STAGE || fs.rmSync(STAGE, { recursive: true, force: true }));
const fail = (msg) => {
  console.error(`of-mirror: ${msg}`);
  process.exit(1);
};

const args = process.argv.slice(2);
const dirFlag = (name) => {
  const i = args.indexOf(name);
  if (i < 0) return undefined;
  const dir = args.splice(i, 2)[1];
  if (!dir) fail(`${name} needs a directory`);
  return path.resolve(dir);
};
const ALLOW_MANY = args.includes("--allow-multiple-accounts") && args.splice(args.indexOf("--allow-multiple-accounts"), 1).length > 0;
const CHECK = args.includes("--check") && args.splice(args.indexOf("--check"), 1).length > 0;
const liveArg = dirFlag("--live");
const liveArg2 = dirFlag("--live2");
const liveArg3 = dirFlag("--live3");
const liveArg4 = dirFlag("--live4");
const DUMP = path.resolve(args[0] || path.join(os.homedir(), "Downloads/us.sitesucker.mac.sitesucker"));
const DEFAULT_LIVE = path.join(os.homedir(), "Downloads/of-live-capture");
const LIVE = liveArg || (fs.existsSync(DEFAULT_LIVE) ? DEFAULT_LIVE : null);
const DEFAULT_LIVE3 = path.join(os.homedir(), "Downloads/of-live-capture-3");
const LIVE3 = liveArg3 || (fs.existsSync(DEFAULT_LIVE3) ? DEFAULT_LIVE3 : null);
const DEFAULT_LIVE4 = path.join(os.homedir(), "Downloads/of-live-capture-5"); // the Go live page
const LIVE4 = liveArg4 || (fs.existsSync(DEFAULT_LIVE4) ? DEFAULT_LIVE4 : null);
const DEFAULT_LIVE2 = path.join(os.homedir(), "Downloads/of-live-capture-2");
const LIVE2 = liveArg2 || (fs.existsSync(DEFAULT_LIVE2) ? DEFAULT_LIVE2 : null);
const PORTALS = "<!-- body-level portals (modals/menus) -->";
// Placeholder values the scrub writes; everything else of their kind is a leak.
const SAFE_IPS = new Set(["127.0.0.1", "1.2.3.4"]); // 1.2.3.4: OF's own block-by-IP format hint
const secrets = new Set(); // identity strings seen in the inputs; none may reach the output
const fanSecrets = new Set(); // fan names: short common words, so only checked in pages, not OF's CSS
const dataSecrets = new Set(); // what the scrub rules replaced (names, handles, texts): checked in page text, as whole words

// ---------------------------------------------------------------- sources

// OF path (pathname, plus the query of a chat send list) -> our section and its
// sub page ("$n": the regex's groups). First match wins. An OF path no row
// matches, or whose sub still holds a numeric id, has no page here: links to it
// are "#". The creator's own profile ("/<username>") is matched in routeOfPath.
const ROUTES = [
  [/^\/my\/settings(?:\/(.+))?$/, "settings", "$1"],
  [/^\/$/, "home", ""],
  [/^\/posts\/create$/, "new-post", ""],
  [/^\/my\/streaming$/, "streaming", ""],
  [/^\/my\/streaming\/dashboard$/, "streaming", "dashboard"],
  [/^\/my\/streaming\/dashboard\/create$/, "streaming", "dashboard/create"],
  [/^\/my\/notifications(?:\/(.+))?$/, "notifications", "$1"],
  [/^\/my\/chats\/chat\/\d+(?:\/(.+))?$/, "messages", "chat/$1"], // every chat is the one mirrored chat
  [/^\/my\/chats\/send\?(\w+)=(\w+)$/, "messages", "send/$1-$2"],
  [/^\/my\/chats(?:\/(.+))?$/, "messages", "$1"],
  [/^\/my\/vault(?:\/list\/all)?$/, "vault", ""],
  [/^\/my\/vault\/list\/\d+$/, "vault", "list"], // every custom list is the one mirrored list
  [/^\/my\/queue$/, "queue", ""],
  [/^\/saved-for-later-(posts|messages)$/, "queue", "saved-for-later-$1"],
  [/^\/my\/collections\/user-lists\/\d+$/, "collections", "user-lists/list"],
  [/^\/my\/collections\/user-lists\/\d+\/posts$/, "collections", "user-lists/list/posts"], // a list's Posts tab (listPostsRaw)
  [/^\/my\/collections(?:\/(.+))?$/, "collections", "$1"],
  [/^\/my\/statements(?:\/(.+))?$/, "statements", "$1"],
  [/^\/my\/stats\/(.+)$/, "statements", "stats/$1"], // its "Earning statistics" and "Chargebacks" tabs
  [/^\/my\/statistics(?:\/overview)?$/, "statistics", ""],
  [/^\/my\/statistics\/(.+)$/, "statistics", "$1"],
  [/^\/my\/banking(?:\/(.+))?$/, "bank", "$1"],
  [/^\/my\/payments(?:\/(.+))?$/, "bank", "payments/$1"],
  [/^\/my\/release-forms$/, "release-forms", ""],
];
// Every section the OF Manager nav links to; each needs its root page.
const SECTIONS = ["home", "streaming", "new-post", "notifications", "messages", "vault", "queue", "collections", "statements", "statistics", "bank", "profile", "release-forms", "settings"];
// The sub a section root shows: OF's settings root is its profile page; elsewhere the root page itself.
const SECTION_INDEX = { settings: "profile", statistics: "overview/earnings" }; // OF lands /my/statistics on Overview
// Infloww lands its Statistics menu on Statements › Earnings (app/next.config.ts redirects the bare section there), so
// OF's own links to /my/statistics (its rail, Back, the menus) name Overview's page (hrefOf).
const LINK_INDEX = new Set(["statistics"]);
// The stylesheets (build dir CSS files, in order) the live page links, for a page captured as #app alone:
// its <head> comes from the dump's copy, whose list differs (and named files the dump did not fetch).
const STREAMING_CSS =
  "chunk-vendors-95328e84 app 40134 11452 main-017397ff main-4c120c8f 70780 settings-page 97727 6088 47612 95301 16705 61894 48790 58702 86950 99847 28945 27646 84702 27323 86031 302 15576 45432 63420 87989 87473 64090 3781 streaming-age-017397ff 45843 35240".split(" ");
const DASHBOARD_CSS = [...STREAMING_CSS, "streaming-dashboard"];
const LIVE_CSS = {
  "/my/streaming": STREAMING_CSS,
  "/my/streaming/dashboard": DASHBOARD_CSS,
  "/my/streaming/dashboard/create": [...DASHBOARD_CSS, "91617", "streaming-create-edit-schedule-017397ff"],
};
// Where the pages are in the dump, under onlyfans.com/ (plus "<username>.html", the profile).
const DUMP_ROOTS = ["index.html", "posts/create.html", "my"];
// First path segments of OF's own pages: a link there is never to a user.
const NOT_USERS = new Set(
  "my posts help terms privacy cookies about contact contacts dmca brand transparency-center acceptable-use-policy antitraffickingstatement fightcsam appeal appeals captcha contract complaints faq legal blog onlyfans search explore index".split(" "),
);
const MODEL_HANDLES = new Set(); // the account's usernames, lowercased, once detected
// With --allow-multiple-accounts one account can be a fan on another's page (a
// subscriber card): while such a page is built, the accounts other than its owner.
let pageFans = new Set();
const accountNames = new Map(); // username, lowercased -> the display names seen with it
const isModel = (h) => MODEL_HANDLES.has(h) && !pageFans.has(h);
const BUILT = new Set(); // pageKey of every page this run writes, known before any is built

/** "onlyfans.com/my/chats/send\uFE56list=users.html" (dump file) or "onlyfans.com/my/vault" (link) -> "/my/chats/send?list=users", "/my/vault"; null off onlyfans.com. */
function ofPathOf(rel) {
  if (!rel || (rel !== "onlyfans.com" && !rel.startsWith("onlyfans.com/"))) return null;
  let p = rel.slice("onlyfans.com".length);
  try {
    p = decodeURIComponent(p);
  } catch {
    // a stray "%": keep it as it is
  }
  p = p.replace(/\uFE56/g, "?").replace(/\.html$/, "").replace(/(^|\/)index$/, "").replace(/\/+$/, "");
  return p || "/";
}

/** OF path -> { section, sub }, or null if no page of ours stands for it. */
function routeOfPath(p) {
  if (!p) return null;
  const own = p.match(/^\/([\w.-]+)(?:\/([\w-]+))?$/); // "/<username>", "/<username>/media"
  if (own && isModel(own[1].toLowerCase())) return { section: "profile", sub: (own[2] || "").toLowerCase() };
  for (const [re, section, tpl] of ROUTES) {
    const m = p.match(re);
    if (!m) continue;
    const sub = tpl
      .replace(/\$(\d)/g, (_, i) => m[i] || "")
      .toLowerCase()
      .replace(/(^|\/)index$/, "")
      .replace(/^\/+|\/+$/g, "");
    if (section === "settings" && SETTINGS_OFF.some((off) => sub === off || sub.startsWith(`${off}/`))) return null;
    return /\d{5,}/.test(sub) || !/^[\w./-]*$/.test(sub) ? null : { section, sub };
  }
  return null;
}

const pageKey = (section, sub) => `${section}/${sub || SECTION_INDEX[section] || ""}`;
const pageFile = (section, sub) => `${section}/${sub || SECTION_INDEX[section] || "index"}.html`;
const hrefOf = (section, sub) => (sub || LINK_INDEX.has(section) ? `${MANAGER}/${section}/${sub || SECTION_INDEX[section]}` : `${MANAGER}/${section}`);

/**
 * Our URL for an OF page, or null if this run builds no page for it. A tab
 * whose own page is only a shell in the inputs opens its first built sub-tab.
 */
function routeOf(rel) {
  const r = routeOfPath(ofPathOf(rel));
  if (!r) return null;
  if (BUILT.has(pageKey(r.section, r.sub))) return hrefOf(r.section, r.sub);
  const prefix = `${r.section}/${r.sub ? `${r.sub}/` : ""}`;
  const child = [...BUILT].sort().find((k) => k.startsWith(prefix) && !k.includes("/state-"));
  return child ? hrefOf(r.section, child.slice(r.section.length + 1)) : null;
}

/** The other user a profile link points at ("/<handle>", "/u<id>"), lowercased; null for OF's pages, posts and the model. */
function userOf(rel) {
  const h = ofPathOf(rel)?.match(/^\/([\w.-]{2,40})$/)?.[1].toLowerCase();
  return !h || /^\d+$/.test(h) || NOT_USERS.has(h) || isModel(h) ? null : h;
}

// ---------------------------------------------------------------- discovery

/** Every dump page (path relative to the dump) that a route maps, sorted. */
function listPages() {
  const root = path.join(DUMP, "onlyfans.com");
  const files = [];
  const walk = (p) => {
    if (!fs.existsSync(p)) return;
    if (fs.statSync(p).isDirectory()) for (const e of fs.readdirSync(p)) walk(path.join(p, e));
    else if (p.endsWith(".html")) files.push(path.relative(DUMP, p).split(path.sep).join("/"));
  };
  for (const r of DUMP_ROOTS) walk(path.join(root, r));
  return files.filter((rel) => routeOfPath(ofPathOf(rel))).sort();
}

// ---------------------------------------------------------------- html helpers

/** The element starting at `start` (an opening `<tag`), through its matching close tag. */
function element(html, start, tag) {
  const re = new RegExp(`<(/?)${tag}\\b`, "gi");
  re.lastIndex = start;
  let depth = 0;
  for (let m; (m = re.exec(html)); ) {
    depth += m[1] ? -1 : 1;
    if (depth === 0) return html.slice(start, html.indexOf(">", m.index) + 1);
  }
  return null;
}

const TAG = /<([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
const ATTR = /(\s)([\w:-]+)="([^"]*)"/g;

const decode = (v) => v.replace(/&amp;/g, "&");

const VOID = new Set("area base br col embed hr img input link meta source track wbr use path circle rect stop polygon polyline line ellipse".split(" "));

/**
 * `html` rebuilt token by token: text(text, stack) for each text node outside
 * <style>/<script>, tag(tag, el, stack) for each start tag. stack: the open
 * elements, innermost last, each { tag, cls (Set), href, fan (data-fan), at (at-attr) }.
 */
function mapHtml(html, { text, tag }) {
  const stack = [];
  return html.replace(/<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>|[^<]+|</g, (all, close, name, attrs) => {
    if (name === undefined) {
      if (all.startsWith("<!--") || all === "<" || !text) return all;
      return stack.some((e) => e.tag === "style" || e.tag === "script") ? all : text(all, stack);
    }
    const t = name.toLowerCase();
    if (close) {
      const i = stack.findLastIndex((e) => e.tag === t);
      if (i >= 0) stack.length = i;
      return all;
    }
    const el = {
      tag: t,
      cls: new Set((attrs.match(/\sclass="([^"]*)"/)?.[1] || "").split(/\s+/).filter(Boolean)),
      href: attrs.match(/\shref="([^"]*)"/)?.[1],
      fan: attrs.match(/\sdata-fan="(\d+)"/)?.[1],
      at: attrs.match(/\sat-attr="([^"]*)"/)?.[1],
    };
    const out = tag ? tag(all, el, stack) : all;
    if (!VOID.has(t) && !/\/\s*$/.test(attrs)) stack.push(el);
    return out;
  });
}

// ---------------------------------------------------------------- rewriting

const assets = new Set(); // paths relative to STATIC_PREFIX, e.g. "<build>/app.css"

/** Resolve a dump-relative reference to a path relative to the dump root, or null if off-dump. */
function resolveRef(fromRel, ref) {
  ref = decode(ref).split(/[?#]/)[0];
  if (!ref) return null;
  const abs = ref.match(/^https?:\/\/(.+)$/);
  if (abs) return abs[1];
  if (/^[a-z]+:/i.test(ref) || ref.startsWith("//")) return null;
  // Root-relative (the live capture's links) are on onlyfans.com.
  const rel = ref.startsWith("/") ? `onlyfans.com${ref}` : path.posix.join(path.posix.dirname(fromRel), ref);
  return path.posix.normalize(rel).replace(/\/$/, "");
}

function staticUrl(rel) {
  if (!rel?.startsWith(STATIC_PREFIX)) return null;
  const file = rel.slice(STATIC_PREFIX.length);
  if (!fs.existsSync(path.join(DUMP, rel))) return null;
  assets.add(file);
  return `${STATIC_URL}/${file}`;
}

const SVG_TAGS = /^(?:svg|symbol|clippath|lineargradient|radialgradient|mask|pattern|filter|g|path|defs|use)$/i;
const CSS_URL = /url\(\s*(?:&quot;|')?([^)'"]*?)(?:&quot;|')?\s*\)/g;
const OF_URL = /^\s*(?:https?:)?\/\/[\w.-]*\bonlyfans(?:api)?\.com\b/i;
/** The local copy of a mirrored static asset, else the grey placeholder. */
const mirrorUrl = (fromRel, url) => staticUrl(resolveRef(fromRel, url)) || BLANK_IMG;

/** Rewrite one start tag. `strict` (pages outside settings): every image is grey, links to other users are "#" with data-fan, ids go. */
function rewriteTag(fromRel, tag, attrs, pii, strict) {
  let top = false;
  let fan = null;
  // The account's avatar and its profile QR code carry its name as alt text.
  const own = tag === "img" && pii.some((p) => attrs.toLowerCase().includes(`alt="${p.toLowerCase()}"`));
  const raster = (v) => /^data:image\/(?!svg)/i.test(v);
  attrs = attrs.replace(ATTR, (all, sp, name, value) => {
    const n = name.toLowerCase();
    if (n.startsWith("on") || n === "srcset") return "";
    if (n === "href" || n === "xlink:href") {
      if (value.startsWith("#")) return all;
      const rel = resolveRef(fromRel, value);
      const asset = staticUrl(rel);
      if (asset) return `${sp}${name}="${asset}"`;
      const route = tag === "a" && rel ? routeOf(rel) : null;
      if (route) {
        top = true;
        return `${sp}${name}="${route}"`;
      }
      const user = strict && tag === "a" && rel ? userOf(rel) : null;
      if (user) fan = fanOfHandle(user);
      return `${sp}${name}="#"`;
    }
    if (n === "src") {
      if (own || (strict && raster(value))) return `${sp}src="${BLANK_IMG}"`;
      if (value.startsWith("data:")) {
        const b64 = value.match(/^data:[^,]*;base64,(.*)$/);
        const body = b64 ? Buffer.from(b64[1], "base64").toString("utf8") : decodeURIComponent(value);
        return pii.some((p) => body.toLowerCase().includes(p.toLowerCase())) ? `${sp}src="${BLANK_IMG}"` : all;
      }
      const asset = staticUrl(resolveRef(fromRel, value));
      return `${sp}src="${asset || BLANK_IMG}"`;
    }
    if (n === "style") {
      const keep = (ref) => /^#/.test(ref) || (/^data:/.test(ref) && !(strict && raster(ref)));
      return `${sp}${name}="${value.replace(CSS_URL, (all, ref) => (keep(ref) ? all : `url('${mirrorUrl(fromRel, ref)}')`))}"`;
    }
    if (strict) {
      // Ids inside class names ("js-dynamic-scroller-item-<id>").
      if (n === "class") return `${sp}class="${value.replace(/\d{6,}/g, "0")}"`;
      // Element ids carry list, label and user names ("AIimage-5"); main#content stays for the layout CSS.
      if (n === "id" && !SVG_TAGS.test(tag) && value !== "content") return "";
      // Form values (a hidden country id); the scrub fills the identity inputs itself.
      if (n === "value" && tag === "input" && !/\stype="(?:checkbox|radio|submit|button)"/.test(attrs)) return "";
      // Avatar and media alt texts name people; posters and lazy sources are media.
      if (n === "alt") return own ? all : `${sp}alt=""`;
      if (/^(poster|data-src|data-poster|data-original)$/.test(n)) return `${sp}${name}="${BLANK_IMG}"`;
      // Chat, post, list and user ids (ids, aria-controls, data-*); geometry keeps its numbers.
      if (!/^(d|points|viewbox|transform|class|width|height|x|y|cx|cy|r)$/.test(n) && /\d{6,}/.test(value)) return "";
    }
    // Any other attribute that is a URL on an OF host (data-src, poster, ...); text attributes are left to the guard.
    if (OF_URL.test(value) && !/^(title|alt|value|placeholder|aria-)/.test(n)) return `${sp}${name}="${mirrorUrl(fromRel, value)}"`;
    return all;
  });
  if (fan) attrs += ` data-fan="${fan}"`;
  if (top && !/\starget=/.test(attrs)) attrs += ' target="_top"';
  return `<${tag}${attrs}>`;
}

function rewrite(fromRel, html, pii, strict = false) {
  html = html.replace(/<(script|noscript|iframe)\b[\s\S]*?<\/\1>/gi, "");
  // Strict: no comments; ids out of inline <style> selectors (".js-video-message<timestamp>-dimensions").
  if (strict) html = html.replace(/<!--[\s\S]*?-->/g, "").replace(/(<style\b[^>]*>)([\s\S]*?)(?=<\/style>)/gi, (_, open, css) => open + css.replace(/\d{6,}/g, "0"));
  return html.replace(TAG, (_, tag, attrs) => rewriteTag(fromRel, tag, attrs, pii, strict));
}

// ---------------------------------------------------------------- identity

function detectIdentity(raw) {
  const username =
    raw.match(/class="b-menu-list__text g-semibold"><a [^>]*>\s*@([\w.]+)\s*<\/a>/)?.[1] ||
    raw.match(/l-sidebar__username[\s\S]*?class="g-user-username[^"]*">\s*@([\w.]+)\s*</)?.[1];
  const name =
    raw.match(/l-sidebar__username[\s\S]*?class="g-user-name[^"]*">\s*([^<]*?)\s*</)?.[1] ||
    raw.match(/l-sidebar__avatar[\s\S]*?<img[^>]*\salt="([^"]+)"/)?.[1];
  return { username, name };
}

/** Identity strings in a raw page beyond the account's names: emails, session IPs, the numeric user id. */
function collectSecrets(raw) {
  for (const m of raw.matchAll(/[\w.%+-]+@[a-z][\w-]*(?:\.[\w-]+)*\.[a-z]{2,}/gi)) if (m[0].toLowerCase() !== SUPPORT_EMAIL) secrets.add(m[0]);
  for (const m of raw.matchAll(/b-session-location">\s*([\d.]+)/g)) secrets.add(m[1]);
  for (const m of raw.matchAll(/\sid="(\d{5,})"/g)) secrets.add(m[1]);
}

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Each "Offer claimed" / viewer list row: a numbered placeholder fan instead of the real one. */
function scrubFans(html) {
  let n = 0;
  return html.replace(/(<div [^>]*class="b-viewer-row\b)([\s\S]*?)(?=<div [^>]*class="b-viewer-row\b|<\/footer>)/g, (_, open, row) => {
    n++;
    // (A row scrubData already renamed holds "Fan N", not a name.)
    for (const m of row.matchAll(/class="g-user-name[^"]*">\s*([^<]*?)\s*</g)) if (m[1].length >= 4 && !/^Fan \d+$/.test(m[1])) fanSecrets.add(m[1]);
    for (const m of row.matchAll(/\salt="([^"]+)"/g)) if (m[1].length >= 4 && !/^Fan \d+$/.test(m[1])) fanSecrets.add(m[1]);
    row = row
      .replace(/(m-text-avatar">)[^<]*/g, "$1 F ")
      .replace(/(class="g-user-name[^"]*">)[^<]*/g, `$1 Fan ${n} `)
      .replace(/\salt="[^"]*"/g, ` alt="Fan ${n}"`);
    return open + row;
  });
}

function scrub(html, ids) {
  html = html
    // Every email except OF's own support address.
    .replace(/[\w.%+-]+@[a-z][\w-]*(?:\.[\w-]+)*\.[a-z]{2,}/gi, (m) => (m.toLowerCase() === SUPPORT_EMAIL ? m : PLACEHOLDER.email))
    .replace(/\*{4,}\d{2,4}/g, "******0000")
    // Phone country code prefix.
    .replace(/(class="v-text-field__prefix">)\s*\+\d+\s*</g, "$1+1<")
    // Profile bio (a ProseMirror div), its counter, and the watermark text.
    .replace(/(data-placeholder="Bio"[^>]*>)[\s\S]*?(<\/div>)/, `$1<p>${BIO}</p>$2`)
    .replace(/>\s*\d+\/1000\s*</, `>${BIO.length}/1000<`)
    .replace(/(<p class="g-input__help">\s*Current:)[^<]*/, `$1 ${PLACEHOLDER.username} `)
    // Numeric ids (the user id on the promotion block).
    .replace(/\sid="\d{5,}"/g, "")
    // Login sessions: device, time and place of each.
    .replace(/(m-session-row[^"]*">)<strong>[^<]*<\/strong>[^<]*/g, "$1<strong>Web browser</strong>, Computer ")
    .replace(/(class="session-time">\s*<span[^>]*>)[^<]*/g, "$1 1/1/26 12:00 am ")
    .replace(/(class="b-session-location">)[^<]*/g, "$1 127.0.0.1 • Somewhere ")
    // Text avatars show the account's initials.
    .replace(/(m-text-avatar">)[^<]*/g, `$1 ${PLACEHOLDER.name[0]} `);
  // Free trial / tracking link names.
  let link = 0;
  html = html.replace(/(m-trial-link-block">[\s\S]*?b-offer-join__details m-break-word">)[^<]*/g, (_, pre) => `${pre} Link ${++link} `);
  // The welcome message shown with each promotion campaign.
  html = html.replace(/(b-offer-join__bubble__text[^"]*">\s*<div [^>]*>)[^<]*/g, `$1${BIO}`);
  html = scrubFans(html);
  // Input values live in DOM properties, so they are not in the dump; the
  // counters next to them still give the real lengths away. Fill the two
  // identity inputs with the placeholders and zero the rest.
  html = html.replace(
    /(<input\b[^>]*\sid="input-(\w+)"[^>]*>)((?:(?!<input\b)[\s\S])*?<div class="v-counter[^"]*">)\s*\d+\s*\/\s*(\d+)\s*</g,
    (_, input, field, between, max) => {
      const value = field === "name" ? PLACEHOLDER.name : field === "username" ? PLACEHOLDER.username : "";
      const tag = value ? input.replace(/>$/, ` value="${value}">`) : input;
      return `${tag}${between}${value.length} / ${max}<`;
    },
  );
  html = html.replace(/(<input\b[^>]*\sid="input-login"[^>]*)>/, `$1 value="${PLACEHOLDER.username}">`);
  for (const id of ids) {
    if (id.name) html = html.replace(new RegExp(esc(id.name), "gi"), PLACEHOLDER.name);
    if (id.username) html = html.replace(new RegExp(esc(id.username), "gi"), PLACEHOLDER.username);
  }
  return html;
}

// ---------------------------------------------------------------- people

// Every other person on the pages (fan, creator) gets a number, the same one on every page.
const fans = { handles: new Map(), names: new Map(), n: 0 };
const fanOfHandle = (h) => {
  h = h.toLowerCase();
  if (!fans.handles.has(h)) fans.handles.set(h, ++fans.n);
  return fans.handles.get(h);
};
const listNames = new Map(); // user-made list and folder name -> its number
const fanOfName = (name, n) => {
  if (!fans.names.has(name)) fans.names.set(name, n ?? ++fans.n);
  return fans.names.get(name);
};
// A user-made name that is also a word on OF's own pages (a list named like a language in settings' language list):
// still replaced, but the guard cannot tell the two apart.
const OF_OWN_WORDS = new Set(["spanish"]);
/** Remember a replaced string for the guard, if it is long enough to look for. */
const remember = (s, min = 4) => {
  s = s.trim();
  if ([...s].length >= min && !OF_OWN_WORDS.has(s.toLowerCase())) dataSecrets.add(s);
};

// ---------------------------------------------------------------- scrub rules

// Pages outside settings show fans, other creators, messages, posts and money.
// A text node is scrubbed by the rule of its nearest enclosing element that has
// one (an element matches if it has every class of the rule; ties go to the
// first rule here). Kinds:
//   handle   "@fanN"
//   name     a person: "Fan N"
//   with     "with <a person>": "with Fan N"
//   text     message, post, caption, comment: neutral lorem of a similar length
//   list     a user-made list or folder name: "List N" (OF's own names stay)
//   label    a user-made post label tab: "Label N"
//   bio      the model's bio: BIO, which ofMirrorIdentity swaps for the live one
//   place    a location: "Somewhere"
//   initial  a fan's text avatar: "F"
//   bank     a value after a label matching BANK_LABEL: masked
// Text with no rule directly inside a link to another user is a name. Text matching
// KEEP_TEXT is OF's own and only gets the passes below. Then, on every node:
// "$" amounts -> fakeMoney, card and IBAN tails -> 0000, "@handles" -> "@fanN",
// and every number outside a date, a time, a char counter or a video player's menus -> fake digits
// (a date or time is an explicit format: see DATE_TOKEN).
const TEXT_RULES = [
  ["g-user-username", "handle"],
  ["g-user-realname", "name"],
  ["g-user-name", "name"],
  ["b-username", "name"],
  ["m-disabled-username", "name"],
  ["b-chat__user-status", "with"], // "with <name>" under the chat gallery title
  ["b-chats__item__last-message__text", "text"],
  ["b-chats__item__media-label", "text"],
  ["b-chat__message__text-holder", "text"],
  ["b-chat__message__text", "text"],
  ["g-truncated-text", "text"],
  ["b-post__text", "text"],
  ["b-notifications__text-comment", "text"],
  ["b-comments__item__text", "text"],
  ["b-content-inside-thumbs__only-text", "text"],
  ["b-story-item__text user-select-none", "text"], // profile highlights (a fan's story item also has g-user-name)
  ["b-rows-lists__item__name", "list"],
  ["b-list-titles__item__text", "list"],
  ["@profile_label", "label"], // the profile's post label tabs ("@": an at-attr)
  ["b-user-info__text", "bio"],
  ["b-user-info__detail", "place"],
  ["g-avatar__placeholder", "initial"],
  ["b-payout-type__value", "bank"],
].map(([cls, kind]) => ({ cls: cls.split(" "), kind }));
const KEEP_TEXT = /^(?:OnlyFans|@onlyfans|(?:Recurring )?Subscription (?:to|from)|(?:Payment for message|Tip) from|Transaction could not be processed|\d+\+? new posts?|Fenix (?:International Limited|Internet LLC),.*)$/i;
// OF's own list and vault folder names, and the words of its list pickers.
const OF_LISTS = new Set(
  [
    ...["All media", "Messages", "Posts", "Stories", "Streams", "Uploads", "Fans", "Following", "Restricted", "Blocked", "Muted", "Friends"],
    ...["Tagged", "Purchased", "Recent", "Recent...", "Bookmarks", "Close Friends", "Subscribers", "Subscriptions"],
    ...["Add labels", "Add to favorites and other lists", "Lists", "Labels", "Archive"],
    ...["Vault", "Collections"], // the other h1 of a list's page
  ].map((s) => s.toLowerCase()),
);
const BANK_LABEL = /name|iban|bic|swift|account|routing|bank|country|state|address|city|postal|zip|tax|vat|phone|birth|e-?mail/i;
// Numbers stay only inside an explicit date, time or duration, and in calendars and date pickers.
const COUNTER = /^(?:\d+\s*\/\s*\d+|(?:19|20)\d\d)$/; // "0 / 2000": a limit, not a count; "2026": a lone year (a year picker)
const MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?";
const UNIT = "(?:[Ss]econd|[Mm]inute|[Hh]our|[Dd]ay|[Ww]eek|[Mm]onth|[Yy]ear)s?";
// "Oct 4", "Sep 12, 2026", "Oct 29, '25", "October, 2026", "4 Oct", "12/31/2026", "5:06 am", "5 pm", "3 minutes ago", "7 days", "3-5 business days"
const DATE_TOKEN = `(?<![\\p{L}\\d_])(?:${MONTH}(?:\\s+\\d{1,2})?(?:,?\\s+(?:\\d{4}|'\\d\\d))?|\\d{1,2}\\s+${MONTH}(?:\\s+\\d{4})?|\\d{1,4}[/.-]\\d{1,2}[/.-]\\d{1,4}|\\d{1,2}:\\d\\d(?::\\d\\d)?(?:\\s*[AaPp][Mm])?|\\d{1,2}\\s*[AaPp][Mm]|\\d+(?:\\s*[-–]\\s*\\d+)?\\s+(?:business\\s+)?${UNIT}(?:\\s+ago)?)(?![\\p{L}\\d_])`;
// OF's own fixed phrases with numbers in them (settings): "2 step", "Top 1 or 5%", the block-by-IP format hints.
const FIXED_TOKEN = "\\b2 step\\b|\\bTop \\d+(?: or \\d+)?%|\\b1\\.2\\.[\\d*]+\\.4(?:/24)?";
// What fakeNumbers visits: a date token or a fixed phrase (kept), a "$" amount (left to fakeMoney), or a number ("1.5K": the digits before the suffix count too).
const NUMBER = new RegExp(`(${FIXED_TOKEN}|${DATE_TOKEN})|\\$\\s?[\\d,.]+|(?<![\\p{L}\\d_])\\d+(?:(?=[KMkm](?![\\p{L}_]))|(?![\\p{L}_]))`, "gu");
const DATE_CLASSES = ["v-calendar", "v-date-picker", "vdatetime", "b-month-day-cell", "b-date-value", "date", "b-table__date", "b-table__date__date", "b-table__date__time"];

// "$" amounts: zero stays, anything else becomes the fake for its number of
// integer digits ($5, $12, $123, $1,234, ...), cents as ".00"; OF's own minimums
// ("Minimum withdrawal amount is $20") stay.
const FAKE_MONEY = ["5", "12", "123", "1,234", "12,345", "123,456"];
// Amounts the guard lets through besides the fakes: OF's own fixed texts (minimum tip, price, withdrawal).
// A price is faked like any amount ($5.00 for one digit); ofMirrorIdentity swaps that one back for the model's.
const KEEP_MONEY = new Set(["$1", "$3", "$4.99", "$10", "$20", "$20.00", "$50.00"]);
const MONEY = /\$\s?\d[\d,]*(?:\.\d+)?/g;
const isFakeMoney = (m) => KEEP_MONEY.has(m) || /^\$(?:0(?:\.00)?|(?:5|12|123|1,234|12,345|123,456)(?:\.00)?)$/.test(m);
function fakeMoney(m) {
  const [int, cents] = m.replace(/[$\s,]/g, "").split(".");
  if (/^0*$/.test(int) && /^0*$/.test(cents || "")) return cents === undefined ? "$0" : "$0.00";
  const digits = String(Number(int)).length;
  return `$${FAKE_MONEY[Math.min(digits, FAKE_MONEY.length) - 1]}${cents === undefined ? "" : ".00"}`;
}
const fakeDigits = (d) => (/^0+$/.test(d) ? d : "1234567890".repeat(4).slice(0, d.length));
/** `s` with every number outside a date, time or duration faked ("$" amounts are left to fakeMoney). */
const fakeNumbers = (s) => s.replace(NUMBER, (m, date) => (date || m.startsWith("$") ? m : fakeDigits(m)));
/** A few fixed cases, run by every invocation so a regex edit that loosens the faking fails at once. */
function selfTest() {
  const cases = [
    ["Oct 4, 2026 at 5:06 am", "Oct 4, 2026 at 5:06 am"],
    ["Sep 12, 2026 · 12/31/2026 · 3 minutes ago · 7 days", "Sep 12, 2026 · 12/31/2026 · 3 minutes ago · 7 days"],
    ["You may have 250 fans in 14 days", "You may have 123 fans in 14 days"],
    ["I am 14 and 1.5K blocked", "I am 12 and 1.1K blocked"],
  ];
  for (const [input, want] of cases) if (fakeNumbers(input) !== want) fail(`self-test: fakeNumbers(${JSON.stringify(input)}) = ${JSON.stringify(fakeNumbers(input))}, want ${JSON.stringify(want)}`);
}

const LOREM = ["Lorem ipsum", "Lorem ipsum dolor sit amet.", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.", "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."];
const lorem = (s) => LOREM[[...s].length <= 14 ? 0 : [...s].length <= 40 ? 1 : [...s].length <= 100 ? 2 : 3];

const hasAll = (el, cls) => cls.every((c) => (c.startsWith("@") ? el.at === c.slice(1) : el.cls.has(c)));

/** The scrub rules applied to a page body outside settings (see above). `pii`: the model's own strings, left for scrub(). */
function scrubData(html, section, pii, listPage = false) {
  const own = (s) => pii.some((p) => s.toLowerCase().includes(p.toLowerCase()));
  const modelLink = (stack) => stack.some((e) => e.href === `${MANAGER}/profile`);
  // Settings shows the account's own avatar (initial included); only its fan rows are other people.
  const modelAvatar = (stack) => modelLink(stack) || (section === "settings" && !stack.some((e) => e.cls.has("b-viewer-row")));
  const handle = (h, fan) => {
    if (own(h) || /^(?:onlyfans|mentions|fan\d+)$/i.test(h)) return `@${h}`; // "Tags and @mentions": settings' own words
    remember(h);
    if (fan && !fans.handles.has(h.toLowerCase())) fans.handles.set(h.toLowerCase(), +fan);
    return `@fan${fanOfHandle(h)}`;
  };
  const name = (s, fan) => {
    const inner = s.match(/^\((.*)\)$/s);
    if (inner) return `(${name(inner[1].trim(), fan)})`;
    if (own(s) || KEEP_TEXT.test(s)) return s;
    remember(s);
    return `Fan ${fanOfName(s, fan && +fan)}`;
  };
  let label = ""; // the last bank detail label
  const local = new Set(); // every text replaced on this page, short ones too
  const out = mapHtml(html, {
    tag(all, el, stack) {
      // A fan's text avatar: keep ofMirrorIdentity from putting the model's picture on it.
      if (el.cls.has("m-text-avatar") && !modelAvatar(stack)) return all.replace(/\sclass="([^"]*)"/, ' class="$1 of-fan"');
      return all;
    },
    text(t, stack) {
      const s = t.trim();
      if (!s) return t;
      let ruled = null;
      for (let i = stack.length - 1; i >= 0 && !ruled; i--) {
        const r = TEXT_RULES.find((r) => hasAll(stack[i], r.cls));
        if (r) ruled = { kind: r.kind, el: stack[i] };
      }
      // The title of a user-made list's page is the list's name.
      if (!ruled && listPage && stack.some((e) => e.tag === "h1")) ruled = { kind: "list", el: stack.at(-1) };
      const fan = stack.findLast((e) => e.fan)?.fan;
      const first = () => !ruled.el.done && (ruled.el.done = true);
      let v = s;
      if (stack.at(-1)?.cls.has("b-payout-type__label")) label = s;
      if (KEEP_TEXT.test(s)) v = s;
      else if (/^@[\w.]+$/.test(s) || (ruled?.kind === "handle" && /^[\w.]+$/.test(s))) v = s.replace(/^@?([\w.]+)$/, (_, h) => handle(h, fan));
      // "(Nickname)" can carry a handle's classes; a link's own text is the person it links to.
      else if (ruled?.kind === "name" || ruled?.kind === "handle" || (!ruled && stack.at(-1)?.fan)) v = modelLink(stack) ? s : name(s, fan);
      else if (ruled?.kind === "with") v = s.replace(/^with\s+(.+)$/is, (_, n) => `with ${name(n.trim(), fan)}`);
      else if (ruled?.kind === "text") {
        remember(s, 24); // shorter ones can be OF's own words (a link in a notice)
        v = first() ? lorem(s) : "";
      } else if (ruled?.kind === "list" && !OF_LISTS.has(s.toLowerCase())) {
        remember(s);
        if (!listNames.has(s)) listNames.set(s, listNames.size + 1);
        v = `List ${listNames.get(s)}`;
      } else if (ruled?.kind === "label") {
        const [, text, count] = s.match(/^(.*?)\s*(\d*)$/);
        if (!OF_LISTS.has(text.toLowerCase())) {
          remember(text);
          if (!listNames.has(text)) listNames.set(text, listNames.size + 1);
        }
        v = `${OF_LISTS.has(text.toLowerCase()) ? text : `Label ${listNames.get(text)}`}${count ? ` ${fakeDigits(count)}` : ""}`;
      } else if (ruled?.kind === "bio") v = first() ? BIO : "";
      else if (ruled?.kind === "place") v = "Somewhere";
      else if (ruled?.kind === "initial" && !modelAvatar(stack)) v = "F";
      else if (ruled?.kind === "bank" && BANK_LABEL.test(label) && !/^\$/.test(s)) v = "••••••••";
      // Numbers in OF's own words (not what a rule wrote), outside dates and times.
      const dated = stack.some((e) => DATE_CLASSES.some((c) => e.cls.has(c)) || (section === "settings" && e.cls.has("v-list-item"))); // settings' menus list OF's own options (5% ... 40% discount)
      const player = stack.some((e) => [...e.cls].some((c) => c.startsWith("vjs-"))); // "125%", "0:30"
      if (v === s && !dated && !player && !COUNTER.test(s) && !KEEP_TEXT.test(s)) v = fakeNumbers(v);
      v = v
        .replace(MONEY, (m) => (/minimum/i.test(s) || /minimum/i.test(label) || (section === "settings" && KEEP_MONEY.has(m)) ? m : fakeMoney(m)))
        .replace(/((?:[·•*]{4}\s*){1,4})\d{2,4}\b/g, "$10000")
        .replace(/(?<![@\w.])(?:https?:\/\/)?(?:www\.)?onlyfans\.com(?:[/?][^\s<]*)?/gi, (m) => (m === "OnlyFans.com" || m === "https://onlyfans.com/my/streaming/chat" ? m : `https://onlyfans.com/${PLACEHOLDER.username}`))
        .replace(/(^|[^\w.%+-])@([\w.]*\w)/g, (_, pre, h) => pre + handle(h, fan));
      if (DEBUG && v !== s) console.error(`[${section}] ${ruled?.kind || (fan ? "in fan link" : "-")} ${[...stack.at(-1).cls].join(".")}: ${s.slice(0, 70)} -> ${v.slice(0, 30)}`);
      if (v === s) return t;
      local.add(s);
      return t.replace(s, () => v);
    },
  });
  // Tooltips and accessible names repeat a text the rules replaced (a fan's name, on the element or its row): drop them.
  const replaced = (v) => local.has(v.trim()) || dataSecrets.has(v.trim()) || fanSecrets.has(v.trim());
  return mapHtml(out, {
    tag: (all) => all.replace(/\s(?:aria-label|title|data-original-title|alt)="([^"]*)"/g, (m, v) => (replaced(v) ? "" : m)),
  });
}

// ---------------------------------------------------------------- pages

/** The <head>'s stylesheets and inline styles, in their original order. */
function headStyles(head) {
  const out = [];
  for (const m of head.matchAll(/<style\b[\s\S]*?<\/style>|<link\b[^>]*>/gi)) {
    if (m[0].startsWith("<link") && !/rel="stylesheet"/.test(m[0])) continue;
    out.push(m[0]);
  }
  return out.join("\n");
}

/** The icon sprite cut down to the <symbol>s `markup` references (it is ~230 KB whole). */
function usedSymbols(sprite, markup) {
  const symbols = new Map([...sprite.matchAll(/<symbol\b[^>]*\sid="([^"]+)"[\s\S]*?<\/symbol>/g)].map((m) => [m[1], m[0]]));
  const keep = new Set();
  const visit = (text) => {
    for (const m of text.matchAll(/#([\w-]+)/g)) {
      if (symbols.has(m[1]) && !keep.has(m[1])) {
        keep.add(m[1]);
        visit(symbols.get(m[1]));
      }
    }
  };
  visit(markup);
  return sprite.replace(/<symbol\b[^>]*\sid="([^"]+)"[\s\S]*?<\/symbol>/g, (all, sid) => (keep.has(sid) ? all : ""));
}

// OF's dark theme is the class m-mode-dark on <html>: set it before first paint when the
// OF Manager page framing this one is dark (its <html data-theme> is not "light", as in useTheme;
// useOfTheme keeps it in step after). A page opened on its own stays light.
// Follows our theme only: with "Synchronize platform display settings" off (app/lib/ofMirrorTheme.ts) a page flashes
// dark until useOfTheme's load handler; reading that key here needs every committed page regenerated.
const THEME_BOOT = `<script>try{if(parent!==window&&parent.document.documentElement.getAttribute("data-theme")!=="light")document.documentElement.classList.add("m-mode-dark")}catch(e){}</script>`;

const BODY_CLASSES = new Set(["m-black-body", "m-stream-body"]); // the <body> classes a page keeps

// OF's own layout (left nav + content + right column) applies as is; these only patch what the mirror changes.
const OVERRIDES = `<style id="of-mirror-overrides">
/* The "Offer claimed" list's CSS chunk is not in the dump: keep names clear of the avatars. */
.b-viewer-row { min-height: 36px; }
.b-viewer-row__name { position: relative; padding-left: 34px; }
.b-viewer-row__name > .g-avatar.m-absolute { left: 0; top: 50%; margin-top: -12px; }
/* State pages: a link laid over its control, the open menu under that control,
   and a backdrop link behind the page (inside the modal, if one is open). */
.v-select, .b-dropdown-wrapper, .input-text-editor, .v-list-item { position: relative; }
.of-state-link { position: absolute; top: 0; right: 0; bottom: 0; left: 0; z-index: 3; }
.of-state-backdrop { position: fixed; top: 0; right: 0; bottom: 0; left: 0; z-index: 1; }
.modal > .of-state-backdrop { position: absolute; z-index: auto; }
/* !important: OF's own rules for these poppers are scoped (data-v-*) and position them with JS. */
.v-select--is-menu-active, .b-dropdown-wrapper.m-show-dropdown { z-index: 10 !important; }
/* A sticky column is its own stacking context: one holding the open menu goes over the backdrop with it. */
.l-sidebar-column:has(.m-show-dropdown) { z-index: 2; }
.of-state-menu { position: absolute !important; top: 100% !important; left: 0 !important; min-width: 100%; z-index: 50; background: var(--bg-color, #fff); }
.of-state-menu.m-dropdown-list { left: auto !important; right: 0 !important; }
</style>`;

/** data-v-<id> scope id -> the CSS files (relative to STATIC_PREFIX) that style it. */
let scopeIndex;
function cssFor(scope) {
  if (!scopeIndex) {
    scopeIndex = new Map();
    const root = path.join(DUMP, STATIC_PREFIX);
    for (const build of fs.existsSync(root) ? fs.readdirSync(root) : []) {
      const dir = path.join(root, build);
      if (!fs.statSync(dir).isDirectory()) continue;
      for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".css")).sort()) {
        for (const id of new Set(fs.readFileSync(path.join(dir, f), "utf8").match(/(?<=data-v-)[0-9a-f]{8}/g))) {
          scopeIndex.set(id, [...(scopeIndex.get(id) || []), `${build}/${f}`]);
        }
      }
    }
  }
  return scopeIndex.get(scope) || [];
}

/**
 * Live markup can use components whose CSS chunk the dump's copy of the page
 * never loaded (its <head> came from an empty shell). Link the dump's CSS
 * files for any data-v scope the page's own stylesheets do not cover (Statistics: also the scopes of the markup
 * statisticsPage adds, e.g. Engagement › Posts' ChartSummary).
 */
function extraStyles(styles, markup) {
  const linked = new Set([...styles.matchAll(new RegExp(`href="${STATIC_URL}/([^"]+\\.css)"`, "g"))].map((m) => m[1]));
  const covered = new Set([...linked].flatMap((f) => [...scopeIndexOf(f)]));
  const extra = [];
  for (const scope of new Set(markup.match(/(?<=data-v-)[0-9a-f]{8}/g))) {
    if (covered.has(scope)) continue;
    const file = cssFor(scope).find((f) => !linked.has(f));
    if (!file) continue;
    linked.add(file);
    for (const s of scopeIndexOf(file)) covered.add(s);
    assets.add(file);
    extra.push(`<link rel="stylesheet" href="${STATIC_URL}/${file}">`);
  }
  return extra.join("\n");
}
const scopeIndexOf = (file) => new Set(fs.readFileSync(path.join(DUMP, STATIC_PREFIX, file), "utf8").match(/(?<=data-v-)[0-9a-f]{8}/g));

/** OF's header back arrows (dead <button>s in the capture) as links one level up:
 *  modal/nested page -> its nearest built parent, top-level page -> the section root, a section root -> OF Manager home. */
function backButtons({ section, sub }, html) {
  const parts = sub ? sub.split("/") : [];
  let up = section === "home" ? "#" : `${MANAGER}/home`;
  if (sub && sub !== SECTION_INDEX[section]) {
    for (let i = parts.length - 1; i >= 0; i--) {
      const parent = parts.slice(0, i).join("/");
      if (BUILT.has(pageKey(section, parent))) {
        up = hrefOf(section, parent);
        break;
      }
    }
  }
  return html.replace(
    /<button\b([^>]*class="g-page__header__btn[^"]*"[^>]*)>(\s*<svg[^>]*data-icon-name="icon-back"[\s\S]*?<\/svg>\s*)<\/button>/g,
    (_, attrs, inner) => `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${up}" target="_top" aria-label="Back">${inner}</a>`,
  );
}

// Every chat, vault list and collections user-list row (and list name on a user card) opens the one mirrored example page; its link
// gets ?row=<name>|<handle> (what the row shows, scrubbed), and useOfRow (app/lib/ofMirrorRow.ts) shows it there.
const ROW_LINKS = [
  { href: `${MANAGER}/messages/chat`, cls: "b-chats__item__link", name: "g-user-name", handle: "g-user-username" },
  { href: `${MANAGER}/vault/list`, cls: "b-rows-lists__item__text", name: "b-rows-lists__item__name" },
  { href: `${MANAGER}/collections/user-lists/list`, cls: "b-rows-lists__item__text", name: "b-rows-lists__item__name" },
  { href: `${MANAGER}/collections/user-lists/list`, cls: "b-dot-item", name: "b-list-titles__item__text" }, // a user card's list names
];

/** Each row link of ROW_LINKS in `html` with its row's ?row= query. */
function rowLinks(html) {
  const textOf = (inner, cls, re = /\S/) =>
    [...inner.matchAll(/<\w+\b[^>]*\sclass="([^"]*)"[^>]*>([^<]*)</g)].find((m) => hasClass(m[1], cls) && re.test(m[2]))?.[2].trim();
  return html.replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/g, (all, attrs, inner) => {
    const href = attrs.match(/\shref="([^"]*)"/)?.[1];
    const row = ROW_LINKS.find((r) => r.href === href && hasClass(attrs.match(/\sclass="([^"]*)"/)?.[1] || "", r.cls));
    const name = row && textOf(inner, row.name);
    if (!name) return all;
    const handle = row.handle && textOf(inner, row.handle, /^\s*@/)?.slice(1);
    const q = [name, handle].filter(Boolean).map(encodeURIComponent).join("|");
    return `<a${attrs.replace(/\shref="[^"]*"/, ` href="${href}?row=${q}"`)}>${inner}</a>`;
  });
}

/** The first <button> whose text is one of `labels` (case-insensitive) as a link to `href`. */
function linkButton(html, labels, href) {
  const want = labels.map((l) => l.trim().toLowerCase());
  let done = false;
  return html.replace(/<button\b([^>]*)>(\s*)([^<]*?)(\s*)<\/button>/g, (all, attrs, a, text, b) => {
    if (done || !want.includes(text.toLowerCase())) return all;
    done = true;
    return `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${href}" target="_top">${a}${text}${b}</a>`;
  });
}

/**
 * The first <button>/<a> matching `spec` ("aria:<aria-label>", "icon:<data-icon-name>" or
 * "text:<its text>") as a link to `href`; null if there is none.
 */
function linkEl(html, spec, href) {
  const [, kind, want] = spec.match(/^(aria|icon|text):(.+)$/);
  let done = false;
  const out = html.replace(/<(button|a)\b([^>]*)>([\s\S]*?)<\/\1>/g, (all, tag, attrs, inner) => {
    if (done) return all;
    const have =
      kind === "aria"
        ? decode(attrs.match(/\saria-label="([^"]*)"/)?.[1] ?? "")
        : kind === "icon"
          ? inner.match(/data-icon-name="([^"]+)"/)?.[1]
          : inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    if (have?.toLowerCase() !== want.toLowerCase()) return all;
    done = true;
    return `<a${attrs.replace(/\s(type|disabled|role|href|target)="[^"]*"/g, "")} href="${href}" target="_top">${inner}</a>`;
  });
  return done ? out : null;
}

/** Captured modals can be mid fade-in; show them, and make Cancel/Close go back to the page. */
function openModal(portal, back) {
  portal = portal.replace(/class="(modal|modal-backdrop)((?: [^"]*)?)"/g, (all, c, rest) => (/\bshow\b/.test(rest) ? all : `class="${c}${rest} show"`));
  for (const label of ["Cancel", "Close"]) {
    for (let prev; prev !== portal; ) {
      prev = portal;
      portal = linkButton(portal, [label], back);
    }
  }
  return portal;
}

// ---------------------------------------------------------------- states

// A --live3 "<slug>__state-<name>" capture is its page with one dialog, dropdown or popup open;
// the page "<page>/state-<name>". open: the control that opens it, on the page (or on the state
// named in `from`), as "aria:<aria-label>", "icon:<data-icon-name>" or "text:<button text>"
// (a dropdown that is open in the capture is found from its markup: no `open`). close: the
// same on the state page, going back. skip: a capture with no page of its own.
const FOCUS_ONLY = { skip: "the page itself with a control focused" };
const PAGE_STATES = {
  "profile__state-more-menu": {}, // the creator's own profile capture, keyed by route not by username
  // The left nav's drawer open (the avatar and More open the same one): navFor links them, its close and its overlay.
  "home__state-avatar-menu": {},
  "home__state-more-menu": { skip: "the same capture as home__state-avatar-menu" },
  "home__state-feed-tabs-edit": { open: "icon:icon-edit" },
  "my__chats__state-filter-dropdown": {},
  "my__chats__send__state-list-dropdown": {},
  "my__chats__chat__state-composer-focus": FOCUS_ONLY,
  "my__chats__chat__state-header-menu": {},
  "my__chats__chat__state-price": { open: "aria:Message price" },
  "my__chats__chat__state-schedule": { open: "aria:Scheduled messages" },
  "my__chats__chat__state-vault": { open: "aria:Add media from vault" },
  "my__queue__state-list-view": { open: "icon:icon-agenda", close: "icon:icon-month" },
  "my__queue__state-tab-messages": { open: "text:Messages", close: "text:Messages" },
  "my__queue__state-tab-streams": { open: "text:Streams", close: "text:Streams", from: "tab-messages" },
  "my__statistics__overview__state-period-dropdown": { skip: "the period menu: Statistics reads the Relay's default 30 days only (statisticsPage)" },
  "my__stats__earnings__state-date-range": { skip: "the date range picker: Earning Statistics reads all time only (statementsPage)" },
  "my__vault__state-add-list": { open: "aria:Create new category" },
  "my__vault__state-lists-sort-dropdown": {},
  "my__vault__state-sort-dropdown": {},
  "posts__create__state-focus": FOCUS_ONLY,
  "posts__create__state-expiration": { open: "aria:Expiration period" },
  "posts__create__state-format-text": { open: "aria:Format Text", close: "aria:Format Text" },
  "posts__create__state-labels": { open: "text:Add labels" },
  "posts__create__state-poll": { open: "aria:Add poll", close: "aria:Delete" },
  "posts__create__state-quiz": { open: "aria:Add quiz", close: "aria:Delete" },
  "posts__create__state-schedule": { open: "aria:Schedule post" },
  "posts__create__state-tag-people": { open: "aria:Tag other creators" },
  "posts__create__state-target": { open: "aria:Your target" },
  "posts__create__state-vault": { open: "aria:Add media from vault" },
};

// Controls a state capture can have open: the root element's class, and the
// class it carries while open.
const CONTROLS = [
  { cls: "v-select", open: "v-select--is-menu-active" }, // select and autocomplete
  { cls: "b-dropdown-wrapper", open: "m-show-dropdown" }, // sort dropdown
  { cls: "input-text-editor", open: "m-focused" }, // bio editor
];
const hasClass = (classes, c) => classes.split(/\s+/).includes(c);
const roots = (html, cls) => [...html.matchAll(/<div\b[^>]*?\sclass="([^"]*)"[^>]*>/g)].filter((m) => hasClass(m[1], cls));
const mainOf = (app) => {
  const at = app.search(/<main id="content"/);
  return at >= 0 ? element(app, at, "main") || "" : "";
};

/** Which control is open in a state capture: { cls, part: "body" | "modal", index among that class in the part }. */
function findControl(body, modal) {
  for (const [part, html] of [["body", body], ["modal", modal]]) {
    for (const { cls, open } of CONTROLS) {
      const index = roots(html, cls).findIndex((m) => hasClass(m[1], open));
      if (index >= 0) return { cls, part, index };
    }
  }
  return null;
}

const anchor = (cls, href, label) => `<a class="${cls}" href="${href}" target="_top" aria-label="${label}"></a>`;

/** A link laid over the index-th `cls` control of `html`. */
function overControl(html, cls, index, href) {
  const m = roots(html, cls)[index];
  if (!m) return html;
  const at = m.index + m[0].length;
  return html.slice(0, at) + anchor("of-state-link", href, "Toggle") + html.slice(at);
}

/**
 * The state's page: the open menu (a body-level popper in the capture, hidden
 * by a layout glitch) moved under its control and made visible; every option,
 * the control and the backdrop link to `back`.
 */
function openState(body, modal, { cls, part, index, back }) {
  let menu = "";
  const menuRe = /<div\b[^>]*\sclass="[^"]*\bv-menu__content\b[^"]*"[^>]*>/;
  for (let m; (m = menuRe.exec(modal)); ) {
    const node = element(modal, m.index, "div");
    if (hasClass(m[0].match(/\sclass="([^"]*)"/)[1], "menuable__content__active")) menu = node;
    modal = modal.slice(0, m.index) + modal.slice(m.index + node.length);
  }
  menu = menu
    .replace(/^<div\b([^>]*)>/, (_, attrs) =>
      `<div${attrs
        .replace(/\sstyle="([^"]*)"/, (_, st) => ` style="${st.replace(/(?:display|top|left|transform-origin|z-index)\s*:[^;]*;?\s*|min-width\s*:\s*0px;?\s*/g, "").trim()}"`)
        .replace(/\sclass="/, ' class="of-state-menu ')}>`,
    )
    // Buttons cannot hold the link; options become plain blocks with one on top.
    .replace(/<(\/?)button\b/g, "<$1div")
    .replace(/<div\b[^>]*\sclass="[^"]*\bv-list-item\b[^"]*"[^>]*>/g, (tag) => tag + anchor("of-state-link", back, "Select"));
  let html = part === "body" ? body : modal;
  html = overControl(html, cls, index, back);
  const m = roots(html, cls)[index];
  if (m) {
    const end = m.index + element(html, m.index, "div").length - "</div>".length;
    html = html.slice(0, end) + menu + html.slice(end);
  }
  if (part === "body") body = html;
  else modal = html;
  const backdrop = anchor("of-state-backdrop", back, "Close");
  const dialog = modal.match(/<div\b[^>]*\sclass="modal[\s"][^>]*>/);
  if (dialog) modal = modal.slice(0, dialog.index + dialog[0].length) + backdrop + modal.slice(dialog.index + dialog[0].length);
  else body = backdrop + body;
  return { body, modal };
}

/** A state page whose dialog or popup is not a menu: a backdrop link, a date picker's overlay and Cancel/Close buttons go back to `back`. */
function closePopup(body, modal, back) {
  const close = (h) => h.replace(/<div class="vdatetime-overlay"><\/div>/g, `<a class="vdatetime-overlay" href="${back}" target="_top" aria-label="Close"></a>`);
  const dialog = modal.match(/<div\b[^>]*\sclass="modal[\s"][^>]*>/);
  if (dialog) modal = modal.slice(0, dialog.index + dialog[0].length) + anchor("of-state-backdrop", back, "Close") + modal.slice(dialog.index + dialog[0].length);
  else body = anchor("of-state-backdrop", back, "Close") + body;
  return { body: openModal(close(body), back), modal: close(modal) };
}

// ---------------------------------------------------------------- home

// Home shows no captured example: what has a Relay source is drawn at runtime (app/lib/ofMirrorData.ts, ofMirrorFeeds.ts),
// the rest goes. Its composer posts in place, as OF's (app/lib/ofMirrorPost.ts): "Add media" uploads, and its vault,
// schedule, tag, poll, quiz, expiration, target and format tools open over Home itself (HOME_DIALOGS: Home's own State
// pages, built from New post's captures of the same dialogs and panels). Record video/voice (no source anywhere) are
// disabled with a tooltip (no Read-only note crowding the toolbar).
const NOT_YET = ["Record video", "Record voice"];
const NOT_YET_TITLE = "Not available in Inflowwww yet";
/** New post's dialog captures (posts__create__state-<name>) that are also Home's State pages, home/state-<name>. */
const HOME_DIALOGS = ["vault", "schedule", "tag-people", "poll", "quiz", "expiration", "target", "format-text"];

/** The first element with class `cls` in `html` removed (`keep`: replaced by keep(element)). */
function dropEl(html, cls, keep = () => "") {
  const m = roots(html, cls)[0];
  if (!m) return html;
  const el = element(html, m.index, "div");
  return html.slice(0, m.index) + keep(el) + html.slice(m.index + el.length);
}

/**
 * The story strip: the own "Add to story" tile's letter is the model's (ofMirrorIdentity puts its picture there, as OF
 * shows it), not a fan's; on Home fans' story tiles (OF's at-attr="story_item") go and the others are laid out again
 * from the left.
 */
function storyStrip(html, section) {
  html = html.replace(/(<button\b[^>]*\sclass="[^"]*\bm-story-item-own\b(?:(?!<\/button>)[\s\S])*?class="g-avatar__placeholder m-text-avatar) of-fan("[^>]*>)\s*F\s*</, "$1$2 Y <");
  if (section !== "home") return html;
  return dropEl(html, "stories-list", (strip) => {
    const tiles = [...strip.matchAll(/<div class="vue-recycle-scroller__item-view" style="transform: translateX\((\d+)px\);">/g)].map((m) => ({
      at: m.index,
      x: +m[1],
      html: element(strip, m.index, "div"),
    }));
    if (!tiles.length) return strip;
    const step = tiles.length > 1 ? tiles[1].x - tiles[0].x : 136;
    const keep = tiles.filter((t) => !/\sat-attr="story_item"/.test(t.html));
    const views = keep.map((t, i) => t.html.replace(/translateX\(\d+px\)/, `translateX(${i * step}px)`)).join("");
    const last = tiles.at(-1);
    return (strip.slice(0, tiles[0].at) + views + strip.slice(last.at + last.html.length)).replace(
      /(class="vue-recycle-scroller__item-wrapper" style="min-width: )\d+px/,
      `$1${keep.length * step}px`,
    );
  });
}

/** The <button>s aria-labelled `labels` (default: Record video and Record voice, which have no source): disabled, with a tooltip. */
const notYet = (html, labels = NOT_YET) =>
  labels.reduce((h, label) => h.replace(new RegExp(`<button\\b((?:(?!disabled=)[^>])*\\saria-label="${label}")`, "g"), `<button disabled="disabled" title="${NOT_YET_TITLE}"$1`), html);

/** Every enabled <button> for which `pick(attrs, text)` holds (`text`: its visible words): disabled, with the tooltip. */
const notYetWhere = (html, pick) =>
  html.replace(/<button\b((?:(?!disabled=)[^>])*)>((?:(?!<\/?button\b)[\s\S])*)<\/button>/g, (all, attrs, inner) =>
    pick(attrs, inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()) ? `<button disabled="disabled" title="${NOT_YET_TITLE}"${attrs}>${inner}</button>` : all,
  );

/** The story strip's "create" tile whose text is `text` (a <button>): `swap(attrs, inner)` gives its replacement. */
const storyTile = (html, text, swap) =>
  html.replace(/<button\b([^>]*\sclass="b-story-item m-create"[^>]*)>((?:(?!<\/button>)[\s\S])*?)<\/button>/g, (all, attrs, inner) =>
    inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() === text ? swap(attrs, inner) : all,
  );
const tileLink = (href) => (attrs, inner) => `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${href}" target="_top">${inner}</a>`;
const tileNotYet = (attrs, inner) => `<button disabled="disabled" title="${NOT_YET_TITLE}"${attrs}>${inner}</button>`;

/**
 * The right column Home, New post and the stream schedule form share: no example stays. The price line (no bundle count)
 * is hidden until ofMirrorIdentity shows the Creator's own price, the promotion cards become one hidden template
 * (ofMirrorFeeds' applyPromotions shows the Creator's live promotions in its copies), the ad banner goes, and the
 * Scheduled events widget's "+" (`widget`): "schedule" opens the section's own schedule dialog (`<section>/state-schedule`),
 * "queue" is OF's own "Add to queue" (data-oi-wired: ofMirrorQueue's bindQueue opens the Queue's "+" modal, as OF's
 * widget opens NEW_SCHEDULED_EVENT), "off" is disabled with the tooltip; applyEvents lists the queue's next items there.
 */
function feedAside(html, section, widget = "schedule") {
  html = html.replace(
    /<div class="b-menu-list__subtext">(<span class="b-amount-price m-num">[^<]*<\/span> per month)(?:, \d+ subscription bundles?)?<\/div>/,
    '<div class="b-menu-list__subtext" data-oi-price="" style="display:none">$1</div>',
  );
  html = dropEl(html, "b-offer-wrapper", (el) => {
    const open = el.match(/^<div\b[^>]*>/)[0].replace(/>$/, ' style="display:none">');
    const card = roots(el, "b-offer-join")[0];
    const tpl = card ? element(el, card.index, "div").replace(/^<div\b([^>]*)>/, '<div$1 data-oi-template="promotion" style="display:none">') : "";
    return `${open}${tpl}</div>`;
  });
  html = dropEl(html, "banner_place");
  return html.replace(/<button\b([^>]*\sat-attr="add_event_widget"[^>]*)>([\s\S]*?)<\/button>/, (_, attrs, inner) =>
    widget === "schedule"
      ? `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${MANAGER}/${section}/state-schedule" target="_top" aria-label="Schedule post">${inner}</a>`
      : widget === "queue"
        ? `<button type="button"${attrs} aria-label="Add to queue" data-oi-wired="">${inner}</button>`
        : `<button disabled="disabled" title="${NOT_YET_TITLE}" style="opacity:.5;cursor:default"${attrs}>${inner}</button>`,
  );
}

// A chat's vault dialog (the composers' markup): the controls its binder does not work (OF's sort menus, the folder
// search; the rest is not in that dialog). New post's and Home's composer works all of them (ofMirrorPost).
const NEW_POST_NOT_YET = (attrs, text) =>
  /\saria-label="(?:Sort|More|Search|Bold|Italic|Text Color|Clear Formatting)"/.test(attrs) ||
  /\sclass="[^"]*\bm-drag-btn\b/.test(attrs) ||
  (/\sclass="b-tabs__nav__link\b/.test(attrs) && text === "Release form") ||
  text === "Invite new user" ||
  // the tag dialog's search icon (its header's first button, no label)
  (/\sclass="g-btn m-icon m-icon-only m-gray m-sm-size m-with-round-hover ml-0"/.test(attrs) && !text);

/**
 * The composer's dialogs (New post's, Home's copies of them and a chat's and New message's vault dialog): their NEW_POST_NOT_YET
 * controls are disabled with the tooltip (New post's and Home's all work), and the vault dialog's folder rows (OF's
 * role=button rows) become links, as on the Vault page: "All media" to
 * the dialog itself, the others (examples ofMirrorData replaces with the Creator's folders, each the dialog with its
 * ?list=) to the one mirrored folder page.
 */
function composerDialog(modal, section) {
  if (section.startsWith("messages/")) modal = notYetWhere(modal, NEW_POST_NOT_YET);
  const vault = `${MANAGER}/${section}/state-vault`;
  const rowRe = /<div\b([^>]*\sclass="b-rows-lists__item__text\b[^"]*"[^>]*\srole="button"[^>]*)>/g;
  let out = "";
  let at = 0;
  for (let m; (m = rowRe.exec(modal)); ) {
    const el = element(modal, m.index, "div");
    const all = /<div at-attr="lists_item" class="b-rows-lists__item__name[^"]*">\s*All media\s*</.test(el);
    const attrs = m[1].replace(/\s(tabindex|role)="[^"]*"/g, "");
    out += modal.slice(at, m.index) + `<a${attrs} href="${all ? vault : `${MANAGER}/vault/list`}" target="_top">` + el.slice(m[0].length, -"</div>".length) + "</a>";
    at = m.index + el.length;
    rowRe.lastIndex = at;
  }
  return out + modal.slice(at);
}

/**
 * OF's price button (MakeFeedPost's `price_btn`, after Fundraising target and before Tag other creators), in the chat
 * composer's captured markup: the post capture has none (OF shows it only on a free page). Its POST PRICE dialog is
 * new-post/state-price (postPriceState); ofMirrorPost hides it where OF would.
 */
const PRICE_BTN =
  '<button data-v-377a022e="" type="button" at-attr="price_btn" class="g-btn m-with-round-hover m-icon m-icon-only m-gray m-sm-size has-tooltip" data-original-title="null" aria-label="Post price"><svg data-v-377a022e="" class="g-icon" data-icon-name="icon-price" aria-hidden="true"><use href="#icon-price" xlink:href="#icon-price"></use></svg></button>';

/**
 * New post and its State pages: no example stays in the right column (feedAside, its "+" opening New post's schedule
 * dialog). The story strip's "Go live" opens Go live, "Send message" the new message page, "Start profile promotion" the
 * promotion campaign dialog and "Create new trial link" the free trial link dialog over New post itself (OFFER_STATES),
 * as OF's PromoteProfile and CreateTrialLinkBtn open their modals over the page. Every tool works (ofMirrorPost: format panel, record popup, sort and search menus, drag handles); OF's footer
 * links go. The price button (PRICE_BTN) follows Fundraising target. The labels row's icon opens ADD LABELS like its text, and the format panel's
 * close returns to the composer.
 */
function newPostPage(html) {
  html = feedAside(html, "new-post", "queue");
  html = storyTile(html, "Go live", tileLink(`${MANAGER}/streaming`));
  html = storyTile(html, "Send message", tileLink(`${MANAGER}/messages/send`));
  html = storyTile(html, "Start profile promotion", tileLink(`${MANAGER}/new-post/state-promotion`));
  html = storyTile(html, "Create new trial link", tileLink(`${MANAGER}/new-post/state-trial-link`));
  html = html.replace(/(<button\b[^>]*\saria-label="Your target"[^>]*>[\s\S]*?<\/button>)/, `$1${PRICE_BTN}`);
  if (!html.includes('at-attr="price_btn"')) fail('new-post: no "Your target" button to put the price button after');
  // OF's footer links (Privacy, Cookie Notice, Terms of Service): not on New post.
  html = dropEl(html, "l-footer");
  html = html.replace(
    /<button\b([^>]*\sat-attr="add_to_list"[^>]*)>([\s\S]*?)<\/button>/,
    (_, attrs, inner) => `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${MANAGER}/new-post/state-labels" target="_top" aria-label="Add labels">${inner}</a>`,
  );
  html = html.replace(
    /<button\b([^>]*\saria-label="Close Formatting Panel"[^>]*)>([\s\S]*?)<\/button>/,
    (_, attrs, inner) => `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${MANAGER}/new-post" target="_top">${inner}</a>`,
  );
  return html;
}

/**
 * New post's POST PRICE dialog (new-post/state-price): OF opens the same ModalPostPrice as a chat's price (MakeFeedPost
 * openModalPostPrice), titled for a post, and no capture holds it over the post composer. So it is the chat's captured
 * dialog (messages chat/state-price) over New post's own page, opened by the price button (PRICE_BTN). null: either
 * capture is missing (the price button then links nowhere).
 */
function postPriceState(pageStates, base) {
  const chat = pageStates.find((p) => p.section === "messages" && p.state === "price");
  const at = base?.raw.search(/<div id="app"/) ?? -1;
  if (!chat || at < 0) return null;
  // The dialog alone (the chat page's menus stay behind). OF's title for a post's price (message.post_set_price_title):
  // its English text is not in the capture, so it is assumed.
  const dialog = priceDialog(chat.portal);
  const portal = dialog.replace(/(<h4 class="modal-title">)\s*MESSAGE PRICE\s*</, "$1 POST PRICE <");
  if (portal === dialog) fail("the chat's price dialog capture has no ModalPostPrice titled MESSAGE PRICE");
  return { ...chat, slug: "posts__create__state-price", rel: base.rel, raw: base.raw, state: "price", section: "new-post", baseSub: "", sub: "state-price", base, app: element(base.raw, at, "div"), portal, ctl: null, open: "aria:Post price", close: undefined, from: undefined, label: "Price", drawer: false };
}

/** The price dialog alone (OF's ModalPostPrice) out of a chat's price capture, whose chat page's menus stay behind; "" if none. */
function priceDialog(portal) {
  const outer = /<div\b[^>]*\sid="ModalPostPrice___BV_modal_outer_"[^>]*>/.exec(portal);
  return outer ? element(portal, outer.index, "div") : "";
}

/**
 * New message's price, vault and tag dialogs (messages/send/state-<name>): OF opens the same dialogs over New message as
 * over a chat (the same composer, MakeFeedPost), and no capture holds them there. So each is the chat's (its price and
 * vault captures, and New post's tag dialog the chat borrows) over New message's own page, opened by the same button.
 */
function sendStates(pageStates, base) {
  const at = base?.raw.search(/<div id="app"/) ?? -1;
  if (at < 0) return [];
  const app = element(base.raw, at, "div");
  const chat = pageStates.filter((p) => p.section === "messages" && p.baseSub === "chat" && SEND_TOOLS.includes(p.state));
  if (chat.length !== SEND_TOOLS.length) fail(`New message's dialogs: the chat has ${chat.map((p) => p.state).join(", ") || "none"} of ${SEND_TOOLS.join(", ")}`);
  return chat.map((p) => {
    const portal = p.state === "price" ? priceDialog(p.portal) : p.portal;
    if (!portal) fail("the chat's price dialog capture has no ModalPostPrice");
    return { ...p, slug: `my__chats__send__state-${p.state}`, rel: base.rel, raw: base.raw, baseSub: "send", sub: `send/state-${p.state}`, base, app, portal, from: undefined };
  });
}

/**
 * New post's offer dialogs (new-post/state-<name>): OF's PromoteProfile and CreateTrialLinkBtn tiles open ModalPromotion
 * and ModalTrial over the page they are on (showModal; PromoteProfile goes to Settings > Subscription #promotion only
 * when an "all" promotion is already claimable, which ofMirrorOffers handles). No capture holds them over New post, so
 * each is the settings dialog's capture (its settings sub here) over New post's own page, worked like that settings
 * dialog (settingsPart's OFFER_MODALS, ofMirrorOffers, ofMirrorWrites' SUBMITS).
 */
const OFFER_STATES = {
  "state-promotion": { modal: "subscription/promotion-campaign/modal-1", label: "Promotion campaign" },
  "state-trial-link": { modal: "subscription/trial-links/modal-1", label: "Free trial link" },
};
function offerStates(modals, base) {
  const at = base?.raw.search(/<div id="app"/) ?? -1;
  if (at < 0) return [];
  const app = element(base.raw, at, "div");
  return Object.entries(OFFER_STATES).map(([sub, { modal, label }]) => {
    const m = modals.find((x) => x.slug === modal);
    if (!m?.portal) fail(`New post's ${label} dialog: no settings capture ${modal} to take it from`);
    return { slug: `posts__create__${sub}`, rel: base.rel, raw: base.raw, state: sub.slice("state-".length), section: "new-post", baseSub: "", sub, base, app, portal: m.portal, ctl: null, open: undefined, close: undefined, from: undefined, label, drawer: false };
  });
}

/**
 * Home's "Pin to home" dialog (the feed tabs' pencil): the Relay has no route for pinned feed tabs, so the captured
 * example lists go, an empty line says so, and its Sort is disabled with the tooltip; Close goes back to Home.
 */
function pinToHome(modal) {
  modal = modal.replace(/<label\b[^>]*\sclass="b-rows-lists__item\b[\s\S]*?<\/label>/g, "");
  modal = modal.replace(/(<div\b[^>]*\sclass="b-rows-lists\b[^"]*"[^>]*>)/, `$1${settingsEmpty("Pinning lists to Home is not available in Inflowwww yet")}`);
  return notYetWhere(modal, (attrs) => /\saria-label="Sort"/.test(attrs));
}

/**
 * Home and its State pages: no example stays. The expired-subscription alerts (no source) go; the feed's example posts
 * and their infinite-loading footer give way to OF's empty message, which ofMirrorFeeds' applyHome replaces with the
 * Creator's feed (or a loading or error line); the right column's price line (no bundle count) is hidden until
 * ofMirrorIdentity shows the Creator's own price, its promotion cards become one hidden template (applyPromotions shows
 * the Creator's live promotions in its copies) and the ad banner goes. The composer gets OF's Post button after "Go live"
 * (ofMirrorPost posts in place); its tools open Home's own State pages (main's HOME_DIALOGS links; the format panel's
 * close returns to Home), and the story strip's "Start profile promotion" is disabled with a tooltip (its campaign form
 * has no Known body). The Scheduled events widget's "+" opens Home's schedule dialog; applyEvents
 * lists the queue's next items there. The header's More menu (not captured) is disabled with the tooltip too.
 */
function homePage(html) {
  html = dropEl(html, "b-feed-alerts");
  html = dropEl(html, "user_posts", (el) => {
    const open = el.match(/^<div\b[^>]*>/)[0];
    const scope = open.match(/\sdata-v-[0-9a-f]+=""/)?.[0] ?? "";
    return `${open}<div${scope} class="empty-message"><span>No posts yet</span></div></div>`;
  });
  html = feedAside(html, "home");
  html = html.replace(
    /<button\b([^>]*\saria-label="Close Formatting Panel"[^>]*)>([\s\S]*?)<\/button>/,
    (_, attrs, inner) => `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${MANAGER}/home" target="_top">${inner}</a>`,
  );
  // Post goes after "Go live", on a second row at the right when the toolbar leaves no room (the tools wrap on a phone).
  html = html.replace(/(<div\b[^>]*\sclass="b-make-post__actions")>/, '$1 style="flex-wrap:wrap">');
  html = html.replace(/(<div\b[^>]*\sclass="b-make-post__actions__btns")>/, '$1 style="flex-wrap:wrap;min-width:0">');
  html = html.replace(
    /(<a\b[^>]*\sclass="b-make-post__streaming-link\b[\s\S]*?<\/a>)/,
    `$1<button type="button" disabled="disabled" at-attr="submit_post" class="g-btn m-rounded m-sm-width m-reset-width m-colored" style="margin-left:auto"> Post </button>`,
  );
  // The header's More menu (no captured menu): disabled with a tooltip.
  html = html.replace(/(\sclass="g-page__header\b[\s\S]*?)<button\b((?:(?!disabled=)[^>])*\saria-label="More")/, `$1<button disabled="disabled" title="${NOT_YET_TITLE}"$2`);
  html = html.replace(
    /<button\b((?:(?!disabled=)[^>])*\sclass="b-story-item m-create"[^>]*)>(?=(?:(?!<\/button>)[\s\S])*?Start profile promotion)/,
    `<button disabled="disabled" title="${NOT_YET_TITLE}"$1>`,
  );
  return html;
}

// ---------------------------------------------------------------- go live

/**
 * Go live and the stream schedule form. Inflowwww cannot stream, so Go live is OF's idle page with every control
 * quietly disabled with the tooltip: OF's own "Start Live Video" (captured hidden, waiting for the camera) shows,
 * disabled; the option rows, switches and description are disabled; and the camera's endless "loading." says it is not
 * available instead. The schedule form (its SCHEDULE writes through, app/lib/ofMirrorWrites.ts) gets the shared right
 * column (feedAside: no example price, promotion or banner; its "+" disabled, as this section has no schedule dialog)
 * and its search, cover picker and the editor's text-format button (no source) are disabled with the tooltip. The
 * dashboard has nothing to drop (its past streams are drawn at runtime; its "View stats" is disabled there).
 */
function streamingPage(html, sub) {
  const off = `title="${NOT_YET_TITLE}"`;
  if (sub === "") {
    html = html.replace(
      /(<span\b[^>]*\sclass="b-text-progress__value">)loading(<\/span>)<span\b[^>]*\sclass="b-text-progress__dots">[^<]*<\/span>/,
      `$1${NOT_YET_TITLE}$2`,
    );
    html = html.replace(/<button\b([^>]*\sclass="[^"]*\bb-streaming__btn-start\b[^"]*")\sstyle="display: none;">/, `<button ${off}$1>`);
    html = html.replace(/<div\b([^>]*)\sclass="b-streaming-details__row([^"]*)"/g, (_, pre, cls) =>
      `<div${pre} class="b-streaming-details__row${cls.replace(/\s*\bg-pointer-cursor\b/, "")}" ${off} aria-disabled="true" style="opacity:.5;cursor:default"`,
    );
    html = html.replace(/<input\b((?:(?!disabled=)[^>])*\stype="checkbox"[^>]*)>/g, `<input disabled="disabled"$1>`);
    html = html.replace(/<textarea\b((?:(?!disabled=)[^>])*)>/g, `<textarea disabled="disabled"$1>`);
    return html;
  }
  if (sub !== "dashboard/create") return html;
  html = feedAside(html, "streaming", "queue");
  html = html.replace(/<input\b((?:(?!disabled=)[^>])*\sname="feed-search-input"[^>]*)>/, `<input disabled="disabled" ${off}$1>`);
  html = html.replace(/(<button\b[^>]*\saria-label="Search")/, `$1 ${off}`);
  return notYetWhere(
    html,
    (attrs, text) => text === "Add cover" || (/\sclass="g-btn m-with-round-hover m-icon m-icon-only m-gray m-sm-size"/.test(attrs) && !text),
  );
}

// ---------------------------------------------------------------- notifications

/**
 * Every notifications tab: no example stays. Each tab opens as OF's own empty tab (its `m-empty-page` layout and "No
 * notifications currently!"); ofMirrorFeeds' applyNotifications lists the Creator's notifications of the tab's type in
 * copies of the one row kept, hidden, as the template (the plain row the runtime picks: no list link), and
 * applyNotificationCounts puts the real tab counts back (the captured ones go). The row's "Add to favorites and other
 * lists", the header's "Search users" (the Relay has no `related_user` filter) and the tab bar's rearrange button (no
 * tabs-order write) are disabled with the tooltip; the gear stays OF's link to its notification settings. The right
 * column is the shared one (feedAside: no example price, promotion or banner; its "+" disabled, as this section has
 * no schedule dialog), and its search, with no source, is disabled too.
 */
function notificationsPage(html) {
  const off = `title="${NOT_YET_TITLE}"`;
  html = html.replace(/(\sclass="b-notifications l-wrapper__content)((?:(?!\bm-empty-page\b)[^"])*)"/, "$1$2 m-empty-page\"");
  html = dropEl(html, "vue-recycle-scroller__item-wrapper", (wrapper) => {
    const open = wrapper.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"');
    const views = [...wrapper.matchAll(/<div class="vue-recycle-scroller__item-view"/g)].map((m) => element(wrapper, m.index, "div"));
    const plain = (v) => {
      const lists = roots(v, "b-list-titles")[0];
      return !lists || !/<a\b/.test(element(v, lists.index, "div"));
    };
    const tpl = views.find((v) => v.includes("b-notifications__list__item") && plain(v));
    const kept = tpl ? tpl.replace(/^<div class="vue-recycle-scroller__item-view" style="[^"]*"/, '<div class="vue-recycle-scroller__item-view" style="display:none"') : "";
    return `${open}${kept}</div>`;
  });
  // OF's "no results" prompt, which the captured non-empty tabs left blank.
  html = html.replace(
    /(<div (data-v-[0-9a-f]+="") class="infinite-status-prompt") style="(?:display: none;)?"><div (data-v-[0-9a-f]+="") \2><\/div><\/div>/,
    '$1 style=""><div $3 class="empty-message" $2><span>No notifications currently!</span></div></div>',
  );
  html = dropEl(html, "b-tabs__nav", (bar) =>
    bar
      .replace(/<span class="b-tabs__nav__count">[^<]*<\/span>/g, "")
      .replace(/<button\b((?:(?!disabled=)[^>])*\sclass="b-tabs__nav__link\b[^>]*)>/, `<button disabled="disabled" ${off}$1>`),
  );
  html = html.replace(/<button\b((?:(?!disabled=)[^>])*\saria-label="Search users")/, `<button disabled="disabled" ${off}$1`);
  html = html.replace(/<button\b((?:(?!disabled=)[^>])*\sat-attr="add_to_list")/g, `<button disabled="disabled" ${off}$1`);
  html = feedAside(html, "notifications", "off");
  return html.replace(/<input\b((?:(?!disabled=)[^>])*\sname="feed-search-input"[^>]*)>/, `<input disabled="disabled" ${off}$1>`);
}

// ---------------------------------------------------------------- messages

// The Messages pages' controls with no Relay route or no Known body: the chat header's name edit, Lists and Add notes,
// the message and list "More" menus, the composer's tip (OF's is a card payment, ofMirrorComposer shows it only where OF
// does), and, off a composer (a chat's pinned page, New message's list pages), the GIF, video, voice, creator-tag and
// format tools; a chat's and New message's own are ofMirrorComposer's. (The chat list's tabs, folders, sort menu, search and row "x" are ofMirrorChats'.)
const COMPOSER_TOOLS = /\saria-label="(?:Add GIF|Record video|Record voice|Tag other creators|Format Text)"/;
const MESSAGES_NOT_YET = (sub) => (attrs) =>
  (/\saria-label="(?:More|Edit|Add GIF|Record video|Record voice|Tag other creators|Format Text)"/.test(attrs) && !/\sdata-oi-(?:tool|msg-menu|pinned-menu)=/.test(attrs) && !(hasComposer(sub) && COMPOSER_TOOLS.test(attrs))) ||
  /\sat-attr="send_tip"/.test(attrs) ||
  (/\sat-attr="release_forms_btn"/.test(attrs) && !hasComposer(sub)) ||
  /\sclass="[^"]*\bcustom-datepicker-button-save-later\b/.test(attrs);
/** A chat's page with its composer working (the chat and its dialogs' pages; not its pinned page or gallery). */
const isChatComposer = (sub) => sub === "chat" || sub.startsWith("chat/state-");
/** New message's dialogs over itself (sendStates), as a chat's. */
const SEND_TOOLS = ["price", "vault", "tag-people"];
/** New message with its composer working: the page and its dialogs' pages (not its list pages or list menu). */
const isSendComposer = (sub) => sub === "send" || SEND_TOOLS.some((t) => sub === `send/state-${t}`);
/** A page whose composer's own tools work (ofMirrorComposer): a chat's or New message's. */
const hasComposer = (sub) => isChatComposer(sub) || isSendComposer(sub);
/** New post's Format text panel (OF's TextEditorToolbar), from its capture: a chat's composer holds it hidden. */
let FORMAT_TOOLBAR = "";
/**
 * `app`'s Format text panel, hidden, its close a button (ofMirrorComposer opens and closes it in place). Hidden it drops
 * `b-form-editor`: OF only renders the panel while open, and its `.b-create-post-form:has(.b-form-editor)` rule takes
 * the panel's 56px off the composer's max-height, which a hidden panel's class would do too (hiding the text box).
 */
function formatToolbar(app) {
  const m = roots(app, "js-text-editor-toolbar")[0];
  if (!m) return "";
  const el = element(app, m.index, "div")
    .replace(/^<div\b/, '<div data-oi-format-panel="" style="display:none !important"')
    .replace(/^(<div\b[^>]*\sclass=")([^"]*)"/, (_, open, cls) => `${open}${cls.split(/\s+/).filter((c) => c && c !== "b-form-editor").join(" ")}"`);
  return el.replace(/<a\b([^>]*\saria-label="Close Formatting Panel"[^>]*)>([\s\S]*?)<\/a>/, (_, attrs, inner) => `<button type="button"${attrs.replace(/\s(?:href|target)="[^"]*"/g, "")}>${inner}</button>`);
}
/** A chat header's ⋮ menu items by their text: ofMirrorChatTools (and ofMirrorChat's Hide and Mute) read data-oi-menu. */
const CHAT_MENU = { "Copy link to profile": "copy", "Rename user": "rename", "Add to / remove from lists": "lists", "Give user a discount": "discount", "View user's comments": "comments", "Hide chat": "hide", "Mute notifications": "mute", "Unmute notifications": "mute", Restrict: "restrict", Block: "block", Report: "report" };
/**
 * A chat header's tools (ofMirrorChatTools reads data-oi-tool): the name's pencil, the lists star and the notes icon;
 * on the menu page, each menu item by its text.
 */
function chatHeaderTools(html, sub) {
  html = html.replace(/<button\b([^>]*\sat-attr="name_edit"[^>]*)>/g, '<button data-oi-tool="rename"$1>');
  html = html.replace(/<button\b([^>]*\sclass="[^"]*\bb-chat__add-to-favorites__btn\b[^"]*"[^>]*\saria-label="Lists"[^>]*)>/g, '<button data-oi-tool="lists"$1>');
  html = html.replace(/<button\b([^>]*\saria-label="Add notes"[^>]*)>/g, '<button data-oi-tool="notes"$1>');
  if (sub !== "chat/state-header-menu") return html;
  return html.replace(/<div\b([^>]*\srole="menuitem"[^>]*)>/g, (open, attrs, at) => {
    if (!/\sclass="[^"]*\bv-list-item\b/.test(attrs)) return open;
    const text = element(html, at, "div").replace(/<span\b[^>]*\bg-icon-info\b[\s\S]*?<\/span>/, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return Object.hasOwn(CHAT_MENU, text) ? `<div data-oi-menu="${CHAT_MENU[text]}"${attrs}>` : open;
  });
}

/** The chat list's tabs by their text: ofMirrorChats reads data-oi-tab (the icon-only one is the folders pencil). */
const CHAT_TABS = { All: "all", Pinned: "pinned", Priority: "priority", Unread: "unread", "With Tips": "who_tipped", "": "folders" };
/** The sort dropdown's radios (their label's `for`) and its other items: ofMirrorChats reads data-oi-chats. */
const CHAT_SORT = { chats_filter_input_all: "filter:", chats_filter_input_priority: "filter:priority", chats_filter_input_unread: "filter:unread", chats_filter_input_unread_tips: "filter:unread_tips", chats_order_input_newest: "order:recent", chats_order_input_oldest: "order:old" };

/**
 * Messages' folders dialog (the tab bar's pencil, messages/state-folders): OF's "Pinned lists" dialog is the same
 * component as Home's "Pin to home" (ModalPinCollectionsFilters with isChat; its title message.pinned_lists, whose English
 * text is not in the capture: assumed), so Home's capture is put over the chat list. Its rows are ofMirrorChats'.
 */
function chatFoldersState(pageStates, base) {
  const home = pageStates.find((p) => p.section === "home" && p.state === "feed-tabs-edit");
  const at = base?.raw.search(/<div id="app"/) ?? -1;
  if (!home || at < 0) return null;
  const portal = home.portal.replace(/(<h4\b[^>]*\sclass="modal-title"[^>]*>)\s*Pin to home\s*</, "$1 Pinned lists <");
  if (portal === home.portal) fail("Home's feed tabs dialog capture has no title \"Pin to home\"");
  return { ...home, slug: "my__chats__state-folders", rel: base.rel, raw: base.raw, state: "folders", section: "messages", baseSub: "", sub: "state-folders", base, app: element(base.raw, at, "div"), portal, ctl: null, open: "icon:icon-edit", close: undefined, from: undefined, label: "Folders", drawer: false };
}

/**
 * The sort dropdown's items (messages/state-filter-dropdown, after its menu is opened into the page): each radio and
 * "Mark all as read" marked for ofMirrorChats (data-oi-chats); "Select" (OF's bulk-select mode, no bulk action here)
 * disabled with the tooltip.
 */
function chatSortMenu(html) {
  html = html.replace(/<div\b([^>]*\srole="menuitem"[^>]*)>/g, (open, attrs, at) => {
    if (!/\sclass="[^"]*\bv-list-item\b/.test(attrs)) return open;
    const item = element(html, at, "div");
    const radio = item.match(/\sfor="(chats_(?:filter|order)_input_\w+)"/)?.[1];
    const text = item.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    if (radio && Object.hasOwn(CHAT_SORT, radio)) return `<div data-oi-chats="${CHAT_SORT[radio]}"${attrs}>`;
    if (text === "Mark all as read") return `<div data-oi-chats="mark-all"${attrs}>`;
    if (text === "Select") return `<div data-oi-select=""${attrs.replace(/\stabindex="[^"]*"/, ' tabindex="-1"').replace(/(\sclass="[^"]*)"/, "$1 v-list-item--disabled\"")} aria-disabled="true" title="${NOT_YET_TITLE}">`;
    return open;
  });
  return html.replace(/(<div data-oi-select=""[^>]*>)\s*<a class="of-state-link"[^>]*><\/a>/, "$1");
}

/** The folders dialog: one example row kept hidden (ofMirrorChats' template), OF's "Nothing found" until the lists come; its Sort disabled. */
function pinToChat(modal) {
  let kept = false;
  modal = modal.replace(/<label\b[^>]*\sclass="b-rows-lists__item\b[\s\S]*?<\/label>/g, (row) => {
    if (kept) return "";
    kept = true;
    return row.replace(/^<label\b/, '<label style="display:none"');
  });
  modal = modal.replace(/(<div\b[^>]*\sclass="b-rows-lists\b[^"]*"[^>]*>)/, `$1<div class="empty-message" data-oi-empty="" style="padding:24px 16px;text-align:center;color:#8a96a3;font-size:14px"><span>Nothing found</span></div>`);
  return notYetWhere(modal, (attrs) => /\saria-label="Sort"/.test(attrs));
}
/**
 * New message's controls with nothing behind them. On New message and its dialogs' pages (isSendComposer) Add media, the
 * vault and the price work as a chat's (the vault and price buttons open sendStates' pages), and the schedule button
 * carries data-oi-wired (ofMirrorChat's bindMass opens a date and time dialog: Cancel, Save for Later, Next); on its list
 * pages they stay disabled.
 */
const SEND_NOT_YET = (sub) => (attrs) =>
  (/\saria-label="Add media"/.test(attrs) && !isSendComposer(sub)) ||
  (/\sat-attr="(?:add_vault_media|price_btn)"/.test(attrs) && !isSendComposer(sub)) ||
  /\sat-attr="(?:list_filter|filter_delete_btn)"/.test(attrs) ||
  (/\sat-attr="scheduled_msg"/.test(attrs) && !/\sdata-oi-wired=/.test(attrs)) ||
  /\sclass="b-tabs__nav__link\b/.test(attrs);
/** A chat's composer tools under the header menu: links to their dialogs, as on the chat page. */
const CHAT_TOOLS = { add_vault_media: "vault", scheduled_msg: "schedule", price_btn: "price" };

/** The chat gallery's tabs by their text: ofMirrorThread reads data-oi-gallery (OF's media type path segment, or its Unlocked / Purchased filter). */
const GALLERY_TABS = { All: "all", Unlocked: "opened", Purchased: "purchased", Photos: "photos", Videos: "videos", Audio: "audios" };

/**
 * A chat's Gallery (messages/chat/gallery): its tabs are links ofMirrorThread points at the open chat's view; of the
 * captured tiles one photo, one video and one locked (a PPV the Creator cannot view) stay, hidden, as ofMirrorThread's
 * templates (data-oi-tile), their link, id and picture's alt blanked; then OF's "Nothing found", shown until the
 * chat's media are listed.
 */
function galleryPage(html) {
  html = dropEl(html, "b-photos", (grid) => {
    const open = grid.match(/^<div\b[^>]*>/)[0];
    const tiles = [];
    for (const m of grid.matchAll(/<(a|div)\b[^>]*\sclass="b-photos__item\b[^"]*"[^>]*>/g)) {
      const el = element(grid, m.index, m[1]);
      const kind = m[1] === "div" ? "locked" : /\sclass="[^"]*\bm-video-item\b/.test(m[0]) ? "video" : "photo";
      if (!tiles.some((t) => t.kind === kind)) tiles.push({ kind, el });
    }
    for (const want of ["photo", "video", "locked"]) if (!tiles.some((t) => t.kind === want)) fail(`messages/chat/gallery: the capture has no ${want} tile to keep as a template`);
    const kept = tiles
      .map(({ kind, el }) =>
        el
          .replace(/^<(a|div)\b/, `<$1 data-oi-tile="${kind}" style="display:none"`)
          .replace(/\shref="[^"]*"/g, ' href="#"')
          .replace(/\sdata-id="[^"]*"/g, "")
          .replace(/(<img\b[^>]*\salt=")[^"]*"/g, '$1"'),
      )
      .join("");
    return `${open}${kept}</div><div class="infinite-status-prompt" data-oi-empty="" style="color: rgb(102, 102, 102); font-size: 14px; padding: 10px 0px;"><div class="empty-message"><span>Nothing found</span></div></div>`;
  });
  return html.replace(/<a href="[^"]*"((?:(?!>)[\s\S])*?\sclass="b-tabs__nav__link\b[^"]*"[^>]*)>([\s\S]*?)<\/a>/g, (all, attrs, inner) => {
    const text = inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    if (!Object.hasOwn(GALLERY_TABS, text)) return all;
    return `<a data-oi-gallery="${GALLERY_TABS[text]}" href="${MANAGER}/messages/chat/gallery"${attrs.replace(/\s(?:saveprevquery|target)="[^"]*"/g, "")} target="_top">${inner}</a>`;
  });
}

/**
 * A chat's pinned messages (messages/chat/pinned): OF's PinnedMessages route is the chat page with its messages list
 * `pinned` (chats-pinned-messages.js), so the page is the chat capture, its header titled "Pinned messages" with "with
 * <name>" under it (filled by ofMirrorData), the header's tools and the composer gone (its Back already goes to the chat).
 * Its header has OF's pinned actions (42549 `b-chat__header__actions`: the search button, the PinnedAction ⋮ with
 * "Unpin all messages"): ofMirrorThread's Find (filter=pinned) and ofMirrorMessageMenu's ⋮.
 */
function pinnedPage(html) {
  // OF's HeaderWithBackToTop title (as the gallery's "Chat Gallery"), in the header's own style scope.
  html = html.replace(/<h1\b([^>]*)\sat-attr="page_title"[^>]*>[\s\S]*?<\/h1>/, (_, attrs) => {
    const scope = attrs.match(/\sdata-v-[0-9a-f]+=""/)?.[0] ?? "";
    return `<h1 class="m-chat-title m-no-text-transform g-page-title m-scroll-top"${scope}><span class="b-inside-el g-text-ellipsis"${scope}>Pinned messages</span></h1>`;
  });
  html = dropEl(html, "b-chat__subheader", () => '<div class="b-chat__subheader"><div class="b-chat__subheader__col"><div class="b-chat__username g-text-ellipsis" data-oi-with=""></div></div></div>');
  html = dropEl(html, "m-chat-footer");
  html = html.replace(/(<div\b[^>]*\sclass="b-chat__messages-wrapper)"/, '$1 m-pinned"');
  // OF's pinned header: its search, then the ⋮ (the chat menu's More, here PinnedAction's).
  html = html.replace(/(<div\b[^>]*\sclass="b-btns-group m-move-right"[^>]*>)(<div\b[^>]*\sclass="b-dropdown-wrapper[^"]*"[^>]*>)<button\b([^>]*\saria-label="More"[^>]*)>/, (_, group, wrap, attrs) =>
    `${group}<button type="button" at-attr="search_btn" class="g-btn m-with-round-hover m-icon m-icon-only m-default-color m-sm-size" aria-label="Find"><svg class="g-icon" data-icon-name="icon-search" aria-hidden="true"><use href="#icon-search" xlink:href="#icon-search"></use></svg></button>${wrap}<button data-oi-pinned-menu=""${attrs.replace(/\s(?:disabled|title)="[^"]*"/g, "")}>`);
  if (!html.includes("data-oi-pinned-menu")) fail("messages/chat/pinned: the chat header has no More button for OF's pinned actions");
  return html;
}

/**
 * The Messages pages: no example stays. The chat list keeps one example row, hidden, as ofMirrorData's template; its
 * filter tabs lose the captured counts, and the list's loader (a spinner that never ends, or a captured "Something went
 * wrong") gives way to OF's "Nothing found", which ofMirrorData hides once the Creator's chats are listed. A chat keeps
 * its first day of messages, hidden, as the thread's templates (ofMirrorData lists the open chat's messages in copies);
 * its header loses the example's name and online status. The chat gallery's example tiles go (OF's "Nothing found"
 * instead) and its filter tabs are disabled. MESSAGES_NOT_YET's controls are disabled with the tooltip. A chat's pages
 * hide the chat list on a phone, as OF does.
 */
function messagesPage(html, sub) {
  const off = `title="${NOT_YET_TITLE}"`;
  html = dropEl(html, "b-chats__scroller", (list) => {
    list = dropEl(list, "vue-recycle-scroller__item-wrapper", (wrapper) => {
      const open = wrapper.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"');
      const views = [...wrapper.matchAll(/<div class="vue-recycle-scroller__item-view"/g)].map((m) => element(wrapper, m.index, "div"));
      const tpl = views.find((v) => v.includes("b-chats__item__last-message__text")) ?? views[0];
      const kept = tpl ? tpl.replace(/^<div class="vue-recycle-scroller__item-view" style="[^"]*"/, '<div class="vue-recycle-scroller__item-view" style="display:none"') : "";
      return `${open}${kept}</div>`;
    });
    list = list.replace(/(\sclass="vue-recycle-scroller b-chats__list-wrapper[^"]*?) m-loading-items"/, '$1"');
    // Every loader prompt hidden (the spinner, the error and its Retry), then OF's own "Nothing found" one shown.
    list = list.replace(/(<div (?:data-v-[0-9a-f]+="" )*class="infinite-status-prompt") style="[^"]*"/g, '$1 style="display: none;"');
    list = list.replace(
      /(<div (?:data-v-[0-9a-f]+="" )*class="infinite-status-prompt") style="display: none;">(<div\b[^>]*\sclass="empty-message"[^>]*><span>\s*Nothing found\s*<\/span>)/,
      '$1 style="" data-oi-empty="">$2',
    );
    // A list captured with rows: its no-results slot (the one scoped twice) empty, OF's words put in it.
    if (!list.includes("data-oi-empty")) {
      list = list.replace(
        /(<div (?:data-v-[0-9a-f]+="" )*class="infinite-status-prompt") style="display: none;"><div (data-v-[0-9a-f]+="") (data-v-[0-9a-f]+="")><\/div><\/div>/,
        '$1 style="" data-oi-empty=""><div $2 class="empty-message" $3><span>Nothing found</span></div></div>',
      );
    }
    return dropEl(list, "b-tabs__nav", (bar) =>
      bar
        .replace(/<span class="b-tabs__nav__count">[^<]*<\/span>/g, "")
        .replace(/<button\b([^>]*\sclass="b-tabs__nav__link\b[^>]*)>([\s\S]*?)<\/button>/g, (all, attrs, inner) => {
          const text = inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
          return Object.hasOwn(CHAT_TABS, text) ? `<button data-oi-tab="${CHAT_TABS[text]}"${attrs}>${inner}</button>` : all;
        }),
    );
  });
  // The sort dropdown opens from a chat's pages too (as from the list), its choices going back to the chat.
  if (sub === "chat" || sub.startsWith("chat/")) {
    html = html.replace(/(<div\b[^>]*\sat-attr="sort_dropdown"[^>]*>)/, `$1<a class="of-state-link" href="${MANAGER}/messages/state-filter-dropdown" target="_top" aria-label="Toggle"></a>`);
  }
  html = dropEl(html, "b-chat__messages-wrapper", (wrapper) => {
    const open = wrapper.match(/^<div\b[^>]*>/)[0];
    const first = roots(wrapper, "b-chat__item-message")[0];
    if (!first) return wrapper;
    const day = element(wrapper, first.index, "div").replace(/^<div\b[^>]*/, (tag) => `${tag} style="display:none"`);
    return `${open}${day}</div>`;
  });
  // Each message's ⋮ (OF's ItemActions): ofMirrorMessageMenu's, on the chat and its pinned page (a State page's stay off).
  if (sub === "chat" || sub === "chat/pinned") html = html.replace(/<button\b((?:(?!data-oi-msg-menu)[^>])*\sclass="btn dropdown-toggle m-size-sm m-btn-vertical-dots\b[^"]*"[^>]*)>/g, (_, attrs) => `<button data-oi-msg-menu=""${attrs.replace(/\s(?:disabled|title)="[^"]*"/g, "")}>`);
  // The header's name (the open chat's, filled in at run time), with no verified mark: a fan's never is.
  html = html.replace(/(<div\b[^>]*\sclass="b-chat__header__title\b[\s\S]*?<span class="g-user-name">)[^<]*(<\/span>)(?:<svg class="m-verified-icon g-icon"[\s\S]*?<\/svg>)?/, "$1$2");
  html = html.replace(/(<div\b[^>]*\sclass="b-chat__user-status\b[^"]*"[^>]*>)[\s\S]*?(<\/div>)/, '$1$2');
  // The header's pin button and Gallery link: ofMirrorData points them at the open chat's pages (and lights the pin
  // while the chat has pinned messages, as OF).
  html = html.replace(/<a href="\/of-manager\/messages\/chat\/(pinned|gallery)"(?=[^>]*\sat-attr="(?:pinned|gallery)_btn")/g, '<a data-oi-chat-link="$1" href="/of-manager/messages/chat/$1"');
  if (sub === "chat" || sub.startsWith("chat/state-")) html = chatHeaderTools(html, sub);
  if (sub === "chat/pinned") html = pinnedPage(html);
  // A chat on a phone: OF renders only the chat below its two-column width (1004px), never the list above it.
  if (sub === "chat" || sub.startsWith("chat/")) {
    html = `<style>@media (max-width: 1003.98px) { .b-chats__conversations-list { display: none !important; } }</style>${html}`;
  }
  if (sub === "chat/state-header-menu") {
    html = html.replace(
      /<button\b([^>]*\sat-attr="(add_vault_media|scheduled_msg|price_btn)"[^>]*)>([\s\S]*?)<\/button>/g,
      (_, attrs, at, inner) => `<a${attrs.replace(/\stype="[^"]*"/, "")} href="${MANAGER}/messages/chat/state-${CHAT_TOOLS[at]}" target="_top">${inner}</a>`,
    );
  }
  // A chat's State pages (a menu or dialog open over it): its Find is the chat page's (ofMirrorThread binds it there only).
  if (sub.startsWith("chat/state-")) html = notYetWhere(html, (attrs) => /\sat-attr="search_btn"/.test(attrs));
  if (sub === "chat/gallery") html = galleryPage(html);
  if (sub.startsWith("send")) {
    if (isSendComposer(sub)) html = html.replace(/<button\b((?:(?!disabled=|data-oi-wired)[^>])*\sat-attr="scheduled_msg"[^>]*)>/, '<button$1 data-oi-wired="">');
    html = notYetWhere(html, SEND_NOT_YET(sub));
    // The example selection's chip ("123 Selected") goes.
    html = dropEl(html, "b-filter-counter__wrapper").replace(/(\sclass="b-search-users-form__wrapper) m-active-filter"/, '$1"');
    // The Exclude and Following tabs' sort (New message's own opens its State page).
    if (sub !== "send" && !sub.startsWith("send/state-")) html = notYetWhere(html, (attrs) => /\saria-label="Sort"/.test(attrs));
    // New message's example lists (List N): the first kept hidden, the template ofMirrorChat's applyListRows copies.
    html = dropEl(html, "b-rows-lists", (list) => {
      const rows = [...list.matchAll(/<label\b[^>]*\sclass="b-rows-lists__item m-checkbox-row\b[^"]*"[^>]*>/g)].map((m) => ({ at: m.index, el: element(list, m.index, "label") }));
      if (!rows.length) return list;
      const tpl = rows[0].el.replace(/^<label\b/, '<label style="display:none"');
      const end = rows.at(-1).at + rows.at(-1).el.length;
      return list.slice(0, rows[0].at) + tpl + list.slice(end);
    });
    // A list's example users (Fan N): none, OF's own "Nothing found" in their place.
    html = dropEl(html, "b-rows-lists", (list) => {
      if (!/<label\b[^>]*\sclass="[^"]*\bm-avatar-inside\b/.test(list)) return list;
      const open = list.match(/^<div\b[^>]*>/)[0];
      return `${open}<div class="infinite-status-prompt" data-oi-empty="" style="color: rgb(102, 102, 102); font-size: 14px; padding: 10px 0px;"><div class="empty-message"><span>Nothing found</span></div></div></div>`;
    });
  }
  // A chat's and New message's composer: OF's Format text panel at the top of its sticky panel (hidden until Aa opens it).
  if (hasComposer(sub) && FORMAT_TOOLBAR) html = html.replace(/(<div\b[^>]*\sclass="b-make-post__sticky-panel"[^>]*>)/, `$1${FORMAT_TOOLBAR}`);
  return notYetWhere(html, MESSAGES_NOT_YET(sub));
}

// ---------------------------------------------------------------- vault

/** OF's no-results slot of an infinite-loading list (the prompt scoped twice) shown, with OF's "Nothing found" in it. */
const nothingFound = (html) =>
  html.replace(
    /(<div (?:data-v-[0-9a-f]+="" )*class="infinite-status-prompt") style="display: none;"><div (data-v-[0-9a-f]+="") (data-v-[0-9a-f]+="")><\/div><\/div>/,
    '$1 style="color: rgb(102, 102, 102); font-size: 14px; padding: 10px 0px;" data-oi-empty=""><div $2 class="empty-message" $3><span>Nothing found</span></div></div>',
  );

/** The `<tag class="cls…">` elements of `html` (class list starting with `cls`), each { at, el }. */
const elements = (html, tag, cls) =>
  [...html.matchAll(new RegExp(`<${tag}\\b[^>]*\\sclass="${cls}\\b[^"]*"[^>]*>`, "g"))].map((m) => ({ at: m.index, el: element(html, m.index, tag) }));

/**
 * The Vault pages (vault, vault/list and their State pages): no example stays. The folder list keeps "All media" (its
 * example pictures become one hidden, pictureless cover and its counts one hidden count, ofMirrorData's templates) and
 * one example folder row, hidden,
 * nameless, the template ofMirrorData copies per Creator folder. The media grid keeps one row with a photo tile and a
 * video tile, hidden, as applyVaultMedia's templates; under it OF's "Nothing found", which ofMirrorData hides once the
 * Creator's media are listed (or turns into a loading or error line). The folder list's Search is Wired (ofMirrorVault
 * opens its search form, OF's ?slist=). vault/list (OF's custom folder page; a Creator's folder row opens vault?list=<id>
 * instead) heads its grid "All media" and keeps its media tabs enabled (the example folder had no GIF or audio); its
 * two Sorts and "Create new category" open the Vault's State pages (no State page of their own), its More (no Relay
 * route) is disabled with the tooltip.
 */
function vaultPage(html, sub) {
  html = dropEl(html, "b-rows-lists", (list) => {
    const rows = elements(list, "div", "b-rows-lists__item");
    if (!rows.length) return list;
    const all = rows.find((r) => /\shref="\/of-manager\/vault"/.test(r.el));
    const tpl = rows.find((r) => r !== all && r.el.includes("b-content-inside-thumbs__icon"));
    // One cover kept, hidden and pictureless: setCovers copies it per folder cover (OF's `medias`).
    const oneCover = (set) => {
      const first = elements(set, "div", "b-photos__item")[0];
      return `${set.match(/^<div\b[^>]*>/)[0].replace(/^<div\b/, '<div style="display:none"')}${first ? first.el.replace(/\ssrc="[^"]*"/, "") : ""}</div>`;
    };
    // One count kept, hidden: setCounts copies it per kind.
    const oneCount = (row) =>
      dropEl(dropEl(row, "b-media-set", oneCover), "b-content-inside-thumbs", (thumbs) => {
        const first = elements(thumbs, "span", "b-content-inside-thumbs__item")[0];
        return `${thumbs.match(/^<div\b[^>]*>/)[0]}${first ? first.el.replace(/^<span\b/, '<span style="display:none"') : ""}</div>`;
      });
    const kept = [
      all ? oneCount(all.el) : "",
      tpl
        ? oneCount(tpl.el)
            .replace(/^<div\b/, '<div style="display:none"')
            .replace(/(\shref="\/of-manager\/vault\/list)\?row=[^"]*"/, '$1"')
            .replace(/(<div\b[^>]*\sclass="b-rows-lists__item__name\b[^"]*"[^>]*>)[^<]*/, "$1")
        : "",
    ].join("");
    const end = rows.at(-1).at + rows.at(-1).el.length;
    return list.slice(0, rows[0].at) + kept + list.slice(end);
  });
  html = dropEl(html, "b-photos", (grid) => {
    const tiles = elements(grid, "div", "b-photos__item").map((t) => t.el);
    const photo = tiles.find((t) => !/m-video-duration|b-photos__item__play-btn/.test(t));
    const video = tiles.find((t) => t.includes("m-video-duration"));
    grid = dropEl(grid, "vue-recycle-scroller__item-wrapper", (wrapper) => {
      const open = wrapper.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"');
      const view = elements(wrapper, "div", "vue-recycle-scroller__item-view")[0]?.el;
      const cell = view && elements(view, "div", "dynamic-scroller-item")[0]?.el;
      if (!cell) return `${open}</div>`;
      const row = view.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="display:none"');
      return `${open}${row}${cell.match(/^<div\b[^>]*>/)[0]}${photo ?? ""}${video ?? ""}</div></div></div>`;
    });
    return nothingFound(grid);
  });
  // The folder list's Search (not the media search form's submit): ofMirrorVault's folder search, Wired.
  html = html.replace(/<button\b([^>]*\saria-label="Search")>/g, (m, attrs) => (/\stype="submit"|data-oi-wired/.test(attrs) ? m : `<button${attrs} data-oi-wired="">`));
  if (sub !== "list") return html;
  html = html.replace(/(<div\b[^>]*\sclass="l-main-content m-r-side"[\s\S]*?<h1\b[^>]*>\s*<span\b[^>]*>)[^<]*/, "$1All media");
  html = html.replace(
    /<li class="b-tabs__nav__item m-no-pointer"><button tabindex="-1" disabled="disabled" type="button" class="(b-tabs__nav__link m-reset-wcag-link-focus) m-disabled">/g,
    '<li class="b-tabs__nav__item"><button tabindex="0" type="button" class="$1">',
  );
  // Its folder sort, media sort and Create new category open the Vault's own state pages (ofMirrorVault's keepView
  // carries the view); the header's More stays disabled.
  html = linkEl(html, "aria:Create new category", `${MANAGER}/vault/state-add-list`) ?? html;
  const sorts = ["state-lists-sort-dropdown", "state-sort-dropdown"];
  const wrappers = roots(html, "b-dropdown-wrapper").filter((m) => /^<div\b[^>]*>\s*<button\b[^>]*\saria-label="Sort"/.test(html.slice(m.index)));
  for (const [i, m] of [...wrappers.entries()].reverse()) {
    const href = `${MANAGER}/vault/${sorts[i]}`;
    const at = m.index + m[0].length;
    html = html.slice(0, at) + anchor("of-state-link", href, "Toggle") + html.slice(at);
  }
  return notYetWhere(html, (attrs) => /\saria-label="More"/.test(attrs));
}

// ---------------------------------------------------------------- queue

/**
 * The queue pages. The header's "Messages saved for later" and "Posts saved for later" open their pages (as OF's own
 * do); "Add to queue" ("+": header, list view and right column, and the saved-for-later pages' two, which get
 * data-oi-add) carries data-oi-wired: ofMirrorQueue's bindQueue opens OF's "Add to queue" modal (Scheduled / Save for
 * later) and the composer from it. The saved-for-later pages' auto-publish switch stays disabled (no Relay route). The month pages' arrows and day cells carry data-oi-wired: ofMirrorQueue's bindCalendar moves the
 * month and day in place. A tab state page (Messages, Streams) gets the calendar/list switch as a link to the list
 * view, as Queue's own has (it was captured without one).
 */
function queuePage(html, sub) {
  html = html.replace(/<button\b([^>]*\saria-label="(Messages|Posts) saved for later"[^>]*)>([\s\S]*?)<\/button>/g, (_, attrs, kind, inner) =>
    `<a${attrs.replace(/\s(type|disabled|role)="[^"]*"/g, "")} href="${MANAGER}/queue/saved-for-later-${kind.toLowerCase()}" target="_top">${inner}</a>`,
  );
  html = html.replace(/<button\b((?:(?!data-oi-wired)[^>])*\sat-attr="(?:prev|next)_(?:month|day_sidebar)"[^>]*)>/g, "<button$1 data-oi-wired=\"\">");
  html = html.replace(/<button\b([^>]*\sclass="b-month-day-cell[^"]*"[^>]*)>/g, "<button$1 data-oi-wired=\"\">");
  html = html.replace(/<button\b((?:(?!data-oi-wired)[^>])*\sat-attr="add_event_(?:header|page|sidebar)"[^>]*)>/g, "<button$1 data-oi-wired=\"\">");
  // The saved-for-later pages' "+" (the header's icon-add button and the b-new-event-btn): OF's "Add to queue".
  if (sub.startsWith("saved-for-later-"))
    html = html.replace(/<button\b((?:(?!data-oi-wired)[^>])*)>((?:(?!<\/?button\b)[\s\S])*?data-icon-name="icon-add"(?:(?!<\/?button\b)[\s\S])*?)<\/button>/g, '<button$1 aria-label="Add to queue" data-oi-add="" data-oi-wired="">$2</button>');
  if (sub.startsWith("state-tab-"))
    html = html.replace(
      /(<div\b[^>]*\sclass="b-content-filter__group-btns[^"]*"[^>]*>)<button\b([^>]*)>((?:(?!<\/button>)[\s\S])*data-icon-name="icon-agenda"(?:(?!<\/button>)[\s\S])*)<\/button>/,
      (_, open, attrs, inner) => `${open}<a${attrs} href="${MANAGER}/queue/state-list-view" target="_top">${inner}</a>`,
    );
  html = html.replace(
    /<input\b((?:(?!disabled=)[^>])*\sname="isSavedForLater"[^>]*)>(<label\b)/,
    `<input disabled="disabled"$1>$2 title="${NOT_YET_TITLE}" style="opacity:.5;cursor:default"`,
  );
  // The saved-for-later pages' "every ..." select (a Vuetify select: its slot is the control): disabled the way Vuetify draws it.
  if (sub.startsWith("saved-for-later-"))
    html = html
      .replace(/(<div\b[^>]*\sclass="v-input\b[^"]*?\sv-select)("[^>]*)>(<div class="v-input__control">)<div role="button"[^>]*?class="v-input__slot">/, (_, cls, rest, control) =>
        `${cls.includes("v-input--is-disabled") ? cls : `${cls} v-input--is-disabled`}${rest} title="${NOT_YET_TITLE}" style="pointer-events:none">${control}<div class="v-input__slot">`,
      )
      .replace(/<input\b((?:(?!disabled=)[^>])*\sat-attr="dropdown")/, '<input disabled="disabled"$1')
      .replace(/(\sclass="v-label v-label--active)(?! v-label--is-disabled)/, "$1 v-label--is-disabled")
      .replace(/(\sclass="v-select__selection v-select__selection--comma)(?! v-select__selection--disabled)/, "$1 v-select__selection--disabled");
  return notYetWhere(html, (attrs) => sub.startsWith("saved-for-later-") && !/\sdata-oi-wired=/.test(attrs));
}

/**
 * The icons ofMirrorQueue's Add to queue modal and the saved-for-later cards draw (OF's own sprite symbols, as the live
 * modal and cards use them), kept in the sprite of the pages that show them: the queue, New post and Go live (the
 * Scheduled events widget's "+") and New message (its date and time dialog).
 */
const QUEUE_ICONS = " #icon-post2 #icon-message #icon-live #icon-recent #icon-calendar-datepicker #icon-saved-for-later-posts #icon-saved-for-later-message #icon-more #icon-post-cat";
const QUEUE_ICON_SECTIONS = new Set(["queue", "new-post", "streaming", "messages"]);
/**
 * The data-v scopes of OF's saved-for-later card (ScheduleEventDayView: b-post m-queue-post and its queue rows, as the
 * live saved-for-later pages render a row) and its More dropdown: their CSS is linked on the queue pages, whose captures
 * hold no card.
 */
const SFL_CARD_SCOPES = '<i data-v-48bf68d0="" data-v-48f703ce="" data-v-55f3fe86="" data-v-74f8aaf2=""></i>';

/** The month pages' Posts / Messages / Streams tabs (after the State page links): buttons ofMirrorQueue toggles in place. */
const queueTabs = (html) =>
  html
    .replace(/<a\b([^>]*\sclass="b-tabs__nav__link\b[^"]*")\shref="[^"]*"\starget="_top">([\s\S]*?)<\/a>/g, '<button$1 type="button" data-oi-wired="">$2</button>')
    .replace(/<button\b((?:(?!data-oi-wired)[^>])*\sclass="b-tabs__nav__link\b[^"]*"(?:(?!data-oi-wired)[^>])*)>/g, '<button$1 data-oi-wired="">');

// ---------------------------------------------------------------- collections

/**
 * The icons of My profile's post row, which ofMirrorFeeds borrows (TEMPLATES.post) for Bookmarks' and a list's Posts
 * tab's posts (its More, pin, Like, Comment and Bookmark): kept in those pages' sprite, whose captures hold no post.
 */
const POST_ICONS = " #icon-more #icon-pin-on #icon-post-cat #icon-loading #icon-like #icon-comment #icon-statements #icon-funds #icon-bookmark";
/** Collections' list rows: their avatar stacks' default avatar (ofMirrorData's, a member with no picture or name). */
const LIST_ICONS = " #icon-profile";
const postRowsPage = (route) => route.section === "collections" && /^(?:bookmarks\/|user-lists\/list\/posts$)/.test(route.sub);

/** OF's empty-list line, marked for ofMirrorData (hidden once rows are listed, or turned into a loading or error line). */
const emptyNote = (text) =>
  `<div class="empty-message" data-oi-empty="" style="padding:24px 16px;text-align:center;color:#8a96a3;font-size:14px"><span>${text}</span></div>`;

/** `html` with each `<tag class="cls…">` element replaced by `swap(el)`, last first (offsets stay valid). */
const swapEls = (html, tag, cls, swap) =>
  elements(html, tag, cls)
    .reverse()
    .reduce((h, { at, el }) => h.slice(0, at) + swap(el) + h.slice(at + el.length), html);

/** An `<a href="#">` (OF's link with no target in the mirror) as a disabled button with the tooltip. */
const deadLinkOff = (html, pick) =>
  html.replace(/<a\b([^>]*)\shref="#"([^>]*)>((?:(?!<\/a>)[\s\S])*)<\/a>/g, (all, a, b, inner) =>
    pick(`${a}${b}`, inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim())
      ? `<button type="button" disabled="disabled" title="${NOT_YET_TITLE}"${`${a}${b}`.replace(/\s(?:tabindex|aria-current|saveprevquery|target)="[^"]*"/g, "")}>${inner}</button>`
      : all,
  );

/** OF's empty feed picture (img/empty-posts.svg of the dump's build), as a mirror URL; null if the dump has none. */
function emptyPostsUrl() {
  const base = path.join(DUMP, STATIC_PREFIX);
  const build = fs.existsSync(base) ? fs.readdirSync(base).find((d) => fs.existsSync(path.join(base, d, "img/empty-posts.svg"))) : null;
  return build ? staticUrl(`${STATIC_PREFIX}${build}/img/empty-posts.svg`) : null;
}

/** A user card kept as ofMirrorData's template: hidden, nameless, without the example's lists, bio and subscription details. */
function cardTemplate(view) {
  let card = view.replace(/^(<div class="vue-recycle-scroller__item-view") style="[^"]*"/, '$1 style="display:none"');
  for (const cls of ["b-fans__item__list", "b-btn-collapse", "g-truncated-text"]) card = dropEl(card, cls);
  // The Subscription / Earnings / Offers tab bar: the details it switches between are gone.
  card = card.replace(/<div class="b-tabs__nav m-nv m-tabs-default m-flex-width m-size-sm">[\s\S]*?<\/ul><\/div>/, "");
  card = card.replace(/(<div\b[^>]*\sclass="(?:g-user-name|g-user-realname|g-user-username)\b[^"]*"[^>]*>)[^<]*/g, "$1");
  // The example's list links after its "Lists" button: one stays, nameless and without its ?row= (applyListUsers names
  // the open list in it).
  let kept = false;
  card = card.replace(/<a\b[^>]*\sclass="g-btn m-flat m-link[^"]*\bb-dot-item\b[^>]*>[\s\S]*?<\/a>/g, (a) => {
    if (kept || !/\shref="\/of-manager\/collections\/user-lists\/list/.test(a)) return "";
    kept = true;
    return a.replace(/(\shref="\/of-manager\/collections\/user-lists\/list)\?row=[^"]*"/, '$1"');
  });
  card = card.replace(/(<a\b[^>]*\sclass="g-btn m-flat m-link[^"]*\bb-dot-item\b[^>]*>\s*<span class="b-list-titles__item__text">)[^<]*/g, "$1");
  // OF's role=button chips (Follow): disabled buttons with the tooltip.
  card = swapEls(card, "div", "b-tabs__nav__item", (el) =>
    /^<div\b[^>]*\srole="button"/.test(el)
      ? el.replace(/^<div\b([^>]*)>/, (_, a) => `<button type="button" disabled="disabled" title="${NOT_YET_TITLE}"${a.replace(/\s(?:role|tabindex)="[^"]*"/g, "")}>`).replace(/<\/div>$/, "</button>")
      : el,
  );
  // The chat header's tools for the card's fan, ofMirrorCollections' card tools (its cardToolOf, the same test): the
  // name pencil, Restrict, Discount and Add notes.
  const tool = (attrs, text) =>
    /\sat-attr="(?:name_edit|restrict)"/.test(attrs) || (/\sclass="b-tabs__nav__link\b/.test(attrs) && (text === "Discount" || text === "Add notes"));
  // Every other control but the Lists buttons (ofMirrorCollections' card menu) and links.
  return notYetWhere(card, (attrs, text) => !/\sat-attr="add_to_list"/.test(attrs) && !tool(attrs, text));
}

/**
 * A list's Posts tab (OF's /my/collections/user-lists/<id>/posts; one view for every list, as Following's Posts tab):
 * the list page's capture `list` (its lists column, header and Users / Posts tabs, the Posts tab now current) with the
 * right column's content (the Recent title, the type chips and the feed) from Following's Posts tab `following` (its
 * links read as the list's own Posts tab), and that page's stylesheets added to the list page's.
 */
function listPostsRaw(list, following) {
  const id = list.raw.match(/\shref="\/my\/collections\/user-lists\/(\d+)\/posts"/)?.[1];
  const right = (html) => html.indexOf('<div class="l-main-content m-r-side"');
  // The list page's own Users / Posts tabs (its right column's, before Following's content goes in): Posts is the current one.
  const tab = (a, on) =>
    a
      .replace(/\sclass="([^"]*)"/, (_, cls) => ` class="${cls.replace(/\s*\b(?:router-link-active|m-current|m-no-pointer)\b/g, "")}${on ? " router-link-active m-current m-no-pointer" : ""}"`)
      .replace(/\s(?:aria-current|tabindex)="[^"]*"/g, "")
      .replace(/>$/, on ? ' tabindex="-1" aria-current="page">' : ' tabindex="0">');
  const at = right(list.raw);
  const own = at < 0 ? list.raw : list.raw.slice(0, at) + list.raw.slice(at).replace(/<a href="\/my\/collections\/user-lists\/\d+(\/posts)?"[^>]*>/g, (a, posts) => tab(a, !!posts));
  const from = right(following.raw);
  const old = at < 0 ? -1 : own.indexOf('<div at-attr="list_page"', at);
  const start = from < 0 ? -1 : following.raw.slice(0, following.raw.indexOf(' class="g-page-content g-sides-gaps"', from)).lastIndexOf("<div");
  if (!id || old < 0 || start < 0) fail("the list page or Following's Posts tab has no right column content to build a list's Posts tab from");
  // Following's URLs resolved where its page was (a dump page links relatively, "<host>/<path>"), its own Posts tab the list's.
  const abs = (v, rel) => {
    const u = new URL(v, `https://dump/${rel}`);
    return /^https?:/.test(v) ? v : `https://${u.pathname.slice(1)}${u.search}`;
  };
  const content = element(following.raw, start, "div")
    .replace(/\s(href|src)="(?!https?:|#|data:)([^"]*)"/g, (_, attr, v) => ` ${attr}="${abs(v, following.rel)}"`)
    .replace(/\/my\/collections\/user-lists\/subscriptions\/posts(?:\.html)?/g, `/my/collections/user-lists/${id}/posts`);
  const raw = own.slice(0, old) + content + own.slice(old + element(own, old, "div").length);
  // Following's stylesheets the list page lacks (its feed's), absolute, before </head>.
  const sheets = (html, rel) => [...html.slice(0, html.search(/<\/head>/i)).matchAll(/<link\b[^>]*\shref="([^"]*\.css)"[^>]*>/gi)].map((m) => abs(m[1], rel));
  const have = new Set(sheets(raw, list.rel).map((u) => u.replace(/^.*\//, "")));
  const extra = sheets(following.raw, following.rel).filter((u) => !have.has(u.replace(/^.*\//, "")));
  const head = raw.search(/<\/head>/i);
  return raw.slice(0, head) + extra.map((u) => `<link rel="stylesheet" href="${u}">\n`).join("") + raw.slice(head);
}

/**
 * The Collections pages: no example stays.
 * - The user lists column (every user-lists page and the index) keeps one example list row, hidden and nameless, as
 *   ofMirrorData's template (applyUserLists lists the Creator's lists in copies), and OF's "Nothing found" under it.
 * - A users column (the index's and a list's, Fans, Following and its tabs) keeps one fan card, hidden, as
 *   applyListUsers' template (Following's creator cards go: the Relay has no subscriptions read), and "Nothing found".
 *   Its Lists, name pencil, Discount, Restrict and Add notes are ofMirrorCollections' (the others disabled with the tooltip).
 * - The right column's list name (index, list, a list's Posts tab) is drawn by ofMirrorData; Fans' and Following's filter chips lose the
 *   captured counts, and their chips with no page of their own are disabled; Attention required's rows go.
 * - Post Labels: one label row, hidden, as applyLabels' template; the example posts go (the Relay has no route for a
 *   label's posts), OF's "No posts yet" instead; the posts' filter chips and tools are disabled.
 * - OF's "Something went wrong" prompts (and their Retry) are hidden. Search, Search users (but on the index and a list
 *   page: ofMirrorCollections'), Sort, Filter, Pin to home, Posts tabs with no page and the Bookmarks "+" (no bookmark
 *   folder write) are disabled with the tooltip; the index's Send message links to New message, as the list page's does.
 */
function collectionsPage(html, sub) {
  // OF's error prompts: hidden.
  html = swapEls(html, "div", "infinite-status-prompt", (el) =>
    /went wrong/i.test(el) ? el.replace(/^(<div\b[^>]*?)\sstyle="([^"]*)"/, (_, open, style) => `${open} style="${style.replace(/;?\s*display:\s*none;?/, "")};display: none;"`) : el,
  );
  html = dropEl(html, "b-user-lists__list", (col) => {
    const views = elements(col, "div", "vue-recycle-scroller__item-view").map((v) => v.el);
    const tpl = views.find((v) => v.includes('href="/of-manager/collections/user-lists/list') && v.includes("b-content-inside-thumbs__item"));
    const row = tpl
      ? dropEl(tpl, "b-media-set")
          .replace(/^(<div class="vue-recycle-scroller__item-view") style="[^"]*"/, '$1 style="display:none"')
          .replace(/(\shref="\/of-manager\/collections\/user-lists\/list)\?row=[^"]*"/, '$1"')
          .replace(/(<div\b[^>]*\sclass="b-rows-lists__item__name\b[^"]*"[^>]*>)[^<]*/, "$1")
          .replace(/(<span\b[^>]*\sclass="b-content-inside-thumbs__item\b[^"]*"[^>]*>)[^<]*/g, "$1")
      : "";
    col = dropEl(col, "vue-recycle-scroller__item-wrapper", (w) => `${w.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"')}${row}</div>`);
    col = dropEl(col, "vue-recycle-scroller__slot", (s) => `${s.match(/^<div\b[^>]*>/)[0]}</div>`);
    return dropEl(col, "b-rows-lists", (lists) => lists + emptyNote("Nothing found"));
  });
  html = dropEl(html, "b-wrapper-recycle-scroller", (users) => {
    const views = elements(users, "div", "vue-recycle-scroller__item-view").map((v) => v.el);
    const tpl = views.find((v) => /\sclass="b-users__item m-fans\b/.test(v));
    users = swapEls(users, "div", "vue-recycle-scroller__item-wrapper", (w) => {
      const open = w.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"');
      return `${open}</div>`;
    });
    if (tpl) users = users.replace(/(<div class="vue-recycle-scroller__item-wrapper" style="min-height: 0px;">)/, `$1${cardTemplate(tpl)}`);
    return users + emptyNote("Nothing found");
  });
  // Attention required: the example rows go.
  html = html.replace(/(<table\b[^>]*\sclass="b-table\b[\s\S]*?<tbody\b[^>]*>)[\s\S]*?(<\/tbody>\s*<\/table>)/, (_, open, close) => `${open}${close}${emptyNote("Nothing found")}`);
  // The open list's name (index, list, its Posts tab): ofMirrorData's.
  if (sub === "" || sub === "index" || sub === "user-lists/list" || sub === "user-lists/list/posts")
    html = html.replace(/(<div class="l-main-content m-r-side">\s*<div\b[^>]*>\s*<h1\b[^>]*>\s*<span\b[^>]*>)[^<]*/, "$1");
  // The filter chips' captured counts.
  html = html.replace(/(<span class="b-tabs__nav__text">\s*(?:All|Active|Expired|Restricted|Blocked|Attention required))\s+\d[\d.,K]*\s*(<\/span>)/g, "$1 $2");
  // Post Labels: one label row, hidden; no example post.
  if (sub.startsWith("post-labels/")) {
    html = dropEl(html, "b-post-labels__list", (col) => {
      const rows = elements(col, "div", "b-rows-lists__item");
      if (!rows.length) return col;
      const tpl = dropEl(rows[0].el, "b-media-set")
        .replace(/^<div\b/, '<div style="display:none"')
        .replace(/(<div\b[^>]*\sclass="b-rows-lists__item__name\b[^"]*"[^>]*>)[^<]*/, "$1")
        .replace(/(<span\b[^>]*\sclass="b-content-inside-thumbs__item\b[^"]*"[^>]*>)[^<]*/g, "$1")
        .replace(/\s(?:aria-current="page"|class="([^"]*)")/g, (m, cls) => (cls === undefined ? "" : ` class="${cls.replace(/\s*\b(?:m-current|router-link-active)\b/g, "")}"`));
      const end = rows.at(-1).at + rows.at(-1).el.length;
      return (col.slice(0, rows[0].at) + tpl + col.slice(end)).replace(/<\/div>$/, `${emptyNote("Nothing found")}</div>`);
    });
    html = html.replace(/(<div class="l-main-content m-r-side">\s*<div\b[^>]*>\s*<h1\b[^>]*>\s*<span\b[^>]*>)[^<]*/, "$1");
    const img = emptyPostsUrl();
    html = dropEl(html, "g-page-content__body", (body) => {
      const scope = body.match(/^<div\b[^>]*?\s(data-v-[0-9a-f]+)=""/)?.[1];
      body = dropEl(body, "vue-recycle-scroller__item-wrapper", (w) => `${w.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"')}</div>`);
      body = dropEl(body, "vue-recycle-scroller__slot", (s) => `${s.match(/^<div\b[^>]*>/)[0]}</div>`);
      // OF's own empty feed (as Following's Posts tab shows it).
      const empty = `<div${scope ? ` ${scope}=""` : ""} class="empty-message" data-oi-empty="">${img ? `<div class="empty-message__icon-img"><img src="${img}" alt="" class="img-responsive"></div>` : ""}<span>No posts yet</span></div>`;
      return body.replace(/<\/div>$/, `${empty}</div>`);
    });
  }
  // The index's Send message: New message, as the list page's.
  html = html.replace(/<a href="#"(\s[^>]*\saria-label="Send message")/, `<a href="${MANAGER}/messages/send"$1 target="_top"`);
  // Tabs and chips with no page of their own (Fans' Expired ... Fan Stats).
  html = deadLinkOff(html, (attrs, text) => /\sclass="b-tabs__nav__link\b/.test(attrs) && text !== "Users");
  // All Bookmarks' empty state: its picture was scrubbed to a grey square; OF's own empty feed picture instead.
  const emptyPic = emptyPostsUrl();
  if (emptyPic) html = html.replace(/(<div\b[^>]*\sclass="empty-message__icon-img"[^>]*>\s*<img\b[^>]*?\ssrc=")(?!\/of-mirror\/)[^"]*"/g, `$1${emptyPic}"`);
  const off = (attrs) =>
    /\saria-label="(?:Search|Sort|Filter|Pin to home|Compact view|More)"/.test(attrs) ||
    // Search users: ofMirrorCollections' (OF's `query` on the open list's users), on the index and a list page.
    (/\saria-label="Search users"/.test(attrs) && sub !== "" && sub !== "index" && sub !== "user-lists/list") ||
    /\sat-attr="list_filter"/.test(attrs) ||
    (sub.startsWith("bookmarks/") && /\saria-label="Create new list"/.test(attrs)) ||
    (sub.startsWith("post-labels/") && /\sclass="b-tabs__nav__link\b/.test(attrs));
  // A list's More (at-attr list_dropdown) is ofMirrorCollections' menu.
  return html.replace(/(<div\b[^>]*\sat-attr="list_dropdown"[^>]*>)(<button\b)/, "$1$2 data-oi-keep=\"\"").replace(/<button\b((?:(?!disabled=)[^>])*)>((?:(?!<\/?button\b)[\s\S])*)<\/button>/g, (all, attrs, inner) =>
    off(attrs) && !/\sdata-oi-keep=""/.test(attrs) ? `<button disabled="disabled" title="${NOT_YET_TITLE}"${attrs}>${inner}</button>` : all,
  ).replace(/\sdata-oi-keep=""/g, "");
}

// ---------------------------------------------------------------- statements

// A figure with no Relay value (All Creators, still loading, a Relay error): ofMirrorMoney writes the same.
const DASH = " — ";
/** OF's empty table row (the Referrals capture's). */
const emptyRow = (cols, text) => `<tr class="m-responsive__reset-pb"><td colspan="${cols}" class="w-100 text-center"><div class="empty-message"><span>${text}</span></div></td></tr>`;

/**
 * A statements table's example rows (those with a date): the first of each kind `kindOf(row)` names stays as a hidden
 * template (ofMirrorFeeds clones it per real row), the others go, and OF's empty row saying `text` follows the templates.
 * The table's own trailing rows (its loading row) stay. A table with no example row is left alone.
 */
function tableExamples(html, kindOf, text) {
  const at = html.indexOf("<tbody>");
  if (at < 0) return html;
  const body = element(html, at, "tbody");
  const rows = [];
  for (let i = body.indexOf("<tr", 1); i >= 0; ) {
    const el = element(body, i, "tr");
    rows.push(el);
    i = body.indexOf("<tr", i + el.length);
  }
  const examples = rows.filter((r) => r.includes('class="b-table__date"'));
  if (!examples.length) return html;
  const seen = new Set();
  const templates = examples.flatMap((r) => {
    const kind = kindOf(r);
    if (!kind || seen.has(kind)) return [];
    seen.add(kind);
    return [r.replace(/^<tr\b/, '<tr style="display:none" data-oi-template=""')];
  });
  const cols = examples[0].match(/<td\b/g).length;
  const rest = rows.filter((r) => !examples.includes(r));
  return html.slice(0, at) + `<tbody>${templates.join("")}${emptyRow(cols, text)}${rest.join("")}</tbody>` + html.slice(at + body.length);
}

/**
 * Statements' pages show no captured example: what has a Relay source is drawn at runtime (ofMirrorMoney: balances,
 * payout frequency, Earning Statistics, referral earnings, chargeback ratio; ofMirrorFeeds: the Earnings, Payouts and
 * Referrals tables), and until then (or with All Creators, or on a Relay error) shows a dash or OF's empty row. The
 * account alerts (missing banking information, "top N% of all creators") have no source and go. Unsourced controls are
 * disabled with the tooltip: Earning Statistics' date range (its picker page is not built: the Relay is asked for all
 * time only) and the Billing Support form (OF's needs its captcha). The balance box's collapse, its payout frequency
 * select (its slot) and Request withdrawal, and Referrals' Copy link are ofMirrorMoney's (data-oi-wired): the select
 * and Request withdrawal start disabled, as OF draws them until the balances arrive.
 */
function statementsPage(html, sub) {
  html = dropEl(html, "alert-danger");
  html = dropEl(html, "m-panel"); // "YOU ARE IN THE TOP N% OF ALL CREATORS!"
  // Balances, referral earnings and the payout frequency.
  html = html.replace(
    /(<div\b[^>]*\sclass="(?:b-statements__(?:current|pending)-balance__value|g-box__header__inner__value)\b[^"]*"[^>]*>)<span\b([^>]*)>[^<]*/g,
    (_, open, attrs) => `${open}<span${attrs.replace(/\bm-zero-value\b/, "")}>${DASH}`,
  );
  html = html.replace(/<span\b([^>]*\sclass="b-statements-balances__sum\b[^"]*"[^>]*)>[^<]*/g, (_, attrs) => `<span${attrs.replace(/\s*\bm-zero-value\b/, "")}>${DASH}`);
  html = html.replace(/(<div class="v-select__selection v-select__selection--comma">)[^<]*/g, "$1");
  html = html.replace(/<button\b([^>]*\sclass="g-box__header m-title")/g, '<button$1 data-oi-wired=""');
  // Referrals' link: OF's `<origin>?ref=<the Creator's id>` (ofMirrorMoney), copied by its Copy link.
  html = html.replace(/(<div class="b-referrals__copy-description">)[^<]*/, `$1${DASH}`);
  html = html.replace(/(<div\b[^>]*\sat-attr="referrals_url"[\s\S]*?<button\b)/, '$1 data-oi-wired=""');
  // Earning Statistics: every sum and the date range a dash; one month row stays as the hidden template.
  html = html.replace(/(<div\b[^>]*\sclass="b-stats-row__total-net\b[^"]*"[^>]*>)<span\b([^>]*)>[^<]*/g, (_, open, attrs) => `${open}<span${attrs}>${DASH}`);
  html = html.replace(/<span\b([^>]*\sclass="b-stats-row__val\b[^"]*"[^>]*)>[^<]*/g, (_, attrs) => `<span${attrs.replace(/\s*\bm-zero-value\b/, "")}>${DASH}`);
  html = html.replace(/(<span class="b-date-value">)[^<]*/g, "$1—");
  const months = roots(html, "b-stats-row").filter((m) => !hasClass(m[1], "m-expanded"));
  if (months.length) {
    const els = months.map((m) => ({ at: m.index, el: element(html, m.index, "div") }));
    const tpl = els[0].el.replace(/^<div\b/, '<div style="display:none" data-oi-template=""');
    const end = els.at(-1).at + els.at(-1).el.length;
    html = html.slice(0, els[0].at) + tpl + html.slice(end);
  }
  html = html.replace(/(Chargeback ratio )\d[\d.,]*%/, "$1—");
  // The tables.
  if (sub === "" || sub === "earnings")
    html = tableExamples(html, (r) => (/data-icon-name="icon-loading"/.test(r) ? "pending" : /data-icon-name="icon-done"/.test(r) ? "done" : null), "No earnings for this period");
  if (sub === "payouts") html = tableExamples(html, (r) => r.match(/<span class="(approved|rejected)">/)?.[1] ?? null, "This list is empty");
  // The balance box's Request withdrawal (captured disabled) and payout frequency select: ofMirrorMoney's, disabled until
  // the balances arrive (the select's slot gets OF's role=button back then).
  html = html.replace(/(<button\b[^>]*\sdisabled="disabled"[^>]*)>(\s*Request withdrawal\s*<\/button>)/g, '$1 data-oi-wired="">$2');
  html = html.replace(/(<div\b[^>]*\sclass="g-select__wrapper m-attach-select"[^>]*><div\b[^>]*\sclass="v-input\b[^"]*?\sv-select)("[^>]*)>(<div class="v-input__control">)<div role="button"[^>]*?class="v-input__slot">/g, (_, cls, rest, control) =>
    `${cls} v-input--is-disabled${rest}>${control}<div class="v-input__slot" data-oi-wired="">`,
  );
  // Disabled: any other Vuetify select (Billing Support's), the date range and the Billing Support form.
  html = html.replace(/(<div\b[^>]*\sclass="v-input\b[^"]*?\sv-select)("[^>]*)>(<div class="v-input__control">)<div role="button"[^>]*?class="v-input__slot">/g, (_, cls, rest, control) =>
    `${cls} v-input--is-disabled${rest} title="${NOT_YET_TITLE}" style="pointer-events:none">${control}<div class="v-input__slot">`,
  );
  html = html.replace(/<input\b((?:(?!disabled=)[^>])*\sat-attr="dropdown")/g, '<input disabled="disabled"$1');
  html = html.replace(/<textarea\b((?:(?!disabled=)[^>])*)>/g, `<textarea disabled="disabled" title="${NOT_YET_TITLE}"$1>`);
  return notYetWhere(html, (attrs, text) => /\sclass="btn dropdown-toggle b-holder-options\b/.test(attrs) || /^From .* To /.test(text) || (sub === "support" && text === "Send"));
}

// ---------------------------------------------------------------- statistics

/**
 * Statistics' figures with a Relay source, by the label OF shows above them (a main chart's summary: "summary"), per
 * tab: the figures' paths in the source's body (a pair "new / renew": two) and their change in % (OF's `delta`).
 * Sources (ofMirrorStats reads them, for the period picked): `/users/me/stats/overview?by=<by>` as <by> (its body
 * `{<OF's key>: {...}}`), and `derived` (ofMirrorStats' sums OF has no Relay route for: Tips, Stream tips, Referrals).
 * Field names are OF's own (build 202610091632: statistics-overview, SummaryBlock), checked against live bodies
 * (app/lib/__fixtures__/of/statistics-*.json). The Statements sidebar's Earnings rows are a template (statementsAside).
 */
const stat = (src, base, ...more) => ({ keys: [base, ...more].map((b) => `${src}:${b}.total`), delta: `${src}:${base}.delta` });
const STAT_FIGURES = {
  overview: {
    Earnings: stat("earnings", "earning"),
    "Profile visitors": stat("visitors", "visitors.visitors"),
    "Subscriptions earnings": stat("visitors", "visitors.earnings"),
    "New subs/Renews": stat("visitors", "visitors.subscriptions.new", "visitors.subscriptions.renew"),
    Posts: stat("posts", "posts.count"),
    "Posts earnings": stat("posts", "posts.earnings"),
    "Posts views": stat("posts", "posts.views"),
    Messages: stat("messages", "massMessages.count"),
    "Messages earnings": stat("messages", "massMessages.earnings"),
  },
  "engagement/posts": { Posts: stat("posts", "posts.count"), "Posts views": stat("posts", "posts.views"), "Posts earnings": stat("posts", "posts.earnings") },
  "engagement/messages": {
    Messages: stat("messages", "massMessages.count"),
    "Message earnings": stat("messages", "massMessages.earnings"),
    summary: stat("messages", "massMessages.count", "massMessages.earnings"),
  },
  fans: {
    Subscribers: stat("fans", "fans.subscribers"),
    "New subs/Renews": stat("fans", "fans.subscriptions.new", "fans.subscriptions.renew"),
    "Subscriptions earnings": stat("fans", "fans.earnings"),
    summary: { ...stat("fans", "fans.subscribers", "fans.earnings"), delta: null },
  },
  "reach/profile-visitors": {
    "Profile visitors": stat("visitors", "visitors.visitors"),
    "New subs/Renews": stat("visitors", "visitors.subscriptions.new", "visitors.subscriptions.renew"),
    "Subscriptions earnings": stat("visitors", "visitors.earnings"),
    summary: stat("visitors", "visitors.visitors"),
  },
  "reach/promotions": { "Mass-offers": stat("promo", "promo.offers"), Claims: stat("promo", "promo.claims"), "Subscriptions earnings": stat("promo", "promo.earnings") },
  "reach/trial-links": { Trials: stat("trials", "trials.offers"), Claims: stat("trials", "trials.claims"), "Subscriptions earnings": stat("trials", "trials.earnings") },
  "statements/earnings": { summary: { keys: ["earnings:earning.total", "earnings:earning.gross"], delta: "earnings:earning.delta" } },
  "statements/referrals/earnings": { summary: { keys: ["derived:ref.total"], delta: null } },
};
/**
 * Overview › Earnings' period rows (OF's `/earnings/chart` filter keys, the rows' radio names): the source of each sum.
 * `/earnings/chart` itself answers [] through the Relay (it sends no `filter`), so the per-category sums come from
 * `/users/me/stats/overview`; Tips, Stream tips and Referrals have no such source (ofMirrorStats derives them).
 */
const PERIOD_ROWS = {
  total: "earnings:earning",
  subscribes: "fans:fans.earnings",
  tips: "derived:tips",
  tips_stream: "derived:tips_stream",
  post: "posts:posts.earnings",
  chat_messages: "messages:massMessages.earnings",
  ref: "derived:ref",
  stream: "streams:streams.earnings",
};
const statFigures = (sub, label) => {
  if (STAT_FIGURES[sub]?.[label]) return STAT_FIGURES[sub][label];
  for (let s = sub; s.includes("/"); ) {
    s = s.slice(0, s.lastIndexOf("/"));
    if (STAT_FIGURES[s]?.[label]) return STAT_FIGURES[s][label];
  }
  return null;
};

// OF's level mark's arrows (ofMirrorStats draws the mark) and the Custom date picker's month arrows
// (ofMirrorDatepicker): in every Statistics page's sprite.
const STAT_ICONS = "#icon-increase #icon-decrease #icon-arrow-left #icon-arrow-right #icon-done #icon-loading #icon-alert #icon-locked #icon-undo";
/** The icons ofMirrorData and ofMirrorThread draw on the Messages pages (Find's arrows, the lit pin, tip, PPV and gallery tiles). */
const MESSAGES_ICONS = "#icon-bold #icon-italic #icon-text-colour #icon-clear-format #icon-close #icon-search #icon-stop #icon-arrow-up #icon-arrow-down #icon-pin #icon-pin-on #icon-funds #icon-likes #icon-locked #icon-unlocked #icon-media #icon-video #icon-gif #icon-voice #icon-play #icon-text-frame-off #icon-loading #icon-star-default #icon-notification";
/** Icons a page's mirror code draws that its capture may not use, kept in its sprite: [the pages, their icons]. */
const EXTRA_ICONS = [
  [(r) => r.section === "statistics", STAT_ICONS],
  [(r) => r.section === "new-post", "#icon-price"],
  [(r) => r.section === "messages", MESSAGES_ICONS],
  [(r) => QUEUE_ICON_SECTIONS.has(r.section), QUEUE_ICONS],
  [postRowsPage, POST_ICONS],
  [(r) => r.section === "collections", LIST_ICONS],
];

/** A figure slot: a dash, `key` (if any) the figure ofMirrorStats writes there; a money slot is OF's UtilsMoney span. */
const statSlot = (key, money) => `<span class=""${key ? ` data-oi-stat="${key}"` : ""}${money ? ' data-oi-money=""' : ""}>${money ? DASH : "—"}</span>`;

/**
 * Every Statistics figure OF draws as `.b-elements-determinant__value` (a summary's unit, the sidebar's rows, a main
 * chart's summary): the captured numbers and their % change go, each figure a dash slot, keyed when it has a source
 * (STAT_FIGURES by its label) and the value marked with its change's key (data-oi-delta).
 */
function statValues(html, sub) {
  const out = [];
  let at = 0;
  for (const m of html.matchAll(/<div\b[^>]*\sclass="b-elements-determinant__value\b[^"]*"[^>]*>/g)) {
    if (m.index < at) continue;
    const el = element(html, m.index, "div");
    const label = html.slice(Math.max(0, m.index - 300), m.index).match(/<div\b[^>]*\sclass="b-elements-determinant__label"[^>]*>([^<]*)<\/div>\s*$/)?.[1].trim() ?? "summary";
    const fig = statFigures(sub, label);
    let i = 0;
    const slot = (money) => statSlot(fig?.keys[i++], money);
    const value = el
      .replace(/^<div\b[^>]*>/, (open) => (fig?.delta ? open.replace(/>$/, ` data-oi-delta="${fig.delta}">`) : open))
      .replace(/<span\b[^>]*\sclass="b-statistics-level m-level-(?:up|down)"[^>]*>[\s\S]*?<\/span>/g, "")
      // The gross beside a net (Statements: "(<gross> Gross)") is the summary's next key.
      .replace(/<span\b[^>]*\sclass="(?:m-zero-value)?"[^>]*>\s*\$[\d,.]+\s*<\/span>|>([^<]*\d[^<]*)(?=<)/g, (all, text) =>
        text === undefined ? slot(true) : `>${text.replace(/\d[\d,.]*/g, () => slot(false))}`,
      );
    out.push(html.slice(at, m.index), value);
    at = m.index + el.length;
  }
  return out.join("") + html.slice(at);
}

/** The innermost element with class `cls` (a <div>) around `pos`, as { at, el }. */
function around(html, pos, cls) {
  let best = null;
  for (const m of roots(html, cls)) {
    if (m.index > pos) break;
    const el = element(html, m.index, "div");
    if (m.index + el.length > pos) best = { at: m.index, el };
  }
  return best;
}

/**
 * OF's clean state (a Top card's title and its message) saying the block has no source in Inflowwww; `empty`: OF's own
 * text for a period with no activity, which ofMirrorStats shows instead once the Relay's figures prove the period empty.
 */
const notYetState = (title, cls, empty = "") =>
  `<div class="b-clean-state"><div class="b-clean-state__title ${cls}"> ${title} </div><div class="empty-message m-default-font-weight text-left pt-0 pb-0"><span${empty ? ` data-oi-empty="${empty}"` : ""}>${NOT_YET_TITLE}</span></div></div>`;
/** A Top card's empty text in OF's words (captured on the live pages; Top Fan's from OF's texts_en.json). */
const TOP_EMPTY = {
  "Top Fan": "No Fans yet",
  "Top Post": "No Post activity during selected period",
  "Top Message": "No Message activity during selected period",
  "Top Stream": "No Streaming activity during selected period",
  "Top Story": "No Stories activity during selected period",
};
/** A captured example row as a hidden template: `kind` its name, every figure a dash, its first name (a <strong>) blank. */
const rowTemplate = (row, kind, blankName) =>
  (blankName ? row.replace(/(<strong>)[^<]*(<\/strong>)/, "$1$2") : row)
    .replace(/>([^<]*\d[^<]*)</g, "> — <")
    .replace(/^<tr\b/, `<tr style="display:none" data-oi-template="${kind}"`);

/**
 * The Statements tabs' sidebar "Earnings": OF lists only the categories with earnings in the period (StatementsStatistics),
 * else its clean state "No earnings for this period" (captured on the account's own page). One captured row stays as the
 * hidden template ofMirrorStats copies per category; the clean state follows, hidden.
 */
function statementsAside(html) {
  const head = html.search(/<div class="b-useful-data__header"> Earnings <\/div><div class="b-statistics-columns m-separate-block m-rows-items">/);
  if (head < 0) return html;
  const at = html.indexOf('<div class="b-statistics-columns', head);
  const cols = element(html, at, "div");
  const first = roots(cols, "b-elements-determinant")[0];
  if (!first) return html;
  const tpl = element(cols, first.index, "div")
    .replace(/^<div class="([^"]*)"/, '<div class="$1" style="display:none" data-oi-template="earning"')
    .replace(/(<div class="b-elements-determinant__label">)[^<]*/, "$1");
  const empty = '<div class="b-clean-state" data-oi-earnings-empty="" style="display:none"><div class="empty-message m-default-font-weight text-left pt-0 pb-0"><span>No earnings for this period</span></div></div>';
  return html.slice(0, at) + cols.match(/^<div\b[^>]*>/)[0] + tpl + "</div>" + empty + html.slice(at + cols.length);
}

/** The `<div>` at `at` (its element `el`) with its content `inner`. */
const withInner = (html, { at, el }, inner) => html.slice(0, at) + el.match(/^<div\b[^>]*>/)[0] + inner + "</div>" + html.slice(at + el.length);

/** A table's body (the first `<tbody>` after `from`): `rows`. */
function tableBody(html, from, rows) {
  const at = html.indexOf("<tbody", from);
  if (at < 0) return html;
  const body = element(html, at, "tbody");
  return html.slice(0, at) + body.match(/^<tbody\b[^>]*>/)[0] + rows + "</tbody>" + html.slice(at + body.length);
}

/** Statements › Earnings' type tabs: OF's keys (statistics-earnings.js `tabs`) by the tab's text. */
const EARNINGS_TYPES = { All: "total", Subscriptions: "subscribes", Tips: "tips", Posts: "post", Messages: "chat_messages", Streams: "stream" };
/** Engagement › Posts' metric tabs: OF's keys (248806 `Jp`) by the tab's text. */
const POSTS_BY = { Purchases: "purchases", Tips: "tips", Views: "views", Likes: "likes", Comments: "comments" };
/**
 * Engagement › Posts' period block (statistics-engagement-post's StatisticsEngagementPosts; the capture's period had no
 * post): OF's ChartSummary ("<n> posts" and the metric's sum), its double-line chart (the markup Engagement › Messages
 * captured) and its EngagementTopStatisticsTable (Date, Views, the metric's column, Price, Purchases), all hidden until
 * ofMirrorStats has the period's posts.
 */
const POSTS_BLOCK =
  '<div data-v-6ea2f093="" class="b-elements-determinant__value" data-oi-posts-summary="" style="display:none" data-oi-delta="postsChart:purchases.delta"><div data-v-6ea2f093="" class="b-engagements-summary__item"> <span class="" data-oi-stat="postsChart:posts.total">—</span> <span data-v-6ea2f093="" class="m-capitalize" data-oi-posts-word="">posts</span></div><div data-v-6ea2f093="" class="b-engagements-summary__item"><span class="" data-oi-stat="postsChart:purchases.total" data-oi-money=""> — </span></div></div>' +
  '<div class="b-chart b-chart--no-padding" data-oi-posts-chart="" style="display:none"><div class="b-chart__wrapper"><canvas height="224" class="b-chart__double-line__main" style="display: block; box-sizing: border-box; height: 112px; width: 100%;" width="1136"></canvas></div><div class="b-chart__wrapper"><canvas height="160" class="b-chart__double-line__aside" style="display: block; box-sizing: border-box; height: 80px; width: 100%;" width="1136"></canvas></div></div>' +
  '<table cellpadding="0" cellspacing="0" border="0" class="b-table m-responsive m-compact-view-mode m-default-table b-statements-table mb-4" data-oi-table="posts" style="display:none"><thead><tr><th class="m-width-engagement"> Date </th><th class="text-right"> Views </th><th class="text-right" data-oi-posts-col=""> Tips </th><th class="text-right"> Price </th><th class="text-right"> Purchases </th></tr></thead><tbody></tbody></table>';
/**
 * OF's Tips sub-tabs (tipsTabs, texts_en.json) and their keys (app.js `D`): "All tips" works with today's Relay; the
 * others need its `tipsSource` (the phase-2 Relay): disabled until ofMirrorStats knows it has it (data-oi-enable).
 */
const TIPS_TABS = ["All tips", "Profile", "Posts", "Messages", "Streams", "Stories"];
const TIPS_KEYS = ["all", "profile", "post", "chat", "stream", "story"];

/**
 * The payout tables OF draws on Statistics › Statements (statistics-payout-requests.js, statistics-referrals-earnings.js;
 * the capture has none: the account's period was empty), hidden until ofMirrorStats fills its body with the period's
 * payouts: Date, Invoice, Amount and the status cell. Header copy is OF's (texts_en.json).
 */
const payoutTable = (kind) =>
  `<div class="b-separate-section g-negative-sides-gaps g-sides-gaps" data-oi-table="${kind}" style="display:none"><table class="b-table m-responsive m-compact-view-mode m-default-table b-statements-table m-reset-bt" cellspacing="0" cellpadding="0" border="0"><thead><tr><th class="m-width-statements"> Date </th><th class="text-right"> Invoice </th><th class="text-right"> Amount </th></tr></thead><tbody></tbody></table></div>`;

/** OF's DoubleLineChart (the markup Statements › Earnings captured): its two canvases. */
const CHART_PAIR =
  '<div class="b-chart b-chart--no-padding"><div class="b-chart__wrapper"><canvas height="224" class="b-chart__double-line__main" style="display: block; box-sizing: border-box; height: 112px; width: 100%;" width="1136"></canvas></div><div class="b-chart__wrapper"><canvas height="160" class="b-chart__double-line__aside" style="display: block; box-sizing: border-box; height: 80px; width: 100%;" width="1136"></canvas></div></div>';
/**
 * OF's summary and chart over a Statistics list (statements-summary over double-line-chart: Chargebacks, Payout Requests,
 * Reach), hidden until ofMirrorStats has the phase-2 Relay's chart for the period (data-oi-chartbox).
 */
const chartBox = (key) =>
  `<div class="b-separate-section g-negative-sides-gaps g-sides-gaps" data-oi-chartbox="${key}" style="display:none"><div class="b-elements-determinant mb-0"><div class="b-elements-determinant__value m-inline" data-oi-chart-delta=""><span class="" data-oi-chart-total=""> — </span></div></div>${CHART_PAIR}</div>`;
/** OF's table head and an empty body, hidden until ofMirrorStats has rows (data-oi-table). Header copy is OF's (texts_en.json). */
const listTable = (kind, heads, cls = "b-table m-responsive m-compact-view-mode m-default-table b-statements-table") =>
  `<div class="b-separate-section g-negative-sides-gaps g-sides-gaps" data-oi-table="${kind}" style="display:none"><table class="${cls}" cellspacing="0" cellpadding="0" border="0"><thead><tr>${heads}</tr></thead><tbody></tbody></table></div>`;
/** Chargebacks' table (StatisticsStatementsDisputes). */
const DISPUTES_HEAD = '<th class="m-width-statements"> Dispute date </th><th class="text-right"> Payment date </th><th class="text-right"> Amount </th><th class="text-right"> Fee / Net </th>';
/** Referred creators / Referred users (StatementsReferredCreators / Users). */
const REFERRED_HEAD = '<th> Name </th><th class="m-responsive__hidden"> Joined </th><th class="text-right"><span class="g-hidden-desktop"> Joined / </span> Earnings </th>';

/**
 * Fans' sidebar Top Fan card (statistics-fans.js: the fan, their lists, Discount / Restrict / Add notes, the Subscription
 * and Earnings details), kept from the capture as a hidden template ofMirrorStats fills (data-oi-fan-card): no captured
 * fan, list or figure. The category tabs pick in place (data-oi-pick="fan:…"), as do Subscription and Earnings; the
 * fan's actions (Lists, Discount, Restrict, Add notes, More) and Offers have no Inflowwww write and stay disabled.
 */
const FAN_TABS = { Total: "total", Subscriptions: "subscriptions", Tips: "tips", Messages: "messages", Streams: "streams" };
function fanCard(box) {
  const start = box.indexOf('<div class="b-tabs__nav');
  if (start < 0) return "";
  const inner = box.slice(start, box.lastIndexOf("</div>"))
    .replace(/<a\b[^>]*href="[^"]*collections\/user-lists[^"]*"[^>]*>[\s\S]*?<\/a>/g, "")
    .replace(/<a\b([^>]*\sclass="g-avatar\b[^"]*"[^>]*)>[\s\S]*?<\/a>/, (all, attrs) => `<span${attrs.replace(/\s(?:href|target)="[^"]*"/g, "")} data-oi-fan-avatar=""></span>`)
    .replace(/<a\b([^>]*)>/g, (all, attrs) => `<span${attrs.replace(/\s(?:href|target|at-attr)="[^"]*"/g, "")}>`)
    .replace(/<\/a>/g, "</span>")
    .replace(/(<div\b[^>]*\sclass="g-user-name\b[^"]*"[^>]*?)(?:\saria-label="[^"]*")?([^>]*>)[^<]*/, "$1$2")
    .replace(/(<div class="g-user-username">)[^<]*/, "$1")
    .replace(/(<span class="b-fans__item__list__label">[^<]*<\/span>)<span>[\s\S]*?<\/span>(?:<\/span>)?/g, "$1<span></span>")
    .replace(/<button\b([^>]*)>(<!---->)?(<span class="b-tabs__nav__text">\s*([^<]*?)\s*<\/span>)/g, (b, attrs, c, inner, text) => {
      const clean = attrs.replace(/\s(?:disabled|tabindex)="[^"]*"/g, "").replace(/\s*\bm-disabled\b/, "");
      if (FAN_TABS[text]) return `<button data-oi-pick="fan:${FAN_TABS[text]}" disabled="disabled"${clean}>${inner}`;
      if (text === "Subscription" || text === "Earnings") return `<button data-oi-pick="fantab:${text.toLowerCase()}" data-oi-wired=""${clean}>${inner}`;
      return b;
    });
  return `<div data-oi-fan-card="" style="display:none">${inner}</div>`;
}

/**
 * Statistics' pages show no captured example (no figure, fan, message, post or chart from the capture): what has a
 * Relay source is drawn at runtime for the period picked, until then (still loading, a Relay error) a dash.
 * ofMirrorStats: the period menu (the button is wired, data-oi-period: OF's periods, the dates in the owner's time
 * zone), the summaries, sidebar rows and main chart summaries (STAT_FIGURES), the Statements sidebar's Earnings rows
 * (statementsAside), Overview › Earnings' all-time net, period sums per category (PERIOD_ROWS) and month rows,
 * Engagement › Messages' mass messages, Statements › Earnings' earnings, Reach › Profile visitors' stat and country rows
 * (hidden templates, their figures dashes), the chargeback ratio and the charts' lines; ofMirrorMoney: the balances
 * and referral earnings. What has no source (the Top Message/Fan cards, streaks, the fan tables) shows OF's clean state
 * or empty row saying "Not available in Inflowwww yet"; a captured "No … during selected period" and a Top card keep
 * OF's own text in data-oi-empty, shown instead once the figures prove the period empty. The account alerts go. Every
 * other button and radio (chart tabs, Unsend, the payout frequency) is disabled with the tooltip.
 */
function statisticsPage(html, sub) {
  for (const cls of ["alert-danger", "b-top-rated"]) while (roots(html, cls).length) html = dropEl(html, cls);
  // The sidebar's balances (ofMirrorMoney) and the payout frequency.
  html = html.replace(/<span\b([^>]*\sclass="b-statements-balances__sum\b[^"]*"[^>]*)>[^<]*/g, (_, attrs) => `<span${attrs.replace(/\s*\bm-zero-value\b/, "")}>${DASH}`);
  html = html.replace(/(<div\b[^>]*\sclass="balance-block"[\s\S]*?<div\b[^>]*\sclass="b-holder-options__title[^"]*"[^>]*>)[^<]*/, "$1");
  html = html.replace(/<span\b([^>]*\sclass="b-referrals-state__count\b[^"]*"[^>]*)>[^<]*/g, (_, attrs) => `<span${attrs.replace(/\s*\bm-zero-value\b/, "")}>${DASH}`);
  html = html.replace(/(Chargeback ratio )\d[\d.,]*%/, "$1—");
  // The period: its date range (a dash until ofMirrorStats dates it; data-oi-range="tz": with OF's local time note).
  // The period button opens ofMirrorStats' menu (data-oi-period; its title data-oi-period-title).
  html = html.replace(/(<button\b[^>]*\sclass="btn dropdown-toggle b-holder-options\b[\s\S]*?<div\b[^>]*\sclass="g-sm-text g-gray-text")>([^<]*)</, (_, open, text) =>
    `${open.replace(/^<button\b/, '<button data-oi-period="" data-oi-wired=""').replace(/(<div class="b-holder-options__title m-bold")>[^<]*/, "$1 data-oi-period-title=\"\"> Last 30 days ")} data-oi-range="${/local time/.test(text) ? "tz" : ""}">—<`,
  );
  // Captured claims of no activity (OF's text kept in data-oi-empty), and the Top cards with no source.
  html = html.replace(/(<div\b[^>]*\sclass="empty-message\b[^"]*"[^>]*>(?:<svg\b[\s\S]*?<\/svg>)?<span\b)([^>]*>)([^<]*)/g, (_, open, rest, text) =>
    `${open}${text.trim() && text.trim() !== NOT_YET_TITLE ? ` data-oi-empty="${text.trim()}"` : ""}${rest}${NOT_YET_TITLE}`,
  );
  for (let m; (m = html.match(/<div\b[^>]*\sclass="b-section-title(?: m-simple-text)?"[^>]*>\s*(Top (?:Fan|Message|Post|Stream|Story))\s*<\/div>/)); ) {
    const box = around(html, m.index, "b-separate-section") ?? around(html, m.index, "b-useful-data");
    if (!box) break;
    html = withInner(html, box, notYetState(m[1], box.el.includes("b-useful-data") ? "m-useful-header" : "m-mb-14", TOP_EMPTY[m[1]]) + (m[1] === "Top Fan" && sub.startsWith("fans/") ? fanCard(box.el) : ""));
  }
  if (sub.startsWith("statements/")) html = statementsAside(html);
  // Streaks: its tabs and calendar.
  if (sub === "overview/streaks") {
    const box = around(html, html.indexOf("b-datepicker-wrapper"), "g-position-relative");
    const tabs = around(html, html.indexOf("b-streak-tab"), "b-tabs__nav");
    // OF's streak tabs and calendar stay, hidden until ofMirrorStats has the phase-2 Relay's streaks (data-oi-streaks):
    // no captured mark or count; "Longest streak" (OF's top streak page, stab:top) and the month switch
    // (data-oi-streak-month) stay disabled until then.
    if (box && tabs) {
      let n = 0;
      const own = html
        .slice(tabs.at, box.at + box.el.length)
        .replace(/<div class="v-event\b[^"]*"[^>]*>[\s\S]*?<\/div><\/div>/g, "")
        .replace(/<div class="v-event-more\b[^"]*"[^>]*><\/div>/g, "")
        .replace(/\s*\b(?:vc-marked-[a-z-]+|vc-range-[a-z]+|m-active-streak|m-frozen-date)\b/g, "")
        .replace(/(<span\b[^>]*\sclass="b-streak-tab__count[^"]*"[^>]*>)[^<]*/g, "$1 — ")
        .replace(/<a\b([^>]*)\shref="[^"]*streaks(?:\?tab=top)?"([^>]*)>([\s\S]*?)<\/a>/, (all, a, b, inner) =>
          `<button type="button" disabled="disabled" title="${NOT_YET_TITLE}" data-oi-pick="stab:top"${`${a}${b}`.replace(/\s(?:target|tabindex)="[^"]*"/g, "").replace(/\s*\brouter-link-active\b/, "")}>${inner}</button>`)
        .replace(/(<div\b[^>]*class="b-streaks-swither__btn[^"]*"[^>]*><button\b)/g, (m) => `${m} data-oi-streak-month="${(n++ ? "next" : "prev")}"`)
        .replace(/(<button\b(?:(?!title=)[^>])*\sdisabled="disabled"(?:(?!title=)[^>])*)>/g, `$1 title="${NOT_YET_TITLE}">`)
        .replace(/(<button\b[^>]*\sclass="b-tabs__nav__link[^"]*\bm-current\b[^"]*")/, '$1 data-oi-wired="" data-oi-pick="stab:current"');
      html = html.slice(0, tabs.at) + `<div class="pt-0 b-separate-section g-negative-sides-gaps g-sides-gaps" data-oi-streaks-clean="">${notYetState("Streaks", "m-mb-14")}</div><div data-oi-streaks="" style="display:none">${own}</div>` + html.slice(box.at + box.el.length);
    }
    html = dropEl(html, "alert-info"); // "Let's start! Take action": the streaks' call
  }
  // Fans: no source. Profile visitors: its stat rows (Profile visitors, View duration) and a country row and the
  // "Others" row as hidden templates (ofMirrorStats fills them from /users/me/profile/stats), OF's empty row after them.
  if (/^fans\//.test(sub) || sub === "reach/profile-visitors") {
    for (let from = 0, at; (at = html.indexOf("<table", from)) >= 0; ) {
      const table = element(html, at, "table");
      const cols = (table.match(/<thead\b[\s\S]*?<\/thead>/)?.[0].match(/<th\b/g) ?? [1]).length;
      const rows = [...table.matchAll(/<tr\b[^>]*\sclass="m-responsive__reset-pb"[^>]*>/g)].map((m) => element(table, m.index, "tr"));
      const visitors = sub === "reach/profile-visitors" && rows.length >= 2;
      const tpls = !visitors ? "" : /vti__flag/.test(rows[0])
        ? rowTemplate(rows[0], "country", true) + (rows.find((r) => !/vti__flag/.test(r)) ? rowTemplate(rows.find((r) => !/vti__flag/.test(r)), "others", false) : "")
        : rowTemplate(rows[0], "stat-visitors", false) + rowTemplate(rows[1], "stat-duration", false);
      // Fans' tables: OF's empty text once ofMirrorStats has read the tab (EmptyPlaceholder: "Nothing found", Top fans' "No
      // users found"); marked for its rows (data-oi-table).
      const fans = { "fans/subscriptions": ["subs", "Nothing found"], "fans/top-fans": ["topfans", "No users found"] }[sub];
      const empty = fans ? emptyRow(cols, NOT_YET_TITLE).replace("<span>", `<span data-oi-empty="${fans[1]}">`) : emptyRow(cols, NOT_YET_TITLE);
      if (fans) html = html.slice(0, at) + html.slice(at).replace(/^<table\b/, `<table data-oi-table="${fans[0]}"`);
      html = tableBody(html, at, tpls + empty);
      from = at + 6;
    }
    // Profile visitors' top countries: OF's "View all" (ofMirrorStats shows it while OF has more and reads them all);
    // the Fans tables have no source: theirs goes.
    html = html.replace(/<div class="b-btn-collapse">([\s\S]*?)<\/div>/g, (all, inner) =>
      sub === "reach/profile-visitors" ? `<div class="b-btn-collapse" data-oi-countries-more="" style="display:none">${inner.replace(/<button\b/, '<button type="button" data-oi-wired=""')}</div>` : "",
    );
  }
  // Fans activity: OF's sectors chart (data-oi-activity="sectors") and hours bars (data-oi-activity="hours") wait for the
  // phase-2 Relay's `/fans-activity/list`, a note each until then.
  if (sub === "fans/activity") {
    let n = 0;
    html = html.replace(/<div class="b-chart__wrapper b-chart">(<canvas\b[\s\S]*?<\/canvas>)<\/div>/g, (all) =>
      n++ === 0
        ? `${all.replace('<div class="b-chart__wrapper b-chart">', '<div class="b-chart__wrapper b-chart" data-oi-activity="sectors" style="display:none">')}<div class="empty-message m-light-text" data-oi-activity-empty="sectors"><span>${NOT_YET_TITLE}</span></div>`
        : `${all.replace('<div class="b-chart__wrapper b-chart">', '<div class="b-chart__wrapper b-chart" data-oi-activity="hours" style="display:none">')}<div class="empty-message m-light-text" data-oi-activity-empty="hours"><span data-oi-empty="No Profile activity during selected period">${NOT_YET_TITLE}</span></div>`,
    );
  }
  // Reach › Tracking links: OF's SummaryBlock (reachCampaigns: tracking links, clicks, subscribers, each with its change),
  // hidden until the overview's campaign figures say the period has statistics; else OF's "No tracking links" text.
  if (sub === "reach/tracking-links") {
    const unit = (label, key) =>
      `<div class="b-elements-determinant"><div class="b-elements-determinant__unit"><div class="b-elements-determinant__label"> ${label} </div><div class="b-elements-determinant__value" data-oi-delta="campaign:campaigns.${key}.delta"> <span class="" data-oi-stat="campaign:campaigns.${key}.total">—</span> </div></div></div>`;
    html = html.replace(
      /(<div class="empty-message m-default-font-weight text-left pt-0 pb-0"><span data-oi-empty="No tracking links during selected period">)/,
      `<div class="b-statistics-columns m-separate-block" data-oi-campaign-summary="" style="display:none"><div class="b-statistics-item">${unit("Tracking links", "count")}${unit("Clicks", "clicks")}${unit("Subscribers", "claims")}<div class="b-elements-determinant m-chart-summary"></div></div></div>$1`,
    );
  }
  // Mass messages and earnings: an example row stays as the hidden template ofMirrorStats copies per item (earnings:
  // one per status, "loading" and "done", by its status icon).
  if (sub === "engagement/messages" || sub === "statements/earnings") {
    const at = html.indexOf("b-statements-table");
    const end = at < 0 ? -1 : html.indexOf("</table>", at);
    const rows = [...html.slice(at, end).matchAll(/<tr\b[^>]*\sclass="m-responsive__reset-pb"[^>]*>/g)].map((m) => element(html, at + m.index, "tr"));
    if (rows.length) {
      const cols = (html.slice(at, end).match(/<th\b/g) ?? [1]).length;
      const kinds = sub === "statements/earnings" ? ["loading", "done"] : [""];
      const tpls = kinds.map((k) => {
        const row = rows.find((r) => !k || r.includes(`data-icon-name="icon-${k}"`));
        return row ? row.replace(/^<tr\b/, `<tr style="display:none" data-oi-template="${k}"`) : "";
      });
      // OF's "No data" once ofMirrorStats has read the whole period (both lists are read by pages).
      const empty = sub === "statements/earnings" || sub === "engagement/messages" ? emptyRow(cols, NOT_YET_TITLE).replace("<span>", '<span data-oi-empty="No data during selected period">') : emptyRow(cols, "No data during selected period");
      html = tableBody(html, at, tpls.join("") + empty);
    }
  }
  // Overview › Earnings: All time, the period (its sums per category) and one month row as the template.
  if (sub === "overview/earnings") {
    html = html.replace(/(<div data-name="all"[\s\S]*?<div class="b-stats-row__total-net[^"]*">)<span\b[^>]*>[^<]*<\/span>/, `$1${statSlot("stats:total.all.total_net", true)}`);
    html = html.replace(/(<div data-name=")[^"]*(" class="[^"]*\bm-expanded\b[\s\S]*?<div class="b-stats-row__month")>[^<]*(<\/div><div class="b-stats-row__total-net[^"]*">)<span\b[^>]*>[^<]*<\/span>/, (_, a, b, c) =>
      `${a}period${b} data-oi-range="">—${c}${statSlot("earnings:earning.total", true)}`,
    );
    html = html.replace(/(<input\b[^>]*\sname="(\w+)" type="radio"[\s\S]*?)<div class="b-stats-row__val([^"]*)"><span><span class="g-page__link[^"]*">[^<]*<\/span><\/span><\/div><div class="b-stats-row__val([^"]*)"><span><span class="g-page__link[^"]*">[^<]*<\/span><\/span><\/div>/g, (_, head, key, c1, c2) =>
      `${head}<div class="b-stats-row__val${c1}"><span><span class="g-page__link" data-oi-stat="${PERIOD_ROWS[key]}.gross" data-oi-money="">${DASH}</span></span></div><div class="b-stats-row__val${c2}"><span><span class="g-page__link" data-oi-stat="${PERIOD_ROWS[key]}.total" data-oi-money="">${DASH}</span></span></div>`,
    );
    const months = [...html.matchAll(/<div data-name="(?!all")[^"]*" class="b-separate-section pt-0 mb-0 m-without-bold-border">/g)];
    if (months.length) {
      const els = months.map((m) => ({ at: m.index, el: element(html, m.index, "div") }));
      const tpl = els[0].el
        .replace(/^<div data-name="[^"]*"/, '<div data-name="" style="display:none" data-oi-template="month"')
        .replace(/(<div class="b-stats-row__month">)[^<]*/, "$1—")
        .replace(/(<div class="b-stats-row__total-net[^"]*">)<span\b[^>]*>[^<]*<\/span>/, `$1${statSlot("", true)}`);
      html = html.slice(0, els[0].at) + tpl + html.slice(els.at(-1).at + els.at(-1).el.length);
    }
  }
  // Statements › Earnings: OF's type tabs (ofMirrorStats switches them in place, data-oi-pick="type:…") and, under them
  // while Tips is picked, OF's Tips sub-tabs (hidden; only "All tips" has a source, the others disabled).
  if (sub === "statements/earnings") {
    let tabs = "";
    html = html.replace(/(<div class="b-tabs__nav m-nv mb-0 m-tab-rounded m-single-current">)(<ul\b[\s\S]*?<\/ul>)(<\/div>)/, (all, open, ul, close) => {
      const wired = ul.replace(/<button\b([^>]*)>(<span class="b-tabs__nav__text">\s*([^<]*?)\s*<\/span>)<\/button>/g, (b, attrs, inner, text) =>
        EARNINGS_TYPES[text] ? `<button data-oi-wired="" data-oi-pick="type:${EARNINGS_TYPES[text]}"${attrs}>${inner}</button>` : b,
      );
      const li = (text, i) =>
        `<li class="b-tabs__nav__item">${i ? `<button disabled="disabled" title="${NOT_YET_TITLE}" data-oi-enable="" data-oi-pick="tips:${TIPS_KEYS[i]}" tabindex="0" type="button" class="b-tabs__nav__link m-reset-wcag-link-focus">` : '<button data-oi-wired="" data-oi-tips-type="all" data-oi-pick="tips:all" tabindex="-1" type="button" class="b-tabs__nav__link m-reset-wcag-link-focus m-current m-no-pointer">'}<span class="b-tabs__nav__text"> ${text} </span></button></li>`;
      tabs = `<div class="b-tabs__nav m-nv mb-0 m-tab-rounded m-single-current" data-oi-tips-tabs="" style="display:none">${ul.replace(/^(<ul\b[^>]*>)[\s\S]*$/, "$1")}${TIPS_TABS.map(li).join("")}</ul></div>`;
      return open + wired + close + tabs;
    });
  }
  // Engagement › Posts: OF's metric tabs (ofMirrorStats switches them in place, data-oi-pick="by:…") and its period block.
  if (sub === "engagement/posts") {
    html = html.replace(/(<div class="b-tabs__nav m-nv m-tab-rounded mb-0 m-single-current">)(<ul\b[\s\S]*?<\/ul>)(<\/div>)/, (all, open, ul, close) =>
      open +
      ul.replace(/<button\b([^>]*)>(<span class="b-tabs__nav__text">\s*([^<]*?)\s*<\/span>)<\/button>/g, (b, attrs, inner, text) =>
        POSTS_BY[text] ? `<button data-oi-wired="" data-oi-pick="by:${POSTS_BY[text]}"${attrs}>${inner}</button>` : b,
      ) +
      close +
      POSTS_BLOCK,
    );
  }
  // Engagement's tabs (Messages: Mass / Direct; Streaming and Stories: their metric), in place once ofMirrorStats knows the
  // Relay forwards their params (data-oi-enable); Messages' search likewise (data-oi-search).
  const ENGAGEMENT_TABS = {
    "reach/profile-visitors": ["visitors", { All: "total", Guests: "guests", Users: "users" }],
    "fans/subscriptions": ["subs", { All: "total", Renews: "renew", "New subscribers": "new" }],
    "fans/top-fans": ["top", { Total: "total", Subscriptions: "subscribes", Tips: "tips", Messages: "messages", Posts: "post", Streams: "streams" }],
    "engagement/messages": ["msg", { "Mass messages": "group", "Direct messages": "direct" }],
    "engagement/streaming": ["streams", { Purchases: "purchases", Tips: "tips", Viewers: "views", Likes: "likes", Comments: "comments" }],
    "engagement/stories": ["stories", { Tips: "tips", Viewers: "views", Likes: "likes", Comments: "comments" }],
  };
  if (ENGAGEMENT_TABS[sub]) {
    const [pick, keys] = ENGAGEMENT_TABS[sub];
    html = html.replace(/(<div class="b-statistics-page-content__wrapper[^"]*"[^>]*>)(<div class="b-tabs__nav[^"]*">[\s\S]*?<\/ul><\/div>)/, (all, open, nav) =>
      open + nav.replace(/<button\b([^>]*)>(<span class="b-tabs__nav__text">\s*([^<]*?)\s*<\/span>)<\/button>/g, (b, attrs, inner, text) =>
        keys[text] ? `<button disabled="disabled" title="${NOT_YET_TITLE}" data-oi-enable="" data-oi-pick="${pick}:${keys[text]}"${attrs}>${inner}</button>` : b),
    );
  }
  if (sub === "engagement/messages") html = html.replace(/<form class="b-search-form\b/, '<form data-oi-search="" class="b-search-form');
  // Streaming and Stories: OF's ChartSummary, chart and list of the period's streams / stories (TopStreamBody /
  // TopStoryBody cards), hidden until the phase-2 Relay reads them, before OF's empty text.
  if (sub === "engagement/streaming" || sub === "engagement/stories") {
    const kind = sub === "engagement/streaming" ? "streams" : "stories";
    html = html.replace(/(<div class="empty-message"><svg\b)/,
      `<div data-v-6ea2f093="" class="b-elements-determinant__value" data-oi-summary="${kind}" style="display:none"><div data-v-6ea2f093="" class="b-engagements-summary__item" data-oi-summary-a=""></div><div data-v-6ea2f093="" class="b-engagements-summary__item" data-oi-summary-b=""></div></div><div data-oi-chart="${kind}" style="display:none">${CHART_PAIR}</div><div class="b-statistics-columns g-border-top m-without-header mb-5" data-oi-list="${kind}" style="display:none"></div>$1`);
  }
  // Reach › Promotions, Trial links and Tracking links: OF's ChartSummary, chart and table (PromotionsAndTrialLinksTable,
  // ReachCampaignsTable; Tracking links' Start date and Subscribers headers sort it), hidden until the phase-2 Relay
  // reads them, before OF's empty text.
  const REACH_LISTS = {
    "reach/promotions": ["promotions", '<th> Start date </th><th> End date </th><th class="text-right"> Offer limit </th><th class="text-right"> Claimed </th>'],
    "reach/trial-links": ["trials", '<th> Start date </th><th> End date </th><th class="text-right"> Offer limit </th><th class="text-right"> Claimed </th>'],
    "reach/tracking-links": ["campaigns", '<th class="g-pointer-cursor" data-oi-sort="created_date"> Start date </th><th> End date </th><th class="text-right"> Clicks </th><th class="text-right g-pointer-cursor" data-oi-sort="subscribers_counts"> Subscribers </th>'],
  };
  if (REACH_LISTS[sub]) {
    const [kind, heads] = REACH_LISTS[sub];
    html = html.replace(/(<div class="empty-message"><svg\b)/,
      `<div data-v-6ea2f093="" class="b-elements-determinant__value m-mt-16" data-oi-summary="${kind}" style="display:none"><div data-v-6ea2f093="" class="b-engagements-summary__item" data-oi-summary-a=""></div><div data-v-6ea2f093="" class="b-engagements-summary__item" data-oi-summary-b=""></div></div><div data-oi-chart="${kind}" style="display:none">${CHART_PAIR}</div>${listTable(kind, heads, "b-table m-responsive m-compact-view-mode m-default-table")}$1`);
  }
  // Payout Requests and Referrals: OF's table (hidden until the period has payouts) before OF's "No data" row.
  if (sub === "statements/payout-request" || sub === "statements/referrals/earnings") {
    const kind = sub === "statements/payout-request" ? "payouts" : "referrals";
    html = html.replace(/(<div class="empty-message"><span data-oi-empty="No data during selected period">)/, `${payoutTable(kind)}$1`);
  }
  // Payout Requests: OF's summary and chart over the notice (StatisticsStatementsPayoutRequests), while it has rows.
  if (sub === "statements/payout-request")
    html = html.replace(/(<div class="b-statistics-page-content__wrapper[^"]*">)(<div class="b-separate-section g-negative-sides-gaps g-sides-gaps"><div class="b-separate-section__header m-notice">)/, `$1${chartBox("payouts")}$2`);
  // Chargebacks: OF's summary, chart and disputes table (hidden until the phase-2 Relay reads them) before "No data".
  if (sub === "statements/disputes")
    html = html.replace(/(<div class="empty-message"><span data-oi-empty="No data during selected period">)/, `${chartBox("disputes")}${listTable("disputes", DISPUTES_HEAD)}$1`);
  // Referrals: the referral link (ofMirrorMoney prints the Creator's) and its Copy link, OF's; Referred creators and
  // Referred users have no Relay route yet: disabled tabs.
  if (sub === "statements/referrals/earnings") {
    html = html.replace(/(<div class="b-referrals-state__copy-url__link">)[^<]*/, `$1${DASH}`);
    html = html.replace(/(<div class="g-btn__row"><button\b)((?:(?!disabled=)[^>])*>\s*Copy link\s*<\/button>)/, '$1 data-oi-wired=""$2');
    // Referred creators / Referred users: in place (OF's child pages), once the phase-2 Relay reads them (data-oi-enable).
    html = html.replace(/<a href="#"([^>]*\sclass="(b-tabs__nav__link[^"]*)"[^>]*)>(<span class="b-tabs__nav__text">\s*Referred (creators|users)\s*<\/span>)<\/a>/g, (all, attrs, cls, inner, kind) =>
      `<button disabled="disabled" title="${NOT_YET_TITLE}" data-oi-enable="" data-oi-pick="ref:${kind}" type="button" class="${cls}">${inner}</button>`,
    );
    html = html.replace(/(<a href="\/of-manager\/statistics\/statements\/referrals\/earnings"[^>]*?)>/, '$1 data-oi-pick="ref:earnings">');
    // The Referral earnings tab's own parts (its notice, table and "No data"), hidden while another tab shows.
    html = html.replace(/<div class="b-statistics-page-content__wrapper b-separate-section g-negative-sides-gaps g-sides-gaps pt-0 m-reset-bb mb-0">/, (m) => m.replace(/>$/, ' data-oi-ref-earnings="">'));
    html = html.replace(/<div class="b-separate-section g-negative-sides-gaps g-sides-gaps" data-oi-table="referrals"/, '$& data-oi-ref-earnings=""');
    html = html.replace(/(<div class="empty-message")(><span data-oi-empty="No data during selected period">)/, `${listTable("referred", REFERRED_HEAD, "b-table m-responsive m-default-table")}<div class="empty-message" data-oi-referred-empty="" style="display:none"><span>No data during selected period</span></div>$1 data-oi-ref-earnings=""$2`);
  }
  html = statValues(html, sub);
  // A sidebar row opens its chart in OF (not here): no pointer.
  html = html.replace(/(<div class="b-elements-determinant) g-pointer-cursor/g, "$1");
  html = html.replace(/<input\b((?:(?!disabled=)[^>])*\stype="(?:radio|search)")/g, `<input disabled="disabled" title="${NOT_YET_TITLE}"$1`);
  html = html.replace(/(<button\b[^>]*\sdisabled="disabled"[^>]*)>(\s*Request withdrawal\s*<\/button>)/g, `$1 title="${NOT_YET_TITLE}">$2`);
  return notYetWhere(html, (attrs) => !/\sdata-oi-(?:period|wired)=/.test(attrs));
}

// ---------------------------------------------------------------- bank

/** Bank's empty state (OF's empty line) where the capture shows the account's bank details or payout system. */
const bankEmpty = (text) =>
  `<div class="empty-message" style="padding:24px 16px;text-align:center;color:#8a96a3;font-size:14px"><span>${text}</span></div>`;

/**
 * Bank's pages show no captured example and write nothing (we never write bank details). The Relay reads no bank
 * account or selected payout system (only `/payouts/balances` and `/payouts/check-receive`, neither with bank details),
 * so "Your bank account data"'s endless loader and the selected payout system's example card give way to an empty state
 * saying they are managed on OnlyFans; the "account has been approved" box (no source) goes, Select payout system marks
 * no system as the selected one, and Payment Cards' wallet credits show a dash, its "add a new card" alert goes and its
 * latest transactions say they are not available. Every control is disabled with the tooltip: the payout systems'
 * CONTINUE and radios, Payment Cards' card, wallet and tab controls, the Billing Support form and the DAC7 form, and
 * the `#` links (OF pages we do not mirror). OF's links to mirrored pages (Back, Billing Support, Other payout options,
 * Settings) stay.
 */
function bankPage(html) {
  // Payment Cards: no example figure, account alert or claim of no payments.
  html = dropEl(html, "alert-danger");
  html = html.replace(/(<span\b[^>]*\sat-attr="balance_info"[^>]*>)[^<]*/, `$1${DASH}`);
  html = html.replace(/(<div\b[^>]*\sclass="empty-message\b[^"]*"[^>]*>(?:<svg\b[\s\S]*?<\/svg>)?<span\b[^>]*>)[^<]*/g, `$1${NOT_YET_TITLE}`);
  html = dropEl(html, "b-banking-approved");
  html = dropEl(html, "b-posts_preloader", () => bankEmpty("Your bank details are managed on OnlyFans"));
  html = dropEl(html, "m-banking-types"); // DAC7's capture has OF's bank icon there instead of a card
  html = html.replace(/(<h2\b[^>]*>\s*SELECTED PAYOUT SYSTEM\s*<\/h2>)(?:<svg\b[\s\S]*?<\/svg>)?/, `$1${bankEmpty("Your payout system is managed on OnlyFans")}`);
  // Select payout system: OF's list of systems stays, none marked as the account's.
  html = html.replace(/(<div class="b-payout-type) m-active"/g, '$1"').replace(/(<div class="b-payout-type__title">[^<]*)<svg\b[\s\S]*?<\/svg>/g, "$1");
  // Disabled: the payout systems' CONTINUE (a label for its radio), every field, and the `#` links.
  html = html.replace(/<label for="payout_type__[^"]*"([^>]*\sclass="g-btn\b[^"]*"[^>]*)>([\s\S]*?)<\/label>/g, `<button type="button" disabled="disabled" title="${NOT_YET_TITLE}"$1>$2</button>`);
  html = html.replace(/<(input|textarea)\b((?:(?!disabled=)[^>])*)>/g, (all, tag, attrs) =>
    /\stype="hidden"/.test(attrs) ? all : `<${tag} disabled="disabled" title="${NOT_YET_TITLE}"${attrs}>`,
  );
  html = html.replace(/<a href="#"((?:(?!aria-disabled=)[^>])*)>/g, `<a href="#" aria-disabled="true" title="${NOT_YET_TITLE}"$1>`);
  html = html.replace(/(<button\b[^>]*\sdisabled="disabled"(?:(?!title=)[^>])*)>(\s*Send\b)/g, `$1 title="${NOT_YET_TITLE}">$2`);
  return notYetWhere(html, () => true);
}

// ---------------------------------------------------------------- release forms

/**
 * Release forms (OF's ReleaseFormsStorage, /my/release-forms): one example row stays, the template ofMirrorReleaseForms
 * copies per row of the tab's Relay list (it hides the example). The Tag user and Release form tabs, the filter's Search
 * and Sort, the sidebar search and a row's More are ofMirrorReleaseForms'. Mentions opens Notifications' Tags tab (the
 * same OF list, /release-forms/mentions), its count gone. Create new release form (OF's release-form-links, whose body
 * no capture shows) and Create new invitation link (the page's own chunk, and so its request, was never captured) are
 * disabled with the tooltip.
 */
function releaseFormsPage(html) {
  html = html.replace(/<span class="b-tabs__nav__count">[^<]*<\/span>/g, "");
  html = html.replace(/<button\b([^>]*\sclass="b-tabs__nav__link\b[^>]*)>(<span\b[^>]*>\s*Mentions\s*<\/span>)<\/button>/, (_, attrs, inner) => `${asLink(attrs, `${MANAGER}/notifications/tags`)}>${inner}</a>`);
  let rows = 0;
  html = html.replace(/<label\b[^>]*\sclass="b-rows-lists__item\b[^"]*\bm-release-item\b[^"]*"[\s\S]*?<\/label>/g, (row) => (rows++ ? "" : row));
  return notYetWhere(html, (_, text) => text === "Create new release form" || text === "Create new invitation link");
}

// ---------------------------------------------------------------- my profile

/** Every `<div class="… cls …">` of `html` (outermost first found, last replaced first) replaced by keep(element). */
function eachEl(html, cls, keep) {
  for (const m of roots(html, cls).reverse()) {
    const el = element(html, m.index, "div");
    html = html.slice(0, m.index) + keep(el) + html.slice(m.index + el.length);
  }
  return html;
}
const asLink = (attrs, href) => `<a${attrs.replace(/\s(type|disabled|role|tabindex)="[^"]*"/g, "")} href="${href}" target="_top"`;
const PROFILE_EMPTY = (scope) => `<div${scope} class="empty-message" data-oi-empty=""><span>No posts yet</span></div>`;

/**
 * My profile (its wall, its Media tab and the header's More menu page): no example stays. Every count (the compact
 * header's Photos, Videos, Likes and Fans, the Posts and Media tabs, the label and media type tabs) goes: ofMirrorFeeds'
 * applyProfile shows the Creator's own from /users/me. Photos and Videos open the Media tab and Fans the Fans list, as
 * OF's do. The wall and the Media grid keep one example row, hidden, as the template ofMirrorFeeds copies per post (Home
 * and All bookmarks borrow the wall's), with OF's "No posts yet" under it; the label tabs keep "All" and one hidden
 * tab (applyProfile copies it per label; a label's posts have no Relay route, so it is disabled with the tooltip); the
 * Media tab's All, Photo and Video filter the grid in place (data-oi-wired: ofMirrorProfile). The sidebar's Recent strip
 * keeps one hidden tile and is hidden until applyRecent shows the Creator's latest media. The story strip: Story
 * archive lists the archived stories in place (ofMirrorProfile; its picture is the Creator's, as OF's, not a fan's), Go live opens Go live, and
 * Create highlight (no Relay write) is disabled. The price lines (no bundle count) hide until ofMirrorIdentity shows the
 * Creator's price, the promotion cards become hidden templates (applyPromotions) and the ad banner goes. Copy link to
 * profile, More info and Spotify's collapse work in place; the status menu, the wall's search, compact view and sort, the
 * sidebar search, Sign in with Spotify and each post's Labels and bookmark are disabled with the tooltip, and the post
 * row's `#` links (date, media) are marked so. A post's "N Likes" and "N Comments" open its likers and its comments
 * (ofMirrorHome); its Post statistics is disabled with the tooltip too, and ofMirrorHome enables it (OF's popup) for a
 * role with Statistics on a Relay with the route.
 */
function profilePage(html, sub) {
  const off = `title="${NOT_YET_TITLE}"`;
  // The compact header's counts, and its Photos, Videos and Fans.
  html = html.replace(/(<span\b[^>]*\sclass="b-profile__sections__count g-semibold">)[^<]*/g, "$1");
  html = html.replace(/<button\b([^>]*\saria-label="(Photos|Videos|Fans)"[^>]*)>([\s\S]*?)<\/button>/g, (_, attrs, what, inner) =>
    `${asLink(attrs, what === "Fans" ? `${MANAGER}/collections/user-lists/subscribers/active` : `${MANAGER}/profile/media`)}>${inner}</a>`,
  );
  // The Media tab's header More opens the same menu page as the wall's.
  if (sub === "media") html = html.replace(/(<div\b[^>]*\sclass="b-compact-header__settings\b[^"]*"[^>]*>)(?!<a class="of-state-link")/, `$1<a class="of-state-link" href="${MANAGER}/profile/state-more-menu" target="_top" aria-label="Toggle"></a>`);
  // The Posts and Media tabs: their words only.
  html = html.replace(/(<span\b[^>]*\sclass="b-tabs__nav__text">)\s*\d[\d.,KkMm]*\s+(posts|Media)\s*</g, (_, open, w) => `${open} ${w === "posts" ? "Posts" : "Media"} <`);
  // The wall's label tabs: "All", and one hidden tab, disabled.
  html = html.replace(/(<ul\b[^>]*>)((?:<li class="b-tabs__nav__item">(?:(?!<\/li>)[\s\S])*?at-attr="profile_label"[\s\S]*?<\/li>)+)(<\/ul>)/, (_, open, items, close) => {
    const li = items.match(/<li class="b-tabs__nav__item">[\s\S]*?<\/li>/g);
    const label = (item) => item.replace(/(at-attr="profile_label">)[^<]*/, "$1 All ");
    const tpl = li[1] ?? li[0];
    const hidden = tpl
      .replace(/^<li class="b-tabs__nav__item"/, '<li class="b-tabs__nav__item" data-oi-template="label" style="display:none"')
      .replace(/<button\b((?:(?!disabled=)[^>])*)>/, `<button disabled="disabled" ${off}$1>`)
      .replace(/(at-attr="profile_label">)[^<]*/, "$1");
    return `${open}${label(li[0])}${hidden}${close}`;
  });
  // The Media tab's type tabs: All, Photo, Video, in place.
  html = html.replace(/<a\b([^>]*)\shref="[^"]*"([^>]*\sclass="b-tabs__nav__link\b[^"]*"[^>]*)>(<span\b[^>]*\sclass="b-tabs__nav__text">)\s*(All|Photo|Video)\s+\d+\s*(<\/span>)<\/a>/g, (_, pre, attrs, open, kind, close) =>
    `<button type="button" data-oi-wired="" data-oi-media-tab="${kind.toLowerCase()}"${pre}${attrs.replace(/\s(target|tabindex)="[^"]*"/g, "")}>${open} ${kind} ${close}</button>`,
  );
  // The wall's search, compact view and sort; the sidebar's search; the status menu.
  html = notYetWhere(html, (attrs) =>
    /\saria-label="(?:Compact view|Sort)"/.test(attrs) ||
    /\sclass="g-btn m-gray m-with-round-hover m-icon m-icon-only m-default-color m-sm-size"/.test(attrs) ||
    /\sclass="btn dropdown-toggle m-user-status"/.test(attrs),
  );
  html = html.replace(/<input\b((?:(?!disabled=)[^>])*\sname="feed-search-input"[^>]*)>/, `<input disabled="disabled" ${off}$1>`);
  html = html.replace(/(<button\b[^>]*\saria-label="Search")(?![^>]*\stitle=)/, `$1 ${off}`);
  // Copy link to profile (the header's icon button), More info, Spotify's collapse: in place.
  html = html.replace(/<button\b([^>]*\saria-label="Copy link to profile")/g, '<button data-oi-wired="" data-oi-copy-link=""$1');
  html = html.replace(/<button\b([^>]*\sclass="link-trunc\b)/g, '<button data-oi-wired="" data-oi-bio-toggle=""$1');
  html = html.replace(/<button\b([^>]*\sclass="b-section-title m-row m-collapsible\b)/g, '<button data-oi-wired="" data-oi-collapse=""$1');
  html = html.replace(/<a href="#"([^>]*\sclass="g-btn m-rounded m-block m-spotify\b)/g, `<a href="#" aria-disabled="true" ${off}$1`);
  // The story strip.
  html = html.replace(/(<button\b[^>]*\sclass="b-story-item m-story-archive\b[^"]*"[^>]*)>((?:(?!<\/button>)[\s\S])*?<div\b[^>]*\sclass="g-avatar__placeholder m-text-avatar) of-fan("[^>]*>)[^<]*</, '$1 data-oi-wired="" data-oi-story-archive="" aria-expanded="false">$2$3 Y <');
  html = storyTile(html, "Go live", tileLink(`${MANAGER}/streaming`));
  html = storyTile(html, "Create highlight", tileNotYet);
  // The right column (and its copy in the wall's column on a phone).
  html = html.replace(
    /<div class="b-menu-list__subtext">(<span class="b-amount-price m-num">[^<]*<\/span> per month)(?:, \d+ subscription bundles?)?<\/div>/g,
    '<div class="b-menu-list__subtext" data-oi-price="" style="display:none">$1</div>',
  );
  html = eachEl(html, "b-offer-wrapper", (el) => {
    const open = el.match(/^<div\b[^>]*>/)[0].replace(/>$/, ' style="display:none">');
    const card = roots(el, "b-offer-join")[0];
    const tpl = card ? element(el, card.index, "div").replace(/^<div\b([^>]*)>/, '<div$1 data-oi-template="promotion" style="display:none">') : "";
    return `${open}${tpl}</div>`;
  });
  html = eachEl(html, "banner_place", () => "");
  // The Recent strip: one hidden tile; the section shows once applyRecent has tiles.
  html = html.replace(/(<div\b[^>]*\sclass="b-profile__content__item")((?:(?!<div\b[^>]*\sclass="b-profile__content__item")[\s\S])*?class="b-photos\b[^"]*\bm-recent-list\b)/, '$1 data-oi-recent="" style="display:none"$2');
  html = eachEl(html, "m-recent-list", (strip) => {
    const tiles = [...strip.matchAll(/<a\b[^>]*\sat-attr="photo_item"[\s\S]*?<\/a>/g)];
    if (!tiles.length) return strip;
    const tile = tiles[0][0].replace(/^<a\b/, '<a style="display:none"');
    const last = tiles.at(-1);
    return strip.slice(0, tiles[0].index) + tile + strip.slice(last.index + last[0].length);
  });
  // The wall or the Media grid: one hidden example row (the template), OF's empty message under it.
  html = eachEl(html, "user_posts", (posts) => {
    const open = posts.match(/^<div\b[^>]*>/)[0];
    const scope = open.match(/\sdata-v-[0-9a-f]+=""/)?.[0] ?? "";
    posts = dropEl(posts, "infinite-loading-container");
    posts = dropEl(posts, "vue-recycle-scroller__item-wrapper", (wrapper) => {
      const wopen = wrapper.match(/^<div\b[^>]*>/)[0].replace(/\sstyle="[^"]*"/, ' style="min-height: 0px;"');
      const view = elements(wrapper, "div", "vue-recycle-scroller__item-view")[0]?.el;
      if (!view) return `${wopen}</div>`;
      let row = view.replace(/^(<div\b[^>]*?)\sstyle="[^"]*"/, '$1 style="display:none"');
      // The media grid's row: one tile.
      const tiles = [...row.matchAll(/<a\b[^>]*\sat-attr="photo_item"[\s\S]*?<\/a>/g)];
      if (tiles.length > 1) row = row.slice(0, tiles[1].index) + row.slice(tiles.at(-1).index + tiles.at(-1)[0].length);
      return `${wopen}${row}</div>`;
    });
    return posts.replace(/<\/div>$/, `${PROFILE_EMPTY(scope)}</div>`);
  });
  // The post row's own-post tools with no Relay route (Post statistics: ofMirrorHome enables it for a role with
  // Statistics), and its `#` links.
  html = notYetWhere(html, (attrs, text) => /\sat-attr="add_to_list"/.test(attrs) || text === "Post statistics");
  html = html.replace(/(<div\b[^>]*\sclass="b-post__tools__item m-last"[^>]*><div\b[^>]*>)<button\b((?:(?!disabled=)[^>])*)>/g, `$1<button disabled="disabled" ${off}$2>`);
  return html.replace(/<a\b([^>]*)\shref="#"([^>]*)>/g, (all, pre, post) =>
    /\saria-disabled=/.test(pre + post) || !/\s(?:class="b-post__date"|at-attr="photo_item"|class="g-btn m-flat m-link\b)/.test(pre + post) ? all : `<a${pre} href="#" aria-disabled="true" ${off}${post}>`,
  );
}

/**
 * My profile's More menu page: Statistics opens Statistics' Overview (as OF's); Copy link to profile copies in place (ofMirrorProfile); QR
 * code (its dialog was never captured) is disabled with the tooltip.
 */
function profileMenu(html) {
  return html.replace(/(<div\b[^>]*\srole="menuitem"[^>]*)>(<a class="of-state-link" href="[^"]*"[^>]*><\/a>)\s*(statistics|QR code|Copy link to profile)\s*</gi, (_, open, link, text) => {
    const t = text.toLowerCase();
    if (t === "statistics") return `${open}>${link.replace(/href="[^"]*"/, `href="${MANAGER}/statistics/${SECTION_INDEX.statistics}"`)} ${text} <`;
    if (t === "qr code") return `${open} aria-disabled="true" title="${NOT_YET_TITLE}" style="opacity:.5;cursor:default"> ${text} <`;
    return `${open} data-oi-wired="" data-oi-copy-link=""> ${text} <`;
  });
}

// ---------------------------------------------------------------- settings

/**
 * The settings switches and radios a binder saves (ofMirrorSettings' SETTINGS_MAP, the welcome switch) and Dark mode
 * (useOfTheme), and the ones OF keeps in the browser only (ofMirrorQr, ofMirrorLanguage): QR code's two switches and
 * Display > Language's radios.
 */
const SETTINGS_TOGGLE = /^(?:setting_|toggle_|allow(?:Subscribers|Friends|Nobody)$|autoMessage$|hasWatermark(?:Photo|Video)$|show_subscribes_offers$|dark_mode_switcher$|add_(?:url|avatar)_to_qrcode$|lang-[a-z]{2}$)/;
/** The settings text fields a binder saves: Edit profile's (ofMirrorWrites), the subscription price (ofMirrorSettingsWrites). */
const SETTINGS_FIELDS = /^(?:input-(?:name|location|website|wishlist)|priceInput_\d+)$/;
const SUBSCRIPTION_PAGE = /^subscription(?:\/|$)/;
/** OF settings pages Inflowwww turns off: no page, no menu row (their URLs redirect, app/next.config.ts). */
const SETTINGS_OFF = ["security/reserved_usernames"];
/** Their menu rows' OF titles (the row's link is already gone when settingsPart runs). */
const SETTINGS_OFF_ROWS = ["Reserved usernames"];
/** The promotion campaign and bundle dialogs and the free trial link dialog (ofMirrorOffers works them). */
const OFFER_MODALS = /^subscription\/(?:promotion-campaign\/modal-[12]|trial-links\/modal-1)$/;
/** OF's default sort radios (build 202610091632): TrialFilter's create_date/desc, CampaignFilter's created_date/desc. */
const SORT_DEFAULTS = new Set(["filter-create_date", "trial-order-desc", "campaign-field-created_date", "campaign-sort-desc"]);
/** OF settings' empty line where the capture shows the account's own data we have no source for. */
const settingsEmpty = (text) =>
  `<div class="empty-message" data-oi-empty="" style="padding:24px 16px;text-align:center;color:#8a96a3;font-size:14px"><span>${text}</span></div>`;
/**
 * One part (`body`: the page, `modal`: its open dialog) of an OF settings page: no captured example and no control
 * that neither works nor is disabled. What a binder writes stays: the toggles (SETTINGS_TOGGLE), Edit profile's fields
 * and Save, Watermarks' form, the subscription price form, the tracking link modal's name and Create Link, and the
 * Subscription rows' Delete, Remove, Copy link to profile and Copy link (ofMirrorSubscription).
 * So do the promotion, bundle and free trial link dialogs (OFFER_MODALS: every field, tab, dropdown and submit), Stop
 * promotion, and the free trial links' Sort, "Shared with you" and share (ofMirrorOffers). So do what OF keeps in the
 * browser: QR code's switches and Download, Display's language radios. Everything else with no Relay write (credentials,
 * 2-step, sessions, social links, stream keys, block lists, the tracking links' sort and share) is disabled with the
 * tooltip, its dropdowns too (their State page openers go); OF's `#` links are marked disabled.
 * Examples: the account email (ofMirrorSettings shows the model's own), the login sessions (it lists the model's own), the price line's bundle count (the price shows once
 * ofMirrorIdentity has the Creator's own), the promotion, bundle, tracking and free trial link rows (one hidden template
 * each, filled from the Relay by ofMirrorSubscription) and the "Offer claimed" fans.
 */
function settingsPart(html, sub, part) {
  const off = `disabled="disabled" title="${NOT_YET_TITLE}"`;
  const subscription = SUBSCRIPTION_PAGE.test(sub);
  const watermarks = sub.startsWith("security/watermarks");
  const trackingModal = part === "modal" && sub === "subscription/tracking-links/modal-1";
  // The promotion, bundle and free trial link dialogs: every field, tab, dropdown and submit works (ofMirrorOffers).
  const offerModal = part === "modal" && OFFER_MODALS.test(sub);
  if (part === "body") {
    // The account email: the capture's is scrubbed to a dash; ofMirrorSettings shows the model's own (users/me), read-only.
    const email = /[\w.%+-]+@[a-z][\w-]*(?:\.[\w-]+)*\.[a-z]{2,}/i;
    html = html.replace(/<div>E-mail \S+@\S+ is verified<\/div>/g, "");
    html = html.replace(/(<div class="b-menu-list__subtext">)([^<]*)(<\/div>)/g, (all, a, t, b) => (email.test(t) ? `${a}${DASH.trim()}${b}` : all));
    html = html.replace(/(Email: <b>)[^<]*@[^<]*(<\/b>)/g, `$1${DASH.trim()}$2`);
    // A price line shows only the Creator's own price (ofMirrorIdentity un-hides it), with no bundle count.
    html = html.replace(
      /<div class="b-menu-list__subtext">(<span class="b-amount-price m-num">[^<]*<\/span> per month)(?:, \d+ subscription bundles?)?<\/div>/g,
      '<div class="b-menu-list__subtext" data-oi-price="" style="display:none">$1</div>',
    );
    // A turned-off page's menu row (SETTINGS_OFF), and its list wrapper once empty.
    for (const title of SETTINGS_OFF_ROWS) {
      html = html.replace(new RegExp(`<a\\b[^>]*>(?:(?!</a>)[\\s\\S])*?<div class="b-menu-list__text"> ${title} </div>[\\s\\S]*?</a>`, "g"), "");
    }
    html = html.replace(/<div class="b-menu-list m-without-bold-line">(?:<!---->)*<\/div>/g, "");
    if (watermarks) {
      // The capture's position goes (its text, value and the open list's selected option): ofMirrorSettings shows the
      // model's own (users/me watermarkPosition), so none shows while that loads or after it fails, and Save sends none.
      html = html.replace(/(<div class="v-select__selection v-select__selection--comma">)[^<]*(<\/div>)/g, "$1$2");
      html = html.replace(/(<input type="hidden" name="watermark_position" value=")[^"]*"/g, '$1"');
      html = html.replace(/\saria-activedescendant="[^"]*"/g, "");
      html = html.replace(/(<div\b[^>]*\s)aria-selected="true"([^>]*\sclass=")([^"]*)"/g, (_, a, b, cls) =>
        `${a}aria-selected="false"${b}${cls.split(" ").filter((c) => !["primary--text", "v-list-item--active", "v-list-item--highlighted"].includes(c)).join(" ")}"`,
      );
    }
    if (sub === "account/sessions") {
      // The captured rows go (IPs, places, devices); ofMirrorSettings draws the model's own from GET /sessions.
      html = eachEl(html, "m-session-row", () => "");
    }
    if (subscription) {
      // Promotions: the first example card, hidden, is ofMirrorSubscription's template; bundles and link rows likewise.
      html = eachEl(html, "m-start-campaign", (el) => {
        const cards = roots(el, "b-offer-join").filter((m) => !/\bm-only-start-btn\b/.test(m[1]));
        if (!cards.length) return el;
        const tpl = element(el, cards[0].index, "div").replace(/^<div\b([^>]*)>/, '<div$1 data-oi-template="promotion-row" style="display:none">');
        const last = element(el, cards.at(-1).index, "div");
        return el.slice(0, cards[0].index) + tpl + el.slice(cards.at(-1).index + last.length);
      });
      html = eachEl(html, "list-offers", (el) => {
        const rows = roots(el, "m-bundle-row");
        if (!rows.length) return el;
        const tpl = element(el, rows[0].index, "div").replace(/^<div\b([^>]*)>/, '<div$1 data-oi-template="bundle-row" style="display:none">');
        const last = element(el, rows.at(-1).index, "div");
        return el.slice(0, rows[0].index) + tpl + el.slice(rows.at(-1).index + last.length);
      });
      const rows = roots(html, "m-trial-link-block");
      if (rows.length) {
        const tpl = element(html, rows[0].index, "div").replace(/^<div\b([^>]*)>/, '<div$1 data-oi-template="link-row" style="display:none">');
        const last = element(html, rows.at(-1).index, "div");
        html = html.slice(0, rows[0].index) + tpl + html.slice(rows.at(-1).index + last.length);
      }
      // "Share link's statistics with another user": a free trial link's opens ofMirrorOffers' share dialog; a tracking
      // link's has no Relay route.
      html = sub.startsWith("subscription/trial-links")
        ? html.replace(/<div class="b-hint-offer g-pointer-cursor">/g, '<div class="b-hint-offer g-pointer-cursor" data-oi-wired="" data-oi-share="">')
        : html.replace(/<div class="b-hint-offer g-pointer-cursor">/g, `<div class="b-hint-offer" aria-disabled="true" title="${NOT_YET_TITLE}" style="opacity:.5">`);
      // The current tab ("Your links") is no control; Sort's menu (its State page) has nothing to sort here.
      html = html.replace(/<button\b([^>]*\sclass="b-tabs__nav__link\b[^"]*\bm-current\b[^"]*")>([\s\S]*?)<\/button>/g, (_, attrs, inner) => `<div${attrs.replace(/\s(type|tabindex)="[^"]*"/g, "")}>${inner}</div>`);
    }
  } else if (sub === "subscription/promotion-campaign/modal-3") {
    // "Offer claimed": the Relay reads no promotion's claimers.
    html = eachEl(html, "b-viewer-row", () => "");
    html = html.replace(/(<div\b[^>]*\sclass="b-rows-lists\b[^"]*"[^>]*>)/, `$1${settingsEmpty("Nothing found")}`);
  }
  // State page openers of controls disabled below: Sort, and the promotion and bundle dialogs' dropdowns.
  html = html.replace(/<a class="of-state-link" href="[^"]*\/state-(?:kebab|promo-dropdowns-\d+|bundle-[a-z-]+)"[^>]*><\/a>/g, "");
  // Dropdowns (Vuetify selects) other than Watermarks' position: disabled.
  if (!watermarks && !offerModal) {
    html = html.replace(/<div class="v-input ([^"]*\bv-select\b[^"]*)">/g, `<div class="v-input $1 v-input--is-disabled" title="${NOT_YET_TITLE}">`);
    html = html.replace(/<div role="button" aria-haspopup="listbox"/g, '<div aria-haspopup="listbox" aria-disabled="true"');
  }
  // The sort menus' checked radios: a capture keeps a radio's checked state as a property only, so it shows none.
  html = html.replace(/<input\b([^>]*)>/g, (all, attrs) => {
    const id = attrs.match(/\sid="([^"]*)"/)?.[1];
    return id && SORT_DEFAULTS.has(id) && !/\schecked=/.test(attrs) ? `<input checked="checked"${attrs}>` : all;
  });
  html = html.replace(/<input\b((?:(?!\sdisabled=)[^>])*)>/g, (all, attrs) => {
    const type = attrs.match(/\stype="([^"]*)"/)?.[1] ?? "text";
    const id = attrs.match(/\sid="([^"]*)"/)?.[1] ?? "";
    if (type === "hidden" || watermarks || offerModal) return all;
    if (type === "checkbox" || type === "radio" ? SETTINGS_TOGGLE.test(id) : SETTINGS_FIELDS.test(id)) return all;
    if (trackingModal && /\sname="name"/.test(attrs)) return all;
    return `<input ${off}${attrs}>`;
  });
  if (!offerModal) html = html.replace(/<textarea\b((?:(?!\sdisabled=)[^>])*)>/g, `<textarea ${off}$1>`);
  const keep = (attrs, text) => {
    if (trackingModal) return /\stype="submit"/.test(attrs);
    if (offerModal) return true;
    if (part !== "body") return false;
    if ((text === "Save" || text === "Cancel") && (sub.startsWith("profile") || watermarks || subscription)) return true;
    // QR code's Download (ofMirrorQr draws OF's code and saves it as OF's PNG).
    if (sub === "qrcode" && text === "Download QR Code") return true;
    if (!subscription) return false;
    if (["Delete", "Remove", "Copy link to profile", "Retry", "Stop promotion"].includes(text) || /\saria-label="Delete"/.test(attrs)) return true;
    // The free trial links' Sort menu and "Shared with you" tab (ofMirrorOffers).
    if (sub.startsWith("subscription/trial-links") && (/\saria-label="Sort"/.test(attrs) || text === "Shared with you")) return true;
    return text === "Copy link"; // a tracking or free trial link's (ofMirrorSubscription disables an ended one's)
  };
  html = notYetWhere(html, (attrs, text) => !keep(attrs, text));
  // Edit profile's header and avatar icons (camera, remove) stay disabled but look as OF's: without .g-btn[disabled]'s .4.
  if (sub.startsWith("profile")) {
    html = html.replace(new RegExp(`<button ${off}((?:(?!\\sstyle=)[^>])*\\sclass="[^"]*\\bg-btn m-icon\\b[^"]*\\bm-light\\b[^"]*"[^>]*)>`, "g"), `<button ${off} style="opacity:1"$1>`);
  }
  return html.replace(/<a\b((?:(?!aria-disabled=)[^>])*\shref="#"(?:(?!aria-disabled=)[^>])*)>/g, `<a aria-disabled="true" title="${NOT_YET_TITLE}"$1>`);
}

// ---------------------------------------------------------------- left nav

// OF's left nav (header.l-header: the menu column and its avatar/More drawer), built once by
// buildNav and put on every page by navFor; NAV_MENU: the page with the drawer open, if one is built.
let NAV = "";
let NAV_MENU = null;
const MENU_HREF = "#of-nav-menu"; // stands for the drawer's link until navFor knows the page

// The nav's captured counts -> the "who am I" field ofMirrorIdentity fills them from (by the item's data-name).
const NAV_BADGES = { Notifications: "notificationsCount", Chats: "chatMessagesCount" };
const NAV_USER_DATA = { Subscribers: "subscribersCount", Subscribes: "subscribesCount" };

/** The drawer's account switcher, the chevron by the name (OF's "m-dark no-padding" dropdown toggle). */
const SWITCHER = /\sclass="btn dropdown-toggle m-dark no-padding\b/;
/** The drawer's icons ofMirrorIdentity draws that the capture lacks: a payout-ready model's bank row, the switcher's tick. */
const NAV_ICONS = "#icon-bank #icon-done";

/**
 * The left nav from a page's document, rewritten and scrubbed; its avatar and More buttons as links to the drawer.
 * No captured count stays: the Notifications and Chats badges are hidden and empty, the drawer's Fans and Following
 * counts read "—", each marked data-oi-count with its `/users/me` field (ofMirrorIdentity shows the Creator's own).
 * The account switcher (the chevron by the name, [data-oi-switcher]) stays enabled: ofMirrorIdentity's bindSwitcher
 * lists the agency's models in it and marks it data-oi-wired. The drawer's remaining buttons (Dark mode, the language menu, Log out) have no Relay route or are
 * OnlyFans' own session, and its links with no OF Manager page (Release forms, Help and support) go nowhere: disabled
 * with the tooltip (our theme switch is settings > Display's "Dark mode").
 */
function buildNav(rel, raw, ids) {
  const at = raw.search(/<header\b[^>]*\sclass="l-header\b/);
  if (at < 0) return "";
  const pii = ids.flatMap((id) => [id.username, id.name]).filter(Boolean);
  // "settings": like there, every avatar in the nav is the model's own. Scrubbed here, since a page
  // another account owns (--allow-multiple-accounts) does not scrub this account's identity.
  const nav = scrub(scrubData(rewrite(rel, element(raw, at, "header"), pii, true), "settings", pii), ids)
    .replace(/(<a\b[^>]*\sclass="[^"]*?)\s+m-current\b/g, "$1")
    .replace(/<button\b([^>]*\sclass="[^"]*\bl-header__menu__item\b[^"]*"[^>]*)>([\s\S]*?)<\/button>/g, (_, attrs, inner) => `<a${attrs.replace(/\stype="[^"]*"/, "")} href="${MENU_HREF}" target="_top">${inner}</a>`)
    .replace(/(<a\b[^>]*\sdata-name="(\w+)"[^>]*>)((?:(?!<\/a>)[\s\S])*?)<span([^>]*\sclass="(l-header__menu__item__count|l-sidebar__user-data__item__count)")>[^<]*<\/span>/g, (all, open, name, mid, attrs, cls) => {
      const field = (cls === "l-header__menu__item__count" ? NAV_BADGES : NAV_USER_DATA)[name];
      if (!field) return all;
      const blank = cls === "l-header__menu__item__count" ? ' style="display:none"></span>' : `>${DASH}</span>`;
      return `${open}${mid}<span${attrs} data-oi-count="${field}"${blank}`;
    });
  const sidebarDead = deadLinkOff(nav, (attrs) => /\sclass="l-sidebar__menu__item\b/.test(attrs));
  return notYetWhere(sidebarDead, (attrs) => !/\sclass="l-sidebar__btn-close\b/.test(attrs) && !SWITCHER.test(attrs)).replace(
    /(<div\b[^>]*\sclass="b-dropdown-wrapper\b[^"]*")(>\s*<button\b)((?:(?!disabled=)[^>])*\sclass="btn dropdown-toggle m-dark no-padding\b[^"]*")/,
    '$1 data-oi-switcher=""$2 aria-label="Switch model"$3',
  );
}

/** The nav for one page: its section's item marked current (as OF does: none for new post, bank, settings), the drawer open on its own page. */
function navFor({ section }, live) {
  const here = hrefOf(section, "");
  let nav = NAV.replace(/<a\b[^>]*>/g, (tag) => {
    const cls = tag.match(/\sclass="([^"]*)"/)?.[1] || "";
    if (!hasClass(cls, "l-header__menu__item") || hasClass(cls, "m-create-post") || !tag.includes(` href="${here}"`)) return tag;
    return tag.replace(/\sclass="([^"]*)"/, ' class="$1 m-current"');
  });
  nav = nav.replaceAll(`href="${MENU_HREF}"`, `href="${live?.drawer ? live.back : NAV_MENU || "#"}"`);
  if (live?.drawer) {
    nav = nav
      .replace(/(<div\b[^>]*)\sinert="inert"([^>]*\sclass="l-sidebar")/, "$1$2")
      .replace(/<button\b([^>]*\sclass="l-sidebar__btn-close\b[^"]*"[^>]*)>([\s\S]*?)<\/button>/, (_, attrs, inner) => `<a${attrs.replace(/\stype="[^"]*"/, "")} href="${live.back}" target="_top" aria-label="Close">${inner}</a>`)
      .replace(/<div\b([^>]*\sclass="l-sidebar__overlay")><\/div>/, `<a$1 href="${live.back}" target="_top" aria-label="Close"></a>`);
  }
  return nav;
}

/**
 * One standalone page. `raw` is the dump's document for the slug (its <head>
 * styles, clip-path svg and icon sprite); `live`, if given, supplies the
 * <main> instead, plus modal nodes (`portal`), a title, and buttons to turn
 * into links to modal pages (`triggers`: [{ labels, href }]) and controls to
 * turn into links to state pages (`controls`: [{ cls, part, index, href }]).
 * A state page has `state`: { ...control that is open, back }.
 */
function buildPage(rel, raw, ids, live, route) {
  const strict = route.section !== "settings";
  const owner = strict && detectIdentity(raw).username?.toLowerCase();
  pageFans = new Set(owner ? [...MODEL_HANDLES].filter((h) => h !== owner) : []);
  // Those accounts are scrubbed as fans there (Fan N, @fanN), not to the model's placeholders.
  const asFan = new Set([...pageFans].flatMap((h) => [h, ...(accountNames.get(h) || [])]));
  try {
    return buildPageAs(rel, raw, ids.filter((id) => !asFan.has(id.username?.toLowerCase() ?? id.name)), live, route, strict);
  } finally {
    pageFans = new Set();
  }
}

function buildPageAs(rel, raw, ids, live, route, strict) {
  const src = live?.app ?? raw;
  const bodyAt = raw.search(/<body\b/i);
  const mainAt = src.search(/<main id="content"/);
  const main = mainAt >= 0 ? element(src, mainAt, "main") : null;
  if (bodyAt < 0 || !main) return null;
  const portal = live?.portal || "";
  const head = raw.slice(0, bodyAt);
  let htmlTag = (raw.match(/<html\b[^>]*>/i)?.[0] || '<html lang="en">').replace(/\sclass="[^"]*"/, "");
  if (live?.drawer) htmlTag = htmlTag.replace(/>$/, ' class="m-sidebar-visible">');
  const nav = navFor(route, live);
  let title = raw.match(/<title>([^<]*)<\/title>/)?.[1].trim() || "Settings — OnlyFans";
  // The dump's shells are titled just "OnlyFans"; the live page's header has the name.
  const h1 = main.match(/<h1 [^>]*class="g-page-title m-scroll-top"[^>]*>(?:<span[^>]*>)?\s*([^<]+?)\s*</)?.[1];
  if (live?.title) title = `${live.title} — OnlyFans`;
  else if (live && title === "OnlyFans" && h1) title = `${h1} — OnlyFans`;
  if (live?.state) title = title.replace(/( — OnlyFans)?$/, `: ${live.state.label}$1`);
  // OF's 2-3 column layout: whether the page has the right column.
  const container = src.match(/<div class="(container m-main-container[^"]*)"/)?.[1] || "container m-main-container";
  const clipAt = raw.indexOf("<svg", bodyAt);
  const clip = clipAt >= 0 && clipAt < raw.indexOf('id="app"') ? element(raw, clipAt, "svg") : "";
  const spriteSrc = src.includes('<svg id="of-svg-sprite"') ? src : raw;
  const spriteAt = spriteSrc.indexOf('<svg id="of-svg-sprite"');
  const extraIcons = EXTRA_ICONS.filter(([on]) => on(route)).map(([, icons]) => ` ${icons}`).join("");
  const sprite = spriteAt >= 0 ? usedSymbols(element(spriteSrc, spriteAt, "svg"), nav + main + portal + NAV_ICONS + extraIcons) : "";
  const pii = ids.flatMap((id) => [id.username, id.name]).filter(Boolean);
  // A stylesheet the dump does not have is dropped (its link would point at the page itself).
  const styles = rewrite(rel, headStyles(head), pii, strict).replace(/<link\b[^>]*\shref="#"[^>]*>\n?/g, "");
  let body = backButtons(route, rewrite(rel, main, pii, strict));
  body = scrubData(body, route.section, pii, /(^|\/)list$/.test(route.sub));
  body = rowLinks(body);
  body = storyStrip(body, route.section);
  if (route.section === "home") body = homePage(body);
  if (route.section === "new-post") body = newPostPage(body);
  if (route.section === "streaming") body = streamingPage(body, route.sub);
  if (route.section === "notifications") body = notificationsPage(body);
  if (route.section === "messages") body = messagesPage(body, route.sub);
  if (route.section === "vault") body = vaultPage(body, route.sub);
  if (route.section === "queue") body = queuePage(body, route.sub);
  if (route.section === "collections") body = collectionsPage(body, route.sub);
  if (route.section === "statements") body = statementsPage(body, route.sub);
  if (route.section === "statistics") body = statisticsPage(body, route.sub);
  if (route.section === "bank") body = bankPage(body);
  if (route.section === "profile") body = profilePage(body, route.sub);
  if (route.section === "release-forms") body = releaseFormsPage(body);
  // Record video and Record voice: disabled on Home; New post's open ofMirrorPost's "not supported here" popup.
  if (route.section === "home") body = notYet(body);
  if (strict) title = titleFor(body, route); // from the scrubbed h1: a list page's name is the list's
  for (const t of live?.triggers || []) body = linkButton(body, t.labels, t.href);
  // Modals and menus hold the same fan data as the page.
  const portalHtml = portal ? rowLinks(scrubData(rewrite(rel, portal, pii, strict), route.section, pii)) : "";
  let modal = portal ? openModal(portalHtml, live.back) : "";
  const offerState = route.section === "new-post" && Object.hasOwn(OFFER_STATES, route.sub) ? OFFER_STATES[route.sub] : null;
  if (offerState) modal = settingsPart(modal, offerState.modal, "modal");
  else if (route.section === "new-post" || (route.section === "home" && HOME_DIALOGS.some((d) => route.sub === `state-${d}`))) modal = composerDialog(modal, route.section);
  if (route.section === "home" && route.sub === "state-feed-tabs-edit") modal = pinToHome(modal);
  if (route.section === "messages" && route.sub === "state-folders") modal = pinToChat(modal);
  // A chat's dialogs: the vault dialog as the composers' (its folders link to the dialog), and the schedule dialog's
  // Save for Later disabled (the Relay has no saved-for-later body for one chat).
  if (route.section === "messages" && (route.sub === "chat/state-vault" || route.sub === "send/state-vault")) modal = composerDialog(modal, `messages/${route.sub.split("/")[0]}`);
  if (route.section === "messages") modal = notYetWhere(modal, (attrs) => /\sclass="[^"]*\bcustom-datepicker-button-save-later\b/.test(attrs));
  if (live?.state) ({ body, modal } = openState(body, modal, live.state));
  else if (live?.popup) ({ body, modal } = closePopup(body, modal, live.back));
  if (route.section === "messages" && route.sub === "state-filter-dropdown") [body, modal] = [chatSortMenu(body), chatSortMenu(modal)];
  if (route.section === "messages" && route.sub === "chat/state-header-menu") [body, modal] = [chatHeaderTools(body, route.sub), chatHeaderTools(modal, route.sub)];
  if (route.section === "profile" && live?.state) [body, modal] = [profileMenu(body), profileMenu(modal)];
  for (const l of live?.links || []) {
    // An optional link (the composer's tools on a State page) is the page's own control, never one in its dialog.
    const linked = [body, l.optional ? null : modal].map((h) => (h === null ? null : linkEl(h, l.spec, l.href)));
    if (linked[0] === null && linked[1] === null && !l.optional) fail(`${route.section}/${route.sub}: no control "${l.spec}" to link`);
    body = linked[0] ?? body;
    modal = linked[1] ?? modal;
  }
  for (const c of live?.controls || []) {
    if (c.part === "body") body = overControl(body, c.cls, c.index, c.href);
    else modal = overControl(modal, c.cls, c.index, c.href);
  }
  if (route.section === "queue") body = queueTabs(body);
  if (route.section === "settings") [body, modal] = [settingsPart(body, route.sub, "body"), settingsPart(modal, route.sub, "modal")];
  body = nav + body; // after the links and controls: their specs and indices are the page's own
  // OF's full-screen pages (Go live) mark <body>: black, and its left nav hidden.
  const bodyClass = (raw.slice(bodyAt).match(/^<body\b[^>]*\sclass="([^"]*)"/i)?.[1] || "").split(/\s+/).filter((c) => BODY_CLASSES.has(c));
  const doc = `<!DOCTYPE html>
${htmlTag}<head>
<meta charset="utf-8">
<meta name="robots" content="noindex">
${THEME_BOOT}
<title>${title}</title>
${styles}
${extraStyles(styles, nav + main + portal + (route.section === "queue" ? SFL_CARD_SCOPES : route.section === "statistics" ? body : ""))}
${OVERRIDES}
</head><body data-app="true"${bodyClass.length ? ` class="${bodyClass.join(" ")}"` : ""}>${clip}<div id="app" class="main-wrapper"><div class="${container}">${body}</div></div>${modal}${sprite}</body></html>
`;
  return { title: scrub(title.replace(/\s+—\s+OnlyFans$/, ""), ids), html: scrub(doc, ids) };
}

// Title words that are not just the humanised route: a section, a route segment, a whole page's name.
const SECTION_LABELS = { bank: "Bank" };
const SEGMENT_LABELS = { send: "New message", "sendlist-following": "Following", dac7: "DAC7 form" };
const PAGE_NAMES = { "bank/dac7/edit": "DAC7 form" };
// An h1 that only names its section says nothing about the page (OF's <title> is just "OnlyFans").
const SECTION_H1 = /^(?:home|new (?:post|message)|notifications|messages|vault|queue|collections|statements|statistics|banking(?: edit)?)\b/i;

/** A page title outside settings: "<Section>: <page or tab path> › <state>"; a page whose own h1 names it (Billing Support) uses that for the page. */
function titleFor(main, { section, sub, label }) {
  const h1 = main.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/)?.[1].replace(/<svg\b[\s\S]*?<\/svg>|<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  const path = (sub || SECTION_INDEX[section] || "").split("/").filter((s) => s && !s.startsWith("state-")); // label: a state page's
  const name = PAGE_NAMES[`${section}/${path.join("/")}`] || (path.length && h1 && !SECTION_H1.test(h1) ? h1 : null);
  const parts = [...(name ? [name] : path.map((s) => SEGMENT_LABELS[s] || sentence(s.replace(/[_-]/g, " ")))), ...(label ? [label] : [])];
  const head = SECTION_LABELS[section] || sentence(section.replace(/-/g, " "));
  return parts.length ? `${head}: ${parts.join(" › ")}` : head;
}

// ---------------------------------------------------------------- assets

function copyAssets() {
  const queue = [...assets];
  const missing = [];
  const skipped = [];
  for (let i = 0; i < queue.length; i++) {
    const file = queue[i];
    const src = path.join(DUMP, STATIC_PREFIX, file);
    const dst = path.join(STAGE, "static", file);
    // NotoColorEmoji.ttf alone is ~10 MB; a font that size only matters for
    // glyphs these pages do not show, so it is left out (it 404s if ever asked for).
    if (fs.statSync(src).size > MAX_ASSET_BYTES) {
      skipped.push(file);
      continue;
    }
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    if (!file.endsWith(".css")) continue;
    const css = fs.readFileSync(src, "utf8");
    for (const m of css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) {
      const ref = m[1].split(/[?#]/)[0];
      if (!ref || /^(data:|#|[a-z]+:\/\/|\/)/i.test(ref)) continue;
      const rel = path.posix.normalize(path.posix.join(path.posix.dirname(file), ref));
      if (queue.includes(rel)) continue;
      if (fs.existsSync(path.join(DUMP, STATIC_PREFIX, rel))) queue.push(rel);
      else missing.push(rel);
    }
  }
  return { files: queue.length - skipped.length, missing: [...new Set(missing)].sort(), skipped };
}

// ---------------------------------------------------------------- guard

const NOTICE = `# of-mirror

Contains OnlyFans' CSS, fonts and markup, mirrored for an internal look-alike of its creator UI (OF Manager).
Exclude this folder from any public export. Generated by scripts/of-mirror.mjs (see its header).
`;

// Numbers that are legitimately long or dotted: SVG geometry, base64 payloads, z-index, our own build-id paths.
const GEOMETRY = /\s(?:d|points|[\w:-]*[Tt]ransform)="[^"]*"|base64,[\w+/=]+|z-index:\s*\d+|\/of-mirror\/static\/[^"')\s]+/g;
// Where a page may link: nowhere, our routes, mirrored assets, inline data.
const SAFE_HREF = /^(?:#|\/of-manager(?:\/|$)|\/of-mirror\/static\/|data:)/;
// The only "@handles" a page may show: the placeholder, a fan placeholder, OF's own account.
const SAFE_HANDLE = new RegExp(`^(?:${esc(PLACEHOLDER.username)}|fan\\d+|onlyfans|mentions)$`, "i"); // "Tags and @mentions": settings' own words
// Attributes that hold no text a person reads.
const NON_TEXT_ATTR = /^(?:class|style|d|points|viewbox|transform|xmlns(?::\w+)?|src|href|xlink:href|data-v-\w+|width|height|x|y|cx|cy|r|fill|stroke)$/i;

/** A page's readable text: its text nodes, and the values of its other attributes; plus its links. */
function pageText(html) {
  const texts = [];
  const attrs = [];
  const hrefs = [];
  mapHtml(html, {
    text: (t) => (texts.push(t), t),
    tag(all) {
      for (const [, , name, value] of all.matchAll(ATTR)) {
        if (/^(?:href|xlink:href)$/i.test(name)) hrefs.push(value);
        else if (!NON_TEXT_ATTR.test(name)) attrs.push(value);
      }
      return all;
    },
  });
  return { texts, attrs, hrefs };
}

/** Every leak found in the files under `dir` (pages, CSS, SVG; whole files, attributes and inline styles included), and in `extra` ({ where, text }). */
function guard(dir, extra = []) {
  const needles = [...secrets].map((s) => s.toLowerCase());
  const pageNeedles = [...needles, ...[...fanSecrets].map((s) => s.toLowerCase())];
  // Scrubbed names and texts, matched as whole words (they can be short common words).
  const dataNeedles = [...dataSecrets].map((s) => s.toLowerCase());
  const wordChar = (c) => c !== undefined && /[\p{L}\p{N}_]/u.test(c);
  const wholeWord = (hay, n) => {
    for (let i = hay.indexOf(n); i >= 0; i = hay.indexOf(n, i + 1)) if (!wordChar(hay[i - 1]) && !wordChar(hay[i + n.length])) return true;
    return false;
  };
  // OF hosts allowed to survive, as text only: OF's support address, the placeholder profile link, two help-text URLs.
  const allowedOf = [
    new RegExp(esc(SUPPORT_EMAIL), "gi"),
    new RegExp(`https://onlyfans\\.com/${esc(PLACEHOLDER.username)}\\b`, "gi"),
    /https:\/\/onlyfans\.com\/my\/streaming\/chat\b/gi,
    /https:\/\/obs-settings\.onlyfans\.com\//gi,
    /\bOnlyFans\.com(?![\w/.-])/g, // the brand, as in "your OnlyFans.com profile"
  ];
  const leaks = [];
  const check = (where, raw, kind) => {
    const note = (what, m) => leaks.push(`${where}: ${what} ${m}`);
    const lower = raw.toLowerCase();
    for (const n of kind === "asset" ? needles : pageNeedles) if (lower.includes(n)) note("identity", n);
    const ofRest = allowedOf.reduce((s, re) => s.replace(re, ""), raw);
    for (const m of ofRest.matchAll(/[\w.-]*onlyfans(?:api)?\.com[^\s"'<>)]{0,40}/gi)) note("OF host", m[0]);
    for (const m of raw.matchAll(/@import\b|url\(\s*(?:&quot;|["'])?(?:https?:)?\/\/[^)]{0,60}/gi)) note("remote load", m[0]);
    if (where.endsWith(".css")) for (const m of raw.matchAll(/https?:\/\/(?!www\.w3\.org\/)[^\s"')]{0,60}/g)) note("remote URL", m[0]);
    for (const m of raw.matchAll(/[\w.%+-]+@[a-z][\w-]*(?:\.[\w-]+)*\.[a-z]{2,}/gi)) {
      if (m[0] !== PLACEHOLDER.email && m[0].toLowerCase() !== SUPPORT_EMAIL) note("email", m[0]);
    }
    const num = raw.replace(GEOMETRY, "");
    for (const m of num.matchAll(/(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])/g)) if (!SAFE_IPS.has(m[0])) note("ipv4", m[0]);
    for (const m of num.matchAll(/(?<![\w:])(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}(?![\w:])|(?<![\w:])(?:[0-9a-f]{1,4}:){1,7}:(?:[0-9a-f]{1,4})?(?![\w:])/gi)) {
      note("ipv6", m[0]);
    }
    for (const m of num.matchAll(/(?<![\d.])\d{9,}(?!\d|\.\d)/g)) note("digit run", m[0]);
    if (kind === "asset") return;
    const { texts, attrs, hrefs } = kind === "page" ? pageText(raw) : { texts: [raw], attrs: [], hrefs: [] };
    for (const h of hrefs) if (!SAFE_HREF.test(h)) note("link", h.slice(0, 80));
    const readable = [...texts, ...attrs].join("\n");
    for (const m of readable.matchAll(/(?:^|[^\w.%+-])@([\w.]*\w)/g)) if (!SAFE_HANDLE.test(m[1])) note("handle", `@${m[1]}`);
    for (const t of texts) for (const m of t.matchAll(MONEY)) if (!isFakeMoney(m[0])) note("amount", m[0]);
    const lowerReadable = readable.toLowerCase();
    for (const n of dataNeedles) if (wholeWord(lowerReadable, n)) note("scrubbed text", n.slice(0, 60));
  };
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(html|css|svg)$/.test(e.name)) check(path.relative(REPO, p), fs.readFileSync(p, "utf8"), p.endsWith(".html") ? "page" : "asset");
    }
  };
  walk(dir);
  for (const { where, text } of extra) check(where, text, "list");
  return leaks;
}

// ---------------------------------------------------------------- main

/** "https://onlyfans.com/my/settings/account/2fa" -> "account/2fa"; null if not a settings URL. */
function settingsSlug(url) {
  let p;
  try {
    p = new URL(url).pathname.replace(/\/+$/, "");
  } catch {
    return null;
  }
  if (p !== "/my/settings" && !p.startsWith("/my/settings/")) return null;
  const slug = p.slice("/my/settings".length).replace(/^\//, "");
  if (SETTINGS_OFF.some((off) => slug === off || slug.startsWith(`${off}/`))) return null;
  return /^[\w-]+(\/[\w-]+)*$|^$/.test(slug) ? slug : null;
}

const sentence = (s) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

// Page-title suffix per state capture name (the captures' own names are working labels).
const STATE_LABELS = {
  "bio-focus": "Bio editor focused",
  "country-picker": "Country picker",
  options: "Position options",
  "bundle-discount-dropdown": "Bundle discount",
  "bundle-duration-dropdown": "Bundle duration",
  "promo-dropdowns-0": "Offer limit",
  "promo-dropdowns-1": "Offer expiration",
  "promo-dropdowns-2": "Free trial duration",
  kebab: "Sort menu",
};

/** The live capture: [{ slug, base, label?, app, portal }]; label is set for modal captures. */
function loadLive() {
  if (!LIVE) return [];
  const manifest = JSON.parse(fs.readFileSync(path.join(LIVE, "manifest.json"), "utf8"));
  if (!Array.isArray(manifest)) fail(`${LIVE}/manifest.json is not a list`);
  const out = [];
  for (const e of manifest) {
    if (typeof e?.file !== "string" || !/^[\w.-]+\.html$/.test(e.file)) continue;
    const base = settingsSlug(e.final_url || e.url);
    const file = path.join(LIVE, e.file);
    if (base === null || !fs.existsSync(file)) continue;
    const text = fs.readFileSync(file, "utf8");
    const cut = text.indexOf(PORTALS);
    const n = e.file.match(/__modal-(\d+)\.html$/)?.[1];
    const label = n && typeof e.modal === "string" ? e.modal : undefined;
    const slug = label ? `${base}/modal-${n}` : settingsSlug(e.url);
    if (slug === null) continue;
    out.push({ slug, base, label, app: cut < 0 ? text : text.slice(0, cut), portal: label && cut >= 0 ? text.slice(cut + PORTALS.length) : "" });
  }
  return out;
}

/** The state captures: [{ slug, base, name, app (#app), portal (the body nodes after it) }]. */
function loadStates() {
  if (!LIVE2) return [];
  const manifest = JSON.parse(fs.readFileSync(path.join(LIVE2, "manifest.json"), "utf8"));
  const list = Array.isArray(manifest) ? manifest : manifest?.files;
  if (!Array.isArray(list)) fail(`${LIVE2}/manifest.json has no file list`);
  const out = [];
  for (const e of list) {
    const name = typeof e?.file === "string" && /^[\w.-]+$/.test(e.file) ? e.file.match(/__state-([\w-]+)\.html$/)?.[1] : undefined;
    const base = settingsSlug(e?.url);
    const file = name && path.join(LIVE2, e.file);
    if (!base || !file || !fs.existsSync(file)) continue;
    const text = fs.readFileSync(file, "utf8");
    const at = text.search(/<div id="app"/);
    const app = at >= 0 ? element(text, at, "div") : null;
    if (!app) fail(`state capture ${e.file} has no #app`);
    out.push({ slug: `${base}/state-${name}`, base, name, app, portal: text.slice(at + app.length).replace(/<\/body>[\s\S]*$/i, "") });
  }
  return out;
}

/** --live3/--live4: [{ slug, state, rel, query, raw }], one full document per capture of a page outside settings; state: the name of a "__state-" capture. */
const loadPages = () => [LIVE3, LIVE4].filter(Boolean).flatMap(loadPagesDir);

function loadPagesDir(dir) {
  const manifest = path.join(dir, "manifest.json");
  const entries = fs.existsSync(manifest)
    ? JSON.parse(fs.readFileSync(manifest, "utf8"))
    : fs
        .readdirSync(dir)
        .filter((f) => /^[\w.-]+\.meta\.json$/.test(f))
        .sort()
        .map((f) => ({ ...JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")), file: f.replace(/\.meta\.json$/, ".html") }));
  if (!Array.isArray(entries)) fail(`${dir}: manifest.json is not a list`);
  const out = [];
  for (const e of entries) {
    const name = e?.file ?? (typeof e?.slug === "string" ? `${e.slug}.html` : null);
    if (typeof name !== "string" || !/^[\w.-]+\.html$/.test(name)) continue;
    const slug = name.replace(/\.html$/, "");
    const state = slug.match(/__state-([\w-]+)$/)?.[1];
    if (!state && e.state && e.state !== "default") continue;
    let url;
    try {
      url = new URL(e.final_url || e.url);
    } catch {
      continue;
    }
    const file = path.join(dir, name);
    if (url.hostname !== "onlyfans.com" || !fs.existsSync(file)) continue;
    const rel = `onlyfans.com${url.pathname.replace(/\/+$/, "") || "/index"}.html`;
    out.push({ slug, state, rel, query: url.search, raw: fs.readFileSync(file, "utf8") });
  }
  return out;
}

/** The route of a --live3 capture: its URL with the query if a route takes it ("/my/chats/send?list=users"), else without. */
const routeOfCapture = (c) => {
  const p = c.rel.replace(/\.html$/, "");
  return routeOfPath(ofPathOf(p + c.query)) || routeOfPath(ofPathOf(p));
};

/** The body-level nodes of a state capture that matter: the modals that are open, and the menus (as popper nodes). */
function openPortal(tail) {
  let modals = "";
  for (let m; (m = /<div\b[^>]*\sid="\w+___BV_modal_outer_"[^>]*>/.exec(tail)); ) {
    const node = element(tail, m.index, "div");
    if (/class="modal [^"]*\bshow\b/.test(node)) modals += node;
    tail = tail.slice(0, m.index) + tail.slice(m.index + node.length);
  }
  let menus = "";
  for (let m; (m = /<div\b[^>]*\sclass="[^"]*\bv-menu__content\b[^"]*"[^>]*>/.exec(tail)); ) {
    const node = element(tail, m.index, "div");
    menus += node;
    tail = tail.slice(0, m.index) + tail.slice(m.index + node.length);
  }
  return modals + menus;
}

/** --check: the guard's pattern checks over the committed output (no inputs, so no identity or scrubbed-text needles), and the page list against the page files. */
function check() {
  const list = fs.readFileSync(LIST, "utf8");
  const listed = new Set();
  const problems = [];
  let section = null;
  let index = null;
  const subs = [];
  const endSection = () => {
    if (section !== null && !subs.includes(index)) problems.push(`${section}: index "${index}" is not a listed page`);
  };
  for (const line of list.split("\n")) {
    const s = line.match(/^  ("(?:[^"\\]|\\.)*"): \{$/);
    if (s) {
      endSection();
      section = JSON.parse(s[1]);
      index = null;
      subs.length = 0;
    }
    const i = line.match(/^    index: ("(?:[^"\\]|\\.)*"),$/);
    if (i) index = JSON.parse(i[1]);
    const p = line.match(/^      ("(?:[^"\\]|\\.)*"): "(?:[^"\\]|\\.)*",$/);
    if (p && section !== null) {
      subs.push(JSON.parse(p[1]));
      listed.add(pageFile(section, subs.at(-1)));
    }
  }
  endSection();
  const files = new Set();
  const walk = (d) => {
    for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
      if (e.isDirectory()) walk(path.join(d, e.name));
      else if (e.name.endsWith(".html")) files.add(path.relative(path.join(OUT, "pages"), path.join(d, e.name)).split(path.sep).join("/"));
    }
  };
  walk(path.join(OUT, "pages"));
  for (const f of listed) if (!files.has(f)) problems.push(`${path.relative(REPO, LIST)}: ${f} is listed but has no file`);
  for (const f of files) if (!listed.has(f)) problems.push(`app/public/of-mirror/pages/${f}: not listed in ${path.relative(REPO, LIST)}`);
  problems.push(...guard(OUT, [{ where: path.relative(REPO, LIST), text: list }]));
  const build = fs.readFileSync(BUILD_TS, "utf8").match(/OF_MIRROR_BUILD = "([^"]+)"/)?.[1];
  if (!build || !fs.existsSync(path.join(OUT, "static", build))) problems.push(`${path.relative(REPO, BUILD_TS)}: OF_MIRROR_BUILD ${build ?? "(none)"} is not a dir under app/public/of-mirror/static`);
  if (problems.length) fail(`check failed (${problems.length}):\n  ${problems.join("\n  ")}`);
  console.log(`of-mirror --check: ${files.size} pages and ${listed.size} list entries match; no leak found`);
}

function main() {
  const raws = listPages().map((rel) => ({ rel, raw: fs.readFileSync(path.join(DUMP, rel), "utf8") }));
  if (!raws.some((r) => routeOfPath(ofPathOf(r.rel)).section === "settings")) fail(`no onlyfans.com/my/settings pages under ${DUMP}`);
  const live = loadLive();
  const states = loadStates();
  const captured = loadPages();
  // Identity is detected per input page: exactly one username may appear across all of them.
  const usernames = new Map(); // username -> the inputs it was seen in
  const names = new Set();
  const identify = (what, t) => {
    const { username, name } = detectIdentity(t);
    if (username) usernames.set(username, (usernames.get(username) || new Set()).add(what));
    if (name) names.add(name);
    if (username && name) accountNames.set(username.toLowerCase(), (accountNames.get(username.toLowerCase()) || new Set()).add(name));
    collectSecrets(t);
  };
  for (const [what, texts] of [
    ["dump", raws.map((r) => r.raw)],
    ["live capture", live.map((l) => l.app)],
    ["state captures", states.map((st) => st.app)],
    ["page captures", captured.map((c) => c.raw)],
  ]) {
    for (const t of texts) identify(what, t);
  }
  for (const l of [...live, ...states]) collectSecrets(l.portal);
  if (usernames.size === 0) fail("could not detect the logged-in username in any input; refusing to write unscrubbed pages");
  if (usernames.size > 1 && !ALLOW_MANY) {
    fail(`expected one account across the inputs, found ${usernames.size}: ${[...usernames].map(([u, w]) => `${u} (${[...w].join(", ")})`).join("; ")}. Re-capture from one account, or pass --allow-multiple-accounts (every one is scrubbed).`);
  }
  for (const u of usernames.keys()) MODEL_HANDLES.add(u.toLowerCase());
  // The creator's own profile page, "<username>.html" in the dump.
  for (const u of [...usernames.keys()].sort()) {
    const rel = `onlyfans.com/${u}.html`;
    if (!fs.existsSync(path.join(DUMP, rel))) continue;
    raws.push({ rel, raw: fs.readFileSync(path.join(DUMP, rel), "utf8") });
    identify("dump", raws.at(-1).raw);
  }
  for (const s of [...usernames.keys(), ...names]) if (s.length < 4) fail(`detected identity "${s}" is under 4 chars, too short to check for in the output`);
  const ids = [...usernames.keys()].map((username) => ({ username })).concat([...names].map((name) => ({ name })));
  for (const s of [...usernames.keys(), ...names, ...[...names].map((n) => n.split(/\s+/)[0])]) if (s.length >= 4) secrets.add(s);

  // Per page, the input to build from: one that rendered over an empty shell
  // (settings/notifications.html is a shell, settings/notifications/index.html
  // the real page); outside settings the larger of two rendered ones (my/chats.html
  // vs my/chats/index.html, which has the chat list), and a --live3 capture over both.
  const rendered = (raw) => raw.includes('<main id="content"');
  const dump = new Map(); // pageKey -> { rel, raw, section, sub }
  for (const r of raws) {
    const route = routeOfPath(ofPathOf(r.rel));
    if (route.section === "settings" && route.sub === "") continue; // the dump's settings root is an older copy of its index (profile)
    const key = pageKey(route.section, route.sub);
    const cur = dump.get(key);
    const better = !cur || (!rendered(cur.raw) && rendered(r.raw)) || (route.section !== "settings" && rendered(r.raw) && r.raw.length > cur.raw.length);
    if (better) dump.set(key, { ...r, ...route });
  }
  for (const c of captured) {
    const route = c.state ? null : routeOfCapture(c);
    if (!route || route.section === "settings" || !rendered(c.raw)) continue;
    const key = pageKey(route.section, route.sub);
    // A capture of #app alone (no <body>) takes its <head> (the stylesheets) from the dump's page for the same route.
    if (!/<body\b/i.test(c.raw)) {
      const d = dump.get(key);
      const at = d?.raw.search(/<body\b/i) ?? -1;
      if (at < 0 || d.rel !== c.rel) fail(`page capture ${c.slug} is #app only and the dump has no page for ${c.rel} to take its <head> from`);
      let head = d.raw.slice(0, at);
      const css = LIVE_CSS[ofPathOf(c.rel)];
      if (css) {
        const link = /<link\b[^>]*\shref="([^"]*\.css)"[^>]*>\n?/gi;
        const build = [...head.matchAll(link)].map((m) => m[1].match(/\/f\/([^/]+)\/[^/]+\.css$/)?.[1]).find(Boolean);
        if (!build) fail(`${d.rel}: no build dir in its stylesheet links`);
        const first = head.search(link);
        head = head.replace(link, "");
        head = head.slice(0, first) + css.map((f) => `<link rel="stylesheet" href="https://${STATIC_PREFIX}${build}/${f}.css">\n`).join("") + head.slice(first);
      }
      c.raw = `${head}${d.raw.slice(at, d.raw.indexOf(">", at) + 1)}${c.raw}</body></html>`;
    }
    dump.set(key, { ...c, ...route });
  }
  // A chat's pinned messages: OF draws them in its chat page (the PinnedMessages route), so that page is built from the
  // chat's capture (messagesPage's pinnedPage), not the dump's empty one.
  const chatPage = dump.get(pageKey("messages", "chat"));
  if (chatPage) dump.set(pageKey("messages", "chat/pinned"), { ...chatPage, sub: "chat/pinned" });
  // A list's Posts tab: no list's own was captured rendered; built from the list page and Following's Posts tab.
  const listPage = dump.get(pageKey("collections", "user-lists/list"));
  const followingPosts = dump.get(pageKey("collections", "user-lists/subscriptions/posts"));
  if (listPage && followingPosts && rendered(listPage.raw) && rendered(followingPosts.raw))
    dump.set(pageKey("collections", "user-lists/list/posts"), { ...listPage, sub: "user-lists/list/posts", raw: listPostsRaw(listPage, followingPosts) });
  // Outside settings a shell is left out (links to it become "#"); settings needs a live page for it (checked below).
  let shells = 0;
  for (const [key, d] of dump) {
    if (d.section !== "settings" && !rendered(d.raw)) {
      dump.delete(key);
      shells++;
    }
  }

  // --live3 state captures that get a page; those with nothing to open them from are listed in the summary.
  const pageStates = [];
  const unreached = [];
  for (const c of captured.filter((c) => c.state)) {
    const route = routeOfCapture(c);
    // Profile captures are named after the real username; look them up by route so no handle lives in source.
    const rule = PAGE_STATES[route?.section === "profile" ? c.slug.replace(/^[^_]+(?:_[^_]+)*?(?=__state-)/, "profile") : c.slug];
    if (rule?.skip) continue;
    const base = route && route.section !== "settings" && dump.get(pageKey(route.section, route.sub));
    const at = c.raw.search(/<div id="app"/);
    const app = at >= 0 ? element(c.raw, at, "div") : null;
    if (!rule || !base || !app) {
      unreached.push(c.slug);
      continue;
    }
    const portal = openPortal(c.raw.slice(at + app.length));
    const ctl = findControl(mainOf(app), portal);
    const drawer = /<html\b[^>]*\sclass="[^"]*\bm-sidebar-visible\b/.test(c.raw); // the left nav's drawer open: navFor links it
    if (ctl && ctl.part !== "body") fail(`state capture ${c.slug}: an open control inside a modal is not handled`);
    if (!ctl && !rule.open && !drawer) {
      unreached.push(c.slug);
      continue;
    }
    const sub = [route.sub, `state-${c.state}`].filter(Boolean).join("/");
    const label = STATE_LABELS[c.state] || sentence(c.state.replace(/-/g, " "));
    pageStates.push({ ...c, ...rule, section: route.section, baseSub: route.sub, sub, base, app, portal, ctl, label, drawer });
  }
  // Home's composer is New post's: its dialogs and panels open over Home (home/state-<name>), each Home's own page with
  // New post's captured dialog: the modal (vault, tag, expiration, target), the schedule popup in place of Home's empty
  // one, or the composer's panel (poll and quiz above the text, the format panel atop the toolbar) put into Home's.
  const homeBase = dump.get(pageKey("home", ""));
  /** The first `cls` element of New post's `from` put first into `into`'s first `parent`, which loses its `drop` classes. */
  const homePanel = (into, from, cls, parent, drop = []) => {
    const [panel, slot] = [roots(from, cls)[0], roots(into, parent)[0]];
    if (!panel || !slot) fail(`Home's or New post's capture has no .${panel ? parent : cls} for Home's ${cls} panel`);
    const open = slot[0].replace(/\sclass="([^"]*)"/, (_, c) => ` class="${c.split(/\s+/).filter((x) => x && !drop.includes(x)).join(" ")}"`);
    return into.slice(0, slot.index) + open + element(from, panel.index, "div") + into.slice(slot.index + slot[0].length);
  };
  for (const st of pageStates.filter((p) => p.section === "new-post" && p.baseSub === "" && HOME_DIALOGS.includes(p.state))) {
    const at = homeBase?.raw.search(/<div id="app"/) ?? -1;
    if (at < 0) fail(`no #app in Home's input for its ${st.state} dialog`);
    let app = element(homeBase.raw, at, "div");
    if (st.state === "schedule") {
      const swap = (html) => {
        const m = roots(html, "vdatetime")[0];
        return m ? { at: m.index, el: element(html, m.index, "div") } : null;
      };
      const [mine, theirs] = [swap(app), swap(st.app)];
      if (!mine || !theirs) fail("Home's or New post's capture has no schedule popup (.vdatetime)");
      app = app.slice(0, mine.at) + theirs.el + app.slice(mine.at + mine.el.length);
    }
    if (st.state === "poll" || st.state === "quiz") app = homePanel(app, st.app, "b-make-post__voting-wrapper", "b-make-post__main-wrapper", ["m-placeholder-height"]);
    if (st.state === "format-text") app = homePanel(app, st.app, "js-text-editor-toolbar", "b-make-post__sticky-panel");
    pageStates.push({ ...st, slug: `home__state-${st.state}`, rel: homeBase.rel, raw: homeBase.raw, section: "home", sub: `state-${st.state}`, base: homeBase, app });
  }
  // A chat's "Tag other creators" opens New post's tag dialog over the chat (messages/chat/state-tag-people), and its
  // composer holds New post's Format text panel.
  const chatBase = dump.get(pageKey("messages", "chat"));
  const tagState = pageStates.find((p) => p.section === "new-post" && p.baseSub === "" && p.state === "tag-people");
  if (chatBase && tagState) {
    const at = chatBase.raw.search(/<div id="app"/);
    if (at < 0) fail("no #app in the chat page's input for its tag dialog");
    pageStates.push({ ...tagState, slug: "messages__chat__state-tag-people", rel: chatBase.rel, raw: chatBase.raw, section: "messages", baseSub: "chat", sub: "chat/state-tag-people", base: chatBase, app: element(chatBase.raw, at, "div") });
  }
  const formatState = pageStates.find((p) => p.section === "new-post" && p.baseSub === "" && p.state === "format-text");
  FORMAT_TOOLBAR = formatState ? formatToolbar(formatState.app) : "";
  if (chatBase && !FORMAT_TOOLBAR) fail("New post's Format text capture has no .js-text-editor-toolbar for the chat composer");
  const priceState = postPriceState(pageStates, dump.get(pageKey("new-post", "")));
  if (priceState) pageStates.push(priceState);
  pageStates.push(...sendStates(pageStates, dump.get(pageKey("messages", "send"))));
  pageStates.push(...offerStates(live.filter((l) => l.label), dump.get(pageKey("new-post", ""))));
  const foldersState = chatFoldersState(pageStates, dump.get(pageKey("messages", "")));
  if (foldersState) pageStates.push(foldersState);
  for (const st of pageStates) {
    const from = st.from ? pageStates.find((p) => p.section === st.section && p.baseSub === st.baseSub && p.state === st.from) : null;
    if (st.from && !from) fail(`state capture ${st.slug} opens from "${st.from}", which has no page`);
    st.fromSub = from ? from.sub : st.baseSub;
  }
  /** What a page links to its states: the controls that open the ones that start from it. */
  const statesFrom = (section, sub) => {
    const here = pageStates.filter((st) => st.section === section && st.fromSub === sub);
    return {
      // (New post's offer dialogs have no `open`: newPostPage links their tiles.)
      links: here.filter((st) => !st.ctl && !st.drawer && st.open).map((st) => ({ spec: st.open, href: hrefOf(section, st.sub) })),
      controls: here.filter((st) => st.ctl).map(({ ctl, sub }) => ({ ...ctl, href: hrefOf(section, sub) })),
    };
  };

  // Settings captures, keyed by settings slug.
  const settings = (slug) => dump.get(pageKey("settings", slug));
  const liveBySlug = new Map(live.filter((l) => !l.label).map((l) => [l.slug, l]));
  const modals = live.filter((l) => l.label && settings(l.base));
  const href = (slug) => hrefOf("settings", slug);

  // States with an open control; `from` is the page whose control opens it: the
  // modal capture holding the same modal as the state's, else the base page.
  const openStates = [];
  for (const st of states) {
    if (!settings(st.base)) continue;
    const ctl = findControl(mainOf(st.app), st.portal);
    if (!ctl) continue; // a bare modal: same as its modal page
    let from = st.base;
    if (ctl.part === "modal") {
      const id = st.portal.match(/\sid="(\w+)___BV_modal_outer_"/)?.[1];
      const m = id && modals.find((m) => m.base === st.base && m.portal.includes(`id="${id}___BV_modal_outer_"`));
      if (!m) fail(`state capture ${st.slug} is in a modal that has no modal capture`);
      from = m.slug;
    } else if (!liveBySlug.has(st.base)) fail(`state capture ${st.slug} has no live page for ${st.base} to link from`);
    openStates.push({ ...st, ...ctl, from, label: STATE_LABELS[st.name] || sentence(st.name.replace(/-/g, " ")) });
  }
  const controlsOf = (slug) => openStates.filter((st) => st.from === slug).map(({ cls, part, index, slug }) => ({ cls, part, index, href: href(slug) }));

  // Every page this run writes, before any is built: links to anything else become "#".
  for (const key of dump.keys()) BUILT.add(key);
  for (const x of [...modals, ...openStates]) BUILT.add(pageKey("settings", x.slug));
  for (const st of pageStates) BUILT.add(pageKey(st.section, st.sub));
  // The left nav, from the home page's input (BUILT is known, so its links resolve); its drawer opens on the state that shows it.
  const drawer = pageStates.find((st) => st.drawer);
  NAV_MENU = drawer ? hrefOf(drawer.section, drawer.sub) : null;
  const home = dump.get(pageKey("home", ""));
  NAV = home ? buildNav(home.rel, home.raw, ids) : "";
  if (!NAV) fail("no OF left nav (header.l-header) in the home page's input");
  for (const section of SECTIONS) if (!BUILT.has(pageKey(section, ""))) fail(`no page for the ${section} section's root (${hrefOf(section, "")}) in the inputs`);

  fs.rmSync(STAGE, { recursive: true, force: true });
  fs.mkdirSync(path.join(STAGE, "pages"), { recursive: true });

  const pages = new Map(); // pageKey -> { section, sub, title }
  const write = (section, sub, page) => {
    pages.set(pageKey(section, sub), { section, sub: sub || SECTION_INDEX[section] || "", title: page.title });
    const dst = path.join(STAGE, "pages", pageFile(section, sub));
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, page.html);
  };
  let fromLive = 0;
  for (const [, { rel, raw, section, sub }] of [...dump].sort(([a], [b]) => a.localeCompare(b))) {
    const route = { section, sub };
    if (section !== "settings") {
      const states = statesFrom(section, sub);
      write(section, sub, buildPage(rel, raw, ids, states.links.length || states.controls.length ? states : null, route));
      continue;
    }
    const l = liveBySlug.get(sub);
    const triggers = l
      ? modals.filter((m) => m.base === l.base).map((m) => ({ labels: [m.label, ...(m.label.match(/\((\d+)\)$/)?.slice(1) || [])], href: href(m.slug) }))
      : [];
    const livePage = l && buildPage(rel, raw, ids, { ...l, triggers, controls: controlsOf(sub) }, route);
    const page = livePage || buildPage(rel, raw, ids, null, route);
    if (!page) fail(`settings/${sub} is only an empty SPA shell in the inputs; capture it logged in`);
    if (livePage) fromLive++;
    write(section, sub, page);
  }
  for (const m of modals) {
    const { rel, raw } = settings(m.base);
    // "PROMOTION CAMPAIGN FOR" (a plan picker follows it) -> "Promotion campaign".
    const heading = m.portal.match(/class="modal-title[^"]*">\s*([^<]+?)\s*</)?.[1].replace(/\s+for$/i, "");
    const title = sentence(heading || m.label.replace(/\s*\(\d+\)$/, ""));
    const page = buildPage(rel, raw, ids, { ...m, title, back: href(m.base), controls: controlsOf(m.slug) }, { section: "settings", sub: m.slug });
    if (page) write("settings", m.slug, page);
    else fail(`modal capture ${m.slug} has no <main>`);
  }
  for (const st of openStates) {
    const { rel, raw } = settings(st.base);
    const state = { cls: st.cls, part: st.part, index: st.index, label: st.label, back: href(st.from) };
    const page = buildPage(rel, raw, ids, { ...st, back: href(st.base), state }, { section: "settings", sub: st.slug });
    if (page) write("settings", st.slug, page);
    else fail(`state capture ${st.slug} has no <main>`);
  }

  for (const st of pageStates) {
    const back = hrefOf(st.section, st.fromSub);
    const { links, controls } = statesFrom(st.section, st.sub);
    if (st.close) links.push({ spec: st.close, href: back });
    // New post's State pages (and Home's composer ones) keep the composer's tools working: each opens its own State page.
    if (st.section === "new-post" || (st.section === "home" && HOME_DIALOGS.includes(st.state))) {
      const here = hrefOf(st.section, st.sub);
      for (const l of statesFrom(st.section, st.baseSub).links) if (l.href !== here && !links.some((k) => k.spec === l.spec)) links.push({ ...l, optional: true });
    }
    const state = st.ctl && { ...st.ctl, label: st.label, back };
    const live = { app: st.app, portal: st.portal, back, links, controls, state, popup: !st.ctl, drawer: st.drawer };
    const page = buildPage(st.rel, st.raw, ids, live, { section: st.section, sub: st.sub, label: st.label });
    if (page) write(st.section, st.sub, page);
    else fail(`state capture ${st.slug} has no <main>`);
  }

  const { files: assetCount, missing, skipped } = copyAssets();

  fs.writeFileSync(path.join(STAGE, "NOTICE.md"), NOTICE);
  const bySection = new Map(SECTIONS.map((s) => [s, []]));
  for (const p of [...pages.values()].sort((a, b) => a.sub.localeCompare(b.sub))) bySection.get(p.section).push(p);
  const list = `// Generated by scripts/of-mirror.mjs; do not edit by hand.
// OF Manager sections and their mirrored pages, by sub path, with the OF page
// title: public/of-mirror/pages/<section>/<sub, or "index" for "">.html.
// \`index\` is the sub the section root (/of-manager/<section>) shows.

export interface OfMirrorSection {
  index: string;
  pages: Record<string, string>;
}

export const OF_MIRROR_SECTIONS: Record<string, OfMirrorSection> = {
${[...bySection]
  .map(
    ([section, ps]) => `  ${JSON.stringify(section)}: {
    index: ${JSON.stringify(SECTION_INDEX[section] || "")},
    pages: {
${ps.map((p) => `      ${JSON.stringify(p.sub)}: ${JSON.stringify(p.title)},`).join("\n")}
    },
  },`,
  )
  .join("\n")}
};
`;
  const leaks = guard(STAGE, [{ where: path.relative(REPO, LIST), text: list }]);
  if (leaks.length) fail(`leak guard failed, nothing written:\n  ${leaks.join("\n  ")}`);

  fs.rmSync(OUT, { recursive: true, force: true });
  fs.renameSync(STAGE, OUT);
  fs.writeFileSync(LIST, list);
  // The newest build the pages link (a build id starts with its yyyymmddhhmm, so it sorts by date).
  const build = [...new Set([...assets].map((a) => a.split("/")[0]))].sort().at(-1);
  fs.writeFileSync(BUILD_TS, `// Generated by scripts/of-mirror.mjs; do not edit by hand.
// The OF web build (its x-of-rev) the mirror was captured from: public/of-mirror/static/<build>.
export const OF_MIRROR_BUILD = ${JSON.stringify(build)};
`);

  console.log(`pages: ${pages.size} rendered (settings: ${fromLive} from the live capture, ${modals.length} modals, ${openStates.length} states; ${captured.filter((c) => !c.state).length} page captures, ${pageStates.length} of their states; ${shells} shells left out)`);
  if (unreached.length) console.log(`state captures with no page (no control opens them): ${unreached.join(", ")}`);
  for (const [section, ps] of bySection) console.log(`  ${section}: ${ps.length}`);
  console.log(`assets: ${assetCount} files copied`);
  if (skipped.length) console.log(`assets skipped as too large: ${skipped.join(", ")}`);
  if (missing.length) console.log(`assets referenced by CSS but not in the dump (${missing.length}): ${missing.join(", ")}`);
  console.log(`scrubbed: ${usernames.size} account(s), ${fans.n} other people; ${secrets.size + fanSecrets.size + dataSecrets.size} scrubbed strings checked absent, plus the host/email/IP/digit-run/link/handle/amount checks`);
}

selfTest();
if (CHECK) check();
else main();
