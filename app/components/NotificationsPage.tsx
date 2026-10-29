"use client";

/**
 * NotificationsPage — the full page at `/notifications`, reached from the top
 * bar bell's "See all" (docs/spec/phase-05-remaining-parity-gaps.md, stories
 * 40-44): "Back", "Notifications", the section "OnlyFans notifications" and
 * the bell's eight tabs. Infloww has no such web page, so it is our extra drawn
 * in Infloww's legacy page grammar (page-parity ticket 19): the 48px header
 * with a back chevron, the line tabs under it, a centred 1000px column, rows on
 * a #262626 block (`Row size="page"`), and `EmptyState` for empty, no session
 * and error.
 *
 * It reads the bell's feed (`useNotificationFeed`): the bell's tab list
 * (`FILTERS`), request (`notifPath`, `NOTIF_PAGE_SIZE` rows per Creator),
 * Creator scope, query key and its no-session, loading, error and empty
 * states. "All" is the feed merged to `NOTIF_ALL_CAP`; a single-type tab adds
 * "Load more", which reads the next page by `offset` for each Creator whose
 * last page came back full, so a Creator whose feed has ended is not read
 * again.
 *
 * Back is `router.back()`, or `/` when the page has no history to go back to
 * (opened directly or in a new tab).
 *
 * ASSUMPTION: the page opens on "All", not on the bell's saved tab
 * (`readNotifFilterId`), and does not save its own tab, so the page cannot
 * change the bell (rung 4). Overturned if the owner wants the page to open
 * where the bell was left.
 *
 * ASSUMPTION: the page shows the Relay feed only; the bell's browser-side
 * history of toasts (types OnlyFans does not list, arrivals it has not listed
 * yet) is not merged in, so the page can lack rows the bell shows, against
 * story 41's "so that both show the same notifications" (rung 5: the history
 * is per browser and has no offset to page through). Overturned if the owner
 * wants the history on the page, at least on "All".
 *
 * ASSUMPTION (evidence blocked): "Load more" is wired, not Not wired. Observed:
 * the Relay forwards `offset` to OnlyFans and keys its cache by it
 * (`service/server.py` `of_notifications`). Not observed: whether OnlyFans
 * honours `offset` (a live OnlyFans call is off limits). Overturned by a feed
 * that returns page 1 again for `offset=20`: then "Load more" is Not wired.
 *
 * Not wired (ADR-0008): Tips, until its OnlyFans `type` value is settled
 * (connectors ticket 31), and "Mark all read" and the gear, because the
 * Relay has no mark-read endpoint.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, Settings } from "lucide-react";

import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
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

/** Tabs shown but Not wired on this page only: Tips' `type` is unsettled. */
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
  // Pages read per Creator on the current tab (one when absent); a tab
  // change starts every Creator at one.
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
  // Loading until the Creators answer too: with none known yet the feed reads nothing, and "No notifications" would
  // show before the first read.
  const anyLoading = feed.loading || accountsLoading;
  const firstError = feed.error;
  // Creators with more to read: their last page came back full.
  const lastOffset = (aid: string) => ((pages[aid] ?? 1) - 1) * NOTIF_PAGE_SIZE;
  const fullCreators = feed.reads
    .filter((r) => r.offset === lastOffset(r.accountId) && (r.count ?? 0) >= NOTIF_PAGE_SIZE)
    .map((r) => r.accountId);
  const hasMore = pageable && !anyLoading && !firstError && fullCreators.length > 0;
  const loadMore = () => setPages((prev) => {
    const next = { ...prev };
    for (const aid of fullCreators) next[aid] = (prev[aid] ?? 1) + 1;
    return next;
  });
  const showAccountTag = targetAccountIds.length > 1;

  return (
    <div className="min-w-0">
      <InflowwPageHeader
        title="Notifications"
        onBack={back}
        actions={(
          <>
            <IfButton disabled title={NOT_WIRED} aria-label="Mark all read" className="max-sm:w-8 max-sm:px-0">
              <CheckCheck aria-hidden className="h-4 w-4 sm:hidden" />
              <span className="max-sm:hidden">Mark all read</span>
            </IfButton>
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
            // No Creator known yet because the Creators are still loading: the rows' places, not "No active sessions".
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
