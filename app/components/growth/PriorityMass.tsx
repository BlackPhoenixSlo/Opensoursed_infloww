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

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountPicker } from "@/components/compose/AccountPicker";
import { MediaTray } from "@/components/compose/MediaTray";
import { ListColumn, DEFAULT_BROADCAST_LISTS, SYSTEM_AUDIENCES, SysChip, useFanLists } from "@/components/audience/fanLists";
import { sanitizePriceInput } from "@/components/chat/Composer";
import { SensitiveWordWarning } from "@/components/chat/SensitiveWordWarning";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { Button } from "@/components/ui/primitives";
import { relay, type VaultMedia } from "@/lib/relay";
import { SENSITIVE_BLOCK_MESSAGE, useSensitiveHits } from "@/lib/sensitiveWords";
import { fmtPrice } from "@/lib/format";

const ROUTE = "/admin/priority-mass/runs";
const MAX_RECIPIENTS = 5000;
const HOURLY_RATE = 300;

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
  const [accountId, setAccountId] = useState<string | null>(initialAccountId);
  const [text, setText] = useState("");
  const [attached, setAttached] = useState<VaultMedia[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [price, setPrice] = useState("");
  const [previewCount, setPreviewCount] = useState(0);
  const [lockedText, setLockedText] = useState(false);
  const [includes, setIncludes] = useState<Set<string>>(() => new Set(DEFAULT_BROADCAST_LISTS));
  const [excludes, setExcludes] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const { customLists, isLoading } = useFanLists(accountId);
  const sensitiveHits = useSensitiveHits(text, accountId);
  const numericPrice = Number(price) || 0;

  // A list is never both included and excluded.
  const toggle = (id: string, into: "in" | "out") => {
    const flip = (s: Set<string>, on: boolean) => {
      const n = new Set(s);
      if (on) n.add(id); else n.delete(id);
      return n;
    };
    if (into === "in") {
      setIncludes((s) => flip(s, !s.has(id)));
      setExcludes((s) => flip(s, false));
    } else {
      setExcludes((s) => flip(s, !s.has(id)));
      setIncludes((s) => flip(s, false));
    }
  };

  const send = useMutation({
    mutationFn: () => relay.post<PriorityMassRun>(ROUTE, {
      account_id: accountId,
      text: text.trim(),
      media_files: attached.map((m) => m.id),
      previews: numericPrice > 0 ? attached.slice(0, previewCount).map((m) => m.id) : [],
      price: numericPrice,
      locked_text: numericPrice > 0 && lockedText,
      user_lists: [...includes],
      excluded_user_lists: [...excludes],
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
    if (includes.size === 0) return setError("Pick at least one list to include.");
    if (numericPrice > 0 && attached.length === 0) return setError("A priced message needs media.");
    send.mutate();
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pm-compose-title"
        className="w-full max-w-[640px] max-h-[90vh] flex flex-col bg-panel border border-border rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border">
          <h2 id="pm-compose-title" className="text-sm font-semibold">Priority mass message</h2>
          <p className="text-xs text-fg-dim mt-1">
            {paceLine()} Fans messaged in the last 6 hours, fans who wrote in the last 2 hours, and
            fans on your exclusion lists are skipped.
          </p>
        </header>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <AccountPicker value={accountId} onChange={setAccountId} />
          <div className="space-y-1.5">
            <textarea
              aria-label="Message"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Hey {name}…"
              rows={4}
              maxLength={2000}
              className="w-full bg-bg border border-border rounded-md px-3 py-2 text-base md:text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
            />
            <SensitiveWordWarning hits={sensitiveHits} />
          </div>
          <MediaTray
            accountId={accountId}
            attached={attached}
            onChange={setAttached}
            onOpenVaultPicker={() => setPickerOpen(true)}
            price={numericPrice}
            previewCount={previewCount}
            onPreviewCountChange={setPreviewCount}
          />
          <div className="flex items-center gap-2">
            <label htmlFor="pm-price" className="text-xs text-fg-dim shrink-0">Price (USD):</label>
            <input
              id="pm-price"
              type="text"
              inputMode="decimal"
              value={price}
              onChange={(e) => setPrice(sanitizePriceInput(e.target.value))}
              placeholder="0 (free)"
              className="flex-1 bg-bg border border-border rounded-md px-2 py-1.5 text-base md:text-xs focus:outline-none focus:border-accent"
            />
          </div>
          {numericPrice > 0 && (
            <label className="flex items-center gap-2 text-xs text-fg-dim cursor-pointer">
              <input type="checkbox" checked={lockedText} onChange={(e) => setLockedText(e.target.checked)} />
              Lock the text too (fan must pay to read)
            </label>
          )}
          <div className="border border-border rounded-md p-3 space-y-3">
            <div className="text-[11px] uppercase tracking-wide text-fg-dim">Audience</div>
            <div className="flex flex-wrap gap-1.5">
              {SYSTEM_AUDIENCES.map((b) => (
                <SysChip key={b.id} state={includes.has(b.id) ? "in" : "off"} onClick={() => toggle(b.id, "in")} label={b.label} />
              ))}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-border/60">
              <div>
                <div className="text-[11px] text-fg-dim mb-1.5">Custom lists — include</div>
                <ListColumn lists={customLists} loading={isLoading} selected={includes}
                  onToggle={(id) => toggle(id, "in")} emptyLabel="No custom lists." />
              </div>
              <div>
                <div className="text-[11px] text-fg-dim mb-1.5">Custom lists — exclude</div>
                <ListColumn lists={customLists} loading={isLoading} selected={excludes}
                  onToggle={(id) => toggle(id, "out")} emptyLabel="—" />
              </div>
            </div>
          </div>
          {error && <div role="alert" className="text-xs text-err">{error}</div>}
        </div>
        <footer className="px-4 py-3 border-t border-border flex justify-end gap-4">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={send.isPending}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={launch} disabled={send.isPending}>
            {send.isPending ? "Starting…" : "Send"}
          </Button>
        </footer>
      </div>
      <VaultPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={attached.map((m) => m.id)}
        onConfirm={(p) => { setAttached(p); setPickerOpen(false); }}
      />
    </div>
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
                      <Button size="sm" variant="secondary" disabled={act.isPending}
                        onClick={() => act.mutate({ id: r.id, verb: "resume" })}>Resume</Button>
                    )}
                    {live && (
                      <Button size="sm" variant="secondary" disabled={act.isPending}
                        onClick={() => act.mutate({ id: r.id, verb: "cancel" })}>Cancel</Button>
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
