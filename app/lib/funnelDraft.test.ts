import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { canSubmit, initialRawJson, rawJsonReducer, type RawJsonAction, type RawJsonState } from "./rawJsonReducer";
import {
  blankStep, editFunnel, EMPTY_FUNNEL, FUNNEL_RAW, followOpen, funnelDraftOf, saveBody, stepErrorText, toDraft, toWire,
  type FunnelDraft, type FunnelEdit,
} from "./funnelDraft";
import type { FunnelFull, FunnelStep } from "@/hooks/useFunnels";

const funnel = rawJsonReducer(FUNNEL_RAW);
const run = (from: RawJsonState<FunnelDraft>, actions: RawJsonAction<FunnelDraft>[]) => actions.reduce(funnel, from);
const reply = (msg: string, step = 1) => ({ ...blankStep("reply", step), messages: [msg] });
const DRAFT: FunnelDraft = { name: "strokes", description: "", opening: "hey", steps: [reply("hi")], open: null };
const body = (steps: unknown, extra: Record<string, unknown> = {}) =>
  JSON.stringify({ name: "n", opening_message: "o", steps, ...extra });
const edit = (text: string) => run(initialRawJson(DRAFT), [{ type: "open" }, { type: "edit", text }]);

describe("FUNNEL_RAW", () => {
  it("open serializes the wired body", () => {
    const s = run(initialRawJson(DRAFT), [{ type: "open" }]);
    expect(JSON.parse(s.text)).toEqual({
      name: "strokes", opening_message: "hey", description: null, steps: [{ step: 1, messages: ["hi"] }],
    });
  });

  it("open with a step the form rejects stays typed", () => {
    const s = run(initialRawJson({ ...DRAFT, steps: [blankStep("reply", 1)] }), [{ type: "open" }]);
    expect(s).toMatchObject({ raw: false, error: "Step 1 needs at least one message (or switch it to AI-generated)." });
  });

  it.each<[string, string, string]>([
    ["not JSON", "{", "Funnel is not valid JSON"],
    ["not an object", "[]", "Funnel must be a JSON object"],
    ["steps not a list", body({}), "steps must be a list."],
    ["step not an object", body(["hi"]), "Step 1 must be an object."],
    ["unknown type", body([{ type: "ppv", messages: ["a"] }]), 'Step 1 has unknown type "ppv"'],
    ["no message, not generated", body([{ messages: [] }]), "Step 1 needs at least one message"],
    ["string price", body([{ type: "paid_ppv", price: "12", messages: ["a"] }]), "Step 1 price must be a whole number"],
    ["fractional price", body([{ type: "paid_ppv", price: 1.5, messages: ["a"] }]), "Step 1 price must be a whole number"],
    ["negative price", body([{ type: "paid_ppv", price: -1, messages: ["a"] }]), "Step 1 price must be a whole number"],
    ["messages not a list", body([{ messages: "a" }]), "Step 1 messages must be a list."],
    ["intervals not a list", body([{ messages: ["a"], check_intervals_min: 5 }]), "Step 1 check_intervals_min must be a list"],
    ["zero interval", body([{ messages: ["a"], check_intervals_min: [0] }]), 'Step 1 interval "0" must be a positive whole number'],
    ["bad PPV interval", body([{ messages: ["a"] }, { type: "paid_ppv", messages: ["a"], check_intervals_min: [0] }]),
      'Step 2 interval "0" must be'],
    ["second step bad", body([{ messages: ["a"] }, { generate: false }]), "Step 2 needs at least one message"],
    ["step number 0", body([{ step: 0, messages: ["a"] }]), "Step 1 step must be a whole number ≥ 1."],
    ["step number a string", body([{ step: "2", messages: ["a"] }]), "Step 1 step must be a whole number ≥ 1."],
    ["step number fractional", body([{ step: 1.5, messages: ["a"] }]), "Step 1 step must be a whole number ≥ 1."],
    ["duplicate step numbers", body([{ step: 3, messages: ["a"] }, { step: 3, messages: ["b"] }]), "Step 2 has the same id as Step 1 (id 3)."],
  ])("rejects %s, keeping the last valid draft", (_name, text, error) => {
    const s = edit(text);
    expect(s.error).toContain(error);
    expect(s.value).toBe(DRAFT);
    expect(canSubmit(s)).toBe(false);
    expect(funnel(s, { type: "close" }).raw).toBe(true);
  });

  it("a valid edit updates the draft, keeping keys the form doesn't model", () => {
    const s = edit(body([
      { messages: ["a"], check_intervals_min: [2, 4], next: { default: 2 } },
      { type: "paid_ppv", price: 15, generate: true, prompt: " sell ", locked_text: true, check_intervals_min: [30] },
    ], { description: " d " }));
    expect(s.error).toBeNull();
    expect(s.value).toMatchObject({ name: "n", opening: "o", description: "d" });
    expect(saveBody(s.value).steps).toEqual([
      { step: 1, messages: ["a"], check_intervals_min: [2, 4], next: { default: 2 } },
      { step: 2, type: "paid_ppv", price: 15, generate: true, prompt: "sell", locked_text: true, check_intervals_min: [30] },
    ]);
  });

  it("save keeps the step numbers as written (gaps, `next` targets); an unnumbered step gets max + 1", () => {
    const s = edit(body([
      { step: 1, messages: ["a"], next: { default: 4 } },
      { messages: ["c"] }, // unnumbered → max + 1 = 5, not its position (2)
      { step: 4, type: "paid_ppv", price: 9, messages: ["b"] },
    ]));
    expect(s.error).toBeNull();
    expect(saveBody(s.value).steps.map((st) => st.step)).toEqual([1, 5, 4]);
    expect(saveBody(s.value).steps[0]).toEqual({ step: 1, messages: ["a"], next: { default: 4 } });
  });

  it("open shows the loaded step numbers, so saving an untouched or edited buffer keeps them", () => {
    const f = { id: 1, name: "n", description: null, opening_message: "o", step_count: 2,
      steps: [{ step: 1, messages: ["a"], next: { default: 7 } }, { step: 7, messages: ["b"] }] } as FunnelFull;
    const opened = run(initialRawJson(funnelDraftOf(f)), [{ type: "open" }]);
    expect(JSON.parse(opened.text).steps.map((st: FunnelStep) => st.step)).toEqual([1, 7]);
    expect(saveBody(opened.value).steps.map((st) => st.step)).toEqual([1, 7]);
    const edited = funnel(opened, { type: "edit", text: opened.text.replace('"b"', '"b2"') });
    expect(saveBody(edited.value).steps).toEqual([
      { step: 1, messages: ["a"], next: { default: 7 } }, { step: 7, messages: ["b2"] },
    ]);
  });

  it("blank name / opener parse (so raw → typed works on a new funnel); saveBody requires them", () => {
    const s = run(initialRawJson(EMPTY_FUNNEL), [{ type: "open" }, { type: "close" }]);
    expect(s).toMatchObject({ raw: false, error: null });
    expect(() => saveBody(s.value)).toThrow("Name is required.");
    expect(() => saveBody({ ...s.value, name: "x" })).toThrow("Opening message is required.");
  });

  it("empty text is an empty funnel", () => {
    expect(edit("  ").value).toEqual(EMPTY_FUNNEL);
  });
});

describe("PPV price", () => {
  it.each<[string, FunnelStep, string, number | undefined]>([
    ["a price", { step: 1, type: "paid_ppv", price: 12, messages: ["a"] }, "12", 12],
    ["$0", { step: 1, type: "paid_ppv", price: 0, messages: ["a"] }, "0", 0],
    ["missing → blank, omitted (server default)", { step: 1, type: "paid_ppv", messages: ["a"] }, "", undefined],
    ["null → blank, omitted (server default)",
      { step: 1, type: "paid_ppv", price: null, messages: ["a"] } as unknown as FunnelStep, "", undefined],
  ])("%s", (_name, wire, draftPrice, wirePrice) => {
    const d = toDraft(wire);
    expect(d.price).toBe(draftPrice);
    const out = toWire(d, 0) as { price?: number };
    expect(out.price).toBe(wirePrice);
    expect("price" in out).toBe(wirePrice !== undefined);
  });

  it("a new PPV step starts at $0", () => {
    expect(blankStep("ppv", 1).price).toBe("0");
  });

  it("a server row with no price round-trips through the raw view unpriced", () => {
    const f = { id: 1, name: "n", description: null, opening_message: "o", step_count: 1,
      steps: [{ step: 2, type: "paid_ppv", messages: ["a"] }] } as unknown as FunnelFull;
    const s = run(initialRawJson(funnelDraftOf(f)), [{ type: "open" }]);
    expect(JSON.parse(s.text).steps).toEqual([{ step: 2, type: "paid_ppv", messages: ["a"] }]);
  });
});

describe("editFunnel", () => {
  // Loaded with a gap (ids 1, 3): typed edits keep the ids.
  const two: FunnelDraft = { ...DRAFT, steps: [reply("a", 1), { ...reply("b", 3), messages: ["b", "c"] }] };
  const ids = (d: FunnelDraft) => saveBody(d).steps.map((s) => s.step);
  const msgs = (d: FunnelDraft) => d.steps.map((s) => s.messages);
  it.each<[string, FunnelEdit, (d: FunnelDraft) => unknown, unknown]>([
    ["header patches name", { type: "header", patch: { name: "x" } }, (d) => [d.name, d.opening], ["x", "hey"]],
    ["addStep appends a blank step numbered max + 1", { type: "addStep", kind: "ppv" }, (d) => d.steps[2], blankStep("ppv", 4)],
    ["removeStep keeps the other ids", { type: "removeStep", i: 0 }, ids, [3]],
    ["moveStep keeps the ids", { type: "moveStep", i: 0, dir: 1 }, ids, [3, 1]],
    ["patchStep patches one step", { type: "patchStep", i: 1, patch: { kind: "ppv" } },
      (d) => d.steps.map((s) => s.kind), ["reply", "ppv"]],
    ["removeStep removes one", { type: "removeStep", i: 0 }, msgs, [["b", "c"]]],
    ["moveStep down swaps", { type: "moveStep", i: 0, dir: 1 }, msgs, [["b", "c"], ["a"]]],
    ["moveStep up from the top is a no-op", { type: "moveStep", i: 0, dir: -1 }, (d) => d, two],
    ["moveStep down from the bottom is a no-op", { type: "moveStep", i: 1, dir: 1 }, (d) => d, two],
    ["patchStep replaces a step's message pool", { type: "patchStep", i: 1, patch: { messages: ["z"] } }, msgs, [["a"], ["z"]]],
  ])("%s", (_name, e, pick, want) => {
    expect(pick(editFunnel(two, e))).toEqual(want);
  });

  it("never mutates its input", () => {
    const snap = JSON.stringify(two);
    editFunnel(two, { type: "moveStep", i: 0, dir: 1 });
    editFunnel(two, { type: "patchStep", i: 0, patch: { messages: ["q"] } });
    expect(JSON.stringify(two)).toBe(snap);
  });
});

describe("followOpen (one step card open, following its step)", () => {
  const at = (open: number | null, len = 3) => ({ open, steps: Array.from({ length: len }, (_, i) => reply(`m${i}`, i + 1)) });
  it.each<[string, number | null, FunnelEdit, number | null]>([
    ["add opens the new step", 1, { type: "addStep", kind: "reply" }, 3],
    ["add with none open", null, { type: "addStep", kind: "ppv" }, 3],
    ["toggle opens a closed card", null, { type: "toggleStep", i: 2 }, 2],
    ["toggle switches cards", 0, { type: "toggleStep", i: 2 }, 2],
    ["toggle closes the open card", 2, { type: "toggleStep", i: 2 }, null],
    ["remove the open one closes", 1, { type: "removeStep", i: 1 }, null],
    ["remove above shifts up", 2, { type: "removeStep", i: 0 }, 1],
    ["remove below keeps", 0, { type: "removeStep", i: 2 }, 0],
    ["move the open one down", 0, { type: "moveStep", i: 0, dir: 1 }, 1],
    ["swap into the open slot", 1, { type: "moveStep", i: 0, dir: 1 }, 0],
    ["out-of-range move is a no-op", 2, { type: "moveStep", i: 2, dir: 1 }, 2],
    ["header edit keeps", 1, { type: "header", patch: { name: "x" } }, 1],
    ["patch keeps", 1, { type: "patchStep", i: 1, patch: {} }, 1],
  ])("%s", (_n, open, e, want) => {
    expect(followOpen(at(open), e)).toBe(want);
    expect(editFunnel({ ...DRAFT, ...at(open) }, e).open).toBe(want);
  });

  it("a toggle changes nothing else", () => {
    expect(editFunnel(DRAFT, { type: "toggleStep", i: 0 })).toEqual({ ...DRAFT, open: 0 });
  });

  it("a raw-JSON edit starts closed (no stale index past the new steps)", () => {
    const s = run(initialRawJson({ ...DRAFT, open: 0 }), [{ type: "open" }, { type: "edit", text: body([]) }]);
    expect(s.value).toMatchObject({ steps: [], open: null });
  });
});

describe("stepErrorText (server 422 → step named by position)", () => {
  const gapped = [{ step: 1 }, { step: 3 }, { step: 7 }];
  it.each<[string, string]>([
    ["step[1] must be an object", "Step 2 must be an object"],
    ["step[0] is missing 'step'", "Step 1 is missing 'step'"],
    ["step[2].step must be a whole number", "Step 3 step must be a whole number"],
    ["step[2].step must be >= 1", "Step 3 step must be >= 1"],
    ["step[1] has unknown type 'ppv' (only 'paid_ppv')", "Step 2 has unknown type 'ppv' (only 'paid_ppv')"],
    ["step[0] needs non-empty 'messages' or 'prompt'/'generate': true",
      "Step 1 needs non-empty 'messages' or 'prompt'/'generate': true"],
    ["step[1].price must be a whole number", "Step 2 price must be a whole number"],
    ["step[1].price must be >= 0", "Step 2 price must be >= 0"],
    ["step[1].locked_text must be true or false", "Step 2 locked_text must be true or false"],
    ["step[0].check_intervals_min must be a non-empty list", "Step 1 check_intervals_min must be a non-empty list"],
    ["step[0].check_intervals_min must be a whole number", "Step 1 check_intervals_min must be a whole number"],
    ["step[0].check_intervals_min must be positive ints", "Step 1 check_intervals_min must be positive ints"],
    ["step[0].next must be an object", "Step 1 next must be an object"],
    ["step[0].next has unknown key 'x' (allowed: bought, ignored, default, keyword)",
      "Step 1 next has unknown key 'x' (allowed: bought, ignored, default, keyword)"],
    ["step[0].next.bought must be a whole number", "Step 1 next.bought must be a whole number"],
    ["step[0].next.keyword must be a non-empty object of {word: step}",
      "Step 1 next.keyword must be a non-empty object of {word: step}"],
    ["step[0].next.keyword has a blank keyword", "Step 1 next.keyword has a blank keyword"],
    ["step[0].next.keyword['hi'] must be a whole number", "Step 1 next.keyword['hi'] must be a whole number"],
    // dangling `next` target (cross-step check): the id is unknown → said so, id kept for the raw view
    ["step[1].next.default → step 9 references no existing step",
      "Step 2 next.default points to a step that does not exist (id 9)."],
    ["step[0].next.keyword['buy'] → step 4 references no existing step",
      "Step 1 next.keyword['buy'] points to a step that does not exist (id 4)."],
    // an id that exists in the sent list → its position, still worded as an error (gapped ids 1, 3, 7)
    ["step[0].next.bought → step 7 references no existing step",
      "Step 1 next.bought points to Step 3 (id 7), which the server could not find."],
    // not a step error → unchanged
    ["steps must be a list", "steps must be a list"],
    ["steps are not JSON-serialisable: bad", "steps are not JSON-serialisable: bad"],
    ["name is required", "name is required"],
    ["relay 500", "relay 500"],
    ["Step 2 needs at least one message (or switch it to AI-generated).",
      "Step 2 needs at least one message (or switch it to AI-generated)."],
  ])("%s", (msg, want) => {
    expect(stepErrorText(msg, gapped)).toBe(want);
  });
});

describe("load repair (stored check_intervals_min the validators refuse)", () => {
  let warn: MockInstance<typeof console.warn>;
  beforeEach(() => { warn = vi.spyOn(console, "warn").mockImplementation(() => {}); });
  afterEach(() => warn.mockRestore());
  let nextId = 100;
  const stored = (steps: FunnelStep[]) =>
    ({ id: nextId++, name: "legacy", description: null, opening_message: "o", step_count: steps.length, steps }) as FunnelFull;

  it.each<[string, unknown, boolean]>([
    ["absent", undefined, false],
    ["null", null, false],
    ["good", [2, 4, 10], false],
    ["not a list", 5, true],
    ["empty list", [], true],
    ["zero", [0], true],
    ["negative", [-1], true],
    ["fraction", [1.5], true],
    ["string entry", ["5"], true],
    ["bool entry", [true], true],
    ["mixed (pre-validator row)", [0, "x"], true],
  ])("%s", (_name, iv, dropped) => {
    // reply steps are the ones the server refuses; PPV rows predate the validator
    for (const type of [undefined, "paid_ppv"]) {
      const s = { step: 3, ...(type ? { type } : {}), messages: ["a"], ...(iv === undefined ? {} : { check_intervals_min: iv }) } as FunnelStep;
      const d = funnelDraftOf(stored([s]));
      expect(d.steps).toEqual(dropped ? [{ ...toDraft(s), intervals: "" }] : [toDraft(s)]);
      if (dropped) expect("check_intervals_min" in saveBody({ ...d, name: "n" }).steps[0]).toBe(false);
    }
    expect(warn).toHaveBeenCalledTimes(dropped ? 2 : 0);
  });

  it("drops it on load (blank → walker default), warns once per funnel, and a save sends no malformed field", () => {
    const f = stored([
      { step: 1, messages: ["a"], next: { default: 3 } },
      { step: 3, type: "paid_ppv", messages: ["b"], check_intervals_min: [0, "x"] } as unknown as FunnelStep,
    ]);
    const d = funnelDraftOf(f);
    expect(d.steps[1].intervals).toBe("");
    expect(d.steps[1].step).toBe(3);
    expect(saveBody({ ...d, name: "n" }).steps).toEqual([
      { step: 1, messages: ["a"], next: { default: 3 } }, { step: 3, type: "paid_ppv", messages: ["b"] },
    ]);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toContain(`(id ${f.id})`);
    expect(warn.mock.calls[0][0]).toContain("Step 2");
    expect(warn.mock.calls[0][0]).toContain("dropped on save");
    funnelDraftOf(f); // re-open on the same page load
    expect(warn).toHaveBeenCalledTimes(1);
    funnelDraftOf(stored(f.steps)); // another funnel
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("a well-formed funnel: no warning, drafts = plain toDraft, request body unchanged", () => {
    const steps: FunnelStep[] = [
      { step: 1, messages: ["a"], check_intervals_min: [2, 4, 10], next: { default: 7 } },
      { step: 7, type: "paid_ppv", price: 9, locked_text: true, messages: ["b"], check_intervals_min: [30] },
      { step: 8, generate: true, prompt: "p" },
    ];
    const f = stored(steps);
    expect(funnelDraftOf(f).steps).toEqual(f.steps.map(toDraft));
    const body = saveBody(funnelDraftOf(f));
    expect(JSON.stringify(body)).toBe(JSON.stringify({
      name: "legacy", opening_message: "o", description: null, steps: [
        { next: { default: 7 }, step: 1, check_intervals_min: [2, 4, 10], messages: ["a"] },
        { step: 7, type: "paid_ppv", price: 9, locked_text: true, check_intervals_min: [30], messages: ["b"] },
        { step: 8, generate: true, prompt: "p" },
      ],
    }));
    expect(warn).not.toHaveBeenCalled();
  });

  it("raw JSON a user types keeps its validation (repair is load-only)", () => {
    expect(edit(body([{ messages: ["a"], check_intervals_min: [0, "x"] }])).error).toContain('Step 1 interval "0" must be');
  });
});
