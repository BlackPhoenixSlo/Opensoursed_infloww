"use client";

/** What the ofMirrorFeeds leaves share, cut from ofMirrorFeeds: the queue's items, routes and row actions, the post shape, the borrowed rows (TEMPLATES), the Agency's time zone and its wall clock. */

import { TZ } from "@/hooks/useScheduledMessages";
import { useAppliedSettings } from "@/lib/appliedSettings";
import type { OFPost } from "@/hooks/usePosts";
import type { OFMedia, OFUserMini } from "@/lib/relay";
import type { CardPost } from "@/lib/ofMirrorPostCard";
import type { Part } from "@/lib/ofMirrorDom";

/** A queue item's post, message or stream: what it shows, and its id and state for the row's actions (ofMirrorQueue). */
interface QueueEntity {
  id?: number | string;
  text?: string | null;
  /** A stream's text (OF's schedule form sends `description`). */
  description?: string | null;
  mediaCount?: number;
  isMediaReady?: boolean;
  isPinned?: boolean;
  /** A message's send time; a queued message with none is saved for later (OF's isSFLMessage). */
  scheduledAt?: string | null;
  /** A post saved for later (OF's isSFLPost). */
  isPublishedWithPeriod?: boolean;
  /** A queued message's audience as OF names it on its card: "user" and the fan's username, or a list's name. */
  sentRulesType?: string;
  sentRulesExtra?: string | null;
}

/**
 * A queue item as its route sends it: `/schedules` and `/schedules/later/*` wrap the post, message or stream (`type`,
 * `publishDateTime`, `entity`), their own `id` the schedule's; a flat item (no `entity`) is its own target.
 */
export interface QueueItem extends QueueEntity {
  type?: string;
  publishDateTime?: string;
  createdDateTime?: string;
  entity?: QueueEntity;
}

/**
 * A /schedules item saved for later, as OF's queue store marks it (app.js schedule module: isSFLMessage, a chat whose
 * entity has no `scheduledAt`; isSFLPost, a post whose entity `isPublishedWithPeriod`).
 */
export function isSavedForLater(i: QueueItem): boolean {
  return (i.type === "chat" && !!i.entity && !i.entity.scheduledAt) || (i.type === "post" && !!i.entity?.isPublishedWithPeriod);
}

export type Month = { start: string; end: string };

/**
 * The month pages' route: the shown month's posts, messages and streams, its days those of `zone` (the Agency's time
 * zone; default the browser's). OF's own tabs add `filter[type]` (read from its queue chunk); the Relay passes no type,
 * so the tabs filter the month's items here (QUEUE_TABS).
 */
export const SCHEDULES = {
  route: (m: Month | null, zone = TZ) => m && `/api/of/v2/schedules?publish_date=${m.start}&publish_date_end=${m.end}&time_zone=${encodeURIComponent(zone)}&limit=50`,
  // A saved-for-later item takes OF's half-tinted sfl- mark (QueueAgenda's itemType, its stylesheet's sfl-*-indicator).
  mark: (i: QueueItem) => (isSavedForLater(i) ? `sfl-${i.type}-indicator` : (({ post: "post-indicator", chat: "chat-indicator", stream: "stream-indicator" })[i.type ?? ""] ?? "")),
  // OF's agenda date: publishDateTime, else createdDateTime.
  at: (i: QueueItem) => i.publishDateTime || i.createdDateTime,
  month: true as const,
};

/**
 * Queue page -> its Relay route (null while the shown month is unknown), its items' colour mark and time (none: saved
 * for later), whether it is a month page (only the shown month's items, of the selected tabs; the selected day's in
 * the right column), and every item's kind when the route sends no `type`.
 */
export const QUEUE: Record<string, { route: (m: Month | null, zone?: string) => string | null; mark: (i: QueueItem) => string; at?: (i: QueueItem) => string | undefined; month?: true; kind?: QueueKind }> = {
  "queue/index": SCHEDULES,
  "queue/state-list-view": SCHEDULES,
  // The Messages tab, and the Messages and Streams tabs, selected: the same month, filtered in place.
  "queue/state-tab-messages": SCHEDULES,
  "queue/state-tab-streams": SCHEDULES,
  "queue/saved-for-later-posts": { route: () => "/api/of/v2/schedules/later/post?limit=50", mark: () => "sfl-post-indicator", kind: "post" },
  "queue/saved-for-later-messages": { route: () => "/api/of/v2/schedules/later/chat?limit=50", mark: () => "sfl-chat-indicator", kind: "chat" },
};

export type QueueKind = "post" | "chat";

/** A queue row's actions, as ofMirrorQueue reads them back from the row's data-oi-queue-* attributes. */
export interface QueueActions {
  kind: QueueKind;
  /** The post or message id: pin, delete. */
  target: string;
  /** The schedule id: "Post now" / "Message now" (empty: a flat item has none). */
  schedule: string;
  /** OF greys "Post now" / "Message now" out until the media is ready. */
  ready: boolean;
  pinned: boolean;
}

/** A queue item's row actions, as OF's ScheduleEventDropdown reads them; null (no menu) unless a post or message with an id. */
export function queueActions(page: string, i: QueueItem): QueueActions | null {
  const kind = i.type ?? QUEUE[page]?.kind;
  const target = i.entity ? i.entity.id : i.id;
  if ((kind !== "post" && kind !== "chat") || target == null) return null;
  const body = i.entity ?? i;
  return { kind, target: String(target), schedule: i.entity && i.id != null ? String(i.id) : "", ready: body.isMediaReady !== false, pinned: !!body.isPinned };
}

/** A `/users/{id}/posts` item; its media in the Relay's media shape (what `stillUrl` reads). */
export type MirrorPost = Omit<OFPost, "media" | "preview"> & CardPost & {
  media?: OFMedia[];
  /** A bookmarked or home feed post's own author (only `id` when the Relay skips users). */
  author?: OFUserMini;
  /** The Creator has liked it; OF's like button can toggle it (false on the Creator's own posts). */
  isFavorite?: boolean;
  canToggleFavorite?: boolean;
  /** OF's Comment is enabled only with it (a list's stub posts lack it). */
  canComment?: boolean;
};

export type Template = "post" | "agenda" | "payoutRow" | "chatList" | "listRow";

/**
 * Rows borrowed from another captured page, for a Part whose page captures none: the page (under of-mirror/pages) and
 * how to pick the row there. useOfData fetches the page same-origin and passes the row in `MirrorData.templates`.
 */
export const TEMPLATES: Partial<Record<Template, { parts: Part[]; page: string; pick: (doc: Document) => Element | undefined }>> = {
  post: {
    parts: ["bookmarks", "home", "listPosts"],
    page: "profile/index",
    pick: (d) => [...d.querySelectorAll(".vue-recycle-scroller__item-view")].find((v) => v.querySelector("div.b-post")),
  },
  agenda: {
    parts: ["queue"],
    page: "queue/state-list-view",
    pick: (d) => {
      const block = d.querySelector(".b-queue-scroll-wrapper");
      block?.querySelector(".empty-message")?.remove();
      return block ?? undefined;
    },
  },
  // A chat's Gallery and Pinned tabs were captured with no chat in their list: the Messages page's list (its hidden row).
  chatList: {
    parts: ["chatList"],
    page: "messages/index",
    pick: (d) => d.querySelector(".b-chats__list-dialogues > .vue-recycle-scroller") ?? undefined,
  },
  // Following and its tabs were captured with no user list row: Collections' (its hidden list row).
  listRow: {
    parts: ["listRow"],
    page: "collections/index",
    pick: (d) => [...d.querySelectorAll(".b-user-lists__list .vue-recycle-scroller__item-view")].find((v) => v.querySelector(".b-rows-lists__item")),
  },
  payoutRow: {
    parts: ["referrals"],
    page: "statements/payouts",
    pick: (d) => [...d.querySelectorAll(".b-table tbody tr")].find((r) => r.querySelector(".b-table__date") && r.querySelector("span.approved")),
  },
};

/** "May 20, 2025": OF's date of a post before this year. */
export const fullDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/** The Agency's time zone (the top bar's, `preferences.tz`), else the browser's: the queue's days and today, Statements' Earnings' dates. */
export const useAgencyZone = (): string => useAppliedSettings().data?.preferences?.tz || TZ;

/**
 * `at` as the wall clock of `zone` reads it, as a local Date (its getDate, getHours and so on are the zone's): the
 * queue's days, times and today follow the Agency's time zone, not the browser's. No zone, or one Intl does not know:
 * `at` as is.
 */
export function wallClock(at: Date, zone?: string): Date {
  if (!zone) return at;
  try {
    const opts = { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" } as const;
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", opts).formatToParts(at).map((x) => [x.type, Number(x.value)]));
    return new Date(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second);
  } catch {
    return at;
  }
}

/** The instant whose wall clock in `zone` is `wall`'s local fields (wallClock's inverse; two steps settle a DST edge). */
export function fromWallClock(wall: Date, zone?: string): Date {
  let at = wall;
  for (let i = 0; i < 2; i++) at = new Date(at.getTime() - (wallClock(at, zone).getTime() - wall.getTime()));
  return at;
}
