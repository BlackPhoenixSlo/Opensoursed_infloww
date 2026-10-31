"use client";

/** The Extras drawer and its tools (moved out of `VaultManagePanel`): our tools, which the bundle does not have
 *  (ADR-0003) — the mirror collect, the describe sweep and its prompt, the keyword harvest, the duplicates, pack,
 *  AI-folder and disagreement reviews and the flags review. */

import { type ReactNode, useEffect, useRef } from "react";

import { X } from "lucide-react";

import { AiKeyNotice } from "@/components/AiKeyNotice";
import { useExitGhost } from "@/hooks/useExitGhost";
import { type useDescribePlan } from "@/hooks/useVaultCache";
import { harvestSweepLabel, type VaultSweep } from "@/hooks/useVaultSweep";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

/** The modals the drawer's tools open. */
export type ExtrasModal = "dupes" | "packPicker" | "aiFolders" | "disputes" | "flagsReview";

/** The Extras drawer: the page's own tools, which the bundle does not have, one click from the header (ADR-0003).
 *  A right sheet over the page; Esc or × closes it, unless a modal above it took the Escape first. It slides in
 *  and out as the other sheets do (`sheet-right`, `useExitGhost`). */
function ExtrasDrawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const sheetRef = useRef<HTMLElement>(null);
  useExitGhost(true, sheetRef);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside
      ref={sheetRef}
      role="dialog"
      aria-label={EXTRAS_OVERFLOW_LABEL}
      className="sheet-right fixed inset-y-0 right-0 z-40 w-[420px] max-w-full flex flex-col border-l border-border bg-panel shadow-2xl"
    >
      <header className="h-12 shrink-0 px-4 flex items-center justify-between border-b border-border">
        <h2 title={EXTRA_LABEL} className="text-[16px] font-semibold text-fg">{EXTRAS_OVERFLOW_LABEL}</h2>
        <button type="button" aria-label="Close" onClick={onClose} className="grid h-6 w-6 place-items-center rounded text-muted hover:text-fg">
          <X size={16} aria-hidden />
        </button>
      </header>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">{children}</div>
    </aside>
  );
}

export default function VaultExtrasTools({
  accountId,
  onClose,
  isCollecting,
  totalSeen,
  cachedCount,
  onCollect,
  onDescribeAll,
  describeSweep,
  describeText,
  describeStopped,
  harvestSweep,
  plan,
  capped,
  capReason,
  promptVersion,
  setPromptVersion,
  needsReview,
  setNeedsReview,
  flagsReviewOpen,
  onOpen,
}: {
  accountId: string;
  onClose: () => void;
  isCollecting: boolean;
  totalSeen: number;
  cachedCount: number;
  onCollect: () => void;
  onDescribeAll: (mode: "new" | "restage" | "force") => void;
  describeSweep: VaultSweep;
  describeText: { label: string; title: string };
  describeStopped: { text: string; detail: string } | null;
  harvestSweep: VaultSweep;
  /** The describe plan's data (`useDescribePlan`). */
  plan: ReturnType<typeof useDescribePlan>["data"];
  capped: boolean;
  capReason: string;
  promptVersion: "v1" | "v2";
  setPromptVersion: (v: "v1" | "v2") => void;
  needsReview: number;
  setNeedsReview: (n: number) => void;
  /** The flags review is up (its offer hides meanwhile). */
  flagsReviewOpen: boolean;
  onOpen: (m: ExtrasModal) => void;
}) {
  return (
    <ExtrasDrawer onClose={onClose}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-dim">
          {isCollecting ? (
            <>
              <span className="text-warn">●</span> collecting… {totalSeen}
            </>
          ) : cachedCount > 0 ? (
            <>
              <span className="text-ok">●</span> {cachedCount} cached
            </>
          ) : (
            "not collected"
          )}
        </span>
        {/* Desk-only batch sweeps. `md:contents` keeps every button a direct
            flex child at md, so the desktop row is untouched. */}
        <div className="hidden md:contents">
          <button
            type="button"
            onClick={onCollect}
            disabled={isCollecting}
            className="px-3 py-1.5 rounded-lg text-sm border border-accent bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            {isCollecting ? "Collecting…" : cachedCount > 0 ? "Re-collect" : "Collect all"}
          </button>
        </div>
        <div className="hidden md:contents">
          <button
            type="button"
            onClick={() => onDescribeAll("new")}
            disabled={describeSweep.busy || cachedCount === 0 || capped}
            className={cn(
              "px-3 py-1.5 rounded-lg text-sm border disabled:opacity-50",
              capped && !describeSweep.busy
                ? "border-warn/50 bg-warn/10 text-warn"
                : "border-ok/50 bg-ok/10 text-ok hover:bg-ok/20",
            )}
            title={
              describeSweep.busy
                ? describeText.title
                : capped
                  ? capReason
                  : "Describe every un-described item (background)"
            }
          >
            {describeSweep.busy
              ? `Describing ${describeText.label}`
              : capped
                ? "Daily AI cap reached"
                : `Describe all${plan?.undescribed ? ` (${plan.undescribed})` : ""}`}
          </button>
          {/* Which bake-off prompt the sweep runs. B is the default and the only
              one that emits the structured taxonomy auto-foldering needs; A is
              ~4× cheaper for a rough first pass over a huge vault. */}
          <select
            value={promptVersion}
            onChange={(e) => setPromptVersion(e.target.value as "v1" | "v2")}
            disabled={describeSweep.busy}
            title="Describe prompt variant"
            className="px-2 py-1.5 rounded-lg text-sm bg-bg-elev-1 border border-border text-fg-dim"
          >
            <option value="v2">B · rich</option>
            <option value="v1">A · fast</option>
          </select>
          {!!plan?.restage && !describeSweep.busy && !capped && (
            <button
              type="button"
              onClick={() => onDescribeAll("restage")}
              disabled={cachedCount === 0}
              className="px-3 py-1.5 rounded-lg text-sm border border-warn/50 bg-warn/10 text-warn hover:bg-warn/20 disabled:opacity-50"
              title="Re-describe items that were described with the OTHER prompt version. Resumable — already-current rows are skipped."
            >
              Re-scan old ({plan.restage})
            </button>
          )}
          <button
            type="button"
            onClick={() => harvestSweep.start()}
            disabled={harvestSweep.busy || cachedCount === 0}
            className="px-3 py-1.5 rounded-lg text-sm border border-info/50 bg-info/10 text-info hover:bg-info/20 disabled:opacity-50"
            title="Run OF's own search across ~50 selling keywords and fold into local search"
          >
            {harvestSweep.busy
              ? `Harvesting ${harvestSweepLabel(harvestSweep.progress)}`
              : "Harvest OF (50)"}
          </button>
          <button
            type="button"
            onClick={() => onOpen("dupes")}
            disabled={cachedCount === 0}
            className="px-3 py-1.5 rounded-lg text-sm border border-err/50 bg-err/10 text-err hover:bg-err/20 disabled:opacity-50"
            title="Find re-uploaded copies and remove them from the OF vault (review + confirm first)"
          >
            Duplicates
          </button>
          <button
            type="button"
            onClick={() => onOpen("packPicker")}
            disabled={cachedCount === 0}
            className="px-3 py-1.5 rounded-lg text-sm border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
            title="Triage every feet candidate into rungs, then publish the rungs to the OF vault"
          >
            Feet pack
          </button>
          <button
            type="button"
            onClick={() => onOpen("aiFolders")}
            disabled={cachedCount === 0}
            className="px-3 py-1.5 rounded-lg text-sm border border-accent/50 bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
            title="Group the vault into shoots and send lanes — preview first, nothing is created until you confirm"
          >
            Build AI folders
          </button>
          <button
            type="button"
            onClick={() => onOpen("disputes")}
            disabled={cachedCount === 0}
            className="px-3 py-1.5 rounded-lg text-sm border border-warn/50 bg-warn/10 text-warn hover:bg-warn/20 disabled:opacity-50"
            title="Items where the two vision passes disagree — pick the reading that matches the picture. Your choice is locked against re-runs."
          >
            Fix disagreements
          </button>
        </div>
      </div>

      {/* A describe pass that DIED rather than finished. Only meaningful once it
          stops — while it runs the button carries the count — and it survives a
          reload, because the snapshot lives on the server. */}
      <AiKeyNotice accountId={accountId} kinds={["describe_media"]} />
      {!describeSweep.busy && describeStopped && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
          {describeStopped.text}
          <span className="block text-warn/70 mt-0.5">{describeStopped.detail}</span>
        </div>
      )}

      {/* The flags review, offered when a describe sweep ends with items worth a human's eye. */}
      {needsReview > 0 && !flagsReviewOpen && (
        <div className="rounded-lg border border-ok/50 bg-ok/10 px-3 py-2 flex items-center justify-between gap-3">
          <p className="text-[11px] text-ok">
            Described and flagged. <b>{needsReview}</b>{" "}
            {needsReview === 1 ? "item looks" : "items look"} worth your eye — the
            model disagrees with itself on them, or cannot say what is covering the body.
          </p>
          <div className="flex gap-2 shrink-0">
            <button
              type="button"
              onClick={() => onOpen("flagsReview")}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium border border-ok/60 text-ok hover:bg-ok/20"
            >
              Check them
            </button>
            <button
              type="button"
              onClick={() => setNeedsReview(0)}
              className="px-2 py-1 rounded-md text-[11px] text-fg-dim hover:text-fg"
            >
              Later
            </button>
          </div>
        </div>
      )}
    </ExtrasDrawer>
  );
}
