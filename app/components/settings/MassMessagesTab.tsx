"use client";

/**
 * MassMessagesTab — past mass-message broadcasts, per account.
 *
 * Reads broadcasts from the relay's local cache + offers bulk-cancel
 * actions. Unlike per-chat unsend, mass-message unsend has no edit
 * window — OF reports `canUnsend: true, unsendSeconds: 1000000` on
 * these rows long after the 24h chat window has closed.
 *
 * Bulk actions run client-side over the currently-visible rows; each
 * row's cancel mutation already write-throughs the cache + invalidates
 * the read query, so the UI converges without manual refetch logic.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Lock, MoreHorizontal, Paperclip } from "lucide-react";

import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { Button, Card, ExtraTag } from "@/components/ui/primitives";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useCancelMassMessage,
  useMassMessages,
  useMassQueueProgress,
  useRefreshMassMessages,
  type MassMessageRow,
} from "@/hooks/useMassMessages";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
} from "@/hooks/useAutomations";
import { SM, SM_MASS_ACTIONS, SM_MASS_COLUMNS } from "@/components/growth/smartMessagesControls";
import { MENU_ITEM, MENU_PANEL } from "@/components/ui/Menu";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { proxyImage } from "@/lib/mediaUrl";
import { fmtCents } from "@/lib/messageFormat";
import { cn } from "@/lib/utils";

/** Name + cadence of the scheduled auto-unsend rule this tab manages (one
 *  `unsend_messages` automation_rules row per account, keyed by this name). */
const AUTO_RULE_NAME = "Auto-unsend mass";
const AUTO_EVERY_SECONDS = 3600; // hourly sweep

const RANGE_OPTIONS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
  { label: "Last 365 days", days: 365 },
];

/** True when the row carries non-GIF visual media (photos / videos).
 *  GIFs live under `giphyId`, not `media[]`, so GIF-only rows return
 *  false here. Used by the bulk-action filters. */
function hasImageMedia(m: MassMessageRow): boolean {
  return (m.mediaCount ?? 0) > 0;
}

/** Age gate for every TYPED bulk action (non-image / with-images / free text) —
 *  mirrors the backend unsend_messages `policy.mass_text_hours` (a blast has
 *  done its job after this long). "Unsend all" ignores it on purpose so
 *  fresh sends can still be pulled. */
const BULK_MIN_AGE_H = 4;

function olderThanHours(m: MassMessageRow, hours: number): boolean {
  if (!m.date) return false; // unknown sent time → never auto-eligible
  const t = new Date(m.date).getTime();
  if (Number.isNaN(t)) return false;
  return (Date.now() - t) / 3_600_000 >= hours;
}

/** Free (no price) + image-less + older than the threshold — the exact set the
 *  backend `policy.mass_text_hours` sweep targets. GIF-only counts as image-less. */
function isFreeTextOld(m: MassMessageRow): boolean {
  return !!m.isFree && !hasImageMedia(m) && olderThanHours(m, BULK_MIN_AGE_H);
}

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
  // Bulk actions operate on this slice, so the model bubbles also scope
  // the "Unsend all" buttons.
  const visibleRows = useMemo(() => {
    let out = rows;
    if (selectedModels.size > 0)
      out = out.filter((r) => r.__accountId && selectedModels.has(r.__accountId));
    if (hideUnsent) out = out.filter((r) => !r.isCanceled);
    return out;
  }, [rows, selectedModels, hideUnsent]);

  const actionableRows = useMemo(
    () => visibleRows.filter((r) => r.canUnsend && !r.isCanceled && r.__accountId),
    [visibleRows],
  );

  /** Run cancel mutations across a target subset of rows, in small
   *  parallel batches, with one combined confirmation up front. */
  async function bulkCancel(
    actionKey: string,
    label: string,
    predicate: (r: MassMessageRow) => boolean,
  ) {
    const targets = actionableRows.filter(predicate);
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
            cancelM.mutateAsync({ id: r.id, accountId: r.__accountId! }),
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
  const counts = useMemo(() => {
    const all = actionableRows.length;
    const nonImage = actionableRows.filter(
      (r) => !hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H),
    ).length;
    const withImage = actionableRows.filter(
      (r) => hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H),
    ).length;
    const freeTextOld = actionableRows.filter(isFreeTextOld).length;
    return { all, nonImage, withImage, freeTextOld };
  }, [actionableRows]);

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
            Bulk actions ({actionableRows.length} unsendable in view):
          </span>
          <ExtraTag />
          <Button
            size="sm"
            variant="danger"
            disabled={!!bulkRunning || counts.all === 0}
            onClick={() => bulkCancel("all", "Unsend ALL visible broadcasts", () => true)}
          >
            {bulkRunning === "all" ? "Unsending…" : `Unsend all (${counts.all})`}
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={!!bulkRunning || counts.nonImage === 0}
            onClick={() =>
              bulkCancel(
                "non-image",
                `Unsend non-image broadcasts (text + GIF + empty) older than ${BULK_MIN_AGE_H}h`,
                (r) => !hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H),
              )
            }
          >
            {bulkRunning === "non-image"
              ? "Unsending…"
              : `Unsend non-image (GIFs incl.) >${BULK_MIN_AGE_H}h (${counts.nonImage})`}
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={!!bulkRunning || counts.withImage === 0}
            onClick={() =>
              bulkCancel(
                "with-image",
                `Unsend broadcasts that include images / videos, older than ${BULK_MIN_AGE_H}h`,
                (r) => hasImageMedia(r) && olderThanHours(r, BULK_MIN_AGE_H),
              )
            }
          >
            {bulkRunning === "with-image"
              ? "Unsending…"
              : `Unsend with images >${BULK_MIN_AGE_H}h (${counts.withImage})`}
          </Button>
          {/* The free-text cleanup — same target set as the backend
           *  unsend_messages `policy.mass_text_hours` sweep: free (no price),
           *  image-less, past the age gate. Keeps revenue (PPV/image) blasts. */}
          <Button
            size="sm"
            variant="danger"
            disabled={!!bulkRunning || counts.freeTextOld === 0}
            onClick={() =>
              bulkCancel(
                "free-text-old",
                `Unsend FREE text-only broadcasts older than ${BULK_MIN_AGE_H}h`,
                isFreeTextOld,
              )
            }
            title={`Free (no price), no image, older than ${BULK_MIN_AGE_H}h — leaves PPV/image blasts alone`}
          >
            {bulkRunning === "free-text-old"
              ? "Unsending…"
              : `Unsend free text >${BULK_MIN_AGE_H}h (${counts.freeTextOld})`}
          </Button>
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

/** Per-model auto-unsend config. Reads/writes the single `unsend_messages` rule
 *  named AUTO_RULE_NAME for this account; the payload carries
 *  `policy.{mass_text_hours,mass_media_hours,mass_price_hours}` for the enabled
 *  classes (mirrors the backend sweep). */
function AutoUnsendPanel({ accountId, label }: { accountId: string; label: string }) {
  const rulesQ = useAutomationRules(accountId);
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const existing = useMemo(
    () =>
      (rulesQ.data ?? []).find(
        (r) => r.kind === "unsend_messages" && r.name === AUTO_RULE_NAME,
      ),
    [rulesQ.data],
  );

  const [enabled, setEnabled] = useState(false);
  const [text, setText] = useState({ on: true, h: 4 });
  const [img, setImg] = useState({ on: false, h: 24 });
  const [price, setPrice] = useState({ on: false, h: 48 });

  // Hydrate the form once from the saved rule when it first loads.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current || !existing) return;
    hydratedRef.current = true;
    setEnabled(existing.is_enabled);
    const p = (existing.payload?.policy ?? {}) as Record<string, number>;
    setText(p.mass_text_hours != null ? { on: true, h: p.mass_text_hours } : { on: false, h: 4 });
    setImg(p.mass_media_hours != null ? { on: true, h: p.mass_media_hours } : { on: false, h: 24 });
    setPrice(p.mass_price_hours != null ? { on: true, h: p.mass_price_hours } : { on: false, h: 48 });
  }, [existing]);

  const saving = createM.isPending || updateM.isPending;
  const err = createM.error || updateM.error;
  // Save guard: an empty policy is never sent. The Relay reads one as the
  // per-chat sweep of outbound DMs (`not wants_mass`, unsend_messages.py).
  const noClass = !text.on && !img.on && !price.on;

  const save = () => {
    if (noClass) return;
    const policy: Record<string, number> = {};
    if (text.on) policy.mass_text_hours = text.h;
    if (img.on) policy.mass_media_hours = img.h;
    if (price.on) policy.mass_price_hours = price.h;
    const payload = { policy };
    if (existing) {
      updateM.mutate({
        id: existing.id,
        is_enabled: enabled,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
      });
    } else {
      createM.mutate({
        account_id: accountId,
        kind: "unsend_messages",
        name: AUTO_RULE_NAME,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
        is_enabled: enabled,
      });
    }
  };

  return (
    <div className="border border-border rounded-md p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm font-medium cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          {label}
          {existing?.is_enabled && <span className="text-[10px] text-accent">● active</span>}
        </label>
        <span className="text-[10px] text-fg-dim">runs hourly</span>
      </div>
      <AutoClassRow label="Free text-only" v={text} set={setText} />
      <AutoClassRow label="With image / video" v={img} set={setImg} />
      <AutoClassRow label="PPV (priced)" v={price} set={setPrice} />
      <div className="flex items-center gap-2 pt-1 flex-wrap">
        <Button size="sm" variant="secondary" onClick={save} disabled={saving || noClass}>
          {saving ? "Saving…" : existing ? "Update" : "Save"}
        </Button>
        {noClass && (
          <span className="text-xs text-fg-dim">Turn on at least one class to save.</span>
        )}
        {err && <span className="text-xs text-err">{err.message}</span>}
        {existing?.last_run && (
          <span className="text-[10px] text-fg-dim">
            last run: {existing.last_run.status}
            {existing.next_due_at
              ? ` · next ${new Date(existing.next_due_at).toLocaleTimeString()}`
              : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function AutoClassRow({
  label, v, set,
}: {
  label: string;
  v: { on: boolean; h: number };
  set: (x: { on: boolean; h: number }) => void;
}) {
  return (
    <div className="flex items-center gap-2 text-xs flex-wrap md:flex-nowrap">
      <label className="flex items-center gap-1.5 w-full md:w-36 cursor-pointer">
        <input
          type="checkbox"
          checked={v.on}
          onChange={(e) => set({ ...v, on: e.target.checked })}
        />
        {label}
      </label>
      <span className="text-fg-dim">after</span>
      <input
        type="number"
        min={1}
        className="w-16 bg-bg-elev-1 border border-border rounded px-1.5 py-0.5 text-base md:text-xs disabled:opacity-40"
        value={v.h}
        disabled={!v.on}
        onChange={(e) => set({ ...v, h: Math.max(1, Number(e.target.value) || 1) })}
      />
      <span className="text-fg-dim">hours</span>
    </div>
  );
}

// Friendly labels for the automation_kind tokens that produce broadcasts.
const MASS_AUTOMATION_LABELS: Record<string, string> = {
  send_mass_message: "Mass message",
  reply_mass_funnel: "Funnel reply",
  mass_nudge: "Mass nudge",
  online_blast: "Online blast",
  ppv_send: "PPV Library",
};

/** The capture's OF columns, with our Creator column (an Inflowwww extra)
 *  before Actions. */
const COLUMNS: readonly { label: string; width: number }[] = [
  ...SM_MASS_COLUMNS.slice(0, -1),
  { label: "Creator", width: 200 },
  SM_MASS_COLUMNS[SM_MASS_COLUMNS.length - 1],
];
const TABLE_WIDTH = COLUMNS.reduce((w, c) => w + c.width, 0);

/** The bundle's "MMM D, YYYY [at] h:mm A", in the report time zone. */
function sentAt(iso: string, tz: string | null): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const opts: Intl.DateTimeFormatOptions = {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true,
  };
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-US", { ...opts, timeZone: tz ?? undefined }).formatToParts(d);
  } catch {
    parts = new Intl.DateTimeFormat("en-US", opts).formatToParts(d);
  }
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.month} ${p.day}, ${p.year} at ${p.hour}:${p.minute} ${p.dayPeriod}`;
}

const SALES_TIP = "Purchases recorded on this broadcast's copies in our records (no OnlyFans read)";

/** A Not wired cell: no Relay read backs the column. */
function NotWiredCell() {
  return <td title="not wired" className={cn(IF_TABLE.td, "text-muted")}>—</td>;
}

function MassMessageRowItem({
  m, accountLabel, reportTz, busy, onCancel,
}: {
  m: MassMessageRow;
  accountLabel: string;
  reportTz: string | null;
  busy: boolean;
  onCancel: () => void;
}) {
  const canUnsend = !!m.canUnsend && !m.isCanceled;
  const firstMedia = m.media?.[0];
  const thumbUrl =
    firstMedia?.files?.squarePreview?.url ||
    firstMedia?.files?.thumb?.url ||
    firstMedia?.files?.preview?.url ||
    null;
  const text = stripHtml(m.text || m.rawText || "");
  const dash = <span className="text-fg-dim">--</span>;

  return (
    <tr className={cn(IF_TABLE.row, (busy || m.isCanceled) && "opacity-60")}>
      {/* Message: one line; "--" when the message is media only (#80). */}
      <td className={cn(IF_TABLE.td, "sticky left-0 bg-panel")}>
        {text
          ? <div className="truncate" title={text}>{text}</div>
          : <span className="text-fg-dim" title="This message contains only media">--</span>}
      </td>
      <td className={IF_TABLE.td}>{m.date ? sentAt(m.date, reportTz) : dash}</td>
      {/* Sender: the automation that sent it; who sent a manual one has no read. */}
      {m.automationKind ? (
        <td className={cn(IF_TABLE.td, "truncate")} title="Sent by an automation (joined via mass_runs)">
          {MASS_AUTOMATION_LABELS[m.automationKind] ?? m.automationKind}
          {m.funnelName ? ` · ${m.funnelName}` : ""}
        </td>
      ) : <NotWiredCell />}
      <td className={IF_TABLE.td}>
        {(m.mediaCount ?? 0) > 0 || m.giphyId ? (
          <span className="inline-flex items-center gap-2 text-fg-dim">
            {thumbUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={proxyImage(thumbUrl, m.__accountId)}
                alt=""
                className="w-8 h-8 rounded object-cover border border-border"
              />
            )}
            {(m.mediaCount ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1"><Paperclip size={12} aria-hidden /> {m.mediaCount}</span>
            )}
            {m.giphyId && <span>GIF</span>}
          </span>
        ) : dash}
      </td>
      {/* Status pill (#98): Sent in the Active colours (#100), Unsent in the
       *  Canceled colours (#102), from the app's palette. */}
      <td className={IF_TABLE.td}>
        <span
          className={cn(
            "inline-block rounded-2xl px-2 py-0.5 text-sm font-medium",
            m.isCanceled ? "bg-warn/15 text-warn" : "bg-accent/15 text-accent",
          )}
        >
          {m.isCanceled ? SM.massUnsent.label : SM.massSent.label}
        </span>
      </td>
      {/* Price: "--" when free (#85); priced, but the cache keeps no amount. */}
      {m.isFree ? (
        <td className={IF_TABLE.td}>{dash}</td>
      ) : (
        <td title="not wired" className={IF_TABLE.td}>
          <span className="inline-flex items-center gap-1 text-warn"><Lock size={12} aria-hidden />PPV</span>
        </td>
      )}
      <td className={IF_TABLE.td}>{m.sentCount ?? 0}</td>
      <td className={IF_TABLE.td}>{m.viewedCount ?? 0}</td>
      {/* Purchased, Earnings: the copies our rows mark bought (relay's local
       *  attribution, a floor for a list blast). Withdrawn by, Withdrawn date &
       *  time: no read. */}
      <td className={IF_TABLE.td} title={SALES_TIP}>{m.isFree ? dash : (m.purchasedCount ?? 0)}</td>
      <td className={IF_TABLE.td} title={SALES_TIP}>{m.isFree ? dash : fmtCents(m.earningsCents ?? 0)}</td>
      <NotWiredCell />
      <NotWiredCell />
      <td className={cn(IF_TABLE.td, "truncate")}>{accountLabel}</td>
      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] bg-panel px-1 text-center")}>
        <RowActionsMenu
          items={[
            {
              label: SM_MASS_ACTIONS.unsend.label,
              onClick: onCancel,
              disabled: busy || !canUnsend,
              title: m.isCanceled
                ? "Already unsent"
                : canUnsend
                ? SM_MASS_ACTIONS.unsendTip.label
                : "OF marked this as no-longer-unsendable",
            },
            // Duplicate opens the bundle's editor on a copy; no path of ours reads a sent broadcast back into it.
            { label: SM_MASS_ACTIONS.duplicate.label, disabled: true, title: "not wired" },
          ]}
        />
      </td>
    </tr>
  );
}

type RowAction = { label: string; onClick?: () => void; disabled: boolean; title: string };

/** The bundle's row menu (`OFMMOperateMenu`, capture Notes): a 16px "more" trigger whose menu opens above it, right
 *  aligned. The list scrolls sideways, so the menu is portalled and fixed to the trigger, and closes on a pick, an
 *  outside press, Escape or a scroll. */
function RowActionsMenu({ items }: { items: RowAction[] }) {
  const [pos, setPos] = useState<{ right: number; bottom: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pos) return;
    const close = () => setPos(null);
    const outside = (ev: MouseEvent) => {
      const t = ev.target as Node;
      if (!trigger.current?.contains(t) && !menu.current?.contains(t)) close();
    };
    const esc = (ev: KeyboardEvent) => { if (ev.key === "Escape") close(); };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [pos]);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-label="Actions"
        aria-haspopup="menu"
        aria-expanded={!!pos}
        onClick={() => {
          if (pos) return setPos(null);
          const r = trigger.current!.getBoundingClientRect();
          setPos({ right: window.innerWidth - r.right, bottom: window.innerHeight - r.top + 4 });
        }}
        className="inline-grid place-items-center w-6 h-6 rounded text-fg-dim hover:text-fg hover:bg-bg-elev-1"
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {pos && createPortal(
        <div
          ref={menu}
          role="menu"
          style={{ position: "fixed", right: pos.right, bottom: pos.bottom }}
          className={cn(MENU_PANEL, "mt-0 w-36 z-[60]")}
        >
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              title={it.title}
              onClick={() => {
                setPos(null);
                it.onClick?.();
              }}
              className={cn(MENU_ITEM, it.disabled ? "text-fg-dim cursor-not-allowed opacity-60" : "hover:bg-bg-elev-1")}
            >
              {it.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}

function stripHtml(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .trim();
}
