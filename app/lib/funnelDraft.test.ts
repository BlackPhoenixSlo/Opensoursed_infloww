import { describe, expect, it } from "vitest";

import { canSubmit, initialRawJson, rawJsonReducer, type RawJsonAction, type RawJsonState } from "./rawJsonReducer";
import {
  blankStep, editFunnel, EMPTY_FUNNEL, FUNNEL_RAW, funnelDraftOf, saveBody, toDraft, toWire,
  type FunnelDraft, type FunnelEdit,
} from "./funnelDraft";
import type { FunnelFull, FunnelStep } from "@/hooks/useFunnels";

const funnel = rawJsonReducer(FUNNEL_RAW);
const run = (from: RawJsonState<FunnelDraft>, actions: RawJsonAction<FunnelDraft>[]) => actions.reduce(funnel, from);
const reply = (msg: string, step = 1) => ({ ...blankStep("reply", step), messages: [msg] });
const DRAFT: FunnelDraft = { name: "strokes", description: "", opening: "hey", steps: [reply("hi")] };
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
    ["duplicate step numbers", body([{ step: 3, messages: ["a"] }, { step: 3, messages: ["b"] }]), "Step 2 reuses step number 3."],
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
    ["patchMsg edits one variant", { type: "patchMsg", i: 1, mi: 1, text: "z" }, msgs, [["a"], ["b", "z"]]],
    ["addMsg appends a blank variant", { type: "addMsg", i: 0 }, msgs, [["a", ""], ["b", "c"]]],
    ["removeMsg drops a variant", { type: "removeMsg", i: 1, mi: 0 }, msgs, [["a"], ["c"]]],
    ["removeMsg keeps the last variant", { type: "removeMsg", i: 0, mi: 0 }, msgs, [["a"], ["b", "c"]]],
    ["addMsgs appends, skipping dupes", { type: "addMsgs", i: 1, texts: ["c", "d"] }, msgs, [["a"], ["b", "c", "d"]]],
  ])("%s", (_name, e, pick, want) => {
    expect(pick(editFunnel(two, e))).toEqual(want);
  });

  it("addMsgs replaces a lone blank variant", () => {
    const blank: FunnelDraft = { ...DRAFT, steps: [{ ...reply("a", 1), messages: [""] }] };
    expect(msgs(editFunnel(blank, { type: "addMsgs", i: 0, texts: ["x", "y"] }))).toEqual([["x", "y"]]);
  });

  it("never mutates its input", () => {
    const snap = JSON.stringify(two);
    editFunnel(two, { type: "moveStep", i: 0, dir: 1 });
    editFunnel(two, { type: "patchMsg", i: 0, mi: 0, text: "q" });
    expect(JSON.stringify(two)).toBe(snap);
  });
});
