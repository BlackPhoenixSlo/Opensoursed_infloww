"use client";


import { TZ } from "@/hooks/useScheduledMessages";
import { useAppliedSettings } from "@/lib/appliedSettings";
import type { OFPost } from "@/hooks/usePosts";
import type { OFMedia, OFUserMini } from "@/lib/relay";
import type { CardPost } from "@/lib/ofMirrorPostCard";
import type { Part } from "@/lib/ofMirrorDom";

interface QueueEntity {
  id?: number | string;
  text?: string | null;
  description?: string | null;
  mediaCount?: number;
  isMediaReady?: boolean;
  isPinned?: boolean;
  scheduledAt?: string | null;
  isPublishedWithPeriod?: boolean;
  sentRulesType?: string;
  sentRulesExtra?: string | null;
}

export interface QueueItem extends QueueEntity {
  type?: string;
  publishDateTime?: string;
  createdDateTime?: string;
  entity?: QueueEntity;
}

export function isSavedForLater(i: QueueItem): boolean {
  return (i.type === "chat" && !!i.entity && !i.entity.scheduledAt) || (i.type === "post" && !!i.entity?.isPublishedWithPeriod);
}

export type Month = { start: string; end: string };

export const SCHEDULES = {
  route: (m: Month | null, zone = TZ) => m && `/api/of/v2/schedules?publish_date=${m.start}&publish_date_end=${m.end}&time_zone=${encodeURIComponent(zone)}&limit=50`,
  mark: (i: QueueItem) => (isSavedForLater(i) ? `sfl-${i.type}-indicator` : (({ post: "post-indicator", chat: "chat-indicator", stream: "stream-indicator" })[i.type ?? ""] ?? "")),
  at: (i: QueueItem) => i.publishDateTime || i.createdDateTime,
  month: true as const,
};

export const QUEUE: Record<string, { route: (m: Month | null, zone?: string) => string | null; mark: (i: QueueItem) => string; at?: (i: QueueItem) => string | undefined; month?: true; kind?: QueueKind }> = {
  "queue/index": SCHEDULES,
  "queue/state-list-view": SCHEDULES,
  "queue/state-tab-messages": SCHEDULES,
  "queue/state-tab-streams": SCHEDULES,
  "queue/saved-for-later-posts": { route: () => "/api/of/v2/schedules/later/post?limit=50", mark: () => "sfl-post-indicator", kind: "post" },
  "queue/saved-for-later-messages": { route: () => "/api/of/v2/schedules/later/chat?limit=50", mark: () => "sfl-chat-indicator", kind: "chat" },
};

export type QueueKind = "post" | "chat";

export interface QueueActions {
  kind: QueueKind;
  target: string;
  schedule: string;
  ready: boolean;
  pinned: boolean;
}

export function queueActions(page: string, i: QueueItem): QueueActions | null {
  const kind = i.type ?? QUEUE[page]?.kind;
  const target = i.entity ? i.entity.id : i.id;
  if ((kind !== "post" && kind !== "chat") || target == null) return null;
  const body = i.entity ?? i;
  return { kind, target: String(target), schedule: i.entity && i.id != null ? String(i.id) : "", ready: body.isMediaReady !== false, pinned: !!body.isPinned };
}

export type MirrorPost = Omit<OFPost, "media" | "preview"> & CardPost & {
  media?: OFMedia[];
  author?: OFUserMini;
  isFavorite?: boolean;
  canToggleFavorite?: boolean;
  canComment?: boolean;
};

export type Template = "post" | "agenda" | "payoutRow" | "chatList" | "listRow";

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
  chatList: {
    parts: ["chatList"],
    page: "messages/index",
    pick: (d) => d.querySelector(".b-chats__list-dialogues > .vue-recycle-scroller") ?? undefined,
  },
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

export const fullDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export const useAgencyZone = (): string => useAppliedSettings().data?.preferences?.tz || TZ;

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

export function fromWallClock(wall: Date, zone?: string): Date {
  let at = wall;
  for (let i = 0; i < 2; i++) at = new Date(at.getTime() - (wallClock(at, zone).getTime() - wall.getTime()));
  return at;
}
