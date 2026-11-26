"use client";


import { useEffect, useReducer, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountPicker } from "@/components/compose/AccountPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { isAudienceSeed, useTouched } from "@/components/compose/useTouched";
import { massExcludeListId } from "@/components/audience/audienceReducer";
import { ListColumn, SYSTEM_AUDIENCES, SysChip, useFanLists } from "@/components/audience/fanLists";
import { sanitizePriceInput } from "@/lib/priceInput";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfTextArea } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import { useSensitiveHits } from "@/lib/sensitiveWords";
import { fmtPrice } from "@/lib/format";
import {
  buildPayload, initPriorityMass, launchError, numericPrice as priceOf, priorityMassReducer,
} from "./priorityMassForm";

const ROUTE = "/admin/priority-mass/runs";
const MAX_RECIPIENTS = 5000;
const HOURLY_RATE = 300;
const SUB = "mb-1.5 text-[12px] text-fg-dim";

export interface PriorityMassRun {
  id: number;
  account_id: string;
  status: "resolving" | "running" | "done" | "cancelled" | "error";
  text: string;
  media_count: number;
  price: number;
  created_at: string;
  completed_at: string | null;
  last_error: string | null;
  resolved: number | null;
  excluded: number | null;
  capped: number | null;
  total: number;
  counts: Partial<Record<"pending" | "claimed" | "sent" | "skipped" | "failed" | "unknown", number>>;
  stalled: boolean;
}

interface RunsResp { runs: PriorityMassRun[]; max_recipients: number; hourly_rate: number }

const runsKey = (accountId: string | null) => ["priority-mass-runs", accountId ?? ""];

export function paceLine(hourly = HOURLY_RATE, max = MAX_RECIPIENTS): string {
  return `One direct message per fan, in their priority inbox: up to about ${hourly} fans an hour, at most ${max.toLocaleString("en-US")} fans.`;
}

export function PriorityMassComposer({ open, onClose, initialAccountId = null }: {
  open: boolean;
  onClose: () => void;
  initialAccountId?: string | null;
}) {
  const qc = useQueryClient();
  const [form, rawDispatch] = useReducer(priorityMassReducer, initialAccountId, initPriorityMass);
  const { touched, dispatch } = useTouched(form, rawDispatch, isAudienceSeed);
  const { accountId, includes, excludes, text, attached, price, previewCount, lockedText } = form;
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { customLists, isLoading, data: lists, isFetching } = useFanLists(accountId);
  const sensitiveHits = useSensitiveHits(text, accountId);
  const numericPrice = priceOf(form);

  useEffect(() => {
    if (!accountId || !lists || isFetching) return;
    rawDispatch({ type: "seedExclude", accountId, listId: massExcludeListId(lists) });
  }, [accountId, lists, isFetching]);

  // Send waits for that seed, so a run never goes out before MASSDMEXCLUDE is excluded.
  const seeded = !accountId || form.seededFor === accountId;
  // Read failed: Send stays shut, a missing exclusion would reach excluded fans.
  const listsFailed = !!accountId && !lists && !isFetching;

  const send = useMutation({
    mutationFn: () => relay.post<PriorityMassRun>(ROUTE, buildPayload(form), { cellAccountId: accountId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runsKey(accountId) });
      onClose();
    },
    onError: (e) => setError((e as Error).message),
  });

  function launch() {
    const why = launchError(form, sensitiveHits.length > 0);
    setError(why);
    if (!why) send.mutate();
  }

  if (!open) return null;
  const close = () => { if (!send.isPending) onClose(); };
  return (
    <>
      <IfModal
        title="Priority mass message"
        width={722}
        size="editor"
        onClose={close}
        // Escape never drops a touched draft; × and Cancel still close.
        keyboard={!touched}
        footer={<>
          <IfButton onClick={onClose} disabled={send.isPending}>Cancel</IfButton>
          <IfButton variant="primary" onClick={launch} disabled={send.isPending || !seeded}
            title={seeded ? undefined : listsFailed
              ? "Couldn't load the Creator's lists — reopen to retry"
              : "Loading the Creator's lists…"}>
            {send.isPending ? "Starting…" : "Send"}
          </IfButton>
        </>}
      >
        <div className="space-y-4">
          <IfHelp className="mt-0">{paceLine()}</IfHelp>
          <AccountPicker value={accountId} onChange={(id) => dispatch({ type: "setAccount", id })} />
          <div className="space-y-2">
            <IfTextArea
              aria-label="Message"
              value={text}
              onChange={(e) => dispatch({ type: "setText", text: e.target.value })}
              placeholder="Hey {name}…"
              rows={4}
              maxLength={2000}
              className="max-md:text-base"
            />
            <SensitiveWordWarning hits={sensitiveHits} />
          </div>
          <MediaTray
            accountId={accountId}
            attached={attached}
            onChange={(m) => dispatch({ type: "setAttached", attached: m })}
            onOpenVaultPicker={() => setPickerOpen(true)}
            price={numericPrice}
            previewCount={previewCount}
            onPreviewCountChange={(n) => dispatch({ type: "setPreviewCount", n })}
          />
          <div>
            <IfLabel htmlFor="pm-price">Price (USD)</IfLabel>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <IfInput
                id="pm-price"
                type="text"
                inputMode="decimal"
                value={price}
                onChange={(e) => dispatch({ type: "setPrice", price: sanitizePriceInput(e.target.value) })}
                placeholder="0 (free)"
                className="w-40 max-md:text-base"
              />
              {numericPrice > 0 && (
                <label className="flex cursor-pointer select-none items-center gap-2 text-[14px] text-fg">
                  <input type="checkbox" checked={lockedText} onChange={(e) => dispatch({ type: "setLockedText", on: e.target.checked })}
                    className="h-4 w-4 accent-accent" />
                  Lock the text too (fan must pay to read)
                </label>
              )}
            </div>
          </div>
          <div className="space-y-3">
            <div>
              <IfLabel required>Audience</IfLabel>
              <div className="flex flex-wrap gap-1.5">
                {SYSTEM_AUDIENCES.map((b) => (
                  <SysChip key={b.id} state={includes.has(b.id) ? "in" : "off"} onClick={() => dispatch({ type: "toggleInclude", id: b.id })} label={b.label} />
                ))}
              </div>
              <IfHelp>
                Skipped: fans messaged in the last 6 hours, fans who wrote in the last 2 hours, and your exclusion lists.
              </IfHelp>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <div className={SUB}>Custom lists — include</div>
                <ListColumn lists={customLists} loading={isLoading} selected={includes}
                  onToggle={(id) => dispatch({ type: "toggleInclude", id })} emptyLabel="No custom lists." />
              </div>
              <div>
                <div className={SUB}>Custom lists — exclude</div>
                <ListColumn lists={customLists} loading={isLoading} selected={excludes}
                  onToggle={(id) => dispatch({ type: "toggleExclude", id })} emptyLabel="—" />
              </div>
            </div>
          </div>
          {error && <div role="alert" className="text-[14px] text-err">{error}</div>}
        </div>
      </IfModal>
      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={attached.map((m) => m.id)}
        onConfirm={(p) => { dispatch({ type: "setAttached", attached: p }); setPickerOpen(false); }}
      />
    </>
  );
}

const STATUS_LABEL: Record<PriorityMassRun["status"], string> = {
  resolving: "Reading the audience",
  running: "Sending",
  done: "Done",
  cancelled: "Cancelled",
  error: "Stopped",
};

export function PriorityMassRuns() {
  const qc = useQueryClient();
  const [accountId, setAccountId] = useState<string | null>(null);
  const q = useQuery<RunsResp>({
    queryKey: runsKey(accountId),
    enabled: !!accountId,
    // eslint-disable-next-line local/no-fixed-polling -- run progress is worker-written, no SSE event (TODO verify: poll only while a run is live)
    refetchInterval: 30_000,
    queryFn: () => relay.get<RunsResp>(`${ROUTE}?account_id=${encodeURIComponent(accountId!)}`),
  });
  const act = useMutation({
    mutationFn: ({ id, verb, accountId }: { id: number; verb: "cancel" | "resume"; accountId: string }) =>
      relay.post<PriorityMassRun>(`${ROUTE}/${id}/${verb}`, undefined, { cellAccountId: accountId }),
    onSettled: () => qc.invalidateQueries({ queryKey: runsKey(accountId) }),
  });
  const runs = q.data?.runs ?? [];
  return (
    <div className="space-y-3 pt-4">
      <p className="text-xs text-fg-dim">{paceLine(q.data?.hourly_rate, q.data?.max_recipients)}</p>
      <div className="max-w-sm"><AccountPicker value={accountId} onChange={setAccountId} /></div>
      {act.error && <div role="alert" className="text-xs text-err">{(act.error as Error).message}</div>}
      {q.isLoading ? (
        <div className="text-xs text-fg-dim">Loading…</div>
      ) : runs.length === 0 ? (
        <div className="text-xs text-fg-dim">No priority mass messages yet.</div>
      ) : (
        <ul className="space-y-2">
          {runs.map((r) => {
            const sent = r.counts.sent ?? 0;
            const live = r.status === "resolving" || r.status === "running";
            const notSent = (r.counts.skipped ?? 0) + (r.counts.failed ?? 0) + (r.counts.unknown ?? 0);
            return (
              <li key={r.id} className="border border-border rounded-md p-3 text-sm space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{STATUS_LABEL[r.status]}</span>
                  <span className="text-xs text-fg-dim">{new Date(r.created_at).toLocaleString()}</span>
                  <span className="ml-auto flex gap-2">
                    {live && r.stalled && (
                      <IfButton disabled={act.isPending}
                        onClick={() => act.mutate({ id: r.id, verb: "resume", accountId: r.account_id })}>Resume</IfButton>
                    )}
                    {live && (
                      <IfButton disabled={act.isPending}
                        onClick={() => act.mutate({ id: r.id, verb: "cancel", accountId: r.account_id })}>Cancel</IfButton>
                    )}
                  </span>
                </div>
                <div className="truncate text-fg-dim">
                  {r.text || "(media only)"}
                  {r.media_count > 0 && ` · ${r.media_count} media`}
                  {r.price > 0 && ` · ${fmtPrice(Math.round(r.price * 100))}`}
                </div>
                <div className="text-xs">
                  {r.status === "resolving"
                    ? "Reading the audience from OnlyFans…"
                    : `${sent.toLocaleString("en-US")} of ${r.total.toLocaleString("en-US")} sent`
                      + (notSent ? ` · ${notSent.toLocaleString("en-US")} not sent` : "")
                      + (r.excluded ? ` · ${r.excluded.toLocaleString("en-US")} excluded` : "")
                      + (r.capped ? ` · ${r.capped.toLocaleString("en-US")} over the cap` : "")}
                </div>
                {r.last_error && <div className="text-xs text-err">{r.last_error}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
