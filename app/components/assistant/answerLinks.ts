import { isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER, type NavLink } from "@/lib/nav";
import { withSteps } from "@/lib/deepLink";
import { MESSAGE_DASHBOARD_TABS, SMART_MESSAGES_TABS } from "@/lib/pageTabs";

function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9&'\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

interface Place {
  href?: string;
  children?: Record<string, Place>;
  bare?: boolean;
  label?: string;
}

const tabs = (href: string, strip: Array<{ key: string; label: string }>, param = "tab"): Record<string, Place> =>
  Object.fromEntries(strip.map(({ key, label }) => [norm(label), { href: `${href}?${param}=${key}`, label }]));

const DASHBOARD = "/analytics/message-dashboard";

const BELOW: Record<string, Record<string, Place>> = {
  [DASHBOARD]: tabs(DASHBOARD, [...MESSAGE_DASHBOARD_TABS, { key: "customs", label: "Customs owed" }]),
  "/growth/smart-messages": tabs("/growth/smart-messages", SMART_MESSAGES_TABS),
  "/settings": Object.fromEntries(SETTINGS_TABS.map((l) => [norm(l.label), { href: l.href, label: l.label }])),
};

const place = (l: NavLink): Place =>
  BELOW[l.href] ? { href: l.href, children: BELOW[l.href], label: l.label } : { href: l.href, label: l.label };

const childrenOf = (links: NavLink[]): Record<string, Place> =>
  Object.fromEntries(links.map((l) => [norm(l.label), place(l)]));

export const BARE: ReadonlySet<string> = new Set(["Messages Pro", "Settings", "Help center"]);

const TOP: Array<[string, Place]> = [...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n): Array<[string, Place]> => {
  if (isDivider(n)) return [];
  const p = isGroup(n) ? { children: childrenOf(n.children) } : place(n);
  return [[n.label, BARE.has(n.label) ? { ...p, bare: true } : p]];
});

const DISTINCT_RE = /\s|-/;

const NAMED: Array<[string, Place]> = (() => {
  const seen = new Map<string, Place | null>();
  const walk = (children: Record<string, Place> | undefined) => {
    for (const p of Object.values(children ?? {})) {
      if (p.label && p.href && DISTINCT_RE.test(p.label)) {
        const had = seen.get(p.label);
        seen.set(p.label, had === undefined || had?.href === p.href ? p : null);
      }
      walk(p.children);
    }
  };
  TOP.forEach(([, p]) => walk(p.children));
  const heads = new Set(TOP.map(([l]) => l));
  return [...seen].flatMap(([l, p]): Array<[string, Place]> => (p && !heads.has(l) ? [[l, { ...p, bare: true }]] : []));
})();

// Case-sensitive on purpose: keeps "the growth of an account" plain text.
const SECTIONS: Record<string, Place> = Object.fromEntries([
  ...NAMED,
  ...TOP,
  ["Customs", { ...BELOW[DASHBOARD].customs, bare: true }],
]);

const NAMES = new Set(Object.values(SECTIONS).flatMap((p) => Object.keys(p.children ?? {})));
const PREV_WORD_RE = /(\S+)[^\S\n]$/;

const esc = (l: string) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const HEAD_RE = new RegExp(
  `\\b(${Object.keys(SECTIONS).sort((a, b) => b.length - a.length).map(esc).join("|")})\\b`, "g");
const ARROW = "→|->";
const ARROW_RE = new RegExp(`^\\s*(?:${ARROW})\\s*`);
const AFTER_ARROW_RE = new RegExp(`(?:${ARROW})\\s*$`);
const RUN_END_RE = new RegExp(`\\n|${ARROW}`);
const SEG_END = new RegExp(`[\\n,;:()[\\]"“”*\`]|\\s—\\s|\\.(?=\\s|$)|${ARROW}`);

const SENTENCE_END_RE = /[\n!?]|\.(?=\s|$)/;

function namedBelow(text: string, from: number, children: Record<string, Place>): PathHit | null {
  const tail = text.slice(from);
  const sentence = tail.slice(0, SENTENCE_END_RE.exec(tail)?.index ?? tail.length);
  const found: PathHit[] = [];
  for (const { label, href } of Object.values(children)) {
    if (!label || !href) continue;
    const at = new RegExp(`(?<![\\p{L}\\p{N}])${esc(label)}(?![\\p{L}\\p{N}])`, "u").exec(sentence)?.index;
    if (at !== undefined) found.push({ start: from + at, end: from + at + label.length, href });
  }
  const pages = found.filter((h) => !found.some((o) => o !== h && o.start <= h.start && o.end >= h.end));
  if (pages.length !== 1) return null;
  const best = pages[0];
  const between = text.slice(from, best.start);
  if (new RegExp(ARROW).test(between) || new RegExp(HEAD_RE.source).test(between)) return null;
  return best;
}

const MAX_TAIL_WORDS = 5;

export interface PathHit {
  start: number;
  end: number;
  href: string;
}

function leadingLabel(raw: string, labels: Record<string, Place>): { place: Place; length: number } | null {
  let acc = "";
  let best: { place: Place; length: number } | null = null;
  for (const piece of raw.split(/(\s+)/)) {
    acc += piece;
    if (!piece.trim()) continue;
    let clean = acc.replace(/[^\p{L}\p{N}]+$/u, "");
    const hit = labels[norm(clean)];
    if (!hit) continue;
    if (clean.split("(").length > clean.split(")").length && acc[clean.length] === ")") clean += ")";
    best = { place: hit, length: clean.length };
  }
  return best;
}

const pageOf = (href: string) => href.replace(/[?#].*$/, "");

export function findPaths(text: string, pages: ReadonlySet<string>): PathHit[] {
  const hits: PathHit[] = [];
  let m: RegExpExecArray | null;

  while ((m = HEAD_RE.exec(text))) {
    if (AFTER_ARROW_RE.test(text.slice(0, m.index))) continue;
    const prev = PREV_WORD_RE.exec(text.slice(0, m.index))?.[1];
    if (prev && norm(prev) && NAMES.has(norm(`${prev} ${m[1]}`))) continue;
    const head = SECTIONS[m[1]];
    const headEnd = m.index + m[1].length;
    let cursor = headEnd;
    let end = headEnd;
    let at = head;
    let steps: string[] = [];

    for (;;) {
      const arrow = ARROW_RE.exec(text.slice(cursor));
      if (!arrow) break;
      const segStart = cursor + arrow[0].length;
      const tail = text.slice(segStart);
      const run = tail.slice(0, RUN_END_RE.exec(tail)?.index ?? tail.length);
      const hit = at.children && leadingLabel(run, at.children);
      if (hit) {
        at = hit.place;
        steps = [];
        end = segStart + hit.length;
        if (run.slice(hit.length).trim()) break;
        cursor = end;
        continue;
      }
      const stop = SEG_END.exec(tail);
      const seg = stop ? tail.slice(0, stop.index) : tail;
      if (!seg.trim()) break;
      if (!ARROW_RE.test(text.slice(segStart + seg.length))) {
        if (seg.trim().split(/\s+/).length <= MAX_TAIL_WORDS) steps.push(seg.trim());
        break;
      }
      steps.push(seg.trim());
      end = segStart + seg.trimEnd().length;
      cursor = segStart + seg.length;
    }

    const named = end === headEnd && head.children ? namedBelow(text, headEnd, head.children) : null;
    if (named) {
      hits.push({ start: m.index, end, href: named.href }, named);
      HEAD_RE.lastIndex = named.end;
      continue;
    }

    if (!at.href || (end === headEnd && !head.bare)) continue;

    hits.push({ start: m.index, end, href: withSteps(at.href, steps) });
    HEAD_RE.lastIndex = end;
  }

  // Only pages the asker's role may open link: a chatter's answer never links an owner-only page.
  return hits.filter((h) => pages.has(pageOf(h.href)));
}
