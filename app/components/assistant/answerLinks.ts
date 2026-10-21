/**
 * answerLinks — turn the help bot's click paths into real hrefs.
 *
 * The bot answers in the manual's own words: "Growth → Auto-follow",
 * "Analytics → Message dashboard → Customs". Those are the sidebar's own
 * labels, so they can be resolved to a route instead of being read and
 * re-typed by hand.
 *
 * NOTHING HERE IS COPIED: every head and page comes from lib/nav.ts, the table
 * the sidebar itself draws, and every tab from lib/pageTabs.ts, the arrays the
 * pages draw their strips from, so a renamed or moved page or tab moves here
 * with it.
 *
 * Resolution is BEST-EFFORT and lands on the deepest PAGE the path names: a
 * path whose last segment we cannot read still links to the page before it. A
 * sidebar group is a heading, not a page, so a group with no recognised page
 * under it links nothing. What it must never do is invent — an unrecognised
 * word yields no link, so a sentence about "the growth of an account" stays
 * plain text.
 */

import { isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER, type NavLink } from "@/lib/nav";
import { MESSAGE_DASHBOARD_TABS, SMART_MESSAGES_TABS } from "@/lib/pageTabs";

/** Lowercase, drop emoji/punctuation, collapse runs — "🗓️ Auto Posts" → "auto posts". */
function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9&'\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** A place a path can land on, and the labels one arrow further down it. */
interface Place {
  /** Where it links. A sidebar group has none: it is a heading, not a page. */
  href?: string;
  /** Normalised label → the place it opens. */
  children?: Record<string, Place>;
  /** Linkable on its own, with no "→ …" after it (see BARE). */
  bare?: boolean;
}

/** A page's tab strip as its children, each opening `?param=key`. */
const tabs = (href: string, strip: Array<{ key: string; label: string }>, param = "tab"): Record<string, Place> =>
  Object.fromEntries(strip.map(({ key, label }) => [norm(label), { href: `${href}?${param}=${key}` }]));

const DASHBOARD = "/analytics/message-dashboard";

/** What sits one arrow below a nav page: its tab strip, or Settings' pages. */
const BELOW: Record<string, Record<string, Place>> = {
  // The Customs tab's own heading, and the manual, say "Customs owed".
  [DASHBOARD]: tabs(DASHBOARD, [...MESSAGE_DASHBOARD_TABS, { key: "customs", label: "Customs owed" }]),
  "/growth/smart-messages": tabs("/growth/smart-messages", SMART_MESSAGES_TABS),
  "/settings": Object.fromEntries(SETTINGS_TABS.map((l) => [norm(l.label), { href: l.href }])),
};

const place = (l: NavLink): Place => (BELOW[l.href] ? { href: l.href, children: BELOW[l.href] } : { href: l.href });

const childrenOf = (links: NavLink[]): Record<string, Place> =>
  Object.fromEntries(links.map((l) => [norm(l.label), place(l)]));

/** The pages that link standing alone: nav words no sentence uses by accident.
 *  "Dashboard" is an ordinary word, so it only ever links as the head of a
 *  path. */
export const BARE: ReadonlySet<string> = new Set(["Messages Pro", "Settings", "Help center"]);

/** Keyed by the nav label EXACTLY as the sidebar capitalises it — the match is
 *  case-sensitive, which is what keeps "the growth of an account" plain text. */
const SECTIONS: Record<string, Place> = Object.fromEntries([
  ...[...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n): Array<[string, Place]> => {
    if (isDivider(n)) return [];
    const p = isGroup(n) ? { children: childrenOf(n.children) } : place(n);
    return [[n.label, BARE.has(n.label) ? { ...p, bare: true } : p]];
  }),
  // Not a nav entry but the manual's name for a queue: straight to its tab.
  ["Customs", { ...BELOW[DASHBOARD].customs, bare: true }],
]);

/** Every label one arrow below a head. A head word that ends one of them
 *  ("Role Settings", "Sales Settings") is that page's name, not the head. */
const NAMES = new Set(Object.values(SECTIONS).flatMap((p) => Object.keys(p.children ?? {})));
const PREV_WORD_RE = /(\S+)[^\S\n]$/;

const esc = (l: string) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const HEAD_RE = new RegExp(
  `\\b(${Object.keys(SECTIONS).sort((a, b) => b.length - a.length).map(esc).join("|")})\\b`, "g");
/** Both arrow spellings, once; every pattern below is built from it. */
const ARROW = "→|->";
const ARROW_RE = new RegExp(`^\\s*(?:${ARROW})\\s*`);
/** Text that ends in an arrow: whatever follows it is a path's segment. */
const AFTER_ARROW_RE = new RegExp(`(?:${ARROW})\\s*$`);
/** A segment's run: up to the next arrow or the end of the line. Labels are
 *  matched inside it, brackets and all. */
const RUN_END_RE = new RegExp(`\\n|${ARROW}`);
/** Ends a step the walk cannot name. `.` only counts when it ends a sentence,
 *  so a decimal inside a step survives. Em dash and quotes end it because the
 *  manual uses them to append commentary after a path. `*` and a backtick end
 *  it so that calling this on RAW markdown cannot trail the bold marker into
 *  the link text. */
const SEG_END = new RegExp(`[\\n,;:()[\\]"“”*\`]|\\s—\\s|\\.(?=\\s|$)|${ARROW}`);

export interface PathHit {
  /** Index of the first character of the linked run. */
  start: number;
  /** Index one past the last character of the linked run. */
  end: number;
  href: string;
}

/**
 * The longest leading run of `raw` that names one of `labels`, or null.
 *
 * Walks word by word rather than normalising the whole segment, because the
 * answer usually continues past the label — "Auto Post and press New auto
 * post" must link only the first two words. Matching on the normalised whole
 * would fail outright and link the sentence. Trailing punctuation is trimmed
 * off each candidate ("AI keys," → "AI keys", "Auto Mass)" → "Auto Mass"), and
 * a closing bracket comes back only when the label opened one, so "Security
 * (personal)" is matched whole while a path written inside parentheses keeps
 * its ")" out of the link.
 */
function leadingLabel(raw: string, labels: Record<string, Place>): { place: Place; length: number } | null {
  let acc = "";
  let best: { place: Place; length: number } | null = null;
  for (const piece of raw.split(/(\s+)/)) { // separators kept so lengths stay exact
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

/**
 * Find every click path in `text`.
 *
 * Hits never overlap and are returned in source order, so a caller can splice
 * the string in one pass.
 */
export function findPaths(text: string): PathHit[] {
  const hits: PathHit[] = [];
  HEAD_RE.lastIndex = 0;
  let m: RegExpExecArray | null;

  while ((m = HEAD_RE.exec(text))) {
    // A word right after an arrow is a segment of the path before it, one the
    // walk could not name, never the head of a new path: "Smart lists →
    // Settings" must not link "Settings" to Your Account.
    if (AFTER_ARROW_RE.test(text.slice(0, m.index))) continue;
    const prev = PREV_WORD_RE.exec(text.slice(0, m.index))?.[1];
    if (prev && NAMES.has(norm(`${prev} ${m[1]}`))) continue;
    const head = SECTIONS[m[1]];
    const headEnd = m.index + m[1].length;
    let cursor = headEnd;
    let end = headEnd;
    let at = head;

    // Walk "→ segment" pairs for as long as they keep arriving.
    for (;;) {
      const arrow = ARROW_RE.exec(text.slice(cursor));
      if (!arrow) break;
      const segStart = cursor + arrow[0].length;
      const tail = text.slice(segStart);
      const run = tail.slice(0, RUN_END_RE.exec(tail)?.index ?? tail.length);
      const hit = at.children && leadingLabel(run, at.children);
      if (hit) {
        at = hit.place;
        end = segStart + hit.length;
        // The label may be followed by prose ("Auto Post and press …"); only
        // keep walking when the run WAS the label and an arrow follows.
        if (run.slice(hit.length).trim()) break;
        cursor = end;
        continue;
      }
      // An unrecognised segment is an intermediate step ("+", a card's name)
      // only when another arrow follows it. Otherwise it is prose and the link
      // stops before it.
      const stop = SEG_END.exec(tail);
      const seg = stop ? tail.slice(0, stop.index) : tail;
      if (!seg.trim() || !ARROW_RE.test(text.slice(segStart + seg.length))) break;
      end = segStart + seg.trimEnd().length;
      cursor = segStart + seg.length;
    }

    // A group with no page recognised under it names no page. With nothing
    // consumed past the head, only some pages stand alone.
    if (!at.href || (end === headEnd && !head.bare)) continue;

    hits.push({ start: m.index, end, href: at.href });
    HEAD_RE.lastIndex = end; // never emit overlapping hits
  }

  return hits;
}
