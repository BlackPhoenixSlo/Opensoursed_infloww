import { sentState, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AccountConfigResp, BrainConfig } from "@/hooks/useAccountConfig";
import type { AutoreplyConfig } from "@/hooks/useAutoreplyConfig";

export interface AutoReplyDraft {
  enabled: boolean;
  delay: number;
  randomise: boolean;
  foldersOn: boolean;
  folders: Set<string>;
  capOn: boolean;
  cap: number;
  newOn: boolean;
  newHours: number;
  newMax: number;
  describe: boolean;
  skipPhotoOnly: boolean;
  model: string;
  effort: string;
}

export type BrainPick = Pick<AccountConfigResp, "model_options" | "effort_options" | "default_model"> & {
  config: Pick<BrainConfig, "model" | "reasoning_effort">;
};

type KeysOf<V> = { [K in keyof AutoReplyDraft]: AutoReplyDraft[K] extends V ? K : never }[keyof AutoReplyDraft];
export type SwitchKey = KeysOf<boolean>;
export type NumberKey = KeysOf<number>;

export type AutoReplyState = SentState<AutoReplyDraft> & {
  modelTouched: boolean;
  typing: Partial<Record<NumberKey, string>>;
};

export type AutoReplyEdit =
  | { type: "switch"; k: SwitchKey; on: boolean }
  | { type: "number"; k: NumberKey; raw: string }
  | { type: "toggleFolder"; id: string }
  | { type: "model"; model: string }
  | { type: "effort"; effort: string };

type BrainSaved = { type: "brainSaved"; pick: Pick2 };

type NumberBlur = { type: "numberBlur"; k: NumberKey };

export type Switched = { type: "switched"; on: boolean };

export type AutoReplyAction = AutoReplyEdit | Saved | BrainSaved | Switched | NumberBlur;

// Delay tops out well under the engine's silence_max_minutes (1115), past which a delay would never fire.
export const LIMITS: Record<NumberKey, readonly [number, number]> = {
  delay: [0, 240],
  cap: [0, 100_000],
  newHours: [1, 8760],
  newMax: [0, 100_000],
};

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;

const clamp = (raw: string, lo: number, hi: number) =>
  Math.max(lo, Math.min(Number(raw) || lo, hi));

const DOLLARS: ReadonlySet<NumberKey> = new Set<NumberKey>(["cap", "newMax"]);

export const numberText = (s: AutoReplyState, k: NumberKey): string => s.typing[k] ?? String(s.draft[k]);

// The effort served is what the account runs (_effective_effort), so a pinned one shows, not a blank.
export function brainSeed(b: BrainPick | null | undefined): Pick<AutoReplyDraft, "model" | "effort"> {
  const m = b?.config.model ?? "";
  const model = m && b?.model_options.includes(m) ? m : "";
  const e = b?.config.reasoning_effort ?? "";
  return { model, effort: e && (b?.effort_options[model] ?? []).includes(e) ? e : "" };
}

export const effortChoices = (d: AutoReplyDraft, b: BrainPick): string[] =>
  d.model ? b.effort_options[d.model] ?? [] : [];

export const answersWith = (d: AutoReplyDraft, b: BrainPick): string => d.model || b.default_model;

type Pick2 = Pick<AutoReplyDraft, "model" | "effort">;
const samePick = (d: Pick2, s: Pick2) => d.model === s.model && d.effort === s.effort;

export function brainPayload<C extends BrainPick["config"]>(
  { draft: d, modelTouched }: AutoReplyState, b: BrainPick & { config: C },
): C | null {
  if (!modelTouched || samePick(d, brainSeed(b))) return null;
  return { ...b.config, model: d.model || null, reasoning_effort: d.effort || null };
}

export const pickOf = (c: BrainPick["config"]): Pick2 => ({ model: c.model ?? "", effort: c.reasoning_effort ?? "" });

export function draftFromConfig(eff: AutoreplyConfig, brain?: BrainPick | null): AutoReplyDraft {
  const delay = eff.silence_min_minutes ?? 24;
  return {
    enabled: !!eff.enabled,
    delay,
    randomise: (eff.step_in_max_minutes ?? 0) > delay,
    foldersOn: eff.folders_enabled ?? true,
    folders: new Set((eff.list_ids ?? []).map(String)),
    capOn: eff.folder_max_spend_cents != null,
    cap: toDollars(eff.folder_max_spend_cents ?? 50_000),
    newOn: !!eff.new_fans_enabled,
    newHours: eff.new_fan_hours ?? 72,
    newMax: toDollars(eff.new_fan_max_spend_cents ?? 1_000),
    describe: !!eff.describe_photos,
    skipPhotoOnly: !!eff.skip_photo_only,
    ...brainSeed(brain),
  };
}

export const initState = (eff: AutoreplyConfig, brain?: BrainPick | null): AutoReplyState =>
  ({ ...sentState(draftFromConfig(eff, brain)), modelTouched: false, typing: {} });

export const randomiseOn = (d: AutoReplyDraft) => d.randomise && d.delay > 0;

// Both sources off with the switch on: nobody qualifies, an "on" that never replies.
export const canSubmit = (d: AutoReplyDraft) => !(d.enabled && !d.foldersOn && !d.newOn);

// Judged on the stored blob, not the draft: the switch saves only `enabled`, so an unsaved source never lands.
export function switchPayload(defaults: AutoreplyConfig, stored: AutoreplyConfig, on: boolean): AutoreplyConfig | null {
  const eff = { ...defaults, ...stored };
  if (on && !eff.folders_enabled && !eff.new_fans_enabled) return null;
  return { ...stored, enabled: on };
}

// The PUT replaces the whole blob: send the stored one back with only this page's fields changed.
export function buildPayload(d: AutoReplyDraft, stored: AutoreplyConfig): AutoreplyConfig {
  return {
    ...stored,
    enabled: d.enabled,
    silence_min_minutes: d.delay,
    step_in_max_minutes: randomiseOn(d) ? d.delay * 2 : 0,
    folders_enabled: d.foldersOn,
    list_ids: [...d.folders].map(Number),
    folder_max_spend_cents: d.capOn ? toCents(d.cap) : null,
    new_fans_enabled: d.newOn,
    new_fan_hours: d.newHours,
    new_fan_max_spend_cents: toCents(d.newMax),
    describe_photos: d.describe,
    skip_photo_only: d.skipPhotoOnly,
  };
}

function editDraft(d: AutoReplyDraft, action: AutoReplyEdit): AutoReplyDraft {
  switch (action.type) {
    case "switch":
      return { ...d, [action.k]: action.on };
    case "number": {
      const [lo, hi] = LIMITS[action.k];
      const v = clamp(action.raw, lo, hi);
      return { ...d, [action.k]: DOLLARS.has(action.k) ? toDollars(toCents(v)) : v };
    }
    case "toggleFolder": {
      const folders = new Set(d.folders);
      if (folders.has(action.id)) folders.delete(action.id); else folders.add(action.id);
      return { ...d, folders };
    }
    case "model":
      return { ...d, model: action.model, effort: "" };
    case "effort":
      return { ...d, effort: action.effort };
  }
}

const sentReducer = withSent(editDraft);

export function autoReplyReducer(s: AutoReplyState, a: AutoReplyAction): AutoReplyState {
  if (a.type === "numberBlur") {
    if (!(a.k in s.typing)) return s;
    const typing = { ...s.typing };
    delete typing[a.k];
    return { ...s, typing };
  }
  if (a.type === "brainSaved") return samePick(s.draft, a.pick) ? { ...s, modelTouched: false } : s;
  if (a.type === "switched") {
    const draft = { ...s.draft, enabled: a.on };
    const sent = s.sent === s.draft ? draft : s.sent && { ...s.sent, enabled: a.on };
    return { ...s, draft, sent };
  }
  return {
    ...sentReducer(s, a),
    modelTouched: s.modelTouched || a.type === "model" || a.type === "effort",
    typing: a.type === "number" ? { ...s.typing, [a.k]: a.raw } : s.typing,
  };
}
