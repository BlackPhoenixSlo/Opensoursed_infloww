"use client";

/** The preview drawer's item editor (moved out of `VaultManagePanel`): the editable, lockable fields and the
 *  read-only AI read-out. Draft/baseline/save state is `vaultItemEditorReducer`. */

import { type ReactNode, useEffect, useReducer, useState } from "react";

import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { type Tile } from "@/components/vault/vaultManageActions";
import {
  buildPatch,
  canSave,
  fieldsFromAi,
  initialEditorState,
  isDirty,
  vaultItemEditorReducer,
  type EditorField,
} from "@/components/vault/vaultItemEditorReducer";

/** PATCH /admin/vault-ai/items/{id} — override + lock the operator-edited fields
 *  (contract §6c). `fields` carries only the changed keys so only those lock. */
async function saveVaultItem(
  accountId: string,
  mediaId: number,
  fields: Record<string, unknown>,
): Promise<{ item: Record<string, unknown>; locked: string[] }> {
  return relay.patch(
    `/admin/vault-ai/items/${mediaId}`,
    { account_id: accountId, fields },
    { accountId },
  );
}

/** The three answers the flags pass gives per region. Must match
 *  `vault_ai_brief.VIS_STATES` — the server rejects anything else with a 400
 *  rather than storing a value no lane knows how to read. */
const VIS_OPTIONS = ["bare", "covered", "not_in_frame"];

// explicitness tiers the pricing bands key off (contract §1 bands_by_tier).
const TIER_OPTIONS = ["safe", "suggestive", "explicit", "graphic", "unknown"];

// What the model found, ranked by what an operator actually acts on. PRIMARY is
// shown expanded; everything else sits below the fold behind a toggle. `beats`
// leads because it's the clip's ordered progression — the whole reason a long
// video is worth describing.
const AI_PRIMARY = [
  "acts",
  "clothing_state",
  "penetration",
  "position",
  "primary_folder",
  "explicitness",
] as const;
// Internal bookkeeping stamps, not model output.
const AI_HIDE = new Set(["beats", "description", "tags", "_prompt_version", "_frames"]);

function fmtAi(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (v === true) return "yes";
  if (v === false) return "no";
  return String(v);
}

function AiRows({ entries }: { entries: [string, unknown][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px] m-0">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg-dim whitespace-nowrap">{k.replace(/_/g, " ")}</dt>
          <dd className="m-0 text-fg break-words">{fmtAi(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The V2 describe taxonomy (`_ai.fields`, projected from `ai_fields_json`).
 *  These ~20 fields have always been STORED; until now nothing rendered them,
 *  so a described item looked like it only had a sentence and some tags.
 *  Read-only — the editable, lockable fields are the real columns. */
function AiFieldsPanel({ fields }: { fields?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  if (!fields || Object.keys(fields).length === 0) return null;

  const beats = Array.isArray(fields.beats) ? (fields.beats as unknown[]) : [];
  const live = Object.entries(fields).filter(
    ([k, v]) =>
      !AI_HIDE.has(k) && v !== null && v !== "" && v !== "none" &&
      !(Array.isArray(v) && v.length === 0),
  );
  const primary = live.filter(([k]) => (AI_PRIMARY as readonly string[]).includes(k));
  const rest = live.filter(([k]) => !(AI_PRIMARY as readonly string[]).includes(k));

  return (
    <div className="space-y-2">
      {beats.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-fg-dim mb-1">
            What happens ({beats.length} steps)
          </div>
          <ol className="list-decimal pl-4 text-[12.5px] text-fg space-y-0.5 m-0">
            {beats.map((b, i) => (
              <li key={i}>{String(b)}</li>
            ))}
          </ol>
        </div>
      )}
      {primary.length > 0 && <AiRows entries={primary} />}
      {rest.length > 0 && (
        <div className="rounded-lg border border-border bg-bg-elev-1/40">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[11px] uppercase tracking-wide text-fg-dim hover:text-fg"
          >
            <span>{open ? "▾" : "▸"}</span>
            <span>More AI detail</span>
            <span className="text-fg-dim/70 normal-case tracking-normal">
              {rest.length} fields
            </span>
          </button>
          {open && (
            <div className="px-2.5 pb-2.5">
              <AiRows entries={rest} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Click-to-edit detail/editor for one tile: the FULL description, short tags,
 *  explicitness tier, and suggested caption/script — all editable. Save writes
 *  ONLY the changed fields through the override+lock endpoint (contract §6c), so
 *  a later Describe rerun can't clobber what the operator touched. */
export function VaultItemEditor({
  media,
  accountId,
  onSaved,
  mediaSlot,
  deleteSlot,
}: {
  media: Tile;
  accountId: string;
  onSaved: (updated: Record<string, unknown>) => void;
  /** The preview image/player. Rendered BELOW the action bar so Save and Remove
   *  are reachable without scrolling past a tall video. */
  mediaSlot?: ReactNode;
  deleteSlot?: ReactNode;
}) {
  const ai = (media._ai ?? {}) as Record<string, unknown>;
  const described =
    !!ai.description || !!ai.video_description || !!(ai.tags as unknown[] | undefined)?.length;

  // Draft vs a per-field baseline, and the save — see `vaultItemEditorReducer`.
  // The open item's `_ai` can change under the editor (Re-describe, the merge
  // after a save): untouched fields follow it, edited ones keep the edit.
  const [ed, dispatch] = useReducer(vaultItemEditorReducer, ai, (a) => initialEditorState(fieldsFromAi(a)));
  useEffect(() => {
    dispatch({ type: "refresh", fields: fieldsFromAi((media._ai ?? {}) as Record<string, unknown>) });
  }, [media._ai]);
  const { draft, saved, err, locked } = ed;
  const saving = ed.pending !== null;
  const dirty = isDirty(ed);
  const set = (field: EditorField) => (value: string) => dispatch({ type: "edit", field, value });

  async function onSave() {
    if (!canSave(ed)) return;
    const fields = buildPatch(ed);
    dispatch({ type: "saveStart" });
    try {
      const res = await saveVaultItem(accountId, media.id, fields);
      dispatch({ type: "saveOk", locked: res.locked ?? [] });
      onSaved(res.item ?? {});
    } catch (e) {
      dispatch({ type: "saveFail", msg: e instanceof Error ? e.message : "save failed" });
    }
  }

  const lockBadge = (field: string) =>
    locked.has(field) ? <span className="ml-1 text-[10px] text-warn" title="Locked — a Describe rerun won't overwrite this">🔒</span> : null;

  const label = "text-[11px] uppercase tracking-wide text-fg-dim";
  const inputCls =
    "w-full px-2 py-1.5 rounded-md text-base md:text-sm bg-bg-elev-1 border border-border focus:border-accent outline-none";

  return (
    <div className="space-y-2.5">
      {/* Actions first, and sticky: Save and Remove stay reachable no matter how
          far down the fields you've scrolled, and you never have to scroll PAST
          a tall video to reach them. */}
      <div className="sticky top-0 z-10 -mx-3 px-3 py-2 bg-panel/95 backdrop-blur-sm border-b border-border flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={!dirty || saving}
          className="px-3 py-1.5 rounded-lg text-sm border border-accent bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save & lock"}
        </button>
        {deleteSlot}
        <span className="ml-auto text-right">
          {saved && !err && (
            <span className="text-xs text-ok">
              Saved — locked {saved.length} field{saved.length === 1 ? "" : "s"}
            </span>
          )}
          {err && <span className="text-xs text-err">{err}</span>}
        </span>
      </div>
      {mediaSlot}
      {!described && (
        <div className="text-xs text-fg-dim">Not described yet — click Describe, or write fields below.</div>
      )}
      <div>
        <div className={label}>Description{lockBadge("description")}</div>
        <textarea
          value={draft.desc}
          onChange={(e) => set("desc")(e.target.value)}
          rows={3}
          placeholder="Full description…"
          className={cn(inputCls, "mt-1 resize-y")}
        />
      </div>
      {/* The AI read-out sits directly under the description — it's what you
          check the description against, and it drives foldering. */}
      <AiFieldsPanel fields={ai.fields as Record<string, unknown> | undefined} />
      <div>
        <div className={label}>Tags{lockBadge("tags")}</div>
        <input
          value={draft.tags}
          onChange={(e) => set("tags")(e.target.value)}
          placeholder="comma, separated, tags"
          className={cn(inputCls, "mt-1")}
        />
      </div>
      <div>
        <div className={label}>
          What is on show — decides the folder, the price and whether it can be
          mass-sent
        </div>
        <div className="flex gap-2 mt-1">
          {(
            [
              ["breasts", draft.breasts, set("breasts"), "breasts_vis"],
              ["vulva", draft.vulva, set("vulva"), "vulva_vis"],
              ["anus", draft.anus, set("anus"), "anus_vis"],
            ] as const
          ).map(([name, val, set, field]) => (
            <div key={name} className="flex-1">
              <div className="text-[10px] text-fg-dim">
                {name}
                {lockBadge(field)}
              </div>
              <select
                value={VIS_OPTIONS.includes(val) ? val : ""}
                onChange={(e) => set(e.target.value)}
                className={cn(inputCls, "mt-0.5")}
              >
                <option value="">—</option>
                {VIS_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v === "not_in_frame" ? "not in frame" : v}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <div className="flex-1">
          <div className={label}>Tier{lockBadge("explicitness_tier")}</div>
          <select
            value={TIER_OPTIONS.includes(draft.tier) ? draft.tier : ""}
            onChange={(e) => set("tier")(e.target.value)}
            className={cn(inputCls, "mt-1")}
          >
            <option value="">—</option>
            {TIER_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <div className={label}>Price{lockBadge("suggested_price_cents")}</div>
          <div className="relative mt-1">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-base md:text-sm text-fg-dim pointer-events-none">
              $
            </span>
            <input
              value={draft.price}
              onChange={(e) => set("price")(e.target.value)}
              inputMode="decimal"
              placeholder="—"
              title="Your price for this media. Attaching media in chat prices the message at the HIGHEST price among the selected items."
              className={cn(inputCls, "pl-5")}
            />
          </div>
        </div>
      </div>
      <div>
        <div className={label}>Suggested caption{lockBadge("suggested_caption")}</div>
        <input
          value={draft.cap}
          onChange={(e) => set("cap")(e.target.value)}
          placeholder="One-line PPV/DM caption…"
          className={cn(inputCls, "mt-1")}
        />
      </div>
      <div>
        <div className={label}>Suggested script{lockBadge("suggested_script")}</div>
        <textarea
          value={draft.script}
          onChange={(e) => set("script")(e.target.value)}
          rows={2}
          placeholder="Longer sell copy for this item…"
          className={cn(inputCls, "mt-1 resize-y")}
        />
      </div>
      {!dirty && !saved && !err && (
        <div className="text-xs text-fg-dim pt-0.5">Edit a field to enable save.</div>
      )}
    </div>
  );
}
