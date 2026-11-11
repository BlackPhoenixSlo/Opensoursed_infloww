"use client";

/**
 * NudgeSlotPools — Nudge online's "Message lines & images": a day picker (Every day, Weekdays, Weekend, Mon–Sun) and,
 * for the picked day, one editor per time-of-day slot (its lines and its vault images). Images come from the vault
 * picker, a file chooser or a drop on the slot (imported into the vault, `useNudgeImageUploads`). A day's empty
 * lines or images use the next bucket's (nudgeDayBuckets `inherited`, the relay's `_pick_pool`), shown dimmed with
 * a button to make them the day's own. The tab owns the slots (its reducer), the uploads and the cache of picked
 * media; this only edits them through its callbacks.
 */

import { useRef, useState, type DragEvent } from "react";
import { Image as ImageIcon, Loader2, Upload, X } from "lucide-react";

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
import { type NudgeUploadChip } from "@/components/settings/useNudgeImageUploads";

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
  accountId, slots, mediaCache, onMediaPicked, onSlot, uploads, onUpload, onDismissUpload,
}: {
  accountId: string | null;
  /** Every day bucket: bucket → slot key → its entry. */
  slots: NudgeSlots;
  mediaCache: Record<number, VaultMedia>;
  onMediaPicked: (picked: VaultMedia[]) => void;
  onSlot: (bucket: DayBucket, key: string, entry: NudgeSlotEntry) => void;
  uploads: NudgeUploadChip[];
  onUpload: (bucket: DayBucket, key: string, files: File[]) => void;
  onDismissUpload: (key: string) => void;
}) {
  const [bucket, setBucket] = useState<DayBucket>("default");
  // Which slot's vault picker is open (of the picked day).
  const [pickerSlot, setPickerSlot] = useState<string | null>(null);
  const byIds = useVaultMediaByIds(accountId, shownImageIds(slots, bucket, SLOT_KEYS));
  // A pick or upload this session first (a dropped file's local preview until the vault read lands).
  const media = (id: number): VaultMedia | undefined =>
    mediaCache[id]?.files ? mediaCache[id] : byIds[id] ?? mediaCache[id];
  const day = slots[bucket] ?? {};
  const chain = fallbackChain(bucket);

  return (
    <>
      <div role="radiogroup" aria-label="Day" className="flex flex-wrap gap-2">
        {DAY_BUCKETS.map((b) => {
          const on = b.key === bucket;
          const own = b.key !== "default" && bucketHasContent(slots, b.key);
          return (
            <button key={b.key} type="button" role="radio" aria-checked={on} onClick={() => setBucket(b.key)}
              title={own ? `${bucketLabel(b.key)} has its own lines or images` : undefined}
              className={`relative h-8 rounded-md border px-3 text-[13px] transition-colors ${on
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
          uploads={uploads.filter((u) => u.accountId === accountId && u.bucket === bucket && u.slotKey === key)}
          onFiles={(files) => onUpload(bucket, key, files)}
          onDismissUpload={onDismissUpload}
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
  return raw ? proxyImage(raw, accountId) : media?._localPreview ?? "";
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

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");

/** One time-slot of the picked day: its lines and images, a drop target for image files. */
function SlotEditor({
  label, bucket, entry, from, onChange, accountId, media, uploads, onFiles, onDismissUpload, onPickImages,
}: {
  label: string;
  bucket: DayBucket;
  entry: NudgeSlotEntry;
  /** What this day's empty lines / images use instead. */
  from: Inherited;
  onChange: (e: NudgeSlotEntry) => void;
  accountId: string | null;
  media: (id: number) => VaultMedia | undefined;
  uploads: NudgeUploadChip[];
  onFiles: (files: File[]) => void;
  onDismissUpload: (key: string) => void;
  onPickImages: () => void;
}) {
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
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
    <div
      className={`relative rounded-md border p-3 space-y-2 transition-colors ${over ? "border-accent bg-accent/5" : "border-border"}`}
      onDragOver={(e) => { if (!hasFiles(e)) return; e.preventDefault(); setOver(true); }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false); }}
      onDrop={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setOver(false);
        onFiles(Array.from(e.dataTransfer.files));
      }}>
      {over && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-md bg-bg/80 text-accent font-medium">
          Drop to add to {label}
        </div>
      )}
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

      {/* Images: own thumbnails (else the inherited ones, dimmed), uploads in flight, then Vault / Upload tiles.
       *  One image per nudge; several rotate. */}
      <div className="flex flex-wrap items-center gap-4 md:gap-2">
        {images.map((id) => (
          <MediaThumb key={id} id={id} media={media(id)} accountId={accountId} onRemove={() => removeImage(id)} />
        ))}
        {inheritedImages?.ids.map((id) => (
          <MediaThumb key={`in-${id}`} id={id} media={media(id)} accountId={accountId} dim />
        ))}
        {uploads.map((u) => (
          <div key={u.key} title={u.error ?? `Uploading ${u.name} to the vault…`}
            className={`relative w-12 h-12 rounded border bg-bg shrink-0 ${u.error ? "border-err" : "border-border"}`}>
            {u.previewUrl && <img src={u.previewUrl} alt="" className="w-full h-full object-cover rounded opacity-50" />}
            {!u.error && <Loader2 aria-label="Uploading" className="absolute inset-0 m-auto size-4 animate-spin text-accent" />}
            <button type="button" onClick={() => onDismissUpload(u.key)}
              aria-label={u.error ? "Dismiss failed upload" : "Stop waiting for this upload"}
              className="absolute -top-2 -right-2 md:-top-1 md:-right-1 bg-panel border border-border rounded-full w-7 h-7 md:w-4 md:h-4 grid place-items-center hover:text-err"><X className="size-3 md:size-2.5" aria-hidden /></button>
          </div>
        ))}
        <button type="button" onClick={onPickImages} title="Add image from vault" aria-label="Add image from vault"
          className="w-14 h-12 rounded-md border border-dashed border-border grid place-items-center content-center gap-0.5 text-[11px] text-fg-dim hover:border-accent hover:text-accent">
          <ImageIcon className="size-4" aria-hidden />Vault
        </button>
        <button type="button" onClick={() => fileRef.current?.click()} disabled={!accountId}
          title="Upload images from this device" aria-label="Upload images"
          className="w-14 h-12 rounded-md border border-dashed border-border grid place-items-center content-center gap-0.5 text-[11px] text-fg-dim hover:border-accent hover:text-accent disabled:opacity-50">
          <Upload className="size-4" aria-hidden />Upload
        </button>
        <input ref={fileRef} type="file" accept="image/*" multiple hidden data-testid="nudge-slot-upload"
          onChange={(e) => { onFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        <span className="hidden md:inline text-[12px] text-muted">
          {inheritedImages ? `Uses ${bucketLabel(inheritedImages.from)}'s image${inheritedImages.ids.length === 1 ? "" : "s"}; ` : ""}
          or drop images here
        </span>
      </div>
      {uploads.filter((u) => u.error).map((u) => (
        <div key={u.key} className="text-[12px] text-err">{u.name}: {u.error}</div>
      ))}
    </div>
  );
}
