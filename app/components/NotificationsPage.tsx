"use client";


import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, Settings } from "lucide-react";

import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { useMarkAllOfNotifsRead } from "@/hooks/useOfNotifCount";
import { dispatchNotifCleared } from "@/lib/notifSettings";
import { IfBody, IfButton, IfTabs, InflowwPageHeader } from "@/components/ui/infloww";
import {
  FILTERS,
  FeedStatus,
  NOTIF_ALL_CAP,
  NOTIF_PAGE_SIZE,
  NoSessionsNote,
  Row as NotificationRow,
  useAccountLabelMap,
  useNotificationFeed,
} from "@/components/NotificationBell";

const NOT_WIRED_TABS: ReadonlySet<string> = new Set(["tip"]);
const NOT_WIRED = "not wired";

const TABS = FILTERS.map((f) => {
  const notWired = NOT_WIRED_TABS.has(f.id);
  return { value: f.id, label: f.label, disabled: notWired, title: notWired ? NOT_WIRED : undefined };
});

export default function NotificationsPage() {
  const router = useRouter();
  const activeAccounts = useActiveAccounts();
  const accountsLoading = useAccounts().isLoading;
  const [filter, setFilter] = useState(FILTERS[0]);
  const [pages, setPages] = useState<Record<string, number>>({});
  const pick = (id: string) => {
    const f = FILTERS.find((x) => x.id === id);
    if (!f || NOT_WIRED_TABS.has(f.id)) return;
    setFilter(f);
    setPages({});
  };
  const back = () => {
    if (window.history.length <= 1) router.push("/");
    else router.back();
  };

  const pageable = filter.type !== null;
  const feed = useNotificationFeed(filter.type, true, pageable ? pages : undefined);
  const targetAccountIds = feed.accountIds;
  const accountLabel = useAccountLabelMap(activeAccounts);
  const merged = pageable ? feed.rows : feed.rows.slice(0, NOTIF_ALL_CAP);
  const anyLoading = feed.loading || accountsLoading;
  const firstError = feed.error;
  const lastOffset = (aid: string) => ((pages[aid] ?? 1) - 1) * NOTIF_PAGE_SIZE;
  const fullCreators = feed.reads
    .filter((r) => r.offset === lastOffset(r.accountId) && (r.count ?? 0) >= NOTIF_PAGE_SIZE)
    .map((r) => r.accountId);
  const hasMore = pageable && !anyLoading && !firstError && fullCreators.length > 0;
  // Unverified: whether OnlyFans honours `offset`; the relay forwards it and keys its cache by it.
  const loadMore = () => setPages((prev) => {
    const next = { ...prev };
    for (const aid of fullCreators) next[aid] = (prev[aid] ?? 1) + 1;
    return next;
  });
  const showAccountTag = targetAccountIds.length > 1;
  const { marking, markAll, status: markStatus } = useMarkAllOfNotifsRead();
  const liveIds = targetAccountIds.filter((aid) => !activeAccounts.some((a) => a.id === aid && a.session_dead_at));
  // Arrival badges clear only once every write landed; a failed one leaves them.
  const markAllRead = async () => {
    if (await markAll(liveIds)) dispatchNotifCleared();
  };

  return (
    <div className="min-w-0">
      <InflowwPageHeader
        title="Notifications"
        onBack={back}
        actions={(
          <>
            <IfButton disabled={marking || liveIds.length === 0} onClick={() => void markAllRead()}
              aria-label="Mark all read" className="max-sm:w-8 max-sm:px-0">
              <CheckCheck aria-hidden className="h-4 w-4 sm:hidden" />
              <span className="max-sm:hidden">Mark all read</span>
            </IfButton>
            {markStatus && <span role="status" className="text-xs text-err">{markStatus}</span>}
            <button
              type="button"
              disabled
              title={NOT_WIRED}
              aria-label="Notification settings"
              className="grid h-5 w-5 place-items-center text-fg-dim disabled:cursor-not-allowed"
            >
              <Settings aria-hidden className="h-5 w-5" />
            </button>
          </>
        )}
      />
      <IfTabs aria-label="Notification types" tabs={TABS} value={filter.id} onChange={pick} />

      <IfBody>
        <section className="mx-auto max-w-[1000px]">
          <h2 className="mb-2.5 text-[14px] font-semibold text-fg">OnlyFans notifications</h2>
          {targetAccountIds.length === 0 && accountsLoading ? (
            <FeedStatus loading error={undefined} empty={false} size="page" />
          ) : targetAccountIds.length === 0 ? (
            <NoSessionsNote size="page" />
          ) : (
            <>
              {merged.length > 0 && (
                <div className="overflow-hidden rounded-[12px] bg-bg-elev-1">
                  {merged.map((m, i) => (
                    <NotificationRow
                      key={`${m.accountId}:${m.n.id ?? i}`}
                      size="page"
                      n={m.n}
                      accountId={m.accountId}
                      accountLabel={showAccountTag ? (accountLabel.get(m.accountId) ?? null) : null}
                    />
                  ))}
                </div>
              )}
              <FeedStatus
                size="page"
                loading={anyLoading}
                error={firstError}
                empty={merged.length === 0}
                onRetry={feed.refetch}
              />
              {hasMore && (
                <div className="my-4 text-center">
                  <IfButton onClick={loadMore}>Load more</IfButton>
                </div>
              )}
            </>
          )}
        </section>
      </IfBody>
    </div>
  );
}
