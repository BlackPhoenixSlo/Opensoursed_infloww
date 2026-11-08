"use client";

/**
 * The vault import's per-file details: the model (`RowMeta` as typed, `WireMeta`
 * as the batch route takes it), the one field control the table and Batch edit
 * both draw, and Batch edit itself.
 */

import { useReducer } from "react";
import { Info } from "lucide-react";

import { type VaultList } from "@/lib/relay";
import { IfButton, IfLabel, IfModal } from "@/components/ui/infloww";
import { IF_FIELD, IfNativeSelect } from "@/components/ui/ifSelect";
import { cn } from "@/lib/utils";
import { BATCH_EDIT_INIT, CRITERIA, batchAll, batchEditReducer, batchShown, buildBatchPayload } from "@/components/vault/batchEditState";

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
  id,
}: {
  field: MetaKey;
  label: string;
  value: string;
  onChange: (v: string) => void;
  folders: VaultList[];
  disabled?: boolean;
  multiline?: boolean;
  /** Width, padding, height: the field box is MetaField's own. */
  className?: string;
  /** For a label above it (`htmlFor`). */
  id?: string;
}) {
  if (field === "category") {
    return (
      <IfNativeSelect
        id={id}
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
      </IfNativeSelect>
    );
  }
  const box = cn(IF_FIELD, "outline-none placeholder:text-muted focus:border-accent", className);
  if (field === "notes" && multiline) {
    return (
      <textarea
        id={id}
        aria-label={label}
        rows={3}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Briefly describe the media content"
        className={cn(box, "resize-none")}
      />
    );
  }
  return (
    <input
      id={id}
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      inputMode={field === "price" ? "decimal" : undefined}
      placeholder={PLACEHOLDER[field]}
      className={box}
    />
  );
}

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
  const [s, dispatch] = useReducer(batchEditReducer, BATCH_EDIT_INIT);
  const all = batchAll(s);
  const chip = (on: boolean) =>
    cn(
      "h-8 rounded-md border px-[15px] text-[14px] transition-colors",
      on ? "border-accent bg-accent/10 text-accent" : "border-border text-fg hover:border-accent hover:text-accent",
    );
  const shown = batchShown(s);
  const save = () => onSave(buildBatchPayload(s));
  const field = (key: MetaKey) => cn("w-full px-[11px]", key === "notes" ? "py-1" : "h-8");
  return (
    <IfModal
      title="Batch edit media"
      width={600}
      onClose={onClose}
      footer={
        <>
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" onClick={save}>Save</IfButton>
        </>
      }
    >
      <div className="mb-3 flex items-center gap-1">
        <span>Select criteria</span>
        <span title="Select the criteria you want to batch-edit" className="text-muted">
          <Info size={14} aria-hidden />
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" aria-pressed={all} onClick={() => dispatch({ type: "all" })} className={chip(all)}>
          All
        </button>
        <span aria-hidden className="h-4 w-px bg-border" />
        {CRITERIA.map((c) => (
          <button
            key={c.key}
            type="button"
            aria-pressed={s.criteria.includes(c.key)}
            onClick={() => dispatch({ type: "toggle", key: c.key })}
            className={chip(s.criteria.includes(c.key))}
          >
            {"chip" in c ? c.chip : c.label}
          </button>
        ))}
      </div>
      <div className="mt-6 border-t border-border pt-6">
        {shown.map((c) => (
          <div key={c.key} className="mb-6">
            <IfLabel htmlFor={`batch-${c.key}`}>{c.label}</IfLabel>
            <MetaField
              id={`batch-${c.key}`}
              field={c.key}
              label={c.label}
              value={s.values[c.key] ?? ""}
              onChange={(v) => dispatch({ type: "set", key: c.key, value: v })}
              folders={folders}
              multiline
              className={field(c.key)}
            />
          </div>
        ))}
      </div>
      <p className="flex items-center gap-2 text-[12px] text-muted">
        <Info size={14} aria-hidden className="shrink-0" />
        Saving will update the details for all selected media
      </p>
    </IfModal>
  );
}
