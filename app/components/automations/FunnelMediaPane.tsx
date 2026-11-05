"use client";

/**
 * FunnelMediaPane — map ONE model's vault media to a (global) funnel.
 *
 * A funnel's TEXT (opener + step copy/prompts/price) is shared across all of an
 * owner's models. Its MEDIA is NOT: an OnlyFans vault id is per-account, so an
 * id picked on model A is meaningless in model B's vault. This pane edits the
 * per-account binding (funnel_account_media) for the CURRENTLY selected model —
 * the funnel's opener media + each PPV step's media — and saves it via
 * useSaveFunnelMedia. To map another model, switch the model chip (one row per
 * account).
 *
 * It reads the funnel's SAVED steps (useFunnel) to know which steps are PPV; add
 * a step + save the funnel text first, then attach its media here.
 */

import { useEffect, useMemo, useReducer } from "react";
import { ChevronLeft, ChevronRight, Copy, Image as ImageIcon, Lock, LockOpen, X } from "lucide-react";

import { IfButton, IfHelp, IfInput, IfLabel } from "@/components/ui/infloww";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useVaultMediaByIds } from "@/hooks/useVaultMediaByIds";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import {
  useFunnel,
  useFunnelMedia,
  useSaveFunnelMedia,
  type FunnelSummary,
} from "@/hooks/useFunnels";
import {
  buildPayload,
  funnelMediaReducer,
  initialFunnelMedia,
  pickerIds as pickerIdsOf,
} from "@/components/automations/funnelMediaReducer";

/** A PPV step that needs media: `stepNo` is its wire `step` id (the media key); `label` names it by position. */
interface PpvSlot {
  stepNo: number;
  label: string;
}

export function FunnelMediaPane({
  funnel,
  accountId,
  onClose,
}: {
  funnel: FunnelSummary;
  accountId: string | null;
  onClose: () => void;
}) {
  const accounts = useActiveAccounts();
  const accountName =
    accounts.find((a) => a.id === accountId)?.nickname ?? accountId ?? "";

  const fullQ = useFunnel(funnel.id);
  const mediaQ = useFunnelMedia(funnel.id, accountId);
  const saveM = useSaveFunnelMedia();

  const [state, dispatch] = useReducer(funnelMediaReducer, initialFunnelMedia);
  const { openerIds, steps, done } = state;

  // The funnel's PPV steps (the only ones that carry media), in order.
  const ppvSlots = useMemo<PpvSlot[]>(() => {
    const out: PpvSlot[] = [];
    (fullQ.data?.steps ?? []).forEach((s, i) => {
      if (s.type === "paid_ppv") {
        const stepNo = typeof s.step === "number" ? s.step : i + 1;
        out.push({ stepNo, label: `Step ${i + 1} · PPV` });
      }
    });
    return out;
  }, [fullQ.data]);
  const stepNos = useMemo(() => ppvSlots.map((s) => s.stepNo), [ppvSlots]);

  // Seed once from the saved binding + the funnel's steps (the reducer ignores
  // later refetches, so edits survive the save's own invalidate).
  useEffect(() => {
    if (state.seeded || !fullQ.data || !mediaQ.data) return;
    dispatch({ type: "hydrate", media: mediaQ.data, stepNos });
  }, [state.seeded, fullQ.data, mediaQ.data, stepNos]);

  // Resolve every picked id (opener + all steps) → full VaultMedia for thumbnails.
  // Bare ids carry no image URL, so we fan out a by-id vault read (cached,
  // 404-tolerant); an unresolved id falls back to a "#id" badge. One hook for the
  // whole pane keeps the queries shared/deduped.
  const allIds = useMemo(
    () => [...openerIds, ...Object.values(steps).flatMap((d) => d.ids)],
    [openerIds, steps],
  );
  const resolvedById = useVaultMediaByIds(accountId, allIds);
  function thumbFor(id: number): string {
    const f = resolvedById[id]?.files;
    const raw = f?.thumb?.url || f?.squarePreview?.url || f?.preview?.url || null;
    return raw ? proxyImage(raw, accountId) : "";
  }

  async function save() {
    if (!accountId) return;
    const rev = state.rev;
    dispatch({ type: "saveStart" });
    await saveM.mutateAsync({
      funnelId: funnel.id,
      accountId,
      ...buildPayload(openerIds, steps, stepNos),
    });
    dispatch({ type: "saveOk", rev });
  }

  // What the open picker is currently editing → its selected ids.
  const pickerIds = pickerIdsOf(state);

  if (!accountId) {
    return (
      <div className="rounded-md border border-border bg-panel p-4 text-[14px] text-warn">
        Pick a model (account) in the chips above to map its vault media.
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-md border border-border bg-panel p-4">
      <div>
        <div className="flex items-center justify-between gap-3">
          <h3 className="min-w-0 text-[14px] font-medium text-fg">
            Funnel media · {funnel.name}{" "}
            <span className="font-normal text-muted">for {accountName}</span>
          </h3>
          <IfButton variant="link" icon={X} aria-label="Close media editor" onClick={onClose}
            className="w-8 text-muted hover:text-fg" />
        </div>
        <IfHelp>Media is per model: picked from {accountName}&apos;s vault. Switch the model to map another one.</IfHelp>
      </div>

      {fullQ.isLoading || mediaQ.isLoading ? (
        <div className="text-[14px] text-muted">Loading media…</div>
      ) : (
        <div className="space-y-3">
          {/* Opener media */}
          <div className="space-y-2">
            <MediaRow
              title="Opening message media"
              hint="Sent with the funnel opener (optional)."
              ids={openerIds}
              onPick={() => dispatch({ type: "openPicker", target: "opener" })}
              onClear={() => dispatch({ type: "setOpener", ids: [] })}
            />
            {openerIds.length > 0 && (
              <MediaStrip
                ids={openerIds}
                thumbFor={thumbFor}
                onMove={(i, dir) => dispatch({ type: "move", target: "opener", i, dir })}
                onRemove={(i) => dispatch({ type: "remove", target: "opener", i })}
              />
            )}
          </div>

          {/* PPV step media */}
          {ppvSlots.length === 0 ? (
            <IfHelp>No PPV steps yet: add one in the funnel editor and save, then attach its media here.</IfHelp>
          ) : (
            ppvSlots.map((slot) => {
              const d = steps[String(slot.stepNo)] ?? { ids: [], previewCount: 0 };
              const free = d.previewCount; // reducer keeps it ≤ ids.length
              const freeId = `funnel-${funnel.id}-step-${slot.stepNo}-free`;
              return (
                <div key={slot.stepNo} className="space-y-2">
                  <MediaRow
                    title={slot.label}
                    hint="The paywalled vault media for this PPV step."
                    ids={d.ids}
                    onPick={() => dispatch({ type: "openPicker", target: slot.stepNo })}
                    // Split clear: this wipes the MEDIA (and its teaser); "Clear teaser"
                    // below resets only the free-preview count.
                    onClear={() => dispatch({ type: "setStep", stepNo: slot.stepNo, patch: { ids: [], previewCount: 0 } })}
                    clearLabel="Clear media"
                  />
                  {d.ids.length > 0 && (
                    <>
                      <div className="px-3">
                        <IfLabel htmlFor={freeId}>Free preview</IfLabel>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] text-fg">
                          <span>First</span>
                          <IfInput
                            id={freeId}
                            type="number"
                            min={0}
                            max={d.ids.length}
                            value={String(d.previewCount)}
                            // Raw count; the reducer clamps it to 0..ids.length.
                            onChange={(e) =>
                              dispatch({ type: "setStep", stepNo: slot.stepNo, patch: { previewCount: Number(e.target.value) || 0 } })
                            }
                            className="w-20"
                          />
                          <span>of {d.ids.length} shown free</span>
                          {free > 0 && (
                            <IfButton variant="link"
                              onClick={() => dispatch({ type: "setStep", stepNo: slot.stepNo, patch: { previewCount: 0 } })}>
                              Clear teaser
                            </IfButton>
                          )}
                        </div>
                        <IfHelp className="flex items-center gap-1.5">
                          <Lock aria-hidden className="h-3.5 w-3.5 shrink-0" />
                          {free === 0 ? "Fully locked." : "The first ones go out free as a teaser; the rest stay locked."}
                        </IfHelp>
                      </div>

                      {/* Thumbnail strip: the leading `free` images go out UNLOCKED,
                          the rest stay paywalled. Reorder to pick which ones are the
                          free teaser (it's always the FIRST N). */}
                      <MediaStrip
                        ids={d.ids}
                        free={free}
                        thumbFor={thumbFor}
                        onMove={(i, dir) => dispatch({ type: "move", target: slot.stepNo, i, dir })}
                        onRemove={(i) => dispatch({ type: "remove", target: slot.stepNo, i })}
                      />

                      {/* Same set across steps is common: copy media + teaser to
                          every OTHER PPV step (teaser re-clamped per target). */}
                      {ppvSlots.length > 1 && (
                        <IfButton icon={Copy} onClick={() => dispatch({ type: "copyToAll", fromStepNo: slot.stepNo, stepNos })}>
                          Copy media to all PPV steps
                        </IfButton>
                      )}
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <IfButton variant="primary" onClick={save} disabled={saveM.isPending}>
          {saveM.isPending ? "Saving…" : "Save media"}
        </IfButton>
        <IfButton onClick={onClose} disabled={saveM.isPending}>Close</IfButton>
        {done && <span className="text-[12px] text-ok">Saved for {accountName}.</span>}
        {saveM.isError && (
          <span className="text-[12px] text-err">
            {(saveM.error as Error)?.message || "Save failed"}
          </span>
        )}
      </div>

      <VaultPicker
        open={state.pickerFor !== null}
        onClose={() => dispatch({ type: "closePicker" })}
        accountId={accountId}
        fanId={null}
        initialSelectedIds={pickerIds}
        onConfirm={(picked: VaultMedia[]) => {
          const ids = picked
            .map((m) => m.id)
            .filter((id): id is number => typeof id === "number" && id > 0);
          dispatch({ type: "pickConfirm", ids });
        }}
      />
    </div>
  );
}

/** One media slot: a labelled pick/clear button + the current count. */
function MediaRow({
  title,
  hint,
  ids,
  onPick,
  onClear,
  clearLabel = "Clear",
}: {
  title: string;
  hint: string;
  ids: number[];
  onPick: () => void;
  onClear: () => void;
  /** Text for the clear link — e.g. "Clear media" when a teaser clear sits beside it. */
  clearLabel?: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
      <div className="min-w-0">
        <div className="text-[14px] text-fg">{title}</div>
        <div className="text-[12px] text-muted">{hint}</div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <IfButton icon={ImageIcon} onClick={onPick}>
          {ids.length ? `${ids.length} picked` : "Pick media"}
        </IfButton>
        {ids.length > 0 && (
          <IfButton variant="link" onClick={onClear}>{clearLabel}</IfButton>
        )}
      </div>
    </div>
  );
}

/** A horizontal strip of media thumbnails for one slot, in SEND order. Each tile
 *  shows the image (or a "#id" badge until it resolves), an open / closed lock
 *  when `free` is given (leading `free` = the teaser), and left / right to reorder + × to
 *  drop it. Reordering matters: the first `free` images are the ones sent free. */
function MediaStrip({
  ids,
  free,
  thumbFor,
  onMove,
  onRemove,
}: {
  ids: number[];
  /** How many LEADING tiles are the free teaser (unlocked); omit for opener media. */
  free?: number;
  thumbFor: (id: number) => string;
  onMove: (index: number, dir: -1 | 1) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {ids.map((id, i) => {
        const src = thumbFor(id);
        const isFree = free != null && i < free;
        return (
          <div
            key={`${id}-${i}`}
            className={`relative w-16 group rounded overflow-hidden border ${
              free == null
                ? "border-border"
                : isFree
                  ? "border-ok/60"
                  : "border-border"
            }`}
            title={`#${id}${free == null ? "" : isFree ? " · free teaser" : " · locked"}`}
          >
            <div className="relative h-16 w-16 bg-bg-elev-1">
              {src ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={src}
                  alt={`media ${id}`}
                  className="h-16 w-16 object-cover"
                  draggable={false}
                />
              ) : (
                <div className="h-16 w-16 flex items-center justify-center text-[12px] text-fg-dim">
                  #{id}
                </div>
              )}
              {free != null && (
                <span className="absolute left-0.5 top-0.5 grid h-4 w-4 place-items-center rounded-full bg-black/55 text-white">
                  {isFree ? <LockOpen aria-hidden className="h-2.5 w-2.5" /> : <Lock aria-hidden className="h-2.5 w-2.5" />}
                </span>
              )}
              <button
                type="button"
                onClick={() => onRemove(i)}
                className="absolute top-0.5 right-0.5 h-6 w-6 md:h-4 md:w-4 rounded-full bg-black/55 text-white text-[10px] leading-none opacity-100 md:opacity-0 md:group-hover:opacity-100 flex items-center justify-center"
                aria-label={`Remove media ${id}`}
                title="Remove"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            </div>
            {/* Reorder controls — hover-revealed on desktop, always visible (and
             *  thumb-sized) on touch, where hover never fires. */}
            <div className="flex items-stretch justify-between bg-black/40 py-2 md:py-0 opacity-100 md:opacity-0 md:group-hover:opacity-100">
              <button
                type="button"
                onClick={() => onMove(i, -1)}
                disabled={i === 0}
                className="flex flex-1 items-center justify-center text-white/90 disabled:opacity-30 hover:bg-white/10"
                aria-label="Move left"
                title="Move earlier"
              >
                <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
              </button>
              <span className="px-0.5 text-[12px] leading-4 text-white/60">{i + 1}</span>
              <button
                type="button"
                onClick={() => onMove(i, 1)}
                disabled={i === ids.length - 1}
                className="flex flex-1 items-center justify-center text-white/90 disabled:opacity-30 hover:bg-white/10"
                aria-label="Move right"
                title="Move later"
              >
                <ChevronRight aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
