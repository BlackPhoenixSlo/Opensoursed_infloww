/**
 * NudgeOnlineTab's draft as a pure reducer — the form, the slot pools and
 * their JSON view, the save verdict, and the "Roll out to models" checklist.
 *
 *   • `account` is the picker moving: the draft, `base`, the save / Run now /
 *     Preview lines and any save's snapshot all describe the old account, so
 *     they go — on the pick, not when the new config lands (a failed GET never
 *     lands, and the old "Saved ✓" would stand under the new account).
 *   • `hydrate` loads the server's effective config (defaults ⊕ stored) into
 *     the draft — unless the draft has unsaved edits (`hasUnsavedEdits`: it
 *     differs from `base`, or the JSON box holds unapplied text). The config
 *     query refetches (a save's invalidation, the bulk roll-out's, a remount),
 *     and a refetch used to overwrite the form under an operator mid-edit.
 *     Such a draft keeps its edits; only `base` (what the server holds) moves.
 *     Edit-then-revert is clean again, so a refetch applies. A config for an
 *     account the tab is not on is ignored. So is one fetched before this
 *     account's last save settled, or one arriving while a save PUT is in
 *     flight for it (`preSaveConfig`): that is the PRE-save config — back
 *     on A after A → B → A mid-save, the cache still holds it until the save's
 *     refetch lands, and a form seeded from it would put its stale values into
 *     the next Save. The form stays unseeded (Save off) until a fresh one lands.
 *   • `saveStart` snapshots the config being PUT (a second one while saving is
 *     ignored); `saveOk` moves `base` onto that snapshot, so the draft is clean
 *     again — unless it was edited while the save was in flight, in which case
 *     it still differs from `base`. `saveOk`/`saveErr` for an account the tab
 *     is not on are ignored; a `saveOk` with no snapshot too (the tab left and
 *     came back: nothing to rebase onto, the refetch carries the write) —
 *     except that `saveStart` (Infinity: in flight) / `saveOk` / `saveErr`
 *     always stamp `savedAt` for the account that saved, shown or not (it
 *     survives the pick). A
 *     `saveErr` is shown whenever its account is on screen — a failed write
 *     must not vanish because the operator looked at another account meanwhile.
 *   • Every edit (`field`, `slots`, a good `applyJson`) clears the save's
 *     verdict: the pinned bar keeps it in view and must not outlive the state
 *     it describes. Typing in the JSON box counts as unsaved (so a refetch
 *     keeps it) but is not an edit until applied.
 *   • `selected` null = every model (the default and "All").
 */

import type { NudgeConfig, NudgeSlots } from "@/hooks/useNudgeConfig";
import type { GateNote } from "@/components/settings/StickySaveBar";

export type FormKey = Exclude<keyof NudgeConfig, "slots">;

export interface NudgeOnlineState {
  /** The draft, minus `slots`. */
  form: NudgeConfig;
  slots: NudgeSlots;
  /** The Advanced textarea; becomes `slots` on `applyJson`. */
  jsonDraft: string;
  jsonErr: string | null;
  /** The save's own verdict — the pinned bar shows only this. */
  save: { ok: true } | { ok: false; err: string } | null;
  runMsg: string | null;
  previewErr: string | null;
  /** What the server holds (last hydrate or landed save); null = not loaded. */
  base: NudgeConfig | null;
  /** The account the picker is on — the tab's one copy of it. */
  accountId: string | null;
  /** The config a save started on `accountId` is writing. Two roles: `saveOk`'s
   *  rebase snapshot, and save()'s double-click guard for the commit before the
   *  mutation cache reports the PUT pending. The pick drops it. Whether a PUT
   *  is in flight for the shown account (`busy`) is react-query's
   *  (`useNudgeSavePending`). */
  saving: NudgeConfig | null;
  /** Roll-out checklist; null = every model. */
  selected: ReadonlySet<string> | null;
  bulkMsg: string | null;
  /** Per account: Infinity while its save is in flight, then when it settled
   *  (ms) — `preSaveConfig`. */
  savedAt: Record<string, number>;
}

export type NudgeOnlineAction =
  | { type: "account"; accountId: string | null }
  /** `fetchedAt` = the query's dataUpdatedAt; `pending` = a save PUT is in
   *  flight for `accountId` (useNudgeSavePending). */
  | { type: "hydrate"; eff: NudgeConfig; accountId: string | null; fetchedAt: number; pending: boolean }
  | { type: "field"; k: FormKey; v: NudgeConfig[FormKey] }
  | { type: "slots"; slots: NudgeSlots }
  | { type: "jsonDraft"; text: string }
  | { type: "applyJson" }
  /** `accountId` = the account being saved. */
  | { type: "saveStart"; cfg: NudgeConfig; accountId: string }
  /** `at` = Date.now() when the PUT settled. */
  | { type: "saveOk"; accountId: string; at: number }
  | { type: "saveErr"; msg: string; accountId: string; at: number }
  | { type: "runMsg"; msg: string | null }
  | { type: "previewErr"; msg: string | null }
  | { type: "toggleModel"; id: string; all: readonly string[] }
  /** null = All. */
  | { type: "setModels"; ids: readonly string[] | null }
  | { type: "bulkMsg"; msg: string | null };

export const initialNudgeOnlineState: NudgeOnlineState = {
  form: {}, slots: {}, jsonDraft: "", jsonErr: null, save: null, runMsg: null, previewErr: null,
  base: null, accountId: null, saving: null, selected: null, bulkMsg: null, savedAt: {},
};

/** Defaults with the stored config over them — what the automation runs. */
export function effectiveConfig(
  data: { defaults?: NudgeConfig; config?: NudgeConfig } | undefined,
): NudgeConfig {
  return { ...(data?.defaults ?? {}), ...(data?.config ?? {}) };
}

/** The config a save / preview / roll-out sends. */
export function buildConfig(s: Pick<NudgeOnlineState, "form" | "slots">): NudgeConfig {
  return { ...s.form, slots: s.slots };
}

function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object") {
    return Object.fromEntries(
      Object.keys(v as object).sort().map((k) => [k, stable((v as Record<string, unknown>)[k])]),
    );
  }
  return v;
}

/** Same config, ignoring key order; absent `slots` = `{}` (what the draft holds). */
export function sameConfig(a: NudgeConfig, b: NudgeConfig): boolean {
  const norm = (c: NudgeConfig) => JSON.stringify(stable({ ...c, slots: c.slots ?? {} }));
  return norm(a) === norm(b);
}

/** The draft differs from what the server holds — the roll-out gate (a
 *  roll-out pushes the draft to OTHER accounts, so it must be saved here
 *  first). False before the first load. */
export function isDirty(s: Pick<NudgeOnlineState, "form" | "slots" | "base">): boolean {
  return s.base !== null && !sameConfig(buildConfig(s), s.base);
}

/** The hydrate guard: the draft differs from `base`, or the JSON box holds
 *  text not yet applied to `slots` — a refetch must not overwrite either.
 *  False before the first load (nothing to keep). */
export function hasUnsavedEdits(
  s: Pick<NudgeOnlineState, "form" | "slots" | "base" | "jsonDraft">,
): boolean {
  if (s.base === null) return false;
  return isDirty(s) || s.jsonDraft !== JSON.stringify(s.slots, null, 2);
}

/** The Advanced JSON as slot pools, or why not. */
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

/** The checked models, in list order. */
export function pickedIds(selected: ReadonlySet<string> | null, all: readonly string[]): string[] {
  return selected === null ? [...all] : all.filter((id) => selected.has(id));
}

/** Why "Apply + enable" refuses, or null to go. */
export function rolloutBlock(
  s: Pick<NudgeOnlineState, "form" | "slots" | "base">, picked: readonly string[],
): string | null {
  // Before the load the draft is `{slots:{}}`, not dirty — rolled out, it would wipe every pick.
  if (s.base === null) return "Wait for this account's settings to load.";
  if (isDirty(s)) return "Save your changes first, then roll out.";
  if (picked.length === 0) return "Pick at least one model.";
  return null;
}

/** Preview's fan id + hour, or why not (a typo must not preview the sample fan). */
export function previewPayload(
  fan: string, hour: number | "",
): { fan_id: number | null; hour: number | null } | { error: string } {
  const f = fan.trim();
  if (f && !/^\d+$/.test(f)) return { error: "Fan id must be a number." };
  return { fan_id: f ? Number(f) : null, hour: hour === "" ? null : hour };
}

export interface SaveGateInput {
  accountId: string | null;
  /** The draft was seeded from this account's config (`base !== null`). */
  drafted: boolean;
  /** The config GET failed — only picks the note; `drafted` gates. */
  cfgError: boolean;
  /** The rule list's `data !== undefined`. */
  rulesHasData: boolean;
  rulesPlaceholder: boolean;
  rulesError: boolean;
}

/** THE save gate — the in-flow Save and the pinned bar read this one value.
 *
 *  `drafted` is the load half, and it is a DATA-LOSS guard. The form only
 *  exists inside the `!drafted ? … : <Card>` ternary, but the pinned bar
 *  is a sibling of that ternary and renders throughout the fetch — and `busy`
 *  only watches the save PUTs. A bar gated on `busy || !accountId` alone was
 *  live while the form it saves was not on screen, and one click PUT
 *  `{slots:{}}` (the unseeded draft) to /admin/nudge-config — a whole-blob
 *  replace that wipes the account's nudge config. `drafted` (`base !== null`)
 *  is set only by a `hydrate` of THIS account's fetched config (the query has
 *  no placeholderData) or a `saveOk` (itself behind this gate), and the pick
 *  resets it — so it is false while loading, after a failed fetch, and in the
 *  commit where the config is cached but `hydrate` has not seeded the form.
 *
 *  The rule list is the OTHER half: the label says which rule the save lands
 *  on, and `rule` is null until the list lands. (save() used to POST its own
 *  nudge_online rule in that window — two 60s detectors, fans nudged twice.
 *  The PUT now syncs the rule server-side.)
 *
 *  `rulesHasData` (`data !== undefined`), deliberately NOT `isSuccess`: the
 *  list polls every 30s and refetches on focus, and a failed BACKGROUND
 *  refetch flips `isSuccess` false while `data` stays — an `isSuccess` gate
 *  would take Save away mid-edit with nothing on screen to explain it.
 *  `rulesPlaceholder` is the account switch: the query keeps the PREVIOUS
 *  account's rules while the new ones load. */
export function canSave(g: SaveGateInput): boolean {
  return !!g.accountId && g.drafted && g.rulesHasData && !g.rulesPlaceholder;
}

/** Why Save is off — a pinned grey button with nothing beside it reads as
 *  broken. Shown in the pinned bar, which stays on screen while the form
 *  is scrolled away; a failed load is also the card's own text (both on
 *  purpose). Waiting is dim; a failed load red. */
export function gateNote(g: SaveGateInput): GateNote | null {
  if (canSave(g) || !g.accountId) return null;
  return g.cfgError || g.rulesError
    ? { failed: true,
        text: "Couldn't load this account's nudge settings — Save stays off so it can't write defaults over them or add a second detector." }
    : { failed: false, text: "Loading this account's nudge settings…" };
}

/** The fetched config predates this account's last save (its PUT in flight,
 *  or fetched before that save settled) — `hydrate` ignores it. `savedAt` is
 *  Infinity from `saveStart` to `saveOk`/`saveErr`, so a config fetched while
 *  the PUT is in flight (a remount's refetch of a stale cache) is dropped even
 *  in the render where `pending` has already gone false but the settle has not
 *  been dispatched yet.
 *  STRICT `<`: `saveOk` stamps after mutateAsync settles, i.e. after onSettled
 *  started the invalidation refetch — a network read, so it lands no earlier
 *  than that stamp (save() dispatches `saveOk` in the microtasks after), but
 *  can land in the same ms — `<=` would drop that fresh config and leave the
 *  form unseeded (Save off) until the next refetch. A pre-save config is
 *  necessarily older. */
export function preSaveConfig(
  s: Pick<NudgeOnlineState, "savedAt">,
  h: { accountId: string | null; fetchedAt: number; pending: boolean },
): boolean {
  return h.pending || (h.accountId !== null && h.fetchedAt < (s.savedAt[h.accountId] ?? 0));
}

function stamp(state: NudgeOnlineState, accountId: string, at: number): NudgeOnlineState {
  return { ...state, savedAt: { ...state.savedAt, [accountId]: at } };
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
      // The roll-out checklist, its line and `savedAt` span accounts; the rest is the old one's.
      return {
        ...initialNudgeOnlineState, accountId: action.accountId,
        savedAt: state.savedAt, selected: state.selected, bulkMsg: state.bulkMsg,
      };
    case "hydrate": {
      if (action.accountId !== state.accountId) return state;
      if (preSaveConfig(state, action)) return state;
      if (hasUnsavedEdits(state)) return { ...state, base: action.eff };
      const { slots, ...form } = action.eff;
      const so = slots ?? {};
      return { ...state, form, slots: so, jsonDraft: JSON.stringify(so, null, 2), jsonErr: null, base: action.eff };
    }
    case "field":
      return { ...state, save: null, form: { ...state.form, [action.k]: action.v } };
    case "slots":
      return withSlots(state, action.slots);
    case "jsonDraft":
      return { ...state, jsonDraft: action.text };
    case "applyJson": {
      const r = parseSlotsJson(state.jsonDraft);
      return "error" in r ? { ...state, jsonErr: r.error } : withSlots(state, r.slots);
    }
    case "saveStart":
      if (state.saving) return state;
      // In flight = Infinity: the render where the PUT stops being pending can
      // come before saveOk's (a synchronous notify scheduler), and any config
      // fetched until the settle is stamped must read as older than the save.
      return {
        ...stamp(state, action.accountId, Infinity), save: null, runMsg: null, previewErr: null, saving: action.cfg,
      };
    case "saveOk": {
      // A landed / failed save stamps its account (ending Infinity) whichever one is shown.
      const stamped = stamp(state, action.accountId, action.at);
      // No snapshot: the tab left the account mid-save (and maybe came back).
      if (action.accountId !== state.accountId || state.saving === null) return stamped;
      return { ...stamped, save: { ok: true }, saving: null, base: state.saving };
    }
    case "saveErr": {
      const stamped = stamp(state, action.accountId, action.at);
      if (action.accountId !== state.accountId) return stamped;
      return { ...stamped, save: { ok: false, err: action.msg }, saving: null };
    }
    case "runMsg":
      return { ...state, runMsg: action.msg };
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
