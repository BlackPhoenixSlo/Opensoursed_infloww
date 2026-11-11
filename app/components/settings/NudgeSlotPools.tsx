"use client";

/**
 * NudgeSlotPools — Nudge online's "Message lines & images": a day picker (Every day, Weekdays, Weekend, Mon–Sun) and,
 * for the picked day, one editor per time-of-day slot (its lines and its vault images, picked from the vault). A
 * day's empty lines or images use the next bucket's (nudgeDayBuckets `inherited`, the relay's `_pick_pool`), shown
 * dimmed with a button to make them the day's own. The tab owns the slots (its reducer) and the cache of picked
 * media; this only edits them through its callbacks.
 */

import { useState } from "react";
import { Image as ImageIcon, X } from "lucide-react";

import { IfButton, IfHelp, IfInput } from "@/components/ui/infloww";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import { mergeCaptions } from "@/lib/parseCaptions";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { useVaultMediaByIds } from "@/hooks/useVaultMediaByIds";
import { type NudgeSlotEntry, type NudgeSlots } from "@/hooks/useNudgeConfig";
import {
  DAY_BUCKETS, bucketHasContent, bucketLabel, fallbackChain, inherited, shownImageIds,
  type DayBucket, type Inherited,
} from "@/components/settings/nudgeDayBuckets";

// The 6 time-of-day slots (same buckets send_welcome uses), with friendly labels.
const SLOT_DEFS: [string, string][] = [
  ["morning_1", "Morning · early (5–9)"],
  ["morning_2", "Morning · late (9–12)"],
  ["afternoon_1", "Afternoon · early (12–15)"],
  ["afternoon_2", "Afternoon · late (15–18)"],
  ["evening", "Evening (18–21)"],
  ["night", "Night (21–5)"],
];
const SLOT_KEYS = SLOT_DEFS.map(([k]) => k);

export function NudgeSlotPools({
  accountId, slots, mediaCache, onMediaPicked, onSlot,
}: {
  accountId: string | null;
  /** Every day bucket: bucket → slot key → its entry. */
  slots: NudgeSlots;
  mediaCache: Record<number, VaultMedia>;
  onMediaPicked: (picked: VaultMedia[]) => void;
  onSlot: (bucket: DayBucket, key: string, entry: NudgeSlotEntry) => void;
}) {
  const [bucket, setBucket] = useState<DayBucket>("default");
  // Which slot's vault picker is open (of the picked day).
  const [pickerSlot, setPickerSlot] = useState<string | null>(null);
  const byIds = useVaultMediaByIds(accountId, shownImageIds(slots, bucket, SLOT_KEYS));
  // A pick this session first, else the vault read.
  const media = (id: number): VaultMedia | undefined =>
    mediaCache[id]?.files ? mediaCache[id] : byIds[id] ?? mediaCache[id];
  const day = slots[bucket] ?? {};
  const chain = fallbackChain(bucket);

  return (
    <>
      <div role="radiogroup" aria-label="Day" className="flex flex-wrap gap-1.5">
        {DAY_BUCKETS.map((b) => {
          const on = b.key === bucket;
          const own = b.key !== "default" && bucketHasContent(slots, b.key);
          return (
            <button key={b.key} type="button" role="radio" aria-checked={on} onClick={() => setBucket(b.key)}
              title={own ? `${bucketLabel(b.key)} has its own lines or images` : undefined}
              className={`relative h-8 rounded-md border px-2.5 text-[13px] focus:outline-none focus-visible:ring-1 focus-visible:ring-accent ${on
                ? "border-accent text-accent bg-bg-elev-2" : "border-border text-fg-dim hover:text-fg"}`}>
              {b.label}
              {own && <span aria-hidden className="absolute -top-1 -right-1 size-2 rounded-full bg-accent" />}
            </button>
          );
        })}
      </div>
      <IfHelp className="mt-0">
        {bucket === "default"
          ? "Used on any day that has nothing of its own. Pick a day to give it its own lines or images."
          : `Only on ${bucketLabel(bucket)}. An empty time uses ${chain.map(bucketLabel).join(", then ")}.`}
      </IfHelp>
      {SLOT_DEFS.map(([key, label]) => (
        <SlotEditor
          key={`${bucket}:${key}`}
          label={label}
          bucket={bucket}
          entry={day[key] ?? { text: [], image: [] }}
          from={inherited(slots, bucket, key)}
          onChange={(entry) => onSlot(bucket, key, entry)}
          accountId={accountId}
          media={media}
          onPickImages={() => setPickerSlot(key)}
        />
      ))}
      {/* Vault image picker for a slot of the picked day (opened from a slot's "Vault"). */}
      {pickerSlot && accountId && (
        <VaultPicker
          open
          onClose={() => setPickerSlot(null)}
          accountId={accountId}
          fanId={null}
          initialSelectedIds={day[pickerSlot]?.image ?? []}
          onConfirm={(picked) => {
            onMediaPicked(picked);
            const cur = day[pickerSlot] ?? { text: [], image: [] };
            onSlot(bucket, pickerSlot, { ...cur, image: picked.map((m) => m.id) });
            setPickerSlot(null);
          }}
        />
      )}
    </>
  );
}

function thumbSrc(media: VaultMedia | undefined, accountId: string | null): string {
  const raw = media?.files?.thumb?.url || media?.files?.squarePreview?.url
    || media?.files?.preview?.url || "";
  return raw ? proxyImage(raw, accountId) : "";
}

export function MediaThumb({
  id, media, accountId, onRemove, dim,
}: { id: number; media?: VaultMedia; accountId: string | null; onRemove?: () => void; dim?: boolean }) {
  const url = thumbSrc(media, accountId);
  return (
    <div className={`relative w-12 h-12 rounded md:overflow-hidden border border-border bg-bg shrink-0 ${dim ? "opacity-50" : ""}`}>
      {url
        ? <img src={url} alt="" loading="lazy" className="w-full h-full object-cover rounded md:rounded-none" />
        : <span className="w-full h-full grid place-items-center text-[12px] text-fg-dim">#{id}</span>}
      {onRemove && (
        <button type="button" onClick={onRemove} title="Remove" aria-label="Remove image"
          className="absolute -top-2 -right-2 md:-top-1 md:-right-1 bg-panel border border-border rounded-full w-7 h-7 md:w-4 md:h-4 grid place-items-center hover:text-err"><X className="size-3 md:size-2.5" aria-hidden /></button>
      )}
    </div>
  );
}

/** One time-slot of the picked day: its lines and images. */
function SlotEditor({
  label, bucket, entry, from, onChange, accountId, media, onPickImages,
}: {
  label: string;
  bucket: DayBucket;
  entry: NudgeSlotEntry;
  /** What this day's empty lines / images use instead. */
  from: Inherited;
  onChange: (e: NudgeSlotEntry) => void;
  accountId: string | null;
  media: (id: number) => VaultMedia | undefined;
  onPickImages: () => void;
}) {
  const texts = entry.text ?? [];
  const images = entry.image ?? [];
  const setLine = (i: number, v: string) => {
    const next = [...texts]; next[i] = v;
    onChange({ ...entry, text: next });
  };
  const removeLine = (i: number) => onChange({ ...entry, text: texts.filter((_, j) => j !== i) });
  const addLine = () => onChange({ ...entry, text: [...texts, ""] });
  const removeImage = (id: number) => onChange({ ...entry, image: images.filter((x) => x !== id) });
  const inheritedLines = texts.length === 0 ? from.text : null;
  const inheritedImages = images.length === 0 ? from.image : null;

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="font-medium">{label}</div>

      {inheritedLines ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-fg-dim">
          <span className="min-w-0 truncate">
            Uses {bucketLabel(inheritedLines.from)}&apos;s {inheritedLines.lines.length} line{inheritedLines.lines.length === 1 ? "" : "s"}
            {" "}(“{inheritedLines.lines[0]}”{inheritedLines.lines.length > 1 ? ", …" : ""})
          </span>
          <IfButton variant="link" onClick={() => onChange({ ...entry, text: [...inheritedLines.lines] })}>
            Edit for {bucketLabel(bucket)}
          </IfButton>
        </div>
      ) : texts.length === 0 && <div className="text-[12px] text-muted">No lines yet.</div>}
      {texts.map((t, i) => (
        <div key={i} className="flex items-center gap-2">
          <IfInput className="flex-1" value={t} onChange={(e) => setLine(i, e.target.value)}
            placeholder="e.g. hey {name}" />
          <button type="button" className="text-fg-dim hover:text-err" title="Remove" aria-label="Remove line"
            onClick={() => removeLine(i)}><X className="size-4" /></button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-4">
        <IfButton variant="link" onClick={addLine}>Add line</IfButton>
        <ImportCaptionsButton current={texts}
          onImport={(items) => onChange({ ...entry, text: mergeCaptions(texts, items).pool })} />
      </div>

      {/* Images: own thumbnails (else the inherited ones, dimmed), then the Vault tile. One image per nudge; several
       *  rotate. */}
      <div className="flex flex-wrap items-center gap-4 md:gap-2">
        {images.map((id) => (
          <MediaThumb key={id} id={id} media={media(id)} accountId={accountId} onRemove={() => removeImage(id)} />
        ))}
        {inheritedImages?.ids.map((id) => (
          <MediaThumb key={`in-${id}`} id={id} media={media(id)} accountId={accountId} dim />
        ))}
        <button type="button" onClick={onPickImages} disabled={!accountId}
          title="Pick images from the vault" aria-label="Add image from vault"
          className="h-12 px-3 rounded-md border border-dashed border-border flex items-center gap-1.5 text-[12px] text-fg-dim hover:border-accent hover:text-accent disabled:opacity-50">
          <ImageIcon className="size-4" aria-hidden />{images.length ? "Change images" : "Add from vault"}
        </button>
        {inheritedImages && (
          <span className="text-[12px] text-muted">
            Uses {bucketLabel(inheritedImages.from)}&apos;s image{inheritedImages.ids.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </div>
  );
}
