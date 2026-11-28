import { decodedViews } from "./dom.mjs";
import { CUSTOM_ELEMENT, words } from "./markup-policy.mjs";

export const PLACEHOLDER = { username: "yourmodel", name: "Your Model", email: "model@example.com", fan: "fan1", fanName: "Fan 1" };
export const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const flexRe = (s) => esc(s).replace(/ /g, "\\s+");
const squash = (s) => s.replace(/\s+/g, " ");
export const EMAIL = /[\w.%+-]+@[a-z0-9][\w-]*(?:\.[\w-]+)*\.[a-z]{2,}/gi;
export const MONEY = /\$\s?\d[\d,]*(?:\.\d+)?/g;

const CREDENTIAL = /\beyJ[\w-]+\.[\w-]+\.[\w-]+|\bbearer\s+[\w.+/=-]+|(?<![\w-])[a-f0-9]{32,}(?![\w-])/i;
const BASE64 = /(?<![\w-])[A-Za-z0-9+/_-]{40,}={0,2}(?![\w-])/g;
export const hasCredential = (value, opaque = true) => decodedViews(value).some((v) => {
  const plain = v.normalize("NFKC").replace(/[\p{Cf}\u00ad]/gu, "");
  return CREDENTIAL.test(plain) || (opaque && [...plain.matchAll(BASE64)].some(([token]) =>
    /[A-Z]/.test(token) && /[a-z]/.test(token) && /[0-9+=]/.test(token)));
});

const FANSLY_HOST = /^(?:www\.)?fansly\.com$/i;
export function fanslyPath(v, base) {
  let u;
  try {
    u = new URL(v.trim(), base);
  } catch {
    return null;
  }
  if (!/^https?:$/.test(u.protocol) || !FANSLY_HOST.test(u.hostname)) return null;
  return u.pathname.replace(/\/+$/, "").toLowerCase() || "/";
}

const hasWord = (token, word) => `-${token.toLowerCase().replace(/_/g, "-")}-`.includes(`-${word}-`);
const elementWords = (el) => [...(el.classList || [])].concat(CUSTOM_ELEMENT.test(el.localName) ? [el.localName] : []);
const isAvatar = (el) => {
  for (let e = el; e?.nodeType === 1; e = e.parentNode) if (elementWords(e).some((t) => hasWord(t, "avatar"))) return true;
  return false;
};

const TEXT_RULES = [
  ["session", ["session"]],
  ["bank", ["payout", "tax", "bank"]],
  ["name", ["display-name"]],
  ["handle", ["username"]],
  ["list", ["list-name"]],
  ["bio", ["bio", "about"]],
  ["note", ["note", "notes"]],
  ["text", ["message", "post-text", "post-content", "feed-item-description"]],
];
export const ruleOf = (el) => {
  const tokens = elementWords(el);
  return TEXT_RULES.find(([, ws]) => ws.some((w) => tokens.some((t) => hasWord(t, w))))?.[0];
};
const ruleAbove = (node) => {
  for (let e = node.parentNode; e?.nodeType === 1; e = e.parentNode) {
    const r = ruleOf(e);
    if (r) return r;
  }
};
const LOREM = ["Lorem ipsum", "Lorem ipsum dolor sit amet.", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.", "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."];
const lorem = (s) => LOREM[[...s].length <= 14 ? 0 : [...s].length <= 40 ? 1 : [...s].length <= 100 ? 2 : 3];
const LOREM_KINDS = words("text bio list note");
const BLANK_KINDS = words("session bank");
const PLACEHOLDER_TEXT = new RegExp(`^(?:@?${esc(PLACEHOLDER.username)}|${esc(PLACEHOLDER.name)}|@?fan\\d+|Fan \\d+)$`, "i");

const UI_TEXT = [
  "html.bright-theme>head>title",
  "html.bright-theme>body>app-root>div.middle-side>p.empty-hint",
  "app-account-subscription-plans>div.margin-top-1>div.subscription-plans>div.flex-col.flex-wrap>div.limited-offer>div.offer-ends-at.margin-bottom-1",
  "app-button-new>div.flex-1>div.confirmation-content>div>div.flex-row.margin-top-1",
  "app-consent-co-performer-route>div.cp-detail>div.input-container>div.input-content>div.material-input>select.form-select.notranslate.ng-untouched.ng-pristine.ng-valid>option",
  "app-consent-vault-route>div.consent-vault>a.cv-learn-more>span",
  "app-creator-dashboard-streaming-route>div.flex-col>div.bold",
  "app-creator-dashboard-streaming-route>div.flex-col>div.btn.v2.solid-blue.flex-align-self-start.margin-top-2",
  "app-creator-dashboard-streaming-route>div.flex-col>div.dark-blue-1.font-size-sm",
  "app-date-picker.active-modal>div.modal.v2.date-picker-modal>div.modal-body>div.date-picker-headline>span",
  "app-media-offer-suggestions-timeline-post>div.fyp-gallery-wrapper>div.semi-bold.flex-row.flex-align-center.title-container",
  "app-plan-promotion-model>div.promo>div.modal-check>span",
  "app-plan-promotion-model>div.promo>div.modal-dates>div.btn.v2.solid-grey",
  "app-profile-media-offers-route>div>div.dark-blue-1.margin-top-2.text-center",
  "app-settings-notifications-route>div.fansly-settings-card>div.fansly-settings-row.toggle-row>div.fansly-settings-body>div.fansly-settings-label",
  "app-user-vault>div.vault-wrapper.margin-top-2>div.vault-content>div.flex-row.flex-center.margin-top-4.dark-blue-1.text-center.font-size-sm",
  "app-xd-localization-select.nav-bar-item.sm-mobile-hidden>div.transparent-dropdown>div.dropdown-list>div.dropdown-item>span.margin-left-text.xs-mobile-hidden",
  "app-xd-localization-select>div.transparent-dropdown>div.dropdown-list.top.left>div.dropdown-item>span.margin-left-text",
  "div.current-page.flex-row>button.btn.v2.fansly-icon-btn@aria-label",
  "div.flex-col.flex-0.tier-order>button.btn.v2.text.creator-order-action.disabled@aria-label",
  "div.realtime-tiles>app-growth-stat-tile@label",
  "div.right-side>button.balance-dropdown.balance-trigger.sm-mobile-visible@aria-label",
  "div.row-aside>div.row-time@title",
  "div.tab-nav-items.v2.flex-0>button.btn.v2.text.subscription-filter@aria-label",
  "div.tab-nav-items.v2.flex-0>button.btn.v2.text.subscription-filter@title",
  "div.tile-grid.compact>app-growth-stat-tile@label",
  "div.tile-grid>app-growth-stat-tile@label",
  "div.wallet-figure-label>span.wallet-figure-hint@title",
];
const TEXT_TAILS = new Map([
  ...UI_TEXT.map((t) => [t, "ui"]),
  ["app-account-subscription-plans>div.margin-top-1>div.subscription-plans>div.flex-col.flex-wrap>div.limited-offer>div.offer-title.flex-row.flex-align-center.flex-wrap>span.margin-right-text.eclipse", "list"],
  ["app-list-route>div.flex-row.border-bottom-1.padding-bottom-2.padding-left-text.padding-right-text>div.bold.flex-1", "list"],
  ["app-list>div.flex-row.list.flex-align-center>div.flex-col.flex-1>div.bold", "list"],
  ["app-profile-route>div.page-content>div.profile-wrapper>div.profile-content-wrapper>div.profile-description-text>span", "bio"],
  ["app-subscription-plans-route>div.fansly-settings-card>div.fansly-settings-row.tier-row>div.fansly-settings-body>div.flex-row>div.subscription-promotion.flex-1>div.flex-col.flex-wrap>div.limited-offer>div.offer-title.flex-row.flex-align-center.flex-wrap>span.margin-right-text.eclipse", "list"],
  ["app-subscription-plans-route>div.fansly-settings-card>div.fansly-settings-row>div.fansly-settings-body>div.fansly-settings-label>span", "list"],
  ["app-subscription-plans-route>div.fansly-settings-card>div.fansly-settings-row>div.fansly-settings-body>div.fansly-settings-text.notranslate", "list"],
]);
const BUILT_IN_LISTS = ["Blocked Accounts", "Muted Accounts", "VIP Accounts"];
const SHORT_TEXT_TAILS = new Map([
  ["app-list-route>div.flex-row.border-bottom-1.padding-bottom-2.padding-left-text.padding-right-text>div.bold.flex-1", BUILT_IN_LISTS],
  ["app-list>div.flex-row.list.flex-align-center>div.flex-col.flex-1>div.bold", BUILT_IN_LISTS],
  ["app-media-vault>div.vault-albums-container>div.vault-albums>div.vault-album.fansly-album-card>div.vault-album-footer.xd-drag-ignore>div.fansly-album-card-title", ["All", "Posts", "Messages"]],
  ["app-account-subscription-plans>div.margin-top-1>div.subscription-plans>div.flex-col.flex-wrap>div.limited-offer>div.promo-description.margin-bottom-1", []],
]);
const SHORT_TEXT_CLASSES = new Set([...SHORT_TEXT_TAILS.keys()].map((t) => t.split(">").at(-1).split(".")[1]));
const shortTextRule = (parent, t) => {
  if (![...(parent.classList || [])].some((c) => SHORT_TEXT_CLASSES.has(c))) return;
  const keep = SHORT_TEXT_TAILS.get(textKey(elementPath(parent)));
  return keep ? (keep.includes(t) ? "ui" : "list") : undefined;
};
const SHORT_UI_TEXT = new Set(["Tracking Links", "Creator Dashboard"]);
const isLongText = (t) => t.length >= 20 || t.split(/\s+/).filter((w) => /\p{L}/u.test(w)).length >= 3;
const elementPath = (el) => {
  const parts = [];
  for (let e = el; e?.nodeType === 1; e = e.parentNode) parts.unshift(`${e.localName}${[...(e.classList || [])].map((c) => `.${c}`).join("")}`);
  return parts.join(">");
};

const textKey = (where, attr) => {
  const s = where.split(">");
  if (attr) return s.slice(-2).join(">");
  const host = s.findLastIndex((x, i) => i < s.length - 1 && /^app-(?!root(?:\.|$))/.test(x));
  return host >= 0 ? s.slice(host).join(">") : where;
};

const NOT_PROFILES = words("home post messages notifications creator scheduled lists bookmarks subscriptions settings explore fyp search tag affiliates leaderboard live legal");
const HANDLES = /(?:^|[^\w.%+-])@([\w.]*\w)/g;
const NOT_PEOPLE = /^(?:@?fan ?\d+|fan|your|model|yourmodel|your model|username)$/;
export function collectPeople(docs, identityValues, baseOf) {
  const people = new Map();
  let next = 2;
  const isIdentity = (k) => !/[\p{L}\p{N}_]/u.test(identityValues.reduce((acc, i) => acc.replaceAll(i, ""), k));
  const add = (v, num) => {
    const k = squash(v.trim().replace(/^@/, "")).toLowerCase();
    if (k.length < 2 || !/\p{L}/u.test(k) || NOT_PEOPLE.test(k) || isIdentity(k)) return null;
    if (!people.has(k)) people.set(k, num ?? next++);
    return people.get(k);
  };
  for (const { entry, dom } of docs) {
    const doc = dom.window.document;
    const { SHOW_ELEMENT, SHOW_TEXT } = dom.window.NodeFilter;
    const walker = doc.createTreeWalker(doc, SHOW_ELEMENT | SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.nodeType === n.TEXT_NODE) {
        if (/^(?:script|style)$/.test(n.parentNode?.localName)) continue;
        for (const m of n.data.matchAll(HANDLES)) add(m[1]);
        const rule = n.data.trim() && ruleAbove(n);
        if (rule === "name" || rule === "handle") add(n.data);
      } else if (n.localName === "a" && n.hasAttribute("href")) {
        const seg = fanslyPath(n.getAttribute("href"), baseOf(entry))?.split("/").filter(Boolean)[0];
        const num = seg && /^\w+$/.test(seg) && !NOT_PROFILES.has(seg) ? add(seg) : null;
        if (num === null) continue;
        for (const v of [n.getAttribute("title"), n.getAttribute("aria-label"), ...[...n.querySelectorAll("img[alt]")].map((i) => i.getAttribute("alt"))]) add(v || "", num);
        const texts = doc.createTreeWalker(n, SHOW_TEXT);
        for (let t = texts.nextNode(); t; t = texts.nextNode()) add(t.data, num);
      } else if (n.localName === "img" && n.getAttribute("alt") && isAvatar(n)) add(n.getAttribute("alt"));
    }
  }
  return people;
}

const keysRe = (keys) => {
  if (!keys.length) return null;
  const sorted = [...keys].sort((a, b) => b.length - a.length || (a < b ? -1 : 1));
  return new RegExp(`(?<![\\p{L}\\p{N}_])(@?)(${sorted.map(flexRe).join("|")})(?![\\p{L}\\p{N}_])`, "giu");
};

export function makeSwap(creator, fan, people) {
  const identity = [
    [creator.username, PLACEHOLDER.username],
    [creator.displayName, PLACEHOLDER.name],
    [fan.username, PLACEHOLDER.fan],
    [fan.displayName, PLACEHOLDER.fanName],
  ].sort((a, b) => b[0].length - a[0].length);
  const values = identity.map(([from]) => from.toLowerCase());
  const keys = [...people.keys()];
  const wrapped = keysRe(keys.filter((k) => values.some((v) => k.includes(v))));
  const rest = keysRe(keys.filter((k) => !values.some((v) => k.includes(v))));
  const res = identity.map(([from, to]) => [new RegExp(flexRe(from), "gi"), to]);
  const person = (_, at, k) => (at ? `@fan${people.get(squash(k).toLowerCase())}` : `Fan ${people.get(squash(k).toLowerCase())}`);
  const swap = (s) => {
    const v = res.reduce((acc, [re, to]) => acc.replace(re, to), wrapped ? s.replace(wrapped, person) : s);
    return rest ? v.replace(rest, person) : v;
  };
  return { swap, peopleRe: peopleReOf(people) };
}
export const peopleReOf = (people) => keysRe([...people.keys()]);

const MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?";
const UNIT = "(?:[Ss]econd|[Mm]inute|[Hh]our|[Dd]ay|[Ww]eek|[Mm]onth|[Yy]ear)s?";
const DATE_TOKEN = `(?<![\\p{L}\\d_])(?:${MONTH}(?:\\s+\\d{1,2})?(?:,?\\s+(?:\\d{4}|'\\d\\d))?|\\d{1,2}\\s+${MONTH}(?:\\s+\\d{4})?|\\d{1,4}[/.-]\\d{1,2}[/.-]\\d{1,4}|\\d{1,2}:\\d\\d(?::\\d\\d)?(?:\\s*[AaPp][Mm])?|\\d{1,2}\\s*[AaPp][Mm]|\\d+(?:\\s*[-–]\\s*\\d+)?\\s+(?:business\\s+)?${UNIT}(?:\\s+ago)?)(?![\\p{L}\\d_])`;
const NUMBER = new RegExp(`(${DATE_TOKEN})|\\$\\s?[\\d,.]+|(?<![\\p{L}\\d_])\\d+(?:(?=[KMkm](?![\\p{L}_]))|(?![\\p{L}_]))`, "gu");
const FAKE_MONEY = ["5", "12", "123", "1,234", "12,345", "123,456"];
export function fakeMoney(m) {
  const [int, cents] = m.replace(/[$\s,]/g, "").split(".");
  if (/^0*$/.test(int) && /^0*$/.test(cents || "")) return cents === undefined ? "$0" : "$0.00";
  const digits = String(Number(int)).length;
  return `$${FAKE_MONEY[Math.min(digits, FAKE_MONEY.length) - 1]}${cents === undefined ? "" : ".00"}`;
}
const FAKE_DIGITS = "1234567890".repeat(4);
const fakeDigits = (d) => (/^0+$/.test(d) ? d : FAKE_DIGITS.slice(0, d.length));
export const isFakeDigits = (d) => /^0+$/.test(d) || FAKE_DIGITS.startsWith(d);
const fakeNumbers = (s) => s.split(/(\bFan \d+\b)/).map((part, i) => (i % 2 ? part : part.replace(NUMBER, (m, date) => (date || m.startsWith("$") ? m : fakeDigits(m))))).join("");
export const fakeEmails = (s) => s.replace(EMAIL, () => PLACEHOLDER.email);

export function scrubIdentity(raw, swap) {
  for (const view of decodedViews(raw)) {
    const safe = fakeEmails(swap(view));
    if (safe !== view) return safe;
  }
  return raw;
}

const ID_RUN = /(?<![\d.])\d{6,}(?!\d|\.\d)/;
const COLOUR = /#(?:[\da-f]{8}|[\da-f]{6}|[\da-f]{3,4})(?![\w-])|\b(?:rgba?|hsla?)\((?:\s*[+-]?\d{1,3}(?!\d)(?:\.\d+)?(?:%|deg|turn|rad)?\s*[,/]?)*\)/gi;
const STATIC_REF = /url\("\/fansly-mirror\/static\/[\w./-]*"\)/g;
export function dropIds(name, value) {
  if (!ID_RUN.test(value)) return value;
  if (name === "class") return value.split(/\s+/).filter((t) => t && !ID_RUN.test(t)).join(" ");
  if (name === "style") return value.split(";").filter((d) => !ID_RUN.test(d.replace(COLOUR, "").replace(STATIC_REF, ""))).join(";");
  return "";
}

export const PROSE_ATTRS = words("title alt label placeholder abbr aria-label aria-description aria-roledescription aria-valuetext aria-placeholder");
const KEEP_INPUT_VALUE = words("checkbox radio submit button reset");
const isEditable = (el) => el.hasAttribute("contenteditable") && el.getAttribute("contenteditable").toLowerCase() !== "false";
export function clearFields(el) {
  if (el.localName === "input" && !KEEP_INPUT_VALUE.has((el.getAttribute("type") || "text").toLowerCase())) el.removeAttribute("value");
  if (el.localName === "textarea" || isEditable(el)) el.textContent = "";
}

export function scrubText(raw, given, ctx, parent, attr) {
  if (hasCredential(raw)) return "";
  const v = scrubIdentity(raw, ctx.swap);
  const t = v.trim();
  if (!t) return v;
  let rule = given;
  const candidate = t.replace(EMAIL, "").trim();
  const shortName = /^\p{Lu}\p{Ll}+ \p{Lu}\p{Ll}+$/u.test(candidate) && !PLACEHOLDER_TEXT.test(candidate) && !SHORT_UI_TEXT.has(candidate);
  if (!rule && !attr && shortName) rule = shortTextRule(parent, t);
  if (!rule && ((candidate && isLongText(raw.replace(EMAIL, "").trim())) || shortName)) {
    const where = `${elementPath(parent)}${attr ? `@${attr}` : ""}`;
    rule = TEXT_TAILS.get(textKey(where, attr)) || (!attr && parent.localName === "xd-localization-string" ? "ui" : undefined);
    if (!rule) ctx.unreviewed.add(where);
  } else if (!rule && !attr) rule = shortTextRule(parent, t);
  if (BLANK_KINDS.has(rule)) return "";
  if (LOREM_KINDS.has(rule) && !PLACEHOLDER_TEXT.test(t)) return v.replace(t, () => lorem(raw.trim()));
  if (!attr && parent.classList?.contains("xdp-day") && /^(?:[1-9]|[12]\d|3[01])$/.test(t)) return v;
  return fakeNumbers(fakeEmails(v)).replace(MONEY, fakeMoney);
}
