"use client";

/**
 * MassMessagesTab — past mass-message broadcasts, per account.
 *
 * Reads broadcasts from the relay's local cache + offers bulk-cancel
 * actions. Unlike per-chat unsend, mass-message unsend has no edit
 * window — OF reports `canUnsend: true, unsendSeconds: 1000000` on
 * these rows long after the 24h chat window has closed.
 *
 * Bulk actions run client-side over the model chips' scope (massUnsendRules.ts
 * `bulkTargets`; "Hide unsent" never matters); each row's cancel mutation
 * already write-throughs the cache + invalidates the read query, so the UI
 * converges without manual refetch logic.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { Button, Card, ExtraTag } from "@/components/ui/primitives";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useCancelMassMessage,
  useMassMessages,
  useMassQueueProgress,
  useRefreshMassMessages,
} from "@/hooks/useMassMessages";
import { SM, SM_MASS_COLUMNS } from "@/components/growth/smartMessagesControls";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { cn } from "@/lib/utils";

import { AutoUnsendPanel } from "./AutoUnsendPanel";
import { MassMessageRowItem } from "./MassMessageRow";
import { BULK_ACTIONS, bulkCounts, bulkTargets, visibleMassRows, type BulkAction } from "./massUnsendRules";

const RANGE_OPTIONS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
  { label: "Last 365 days", days: 365 },
];

/** Concurrency cap for bulk cancels. Each cancel is one OF request +
 *  one DB update — small enough to run a few in parallel, large
 *  enough to be polite. */
const BULK_CHUNK = 4;

export default function MassMessagesTab() {
  const accounts = useActiveAccounts();
  const accountIds = useMemo(() => accounts.map((a) => a.id), [accounts]);
  const [daysBack, setDaysBack] = useState(30);
  const [hideUnsent, setHideUnsent] = useState(true);
  // Multi-select model filter. Empty set = no filter (show all). Otherwise
  // restrict to the accounts in the set. Bulk actions inherit this scope.
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [bulkRunning, setBulkRunning] = useState<string | null>(null);

  const { rows, isLoading, isFetching, error } = useMassMessages(accountIds, { daysBack });
  const cancelM = useCancelMassMessage();
  const refreshM = useRefreshMassMessages();
  // Broadcasts OF is still delivering; each one's finish refreshes its Creator's rows.
  const sending = useMassQueueProgress(accountIds, daysBack);
  // The Sent date & time column reads in the report time zone, as the bundle's does.
  const reportTz = useAppliedSettings().data?.preferences?.report_tz ?? null;

  const refresh = () => {
    if (accountIds.length === 0) return;
    refreshM.mutate({ accountIds, daysBack });
  };

  // First-mount auto-warm: if the cache is empty for this account/range,
  // fire a refresh so the user doesn't sit on an empty list.
  const autoRefreshedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (isLoading || isFetching || refreshM.isPending) return;
    if (accountIds.length === 0) return;
    if (rows.length > 0) return;
    const key = `${daysBack}|${accountIds.join(",")}`;
    if (autoRefreshedRef.current.has(key)) return;
    autoRefreshedRef.current.add(key);
    refreshM.mutate({ accountIds, daysBack });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountIds.join(","), daysBack, isLoading, isFetching]);

  // Drop ids from the filter set when the account is no longer active so
  // we don't render an empty list filtered by a model that's gone.
  useEffect(() => {
    setSelectedModels((prev) => {
      if (prev.size === 0) return prev;
      const live = prev.size > 0 ? new Set([...prev].filter((id) => accountIds.includes(id))) : prev;
      return live.size === prev.size ? prev : live;
    });
  }, [accountIds]);

  const refreshing = isFetching || refreshM.isPending;

  const accountName = (id?: string) =>
    accounts.find((a) => a.id === id)?.nickname || id || "?";

  // Filter visible rows by selected models. Empty set = show everything.
  // Bulk actions share the model chips' scope (not the "Hide unsent" box).
  const visibleRows = useMemo(
    () => visibleMassRows(rows, selectedModels, hideUnsent),
    [rows, selectedModels, hideUnsent],
  );

  /** Run cancel mutations across a target subset of rows, in small
   *  parallel batches, with one combined confirmation up front. */
  async function bulkCancel(actionKey: BulkAction, label: string) {
    const targets = bulkTargets(rows, selectedModels, actionKey, Date.now());
    if (targets.length === 0) {
      window.alert("Nothing to unsend matches that filter.");
      return;
    }
    const ok = window.confirm(
      `${label}\n\nUnsend ${targets.length} broadcast${targets.length === 1 ? "" : "s"} from EVERY recipient? This can't be undone.`,
    );
    if (!ok) return;
    setBulkRunning(actionKey);
    let failed = 0;
    try {
      for (let i = 0; i < targets.length; i += BULK_CHUNK) {
        const chunk = targets.slice(i, i + BULK_CHUNK);
        const results = await Promise.allSettled(
          chunk.map((r) =>
            cancelM.mutateAsync({ id: r.id, accountId: r.__accountId }),
          ),
        );
        failed += results.filter((res) => res.status === "rejected").length;
      }
    } finally {
      setBulkRunning(null);
    }
    if (failed > 0) {
      window.alert(
        `${failed} of ${targets.length} unsend${targets.length === 1 ? "" : "s"} failed. Those broadcasts may still be live — refresh and retry.`,
      );
    }
  }

  // Counters for the button labels — shows up-front whether each action
  // will do anything before the user clicks.
  const counts = useMemo(
    () => bulkCounts(rows, selectedModels, Date.now()),
    [rows, selectedModels],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Auto-unsend automation — a scheduled `unsend_messages` rule per model.
       *  Hourly sweep that unsends broadcasts older than the set hours, by type
       *  (free text / image / PPV). Leave a type off to keep it forever.
       *  An Inflowwww extra: Infloww has per-message Auto-unsend only, and no
       *  per-Creator sweep by message type (docs/spec/infloww-parity-round-2/
       *  phase-02b-auto-mass-messages.md). */}
      <Card className="order-2 md:order-1">
        <div className="mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-semibold">Auto-unsend (automation)</h2>
            <ExtraTag />
          </div>
          <p className="text-xs text-fg-dim mt-0.5">
            Runs hourly per model. Automatically unsends broadcasts older than the
            chosen hours, by type — leave a type unchecked to keep those forever.
          </p>
        </div>
        <div className="space-y-2.5">
          {accounts.length === 0 && (
            <div className="text-xs text-fg-dim italic">No active models.</div>
          )}
          {accounts.map((a) => (
            <AutoUnsendPanel key={a.id} accountId={a.id} label={a.nickname || a.id} />
          ))}
        </div>
      </Card>

      <Card className="order-1 md:order-2">
        <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
          <div>
            <h2 className="text-base font-semibold">Mass messages</h2>
            <p className="text-xs text-fg-dim mt-0.5">
              Broadcasts already sent. Cancel one to unsend it from EVERY recipient — no 24h edit window for mass sends.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* An Inflowwww extra: the list's own filters, where Infloww's
             *  OF list has the filter bar above it. */}
            <ExtraTag />
            <label className="flex items-center gap-1.5 text-xs text-fg-dim cursor-pointer select-none">
              <input
                type="checkbox"
                checked={hideUnsent}
                onChange={(e) => setHideUnsent(e.target.checked)}
              />
              Hide unsent
            </label>
            <select
              className="text-xs bg-bg-elev-1 border border-border rounded px-2 py-1"
              value={daysBack}
              onChange={(e) => setDaysBack(Number(e.target.value))}
            >
              {RANGE_OPTIONS.map((o) => (
                <option key={o.days} value={o.days}>{o.label}</option>
              ))}
            </select>
            <Button size="sm" variant="secondary" onClick={refresh} disabled={refreshing}>
              <span className={cn("inline-block mr-1", refreshing && "animate-spin")}>↻</span>
              {refreshing ? "Refreshing…" : "Refresh"}
            </Button>
          </div>
        </div>

        {accounts.length > 1 && (
          <div className="flex items-center gap-1.5 flex-wrap mb-3">
            <span className="text-[10px] uppercase tracking-wide text-fg-dim mr-1">Models</span>
            <ExtraTag />
            <button
              type="button"
              onClick={() => setSelectedModels(new Set())}
              className={cn(
                "px-2.5 py-1 rounded-full text-xs border transition-colors",
                selectedModels.size === 0
                  ? "bg-accent text-white border-accent"
                  : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg hover:border-fg-dim",
              )}
            >
              All ({accounts.length})
            </button>
            {accounts.map((a) => {
              const active = selectedModels.has(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() =>
                    setSelectedModels((prev) => {
                      const next = new Set(prev);
                      if (next.has(a.id)) next.delete(a.id);
                      else next.add(a.id);
                      return next;
                    })
                  }
                  className={cn(
                    "px-2.5 py-1 rounded-full text-xs border transition-colors",
                    active
                      ? "bg-accent text-white border-accent"
                      : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg hover:border-fg-dim",
                  )}
                >
                  {a.nickname || a.id}
                </button>
              );
            })}
          </div>
        )}

        {/* Bulk action bar. Disabled when nothing matches so the user
         *  doesn't fire a confirmation just to be told "nothing to do".
         *  An Inflowwww extra: Infloww's OF list unsends one row at a time,
         *  from its Actions column (capture growth-smart-messages#94). */}
        <div className="hidden md:flex items-center gap-2 flex-wrap mb-3 pb-3 border-b border-border">
          <span className="text-[11px] text-fg-dim mr-1">
            Bulk actions ({counts.all} unsendable in view):
          </span>
          <ExtraTag />
          {BULK_ACTIONS.map(({ action, label, confirm, title }) => (
            <Button
              key={action}
              size="sm"
              variant="danger"
              disabled={!!bulkRunning || counts[action] === 0}
              onClick={() => bulkCancel(action, confirm)}
              title={title}
            >
              {bulkRunning === action ? "Unsending…" : `${label} (${counts[action]})`}
            </Button>
          ))}
        </div>

        {error && (
          <div className="text-sm text-err mb-3">
            Failed to load: {error.message}
          </div>
        )}
        {refreshM.error && (
          <div className="text-sm text-err mb-3">
            Refresh failed: {refreshM.error.message}
          </div>
        )}
        {sending.map((q) => (
          <div key={q.queueId} role="status" className="text-sm text-fg-dim mb-3">
            {accountName(q.accountId)}: Sending…
          </div>
        ))}

        {/* The OF child's list as the capture's table (#80 to #94) in a
         *  horizontal scroller, Message pinned left and Actions right as antd
         *  pins them; a container, so the empty line spans its visible width. */}
        <div className="@container overflow-x-auto">
          <table className={cn(IF_TABLE.table, "table-fixed")} style={{ width: TABLE_WIDTH }}>
            <thead>
              <tr>
                {/* The bundle's middle-size head (`IF_TABLE`): 46px on #353535,
                 *  a 1px rule under it and a 1px by 22px divider after every
                 *  column but the last (capture Notes). */}
                {COLUMNS.map((c) => (
                  <th
                    key={c.label}
                    style={{ width: c.width }}
                    className={cn(
                      IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                      c.label === "Message" && "sticky left-0 z-10",
                      c.label === "Actions" && cn(IF_TABLE.fixedRightHead, "z-10 text-center"),
                    )}
                  >
                    {c.label === "Creator" ? (
                      // Ours: the list spans the active Creators, where the
                      // bundle's shows the one picked in the header.
                      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">{c.label}<ExtraTag /></span>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="p-0">
                    {/* The bundle's heights (capture Notes): a 420px box while
                     *  loading; empty, 12px of cell padding and 220px of
                     *  margin above and below the 90px illustration (our
                     *  redrawn art, `EmptyState size="md"`) and the line. */}
                    {isLoading || refreshing ? (
                      <div className="sticky left-0 w-[100cqw] h-[420px] grid place-items-center text-[14px] text-muted">
                        {isLoading ? "Loading…" : "Fetching from OF…"}
                      </div>
                    ) : (
                      <div className="sticky left-0 w-[100cqw]">
                        <EmptyState kind="data" size="md" text={SM.massEmpty.label} className="py-[232px]" />
                      </div>
                    )}
                  </td>
                </tr>
              ) : visibleRows.map((m) => (
                <MassMessageRowItem
                  key={`${m.__accountId}:${m.id}`}
                  m={m}
                  accountLabel={accountName(m.__accountId)}
                  reportTz={reportTz}
                  busy={
                    !!bulkRunning ||
                    (cancelM.isPending && cancelM.variables?.id === m.id)
                  }
                  onCancel={() => {
                    if (!m.__accountId) return;
                    const recip = m.sentCount ?? 0;
                    const msg = recip
                      ? `Unsend this message from ALL ${recip} recipient${recip === 1 ? "" : "s"}? This can't be undone.`
                      : "Unsend this mass message from every recipient? This can't be undone.";
                    if (!confirm(msg)) return;
                    cancelM.mutate({ id: m.id, accountId: m.__accountId });
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/** The capture's OF columns, with our Creator column (an Inflowwww extra)
 *  before Actions. */
const COLUMNS: readonly { label: string; width: number }[] = [
  ...SM_MASS_COLUMNS.slice(0, -1),
  { label: "Creator", width: 200 },
  SM_MASS_COLUMNS[SM_MASS_COLUMNS.length - 1],
];
const TABLE_WIDTH = COLUMNS.reduce((w, c) => w + c.width, 0);
