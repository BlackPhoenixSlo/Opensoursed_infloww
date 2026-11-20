/**
 * Data age and the No-live-connection mark (docs/spec/watched-creator-refresher/phase-03-data-age-live-connection-mark.md,
 * Implementation Decisions): pure decisions over a Creator's held Freshness snapshot (lib/creatorFreshness), measured
 * on the Relay's clock. The tab's clock and the offset live in lib/ageClock; hooks/useDataAge joins them.
 *
 * The mark, per Creator tab and "+ Add a Creator" row:
 * - dead: a snapshot whose `live` is not null says "dead"; with no snapshot or `live` null (Fansly) the account's
 *   `session_dead_at` decides. At once, labelled with the Creators page's word (`sessionConnectivity`). A snapshot
 *   "up" beside a stale `session_dead_at` is a re-capture: no mark.
 * - down: `live` "down" for DOWN_GRACE_MS on the Relay's clock (`live_since`), so a routine reconnect or a restart's
 *   reconnect wave never shows it. Never for `live` null (no OnlyFans socket).
 * - else none (no green "live" mark).
 *
 * The Unread chip's age (`badgeAge`), over Phase 2's sources (`unreadBadgeSources` of `badgeUnread`'s `fromTotal`):
 * a Creator is late when it has a source `at`, a known `cycle_s` (its current Cycle) and is no Dead session (the
 * mark's rule), and its age on the Relay's clock is over `cycle_s` + SLACK_MS. The badge speaks for the oldest late
 * Creator; none late → no age, so the Knob off (no snapshot), a Creator never read since boot or not read by design
 * show nothing.
 */

import type { CreatorFreshnessState, Freshness } from "@/lib/creatorFreshness";
import { sessionConnectivity } from "@/lib/sessionConnectivity";
import type { BadgeSource } from "./unreadBadge";

/** How long the Live connection must be down before the mark shows: the pump's own "really worked" bar. */
export const DOWN_GRACE_MS = 60_000;

/** How late a healthy confirmation can reach the tab (ping 20 s + queue wait 10 s + an OF read ~10 s). NEEDS-HUMAN:
 *  D7's letter is "older than one cycle" (slack 0); one constant until the owner rules. */
export const SLACK_MS = 40_000;

/** The tab's clock minus the Relay's, from a Relay time (`now`, epoch ms) and the tab time it arrived at. */
export const serverOffset = (serverMs: number, receivedAt: number): number => receivedAt - serverMs;

export interface LiveMark {
  kind: "down" | "dead";
  /** The short form: "No live connection" / "Disconnected". */
  text: string;
  /** The tooltip. */
  title: string;
  /** The end of the tab's accessible name. */
  srText: string;
}

const DEAD_LABEL = sessionConnectivity({ session_dead_at: "flagged", has_session: true, is_active: true })!.label;
const DEAD: LiveMark = { kind: "dead", text: DEAD_LABEL, title: DEAD_LABEL, srText: DEAD_LABEL.toLowerCase() };
const DOWN_TEXT = "No live connection";

/** The mark for one Creator: `facts` its held snapshot (none: null), `isDead` its account's `session_dead_at`,
 *  `tabNow` the tab's clock, `offset` the tab's clock minus the Relay's (`serverOffset`). */
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
  /** The oldest late Creator's age (ms, Relay clock). */
  ageMs: number;
  /** Late Creators among `of`. */
  late: number;
  /** The Creators the age can speak for (a source `at`, a known Cycle, no Dead session). */
  of: number;
  /** "as of 4 min". */
  text: string;
  /** The tooltip. */
  title: string;
}

const MIN_MS = 60_000;

/** "as of 2 min" / "as of 1 h" / "as of 3 d": whole units, rounded down (the house age units, `fmtAgo`). */
export function asOfText(ageMs: number): string {
  const mins = Math.floor(Math.max(0, ageMs) / MIN_MS);
  if (mins < 60) return `as of ${mins} min`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `as of ${hrs} h`;
  return `as of ${Math.floor(hrs / 24)} d`;
}

const cycleText = (cycleS: number) => (cycleS % 60 === 0 ? `${cycleS / 60} min` : `${cycleS} s`);

/** The Unread chip's age, or null while every counted Creator is within its Cycle. `sources`: Phase 2's
 *  `unreadBadgeSources`; `creators`: the Freshness store (each Creator's Cycle and Live connection); `dead`: the
 *  accounts flagged Dead (`session_dead_at`, read only where the snapshot's `live` is null); `tabNow`, `offset` as
 *  `liveMark`'s. */
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
