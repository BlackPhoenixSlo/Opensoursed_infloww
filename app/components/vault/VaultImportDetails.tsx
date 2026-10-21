"use client";

/**
 * The vault import's per-file details: the model (`RowMeta` as typed, `WireMeta`
 * as the batch route takes it), the one field control the table and Batch edit
 * both draw, and Batch edit itself.
 */

import { useState } from "react";
import { Info } from "lucide-react";

import { type VaultList } from "@/lib/relay";
import { cn } from "@/lib/utils";

/** Step 3's per-file columns (growth-vault-pro#109), each a key of `RowMeta`. */
export const STEP3_FIELDS = [
  ["Category", "category"],
  ["Tag Creators", "tag"],
  ["Hashtags", "hashtags"],
  ["Notes", "notes"],
  ["Suggested price", "price"],
] as const;

/** One picked file's details, as typed: the Category is a vault folder id, the
 *  price is in dollars, and the two tag fields are comma-separated. */
export interface RowMeta {
  category?: string;
  tag?: string;
  hashtags?: string;
  notes?: string;
  price?: string;
}
export type MetaKey = keyof RowMeta;

/** What the batch route's `meta` list takes for one file, or null for none. */
export interface WireMeta {
  list_id?: number;
  tag_creators?: string[];
  hashtags?: string[];
  notes?: string;
  price_cents?: number;
}

/** Commas only, as the relay reads the lists: a multi-word hashtag ("red set",
 *  like a Drive folder named that) stays one tag. */
const splitTags = (v: string | undefined, strip: RegExp) =>
  [...new Set((v ?? "").split(",").map((t) => t.trim().replace(strip, "").trim()).filter(Boolean))];

/** A row's details as the relay takes them; empty fields are left out and an
 *  all-empty row is null. Exported for tests. */
export function metaToWire(m: RowMeta | undefined): WireMeta | null {
  if (!m) return null;
  const out: WireMeta = {};
  if (m.category) out.list_id = Number(m.category);
  const creators = splitTags(m.tag, /^@+/);
  if (creators.length) out.tag_creators = creators;
  const tags = splitTags(m.hashtags, /^#+/);
  if (tags.length) out.hashtags = tags;
  if (m.notes?.trim()) out.notes = m.notes.trim();
  const dollars = Number.parseFloat((m.price ?? "").replace(/[$,\s]/g, ""));
  if (Number.isFinite(dollars) && dollars >= 0 && (m.price ?? "").trim()) out.price_cents = Math.round(dollars * 100);
  return Object.keys(out).length ? out : null;
}

/** The free-text fields' hints, shared by the table and Batch edit. */
const PLACEHOLDER: Partial<Record<MetaKey, string>> = {
  tag: "@creator, …",
  hashtags: "beach, lingerie",
  notes: "",
  price: "$",
};

/** One detail's control: the Category's folder `<select>`, Batch edit's Notes
 *  box, or a plain input. */
export function MetaField({
  field,
  label,
  value,
  onChange,
  folders,
  disabled,
  multiline = false,
  className,
}: {
  field: MetaKey;
  label: string;
  value: string;
  onChange: (v: string) => void;
  folders: VaultList[];
  disabled?: boolean;
  multiline?: boolean;
  className?: string;
}) {
  if (field === "category") {
    return (
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={className}
      >
        <option value="">—</option>
        {folders.map((l) => (
          <option key={String(l.id)} value={String(l.id)}>
            {l.name}
          </option>
        ))}
      </select>
    );
  }
  if (field === "notes" && multiline) {
    return (
      <textarea
        aria-label={label}
        rows={3}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Briefly describe the media content"
        className={cn(className, "resize-none")}
      />
    );
  }
  return (
    <input
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      inputMode={field === "price" ? "decimal" : undefined}
      placeholder={PLACEHOLDER[field]}
      className={className}
    />
  );
}

/** Batch edit's criteria (#115); Hashtags and Notes start ticked. An empty
 *  list means All, as the bundle's `EditInfoModal` has it. */
const CRITERIA = [
  { key: "tag", label: "Tag other Creator(s)" },
  { key: "category", label: "Category" },
  { key: "hashtags", label: "Hashtags" },
  { key: "notes", label: "Notes" },
  { key: "price", label: "Suggested price", chip: "Price" },
] as const;
const DEFAULT_CRITERIA = ["hashtags", "notes"];

/** Batch edit media (#113 to #117): the criteria pick which fields show, and
 *  Save writes the shown fields onto every selected row — only those keys, as
 *  the bundle's `batchModifyCurrentlyVaultToBeUploaded` does. */
export function BatchEditModal({
  onClose,
  onSave,
  folders,
}: {
  onClose: () => void;
  onSave: (values: RowMeta) => void;
  folders: VaultList[];
}) {
  const [criteria, setCriteria] = useState<string[]>(DEFAULT_CRITERIA);
  const [values, setValues] = useState<RowMeta>({});
  const all = criteria.length === 0 || criteria.length === CRITERIA.length;
  const toggle = (key: string) => {
    const next = criteria.includes(key) ? criteria.filter((k) => k !== key) : [...criteria, key];
    setCriteria(next.length === CRITERIA.length ? [] : next);
  };
  const chip = (on: boolean) =>
    cn(
      "rounded-full border px-3 py-1 text-xs",
      on ? "border-accent bg-accent/15 text-accent" : "border-border text-fg-dim hover:text-fg",
    );
  const shown = CRITERIA.filter((c) => all || criteria.includes(c.key));
  const save = () => {
    const out: RowMeta = {};
    for (const c of shown) out[c.key] = values[c.key] ?? "";
    onSave(out);
  };
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="vault-batch-edit-title"
        className="w-full max-w-[600px] rounded-lg border border-border bg-panel p-6 shadow-2xl"
      >
        <h2 id="vault-batch-edit-title" className="text-base font-medium">
          Batch edit media
        </h2>
        <div className="mt-4 flex items-center gap-1 text-sm font-medium">
          <span>Select criteria</span>
          <span title="Select the criteria you want to batch-edit" className="text-fg-dim">
            <Info size={14} aria-hidden />
          </span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" aria-pressed={all} onClick={() => setCriteria([])} className={chip(all)}>
            All
          </button>
          <span aria-hidden className="h-4 w-px bg-border" />
          {CRITERIA.map((c) => (
            <button
              key={c.key}
              type="button"
              aria-pressed={criteria.includes(c.key)}
              onClick={() => toggle(c.key)}
              className={chip(criteria.includes(c.key))}
            >
              {"chip" in c ? c.chip : c.label}
            </button>
          ))}
        </div>
        <div className="mt-5 border-t border-border pt-4">
          <div className="mb-3 text-sm font-medium">Edit</div>
          <div className="space-y-4">
            {shown.map((c) => (
              <div key={c.key} className="flex items-start gap-4">
                <span className="w-32 shrink-0 pt-1.5 text-xs">{c.label}</span>
                <MetaField
                  field={c.key}
                  label={c.label}
                  value={values[c.key] ?? ""}
                  onChange={(v) => setValues((cur) => ({ ...cur, [c.key]: v }))}
                  folders={folders}
                  multiline
                  className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs"
                />
              </div>
            ))}
          </div>
        </div>
        <p className="mt-4 flex items-center gap-2 rounded bg-bg-elev-1 px-3 py-2 text-xs">
          <Info size={14} aria-hidden className="shrink-0 text-fg-dim" />
          Saving will update the details for all selected media
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-border px-3 py-1.5 text-xs">
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            className="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
