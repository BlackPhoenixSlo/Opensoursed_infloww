"use client";

/**
 * Smart Messages' Priority mass message (06-growth-automations M4): one direct
 * message per fan instead of OF's mass message, so it lands in each fan's
 * priority inbox. `service/automations/priority_mass.py` sends it and
 * `service/priority_mass_api.py` holds its runs.
 *
 * - `PriorityMassComposer`: the "Priority mass message" card's form (the pop-up's
 *   Next opens it). Creator, text, vault media, price, the OF lists to include
 *   and exclude. Launching freezes the audience on the Relay and starts the run.
 * - `PriorityMassRuns`: the "Priority mass messages" tab. One Creator's runs, newest
 *   first, each with its progress, and Cancel / Resume.
 *
 * Pacing is the shared 11 s per-Creator OF write gap, about 300 fans an hour
 * (Infloww advertises 300 to 700), and a run reaches at most 5,000 fans. Both
 * figures come from the Relay's list answer once loaded.
 */

import { useEffect, useReducer, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountPicker } from "@/components/compose/AccountPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { isAudienceSeed, useTouched } from "@/components/compose/useTouched";
import {
  audienceError, audienceReducer, buildAudiencePayload, initAudience, massExcludeListId,
} from "@/components/audience/audienceReducer";
import { ListColumn, SYSTEM_AUDIENCES, SysChip, useFanLists } from "@/components/audience/fanLists";
import { sanitizePriceInput } from "@/lib/priceInput";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { EDITOR_MODAL } from "@/components/automations/automationPage";
import { IfButton, IfHelp, IfInput, IfLabel, IfModal, IfTextArea } from "@/components/ui/infloww";
import { relay, type VaultMedia } from "@/lib/relay";
import { SENSITIVE_BLOCK_MESSAGE, useSensitiveHits } from "@/lib/sensitiveWords";
import { fmtPrice } from "@/lib/format";

const ROUTE = "/admin/priority-mass/runs";
const MAX_RECIPIENTS = 5000;
const HOURLY_RATE = 300;
/** A list column's heading (under the Audience label), as in AudiencePanel. */
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

/** The pace line both surfaces show. */
export function paceLine(hourly = HOURLY_RATE, max = MAX_RECIPIENTS): string {
  return `One direct message per fan, in their priority inbox: up to about ${hourly} fans an hour, at most ${max.toLocaleString("en-US")} fans.`;
}

export function PriorityMassComposer({ open, onClose, initialAccountId = null }: {
  open: boolean;
  onClose: () => void;
  /** "Post as" on open: the opener's Creator (Smart Messages' header select); else the picker seeds itself. */
  initialAccountId?: string | null;
}) {
  const qc = useQueryClient();
  // The account and its audience (list ids are per account) — one reducer.
  const [aud, rawDispatch] = useReducer(audienceReducer, initialAccountId, (id) => initAudience(id));
  // The user's dispatch and setters: any of them but the seeding touches the form (Escape then keeps it).
  const { touched, dispatch, edit } = useTouched(aud, rawDispatch, isAudienceSeed);
  const { accountId, includes, excludes } = aud;
  const [text, setText] = useState("");
  const [attached, setAttached] = useState<VaultMedia[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [price, setPrice] = useState("");
  const [previewCount, setPreviewCount] = useState(0);
  const [lockedText, setLockedText] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { customLists, isLoading, data: lists, isFetching } = useFanLists(accountId);
  const sensitiveHits = useSensitiveHits(text, accountId);
  const numericPrice = Number(price) || 0;

  // Pre-tick the standing MASSDMEXCLUDE list in Exclude once the account's lists
  // settle (not a stale cache mid-refetch); seeded once per account, so an untick sticks.
  useEffect(() => {
    if (!accountId || !lists || isFetching) return;
    rawDispatch({ type: "seedExclude", accountId, listId: massExcludeListId(lists) });
  }, [accountId, lists, isFetching]);

  // Send waits for that seed, so a run never goes out before MASSDMEXCLUDE is excluded.
  const seeded = !accountId || aud.seededFor === accountId;
  // The read failed (no data, nothing in flight): Send stays shut — a missing
  // exclusion would reach excluded fans. Reopening remounts and refetches.
  const listsFailed = !!accountId && !lists && !isFetching;

  const send = useMutation({
    mutationFn: () => relay.post<PriorityMassRun>(ROUTE, {
      account_id: accountId,
      text: text.trim(),
      media_files: attached.map((m) => m.id),
      previews: numericPrice > 0 ? attached.slice(0, previewCount).map((m) => m.id) : [],
      price: numericPrice,
      locked_text: numericPrice > 0 && lockedText,
      ...buildAudiencePayload(aud),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: runsKey(accountId) });
      onClose();
    },
    onError: (e) => setError((e as Error).message),
  });

  function launch() {
    setError(null);
    if (sensitiveHits.length > 0) return setError(SENSITIVE_BLOCK_MESSAGE);
    if (!accountId) return setError("Pick a Creator.");
    if (!text.trim() && attached.length === 0) return setError("Add a text or media.");
    const audErr = audienceError(aud);
    if (audErr) return setError(audErr);
    if (numericPrice > 0 && attached.length === 0) return setError("A priced message needs media.");
    send.mutate();
  }

  if (!open) return null;
  const close = () => { if (!send.isPending) onClose(); };
  return (
    <>
      <IfModal
        title="Priority mass message"
        width={722}
        className={EDITOR_MODAL}
        onClose={close}
        // Escape never drops a draft the user touched; × and Cancel still close.
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
              onChange={(e) => edit(setText)(e.target.value)}
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
            onChange={edit(setAttached)}
            onOpenVaultPicker={() => setPickerOpen(true)}
            price={numericPrice}
            previewCount={previewCount}
            onPreviewCountChange={edit(setPreviewCount)}
          />
          <div>
            <IfLabel htmlFor="pm-price">Price (USD)</IfLabel>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <IfInput
                id="pm-price"
                type="text"
                inputMode="decimal"
                value={price}
                onChange={(e) => edit(setPrice)(sanitizePriceInput(e.target.value))}
                placeholder="0 (free)"
                className="w-40 max-md:text-base"
              />
              {numericPrice > 0 && (
                <label className="flex cursor-pointer select-none items-center gap-2 text-[14px] text-fg">
                  <input type="checkbox" checked={lockedText} onChange={(e) => edit(setLockedText)(e.target.checked)}
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
        onConfirm={(p) => { edit(setAttached)(p); setPickerOpen(false); }}
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
    refetchInterval: 30_000,
    queryFn: () => relay.get<RunsResp>(`${ROUTE}?account_id=${encodeURIComponent(accountId!)}`),
  });
  const act = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: "cancel" | "resume" }) =>
      relay.post<PriorityMassRun>(`${ROUTE}/${id}/${verb}`),
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
                        onClick={() => act.mutate({ id: r.id, verb: "resume" })}>Resume</IfButton>
                    )}
                    {live && (
                      <IfButton disabled={act.isPending}
                        onClick={() => act.mutate({ id: r.id, verb: "cancel" })}>Cancel</IfButton>
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
