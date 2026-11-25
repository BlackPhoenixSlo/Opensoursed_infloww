import type { CreatorFreshnessState, Freshness } from "@/lib/creatorFreshness";
import { sessionConnectivity } from "@/lib/sessionConnectivity";
import type { BadgeSource } from "./unreadBadge";

// The pump's own "really worked" bar: routine reconnects and restart waves never show the mark.
export const DOWN_GRACE_MS = 60_000;

// Healthy confirmation lag: ping 20 s + queue wait 10 s + OF read ~10 s.
export const SLACK_MS = 40_000;

export interface LiveMark {
  kind: "down" | "dead";
  text: string;
  title: string;
  srText: string;
}

const DEAD_LABEL = sessionConnectivity({ session_dead_at: "flagged", has_session: true, is_active: true })!.label;
const DEAD: LiveMark = { kind: "dead", text: DEAD_LABEL, title: DEAD_LABEL, srText: DEAD_LABEL.toLowerCase() };
const DOWN_TEXT = "No live connection";

export function liveMark(
  facts: Pick<Freshness, "live" | "live_since"> | null | undefined, isDead: boolean, tabNow: number, offset: number,
): LiveMark | null {
  const live = facts?.live ?? null;
  if (live === null ? isDead : live === "dead") return DEAD;
  if (live !== "down" || facts?.live_since == null) return null;
  const downMs = tabNow - offset - facts.live_since;
  if (downMs < DOWN_GRACE_MS) return null;
  return {
    kind: "down",
    text: DOWN_TEXT,
    title: `${DOWN_TEXT} for ${Math.floor(downMs / 60_000)} min: new messages may arrive late`,
    srText: DOWN_TEXT.toLowerCase(),
  };
}

export interface BadgeAge {
  ageMs: number;
  late: number;
  of: number;
  text: string;
  title: string;
}

const MIN_MS = 60_000;

export function asOfText(ageMs: number): string {
  const mins = Math.floor(Math.max(0, ageMs) / MIN_MS);
  if (mins < 60) return `as of ${mins} min`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `as of ${hrs} h`;
  return `as of ${Math.floor(hrs / 24)} d`;
}

const cycleText = (cycleS: number) => (cycleS % 60 === 0 ? `${cycleS / 60} min` : `${cycleS} s`);

export function badgeAge(
  sources: readonly BadgeSource[], creators: CreatorFreshnessState | undefined, dead: ReadonlySet<string>,
  tabNow: number, offset: number,
): BadgeAge | null {
  const relayNow = tabNow - offset;
  let of = 0;
  let late = 0;
  let oldest = 0;
  let oldestCycle = 0;
  for (const s of sources) {
    const f = creators?.[s.account_id];
    if (!f || s.at === null || f.cycle_s == null) continue;
    const live = f.live ?? null;
    if (live === null ? dead.has(s.account_id) : live === "dead") continue;
    of++;
    const ageMs = Math.max(0, relayNow - s.at);
    if (ageMs <= f.cycle_s * 1000 + SLACK_MS) continue;
    late++;
    if (ageMs > oldest) { oldest = ageMs; oldestCycle = f.cycle_s; }
  }
  if (late === 0) return null;
  const ago = `As of ${Math.floor(oldest / MIN_MS)} min ago`;
  const title = of === 1
    ? `${ago}: not refreshed within its ${cycleText(oldestCycle)} Cycle`
    : `${ago}: ${late} of ${of} Creators not refreshed within its Cycle`;
  return { ageMs: oldest, late, of, text: asOfText(oldest), title };
}
