"use client";


import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import DateRangePicker, { type RangePreset } from "@/components/stats/DateRangePicker";
import { IfBody, IfLearn, IfTabs, InflowwPageHeader, type IfOption } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { TableSkeleton } from "@/components/ui/Skeleton";
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
import { BRAND_NAME } from "@/lib/brand";

const TAB_KEYS = new Set<string>(TABS.map((t) => t.key));
const DEFAULT_TAB: Tab = "direct";
const INFLOWW_TABS: IfOption<Tab>[] = TABS.slice(0, 2).map((t) => ({ value: t.key, label: t.label }));
const EXTRA_TABS: IfOption<Tab>[] = TABS.slice(2).map((t) => ({ value: t.key, label: t.label }));
const RAIL_TABS = new Set<Tab>(["ppv", "tips", "all"]);

const LEARN_TIP =
  "Every message sent from your Creators' chats: who sent it, its price, whether the fan bought it and how fast the "
  + "reply came. Direct messages lists one-to-one sends; OnlyFans mass messages lists each broadcast once. Set the "
  + "filters, then Search. Purchases count as recorded, pending (uncleared) ones included.";

function parseTab(raw: string | null): Tab {
  return raw != null && TAB_KEYS.has(raw) ? (raw as Tab) : DEFAULT_TAB;
}

export default function MessagesPage() {
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

  // object-wrapped so re-picking the same username still bumps the nonce
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

  const onClearFanId = useMemo(() => () => clearFanId(), [clearFanId]);

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
          className="min-w-max [&>div:last-child]:ml-0 [&>div:last-child]:self-stretch"
          extra={
            <>
              <span aria-hidden className="h-4 w-px bg-border" />
              <ExtraTag />
              <IfTabs aria-label={`${BRAND_NAME} extras`} tabs={EXTRA_TABS} value={tab} onChange={setTab}
                className="h-full border-b-0 px-0" />
            </>
          }
        />
      </div>

      <IfBody className="space-y-4">
        {!infloww && <div className="flex justify-end">{picker}</div>}
        {!ready ? <TableSkeleton rows={6} /> : (
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
                  // nonce in key: remount so TipsTab's preset effect re-runs on a repeat pick
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
                {/* totals include pending (uncleared) tips */}
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
    case "day":
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
