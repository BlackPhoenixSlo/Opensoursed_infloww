/**
 * UnreadMiniBadge — the unread badge on a Creator tab and a Fan tab, `.mini-badge`
 * (docs/spec/phase-01-window-chrome-tabs.md, Gap table), a pill in Infloww's
 * unread red (`err`, #ff7c71, 2026-10-18 capture) with white text. It brings
 * its own leading space for the tab's accessible name ("Name 3 unread"); a
 * flex row drops whitespace-only text, so it does not show. `count` null is
 * unread with no number known: the badge shows empty.
 *
 * GreyMiniBadge — the Creator tab's Grey circle: the unread count is unknown
 * (creator-badges 0B), an empty grey pill, never a blank.
 *
 * OweMiniBadge — the Creator tab's Amber circle (creator-badges 0F), after the
 * unread one: the Fan List's owe-dot amber (`warn`), tinted and ringed so it
 * never reads as the solid red unread; `count` null is its grey form (amber
 * unknown), the Grey circle's fill in the amber ring.
 *
 * NotifMiniBadge — the Creator tab's notification badge, the Creator's OnlyFans
 * notification count in the Notifications button's teal (`--inf-online`),
 * capped at "99+" like Infloww's.
 */

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const PILL = cn(MP.creatorTabs.badge, "inline-flex flex-none items-center justify-center");

export function UnreadMiniBadge({ count }: { count: number | string | null }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-err text-white")}>
        {count}{count !== null && " "}
        <span className="sr-only">unread</span>
      </span>
    </>
  );
}

export function GreyMiniBadge() {
  return (
    <>
      {" "}
      <span data-red-circle="grey" className={cn(PILL, "bg-fg-dim text-white")}>
        <span className="sr-only">unread count unknown</span>
      </span>
    </>
  );
}

export function OweMiniBadge({ count }: { count: string | null }) {
  return (
    <>
      {" "}
      {count === null ? (
        <span data-badge="owe" data-amber-circle="grey" className={cn(PILL, "bg-fg-dim ring-1 ring-inset ring-warn/60")}>
          <span className="sr-only">awaiting reply unknown</span>
        </span>
      ) : (
        <span data-badge="owe" className={cn(PILL, "bg-warn/20 text-warn ring-1 ring-inset ring-warn/60")}>
          {count}{" "}
          <span className="sr-only">awaiting reply</span>
        </span>
      )}
    </>
  );
}

export function NotifMiniBadge({ count }: { count: number }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-[var(--inf-online,var(--color-ok))] text-white")}>
        {count > 99 ? "99+" : count}{" "}
        <span className="sr-only">notifications</span>
      </span>
    </>
  );
}
