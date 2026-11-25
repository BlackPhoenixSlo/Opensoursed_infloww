export const GO = "go";

export function withSteps(href: string, steps: string[]): string {
  const kept = steps.map((s) => s.trim()).filter((s) => stepLabel(s));
  if (!kept.length) return href;
  const q = new URLSearchParams();
  kept.forEach((s) => q.append(GO, s));
  return `${href}#${q.toString()}`;
}

export function stepsOf(hash: string): string[] {
  const h = hash.replace(/^#/, "");
  if (!h.startsWith(`${GO}=`)) return [];
  return new URLSearchParams(h).getAll(GO).filter((s) => stepLabel(s));
}

const KIND_RE = /\s+(card|tab|tabs|switch|toggle|block|section|view|panel|button|page|field|list|box|strip)$/;

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
