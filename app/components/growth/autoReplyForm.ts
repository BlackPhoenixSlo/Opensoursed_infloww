/**
 * AutoReplyPage's form as a pure reducer — the draft of the `/admin/autoreply-config`
 * blob the page edits (its Human style boxes: components/automations/humanStyle.ts).
 *
 *   • The draft is seeded once from the effective config (defaults ⊕ stored) when
 *     the form mounts (`draftFromConfig`); a refetch does not re-seed it (the
 *     form is keyed by Creator, so switching Creator re-seeds). There is no
 *     hydrate action, so a refetch can never wipe an unsaved edit.
 *   • `buildPayload` sends the STORED blob back with only this page's fields
 *     changed: the PUT replaces the whole blob, so the engine's other knobs
 *     (quiet hours, reply caps) keep whatever they hold.
 *   • Number inputs arrive as the raw text and are clamped to `LIMITS` here;
 *     blank / junk reads as the low bound.
 *   • The state is the draft plus the draft the last Save sent
 *     (automations/sentDraft.ts: `unsaved` holds "Saved" off over an edit made
 *     while that save was in flight).
 *   • Model + effort are the ACCOUNT's (`account_ai_config.model` /
 *     `reasoning_effort`, the account-config PUT), not this blob's: seeded by
 *     `brainSeed`, sent by `brainPayload` only while a pick made here has not
 *     landed (`modelTouched`: set by a model/effort edit, cleared by
 *     `brainSaved`) and differs from the latest brain. "" = null (model: the
 *     server's `default_model`; effort: the model's own pin).
 */

import { sentState, withSent, type Saved, type SentState } from "@/components/automations/sentDraft";
import type { AccountConfigResp, BrainConfig } from "@/hooks/useAccountConfig";
import type { AutoreplyConfig } from "@/hooks/useAutoreplyConfig";

export interface AutoReplyDraft {
  enabled: boolean;
  /** `silence_min_minutes`. */
  delay: number;
  /** Each reply lands in [delay, 2 x delay] (`step_in_max_minutes`). */
  randomise: boolean;
  foldersOn: boolean;
  /** OF custom list ids, as the ListColumn keys them. */
  folders: Set<string>;
  capOn: boolean;
  /** Folder spend cap, dollars. */
  cap: number;
  newOn: boolean;
  newHours: number;
  /** New-fan spend cap, dollars. */
  newMax: number;
  describe: boolean;
  skipPhotoOnly: boolean;
  /** `account_ai_config.model`; "" = null (the server's `default_model`). */
  model: string;
  /** `account_ai_config.reasoning_effort`; "" = the model's own pin. */
  effort: string;
}

/** The account-config read the Model row needs. */
export type BrainPick = Pick<AccountConfigResp, "model_options" | "effort_options" | "default_model"> & {
  config: Pick<BrainConfig, "model" | "reasoning_effort">;
};

type KeysOf<V> = { [K in keyof AutoReplyDraft]: AutoReplyDraft[K] extends V ? K : never }[keyof AutoReplyDraft];
export type SwitchKey = KeysOf<boolean>;
export type NumberKey = KeysOf<number>;

export type AutoReplyState = SentState<AutoReplyDraft> & {
  /** A model/effort pick made here that no brain PUT has landed yet. */
  modelTouched: boolean;
};

/** An edit of the draft. */
export type AutoReplyEdit =
  | { type: "switch"; k: SwitchKey; on: boolean }
  /** A number input's raw text; clamped to `LIMITS[k]`. */
  | { type: "number"; k: NumberKey; raw: string }
  | { type: "toggleFolder"; id: string }
  /** "" = Default. A new model resets effort to its own pin (the legal set is per model). */
  | { type: "model"; model: string }
  | { type: "effort"; effort: string };

/** The brain PUT carrying `pick` landed. */
type BrainSaved = { type: "brainSaved"; pick: Pick2 };

export type AutoReplyAction = AutoReplyEdit | Saved | BrainSaved;

/** [lo, hi] per number input. The delay tops out well under the engine's
 *  `silence_max_minutes` (default 1115), past which a delay (or its randomised
 *  2x) would never fire. */
export const LIMITS: Record<NumberKey, readonly [number, number]> = {
  delay: [0, 240],
  cap: [0, 100_000],
  newHours: [1, 8760],
  newMax: [0, 100_000],
};

const toCents = (dollars: number) => Math.round(dollars * 100);
const toDollars = (cents: number) => Math.round(cents) / 100;

/** A number input's value, clamped; blank / junk reads as `lo`. */
const clamp = (raw: string, lo: number, hi: number) =>
  Math.max(lo, Math.min(Number(raw) || lo, hi));

/** The model/effort the Model row starts on. A stored model the server no longer
 *  offers runs the default (resolve_model), so it reads "" — and so does an
 *  effort the model does not take. The effort served is what the account runs
 *  (account_config_api `_effective_effort`), so a pinned one shows, not a blank. */
export function brainSeed(b: BrainPick | null | undefined): Pick<AutoReplyDraft, "model" | "effort"> {
  const m = b?.config.model ?? "";
  const model = m && b?.model_options.includes(m) ? m : "";
  const e = b?.config.reasoning_effort ?? "";
  return { model, effort: e && (b?.effort_options[model] ?? []).includes(e) ? e : "" };
}

/** The efforts the picked model takes. Default ("") takes none: the PUT refuses
 *  an effort with `model: null`. */
export const effortChoices = (d: AutoReplyDraft, b: BrainPick): string[] =>
  d.model ? b.effort_options[d.model] ?? [] : [];

/** The model the replies run on right now: the pick, else the server's default. */
export const answersWith = (d: AutoReplyDraft, b: BrainPick): string => d.model || b.default_model;

type Pick2 = Pick<AutoReplyDraft, "model" | "effort">;
const samePick = (d: Pick2, s: Pick2) => d.model === s.model && d.effort === s.effort;

/** The account-config PUT body (the latest stored brain `b` echoed, model/effort set), or null with no pick made here
 *  since the last landed brain PUT, or when the pick already is `b`'s — no Save rewrites the brain idly, an unrelated
 *  Save never reverts a model changed elsewhere, and a pick reverted after a Save still goes out. */
export function brainPayload<C extends BrainPick["config"]>(
  { draft: d, modelTouched }: AutoReplyState, b: BrainPick & { config: C },
): C | null {
  if (!modelTouched || samePick(d, brainSeed(b))) return null;
  return { ...b.config, model: d.model || null, reasoning_effort: d.effort || null };
}

/** The pick a brain PUT body carries (`brainSaved`'s). */
export const pickOf = (c: BrainPick["config"]): Pick2 => ({ model: c.model ?? "", effort: c.reasoning_effort ?? "" });

/** The draft for an effective config (defaults ⊕ stored), plus the account's model pick. */
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

/** The form's state for an effective config: its draft, nothing sent yet. */
export const initState = (eff: AutoreplyConfig, brain?: BrainPick | null): AutoReplyState =>
  ({ ...sentState(draftFromConfig(eff, brain)), modelTouched: false });

/** Randomise only means something above a 0 delay (the switch is disabled at 0). */
export const randomiseOn = (d: AutoReplyDraft) => d.randomise && d.delay > 0;

/** Both sources off with the switch on = nobody qualifies: an "on" that never replies. */
export const canSubmit = (d: AutoReplyDraft) => !(d.enabled && !d.foldersOn && !d.newOn);

/** The PUT body: the stored blob with this page's fields set from the draft. */
export function buildPayload(d: AutoReplyDraft, stored: AutoreplyConfig): AutoreplyConfig {
  return {
    ...stored,
    enabled: d.enabled,
    silence_min_minutes: d.delay,
    // Randomise = each reply lands somewhere in [delay, 2 x delay]; the engine's
    // step-in range does the draw. 0 = a fixed delay.
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

/** One edit of the draft; always a new object (sentDraft.ts `unsaved`). */
function editDraft(d: AutoReplyDraft, action: AutoReplyEdit): AutoReplyDraft {
  switch (action.type) {
    case "switch":
      return { ...d, [action.k]: action.on };
    case "number": {
      const [lo, hi] = LIMITS[action.k];
      return { ...d, [action.k]: clamp(action.raw, lo, hi) };
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
  // A landed brain PUT clears the pick, unless it moved again while the PUT ran.
  if (a.type === "brainSaved") return samePick(s.draft, a.pick) ? { ...s, modelTouched: false } : s;
  return { ...sentReducer(s, a), modelTouched: s.modelTouched || a.type === "model" || a.type === "effort" };
}
