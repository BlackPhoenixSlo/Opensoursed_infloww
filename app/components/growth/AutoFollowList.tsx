"use client";

/**
 * AutoFollowList — Infloww's Growth → Auto-follow list: one row per creator
 * with its switch and follow counts, and a details view of the fans it
 * followed (docs/infloww-of-manager-rea.md, Auto-follow). This is the whole
 * page, as in Infloww: no tunables, the switch turns the account's
 * `auto_follow` rule on or off, and a rule it creates follows fans whose
 * subscriptions expired (money gate on). New subscribers are OnlyFans' own
 * "Auto follow back my fans" setting, which the banner points at.
 *
 * Layout (page-parity 13): the legacy header (AutoFollowPage), the body 16px in with no card, the bundle's help
 * strip, "Creator:" and "Auto-follow:" selects with Reset at the right, the antd table with a 32px avatar.
 *
 * Counts: Total and Last followed are lifetime; Today / Yesterday / 7 days /
 * 30 days count from the follow log, cut at midnight in the browser's zone.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { StickyNote } from "lucide-react";

import { ExtraTag } from "@/components/ui/primitives";
import {
  EmptyState, IF_TABLE, IfButton, IfPager, IfRangePicker, IfSelect, IfSwitch, InflowwPageHeader, type IfOption,
} from "@/components/ui/infloww";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { errMsg } from "@/components/growth/_bits";
import {
  useAutoFollowRecords, useAutoFollowStats, useAutoFollowSwitch,
  type AutoFollowStatsRow, type RecordSort,
} from "@/hooks/useAutoFollowList";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { type AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { onPopoutClick } from "@/lib/nav";
import { fmtCents } from "@/lib/format";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const PAGE = 20;

/** The Relay's naive-UTC ISO string → Date. */
function utc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Infloww's "MMMM DD, YYYY hh:mm A", in local time; "-" when none. */
export function formatFollowedAt(iso: string | null): string {
  if (!iso) return "-";
  const d = utc(iso);
  if (Number.isNaN(d.getTime())) return "-";
  const h = d.getHours() % 12 || 12;
  return `${MONTHS[d.getMonth()]} ${pad(d.getDate())}, ${d.getFullYear()} ${pad(h)}:${pad(d.getMinutes())} ${d.getHours() < 12 ? "AM" : "PM"}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  const d = utc(iso);
  return Number.isNaN(d.getTime()) ? "-" : `${MONTHS[d.getMonth()]} ${pad(d.getDate())}, ${d.getFullYear()}`;
}

const usd = fmtCents; // a total: whole dollars

type OnFilter = "all" | "on" | "off";

const ON_FILTERS: IfOption<OnFilter>[] = [
  { value: "all", label: "All" },
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];
/** Reset: antd's default button with M1 text and an M1 outline. */
const RESET = "border-accent text-accent";
/** Infloww's column widths (Total follows 120, Last followed 200, Action 80). */
const W = { total: "w-[120px]", last: "w-[200px]", action: "w-[80px]" };

export default function AutoFollowList({ accounts }: { accounts: AccountMeta[] }) {
  const stats = useAutoFollowStats();
  const sw = useAutoFollowSwitch();
  const [creator, setCreator] = useState<string>("all");
  const [onFilter, setOnFilter] = useState<OnFilter>("all");
  const [details, setDetails] = useState<string | null>(null);

  const byId = useMemo(() => {
    const m = new Map<string, AutoFollowStatsRow>();
    for (const r of stats.data?.rows ?? []) m.set(r.account_id, r);
    return m;
  }, [stats.data]);

  const rows = accounts
    .map((a) => ({ account: a, s: byId.get(a.id) ?? null }))
    .filter(({ account }) => creator === "all" || account.id === creator)
    .filter(({ s }) => onFilter === "all" || (onFilter === "on") === !!s?.on);

  const creators: IfOption[] = [
    { value: "all", label: "All creators" },
    ...accounts.map((a) => ({ value: a.id, label: a.nickname || a.id })),
  ];

  const detailsAccount = accounts.find((a) => a.id === details) ?? null;
  if (detailsAccount) {
    return <AutoFollowDetails account={detailsAccount} stats={byId.get(detailsAccount.id) ?? null} onBack={() => setDetails(null)} />;
  }

  return (
    <div className="space-y-4 p-4">
      <p className="text-[14px] text-fg-dim">Automatically follow fans whose subscriptions have expired</p>
      {/* The bundle's help strip; the sentence is ours (our counts are only Auto-follow's follows). */}
      <div className="flex flex-wrap items-center gap-1 rounded-lg bg-[#b8981a15] px-3 py-2 text-[12px] text-[#b8991a]">
        <StickyNote aria-hidden className="h-4 w-4 shrink-0" />
        <span>
          To also follow fans who just subscribed, turn on &quot;Auto follow back my fans&quot; in OnlyFans
          (Settings → Fans and following). Counts here are only the fans Auto-follow followed.
        </span>
        <ExtraTag />
        <a href="https://help.infloww.com/en/articles/262109-auto-follow" target="_blank" rel="noreferrer"
          className="text-accent hover:underline">Learn more about settings</a>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-6">
          <label className="flex items-center gap-1 text-[14px] text-fg">
            <span>Creator:</span>
            <IfSelect aria-label="Creator" searchable value={creator} options={creators} onChange={setCreator}
              className="w-[212px]" />
          </label>
          <label className="flex items-center gap-1 text-[14px] text-fg">
            <span>Auto-follow:</span>
            <IfSelect aria-label="Auto-follow" value={onFilter} options={ON_FILTERS} onChange={setOnFilter}
              className="w-[212px]" />
          </label>
        </div>
        <IfButton className={RESET} onClick={() => { setCreator("all"); setOnFilter("all"); }}>Reset</IfButton>
      </div>
      {stats.isError && <div className="text-sm text-err">{errMsg(stats.error, "Could not load Auto-follow stats")}</div>}
      {sw.isError && <div className="text-sm text-err">{errMsg(sw.error, "Could not switch Auto-follow")}</div>}
      <div className="overflow-x-auto">
        <table className={cn(IF_TABLE.table, "min-w-[880px]")}>
          <thead>
            <tr>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Creator name</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, W.total)}>Total follows</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Today</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Yesterday</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>7 days</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>30 days</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, W.last)}>Last followed</th>
              <th className={cn(IF_TABLE.th, "sticky right-0", W.action)}>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={8}><EmptyState className="min-h-[400px]" /></td></tr>
            )}
            {rows.map(({ account, s }) => {
              const on = !!s?.on;
              const label = account.nickname || account.id;
              return (
                <tr key={account.id} data-testid={`af-row-${account.id}`}
                  className={cn(IF_TABLE.row, "cursor-pointer hover:bg-bg-elev-2")}
                  onClick={() => setDetails(account.id)}>
                  <td className={IF_TABLE.td}>
                    <span className="flex items-center gap-2">
                      <span className="relative block size-8 shrink-0 overflow-hidden rounded-full">
                        <AccountAvatarPicture account={account} letters={1} initialClassName="text-xs" />
                      </span>
                      {label}
                    </span>
                  </td>
                  <td className={IF_TABLE.td}>{s?.total ?? 0}</td>
                  <td className={IF_TABLE.td}>{s?.today ?? 0}</td>
                  <td className={IF_TABLE.td}>{s?.yesterday ?? 0}</td>
                  <td className={IF_TABLE.td}>{s?.d7 ?? 0}</td>
                  <td className={IF_TABLE.td}>{s?.d30 ?? 0}</td>
                  <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{formatFollowedAt(s?.last_followed_at ?? null)}</td>
                  <td className={cn(IF_TABLE.td, "sticky right-0 bg-bg")} onClick={(e) => e.stopPropagation()}>
                    <IfSwitch aria-label={`Auto-follow ${label}`} checked={on}
                      disabled={sw.isPending || stats.isLoading}
                      onChange={(enable) => sw.mutate({ accountId: account.id, enable })} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const SORTS: Array<{ key: RecordSort; label: string }> = [
  { key: "followed_at", label: "Follow date" },
  { key: "spend", label: "Total spend" },
  { key: "expiry", label: "Expiry date" },
];

/** A local `YYYY-MM-DD` → the ISO instant of that local midnight. */
function localMidnight(day: string, plusDays = 0): string | null {
  if (!day) return null;
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}

export function AutoFollowDetails({ account, stats, onBack }: {
  account: AccountMeta;
  stats?: AutoFollowStatsRow | null;
  onBack: () => void;
}) {
  const [sort, setSort] = useState<RecordSort>("followed_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const q = useAutoFollowRecords(account.id, {
    sort, order, start: localMidnight(from), end: localMidnight(to, 1),
    limit: PAGE, offset: (page - 1) * PAGE,
  });
  const total = q.data?.total ?? 0;

  const sortBy = (key: RecordSort) => {
    if (key === sort) setOrder(order === "desc" ? "asc" : "desc");
    else { setSort(key); setOrder("desc"); }
    setPage(1);
  };

  return (
    <div className="space-y-4 p-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-[14px]">
        <button type="button" className="text-fg-dim hover:text-accent" onClick={onBack}>Auto-Follow</button>
        <span className="text-fg-dim">/</span>
        <span className="font-medium text-fg">Details</span>
        <span className="text-fg-dim">· {account.nickname || account.id}</span>
      </nav>
      {/* The bundle's three figures over the table. */}
      <dl className="flex flex-wrap gap-10">
        {([["Total", stats?.total], ["Today", stats?.today], ["Yesterday", stats?.yesterday]] as const).map(([k, v]) => (
          <div key={k}>
            <dt className="text-[14px] text-fg-dim">{k}</dt>
            <dd className="mt-1 text-[20px] font-medium text-fg">{v ?? 0}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap items-center gap-4">
        <IfRangePicker from={from} to={to} onChange={(r) => { setFrom(r.from); setTo(r.to); setPage(1); }} />
        <IfButton className={RESET} onClick={() => { setFrom(""); setTo(""); setPage(1); }}>Reset</IfButton>
      </div>
      {q.isError && <div className="text-sm text-err">{errMsg(q.error, "Could not load the fans followed")}</div>}
      <div className="overflow-x-auto">
        <table className={cn(IF_TABLE.table, "min-w-[720px]")}>
          <thead>
            <tr>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Fans name</th>
              {(["spend", "expiry", "followed_at"] as RecordSort[]).map((k) => {
                const label = SORTS.find((s) => s.key === k)!.label;
                return (
                  <th key={k} className={cn(IF_TABLE.th, IF_TABLE.thDivider)}
                    aria-sort={sort === k ? (order === "desc" ? "descending" : "ascending") : "none"}>
                    <button type="button" onClick={() => sortBy(k)} className={cn("hover:text-fg", sort === k && "text-fg")}>
                      {label}{sort === k ? (order === "desc" ? " ↓" : " ↑") : ""}
                    </button>
                  </th>
                );
              })}
              <th className={cn(IF_TABLE.th, W.action)}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {!q.isLoading && (q.data?.rows.length ?? 0) === 0 && (
              <tr><td colSpan={5}><EmptyState className="min-h-[400px]" /></td></tr>
            )}
            {(q.data?.rows ?? []).map((r) => (
              <tr key={r.fan_id} className={IF_TABLE.row}>
                <td className={IF_TABLE.td}>
                  {r.name || r.username || r.fan_id}
                  {r.username && r.name && r.name !== r.username && (
                    <span className="text-fg-dim"> @{r.username}</span>
                  )}
                </td>
                <td className={IF_TABLE.td}>{usd(r.total_spend_cents)}</td>
                <td className={IF_TABLE.td}>{formatDate(r.expires_at)}</td>
                <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{formatFollowedAt(r.followed_at)}</td>
                <td className={IF_TABLE.td}>
                  <Link aria-label={`Chat with ${r.name || r.fan_id}`}
                    href={`/messages-pro/${encodeURIComponent(account.id)}/${r.fan_id}`}
                    onClick={(e) => onPopoutClick(e, `/messages-pro/${encodeURIComponent(account.id)}/${r.fan_id}`)}
                    className="text-accent hover:text-accent-hover">Chat</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > PAGE && <IfPager total={total} noun={total === 1 ? "record" : "records"} page={page} size={PAGE} onPage={setPage} />}
    </div>
  );
}

/** /growth/auto-follow: a legacy page with no rail: the 48px header, then the list 16px in. It lists every creator
 *  with its own Creator filter, so it draws (an empty table) with none. */
export function AutoFollowPage() {
  return (
    <div className="flex min-h-full flex-col">
      <InflowwPageHeader title="Auto-follow" />
      <AutoFollowList accounts={useActiveAccounts()} />
    </div>
  );
}
