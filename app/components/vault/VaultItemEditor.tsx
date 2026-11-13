"use client";

/** The vault item popup's editor (`VaultItemModal`): the media pane it is handed, then Infloww's "Media details"
 *  panel — Category, Hashtags, Description, Suggested price always shown; the rest (exposure, tier, caption, script,
 *  the AI and Jev read-outs) behind "More info". Draft/baseline/save state is `vaultItemEditorReducer`. */

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
import {
  aiValue,
  JEV_CONTENT,
  JEV_DETAILS,
  JEV_FEET,
  JEV_FOCUS,
  JEV_OPTIONS,
  optionLabel,
  picksFromAi,
  unsetLabel,
  type JevKey,
  type JevPicks,
} from "@/components/vault/jevPicks";

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
// Shown elsewhere (beats, the editable columns). `_`-prefixed keys are bookkeeping or another pass's blob (`_jev`,
// read out by `JevReading`) and are skipped too.
const AI_HIDE = new Set(["beats", "description", "tags"]);

function fmtAi(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (v === true) return "yes";
  if (v === false) return "no";
  if (typeof v === "number" && !Number.isInteger(v)) return v.toFixed(2);
  if (v && typeof v === "object") return JSON.stringify(v);
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
 *  Read-only — the editable, lockable fields are the real columns. */
function AiFieldsPanel({ fields }: { fields?: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  if (!fields) return null;

  const beats = Array.isArray(fields.beats) ? (fields.beats as unknown[]) : [];
  const live = Object.entries(fields).filter(
    ([k, v]) =>
      !k.startsWith("_") && !AI_HIDE.has(k) && v !== null && v !== "" && v !== "none" &&
      !(Array.isArray(v) && v.length === 0),
  );
  if (beats.length === 0 && live.length === 0) return null;
  const primary = live.filter(([k]) => (AI_PRIMARY as readonly string[]).includes(k));
  const rest = live.filter(([k]) => !(AI_PRIMARY as readonly string[]).includes(k));

  return (
    <div className="space-y-2">
      <div className={LABEL}>AI reading</div>
      {beats.length > 0 && (
        <div>
          <div className="text-[11px] text-fg-dim mb-1">What happens ({beats.length} steps)</div>
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
            className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[11px] text-fg-dim hover:text-fg"
          >
            <span>{open ? "▾" : "▸"}</span>
            <span>More AI detail</span>
            <span className="text-fg-dim/70">{rest.length} fields</span>
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

/** `_ai.fields._jev`, as `service/vault_jev_rules.blob` writes it (the per-frame answers stripped by the relay). */
interface JevBlob {
  status?: string;
  lane5?: string;
  penetration?: string;
  state?: Record<string, string>;
  nn?: { B?: number; G?: number };
  feet_subject?: number | null;
  tags?: Record<string, unknown>;
  at?: string;
  kind?: string;
}

const LANE_TONE: Record<string, string> = {
  free: "border-ok/50 bg-ok/10 text-ok",
  $10: "border-accent/50 bg-accent/10 text-accent",
  $50: "border-accent/50 bg-accent/10 text-accent",
  $100: "border-err/50 bg-err/10 text-err",
  review: "border-warn/50 bg-warn/10 text-warn",
};

const pct = (n: unknown) => (typeof n === "number" ? `${Math.round(n * 100)}%` : "—");
const words = (s: string) => s.replace(/_/g, " ");

/** The Jev pass's reading of this item: its price lane, each region's state, NudeNet's scores and its tag answers.
 *  Nothing when the item has no `_jev`; only the status when the pass failed. */
function JevReading({ jev }: { jev: unknown }) {
  if (!jev || typeof jev !== "object") return null;
  const j = jev as JevBlob;
  const at = j.at ? new Date(j.at) : null;
  const header = (
    <div className={cn(LABEL, "flex items-center gap-2")}>
      <span>Jev reading</span>
      {j.kind === "video" && <span className="normal-case tracking-normal text-fg-dim/80">video</span>}
      {at && !Number.isNaN(at.getTime()) && (
        <span className="ml-auto normal-case tracking-normal text-fg-dim/80">
          {at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
        </span>
      )}
    </div>
  );
  if (j.status && j.status !== "ok") {
    return (
      <div className="space-y-1" data-testid="jev-reading">
        {header}
        <div className="text-[12px] text-warn">status: {j.status}</div>
      </div>
    );
  }
  const rows: [string, ReactNode][] = [];
  if (j.lane5) {
    rows.push([
      "lane",
      <span key="l" className={cn("inline-block rounded px-1.5 py-px border text-[11px] font-medium", LANE_TONE[j.lane5] ?? "border-border text-fg")}>
        {j.lane5}
      </span>,
    ]);
  }
  for (const r of ["breasts", "crotch", "butt"]) {
    if (j.state?.[r]) rows.push([r, words(j.state[r])]);
  }
  if (j.penetration) rows.push(["penetration", j.penetration]);
  if (typeof j.feet_subject === "number") rows.push(["feet subject", pct(j.feet_subject)]);
  if (j.nn) rows.push(["NudeNet", `B ${pct(j.nn.B)} · G ${pct(j.nn.G)}`]);
  const tags = Object.entries(j.tags ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <div className="space-y-1.5" data-testid="jev-reading">
      {header}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px] m-0">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-fg-dim whitespace-nowrap">{k}</dt>
            <dd className="m-0 text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tags.map(([k, v]) => (
            <span key={k} className="rounded bg-bg-elev-2 px-1.5 py-px text-[11px] text-fg-dim">
              {words(k)}: <span className="text-fg">{fmtAi(v)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const JEV_LABEL: Partial<Record<JevKey, string>> = {
  lane: "price lane", breasts_focus: "breasts focus", butt_focus: "butt focus", crotch_focus: "crotch focus", feet_focus: "feet focus",
  feet_detail: "feet",
};

/** The operator's Jev answers (`jevPicks`): one select per key, unset = the AI's reading (shown in the blank
 *  option). Content and Feet up front; the rest behind "Details". Only dispatches. */
function JevPicker({ jev, picks, onPick }: { jev: unknown; picks: JevPicks; onPick: (k: JevKey, v: string | null) => void }) {
  const [details, setDetails] = useState(false);
  const one = (k: JevKey) => {
    const unset = unsetLabel(k, aiValue(jev, k));
    return (
    <label key={k} className="min-w-0">
      <span className="text-[10px] text-fg-dim">{JEV_LABEL[k] ?? words(k)}</span>
      <select
        aria-label={`Jev ${JEV_LABEL[k] ?? words(k)}`}
        title={picks[k] !== undefined ? optionLabel(picks[k] as string) : unset}
        value={picks[k] ?? ""}
        onChange={(e) => onPick(k, e.target.value || null)}
        className={cn(INPUT, "mt-0.5", picks[k] !== undefined && "border-accent/60")}
      >
        <option value="">{unset}</option>
        {JEV_OPTIONS[k].map((v) => (
          <option key={v} value={v}>
            {optionLabel(v)}
          </option>
        ))}
      </select>
    </label>
    );
  };
  const grid = (keys: readonly JevKey[]) => <div className="grid grid-cols-2 gap-2 mt-1">{keys.map(one)}</div>;
  return (
    <div data-testid="jev-picker">
      <div className={LABEL}>What is on show</div>
      <div className="text-[11px] text-fg-dim">
        Decides the folder, the price and whether it can be mass-sent. Blank follows the AI.
      </div>
      {grid(JEV_CONTENT)}
      <div className="text-[11px] text-fg-dim mt-2">Feet</div>
      {grid(JEV_FEET)}
      <button
        type="button"
        aria-expanded={details}
        onClick={() => setDetails((v) => !v)}
        className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-dim hover:text-fg"
      >
        <span aria-hidden>{details ? "▾" : "▸"}</span>
        Details
      </button>
      {details && (
        <div className="space-y-2">
          {grid(JEV_DETAILS)}
          <div>
            <div className="text-[11px] text-fg-dim mt-1">Focus</div>
            {grid(JEV_FOCUS)}
          </div>
        </div>
      )}
    </div>
  );
}

/** The comma list the reducer holds, as chips. */
export const splitTags = (s: string) => s.split(",").map((t) => t.trim()).filter(Boolean);

/** Infloww's Hashtags box: chips with ×, type and press Enter (or a comma) to add. Edits the reducer's `tags` string. */
function HashtagInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState("");
  const chips = splitTags(value);
  const add = (raw: string) => {
    const fresh = splitTags(raw).filter((t, i, a) => !chips.includes(t) && a.indexOf(t) === i);
    if (fresh.length) onChange([...chips, ...fresh].join(", "));
    setText("");
  };
  const remove = (t: string) => onChange(chips.filter((c) => c !== t).join(", "));
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 rounded-md border border-border bg-bg-elev-1 px-1.5 py-1 focus-within:border-accent">
      {chips.map((t) => (
        <span key={t} className="inline-flex items-center gap-0.5 rounded bg-bg-elev-2 pl-1.5 pr-0.5 py-px text-[12px] text-fg">
          {t}
          <button
            type="button"
            aria-label={`Remove hashtag ${t}`}
            onClick={() => remove(t)}
            className="grid h-4 w-4 place-items-center rounded text-fg-dim hover:text-fg"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={text}
        aria-label="Add hashtag"
        placeholder={chips.length ? "" : "Add hashtag…"}
        onChange={(e) => (e.target.value.includes(",") ? add(e.target.value) : setText(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(text);
          } else if (e.key === "Backspace" && text === "" && chips.length) {
            remove(chips[chips.length - 1]);
          }
        }}
        onBlur={() => text.trim() && add(text)}
        className="min-w-[80px] flex-1 bg-transparent px-1 py-0.5 text-base md:text-sm outline-none"
      />
    </div>
  );
}

/** The OF folders this media is in (`listStates`, as OF's vault listing and the mirror's raw row carry it); null when
 *  the tile has no `listStates` at all. */
function folderNames(m: Tile): string[] | null {
  const ls = (m as { listStates?: unknown }).listStates;
  if (!Array.isArray(ls)) return null;
  return ls
    .filter((x): x is { name: string } => !!x && x.type === "custom" && !!x.hasMedia && !!x.name)
    .map((x) => String(x.name));
}

const LABEL = "text-[11px] uppercase tracking-wide text-fg-dim";
const INPUT =
  "w-full px-2 py-1.5 rounded-md text-base md:text-sm bg-bg-elev-1 border border-border focus:border-accent outline-none";

/** Click-to-edit details for one tile: description, hashtags, price up front; tier, exposure, caption, script and the
 *  read-outs behind "More info". Save writes ONLY the changed fields through the override+lock endpoint (contract
 *  §6c), so a later Describe rerun can't clobber what the operator touched. */
export function VaultItemEditor({
  media,
  accountId,
  onSaved,
  mediaSlot,
  deleteSlot,
  describeSlot,
  more,
  onToggleMore,
}: {
  media: Tile;
  accountId: string;
  onSaved: (updated: Record<string, unknown>) => void;
  /** The media pane: left on desktop, on top (42% of the sheet, so it shrinks with the keyboard) on a phone. */
  mediaSlot?: ReactNode;
  deleteSlot?: ReactNode;
  describeSlot?: ReactNode;
  /** "More info" is open. The popup holds it, so it stays as it was while ← → step through items. */
  more: boolean;
  onToggleMore: () => void;
}) {
  const ai = (media._ai ?? {}) as Record<string, unknown>;
  const aiFields = ai.fields as Record<string, unknown> | undefined;
  const described =
    !!ai.description || !!ai.video_description || !!(ai.tags as unknown[] | undefined)?.length;
  const folders = folderNames(media);

  // Draft vs a per-field baseline, and the save — see `vaultItemEditorReducer`.
  // The open item's `_ai` can change under the editor (Re-describe, the merge
  // after a save): untouched fields follow it, edited ones keep the edit.
  const [ed, dispatch] = useReducer(vaultItemEditorReducer, ai, (a) =>
    initialEditorState(fieldsFromAi(a), picksFromAi(a)));
  useEffect(() => {
    const a = (media._ai ?? {}) as Record<string, unknown>;
    dispatch({ type: "refresh", fields: fieldsFromAi(a), picks: picksFromAi(a) });
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

  const idLine = `#${media.id} · ${media.type}${media.duration ? ` · ${Math.round(media.duration)}s` : ""}`;

  return (
    <div className="flex flex-1 min-h-0 min-w-0 flex-col md:flex-row">
      {/* Phone: a thin title bar (the ✕ sits in it), the media, then the details. */}
      <div className="md:hidden shrink-0 h-11 flex items-center px-3 pr-12 text-[13px] text-fg-dim border-b border-border">
        {idLine}
      </div>
      <div className="relative shrink-0 h-[42%] md:h-auto md:flex-1 min-w-0 bg-black">{mediaSlot}</div>

      <div className="flex flex-1 min-h-0 flex-col border-t border-border bg-panel md:w-[340px] md:flex-none md:border-t-0 md:border-l">
        <div className="hidden md:block shrink-0 px-4 pt-3.5 pb-2.5 pr-12 border-b border-border">
          <h2 className="text-[14px] font-semibold text-fg">Media details</h2>
          <div className="text-[11px] text-fg-dim">{idLine}</div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3.5">
          {!described && (
            <div className="text-[11px] text-fg-dim">Not described yet — Describe it, or write the fields.</div>
          )}
          {folders && (
            <div>
              <div className={LABEL}>Category</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {folders.length ? (
                  folders.map((f) => (
                    <span key={f} className="rounded bg-bg-elev-2 px-1.5 py-px text-[12px] text-fg">{f}</span>
                  ))
                ) : (
                  <span className="text-[12px] text-fg-dim">No folder</span>
                )}
              </div>
            </div>
          )}
          <div>
            <div className={LABEL}>Hashtags{lockBadge("tags")}</div>
            <HashtagInput value={draft.tags} onChange={set("tags")} />
          </div>
          <div>
            <div className={LABEL}>Description{lockBadge("description")}</div>
            <textarea
              value={draft.desc}
              onChange={(e) => set("desc")(e.target.value)}
              rows={4}
              placeholder="Full description…"
              className={cn(INPUT, "mt-1 resize-y")}
            />
            <div className="text-right text-[11px] text-fg-dim">{draft.desc.length} chars</div>
          </div>
          <div>
            <div className={LABEL}>Suggested price{lockBadge("suggested_price_cents")}</div>
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
                className={cn(INPUT, "pl-5")}
              />
            </div>
          </div>

          <div className="border-t border-border pt-2">
            <button
              type="button"
              aria-expanded={more}
              onClick={onToggleMore}
              className="flex w-full items-center gap-1.5 text-[12px] text-fg-dim hover:text-fg"
            >
              <span aria-hidden>{more ? "▾" : "▸"}</span>
              More info
            </button>
          </div>
          {more && (
            <div className="space-y-3.5">
              <JevPicker
                jev={aiFields?._jev}
                picks={ed.jev}
                onPick={(key, value) => dispatch({ type: "pick", key, value })}
              />
              <div>
                <div className={LABEL}>Tier{lockBadge("explicitness_tier")}</div>
                <select
                  aria-label="Tier"
                  value={TIER_OPTIONS.includes(draft.tier) ? draft.tier : ""}
                  onChange={(e) => set("tier")(e.target.value)}
                  className={cn(INPUT, "mt-1")}
                >
                  <option value="">—</option>
                  {TIER_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className={LABEL}>Suggested caption{lockBadge("suggested_caption")}</div>
                <input
                  value={draft.cap}
                  onChange={(e) => set("cap")(e.target.value)}
                  placeholder="One-line PPV/DM caption…"
                  className={cn(INPUT, "mt-1")}
                />
              </div>
              <div>
                <div className={LABEL}>Suggested script{lockBadge("suggested_script")}</div>
                <textarea
                  value={draft.script}
                  onChange={(e) => set("script")(e.target.value)}
                  rows={2}
                  placeholder="Longer sell copy for this item…"
                  className={cn(INPUT, "mt-1 resize-y")}
                />
              </div>
              <JevReading jev={aiFields?._jev} />
              <AiFieldsPanel fields={aiFields} />
            </div>
          )}
        </div>

        {/* Actions: the panel's foot on desktop, a bottom bar on a phone — never over the media. */}
        <div className="shrink-0 border-t border-border bg-panel px-4 pt-2.5 pb-[max(10px,env(safe-area-inset-bottom))]">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onSave}
              disabled={!dirty || saving}
              className="px-3 py-1.5 rounded-md text-sm border border-accent bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save & lock"}
            </button>
            {describeSlot}
            {deleteSlot}
          </div>
          <div className="mt-1 min-h-[14px] text-[11px]">
            {saved && !err ? (
              <span className="text-ok">
                {(() => {
                  const n = saved.filter((k) => k !== "jev").length;   // the Jev picks lock nothing
                  return n ? `Saved — locked ${n} field${n === 1 ? "" : "s"}` : "Saved";
                })()}
              </span>
            ) : err ? (
              <span className="text-err">{err}</span>
            ) : !dirty ? (
              <span className="text-fg-dim/70">Edit a field to enable save.</span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
