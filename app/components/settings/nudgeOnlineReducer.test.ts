import { describe, expect, it } from "vitest";

import type { NudgeConfig } from "@/hooks/useNudgeConfig";
import {
  buildConfig, canSave, effectiveConfig, gateNote, hasUnsavedEdits, initialNudgeOnlineState, isDirty,
  nudgeOnlineReducer, parseSlotsJson, pickedIds, preSaveConfig, previewPayload, rolloutBlock, sameConfig,
  type NudgeOnlineAction, type NudgeOnlineState, type SaveGateInput,
} from "./nudgeOnlineReducer";

const A = "100000001";
const B = "100000002";
const SLOTS = { default: { morning_1: { text: ["hi {name}"], image: [5] } } };
const EFF: NudgeConfig = { enabled: true, delay_minutes: 4, slots: SLOTS };

// The clock (ms): a config cached before the save, the save's start (savedAt = Infinity until it
// settles) and settle, a refetch after it.
const STALE = 100;
const SAVE_AT = 200;
const SETTLED = 300;
const FRESH = 400;

/** "save" = what the tab's save() dispatches: saveStart with the draft's config. */
type Step = NudgeOnlineAction | "save";
const run = (steps: Step[], from = initialNudgeOnlineState): NudgeOnlineState =>
  steps.reduce<NudgeOnlineState>((s, a) => nudgeOnlineReducer(s,
    a === "save" ? { type: "saveStart", cfg: buildConfig(s), accountId: s.accountId ?? A } : a), from);
type Settle = Extract<NudgeOnlineAction, { type: "saveOk" | "saveErr" }>;
const okFor = (accountId: string): Settle => ({ type: "saveOk", accountId, at: SETTLED });
const errFor = (accountId: string, msg = "boom"): Settle => ({ type: "saveErr", msg, accountId, at: SETTLED });
const OK_A = okFor(A);
/** The config query's data landing (`fetchedAt` = its dataUpdatedAt; `pending` = a save PUT in flight). */
const hy = (eff: NudgeConfig, accountId: string | null = A, fetchedAt = FRESH, pending = false): NudgeOnlineAction =>
  ({ type: "hydrate", eff, accountId, fetchedAt, pending });
const to = (accountId: string): NudgeOnlineAction => ({ type: "account", accountId });
const loaded = (eff = EFF, accountId = A) => run([to(accountId), hy(eff, accountId, STALE)]);

describe("hydrate", () => {
  it("loads form, slots and the JSON view from the effective config", () => {
    const s = loaded();
    expect(s.form).toEqual({ enabled: true, delay_minutes: 4 });
    expect(s.slots).toEqual(SLOTS);
    expect(JSON.parse(s.jsonDraft)).toEqual(SLOTS);
    expect(hasUnsavedEdits(s)).toBe(false);
    expect(isDirty(s)).toBe(false);
  });

  it.each<[string, NudgeOnlineAction]>([
    ["a field edit", { type: "field", k: "delay_minutes", v: 9 }],
    ["a slot edit", { type: "slots", slots: { default: {} } }],
    ["unapplied JSON typing", { type: "jsonDraft", text: "{\"weekend\": {}}" }],
  ])("refetch while dirty keeps edits — %s", (_name, edit) => {
    const edited = run([edit], loaded());
    const refetched = nudgeOnlineReducer(edited, hy({ ...EFF, delay_minutes: 6 }, A));
    expect(refetched.form).toEqual(edited.form);
    expect(refetched.slots).toEqual(edited.slots);
    expect(refetched.jsonDraft).toBe(edited.jsonDraft);
    expect(hasUnsavedEdits(refetched)).toBe(true);
    // …while `base` follows the server, so the roll-out gate compares to it.
    expect(refetched.base?.delay_minutes).toBe(6);
  });

  it("refetch while clean takes the server's values", () => {
    const s = nudgeOnlineReducer(loaded(), hy({ ...EFF, delay_minutes: 6 }, A));
    expect(s.form.delay_minutes).toBe(6);
  });

  it.each<[string, NudgeOnlineAction[]]>([
    ["field edit then revert", [
      { type: "field", k: "delay_minutes", v: 9 }, { type: "field", k: "delay_minutes", v: 4 }]],
    ["slot edit then revert", [{ type: "slots", slots: { default: {} } }, { type: "slots", slots: SLOTS }]],
    ["JSON typing then revert", [
      { type: "jsonDraft", text: "{" }, { type: "jsonDraft", text: JSON.stringify(SLOTS, null, 2) }]],
  ])("refetch after edit-then-revert applies — %s", (_name, edits) => {
    const reverted = run(edits, loaded());
    expect(hasUnsavedEdits(reverted)).toBe(false);
    const s = nudgeOnlineReducer(reverted, hy({ ...EFF, delay_minutes: 6 }, A));
    expect(s.form.delay_minutes).toBe(6);
    expect(isDirty(s)).toBe(false);
  });

  it("another account's config is ignored", () => {
    const s = loaded();
    expect(nudgeOnlineReducer(s, hy({ enabled: false }, B))).toBe(s);
  });

});

describe("account", () => {
  const lines: Step[] = [{ type: "runMsg", msg: "ran" }, { type: "previewErr", msg: "bad" }];

  // No hydrate after the pick: B's config GET failed (or is still loading).
  it.each<[string, Step[]]>([
    ["a save in flight", ["save", ...lines]],
    ["a failed save", ["save", errFor(A), ...lines]],
    ["a landed save", ["save", OK_A, ...lines]],
  ])("the pick drops A's draft, lines and %s before B's config lands", (_name, steps) => {
    const from = run([{ type: "field", k: "delay_minutes", v: 9 }, ...steps], loaded());
    expect([from.save, from.saving]).not.toEqual([null, null]);
    const s = nudgeOnlineReducer(from, to(B));
    expect([s.save, s.runMsg, s.previewErr, s.saving, s.base]).toEqual([null, null, null, null, null]);
    expect([s.form, s.accountId]).toEqual([{}, B]);
  });

  it("keeps the roll-out checklist and its line", () => {
    const from = run([{ type: "setModels", ids: [A] }, { type: "bulkMsg", msg: "done" }], loaded());
    const s = nudgeOnlineReducer(from, to(B));
    expect([s.selected, s.bulkMsg]).toEqual([new Set([A]), "done"]);
  });

  it("the same account is a no-op", () => {
    const s = run(["save"], loaded());
    expect(nudgeOnlineReducer(s, to(A))).toBe(s);
  });
});

describe("edits and the save verdict", () => {
  const verdict = run(["save", OK_A], loaded());

  it("saveOk sets the verdict", () => {
    expect(verdict.save).toEqual({ ok: true });
  });

  it.each<[string, NudgeOnlineAction, boolean]>([
    ["field clears it", { type: "field", k: "enabled", v: false }, true],
    ["slots clears it", { type: "slots", slots: {} }, true],
    ["good applyJson clears it", { type: "applyJson" }, true],
    ["JSON typing keeps it", { type: "jsonDraft", text: "{" }, false],
    ["a roll-out pick keeps it", { type: "setModels", ids: [A] }, false],
    ["Run now's line keeps it", { type: "runMsg", msg: "Run failed: x" }, false],
    ["Preview's line keeps it", { type: "previewErr", msg: "Preview failed" }, false],
  ])("%s", (_name, a, clears) => {
    expect(nudgeOnlineReducer(verdict, a).save).toEqual(clears ? null : { ok: true });
  });

  it.each<[string, keyof NudgeOnlineState, Step[]]>([
    ["save verdict", "save", ["save", errFor(A)]],
    ["Run now's line", "runMsg", [{ type: "runMsg", msg: "ran" }]],
    ["Preview's line", "previewErr", [{ type: "previewErr", msg: "Preview failed: x" }]],
  ])("saveStart clears the %s", (_name, key, before) => {
    const s = run([...before, "save"], loaded());
    expect(s[key]).toBeNull();
  });

  it("saveErr sets the save's error and ends the save", () => {
    const s = run(["save", errFor(A)], loaded());
    expect(s.save).toEqual({ ok: false, err: "boom" });
    expect(s.saving).toBeNull();
  });

  it.each<[string, Step[], Settle]>([
    ["saveOk for another account", ["save"], okFor(B)],
    ["saveErr for another account", ["save"], errFor(B, "x")],
    ["saveOk without a snapshot", [], OK_A],
  ])("%s is ignored (only its account's savedAt is stamped)", (_name, steps, last) => {
    const before = run(steps, loaded());
    expect(nudgeOnlineReducer(before, last)).toEqual({
      ...before, savedAt: { ...before.savedAt, [last.accountId]: SETTLED },
    });
  });

  it("a second saveStart while saving is ignored (one PUT's snapshot)", () => {
    const first = run([{ type: "field", k: "delay_minutes", v: 9 }, "save"], loaded());
    const again = run([{ type: "field", k: "delay_minutes", v: 7 }, "save"], first);
    expect(again.saving?.delay_minutes).toBe(9);
  });
});

describe("account switch mid-save", () => {
  const away: Step[] = [
    { type: "field", k: "delay_minutes", v: 9 }, "save",
    to(B), hy({ delay_minutes: 1 }, B),
  ];

  it("A's save landing on B does nothing; back on A the refetch shows the saved value", () => {
    const s = run([
      ...away, OK_A,
      to(A),
      hy(EFF, A, STALE), // A's stale cache first: ignored
      hy({ ...EFF, delay_minutes: 9 }, A), // then its refetch
    ], loaded());
    expect(s.save).toBeNull();
    expect(s.form.delay_minutes).toBe(9);
    expect(isDirty(s)).toBe(false);
  });

  it("A's save failing on B does nothing but stamp A", () => {
    const from = run(away, loaded());
    expect(nudgeOnlineReducer(from, errFor(A, "x"))).toEqual({ ...from, savedAt: { [A]: SETTLED } });
  });

  it("A's save failing after A → B → A shows its error on A", () => {
    const s = run([...away, to(A), hy(EFF, A, STALE, true),
      errFor(A)], loaded());
    expect(s.save).toEqual({ ok: false, err: "boom" });
  });
});

describe("a config from before the save (preSaveConfig)", () => {
  const PUT1: NudgeConfig = { ...EFF, delay_minutes: 9 };
  /** A: Delay 9 saved; the picker goes to B and back while the PUT is in flight. */
  const aba: Step[] = [
    { type: "field", k: "delay_minutes", v: 9 }, "save",
    to(B), hy({ delay_minutes: 1 }, B), to(A),
    hy(EFF, A, STALE, true), // A's cached pre-PUT config while the PUT is pending
  ];
  type Want = { seeded: false } | { seeded: true; delay: number | undefined; jitter?: number; dirty: boolean };

  it.each<[string, Step[], Want]>([
    ["A → B → A mid-save: the pre-PUT cache never seeds the form (pending, then fetched before the save)",
      [...aba, OK_A, hy(EFF, A, STALE)], { seeded: false }],
    ["…its fresh refetch after the PUT seeds it with the saved value",
      [...aba, OK_A, hy(EFF, A, STALE), hy(PUT1, A, FRESH)], { seeded: true, delay: 9, dirty: false }],
    ["a refetch landing in the save's settle ms still seeds it (strict <)",
      [...aba, OK_A, hy(PUT1, A, SETTLED)], { seeded: true, delay: 9, dirty: false }],
    ["a config fetched while the PUT was pending is pre-save too",
      [...aba, hy(EFF, A, SAVE_AT + 50, true), OK_A, hy(EFF, A, SAVE_AT + 50)], { seeded: false }],
    ["a config fetched mid-PUT, handed over once busy dropped but before saveOk, is pre-save (Infinity)",
      [...aba, hy(EFF, A, SAVE_AT + 50, false)], { seeded: false }],
    ["…and once saveOk stamps, only the post-PUT refetch seeds it",
      [...aba, hy(EFF, A, SAVE_AT + 50, false), OK_A, hy(PUT1, A, FRESH)], { seeded: true, delay: 9, dirty: false }],
    ["a save error: the stale cache is ignored, the next fresh fetch seeds the form",
      [...aba, errFor(A), hy(EFF, A, STALE), hy(EFF, A, FRESH)], { seeded: true, delay: 4, dirty: false }],
    ["pending blocks even a fresh fetch",
      [{ type: "field", k: "delay_minutes", v: 9 }, "save", hy(PUT1, A, FRESH, true)],
      { seeded: true, delay: 9, dirty: true }],
    ["no switch: a dirty draft keeps its edit over the fresh refetch (stale one ignored)",
      [{ type: "field", k: "delay_minutes", v: 9 }, "save", { type: "field", k: "jitter_minutes", v: 1 },
        OK_A, hy(EFF, A, STALE), hy(PUT1, A, FRESH)], { seeded: true, delay: 9, jitter: 1, dirty: true }],
    ["B's save never blocks A's cached config",
      [to(B), hy({ delay_minutes: 1 }, B), "save", okFor(B), to(A), hy(EFF, A, STALE)],
      { seeded: true, delay: 4, dirty: false }],
    ["A's save in flight never blocks B's cached config",
      ["save", to(B), hy({ delay_minutes: 1 }, B, STALE)], { seeded: true, delay: 1, dirty: false }],
  ])("%s", (_name, steps, want) => {
    const s = run(steps, loaded());
    if (!want.seeded) {
      expect([s.base, s.form]).toEqual([null, {}]);
      return;
    }
    expect(s.base).not.toBeNull();
    expect(s.form.delay_minutes).toBe(want.delay);
    if (want.jitter !== undefined) expect(s.form.jitter_minutes).toBe(want.jitter);
    expect(isDirty(s)).toBe(want.dirty);
  });

  it("savedAt is Infinity from saveStart, the settle time after, for the saving account, and survives the pick", () => {
    expect(run(["save"], loaded()).savedAt).toEqual({ [A]: Infinity });
    expect(run([...aba, OK_A, to(B)], loaded()).savedAt).toEqual({ [A]: SETTLED });
  });

  it("preSaveConfig: pending, or fetched strictly before the account's savedAt", () => {
    const s = { savedAt: { [A]: SETTLED } };
    expect(preSaveConfig(s, { accountId: A, fetchedAt: SETTLED - 1, pending: false })).toBe(true);
    expect(preSaveConfig(s, { accountId: A, fetchedAt: SETTLED, pending: false })).toBe(false);
    expect(preSaveConfig(s, { accountId: A, fetchedAt: FRESH, pending: true })).toBe(true);
    expect(preSaveConfig(s, { accountId: B, fetchedAt: STALE, pending: false })).toBe(false);
    expect(preSaveConfig(s, { accountId: null, fetchedAt: 0, pending: false })).toBe(false);
  });
});

describe("saveOk rebases", () => {
  it("a saved draft is clean and a later refetch may overwrite it", () => {
    const s = run([{ type: "field", k: "delay_minutes", v: 9 }, "save", OK_A], loaded());
    expect(hasUnsavedEdits(s)).toBe(false);
    expect(s.base?.delay_minutes).toBe(9);
    const r = nudgeOnlineReducer(s, hy({ ...EFF, delay_minutes: 9, max_per_tick: 5 }, A));
    expect(r.form.max_per_tick).toBe(5);
  });

  it("an edit made while the save was in flight stays unsaved", () => {
    const s = run([
      { type: "field", k: "delay_minutes", v: 9 }, "save",
      { type: "field", k: "jitter_minutes", v: 1 }, OK_A,
    ], loaded());
    expect(isDirty(s)).toBe(true);
    expect(s.base?.delay_minutes).toBe(9);
    expect(s.base?.jitter_minutes).toBeUndefined();
    const r = nudgeOnlineReducer(s, hy({ ...EFF, delay_minutes: 9 }, A));
    expect(r.form.jitter_minutes).toBe(1);
  });

  it("a save failure keeps the draft dirty", () => {
    const s = run([{ type: "field", k: "delay_minutes", v: 9 }, "save", errFor(A, "x")], loaded());
    expect(isDirty(s)).toBe(true);
    expect(s.base?.delay_minutes).toBe(4);
  });
});

describe("applyJson / parseSlotsJson", () => {
  it.each<[string, string, string | null]>([
    ["object", "{\"weekend\": {}}", null],
    ["empty text = {}", "", null],
    ["array", "[]", "Invalid JSON: must be an object"],
    ["null", "null", "Invalid JSON: must be an object"],
    ["number", "3", "Invalid JSON: must be an object"],
  ])("%s", (_name, text, error) => {
    const r = parseSlotsJson(text);
    expect("error" in r ? r.error : null).toBe(error);
  });

  it("bad JSON sets jsonErr and leaves slots", () => {
    const s = run([{ type: "jsonDraft", text: "{nope" }, { type: "applyJson" }], loaded());
    expect(s.jsonErr).toMatch(/^Invalid JSON:/);
    expect(s.slots).toEqual(SLOTS);
  });

  it("good JSON becomes slots, re-pretty-printed, and clears jsonErr", () => {
    const s = run([
      { type: "jsonDraft", text: "{nope" }, { type: "applyJson" },
      { type: "jsonDraft", text: "{\"weekend\":{}}" }, { type: "applyJson" },
    ], loaded());
    expect(s.slots).toEqual({ weekend: {} });
    expect(s.jsonDraft).toBe(JSON.stringify({ weekend: {} }, null, 2));
    expect(s.jsonErr).toBeNull();
    expect(isDirty(s)).toBe(true);
  });
});

describe("buildConfig / sameConfig / isDirty / effectiveConfig", () => {
  it("buildConfig is form + slots", () => {
    expect(buildConfig(loaded())).toEqual(EFF);
  });

  it.each<[string, NudgeConfig, NudgeConfig, boolean]>([
    ["identical", EFF, EFF, true],
    ["key order ignored", { slots: SLOTS, delay_minutes: 4, enabled: true }, EFF, true],
    ["absent slots = {}", { enabled: true }, { enabled: true, slots: {} }, true],
    ["value differs", { ...EFF, delay_minutes: 5 }, EFF, false],
    ["array order matters", { quiet_hours: [7, 0] }, { quiet_hours: [0, 7] }, false],
  ])("sameConfig: %s", (_name, a, b, same) => {
    expect(sameConfig(a, b)).toBe(same);
  });

  it("not dirty before the first load", () => {
    const s = run([{ type: "field", k: "enabled", v: false }]);
    expect(isDirty(s)).toBe(false);
    expect(hasUnsavedEdits(s)).toBe(false);
  });

  it("editing back to the server value is clean for the roll-out gate", () => {
    const s = run([{ type: "field", k: "delay_minutes", v: 9 }, { type: "field", k: "delay_minutes", v: 4 }], loaded());
    expect(isDirty(s)).toBe(false);
  });

  it("server config wins over defaults; a config without slots stays clean on load", () => {
    const eff = effectiveConfig({ defaults: { delay_minutes: 4, enabled: true }, config: { delay_minutes: 7 } });
    expect(eff).toEqual({ delay_minutes: 7, enabled: true });
    expect(isDirty(loaded(eff))).toBe(false);
    expect(effectiveConfig(undefined)).toEqual({});
  });
});

describe("roll-out checklist", () => {
  const ALL = [A, B];
  const toggle = (id: string): NudgeOnlineAction => ({ type: "toggleModel", id, all: ALL });

  it.each<[string, NudgeOnlineAction[], string[]]>([
    ["every model by default", [], [A, B]],
    ["toggle off one from all", [toggle(A)], [B]],
    ["toggle back on", [toggle(A), toggle(A)], [A, B]],
    ["None", [{ type: "setModels", ids: [] }], []],
    ["None then one", [{ type: "setModels", ids: [] }, toggle(B)], [B]],
    ["All after toggles", [toggle(A), toggle(B), { type: "setModels", ids: null }], [A, B]],
  ])("%s", (_name, actions, want) => {
    expect(pickedIds(run(actions).selected, ALL)).toEqual(want);
  });

  it("a model listed after the first render is checked (null = all)", () => {
    expect(pickedIds(null, [A, B, "c"])).toEqual([A, B, "c"]);
  });

  it.each<[string, NudgeOnlineAction[], string[], string | null]>([
    ["clean + picked → go", [], [A], null],
    ["dirty → save first", [{ type: "field", k: "enabled", v: false }], [A],
      "Save your changes first, then roll out."],
    ["none picked", [], [], "Pick at least one model."],
    ["dirty wins over none picked", [{ type: "field", k: "enabled", v: false }], [],
      "Save your changes first, then roll out."],
    ["picked account not loaded yet → wait (its draft is `{slots:{}}`, not dirty)", [to(B)], [A, B],
      "Wait for this account's settings to load."],
  ])("rolloutBlock: %s", (_name, actions, picked, want) => {
    expect(rolloutBlock(run(actions, loaded()), picked)).toBe(want);
  });
});

describe("previewPayload", () => {
  it.each<[string, string, number | "", ReturnType<typeof previewPayload>]>([
    ["blank fan + hour = sample now", "", "", { fan_id: null, hour: null }],
    ["fan id + hour", " 123456789 ", 13, { fan_id: 123456789, hour: 13 }],
    ["hour 0 is midnight, not blank", "", 0, { fan_id: null, hour: 0 }],
    ["non-numeric fan id refuses", "abc", "", { error: "Fan id must be a number." }],
    ["mixed fan id refuses", "12a", 8, { error: "Fan id must be a number." }],
  ])("%s", (_name, fan, hour, want) => {
    expect(previewPayload(fan, hour)).toEqual(want);
  });
});

describe("canSave / gateNote", () => {
  const OK: SaveGateInput = {
    accountId: A, drafted: true, cfgError: false,
    rulesHasData: true, rulesPlaceholder: false, rulesError: false,
  };
  const LOADING = { failed: false, text: "Loading this account's nudge settings…" };

  it.each<[string, Partial<SaveGateInput>, boolean, "none" | "loading" | "failed"]>([
    ["all loaded", {}, true, "none"],
    ["no account", { accountId: null, drafted: false }, false, "none"],
    ["config loading (or cached, not yet seeded)", { drafted: false }, false, "loading"],
    ["config failed", { drafted: false, cfgError: true }, false, "failed"],
    ["background config refetch failed, draft kept", { cfgError: true }, true, "none"],
    ["rule list in flight", { rulesHasData: false }, false, "loading"],
    ["rule list failed", { rulesHasData: false, rulesError: true }, false, "failed"],
    ["previous account's rules (placeholder)", { rulesPlaceholder: true }, false, "loading"],
    ["background rules refetch failed, data kept", { rulesError: true }, true, "none"],
  ])("%s", (_name, over, want, noteKind) => {
    const g = { ...OK, ...over };
    expect(canSave(g)).toBe(want);
    const n = gateNote(g);
    if (noteKind === "none") expect(n).toBeNull();
    else if (noteKind === "loading") expect(n).toEqual(LOADING);
    else expect(n?.failed).toBe(true);
  });
});
