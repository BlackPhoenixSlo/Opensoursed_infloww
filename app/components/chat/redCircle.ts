/**
 * The Creator tab's Red circle (docs/spec/creator-badges/phase-0B-red-circle-from-ws-counter.md, Display): the one
 * place the display rule lives. Pure.
 *
 * `slot` is the Creator's `values.unread_total` from the Freshness store: undefined (the Knob off, nothing held) or
 * null (a non-OF Creator, no OF counter) take the route's count by the same rule. The Relay decides grey (`slot.grey`,
 * drawn grey whatever `n` is); the app's only local cause is the Relay/SSE unreachable, which also covers the route's
 * first read not yet settled. n <= 0: none; 1–8: the digit; >= 9: "9+".
 */

import type { FreshnessValues } from "@/lib/creatorFreshness";

type Slot = FreshnessValues["unread_total"];

export type RedCircle =
  | { kind: "none" }
  | { kind: "count"; text: string; n: number }
  | { kind: "grey"; reason: string };

const UNREACHABLE: RedCircle = { kind: "grey", reason: "relay_unreachable" };

function draw(n: number): RedCircle {
  if (n <= 0) return { kind: "none" };
  return { kind: "count", text: n >= 9 ? "9+" : String(n), n };
}

export function redCircle(slot: Slot, relayReachable: boolean, routeCount: number | undefined, settled: boolean): RedCircle {
  if (!relayReachable) return UNREACHABLE;
  if (slot === undefined || slot === null) return settled ? draw(routeCount ?? 0) : UNREACHABLE;
  if (typeof slot.grey === "string") return { kind: "grey", reason: slot.grey };
  return typeof slot.n === "number" && Number.isFinite(slot.n) ? draw(slot.n) : { kind: "grey", reason: "unknown" };
}

/** The number "Most unread first" sorts by: the circle's, grey as 0. */
export const shownUnread = (c: RedCircle): number => (c.kind === "count" ? c.n : 0);

export function circleTitle(c: RedCircle): string {
  if (c.kind === "grey") return "unread count unknown";
  return `${c.kind === "count" ? c.text : 0} unread`;
}
