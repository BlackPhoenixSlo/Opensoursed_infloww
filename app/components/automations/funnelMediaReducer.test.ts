import { describe, expect, it } from "vitest";

import type { FunnelAccountMedia } from "@/hooks/useFunnels";
import {
  buildPayload, funnelMediaReducer, initialFunnelMedia, pickerIds,
  type FunnelMediaAction, type FunnelMediaState, type StepDraft,
} from "./funnelMediaReducer";

const MEDIA: FunnelAccountMedia = {
  funnel_id: 1,
  account_id: "a",
  opening_media_ids: [7, 0, 8],
  steps_media: {
    "2": { media_files: [21, 22, -1, 23], previews: [21, 22] },
    "4": { media_files: [41], previews: [41, 99] },
  },
};
const STEPS = [2, 4, 5];
const hydrate: FunnelMediaAction = { type: "hydrate", media: MEDIA, stepNos: STEPS };

const run = (actions: FunnelMediaAction[], s: FunnelMediaState = initialFunnelMedia) =>
  actions.reduce(funnelMediaReducer, s);
const seeded = run([hydrate]);

describe("hydrate", () => {
  it("seeds positive ids in saved order, teaser clamped to the ids", () => {
    expect(seeded.openerIds).toEqual([7, 8]);
    expect(seeded.steps).toEqual({
      "2": { ids: [21, 22, 23], previewCount: 2 },
      "4": { ids: [41], previewCount: 1 },
      "5": { ids: [], previewCount: 0 },
    });
    expect(seeded.seeded).toBe(true);
    expect(seeded.done).toBe(false);
  });
});

describe("transitions", () => {
  it.each<[string, FunnelMediaAction[], Partial<FunnelMediaState>]>([
    ["refetch after seed keeps edits",
      [{ type: "setOpener", ids: [9] }, { type: "setStep", stepNo: 2, patch: { previewCount: 0 } },
        { type: "hydrate", media: { ...MEDIA, opening_media_ids: [1] }, stepNos: STEPS }],
      { openerIds: [9], steps: { ...seeded.steps, "2": { ids: [21, 22, 23], previewCount: 0 } } }],
    ["save with no edit in flight → Saved",
      [{ type: "saveStart" }, { type: "saveOk", rev: seeded.rev }],
      { done: true }],
    ["edit during save keeps Saved off",
      [{ type: "saveStart" }, { type: "setOpener", ids: [1] }, { type: "saveOk", rev: seeded.rev }],
      { done: false, openerIds: [1] }],
    ["edit after Saved clears it",
      [{ type: "saveStart" }, { type: "saveOk", rev: seeded.rev }, { type: "setStep", stepNo: 4, patch: { ids: [] } }],
      { done: false }],
    ["setStep on an unseeded step starts from empty (teaser clamped to no ids)",
      [{ type: "setStep", stepNo: 9, patch: { previewCount: 3 } }],
      { steps: { ...seeded.steps, "9": { ids: [], previewCount: 0 } } }],
    // teaser clamp lives in the reducer: 0 ≤ previewCount ≤ ids.length.
    ["setStep with fewer ids re-clamps the teaser",
      [{ type: "setStep", stepNo: 2, patch: { ids: [21] } }],
      { steps: { ...seeded.steps, "2": { ids: [21], previewCount: 1 } }, rev: seeded.rev + 1 }],
    ["setStep teaser over max clamps to ids.length",
      [{ type: "setStep", stepNo: 2, patch: { previewCount: 9 } }],
      { steps: { ...seeded.steps, "2": { ids: [21, 22, 23], previewCount: 3 } } }],
    ["setStep negative teaser clamps to 0",
      [{ type: "setStep", stepNo: 2, patch: { previewCount: -2 } }],
      { steps: { ...seeded.steps, "2": { ids: [21, 22, 23], previewCount: 0 } } }],
    ["copyToAll copies ids + teaser onto the other PPV steps",
      [{ type: "copyToAll", fromStepNo: 2, stepNos: STEPS }],
      { steps: {
        "2": { ids: [21, 22, 23], previewCount: 2 },
        "4": { ids: [21, 22, 23], previewCount: 2 },
        "5": { ids: [21, 22, 23], previewCount: 2 },
      } }],
    ["copyToAll from an empty step is a no-op",
      [{ type: "copyToAll", fromStepNo: 5, stepNos: STEPS }],
      { steps: seeded.steps, rev: seeded.rev }],
    ["picker on a step: confirm sets ids, re-clamps teaser, closes",
      [{ type: "openPicker", target: 2 }, { type: "pickConfirm", ids: [30] }],
      { pickerFor: null, steps: { ...seeded.steps, "2": { ids: [30], previewCount: 1 } } }],
    ["picker on the opener: confirm replaces the opener ids",
      [{ type: "openPicker", target: "opener" }, { type: "pickConfirm", ids: [5, 6] }],
      { pickerFor: null, openerIds: [5, 6] }],
    ["picker close leaves the draft",
      [{ type: "openPicker", target: 4 }, { type: "closePicker" }],
      { pickerFor: null, steps: seeded.steps, openerIds: [7, 8] }],
    ["pickConfirm with the picker closed is a no-op",
      [{ type: "pickConfirm", ids: [5] }],
      { pickerFor: null, openerIds: [7, 8], steps: seeded.steps, rev: seeded.rev }],
    // move / remove: send order = teaser order; every one is an edit (rev + 1).
    ["move opener right",
      [{ type: "move", target: "opener", i: 0, dir: 1 }],
      { openerIds: [8, 7], rev: seeded.rev + 1, done: false }],
    ["move opener past the end keeps order",
      [{ type: "move", target: "opener", i: 1, dir: 1 }],
      { openerIds: [7, 8], rev: seeded.rev + 1 }],
    ["move step left keeps the teaser count",
      [{ type: "move", target: 2, i: 2, dir: -1 }],
      { steps: { ...seeded.steps, "2": { ids: [21, 23, 22], previewCount: 2 } }, rev: seeded.rev + 1 }],
    ["move step before the start keeps order",
      [{ type: "move", target: 2, i: 0, dir: -1 }],
      { steps: seeded.steps, rev: seeded.rev + 1 }],
    ["remove opener item",
      [{ type: "remove", target: "opener", i: 0 }],
      { openerIds: [8], rev: seeded.rev + 1, done: false }],
    ["remove step item under the teaser count keeps it",
      [{ type: "remove", target: 2, i: 2 }],
      { steps: { ...seeded.steps, "2": { ids: [21, 22], previewCount: 2 } }, rev: seeded.rev + 1 }],
    ["remove step item re-clamps the teaser to the ids left",
      [{ type: "remove", target: 2, i: 0 }, { type: "remove", target: 2, i: 0 }],
      { steps: { ...seeded.steps, "2": { ids: [23], previewCount: 1 } }, rev: seeded.rev + 2 }],
    ["remove the last step item clamps the teaser to 0",
      [{ type: "remove", target: 4, i: 0 }],
      { steps: { ...seeded.steps, "4": { ids: [], previewCount: 0 } }, rev: seeded.rev + 1 }],
    ["remove on an unknown step is a no-op",
      [{ type: "remove", target: 9, i: 0 }],
      { steps: seeded.steps, rev: seeded.rev }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions, seeded)).toMatchObject(want);
  });

  it("pickerIds follows the open target", () => {
    expect(pickerIds(run([{ type: "openPicker", target: "opener" }], seeded))).toEqual([7, 8]);
    expect(pickerIds(run([{ type: "openPicker", target: 2 }], seeded))).toEqual([21, 22, 23]);
    expect(pickerIds(run([{ type: "openPicker", target: 8 }], seeded))).toEqual([]);
    expect(pickerIds(seeded)).toEqual([]);
  });
});

describe("buildPayload", () => {
  it.each<[string, number[], Record<string, StepDraft>, number[], ReturnType<typeof buildPayload>]>([
    ["seeded draft", seeded.openerIds, seeded.steps, STEPS,
      { opening_media_ids: [7, 8], steps_media: {
        "2": { media_files: [21, 22, 23], previews: [21, 22] },
        "4": { media_files: [41], previews: [41] },
      } }],
    ["empty", [], {}, [], { opening_media_ids: [], steps_media: {} }],
    ["teaser over count clamps; unknown + empty steps omitted; slot order",
      [3, 1], { "5": { ids: [9, 8], previewCount: 5 }, "1": { ids: [4], previewCount: 0 },
        "3": { ids: [], previewCount: 2 }, "7": { ids: [6], previewCount: 1 } }, [5, 3, 1],
      { opening_media_ids: [3, 1], steps_media: {
        "5": { media_files: [9, 8], previews: [9, 8] },
        "1": { media_files: [4], previews: [] },
      } }],
  ])("%s", (_name, opener, steps, stepNos, want) => {
    expect(JSON.stringify(buildPayload(opener, steps, stepNos))).toBe(JSON.stringify(want));
  });
});
