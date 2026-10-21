/**
 * UnreadMiniBadge — the unread badge on a Creator tab and a Fan tab, `.mini-badge`
 * (docs/spec/phase-01-window-chrome-tabs.md, Gap table), a pill in Infloww's
 * unread red (`err`, #ff7c71, 2026-10-18 capture) with white text. It brings
 * its own leading space for the tab's accessible name ("Name 3 unread"); a
 * flex row drops whitespace-only text, so it does not show. `count` null is
 * unread with no number known: the badge shows empty.
 *
 * NotifMiniBadge — the Creator tab's second badge, the Creator's OnlyFans
 * notification count in the Notifications button's teal (`--inf-online`),
 * capped at "99+" like Infloww's.
 */

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const PILL = cn(MP.creatorTabs.badge, "inline-flex flex-none items-center justify-center text-white");

export function UnreadMiniBadge({ count }: { count: number | null }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-err")}>
        {count}{count !== null && " "}
        <span className="sr-only">unread</span>
      </span>
    </>
  );
}

export function NotifMiniBadge({ count }: { count: number }) {
  return (
    <>
      {" "}
      <span className={cn(PILL, "bg-[var(--inf-online,var(--color-ok))]")}>
        {count > 99 ? "99+" : count}{" "}
        <span className="sr-only">notifications</span>
      </span>
    </>
  );
}
