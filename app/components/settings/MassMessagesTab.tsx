"use client";


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
import {
  filterMassRows, initialMassFilter, massCsvRows, massFilterReducer, mayHideOlder, narrowedBy, RANGE_DAYS,
} from "./massFilterBar";
import { BULK_ACTIONS, bulkCounts, bulkTargets, visibleMassRows, type BulkAction } from "./massUnsendRules";
import { bulkStatusLine } from "./bulkUnsendRun";
import { useBulkUnsend } from "./useBulkUnsend";

const RANGE_OPTIONS = RANGE_DAYS.map((days) => ({ label: `Last ${days} days`, days }));

const REFRESH_FAILED = "Couldn't refresh from OnlyFans. Check the creator's connection.";
const LOAD_FAILED = "Couldn't load sent mass messages.";

// OF keeps canUnsend: true (unsendSeconds 1000000) on mass rows long after the 24h chat window; no edit window here.
export default function MassMessagesTab() {
  const accounts = useActiveAccounts();
  const accountIds = useMemo(() => accounts.map((a) => a.id), [accounts]);
  const [filter, dispatch] = useReducer(massFilterReducer, initialMassFilter);
  const { daysBack, draft, hideUnsent, models: selectedModels } = filter;
  // Bulk run lives in the query client so it and its close-tab warning outlive a tab switch.
  const { run: bulk, clear: clearBulk, nothing: nothingToBulk, start: startBulk } = useBulkUnsend();
  const bulkRunning = bulk.running;
  const bulkLine = bulkStatusLine(bulk);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const { ask, modal: confirmModal } = useIfConfirm();

  const { rows: loaded, isLoading, isFetching, error, queries, limit } = useMassMessages(accountIds, { daysBack });
  const cancelM = useCancelMassMessage();
  const refreshM = useRefreshMassMessages();
  const sending = useMassQueueProgress(accountIds, daysBack);
  const reportTz = useAppliedSettings().data?.preferences?.report_tz ?? null;
  const rows = useMemo(() => filterMassRows(loaded, filter.applied, reportTz), [loaded, filter.applied, reportTz]);

  const refreshVia = (vars: { accountIds: string[]; daysBack: number }) =>
    refreshM.mutate(vars, { onError: (e) => console.warn("[mass-messages] refresh failed:", e.message) });
  const refresh = () => {
    if (accountIds.length === 0) return;
    refreshVia({ accountIds, daysBack });
  };

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

  useEffect(() => {
    dispatch({ type: "liveModels", ids: accountIds });
  }, [accountIds]);

  const refreshing = isFetching || refreshM.isPending;

  const accountName = (id?: string) =>
    accounts.find((a) => a.id === id)?.nickname || id || "?";

  const visibleRows = useMemo(
    () => visibleMassRows(rows, selectedModels, hideUnsent),
    [rows, selectedModels, hideUnsent],
  );

  async function bulkCancel(actionKey: BulkAction, label: string) {
    clearBulk();
    const targets = bulkTargets(rows, selectedModels, actionKey, Date.now());
    if (targets.length === 0) {
      nothingToBulk();
      return;
    }
    const ok = await ask(
      label,
      `Unsend ${targets.length} broadcast${targets.length === 1 ? "" : "s"}${narrowedBy(filter.applied, [...selectedModels].map(accountName))} from EVERY recipient? This can't be undone.`,
      "Unsend",
    );
    if (!ok) return;
    await startBulk(actionKey, targets);
  }

  const counts = useMemo(
    () => bulkCounts(rows, selectedModels, now),
    [rows, selectedModels, now],
  );
  const olderHidden = mayHideOlder(
    filter.applied,
    accountIds.flatMap((id, i) => (selectedModels.size === 0 || selectedModels.has(id) ? [queries[i]?.data?.length ?? 0] : [])),
    limit,
  );

  return (
    <div className="flex flex-col gap-4">
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
          <ExtraTag />
          <IfSwitch label="Hide unsent" checked={hideUnsent} onChange={(on) => dispatch({ type: "hideUnsent", on })} />
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
              onClick={() => dispatch({ type: "allModels" })}
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
                  onClick={() => dispatch({ type: "toggleModel", id: a.id })}
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

        {olderHidden && (
          <div className="text-[14px] text-fg-dim mb-3">
            Showing the newest {limit} per Creator: older matches may be hidden.
          </div>
        )}
        {bulkLine && <div role="status" className="text-[14px] text-fg-dim mb-3">{bulkLine}</div>}
        {bulk.note && <div role="alert" className="text-[14px] text-err mb-3">{bulk.note}</div>}
        {error && (
          <FailLine text={LOAD_FAILED} detail={error.message} onRetry={() => queries.forEach((q) => q.refetch())} />
        )}
        {refreshM.error && <FailLine text={REFRESH_FAILED} detail={refreshM.error.message} onRetry={refresh} />}
        {sending.map((q) => (
          <div key={q.queueId} role="status" className="text-[14px] text-fg-dim mb-3">
            {accountName(q.accountId)}: Sending…
          </div>
        ))}

        <div className="@container overflow-x-auto">
          <table className={cn(IF_TABLE.table, "table-fixed")} style={{ width: TABLE_WIDTH }}>
            <thead>
              <tr>
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

function FailLine({ text, detail, onRetry }: { text: string; detail: string; onRetry: () => void }) {
  return (
    <div role="alert" className="mb-3 flex flex-wrap items-center gap-x-3 text-[14px] text-err">
      <span title={detail}>{text}</span>
      <IfButton variant="link" onClick={onRetry}>Retry</IfButton>
    </div>
  );
}

const COLUMNS: readonly { label: string; width: number }[] = [
  ...SM_MASS_COLUMNS.slice(0, -1),
  { label: "Creator", width: 200 },
  SM_MASS_COLUMNS[SM_MASS_COLUMNS.length - 1],
];
const TABLE_WIDTH = COLUMNS.reduce((w, c) => w + c.width, 0);
