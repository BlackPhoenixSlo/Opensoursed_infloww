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
 * converges without manual refetch logic. The hourly Auto-unsend card is its
 * own Smart Messages tab (`AutoUnsendCard`).
 *
 * Above the card, the capture's OF filter bar (#66 to #79): Search for message and Sending Date filter the
 * loaded rows client side when Search is pressed (or Enter), Reset clears them, Export downloads the listed
 * rows as CSV (`massFilterBar.ts`). The bulk actions act on the filtered rows only. A Sending Date older than
 * the "Sent in" window widens it until Reset, as the cache read takes `days_back` alone (up to 365 days, 100 rows per
 * Creator).
 */

import { useEffect, useMemo, useReducer, useRef, useState } from "react";

import {
  EmptyState, IF_TABLE, IfButton, IfCard, IfHelp, IfInput, IfNativeSelect, IfRangePicker, IfSwitch,
} from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useIfConfirm } from "@/hooks/useIfConfirm";
import {
  useCancelMassMessage,
  useMassMessages,
  useMassQueueProgress,
  useRefreshMassMessages,
} from "@/hooks/useMassMessages";
import { SM, SM_MASS_COLUMNS } from "@/components/growth/smartMessagesControls";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { downloadCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";

import { RefreshButton } from "./RefreshButton";
import { MassMessageRowItem } from "./MassMessageRow";
import { filterMassRows, initialMassFilter, massCsvRows, massFilterReducer, narrowedBy, RANGE_DAYS } from "./massFilterBar";
import { BULK_ACTIONS, bulkCounts, bulkTargets, visibleMassRows, type BulkAction } from "./massUnsendRules";

const RANGE_OPTIONS = RANGE_DAYS.map((days) => ({ label: `Last ${days} days`, days }));

/** What the page shows for a failed refresh / load; the raw error stays in the tooltip and the console. */
const REFRESH_FAILED = "Couldn't refresh from OnlyFans. Check the creator's connection.";
const LOAD_FAILED = "Couldn't load sent mass messages.";

/** Concurrency cap for bulk cancels. Each cancel is one OF request +
 *  one DB update — small enough to run a few in parallel, large
 *  enough to be polite. */
const BULK_CHUNK = 4;

export default function MassMessagesTab() {
  const accounts = useActiveAccounts();
  const accountIds = useMemo(() => accounts.map((a) => a.id), [accounts]);
  const [filter, dispatch] = useReducer(massFilterReducer, initialMassFilter);
  const { daysBack, draft } = filter;
  const [hideUnsent, setHideUnsent] = useState(true);
  // Multi-select model filter. Empty set = no filter (show all). Otherwise
  // restrict to the accounts in the set. Bulk actions inherit this scope.
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [bulkRunning, setBulkRunning] = useState<string | null>(null);
  /** The last bulk unsend's problem (nothing matched, or some failed); cleared by the next one. */
  const [bulkNote, setBulkNote] = useState<string | null>(null);
  const { ask, modal: confirmModal } = useIfConfirm();

  const { rows: loaded, isLoading, isFetching, error, queries } = useMassMessages(accountIds, { daysBack });
  const cancelM = useCancelMassMessage();
  const refreshM = useRefreshMassMessages();
  // Broadcasts OF is still delivering; each one's finish refreshes its Creator's rows.
  const sending = useMassQueueProgress(accountIds, daysBack);
  // The Sent date & time column reads in the report time zone, as the bundle's does.
  const reportTz = useAppliedSettings().data?.preferences?.report_tz ?? null;
  // The filter bar's applied search + Sending Date; everything below (list, counts, bulk) reads these rows.
  const rows = useMemo(() => filterMassRows(loaded, filter.applied, reportTz), [loaded, filter.applied, reportTz]);

  const refreshVia = (vars: { accountIds: string[]; daysBack: number }) =>
    refreshM.mutate(vars, { onError: (e) => console.warn("[mass-messages] refresh failed:", e.message) });
  const refresh = () => {
    if (accountIds.length === 0) return;
    refreshVia({ accountIds, daysBack });
  };

  // First-mount auto-warm: if the cache is empty for this account/range,
  // fire a refresh so the user doesn't sit on an empty list.
  const autoRefreshedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (isLoading || isFetching || refreshM.isPending) return;
    if (accountIds.length === 0) return;
    if (loaded.length > 0) return;
    const key = `${daysBack}|${accountIds.join(",")}`;
    if (autoRefreshedRef.current.has(key)) return;
    autoRefreshedRef.current.add(key);
    refreshVia({ accountIds, daysBack });
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
    setBulkNote(null);
    const targets = bulkTargets(rows, selectedModels, actionKey, Date.now());
    if (targets.length === 0) {
      setBulkNote("Nothing to unsend matches that filter.");
      return;
    }
    const ok = await ask(
      label,
      `Unsend ${targets.length} broadcast${targets.length === 1 ? "" : "s"}${narrowedBy(filter.applied)} from EVERY recipient? This can't be undone.`,
      "Unsend",
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
      setBulkNote(
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
      {/* The OF filter bar (#66, #73, #76, #77, #79), all 32px: fields 12px
       *  apart at the sides (#74), labels 8px from their field (#75), buttons
       *  8px apart (#78). The search box is 230px (#66), Sending Date antd's
       *  250px range. Search (or Enter) applies, Reset clears. */}
      <form
        className="flex flex-wrap items-center"
        onSubmit={(e) => { e.preventDefault(); dispatch({ type: "apply", now: Date.now() }); }}
      >
        <IfInput
          search
          aria-label={SM.search.label}
          placeholder={SM.search.label}
          value={draft.q}
          onChange={(e) => dispatch({ type: "draft", patch: { q: e.target.value } })}
          className="mx-3 mt-4 w-[230px] max-sm:mx-0 max-sm:w-full"
        />
        <div className="mx-3 mt-4 flex max-w-full items-center gap-2 max-sm:mx-0">
          <label htmlFor="sm-mass-sending-date" className="shrink-0 text-[14px] text-fg">{SM.sendingDate.label}</label>
          <IfRangePicker
            id="sm-mass-sending-date"
            from={draft.from}
            to={draft.to}
            onChange={({ from, to }) => dispatch({ type: "draft", patch: { from, to } })}
            className="max-w-full"
          />
        </div>
        <div className="mx-3 mt-4 flex items-center gap-2 max-sm:mx-0">
          <IfButton onClick={() => dispatch({ type: "reset" })}>{SM.reset.label}</IfButton>
          <IfButton type="submit" variant="primary">{SM.searchButton.label}</IfButton>
          <IfButton
            disabled={visibleRows.length === 0}
            title={visibleRows.length === 0 ? "Nothing listed to export" : "Download the listed rows as CSV"}
            onClick={() => downloadCsv(`mass-messages-${new Date().toISOString().slice(0, 10)}.csv`, massCsvRows(visibleRows, accountName))}
          >
            {SM.exportButton.label}
          </IfButton>
        </div>
      </form>
      <IfCard title="Mass messages" extra={(
        <div className="flex items-center gap-3 flex-wrap justify-end">
          {/* An Inflowwww extra: the list's own filters, where Infloww's
           *  OF list has the filter bar above it. */}
          <ExtraTag />
          <IfSwitch label="Hide unsent" checked={hideUnsent} onChange={setHideUnsent} />
          <IfNativeSelect
            aria-label="Sent in"
            value={daysBack}
            onChange={(e) => dispatch({ type: "daysBack", days: Number(e.target.value) })}
          >
            {RANGE_OPTIONS.map((o) => (
              <option key={o.days} value={o.days}>{o.label}</option>
            ))}
          </IfNativeSelect>
          <RefreshButton onClick={refresh} refreshing={refreshing} />
        </div>
      )}>
        <IfHelp className="mb-4">
          Broadcasts already sent. Cancel one to unsend it from EVERY recipient; mass sends have no 24h edit window.
        </IfHelp>

        {accounts.length > 1 && (
          <div className="flex items-center gap-2 flex-wrap mb-4">
            <span className="text-[14px] text-fg-dim">Models</span>
            <ExtraTag />
            <button
              type="button"
              onClick={() => setSelectedModels(new Set())}
              className={cn(
                "px-3 h-7 rounded-full text-[12px] border transition-colors",
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
                    "px-3 h-7 rounded-full text-[12px] border transition-colors",
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
        <div className="hidden md:flex items-center gap-2 flex-wrap mb-4 pb-4 border-b border-border">
          <span className="text-[14px] text-fg-dim">
            Bulk actions ({counts.all} unsendable in view)
          </span>
          <ExtraTag />
          {BULK_ACTIONS.map(({ action, label, confirm, title }) => (
            <IfButton
              key={action}
              className="text-err hover:border-err hover:text-err"
              disabled={!!bulkRunning || counts[action] === 0}
              onClick={() => bulkCancel(action, confirm)}
              title={title}
            >
              {bulkRunning === action ? "Unsending…" : `${label} (${counts[action]})`}
            </IfButton>
          ))}
        </div>

        {bulkNote && <div role="alert" className="text-[14px] text-err mb-3">{bulkNote}</div>}
        {error && (
          <FailLine text={LOAD_FAILED} detail={error.message} onRetry={() => queries.forEach((q) => q.refetch())} />
        )}
        {refreshM.error && <FailLine text={REFRESH_FAILED} detail={refreshM.error.message} onRetry={refresh} />}
        {sending.map((q) => (
          <div key={q.queueId} role="status" className="text-[14px] text-fg-dim mb-3">
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
                  onCancel={async () => {
                    const accountId = m.__accountId;
                    if (!accountId) return;
                    const recip = m.sentCount ?? 0;
                    const msg = recip
                      ? `Unsend this message from ALL ${recip} recipient${recip === 1 ? "" : "s"}? This can't be undone.`
                      : "Unsend this mass message from every recipient? This can't be undone.";
                    if (!(await ask("Unsend mass message", msg, "Unsend"))) return;
                    cancelM.mutate({ id: m.id, accountId });
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      </IfCard>
      {confirmModal}
    </div>
  );
}

/** A failed read's plain line and its Retry; the raw error is the line's tooltip. */
function FailLine({ text, detail, onRetry }: { text: string; detail: string; onRetry: () => void }) {
  return (
    <div role="alert" className="mb-3 flex flex-wrap items-center gap-x-3 text-[14px] text-err">
      <span title={detail}>{text}</span>
      <IfButton variant="link" onClick={onRetry}>Retry</IfButton>
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
