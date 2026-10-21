"use client";

/**
 * Fansly Manager > Notifications: the creator's Fansly notification feed and its unread counts, over the Relay's
 * OF routes `/api/of/v2/users/notifications` and `/count`, which the Fansly shim answers from Fansly's
 * `GET /notifications` in OF's shapes (fansly_shim.notifications / notifications_count). A tab filters on the OF type
 * the shim maps each Fansly code to; Fansly answers one page, so the feed is its first 50 rows.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState, IfBody, IfTabs, type IfOption } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

type Tab = "all" | "tip" | "subscribed" | "purchases" | "favorited" | "commented";

interface Notification {
  id: string;
  type: string;
  text: string;
  createdAt: string | null;
  isRead: boolean;
  user: { name?: string; username?: string } | null;
}

/** The shim's unread badge keys (notifications_count); Purchases has none. */
type Counts = Partial<Record<"all" | "tips" | "subscribes" | "hearts" | "comments", number>>;
const COUNT_KEY: Partial<Record<Tab, keyof Counts>> = {
  all: "all", tip: "tips", subscribed: "subscribes", favorited: "hearts", commented: "comments",
};

const TABS: { value: Tab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "tip", label: "Tips" },
  { value: "subscribed", label: "Subscriptions" },
  { value: "purchases", label: "Purchases" },
  { value: "favorited", label: "Likes" },
  { value: "commented", label: "Comments" },
];

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");

export function FanslyNotifications({ accountId }: { accountId: string }) {
  const [tab, setTab] = useState<Tab>("all");
  const countQ = useQuery<Counts>({
    queryKey: ["fansly-manager", "notifications-count", accountId],
    queryFn: () => relay.get<Counts>("/api/of/v2/users/notifications/count", { accountId }),
    staleTime: 30_000,
  });
  const feedQ = useQuery<{ list: Notification[] }>({
    queryKey: ["fansly-manager", "notifications", accountId, tab],
    queryFn: () => relay.get(`/api/of/v2/users/notifications?limit=50${tab === "all" ? "" : `&type=${tab}`}`, { accountId }),
    staleTime: 30_000,
  });
  const tabs: IfOption<Tab>[] = TABS.map((t) => {
    const key = COUNT_KEY[t.value];
    const n = key ? countQ.data?.[key] ?? 0 : 0;
    return {
      value: t.value,
      text: t.label,
      label: (
        <span className="flex items-center gap-1.5">
          {t.label}
          {n > 0 && <span className="rounded-full bg-accent px-1.5 text-[11px] leading-[18px] text-white tabular-nums">{n > 99 ? "99+" : n}</span>}
        </span>
      ),
    };
  });
  const rows = feedQ.data?.list ?? [];

  return (
    <>
      <IfTabs tabs={tabs} value={tab} onChange={setTab} aria-label="Notification type" />
      <IfBody>
        {feedQ.isError ? (
          <EmptyState kind="error" text="Could not load notifications." onRetry={() => void feedQ.refetch()} className="mt-16" />
        ) : feedQ.isPending ? (
          <p className="mt-16 text-center text-[14px] text-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <EmptyState text="No notifications" className="mt-16" />
        ) : (
          <ul className="divide-y divide-border" aria-label="Notifications">
            {rows.map((n) => (
              <li key={n.id} className="flex items-center gap-3 py-3" data-testid="fansly-notification">
                <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-bg-elev-2 text-sm font-semibold text-fg">
                  {(n.user?.name || n.user?.username || "?").trim().slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-fg">{n.text}</span>
                  <span className="block text-[12px] text-muted">{when(n.createdAt)}</span>
                </span>
                <span
                  aria-label={n.isRead ? undefined : "Unread"}
                  className={cn("h-2 w-2 shrink-0 rounded-full", n.isRead ? "invisible" : "bg-accent")}
                />
              </li>
            ))}
          </ul>
        )}
      </IfBody>
    </>
  );
}
