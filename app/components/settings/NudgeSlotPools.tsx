"use client";

/**
 * NudgeSlotPools — Nudge online's "Message lines (default times)": one editor per time-of-day slot (its lines and
 * its vault images) and the vault picker a slot's "Add image" opens. The tab owns the slots (its reducer) and the
 * cache of picked media (the preview draws thumbnails from it too); this only edits them through `onSlot` /
 * `onMediaPicked`.
 */

import { useState } from "react";
import { X, Image as ImageIcon } from "lucide-react";

import { IfButton, IfInput } from "@/components/ui/infloww";
import { VaultPicker } from "@/components/chat/VaultPicker";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import { mergeCaptions } from "@/lib/parseCaptions";
import { type VaultMedia } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { type NudgeSlotEntry } from "@/hooks/useNudgeConfig";

// The 6 time-of-day slots (same buckets send_welcome uses), with friendly labels.
const SLOT_DEFS: [string, string][] = [
  ["morning_1", "Morning · early (5–9)"],
  ["morning_2", "Morning · late (9–12)"],
  ["afternoon_1", "Afternoon · early (12–15)"],
  ["afternoon_2", "Afternoon · late (15–18)"],
  ["evening", "Evening (18–21)"],
  ["night", "Night (21–5)"],
];

export function NudgeSlotPools({
  accountId, slots, mediaCache, onMediaPicked, onSlot,
}: {
  accountId: string | null;
  /** The `default` bucket: slot key → its entry. */
  slots: Record<string, NudgeSlotEntry>;
  mediaCache: Record<number, VaultMedia>;
  onMediaPicked: (picked: VaultMedia[]) => void;
  onSlot: (key: string, entry: NudgeSlotEntry) => void;
}) {
  // Which slot's picker is open.
  const [pickerSlot, setPickerSlot] = useState<string | null>(null);
  return (
    <>
      {SLOT_DEFS.map(([key, label]) => (
        <SlotEditor
          key={key}
          label={label}
          entry={slots[key] ?? { text: [], image: [] }}
          onChange={(entry) => onSlot(key, entry)}
          accountId={accountId}
          mediaCache={mediaCache}
          onPickImages={() => setPickerSlot(key)}
        />
      ))}
      {/* Vault image picker for a slot (opened from a slot's "Add image"). */}
      {pickerSlot && accountId && (
        <VaultPicker
          open
          onClose={() => setPickerSlot(null)}
          accountId={accountId}
          fanId={null}
          initialSelectedIds={slots[pickerSlot]?.image ?? []}
          onConfirm={(picked) => {
            onMediaPicked(picked);
            const cur = slots[pickerSlot] ?? { text: [], image: [] };
            onSlot(pickerSlot, { ...cur, image: picked.map((m) => m.id) });
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
  id, media, accountId, onRemove,
}: { id: number; media?: VaultMedia; accountId: string | null; onRemove?: () => void }) {
  const url = thumbSrc(media, accountId);
  return (
    <div className="relative w-12 h-12 rounded md:overflow-hidden border border-border bg-bg shrink-0">
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

/** One time-slot's editable list of message lines + a vault image picker. */
function SlotEditor({
  label, entry, onChange, accountId, mediaCache, onPickImages,
}: {
  label: string;
  entry: NudgeSlotEntry;
  onChange: (e: NudgeSlotEntry) => void;
  accountId: string | null;
  mediaCache: Record<number, VaultMedia>;
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

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="font-medium">{label}</div>
      {texts.length === 0 && <div className="text-[12px] text-muted">No lines yet.</div>}
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
      {/* Images: thumbnails + an add-from-vault tile (the "Add script" media tile). Sends ONE (rotated) if several. */}
      <div className="flex flex-wrap items-center gap-4 md:gap-2">
        {images.map((id) => (
          <MediaThumb key={id} id={id} media={mediaCache[id]} accountId={accountId}
            onRemove={() => removeImage(id)} />
        ))}
        <button type="button" onClick={onPickImages} title="Add image from vault" aria-label="Add image from vault"
          className="w-12 h-12 rounded-md border border-dashed border-border grid place-items-center text-fg-dim hover:border-accent hover:text-accent">
          <ImageIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}
