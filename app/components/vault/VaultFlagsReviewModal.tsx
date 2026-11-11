"use client";

/**
 * VaultFlagsReviewModal — check what the vision model decided, item by item.
 *
 * The flags pass answers, per region of her body, whether she is bare, covered
 * or not in the picture. Those three answers decide which folder an item lands
 * in, what it may be priced at, and whether it is safe to put in front of a
 * whole list. It is a vision model guessing, and it has been wrong in a
 * DIFFERENT direction after every prompt change — first over-reporting
 * exposure (a tank top read as bare), then under-reporting it (a still of
 * fingers inside her read as "covered by a thong"). Every one of those
 * reversals was invisible to every automatic check and obvious to a human in
 * about four seconds.
 *
 * So checking is part of the product, not part of a test script.
 *
 * Each card is PRE-SET to what the model currently believes. Tap only what is
 * wrong — a pass over a hundred items should be a handful of clicks. Saving
 * records two things and both matter:
 *
 *   · a correction   → locked permanently. No re-run can revert it, so the
 *                      data is right from then on however the model behaves.
 *   · a confirmation → the answers left alone, stamped with the prompt version
 *                      that produced them. This is the half that is easy to
 *                      skip and the half that makes the accuracy number real:
 *                      without it, "looked and agreed" and "never opened" are
 *                      the same record.
 *
 * Ungraded items come first, and within them the ones that gate money or a
 * mass send — two rounds of tuning were once measured entirely on items that
 * had already been checked, and a regression sat in the unchecked remainder
 * through both without moving any total.
 *
 * No OF writes. Nothing here sends anything.
 */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";

import {
  gradeFlags,
  useFlagsAccuracy,
  useFlagsReview,
  type FlagsReviewItem,
} from "@/hooks/useVaultCache";
import { mirrorFullSrc } from "@/lib/mediaUrl";
import ImageLightbox from "@/components/vault/ImageLightbox";
import { MediaMeta, OverLines, REGION_LABEL, Reasons, STATE_TONE } from "@/components/vault/regionBits";
import { IfButton, IfHelp, IfInput, IfModal } from "@/components/ui/infloww";
import { errText } from "@/lib/errText";

const REGIONS = ["breasts_vis", "vulva_vis", "anus_vis"] as const;
const STATES = ["bare", "covered", "not_in_frame"] as const;

const STATE_LABEL: Record<string, string> = {
  bare: "bare",
  covered: "covered",
  not_in_frame: "not in",
};

function stateClass(state: string, on: boolean): string {
  if (!on) return "border-border bg-bg text-fg-dim hover:border-fg-dim/60";
  return STATE_TONE.strong[state] ?? STATE_TONE.strong.not_in_frame;
}

function Card({
  accountId,
  item,
  onSaved,
}: {
  accountId: string;
  item: FlagsReviewItem;
  onSaved: (mediaId: number, corrected: number) => void;
}) {
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [zoom, setZoom] = useState(false);
  const [note, setNote] = useState("");

  /** What the model said, unless the operator has tapped something else. */
  const shown = (region: string) => picked[region] ?? item.regions[region] ?? "";
  const changed = Object.entries(picked).filter(
    ([r, v]) => v !== item.regions[r],
  );

  const saveM = useMutation({
    mutationFn: (changes: [string, string][]) =>
      gradeFlags(accountId, item.media_id, Object.fromEntries(changes), note),
    onSuccess: (_r, changes) => onSaved(item.media_id, changes.length),
  });
  const busy = saveM.isPending;

  return (
    <div
      className={`rounded-md border bg-bg-soft overflow-hidden flex flex-col ${
        changed.length ? "border-warn/60" : "border-border"
      }`}
    >
      {/* Full FRAME, letterboxed — the square crop is where an edge-of-frame
          waistband or genitalia disappears, i.e. exactly what the reviewer is
          here to check. Click to enlarge. */}
      <img
        src={mirrorFullSrc(accountId, item.media_id)}
        alt=""
        onClick={() => setZoom(true)}
        title="Click to view full size"
        className="w-full h-60 object-contain bg-black/70 cursor-zoom-in"
      />
      {zoom && (
        <ImageLightbox accountId={accountId} mediaId={item.media_id} onClose={() => setZoom(false)} />
      )}
      <div className="p-2.5 space-y-2 flex-1 flex flex-col">
        {REGIONS.map((region) => {
          const locked = item.locked.includes(region);
          return (
            <div key={region} className="flex items-center gap-1.5">
              <span className="flex w-16 shrink-0 items-center gap-1 text-[12px] text-muted">
                {locked && <Lock className="h-3 w-3" aria-label="locked" />}
                {REGION_LABEL[region]}
              </span>
              <div className="flex gap-1 flex-1">
                {STATES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    disabled={locked || busy}
                    onClick={() => setPicked((p) => ({ ...p, [region]: s }))}
                    className={`flex-1 text-[12px] font-semibold py-1 rounded border disabled:opacity-40 ${stateClass(
                      s,
                      shown(region) === s,
                    )}`}
                  >
                    {STATE_LABEL[s]}
                  </button>
                ))}
              </div>
            </div>
          );
        })}

        <OverLines over={item.over} />

        <p className="text-[12px] text-fg-dim line-clamp-2 leading-snug">
          {item.description}
        </p>
        <MediaMeta item={item} lanes={item.lanes} />
        <Reasons items={item.iffy_why} tone="warn" />
        {item.settled.length > 0 && (
          <ul aria-label="Auto-settled reading" className="space-y-0.5">
            <li className="text-[12px] leading-snug text-info font-semibold">
              Auto-settled at {item.settled_price ? `$${item.settled_price}` : "no tease price"}
            </li>
            {item.settled.map((line) => (
              <li key={line} className="text-[12px] leading-snug text-info">
                Auto-settled: {line}
              </li>
            ))}
          </ul>
        )}

        <IfInput
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Anything odd?"
          aria-label="Note"
          className="w-full"
        />

        <IfButton
          disabled={busy}
          onClick={() => saveM.mutate(changed)}
          className={`mt-auto w-full ${
            changed.length
              ? "border-warn/60 bg-warn/15 text-warn hover:border-warn hover:bg-warn/25 hover:text-warn"
              : "border-ok/50 bg-ok/10 text-ok hover:border-ok hover:bg-ok/20 hover:text-ok"
          }`}
        >
          {busy
            ? "Saving…"
            : changed.length
              ? `Fix ${changed.length} and continue`
              : "Looks right"}
        </IfButton>
        {saveM.error && <p className="text-[12px] text-err">{errText(saveM.error)}</p>}
      </div>
    </div>
  );
}

export default function VaultFlagsReviewModal({
  accountId,
  onClose,
}: {
  accountId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [onlyIffy, setOnlyIffy] = useState(false);
  const { data, isLoading, error } = useFlagsReview(accountId, true, onlyIffy);
  const { data: acc } = useFlagsAccuracy(accountId, true);
  const [done, setDone] = useState<Map<number, number>>(new Map());

  const open = useMemo(
    () => (data?.items ?? []).filter((i) => !done.has(i.media_id)),
    [data, done],
  );
  const corrected = [...done.values()].filter((n) => n > 0).length;

  function onSaved(mediaId: number, changes: number) {
    setDone((prev) => new Map(prev).set(mediaId, changes));
    // A correction re-cuts the lanes and re-bands the prices.
    for (const key of [
      "vault-flags-accuracy",
      "vault-ai-folder-plan",
      "vault-mirror-items",
    ]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  }

  const pct =
    acc?.accuracy != null ? `${(acc.accuracy * 100).toFixed(1)}%` : "not enough checked yet";

  return (
    <IfModal
      title="Check the vision model"
      width={820}
      onClose={onClose}
      footer={<IfButton onClick={onClose}>Done</IfButton>}
    >
      <IfHelp className="mt-0">
        Each card shows what the model thinks. Tap only what is wrong, then save; “Looks right” counts toward the accuracy too.
      </IfHelp>
      <IfHelp>A fix is permanent — no re-run can undo it.</IfHelp>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
        <span>
          model agrees with you <b className="text-fg">{pct}</b>
          {acc?.answers ? ` (${acc.answers} answers)` : ""}
        </span>
        <span>
          checked <b className="text-fg">{(acc?.graded_items ?? 0) + done.size}</b> /{" "}
          {data?.total ?? "…"}
        </span>
        <span>prompt v{data?.prompt_version ?? "?"}</span>
        <IfButton
          variant="link"
          onClick={() => setOnlyIffy((v) => !v)}
          className="h-auto text-[12px]"
          title="Measured on the graded vault: the badges flag 40 items to catch 11 of the 24 actually wrong — 28% precision, 46% recall. Good enough to sort by, NOT good enough to hide behind, which is why the full list is the default."
        >
          {onlyIffy
            ? `only the ${data?.iffy ?? "…"} flagged — show all ${data?.total ?? ""}`
            : `all ${data?.total ?? ""}, flagged first (${data?.iffy ?? "…"} flagged) — narrow`}
        </IfButton>
        {corrected > 0 && <span className="text-warn">{corrected} fixed just now</span>}
        {!!acc?.graded_other_versions && (
          <span title="Graded against an older prompt — not counted, because a score across two prompts measures neither.">
            {acc.graded_other_versions} checked on an older prompt
          </span>
        )}
      </div>

      <div className="mt-4">
        {isLoading && <p className="text-muted">Loading…</p>}
        {error && <p className="text-err">{errText(error)}</p>}
        {data && open.length === 0 && (
          <p className="text-ok">
            {onlyIffy
              ? "Nothing left worth checking. Switch to “show all” for a full pass."
              : "Nothing left in this batch — close and reopen for the next one."}
          </p>
        )}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
          {open.map((it) => (
            <Card
              key={it.media_id}
              accountId={accountId}
              item={it}
              onSaved={onSaved}
            />
          ))}
        </div>
      </div>
    </IfModal>
  );
}
