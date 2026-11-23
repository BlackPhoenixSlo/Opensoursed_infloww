/**
 * The Creator tab's Amber circle (docs/spec/creator-badges/phase-0F-amber-awaiting-reply.md, Display): Owe reply
 * chats as the Relay publishes them in `values.unread_total.amber`. Pure.
 *
 * The Red circle grey: none (its one grey circle stands for both). `amber` null: grey. No slot or no `amber` key (the
 * Knob off, a non-OF Creator): the route's `owe_reply`. n <= 0: none; 1–8: the digit; >= 9: "9+".
 */

import type { FreshnessValues } from "@/lib/creatorFreshness";
import type { RedCircle } from "./redCircle";

export type AmberCircle =
  | { kind: "none" }
  | { kind: "count"; text: string; n: number }
  | { kind: "grey" };

function draw(n: number): AmberCircle {
  if (!Number.isFinite(n) || n <= 0) return { kind: "none" };
  return { kind: "count", text: n >= 9 ? "9+" : String(n), n };
}

export function amberCircle(
  slot: FreshnessValues["unread_total"], redKind: RedCircle["kind"], routeOwe: number | undefined,
): AmberCircle {
  if (redKind === "grey") return { kind: "none" };
  if (!slot || !("amber" in slot)) return draw(routeOwe ?? 0);
  return typeof slot.amber === "number" ? draw(slot.amber) : { kind: "grey" };
}

export function amberTitle(c: AmberCircle): string {
  if (c.kind === "grey") return "awaiting reply unknown";
  return `${c.kind === "count" ? c.text : 0} awaiting reply`;
}
