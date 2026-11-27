import { EMAIL, MONEY, PLACEHOLDER, collectPeople, esc, isFakeDigits } from "./scrub.mjs";

export const STATIC_URL = "/fansly-mirror/static";
const SAFE_IPS = new Set(["127.0.0.1", "1.2.3.4"]);
const INVISIBLE = /[\p{Cf}\u00ad]/gu;
const views = (v) => [...new Set([v, v.normalize("NFKC")].flatMap((x) => [x, x.replace(INVISIBLE, "")]))];
const KEEP_MONEY = new Set(["$1", "$3", "$4.99", "$10", "$20", "$20.00", "$50.00"]);
const isFakeMoney = (m) => KEEP_MONEY.has(m) || /^\$(?:5|1,234|12,345|123,456)(?:\.00)?$/.test(m) || (/^\$\d+(?:\.\d{1,2})?$/.test(m) && m.slice(1).split(".").every(isFakeDigits));
const SAFE_HANDLE = new RegExp(`^(?:${esc(PLACEHOLDER.username)}|username|fan\\d+)$`, "i");
const SCHEME = /(?<![a-z0-9+.-])(https?|wss?|javascript):/gi;
const unbuild = (v, build) => (build ? v.replace(new RegExp(`${esc(STATIC_URL)}/${esc(build)}(?![\\w.-])`, "g"), `${STATIC_URL}/build`).replaceAll(`"${build}"`, '"build"') : v);

export function textKinds(value, kinds, { build, needles = [], people = null, numeric = true, readable = false } = {}) {
  for (const v of views(unbuild(value, build))) {
    if (/fansly\.com\b|\bfans\.ly\b/i.test(v)) kinds.add("fansly-host");
    const flat = v.replace(/[\t\n\r]/g, "");
    for (const m of flat.matchAll(SCHEME)) kinds.add(m[1].toLowerCase() === "javascript" ? "handler" : "remote");
    if (/(?<![:\w/\\])[\\/]{2}[a-z0-9-]+\.[a-z]/i.test(flat)) kinds.add("remote");
    if (/(?<![\w-])data:(?:\s*[\w.+-]+\/[\w.+-]+|,)/i.test(v)) kinds.add("data-uri");
    for (const m of v.matchAll(EMAIL)) if (!m[0].toLowerCase().endsWith(PLACEHOLDER.email)) kinds.add("email");
    const lower = v.toLowerCase();
    if (needles.some((n) => lower.includes(n)) || (people && v.search(people) >= 0)) kinds.add("identity");
    if (numeric) {
      for (const m of v.matchAll(/(?<!\d|\d\.)\d{1,3}(?:\.\d{1,3}){3}(?!\d|\.\d)/g)) if (!SAFE_IPS.has(m[0])) kinds.add("ipv4");
      if (/(?<![\w:])(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}(?![\w:])|(?<![\w:])(?:[0-9a-f]{1,4}:){1,7}:(?:[0-9a-f]{1,4})?(?![\w:])/i.test(v)) kinds.add("ipv6");
      for (const r of v.matchAll(/(?<![\d.])\d{9,}(?!\d|\.\d)/g)) if (!isFakeDigits(r[0])) kinds.add("digit-run");
    }
    if (readable) {
      for (const m of v.matchAll(/(?:^|[^\w.%+-])@([\w.]*\w)/g)) if (!SAFE_HANDLE.test(m[1])) kinds.add("handle");
      for (const m of v.matchAll(MONEY)) if (!isFakeMoney(m[0])) kinds.add("amount");
    }
  }
}

export const pathOfUrl = (u) => {
  try {
    return new URL(u).pathname.replace(/\/+$/, "").toLowerCase() || "/";
  } catch {
    return null;
  }
};
export const baseOf = (entry) => `https://fansly.com${pathOfUrl(entry.final_url || entry.url) || "/"}`;
export const needlesOf = (identities) => identities.flatMap((i) => [i?.username, i?.displayName, i?.accountId]).filter((v) => typeof v === "string" && v).map((v) => v.toLowerCase());
export const peopleOf = (docs, needles) => collectPeople(docs, needles, baseOf);
