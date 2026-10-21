"use client";

/**
 * "Media details": the Vault picker's ⓘ panel when a Fan is in scope
 * (docs/spec/phase-04-composer-ppv-vault.md, Vault picker, stories 48–49).
 *
 * A full-height panel over the picker, shaped like the vault manager's details
 * drawer (`VaultManagePanel`, `md:w-[430px]`): the media through the vault
 * browser's own `VaultPreviewMedia`, its facts, and the Fan's price history
 * from the picker's existing fan-history and wall-scan queries. Kept out of
 * VaultPicker.tsx, which is already over size; the picker only opens it.
 */

import { useEffect, useId, useRef, type KeyboardEvent } from "react";

import VaultPreviewMedia from "@/components/vault/VaultPreviewMedia";
import { type FanVaultEntry } from "@/hooks/useFanVaultHistory";
import { fmtCents, fmtDateTime, fmtDuration } from "@/lib/format";
import { type VaultMedia } from "@/lib/relay";

/** Props for a control inside a card `<button>` (a nested `<button>` is not
 *  legal HTML): it opens its own thing and never toggles the card's selection,
 *  by mouse, double-click or keyboard. */
export function cardAction(open: () => void) {
  return {
    role: "button",
    tabIndex: 0,
    onClick: (e: { stopPropagation: () => void }) => {
      e.stopPropagation();
      open();
    },
    onDoubleClick: (e: { stopPropagation: () => void }) => e.stopPropagation(),
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      e.stopPropagation();
      open();
    },
  } as const;
}

export interface VaultMediaDetailsProps {
  media: VaultMedia;
  accountId: string | null;
  /** The Fan's fan-history entry: `null` when the media was never sent to
   *  them, `undefined` while fan-history is loading or has failed. */
  entry: FanVaultEntry | null | undefined;
  /** The wall scan: whether the media is posted in the feed, and its price. */
  onWall: boolean;
  wallCents: number;
  tags: string[];
  /** Opened from the card's price pill: scroll to the price history. */
  atHistory: boolean;
  onExpand: () => void;
  onClose: () => void;
}

export function VaultMediaDetails({
  media: m, accountId, entry, onWall, wallCents, tags, atHistory, onExpand, onClose,
}: VaultMediaDetailsProps) {
  const historyRef = useRef<HTMLElement | null>(null);
  const historyHeadingId = useId();
  useEffect(() => {
    if (atHistory) historyRef.current?.scrollIntoView({ block: "start" });
  }, [atHistory, m.id]);

  const facts: Array<[string, string]> = [
    ["Type", m.type],
    ["Duration", fmtDuration(m.duration) || "—"],
    ["Created", fmtDateTime(m.createdAt ?? null)],
    ["Tags", tags.join(", ") || "—"],
    // The relay stores no per-media note.
    ["Notes", "—"],
  ];
  const history: Array<[string, string]> = [
    ["Purchased", entry === undefined
      ? "—"
      : entry?.was_purchased
      ? `Yes · ${fmtDateTime(entry.last_purchase_at)} · ${fmtCents(entry.total_paid_cents)}`
      : "No"],
    ["Sent (free or paid)", entry === undefined
      ? "—"
      : entry === null
      ? "0"
      : `${entry.send_count}× · ${fmtDateTime(entry.last_sent_at)} · ${entry.last_price_cents > 0 ? fmtCents(entry.last_price_cents) : "Free"}`],
    // fan-history returns no message id, so nothing can be unsent.
    ["Unsent (free or paid)", "—"],
    ["Posted in feed", onWall ? `Yes · ${wallCents > 0 ? fmtCents(wallCents) : "Free"}` : "No"],
  ];

  return (
    <aside
      role="dialog"
      aria-label="Media details"
      className="absolute inset-y-0 right-0 z-10 w-full md:w-[430px] flex flex-col border-l border-border bg-panel shadow-2xl"
    >
      <header className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <h3 className="text-sm font-medium">Media details</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close media details"
          title="Close (Esc)"
          className="ml-auto w-9 h-9 md:w-7 md:h-7 grid place-items-center rounded-md border border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1"
        >
          ✕
        </button>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {accountId && <VaultPreviewMedia media={m} accountId={accountId} onExpand={onExpand} />}
        <DetailsList rows={facts} />
        <section ref={historyRef} aria-labelledby={historyHeadingId} className="space-y-1.5">
          <h4 id={historyHeadingId} className="text-xs font-semibold text-fg-dim uppercase tracking-wide">
            Price history
          </h4>
          <DetailsList rows={history} />
        </section>
      </div>
    </aside>
  );
}

function DetailsList({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-dim">{label}</dt>
          <dd className="tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
