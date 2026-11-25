import type { NudgeConfig, NudgeSlotEntry, NudgeSlots } from "@/hooks/useNudgeConfig";
import { setSlot, type DayBucket } from "@/components/settings/nudgeDayBuckets";
import type { GateNote } from "@/components/settings/StickySaveBar";
import { stableJSON } from "@/lib/pendingDraft";

export type FormKey = Exclude<keyof NudgeConfig, "slots">;

export interface NudgeOnlineState {
  form: NudgeConfig;
  slots: NudgeSlots;
  jsonDraft: string;
  jsonErr: string | null;
  save: { ok: true } | { ok: false; err: string } | null;
  runMsg: string | null;
  preview: PreviewInput;
  previewErr: string | null;
  base: NudgeConfig | null;
  accountId: string | null;
  saving: NudgeConfig | null;
  selected: ReadonlySet<string> | null;
  bulkMsg: string | null;
  savedAt: Record<string, number>;
  restored: { moved: boolean } | null;
}

export interface PreviewInput {
  fan: string;
  hour: number | "";
  day: string;
}

export interface KeptDraft {
  draft: NudgeConfig;
  base: NudgeConfig;
}

export type NudgeOnlineAction =
  | { type: "account"; accountId: string | null }
  | { type: "hydrate"; eff: NudgeConfig; accountId: string | null; fetchedAt: number; pending: boolean;
      draft: KeptDraft | null }
  | { type: "discardDraft" }
  | { type: "field"; k: FormKey; v: NudgeConfig[FormKey] }
  | { type: "slots"; slots: NudgeSlots }
  | { type: "slot"; bucket: DayBucket; key: string; entry: NudgeSlotEntry }
  | { type: "jsonDraft"; text: string }
  | { type: "applyJson" }
  | { type: "saveStart"; cfg: NudgeConfig; accountId: string }
  | { type: "saveOk"; accountId: string; at: number }
  | { type: "saveErr"; msg: string; accountId: string; at: number }
  | { type: "runMsg"; msg: string | null }
  | { type: "preview"; patch: Partial<PreviewInput> }
  | { type: "previewErr"; msg: string | null }
  | { type: "toggleModel"; id: string; all: readonly string[] }
  | { type: "setModels"; ids: readonly string[] | null }
  | { type: "bulkMsg"; msg: string | null };

export const initialNudgeOnlineState: NudgeOnlineState = {
  form: {}, slots: {}, jsonDraft: "", jsonErr: null, save: null, runMsg: null,
  preview: { fan: "", hour: "", day: "" }, previewErr: null,
  base: null, accountId: null, saving: null, selected: new Set(), bulkMsg: null, savedAt: {}, restored: null,
};

export const RESTORED_NOTE = "Unsaved changes restored — Save to keep";
export const RESTORED_MOVED_NOTE = "Saved settings changed since this draft; Save overwrites them";

export function buildConfig(s: Pick<NudgeOnlineState, "form" | "slots">): NudgeConfig {
  return { ...s.form, slots: s.slots };
}

export function sameConfig(a: NudgeConfig, b: NudgeConfig): boolean {
  const norm = (c: NudgeConfig) => stableJSON({ ...c, slots: c.slots ?? {} });
  return norm(a) === norm(b);
}

export function isDirty(s: Pick<NudgeOnlineState, "form" | "slots" | "base">): boolean {
  return s.base !== null && !sameConfig(buildConfig(s), s.base);
}

export function hasUnsavedEdits(
  s: Pick<NudgeOnlineState, "form" | "slots" | "base" | "jsonDraft">,
): boolean {
  if (s.base === null) return false;
  return isDirty(s) || s.jsonDraft !== JSON.stringify(s.slots, null, 2);
}

export function restoredNote(
  s: Pick<NudgeOnlineState, "form" | "slots" | "base" | "restored">,
): NudgeOnlineState["restored"] {
  return s.restored && isDirty(s) ? s.restored : null;
}

export function keptDraft(
  s: Pick<NudgeOnlineState, "form" | "slots" | "base" | "jsonDraft" | "saving">,
): KeptDraft | null {
  return s.base !== null && (hasUnsavedEdits(s) || s.saving)
    ? { draft: buildConfig(s), base: s.base } : null;
}

export function parseSlotsJson(text: string): { slots: NudgeSlots } | { error: string } {
  try {
    const parsed: unknown = JSON.parse(text || "{}");
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("must be an object");
    }
    return { slots: parsed as NudgeSlots };
  } catch (e) {
    return { error: `Invalid JSON: ${(e as Error).message}` };
  }
}

export function pickedIds(selected: ReadonlySet<string> | null, all: readonly string[]): string[] {
  return selected === null ? [...all] : all.filter((id) => selected.has(id));
}

export function shareBlock(s: Pick<NudgeOnlineState, "base">, picked: readonly string[]): string | null {
  // Before the load the draft is {slots:{}}: shared, it would wipe every pick's lines.
  if (s.base === null) return "Wait for this account's settings to load.";
  if (picked.length === 0) return "Pick at least one model.";
  return null;
}

export function previewPayload(
  { fan, hour, day }: PreviewInput,
): { fan_id: number | null; hour: number | null; weekday: string | null } | { error: string } {
  const f = fan.trim();
  if (f && !/^\d+$/.test(f)) return { error: "Fan id must be a number." };
  return { fan_id: f ? Number(f) : null, hour: hour === "" ? null : hour, weekday: day || null };
}

export interface SaveGateInput {
  accountId: string | null;
  drafted: boolean;
  cfgError: boolean;
  rulesHasData: boolean;
  rulesPlaceholder: boolean;
  rulesError: boolean;
}

// drafted is a data-loss guard: Save outside the form ternary would PUT the unseeded {slots:{}} and wipe the blob.
// rulesHasData, not isSuccess: a failed background refetch flips isSuccess while data stays, and would drop Save mid-edit.
export function canSave(g: SaveGateInput): boolean {
  return !!g.accountId && g.drafted && g.rulesHasData && !g.rulesPlaceholder;
}

export function gateNote(g: SaveGateInput): GateNote | null {
  if (canSave(g) || !g.accountId) return null;
  return g.cfgError || g.rulesError
    ? { failed: true,
        text: "Couldn't load this account's nudge settings — Save stays off so it can't write defaults over them or add a second detector." }
    : { failed: false, text: "Loading this account's nudge settings…" };
}

export function preSaveConfig(
  s: Pick<NudgeOnlineState, "savedAt">,
  h: { accountId: string | null; fetchedAt: number; pending: boolean },
): boolean {
  // STRICT <: a config fetched in the same ms as the save's stamp is fresh; <= would drop it and leave the form unseeded.
  return h.pending || (h.accountId !== null && h.fetchedAt < (s.savedAt[h.accountId] ?? 0));
}

function stamp(state: NudgeOnlineState, accountId: string, at: number): NudgeOnlineState {
  return { ...state, savedAt: { ...state.savedAt, [accountId]: at } };
}

function seeded(state: NudgeOnlineState, cfg: NudgeConfig): NudgeOnlineState {
  const { slots, ...form } = cfg;
  const so = slots ?? {};
  return { ...state, form, slots: so, jsonDraft: JSON.stringify(so, null, 2), jsonErr: null };
}

function withSlots(state: NudgeOnlineState, slots: NudgeSlots): NudgeOnlineState {
  return {
    ...state, save: null, slots, jsonDraft: JSON.stringify(slots, null, 2), jsonErr: null,
  };
}

export function nudgeOnlineReducer(state: NudgeOnlineState, action: NudgeOnlineAction): NudgeOnlineState {
  switch (action.type) {
    case "account":
      if (action.accountId === state.accountId) return state;
      return {
        ...initialNudgeOnlineState, accountId: action.accountId,
        savedAt: state.savedAt, selected: state.selected, bulkMsg: state.bulkMsg, preview: state.preview,
      };
    case "hydrate": {
      if (action.accountId !== state.accountId) return state;
      if (preSaveConfig(state, action)) return state;
      if (hasUnsavedEdits(state)) return { ...state, base: action.eff };
      const d = state.base === null ? action.draft : null;
      if (d && !sameConfig(d.draft, action.eff)) {
        return {
          ...seeded(state, d.draft), base: action.eff, save: null,
          restored: { moved: !sameConfig(d.base, action.eff) },
        };
      }
      return { ...seeded(state, action.eff), base: action.eff, restored: null };
    }
    case "discardDraft":
      if (state.base === null) return state;
      return { ...seeded(state, state.base), save: null, restored: null };
    case "field":
      return { ...state, save: null, form: { ...state.form, [action.k]: action.v } };
    case "slots":
      return withSlots(state, action.slots);
    case "slot":
      return withSlots(state, setSlot(state.slots, action.bucket, action.key, action.entry));
    case "jsonDraft":
      return { ...state, jsonDraft: action.text };
    case "applyJson": {
      const r = parseSlotsJson(state.jsonDraft);
      return "error" in r ? { ...state, jsonErr: r.error } : withSlots(state, r.slots);
    }
    case "saveStart":
      if (state.saving) return state;
      return {
        // Infinity while in flight: a config fetched before the settle stamp must read as older than the save.
        ...stamp(state, action.accountId, Infinity), save: null, runMsg: null, previewErr: null, saving: action.cfg,
      };
    case "saveOk": {
      const stamped = stamp(state, action.accountId, action.at);
      if (action.accountId !== state.accountId || state.saving === null) return stamped;
      return { ...stamped, save: { ok: true }, saving: null, base: state.saving, restored: null };
    }
    case "saveErr": {
      const stamped = stamp(state, action.accountId, action.at);
      if (action.accountId !== state.accountId) return stamped;
      return { ...stamped, save: { ok: false, err: action.msg }, saving: null };
    }
    case "runMsg":
      return { ...state, runMsg: action.msg };
    case "preview":
      return { ...state, preview: { ...state.preview, ...action.patch } };
    case "previewErr":
      return { ...state, previewErr: action.msg };
    case "toggleModel": {
      const selected = new Set(state.selected ?? action.all);
      if (selected.has(action.id)) selected.delete(action.id);
      else selected.add(action.id);
      return { ...state, selected };
    }
    case "setModels":
      return { ...state, selected: action.ids && new Set(action.ids) };
    case "bulkMsg":
      return { ...state, bulkMsg: action.msg };
  }
}
