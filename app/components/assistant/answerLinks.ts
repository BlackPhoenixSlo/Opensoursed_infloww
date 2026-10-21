/**
 * answerLinks — turn the help bot's click paths into real hrefs.
 *
 * The bot answers in the manual's own words: "Growth → Auto-follow",
 * "Analytics → Message dashboard → Customs". Those are the sidebar's own
 * labels, so they can be resolved to a route instead of being read and
 * re-typed by hand.
 *
 * THE NAV IS READ, NOT COPIED: every head and page below comes from
 * lib/nav.ts, the table the sidebar itself draws, so a renamed or moved page
 * moves here with it. Only the three tab strips are copies — importing the real
 * `TABS` arrays would drag their page components (and data hooks) into the
 * widget's bundle for a string map — and `answerLinks.test.ts` asserts every
 * key still exists in the component that owns it.
 *
 * Resolution is BEST-EFFORT and falls back to the deepest place it could
 * name: a path whose last segment we cannot read still lands the reader on
 * that page's parent, which beats not linking at all. What it must never do is
 * invent — an unrecognised word yields no link, so a sentence about "the
 * growth of an account" stays plain text.
 */

import { isDivider, isGroup, SETTINGS_TABS, SIDEBAR, SIDEBAR_FOOTER, type NavLink } from "@/lib/nav";

/** Lowercase, drop emoji/punctuation, collapse runs — "🗓️ Auto Posts" → "auto posts". */
function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9&'\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** app/analytics/message-dashboard/page.tsx TABS (the ex-"Stuff" page). */
export const MESSAGES_TABS: Record<string, string> = {
  "direct messages": "direct",
  "onlyfans mass messages": "mass",
  ppv: "ppv",
  tips: "tips",
  all: "all",
  customs: "customs",
  // The manual and the tab's own heading both say "Customs owed".
  "customs owed": "customs",
  posts: "posts",
  "my feed": "myfeed",
  "top posts": "top",
};

/** components/growth/SmartMessagesPage.tsx LOOKUP (its two tabs). */
export const SMART_MESSAGES_TABS: Record<string, string> = {
  "automated messages": "automated",
  "mass messages": "mass",
};

/** A place a path can land on, and the labels one arrow further down it. */
interface Place {
  href: string;
  /** Normalised label → the place it opens. */
  children?: Record<string, Place>;
  /** Linkable on its own, with no "→ …" after it. "Analytics" and "Creators"
   *  are ordinary words in a sentence, so they only ever link as the head of a
   *  path. */
  bare?: boolean;
}

const tabs = (href: string, labels: Record<string, string>, param = "tab"): Record<string, Place> =>
  Object.fromEntries(Object.entries(labels).map(([label, key]) => [label, { href: `${href}?${param}=${key}` }]));

/** What sits one arrow below a nav page: its tab strip, or Settings' pages. */
const BELOW: Record<string, Record<string, Place>> = {
  "/analytics/message-dashboard": tabs("/analytics/message-dashboard", MESSAGES_TABS),
  "/growth/smart-messages": tabs("/growth/smart-messages", SMART_MESSAGES_TABS),
  "/settings": Object.fromEntries(SETTINGS_TABS.map((l) => [norm(l.label), { href: l.href }])),
};

const place = (l: NavLink): Place => (BELOW[l.href] ? { href: l.href, children: BELOW[l.href] } : { href: l.href });

const childrenOf = (links: NavLink[]): Record<string, Place> =>
  Object.fromEntries(links.map((l) => [norm(l.label), place(l)]));

/** The heads that link standing alone: nav words no sentence uses by accident. */
const BARE = new Set(["OF Manager", "Messages Pro", "Growth", "Share for Share", "My Automations", "Settings", "Help center"]);

/** Keyed by the nav label EXACTLY as the sidebar capitalises it — the match is
 *  case-sensitive, which is what keeps "the growth of an account" plain text.
 *  A group's own link is its first page, as the sidebar opens it. */
const SECTIONS: Record<string, Place> = Object.fromEntries(
  [...SIDEBAR, ...SIDEBAR_FOOTER].flatMap((n): Array<[string, Place]> => {
    if (isDivider(n)) return [];
    const p = isGroup(n) ? { href: n.children[0].href, children: childrenOf(n.children) } : place(n);
    return [[n.label, BARE.has(n.label) ? { ...p, bare: true } : p]];
  }),
);
// Not a nav entry but the manual's name for a queue: straight to its tab.
SECTIONS.Customs = { href: "/analytics/message-dashboard?tab=customs", bare: true };

const HEAD_RE = new RegExp(
  `\\b(${Object.keys(SECTIONS).sort((a, b) => b.length - a.length).join("|")})\\b`, "g");
const ARROW_RE = /^\s*(→|->)\s*/;
/** Ends a path segment. `.` only counts when it ends a sentence, so a decimal
 *  inside a label survives. Em dash and quotes end it because the manual uses
 *  them to append commentary after a path. `*` and a backtick end it so that
 *  calling this on RAW markdown — which AnswerText does not, but an independent
 *  caller might — cannot trail the bold marker into the link text. */
const SEG_END = /[\n,;:()[\]"“”*`]|\s—\s|\.(?=\s|$)|→|->/;

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
 * off each candidate ("AI keys," → "AI keys") but a closing bracket is kept, so
 * "Security (personal)" is matched whole.
 */
function leadingLabel(
  raw: string,
  labels: Record<string, Place> | undefined,
): { place: Place; length: number } | null {
  if (!labels) return null;
  let acc = "";
  let best: { place: Place; length: number } | null = null;
  for (const piece of raw.split(/(\s+)/)) { // separators kept so lengths stay exact
    acc += piece;
    if (!piece.trim()) continue;
    const clean = acc.replace(/[^\p{L}\p{N})]+$/u, "");
    const hit = labels[norm(clean)];
    if (hit) best = { place: hit, length: clean.length };
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
      const stop = SEG_END.exec(tail);
      const seg = stop ? tail.slice(0, stop.index) : tail;
      if (!seg.trim()) break;

      // A label is matched against the whole run up to the next arrow, not
      // the punctuation-cut segment, so "Security (personal)" survives its
      // bracket.
      const run = tail.slice(0, /\n|→|->/.exec(tail)?.index ?? tail.length);
      const hit = leadingLabel(run, at.children);
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
      if (!ARROW_RE.test(text.slice(segStart + seg.length))) break;
      end = segStart + seg.trimEnd().length;
      cursor = segStart + seg.length;
    }

    // Nothing was consumed past the head: only some nav words stand alone.
    if (end === headEnd && !head.bare) continue;

    hits.push({ start: m.index, end, href: at.href });
    HEAD_RE.lastIndex = end; // never emit overlapping hits
  }

  return hits;
}
