"use client";

/**
 * /analytics/message-dashboard — Analytics > "Message dashboard" (formerly the
 * "Stuff" page at /messages, which redirects here): the money surfaces in one place.
 *
 * Old /messages?tab=… / ?fan_id=… deep links keep working: next.config.ts
 * redirects /messages here and the query string rides along.
 *
 * Infloww's surface first (page-parity ticket 30, bundle `MessageReport$1`): the legacy header (title, the report
 * time zone's UTC offset, Learn), then the tabs Direct messages (the default) and OnlyFans mass messages, each the
 * staged filter form over an eleven-column table (AllMessagesTab with `kind`). Infloww's alert "displays data for
 * direct messages only" is not copied: ours shows mass messages too.
 *
 * Then, after a divider and the Inflowwww extra tag, our tabs, keys unchanged:
 *   • PPV  — outbound priced messages, list view with infinite scroll.
 *            Reads /admin/paid-messages (messages table only, no tx join).
 *   • Tips — tip transactions list. Reads /admin/tips-list directly off
 *            the transactions table (no view dependency — synthesis §2.9).
 *   • All  — all messages (inbound + outbound, free + paid), the cards view
 *            with "Group mass sends". Owns its CSV export.
 *   • Customs — the owed-customs queue: a fan tipped for a voice note and has
 *            not been sent one. Live and cross-account: it ignores the page's
 *            date range, since a debt does not stop being owed because it fell
 *            out of a 30-day window. `/customs` redirects in.
 *   • Posts / My Feed / Top Posts — the feed side of the same window.
 *
 * URL state: `?tab=direct|mass|ppv|tips|all|customs|posts|myfeed|top` (none = direct) + `?fan_id=<n>`, which fills
 * Direct messages' Sent to (and filters the All tab, as before).
 *
 * Right rail: TopTippersCard, on PPV, Tips and All only (Infloww's tabs are full width). Clicking a row sets
 * `tippersPreset`, which TipsTab adopts as its fan_query filter, and switches to Tips. Its totals include pending
 * (uncleared) tips.
 *
 * Date range owned at the page level, in the report time zone (useReportRange, the last 30 days to start with).
 */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import DateRangePicker, { type RangePreset } from "@/components/stats/DateRangePicker";
import { IfBody, IfLearn, IfTabs, InflowwPageHeader, type IfOption } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import AllMessagesTab from "@/components/messages/AllMessagesTab";
import CustomsTab from "@/components/messages/CustomsTab";
import MyFeedTab from "@/components/messages/MyFeedTab";
import PaidMessagesTab from "@/components/messages/PaidMessagesTab";
import PostsTab from "@/components/messages/PostsTab";
import TipsTab from "@/components/messages/TipsTab";
import TopPostsTab from "@/components/messages/TopPostsTab";
import TopTippersCard from "@/components/messages/TopTippersCard";
import { useReportRange } from "@/hooks/useReportRange";
import { MESSAGE_DASHBOARD_TABS as TABS, type MessageDashboardTab as Tab } from "@/lib/pageTabs";
import { cn } from "@/lib/utils";

const TAB_KEYS = new Set<string>(TABS.map((t) => t.key));
const DEFAULT_TAB: Tab = "direct";
/** Infloww's two, then ours behind the extra tag. */
const INFLOWW_TABS: IfOption<Tab>[] = TABS.slice(0, 2).map((t) => ({ value: t.key, label: t.label }));
const EXTRA_TABS: IfOption<Tab>[] = TABS.slice(2).map((t) => ({ value: t.key, label: t.label }));
/** Our tabs that keep the Top tippers rail. */
const RAIL_TABS = new Set<Tab>(["ppv", "tips", "all"]);

const LEARN_TIP =
  "Every message sent from your Creators' chats: who sent it, its price, whether the fan bought it and how fast the "
  + "reply came. Direct messages lists one-to-one sends; OnlyFans mass messages lists each broadcast once. Set the "
  + "filters, then Search. Purchases count as recorded, pending (uncleared) ones included.";

function parseTab(raw: string | null): Tab {
  return raw != null && TAB_KEYS.has(raw) ? (raw as Tab) : DEFAULT_TAB;
}

export default function MessagesPage() {
  // useSearchParams suspends in Next 14+; wrap the body in Suspense so the
  // page can render the static header while it resolves.
  return (
    <Suspense fallback={<div className="max-w-shell mx-auto p-3 sm:p-6 text-sm text-fg-dim">Loading…</div>}>
      <MessagesPageInner />
    </Suspense>
  );
}

function MessagesPageInner() {
  const router = useRouter();
  const search = useSearchParams();

  const { preset, from, to, fromIso, toIso, reportTz, ready, handleRange } = useReportRange();
  const [tab, setTabState] = useState<Tab>(() => parseTab(search.get("tab")));
  const [fanId, setFanIdState] = useState<number | null>(() => {
    const raw = search.get("fan_id");
    const n = raw != null ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  });

  // Mirror URL → state when the user navigates via browser back/forward.
  // We intentionally don't reverse-sync state → URL on every keystroke;
  // only the explicit tab/fan setters push back to the URL so a typing
  // user doesn't see history entries pile up.
  useEffect(() => {
    setTabState(parseTab(search.get("tab")));
    const raw = search.get("fan_id");
    const n = raw != null ? Number(raw) : NaN;
    setFanIdState(Number.isFinite(n) ? n : null);
  }, [search]);

  const updateUrl = useCallback(
    (next: { tab?: Tab; fanId?: number | null }) => {
      const qs = new URLSearchParams(search.toString());
      if (next.tab !== undefined) {
        if (next.tab === DEFAULT_TAB) qs.delete("tab");
        else qs.set("tab", next.tab);
      }
      if (next.fanId !== undefined) {
        if (next.fanId == null) qs.delete("fan_id");
        else qs.set("fan_id", String(next.fanId));
      }
      const qsStr = qs.toString();
      router.replace(qsStr ? `/analytics/message-dashboard?${qsStr}` : "/analytics/message-dashboard", { scroll: false });
    },
    [router, search],
  );

  const setTab = (t: Tab) => {
    setTabState(t);
    updateUrl({ tab: t });
  };
  const clearFanId = () => {
    setFanIdState(null);
    updateUrl({ fanId: null });
  };

  // Object-wrapped so re-setting the same username still bumps the
  // useEffect inside TipsTab. `value` is the username; `nonce` ensures
  // a fresh reference even when the user clicks the same row twice.
  const [tippersPreset, setTippersPreset] = useState<{
    value: string;
    nonce: number;
  } | null>(null);

  const onSelectFan = (username: string) => {
    setTab("tips");
    setTippersPreset((prev) => ({
      value: username,
      nonce: (prev?.nonce ?? 0) + 1,
    }));
  };

  // Memoized so AllMessagesTab's `useMemo(params, …)` keeps a stable
  // reference when neither fanId nor the clearer changed.
  const onClearFanId = useMemo(() => () => clearFanId(), [clearFanId]);

  // The window label feeds TopTippersCard; matches the date-range preset
  // wording the user picked so the leaderboard doesn't lie about its
  // window when the picker shows "Last 30 days."
  const windowLabel = preset === "custom"
    ? from && to ? `${from} → ${to}` : "custom window"
    : presetLabel(preset);

  const picker = <DateRangePicker from={from} to={to} preset={preset} onChange={handleRange} timeZone={reportTz} />;
  const infloww = tab === "direct" || tab === "mass";
  const rail = RAIL_TABS.has(tab);

  return (
    <div className="max-w-shell mx-auto min-w-0">
      <InflowwPageHeader title="Message dashboard" utc={reportTz} actions={<IfLearn tip={LEARN_TIP} />} />

      <div className="overflow-x-auto no-scrollbar">
        <IfTabs
          aria-label="Message dashboard"
          tabs={INFLOWW_TABS}
          value={tab}
          onChange={setTab}
          // The extras follow Infloww's two tabs directly, not at the bar's right.
          className="min-w-max [&>div:last-child]:ml-0 [&>div:last-child]:self-stretch"
          extra={
            <>
              <span aria-hidden className="h-4 w-px bg-border" />
              <ExtraTag />
              <IfTabs aria-label="Inflowwww extras" tabs={EXTRA_TABS} value={tab} onChange={setTab}
                className="h-full border-b-0 px-0" />
            </>
          }
        />
      </div>

      <IfBody className="space-y-4">
        {!infloww && <div className="flex justify-end">{picker}</div>}
        {ready && (
          <div className={cn("grid grid-cols-1 gap-5", rail && "lg:grid-cols-[1fr_320px]")}>
            <div className="min-w-0">
              {infloww && (
                <AllMessagesTab
                  key={`${tab}:${fanId ?? ""}`}
                  kind={tab}
                  from={fromIso}
                  to={toIso}
                  fanId={tab === "direct" ? fanId : null}
                  reportTz={reportTz}
                  range={picker}
                />
              )}
              {tab === "ppv" && <PaidMessagesTab from={fromIso} to={toIso} />}
              {tab === "tips" && (
                <TipsTab
                  from={fromIso}
                  to={toIso}
                  presetFanQuery={tippersPreset?.value ?? null}
                  // The nonce isn't a prop on TipsTab itself; bumping the
                  // key forces a remount on duplicate clicks so the preset
                  // useEffect re-runs even when the same username is picked.
                  key={`tips:${tippersPreset?.nonce ?? 0}`}
                />
              )}
              {tab === "all" && (
                <AllMessagesTab
                  from={fromIso}
                  to={toIso}
                  fanId={fanId}
                  onClearFanId={onClearFanId}
                />
              )}
              {tab === "customs" && <CustomsTab />}
              {tab === "posts" && <PostsTab />}
              {tab === "myfeed" && <MyFeedTab />}
              {tab === "top" && <TopPostsTab from={fromIso} to={toIso} />}
            </div>
            {rail && (
              <aside className="space-y-3 order-first md:order-none">
                <TopTippersCard
                  from={fromIso}
                  to={toIso}
                  onSelectFan={onSelectFan}
                  windowLabel={windowLabel}
                />
              </aside>
            )}
          </div>
        )}
      </IfBody>
    </div>
  );
}

function presetLabel(p: RangePreset): string {
  switch (p) {
    case "day": // never offered on this page; the picker's shared RangePreset type needs it
      return "today";
    case "7d":
      return "last 7 days";
    case "30d":
      return "last 30 days";
    case "90d":
      return "last 90 days";
    case "365d":
      return "last 365 days";
    case "custom":
      return "custom";
  }
}
