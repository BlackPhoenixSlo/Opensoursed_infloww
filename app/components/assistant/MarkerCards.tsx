"use client";

/**
 * MarkerCards — an answer's markers (markers.ts) as live cards: each data card
 * reads its figure from the existing report endpoint with the asker's own
 * session, so a role without stats access sees "Not available for your role",
 * never $0, and an unread count that cannot read every model is an error,
 * never a partial sum. A card's value is never written into the answer, so it never
 * reaches the thread's history. A chat marker is a button into the fan's chat
 * once the handle resolves on the turn's model and the session may open
 * Messages Pro; otherwise its handle stays plain text in the answer and nothing
 * renders here.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { usePrincipalId } from "@/hooks/useEmployeeKey";
import { appliedQuery, type AppliedSettings } from "@/lib/appliedSettings";
import { fmtCents } from "@/lib/format";
import { fanDeepLinkHref } from "@/lib/nav";
import { relay } from "@/lib/relay";
import {
  METRIC_LABEL, metricPath, WINDOW_LABEL, windowRange,
  type ChatMarker, type DataMarker, type Marker,
} from "./markers";

/** One card's rows: a total, or a short ranked list (`more`: rows past it). */
type Reading = { total: string } | { rows: Array<{ name: string; value: string }>; more?: number };

interface RevenueResp { rows?: Array<{ total_cents?: number | null }> }
interface PerModelResp { per_model?: Array<{ display_name?: string | null; account_id: string; total_revenue_cents?: number | null }> }
interface FanReportResp { top_fans?: Array<{ fan_name?: string | null; username?: string | null; fan_id: number | string; total_cents?: number | null }> }
interface TopTippersResp { rows?: Array<{ fan?: { display_name?: string | null; username?: string | null } | null; fan_id: number | string; total_cents?: number | null }> }

const BG = { priority: "background" as const };
const fan = (name: string | null | undefined, user: string | null | undefined, id: number | string) =>
  name || (user ? `@${user}` : `Fan ${id}`);

const SHOWN = 5;

/** The figure behind one data marker. `account` null = every account the
 *  session may see; `accounts` are those, for the per-account unread count.
 *  Any account failing, or answering no count, fails the whole sum. */
async function read(m: DataMarker, account: string | null, accounts: string[], tz: string | null): Promise<Reading> {
  if (m.metric === "unread") {
    const ids = account ? [account] : accounts;
    const got = await Promise.all(
      ids.map((id) => relay.get<{ chatMessagesCount?: number | null }>("/api/of/v2/users/me", { accountId: id, ...BG })),
    );
    const counts = got.map((r) => r?.chatMessagesCount);
    if (counts.some((c) => typeof c !== "number")) throw new Error("no unread count");
    return { total: (counts as number[]).reduce((a, b) => a + b, 0).toLocaleString("en-US") };
  }
  const path = metricPath(m.metric, windowRange(m.window, tz)!, account);
  switch (m.metric) {
    case "revenue": {
      const r = await relay.get<RevenueResp>(path, BG);
      return { total: fmtCents((r?.rows ?? []).reduce((a, x) => a + (x.total_cents ?? 0), 0)) };
    }
    case "per_model": {
      // The endpoint sorts by revenue, highest first: the card shows the top ones.
      const all = (await relay.get<PerModelResp>(path, BG))?.per_model ?? [];
      return {
        rows: all.slice(0, SHOWN).map((x) => ({ name: x.display_name || x.account_id, value: fmtCents(x.total_revenue_cents ?? 0) })),
        more: Math.max(0, all.length - SHOWN),
      };
    }
    case "top_spenders": {
      const r = await relay.get<FanReportResp>(path, BG);
      return { rows: (r?.top_fans ?? []).slice(0, 5).map((x) => ({ name: fan(x.fan_name, x.username, x.fan_id), value: fmtCents(x.total_cents ?? 0) })) };
    }
    case "top_tippers": {
      const r = await relay.get<TopTippersResp>(path, BG);
      return { rows: (r?.rows ?? []).slice(0, 5).map((x) => ({ name: fan(x.fan?.display_name, x.fan?.username, x.fan_id), value: fmtCents(x.total_cents ?? 0) })) };
    }
  }
}

const statusOf = (e: unknown): number | undefined => (e as { status?: unknown } | null)?.status as number | undefined;

const CARD = "rounded-xl border border-border bg-bg px-3 py-2 text-[13px]";

function DataCard({ marker, account, accounts }: { marker: DataMarker; account: string | null; accounts: string[] | null }) {
  // Wait for the report zone of the card's own account (null: the session's,
  // as the endpoint reads it with no account), so a window is cut once.
  const applied = useQuery<AppliedSettings>(appliedQuery(usePrincipalId(), account));
  const tz = applied.data?.preferences?.report_tz ?? null;
  // "All" unread sums the roster: it waits for it (null while it loads).
  const allUnread = marker.metric === "unread" && !account;
  const q = useQuery({
    queryKey: ["assistant-card", marker.metric, marker.window, account, accounts, tz],
    queryFn: () => read(marker, account, accounts ?? [], tz),
    enabled: !applied.isPending && !(allUnread && !accounts?.length),
    staleTime: 60_000,
    retry: false,
  });
  const title = `${METRIC_LABEL[marker.metric]} · ${WINDOW_LABEL[marker.window]} · ${account ? "This model" : "All models"}`;
  let body;
  if (allUnread && accounts?.length === 0) body = <p className="text-fg-dim">No models connected</p>;
  else if (q.isError) body = <p className="text-fg-dim">{statusOf(q.error) === 403 ? "Not available for your role" : "Couldn't load this right now"}</p>;
  else if (!q.data) body = <p className="text-fg-dim animate-pulse">Loading…</p>;
  else if ("total" in q.data) body = <p className="text-[18px] font-semibold text-fg">{q.data.total}</p>;
  else if (q.data.rows.length === 0) body = <p className="text-fg-dim">Nothing in this window</p>;
  else body = (
    <>
      <ol className="flex flex-col gap-0.5">
        {q.data.rows.map((r, i) => (
          <li key={i} className="flex justify-between gap-3">
            <span className="truncate">{r.name}</span>
            <span className="font-medium text-fg tabular-nums">{r.value}</span>
          </li>
        ))}
      </ol>
      {!!q.data.more && <p className="text-[11px] text-fg-dim">Top {SHOWN} models · {q.data.more} more</p>}
    </>
  );
  return (
    <div className={CARD} data-testid="assistant-data-card">
      <p className="text-[11px] text-fg-dim">{title}</p>
      {body}
    </div>
  );
}

function ChatButton({ marker, account, onNavigate }: { marker: ChatMarker; account: string | null; onNavigate?: () => void }) {
  const q = useQuery({
    queryKey: ["assistant-fan", account, marker.handle.toLowerCase()],
    queryFn: () => relay.get<{ id?: number | string | null }>(`/api/of/v2/users/${encodeURIComponent(marker.handle)}`, { accountId: account, ...BG }),
    enabled: !!account,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const id = q.data?.id;
  if (!account || id == null || id === "") return null;
  return (
    <Link
      href={fanDeepLinkHref(account, id)}
      onClick={onNavigate}
      className="self-start rounded-full border border-border bg-bg px-3 py-1 text-[13px] font-medium text-accent hover:border-accent"
    >
      Open @{marker.handle}&apos;s chat
    </Link>
  );
}

/** The cards under one answer. `focus` is the turn's model (null = General:
 *  a `this` marker then reads every account); `accountIds` null while the
 *  roster loads; `canChat` false (no Messages Pro): no chat buttons. */
export function MarkerCards({
  markers, focus, accountIds, canChat, onNavigate,
}: { markers: Marker[]; focus: string | null; accountIds: string[] | null; canChat: boolean; onNavigate?: () => void }) {
  return (
    <div className="flex flex-col gap-1.5">
      {markers.map((m, i) =>
        m.kind === "chat"
          ? canChat && <ChatButton key={i} marker={m} account={focus} onNavigate={onNavigate} />
          : <DataCard key={i} marker={m} account={m.scope === "this" ? focus : null} accounts={accountIds} />,
      )}
    </div>
  );
}
