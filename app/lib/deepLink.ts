/**
 * deepLink — a link that lands on a part of a page, not just the page.
 *
 * A page's inner tabs, collapsed sections and cards are client state with no
 * route of their own ("Smart Messages → Mass Messages → OF mass messages").
 * Rather than give every one an id and a URL param, a link carries the labels
 * of the steps below its route in the hash, `#go=OF+mass+messages&go=…`, and
 * DeepLinkTarget walks them on the page: each step finds the visible tab,
 * toggle or heading with that label, opens it, and the last one is scrolled to
 * and highlighted. A step that matches nothing stops the walk on the page —
 * never a wrong click. Only tabs, disclosure toggles and <summary> are ever
 * clicked; a heading is only scrolled to.
 *
 * Pure: the help bot's link builder (answerLinks.ts) writes these hashes and
 * the walker reads them; the DOM side is DeepLinkTarget.tsx.
 */

export const GO = "go";

/** `href` with `steps` in its hash; no steps, no hash. */
export function withSteps(href: string, steps: string[]): string {
  const kept = steps.map((s) => s.trim()).filter((s) => stepLabel(s));
  if (!kept.length) return href;
  const q = new URLSearchParams();
  kept.forEach((s) => q.append(GO, s));
  return `${href}#${q.toString()}`;
}

/** The steps a location hash carries, in order; [] for any other hash. */
export function stepsOf(hash: string): string[] {
  const h = hash.replace(/^#/, "");
  if (!h.startsWith(`${GO}=`)) return [];
  return new URLSearchParams(h).getAll(GO).filter((s) => stepLabel(s));
}

/** What the bot calls a part, by its kind: "the Auto-unsend card". */
const KIND_RE = /\s+(card|tab|tabs|switch|toggle|block|section|view|panel|button|page|field|list|box|strip)$/;

/** A label as compared: lowercase, punctuation gone, no leading article or
 *  trailing kind word. "the **Auto-unsend** card" → "auto-unsend". */
export function stepLabel(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^\p{L}\p{N}&'\s-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(the|a|an|its|your)\s+/, "")
    .replace(KIND_RE, "")
    .trim();
}

export type CandidateKind = "tab" | "toggle" | "heading";

export interface Candidate {
  text: string;
  kind: CandidateKind;
}

const KIND_RANK: Record<CandidateKind, number> = { tab: 0, toggle: 1, heading: 2 };

/**
 * The candidate a step means, or -1. Exact label beats a label the element's
 * text starts with ("Auto-unsend" ↔ "Auto-unsend (automation)"); then a tab
 * beats a toggle beats a heading; then page order.
 */
export function pick(candidates: Candidate[], step: string): number {
  const want = stepLabel(step);
  if (!want) return -1;
  let best = -1;
  let bestScore = Infinity;
  candidates.forEach((c, i) => {
    const got = stepLabel(c.text);
    const fit = got === want ? 0 : got.startsWith(`${want} `) ? 1 : -1;
    if (fit < 0) return;
    const score = fit * 10 + KIND_RANK[c.kind];
    if (score < bestScore) {
      best = i;
      bestScore = score;
    }
  });
  return best;
}
